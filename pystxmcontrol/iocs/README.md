# pystxmcontrol IOC Layer

The caproto IOC layer wraps pystxmcontrol's hardware drivers in EPICS motor records and fly-control PVs. The architecture offloads the time-critical line-scanning loop (velocity profiling, DAQ synchronization) from the remote Python server to the IOC process running on the beamline control machine, keeping EPICS as the control and reporting plane. This eliminates network round-trip latency on per-point updates and improves fly-line turnaround time.

## Install

```bash
pip install pystxmcontrol[iocs]
```

## Quick Start

```bash
stxm-iocs --station 7011
```

By default, the supervisor reads `motor.json` and `daq.json` from the installed pystxmcontrol package's `config/` directory. Override with `--motor-config` and `--daq-config`. For simulation mode without hardware, use `--station SIM` (the default).

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--station` | `SIM` | Station ID (e.g., `7011`); used to prefix all PV names `STXM{station}:{...}`. |
| `--motor-config` | `config/motor.json` | Path to motor configuration JSON. |
| `--daq-config` | `config/daq.json` | Path to DAQ configuration JSON. |
| `--slice-dir` | temp directory | Directory to store per-IOC slice JSON files; defaults to a temp directory. |
| `--no-shutter-iocs` | not set | Disable shutter/gate IOC startup; useful for hardware where legacy servers manage shutters. |
| `--status-interval` | `10.0` | Period (seconds) to print IOC status table; pass `0` to disable. |
| `--startup-delay` | `3.0` | Delay (seconds) before starting derived IOCs, allowing primary IOCs to become network-accessible. |

## PV Surface

Each controller generates one IOC process. Motors expose standard EPICS motor-record fields; E712 controllers additionally host a FLY group with waveform and line-control PVs.

**Enum PV write gotcha:** CA clients cannot write enum PVs (`:MODE`, `:AXIS`, shutter `:MODE`, etc.) as bare native strings via caproto's threading client. Write by integer index, or write the string with `data_type=ChannelType.STRING` explicitly. Server-side putters receive the enum string in either case.

### Motor Record Fields

Per-motor PVs are named `STXM{station}:{controller}:{axis}.*` and expose the full motor-record interface:

| Field | R/W | Meaning |
|-------|-----|---------|
| `:VAL` | RW | **Target position.** Write triggers a blocking move; put-completion (`caput -c`) waits for the move to complete (DMOV=1). HLM/LLM limits are enforced in the IOC. |
| `:RBV` | RO | **Readback position** from the hardware. Updated by polling (idle: 0.1 s, moving: 0.02 s). |
| `:DMOV` | RO | **Done moving.** 1 when at target, 0 while moving. |
| `:MOVN` | RO | **Motor is moving.** 1 while a move is in progress, 0 when idle. |
| `:STOP` | RW | **Stop motion.** Write 1 to abort the current move (if the driver supports it). |
| `:HLM` | RO | **High limit** (user_high_limit), loaded from motor.json `maxValue`. |
| `:LLM` | RO | **Low limit** (user_low_limit), loaded from motor.json `minValue`. |
| `:EGU` | RO | **Engineering units** string (e.g., `um`, `deg`); defaults to `um`, overridable via motor.json's `"epics": {"egu": "..."}`. |
| `:VELO` | RW | **Velocity** (user_velocity); write to change scan speed (if the driver's `setAxisParams` supports it). |

### FLY Group (E712 IOCs Only)

When an E712 controller is present, the supervisor creates one E712 IOC with a FLY PVGroup at `STXM{station}:{E712_label}:FLY`. The FLY group runs the IOC-side line loop and synchronizes DAQ acquisition.

| PV | R/W | Semantics |
|----|-----|-----------|
| `:START` | RW | **Start position** for the fly line (physical coordinates in motor units). |
| `:STOP` | RW | **Stop position** for the fly line. |
| `:NPOINTS` | RW | **Number of points** in the line (1 to MAX_LINE=16384). Must be set before ARM. |
| `:DWELL` | RW | **Dwell per point** (milliseconds). Must be > 0. |
| `:AXIS` | RW | **Axis enum** (selects which motor to fly). Choices depend on controller axes; default is the first axis. |
| `:MODE` | RW | **Fly mode:** `raster` (line repeats at START, moves to STOP, returns to START) or `continuous` (no turnaround, next line starts immediately at STOP position). |
| `:ARM` | RW | **Arm the IOC** for a line. Write 1 to validate START/STOP/NPOINTS/DWELL and enter ARMED state. If state is FLYING, the ARM is rejected: `:ERROR` is set to `"ARM while FLYING rejected"` and `:STATE` is left unchanged. |
| `:GO` | RW | **Start a fly line.** Write 1 only when state is ARMED. Blocks until the line completes or ABORT is triggered. |
| `:ABORT` | RW | **Abort the current fly line.** Write 1 to stop the IOC-side motor and DAQ at the next sampling point. |
| `:STATE` | RO | **IOC state:** `IDLE`, `ARMED`, `FLYING`, or `ERROR`. Read-only; only ARM, GO, and ABORT change it. |
| `:ERROR` | RO | **Error message** (up to 256 chars) if state is ERROR. |
| `:POS` | RO | **Position waveform** (read-only). The actual motor positions for the most recent completed line (length = NPOINTS). |
| `:INDEX` | RO | **Line index.** Increments by 1 after each completed line. **Consistency contract:** clients MUST monitor `:INDEX`; when it increments, all `:DATA:*` and `:POS` waveforms for that line are already written in full. |
| `:DATA:{key}` | RO | **DAQ waveform** for detector `key` (one per DAQ). Read-only; updated by the FLY loop each line. Data is only valid after `:INDEX` increments. |

### Fly-Capable Controllers

The following controllers are supported for continuous fly-line scanning:

- `e712Controller` (Physik Instrumente E-712): trigger-synchronized fly lines.
  The counter is configured `count=1, samples=n` and acquires the whole line
  off a SINGLE hardware line-start trigger from the E712
  (`line_trigger = "EXT"`, hardware-timed, low-latency).

- `nptController` (nPoint LC400 piezo controller, pylibftdi/USB): fly lines
  with a hardware line-start trigger output; `line_trigger` stays `"EXT"`
  (same single line-start trigger contract as the E712).

- `mmcController` (Micronix MMC): constant-velocity software-timed fly lines.
  The MMC has no trigger output, so `mmcMotor.line_trigger = "IMM"`
  (free-run) makes the DAQ free-run during the line; the fly loop
  pre-positions the axis before arming so acquisition starts at the line
  start (start-skew of a few ms; positions are nominal `linspace`).
  Transport is serial (`COM*`/`/dev/tty*`, 38400 8N1) or TCP (`address` +
  nonzero `port`), chosen from the address format.

### DAQ Group (Keysight Counter Family)

Standalone DAQ IOCs (if no E712 group exists) expose a DaqGroup at `STXM{station}:DAQ_{daq_key}.*`:

| PV | R/W | Semantics |
|----|-----|-----------|
| `:DWELL` | RW | **Dwell per point** (milliseconds, 3 decimal places). |
| `:MODE` | RW | **Acquisition mode:** `point` (single-point acquire) or `line` (internal to FLY loop; not used in DAQ IOC standalone). |
| `:ACQUIRE` | RW | **Single-point acquire.** Write 1 to acquire one point; put-completion waits for acquisition to finish. Updates `:COUNTS` and `:RATE`. |
| `:COUNTS` | RO | **Last acquired count value.** Updated after every point. |
| `:COUNTS:WF` | RO | **Counts waveform.** Updated only by the FLY loop's `write_line` (in-process); point-mode `:ACQUIRE` does not touch it. |
| `:RATE` | RO | **Count rate** (counts/second), computed as `COUNTS / (DWELL_ms / 1000)`. |

### Shutter/Gate Group

If `--no-shutter-iocs` is not set, each shutter in the configuration generates a ShutterGroup at `STXM{station}:{shutter_key}.*`:

| PV | R/W | Semantics |
|----|-----|-----------|
| `:MODE` | RW | **Shutter mode enum:** `OPEN`, `CLOSED`, or `AUTO`. Controls the beam state. |
| `:STATE` | RO | **Actual state:** `OPEN` or `CLOSED`. Polled from hardware every 0.5 s. |

## Naming Conventions

### Standard PV Names

PVs follow the pattern `STXM{station}:{controller}:{axis_or_key}`. For example:
- Motor: `STXM7011:E712:x.VAL`
- E712 FLY: `STXM7011:E712:FLY:GO` 
- DAQ: `STXM7011:DAQ_I0:ACQUIRE`
- Shutter: `STXM7011:SHUTTER_PV:MODE`

### Per-Entry Overrides

The standard name can be overridden on a per-entry basis in motor.json or daq.json by adding an `"epics"` sub-dictionary:

```json
{
  "motor1": {
    "driver": "xpsController",
    ...
    "epics": {"pv": "MY_CUSTOM:PREFIX"}
  }
}
```

If `"epics": {"pv": "..."}` is set, the custom PV name is used instead of the auto-generated one.

**Important:** motor.json and daq.json are the single source of truth for the hardware configuration and are never modified by the IOC layer. Any PV name changes are read-only from the JSON files' perspective.

## Coexistence and Migration

The IOC layer can run alongside a legacy pystxmcontrol scan server. To migrate:

1. **Configure motor.json:** Add or modify motor entries that you want to move to EPICS. For motors already controlled by an IOC, change the `"driver"` to `"epicsMotor"` and set `"address"` to the IOC's PV name (e.g., `"STXM7011:E712:x"`):

   ```json
   {
     "x": {
       "driver": "epicsMotor",
       "address": "STXM7011:E712:x",
       ...
     }
   }
   ```

2. **Hardware Single-Ownership:** An IOC and the legacy server must NOT share a serial port to the same controller. If both try to move the same axis, command conflicts will occur and may damage hardware.

3. **Shutter Management:** If the legacy server manages shutters, use `--no-shutter-iocs` to prevent the new IOC layer from also trying to control them.

4. **Parallel Operation:** The IOC layer can manage new controllers while the legacy server continues with others, provided serial ports do not overlap.

## Derived Motors

Derived motors (e.g., goniometer/piezo combinations) can be **co-located** in the same IOC as their underlying motors, or **cross-controller**, where the derived motor pulls underlying-motor positions via Channel Access.

### Co-Located Derived Motors

If derived motors are wired entirely within one IOC (all underlying motors in the same controller), they are automatically instantiated alongside the primary motors. No special configuration beyond motor.json is needed; the IOC supervisor handles this internally.

### Cross-Controller Derived Motors

If a derived motor's underlying axes span multiple IOCs (or are remote), the supervisor starts a separate **derived IOC** after a startup delay (default 3 seconds) to allow primary IOCs to become network-accessible. These use `CAMotorProxy` internally to pull positions via EPICS motor-record PVs:

- The derived IOC reads `:VAL`, `:RBV`, `:MOVN`, `:STOP`, `:HLM`, `:LLM`, `:VELO` from the underlying motors.
- Derived motors wired via CA MUST have `"simulation": 0` in motor.json (CA cannot talk to simulated motors in other IOCs).
- Cross-IOC composition uses `wait=True` on underlying :VAL writes, so the MotorRecordGroup's put-completion semantics are preserved (caput -c returns when the derived axis reaches target).

## Testing

The IOC layer ships with test suites for each module under `tests/iocs/`. Run from the repository root, with `PYTHONPATH` set to the repo root and an interpreter from a virtual environment that has caproto and ophyd installed:

```bash
PYTHONPATH=. python -m pytest tests/iocs -v
```

### Environment Setup

For long fly lines (NPOINTS > 1000), increase the EPICS CA array-size limit:

```bash
export EPICS_CA_MAX_ARRAY_BYTES=1000000
```

This allows waveforms up to 16384 points to be read and written over Channel Access without truncation.

## Known Limitations

- **Interface binding:** every IOC main (`motor_ioc.py`, `derived_ioc.py`, `e712_ioc.py`, `daq_ioc.py`, `shutter_ioc.py`) and the supervisor's own status server bind all interfaces (no `interfaces=[...]` restriction), so they are reachable from other hosts as required at a real beamline. CA reachability for a given deployment is governed by the EPICS environment (`EPICS_CA_ADDR_LIST`, `EPICS_CA_AUTO_ADDR_LIST`) and each IOC's assigned port (see the per-IOC CA server ports note below), not by interface binding.
- **Per-IOC CA server ports (Windows deployment):** on Windows, only one of the ~10 IOC subprocesses spawned by `stxm-iocs` actually receives UDP CA search broadcasts when they all default to port 5064 -- verified empirically (setting `EPICS_CA_ADDR_LIST=127.0.0.1` or `127.255.255.255` did not fix it). `Supervisor` therefore allocates a distinct free UDP port per IOC plan (once per `Supervisor` instance, stable across restarts of a crashed IOC so clients reconnect to the same address) and sets, per child: `EPICS_CAS_SERVER_PORT=<its port>` AND `EPICS_CA_SERVER_PORT=<its port>` (this caproto version's server actually binds using `EPICS_CA_SERVER_PORT` -- see `caproto/server/common.py Context.__init__` -- despite `EPICS_CAS_SERVER_PORT` existing as a distinct, spec-correct env var name; both are set for forward-compat), and the full fleet's `EPICS_CA_ADDR_LIST="127.0.0.1:<p1> 127.0.0.1:<p2> ..."` with `EPICS_CA_AUTO_ADDR_LIST=NO` -- every child needs the whole list because derived IOCs are CA clients of the motor IOCs. The supervisor's own status server (`STXM<station>:SUP:...`) keeps the *default* CA port, so `caget`/`caput` against it work with no special client-side env. The resulting address list is printed at startup and written to `<slice-dir>/EPICS_CA_ADDR_LIST.txt` -- source that file's contents into `EPICS_CA_ADDR_LIST` (with `EPICS_CA_AUTO_ADDR_LIST=NO`) for any external client (e.g. a scan client on the same host) that needs to reach the individual motor/daq/shutter/derived PVs. Pass `--host` to change the address used in the list (default `127.0.0.1`). On Linux hosts where UDP broadcast search reliably reaches every subprocess, pass `--shared-ca-port` to disable this mechanism and restore the prior shared-port-5064 behavior.

## What's Not Included (v1)

- **PV gateway / redundancy:** No automatic failover or secondary IOCs.
- **Scan module integration:** The IOC layer exposes PVs; higher-level scan loops (Plan-based, bluesky, etc.) are implemented separately.
- **Real-time trajectory upload:** The FLY loop's velocity profile is computed once per line in Python; future versions may pre-compute or upload canned trajectories.
- **Cross-beamline federation:** Each station is independent; multi-beamline scans are orchestrated by external tools.

## Hardware Benchmark

A performance comparison (IOC path vs. native pystxmcontrol server) is available in `pystxmcontrol/iocs/benchmark.py`. This stub requires beamline time and hardware (E712 + Keysight DAQ) to validate that the IOC-side line loop introduces <2% overhead per line turnaround. See the module docstring for usage.

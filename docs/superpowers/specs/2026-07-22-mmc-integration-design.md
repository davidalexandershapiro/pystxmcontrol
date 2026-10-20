# Micronix MMC integration — design

Date: 2026-07-22. Branch: `feature/caproto-iocs`. Hardware integration test: Friday 2026-07-24.

## Goal

Bring the Micronix MMC controller up to full parity with the XPS/nPoint work:
point-to-point motion through the generic `motor_ioc`, plus fly-scan lines
through the controller-agnostic `fly_ioc`. Local-first pass with simulation +
fake-transport tests; hardware validation Friday.

## Background

- The IOC layer is generic: `iocs/base.py` `build_controller`/`build_motor`
  instantiate any driver pair from `pystxmcontrol.drivers` by name;
  `MotorRecordGroup` provides the caproto motor record.
- Drivers are **lock-agnostic**: all link serialization happens at the IOC
  layer via one shared `io_lock` per controller (see
  `test_controller_serialization.py`). Drivers must not take their own locks.
- `fly_ioc.py` serves any controller in `config.FLY_CAPABLE_CONTROLLERS`,
  driving the selected motor through the duck-typed fly interface:
  `trajectory_pixel_count`, `trajectory_pixel_dwell`, `trajectory_start`,
  `trajectory_stop`, `lineMode`, `update_trajectory()`, `moveLine()`,
  optional `positions`.
- Legacy `mmcController`/`mmcMotor` are inadequate: no transaction layer,
  `int(pos)` truncation, hardcoded 1 s move timeout, no `stop()`, no
  `SoftwareLimitError`, no working simulation mode, driver-internal locking.

## MMC protocol facts (from legacy driver usage)

ASCII commands prefixed by the 1-based axis number, terminated `\r`:
`nMVA<pos>` (move absolute), `nPOS?` (reads `#<theoretical>,<encoder>`),
`nSTA?` (status byte; idle values historically `8`/`136`), `nVEL<v>`/`nVEL?`,
`nFBK3`/`nFBK0` (closed/open loop), `nHOM`, `nHCG<dir>`, `nSTP` (stop),
`nERR?` (error queue). Query responses begin with `#`. Serial: 38400 8N1.

## Components

### 1. `drivers/mmcController.py` (rewrite)

- `mmcController(hardwareController)` with `__init__(address, port=None,
  simulation=False)` and `initialize(simulation=False)`.
- **Pluggable transport, chosen in `initialize()`**:
  - serial (default): address looks like `COM*` or `/dev/tty*` → pyserial,
    38400 8N1, 1 s read timeout.
  - TCP: otherwise → `socket` to `(address, port)` with makefile-style
    line reads, same 1 s timeout. (Friday's hookup is not yet known.)
- Transaction API used by the motor (encode/terminate/parse in ONE place):
  - `command(axis, cmd)` — write `f"{axis}{cmd}\r"`, no reply expected.
  - `query(axis, cmd)` — write, readline, strip `#`, return payload string.
    Raises `MMCError` (subclass `IOError`) on empty/garbled response rather
    than crashing on `float('')` — the IOC layer already survives driver
    exceptions per poll/move.
  - `get_error(axis)` — drain `nERR?` and return the message list (used for
    logging after failed transactions; never raises).
- No locking inside the driver (IOC `io_lock` owns serialization).
- Simulation mode: no I/O; per-axis position dict + velocity dict so
  multiple motors on one simulated controller behave independently.

### 2. `drivers/mmcMotor.py` (rewrite)

Point-to-point interface (what `MotorRecordGroup` drives):

- `connect(axis=, **kwargs)` — maps `x/y/z` → axis number 1/2/3 (respect
  `config["controller_index"]` override like `mcsMotor`), inherits
  `controller.simulation`, enables closed loop (`FBK3`).
- `checkLimits(pos)` — raises `SoftwareLimitError` (message pattern of
  `xpsMotor`), not a silent log.
- `moveTo(pos)` — float positions rounded to 3 decimals in **controller
  units** after offset/units transform (no `int()` truncation); issues
  `MVA`; polls `getStatus()` until idle or `config.get("timeout", 10)`
  seconds elapse; on timeout issues `STP` and raises `MMCError`.
- `getPos()` — `POS?`, encoder (second) field, `* units + offset`.
- `getStatus()` — `STA?`, decode the moving bit from the status byte
  (bit 3 / value 8 family observed as idle historically; decode by bit
  mask, not string membership, and confirm against hardware Friday).
- `stop()` — `STP`.
- `setAxisParams(velocity=)` / `get_velocity()` — `VEL`.
- `home()`, `configure_home(direction)`, `setServo(bool)` — kept.
- Simulation: positions/velocity delegated to the controller's sim dicts.

Fly interface (what `fly_ioc._run_line` drives):

- `trajectory_pixel_count`, `trajectory_pixel_dwell` (ms),
  `trajectory_start`, `trajectory_stop` (2-tuples; fast axis inferred from
  whichever slot differs), `lineMode` attributes.
- `update_trajectory()` — pick the varying slot as the fast-axis span;
  compute `line_velocity = |x1 - x0| / (n * dwell_ms / 1000)` in controller
  units; clamp to `config.get("max velocity")` when present (raise
  `MMCError` if the line is un-flyable at max velocity rather than silently
  stretching dwell).
- `moveLine()` — sequence: move to start (`moveTo`), set `VEL` to
  `line_velocity`, `MVA` to stop position, poll status until idle with a
  deadline of 4× nominal line time + slack (mirrors fly_ioc's own guard),
  then restore the cruise velocity. Blocking; runs inside fly_ioc's
  executor thread under `io_lock`.
- No `positions` attribute → `fly_ioc` publishes `np.linspace(x0, x1, n)`,
  correct for a stage with no position capture.

### 3. DAQ triggering for MMC lines (default: internal timing)

`fly_ioc._hw_line` currently hardcodes `daq.config(..., trigger="EXT")` +
`daq.initLine()`, relying on the motor to emit a line-start trigger. The MMC
has no trigger output. **Chosen default (Ron): software-timed lines.**

- Motor drivers gain an optional class attribute `line_trigger`
  (default `"EXT"` — preserves current npt/E712 behavior when absent).
  `mmcMotor.line_trigger = "IMM"` — "IMM (free-run)" is the 53230A
  `TRIG:SOUR` mnemonic (the instrument accepts IMM|EXT|BUS; "INT" would
  queue an SCPI error).
- `fly_ioc._hw_line` reads `getattr(motor, "line_trigger", "EXT")` and
  passes it to `daq.config`; for `"IMM"` (any non-EXT value), `initLine`
  (INIT:IMM) starts acquisition immediately, so the trajectory setup and
  pre-positioning (move to line start, set line velocity — driver
  `prepareLine()`) run in a dedicated "prepare" stage BEFORE the arm;
  the "move" stage then only commands the constant-velocity move
  (`moveLine()` on a prepared axis). Accepted start-skew: a few ms —
  nominal positions are already the contract for this class of axis.
- If Friday shows an external gate is available, flipping the config back to
  `"EXT"` per-axis is a one-line change.

### 4. `iocs/config.py`

Add `"mmcController"` to `FLY_CAPABLE_CONTROLLERS` so `supervisor.plan_fleet`
routes MMC controller groups to the fly IOC (motor records still served
there; groups without DAQs simply get no FLY PVGroup).

### 5. Tests (mirror the npt suite)

- **Fake transport** (`tests/iocs/fake_mmc.py` or fixture): scripted
  object with `write()`/`readline()` recording writes and replaying canned
  `#...` responses; injected in place of the serial/TCP transport.
- Driver unit tests: command formatting (axis prefix, `\r`, 3-decimal
  rounding), `POS?` parse, status-bit decode, limit → `SoftwareLimitError`,
  move-timeout → `STP` + `MMCError`, garbled-response → `MMCError` (framing
  test analogous to `test_npt_read_framing.py`).
- `update_trajectory` math: velocity from span/dwell/count, max-velocity
  clamp behavior.
- IOC-level (simulation over real CA, patterned on `test_npt_fly.py`):
  MMC slice → motor record moves + RBV; fly line ARM/GO in simulation;
  `line_trigger="IMM"` selection in the fly path exercised with a stubbed
  DAQ.

## Error handling summary

Driver raises typed `MMCError`/`SoftwareLimitError`; never `print`-and-hang.
IOC layer already: survives poll exceptions, releases put-completion in
`finally`, surfaces fly exceptions on `:ERROR`. Timeouts always attempt
`STP` before raising.

## Out of scope

- Hardware position capture / measured fly positions (MMC has none).
- 2D trajectories (MMC lines are single-axis constant-velocity).
- Changing npt/E712 behavior (`line_trigger` defaults preserve it).

## Open items for Friday (hardware)

- Confirm idle status-byte values / moving-bit mask on the real firmware.
- Measure move latency + settle; tune `moving_poll`/timeout slack.
- Confirm transport (USB serial vs Ethernet) and port name.
- Decide whether an external gate exists worth switching to `"EXT"`.

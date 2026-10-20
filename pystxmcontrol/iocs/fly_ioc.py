"""Controller-agnostic fly IOC: motor records + FLY PVGroup with an IOC-side
line loop.

Serves any fly-capable controller group (see config.FLY_CAPABLE_CONTROLLERS,
e.g. E712Controller, nptController) -- the line loop is controller-agnostic and
drives the selected axis motor through the duck-typed fly interface
(trajectory_* attrs + update_trajectory/moveLine + continuous lineMode).

Historically this lived in a module named ``e712_ioc``; the logic is not
specific to the E712, so it now lives here under a controller-neutral name.
``pystxmcontrol.iocs.e712_ioc`` remains as a thin back-compat shim that
re-exports everything defined here.

Consistency contract: on each completed line, ALL data/pos waveforms are
written BEFORE :INDEX increments. Clients monitor :INDEX, then read waveforms.
"""
from __future__ import annotations

import argparse
import asyncio
import functools

import numpy as np

from pystxmcontrol.iocs import configure_ioc_logging, require_caproto

require_caproto()

from caproto import ChannelType  # noqa: E402
from caproto.server import PVGroup, pvproperty, run  # noqa: E402

from pystxmcontrol.iocs.config import read_slice  # noqa: E402
from pystxmcontrol.iocs.daq_ioc import MAX_LINE, build_pvdb_for_entry  # noqa: E402

STATES = ["IDLE", "ARMED", "FLYING", "ERROR"]


def _enum_index(prop) -> int:
    """Normalize a caproto enum pvproperty's current value to its index.

    Different caproto versions store the ChannelData value as either the
    int index or the string label -- accept both.
    """
    v = prop.value
    if isinstance(v, str):
        return prop.enum_strings.index(v)
    return int(v)


def _fly_group_class(axis_labels: list, daq_keys: list):
    """Build the FLY PVGroup class with per-DAQ DATA waveforms baked into the
    class namespace up front (not via setattr afterwards) -- caproto's
    PVGroupMeta collects pvproperty attributes at class-creation time, so any
    dynamic per-fleet PVs must already be present when the class object is
    created via ``type()``.
    """

    start = pvproperty(value=0.0, name=":START")
    stop = pvproperty(value=0.0, name=":STOP")
    npoints = pvproperty(value=10, name=":NPOINTS")
    dwell = pvproperty(value=1.0, name=":DWELL", doc="ms per point")
    axis = pvproperty(value=axis_labels[0], enum_strings=list(axis_labels),
                       dtype=ChannelType.ENUM, name=":AXIS")
    fly_mode = pvproperty(value="raster", enum_strings=["raster", "continuous"],
                          dtype=ChannelType.ENUM, name=":MODE")
    arm = pvproperty(value=0, name=":ARM")
    go = pvproperty(value=0, name=":GO")
    abort = pvproperty(value=0, name=":ABORT")
    state = pvproperty(value="IDLE", enum_strings=list(STATES),
                       dtype=ChannelType.ENUM, name=":STATE", read_only=True)
    error = pvproperty(value="", name=":ERROR", read_only=True,
                       dtype=ChannelType.CHAR, max_length=256,
                       report_as_string=True)
    pos = pvproperty(value=[0.0], name=":POS", read_only=True, max_length=MAX_LINE)
    index = pvproperty(value=0, name=":INDEX", read_only=True)

    data_props = {
        key: pvproperty(value=[0.0], name=f":DATA:{key}", read_only=True,
                        max_length=MAX_LINE)
        for key in daq_keys
    }

    @arm.putter
    async def arm(self, instance, value):
        if not value:
            return 0
        if STATES[_enum_index(self.state)] == "FLYING":
            # Do NOT touch STATE or the abort event: a racing ABORT must
            # still be able to interrupt the in-flight line.
            await self.error.write("ARM while FLYING rejected")
            return 0
        n = int(self.npoints.value)
        motor = self._current_motor()
        cfg = motor.config
        lo, hi = cfg["minValue"], cfg["maxValue"]
        problems = []
        if not (1 <= n <= MAX_LINE):
            problems.append(f"NPOINTS {n} outside 1..{MAX_LINE}")
        for label, v in (("START", self.start.value), ("STOP", self.stop.value)):
            if not (lo <= v <= hi):
                problems.append(f"{label} {v} outside limits [{lo}, {hi}]")
        if self.dwell.value <= 0:
            problems.append(f"DWELL {self.dwell.value} must be > 0")
        if problems:
            await self._set_state("ERROR", "; ".join(problems)[:255])
        else:
            self._abort_event.clear()
            await self._set_state("ARMED")
        return 0

    @go.putter
    async def go(self, instance, value):
        if not value:
            return 0
        current = STATES[_enum_index(self.state)]
        if current != "ARMED":
            if current == "FLYING":
                # Do NOT touch STATE or the abort event: a racing GO must not
                # clobber a healthy in-flight line's STATE with ERROR (mirrors
                # the ARM-while-FLYING rejection above).
                await self.error.write("GO rejected: line in progress")
            else:
                await self._set_state("ERROR", f"GO rejected: state is {current}")
            return 0
        # Synchronous guard closing the check-then-act race: two concurrent
        # GO puts could both observe ARMED before either flips STATE, and
        # both proceed to _fly_one_line(). This flag is set before the first
        # await so the second putter's check below is atomic with respect to
        # the first (no await happens between the state check and this set).
        if self._flying:
            await self.error.write("GO rejected: line in progress")
            return 0
        self._flying = True
        try:
            await self._set_state("FLYING")
            try:
                aborted = await self._fly_one_line()
            except Exception as exc:  # noqa: BLE001 - surfaced on :ERROR
                await self._set_state("ERROR", str(exc)[:255])
                return 0
            if aborted:
                await self._set_state("IDLE")
            else:
                await self._set_state("ARMED")
        finally:
            self._flying = False
        return 0

    @abort.putter
    async def abort(self, instance, value):
        if value:
            self._abort_event.set()
        return 0

    def __init__(self, prefix, *, motors, daq_groups, simulation=True,
                 io_lock=None, shutter_pvs=None, **kwargs):
        PVGroup.__init__(self, prefix, **kwargs)
        self._motors = motors
        self._daq_groups = daq_groups
        self._simulation = simulation
        self._abort_event = asyncio.Event()
        self._flying = False
        self._data_props = {k: getattr(self, f"data_{k}") for k in daq_keys}
        # Shared with the motor records on the same controller so a fly line's
        # motor I/O never interleaves with the axes' RBV pollers on the link.
        import threading
        self._io_lock = io_lock if io_lock is not None else threading.Lock()
        # Beam-shutter MODE PVs (served by the dedicated shutter IOC) to open
        # for the beam during a line and close after. Commanded over Channel
        # Access -- the fly IOC must NOT open the Arduino directly (that
        # contends with the shutter IOC). Empty -> no beam gating.
        self._shutter_pvs = list(shutter_pvs or [])
        self._ca_ctx = None

    def _command_shutters(self, mode):
        """Best-effort CA write of ``<shutter>:MODE`` for every beam shutter
        tied to this controller's DAQs. Runs in an executor thread and NEVER
        raises into the fly loop -- a shutter that won't respond must not fail
        the line (worst case: dark counts). ``mode`` is "OPEN"/"CLOSED"/"AUTO".
        """
        if not self._shutter_pvs:
            return
        try:
            from caproto.threading.client import Context
        except Exception:  # noqa: BLE001 - CA client unavailable
            return
        if self._ca_ctx is None:
            self._ca_ctx = Context()
        for prefix in self._shutter_pvs:
            try:
                (pv,) = self._ca_ctx.get_pvs(f"{prefix}:MODE")
                pv.wait_for_connection(timeout=1.0)
                pv.write(mode, wait=True, timeout=1.0)
            except Exception:  # noqa: BLE001 - best-effort, per-shutter
                pass

    async def _set_state(self, name, error_msg=""):
        await self.state.write(name)
        await self.error.write(error_msg)

    def _current_motor(self):
        label = self.axis.enum_strings[_enum_index(self.axis)]
        return self._motors[label]

    async def _fly_one_line(self) -> bool:
        loop = asyncio.get_running_loop()
        n = int(self.npoints.value)
        dwell = float(self.dwell.value)
        x0, x1 = float(self.start.value), float(self.stop.value)

        lines = {}
        for key, group in self._daq_groups.items():
            if self._abort_event.is_set():
                return True
            daq = group._daq
            if self._simulation:
                await group._ensure_started()
                await loop.run_in_executor(
                    None, functools.partial(daq.config, dwell, count=n, samples=1))
                get_task = asyncio.ensure_future(daq.getLine())
                while not get_task.done():
                    if self._abort_event.is_set():
                        get_task.cancel()
                        try:
                            await get_task
                        except asyncio.CancelledError:
                            pass
                        return True
                    await asyncio.sleep(0.02)
                lines[key] = get_task.result()
            else:  # pragma: no cover - hardware path (see benchmark.py)
                motor = self._current_motor()
                axis_label = self.axis.enum_strings[_enum_index(self.axis)]
                other_label = "x" if axis_label == "y" else "y"
                other_motor = self._motors.get(other_label)
                # Beam gating: the DAQ's direct Arduino gate is disabled in the
                # fleet (see build_pvdb_from_slice), so the beam shutter is
                # opened/closed via the dedicated shutter IOC over CA
                # (self._command_shutters) around the line. The counter's
                # totalize is internally timed off the EXT trigger, so the
                # shutter only decides real counts vs. darks -- it never affects
                # line completion.

                def _setup_trajectory():
                    # Caller must hold self._io_lock.
                    # Hold the perpendicular axis at its current position;
                    # 2D (x, y) trajectory drivers (e.g. nptMotor) infer
                    # the fast axis from whichever slot varies.
                    perp = (other_motor.getPos()
                            if other_motor is not None
                            and hasattr(other_motor, "getPos") else 0.0)
                    motor.trajectory_pixel_count = n
                    motor.trajectory_pixel_dwell = dwell
                    motor.lineMode = "continuous"
                    if axis_label == "y":
                        motor.trajectory_start = (perp, x0)
                        motor.trajectory_stop = (perp, x1)
                    else:
                        motor.trajectory_start = (x0, perp)
                        motor.trajectory_stop = (x1, perp)
                    motor.update_trajectory()

                def _run_line():
                    # All motor-side I/O for the line runs here, in one worker
                    # thread holding the controller lock, so it never
                    # interleaves with the axes' RBV pollers (or the other
                    # axis) on the shared link. Drivers stay lock-agnostic, so
                    # calling their methods under the lock can't self-deadlock.
                    with self._io_lock:
                        _setup_trajectory()
                        motor.moveLine()

                def _prepare_line():
                    # Free-run (non-EXT) trigger path only: trajectory setup
                    # + pre-positioning (move to line start, set line
                    # velocity) BEFORE the DAQ is armed, since initLine
                    # starts acquisition immediately for an IMM trigger.
                    with self._io_lock:
                        _setup_trajectory()
                        motor.prepareLine()

                def _run_prepared_line():
                    # Free-run path: only the constant-velocity move remains.
                    with self._io_lock:
                        motor.moveLine()

                async def _close_beam():
                    # Best-effort beam-shutter close; never raises into the
                    # abort/timeout path (a stuck shutter must not fail teardown).
                    await loop.run_in_executor(None, self._command_shutters, "CLOSED")

                # Records the step currently in flight so a timeout reports
                # WHERE it stalled (connect/config/arm/beam_open/move/read) --
                # the IOC's stdout is not visible to clients, but this string
                # rides out on the flyer's ERROR/exception, which the engine logs.
                stage = {"name": "queued"}

                async def _hw_line():
                    # Mirror doFlyscanLine's per-line sequence: connect -> config
                    # (EXT, count=1/samples=n for the beamline's "line" trigger
                    # mode) -> arm counter -> OPEN beam (shutter IOC via CA) ->
                    # drive the line (the motor emits the single line-start
                    # trigger and blocks for the line duration) -> CLOSE beam ->
                    # fetch the counts. ALL of it runs inside the deadline/abort
                    # guard below, so a stall in any step surfaces as ERROR
                    # instead of wedging the IOC in FLYING.
                    stage["name"] = "connect"
                    await group._ensure_started()
                    stage["name"] = "config"
                    # Trigger source is a driver capability: motors with no
                    # hardware trigger output (e.g. MMC) declare
                    # line_trigger = "IMM" (53230A immediate/free-run
                    # trigger) and the DAQ free-runs during the line; absent
                    # attribute keeps the EXT line-start trigger contract
                    # (nPoint, E712).
                    line_trigger = getattr(motor, "line_trigger", "EXT")
                    await loop.run_in_executor(None, functools.partial(
                        daq.config, dwell, count=1, samples=n,
                        trigger=line_trigger))
                    if line_trigger != "EXT":
                        # Free-run: initLine (INIT:IMM) starts acquisition
                        # immediately, so all pre-positioning (move to line
                        # start, set line velocity) must happen BEFORE the
                        # arm. Runs inside this task so the caller's
                        # deadline/abort guard covers a stall here too.
                        stage["name"] = "prepare"
                        await loop.run_in_executor(None, _prepare_line)
                    stage["name"] = "arm"
                    await loop.run_in_executor(None, daq.initLine)
                    stage["name"] = "beam_open"
                    await loop.run_in_executor(None, self._command_shutters, "OPEN")
                    try:
                        stage["name"] = "move"
                        await loop.run_in_executor(
                            None,
                            _run_prepared_line if line_trigger != "EXT"
                            else _run_line)
                    finally:
                        await _close_beam()
                    stage["name"] = "read"
                    result = await daq.getLine()
                    stage["name"] = "done"
                    return result

                fly_task = asyncio.ensure_future(_hw_line())
                # Nominal line time is dwell*n ms; allow 4x plus 5 s of
                # move/settle/return slack before declaring the line stalled.
                deadline = loop.time() + max(5.0, (dwell * n) / 1000.0 * 4.0 + 5.0)
                while not fly_task.done():
                    if self._abort_event.is_set():
                        fly_task.cancel()
                        try:
                            await fly_task
                        except BaseException:  # noqa: BLE001 - best-effort teardown
                            pass
                        await _close_beam()  # cancel may skip _hw_line's finally
                        return True
                    if loop.time() > deadline:
                        fly_task.cancel()
                        try:
                            await fly_task
                        except BaseException:  # noqa: BLE001 - best-effort teardown
                            pass
                        await _close_beam()  # cancel may skip _hw_line's finally
                        raise TimeoutError(
                            f"fly line stalled at step '{stage['name']}' "
                            f"(no completion within "
                            f"{max(5.0, (dwell * n) / 1000.0 * 4.0 + 5.0):.1f}s, "
                            f"dwell={dwell} ms, n={n}); check the counter "
                            "external trigger/gate and the motor line-start "
                            "position trigger")
                    await asyncio.sleep(0.02)
                lines[key] = fly_task.result()

        positions = np.linspace(x0, x1, n)
        if not self._simulation:  # pragma: no cover - hardware path
            motor = self._current_motor()
            if hasattr(motor, "positions"):
                positions = np.asarray(motor.positions)[:n]

        # ---- ordering contract: waveforms FIRST, then INDEX ----
        for key, line in lines.items():
            await self._data_props[key].write([float(v) for v in line])
            await self._daq_groups[key].write_line(line)
        await self.pos.write([float(v) for v in positions])
        await self.index.write(self.index.value + 1)
        return False

    namespace = {
        "start": start, "stop": stop, "npoints": npoints, "dwell": dwell,
        "axis": axis, "fly_mode": fly_mode, "arm": arm, "go": go,
        "abort": abort, "state": state, "error": error, "pos": pos,
        "index": index, "__init__": __init__, "_set_state": _set_state,
        "_current_motor": _current_motor, "_fly_one_line": _fly_one_line,
        "_command_shutters": _command_shutters,
    }
    for key, prop in data_props.items():
        namespace[f"data_{key}"] = prop

    return type("FlyGroup", (PVGroup,), namespace)


def FlyGroup(prefix, *, motors, daq_groups, simulation=True, io_lock=None,
             **kwargs):
    """Instantiate a FLY PVGroup wired to the given motors/DAQ groups.

    ``motors`` maps enum axis label -> driver; ``daq_groups`` maps a DAQ key
    -> an already-built ``daq_ioc.DaqGroup`` instance (co-hosted in the same
    IOC process, so the fly loop can call ``write_line`` on it directly).
    ``io_lock`` is the controller's shared transaction lock (see
    MotorRecordGroup); pass the same lock used for this controller's motor
    records so a fly line serializes with their RBV pollers.
    """
    cls = _fly_group_class(list(motors), list(daq_groups))
    return cls(prefix, motors=motors, daq_groups=daq_groups,
               simulation=simulation, io_lock=io_lock, **kwargs)


def build_pvdb_from_slice(s: dict) -> dict:
    from pystxmcontrol.iocs.config import FLY_CAPABLE_CONTROLLERS

    if not (s["kind"] == "controller"
            and s["controller_cls"] in FLY_CAPABLE_CONTROLLERS):
        raise ValueError(
            f"fly IOC requires kind=controller with a fly-capable controller_cls "
            f"({sorted(FLY_CAPABLE_CONTROLLERS)}), got kind={s['kind']!r} "
            f"controller_cls={s.get('controller_cls')!r}")
    from pystxmcontrol.iocs.base import MotorRecordGroup, build_controller, build_motor

    controller_dict = {
        "controller": s["controller_cls"],
        "address": s["controller_id"],
        "port": s["port"],
        "simulation": s["simulation"],
    }
    controller = build_controller(controller_dict)
    # One lock per controller, shared by every motor record AND the fly loop,
    # so no two blocking transactions overlap on the controller's link.
    import threading
    io_lock = threading.Lock()
    pvdb: dict = {}
    motors = {}
    for m in s["motors"]:
        drv = build_motor(m["entry"]["driver"], controller, m["entry"],
                          m["entry"]["axis"])
        motors[m["entry"]["axis"]] = drv
        pvdb.update(MotorRecordGroup(m["pv"], driver=drv,
                                     motor_config=m["entry"],
                                     io_lock=io_lock).pvdb)

    # gate address -> shutter :MODE PV prefix, written by supervisor from the
    # fleet's shutter IOCs. Lets the fly IOC drive the beam shutter over CA.
    shutters = s.get("shutters", {})
    shutter_pvs = []
    daq_groups = {}
    for d in s.get("daqs", []):
        entry = d["entry"]
        if entry.get("gate"):
            # In the IOC fleet the Arduino gate/shutter is owned by a dedicated
            # shutter IOC (supervisor.plan_fleet builds one per gate address).
            # The DAQ driver's own gate handling (keysight53230A.start ->
            # shutter(/dev/arduino)) is a monolithic-server artifact: letting
            # the fly IOC ALSO open the serial port contends with the shutter
            # IOC and hangs start() on a serial read. The counter's totalize is
            # internally timed off the EXT trigger and does not need this gate,
            # so disable the DAQ's direct gate handling here and instead command
            # the beam shutter via the shutter IOC's CA PV during the line.
            addr = entry.get("gate address")
            if addr and addr in shutters:
                shutter_pvs.append(shutters[addr])
            entry = dict(entry, gate=False)
        dq_pvdb, group = build_pvdb_for_entry(entry, d["prefix"])
        pvdb.update(dq_pvdb)
        daq_groups[d["key"]] = group
    shutter_pvs = sorted(set(shutter_pvs))

    if daq_groups:
        fly_prefix = f"STXM{s['station']}:{s['label']}:FLY"
        fly = FlyGroup(fly_prefix, motors=motors, daq_groups=daq_groups,
                       simulation=bool(s["simulation"]), io_lock=io_lock,
                       shutter_pvs=shutter_pvs)
        pvdb.update(fly.pvdb)
    return pvdb


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    configure_ioc_logging()
    run(build_pvdb_from_slice(read_slice(args.slice)), log_pv_names=not args.quiet)


if __name__ == "__main__":
    main()

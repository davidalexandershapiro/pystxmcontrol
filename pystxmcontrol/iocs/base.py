"""Driver-backed caproto motor record + driver construction helpers."""
from __future__ import annotations

import asyncio
import threading

from caproto.server import PVGroup, pvproperty

from pystxmcontrol.controller.motor import SoftwareLimitError


def build_controller(slice_or_group: dict):
    """Instantiate + initialize a controller class by name from pystxmcontrol.drivers.

    ``slice_or_group`` is expected to carry at least a ``controller`` key naming
    the class in ``pystxmcontrol.drivers``, plus whatever kwargs that class's
    constructor needs (address/port/etc). ``simulation`` (default True) is
    passed through to ``initialize``.
    """
    import pystxmcontrol.drivers as drv

    cls_name = slice_or_group["controller"]
    cls = getattr(drv, cls_name)
    kwargs = {k: v for k, v in slice_or_group.items()
              if k not in ("controller", "simulation", "motors")}
    ctrl = cls(**kwargs)
    ctrl.initialize(simulation=slice_or_group.get("simulation", True))
    return ctrl


def build_motor(driver_cls_name: str, controller, entry: dict, axis):
    """David's motor wiring (controller.py initialize), without eval."""
    import pystxmcontrol.drivers as drv
    m = getattr(drv, driver_cls_name)()
    m.controller = controller
    setattr(m, "config", entry)
    m.connect(axis=axis)
    m.offset = entry.get("offset", 0)
    m.units = entry.get("units", 1)
    return m


class MotorRecordGroup(PVGroup):
    """caproto record='motor' facade over a pystxmcontrol motor driver.

    .VAL put -> IOC-side HLM/LLM limit check -> blocking driver.moveTo in a
    worker thread; the .VAL put-completion is held until the move finishes
    (true motor-record busy semantics: caput -c returns when DMOV=1).
    .RBV polled from driver.getPos() (idle_poll s idle, moving_poll s while
    moving); .STOP put stops the pending move; .VELO put calls
    driver.setAxisParams(velocity=...) when available.

    Note: field putters (``@motor.fields.stop.putter`` etc) are NOT used here
    -- caproto 1.3's fake_motor_record.py example itself drives STOP by
    polling ``fields.stop.value`` inside the simulator loop rather than
    attaching a putter, and ``instance.group`` parent navigation isn't a
    documented/stable path in caproto.server.records.base. We follow the same
    poll-based pattern for both STOP and VELO to sidestep that fragility.
    """

    motor = pvproperty(value=0.0, name="", record="motor", precision=3)

    def __init__(self, prefix, *, driver, motor_config,
                 idle_poll=0.1, moving_poll=0.02, io_lock=None, **kwargs):
        super().__init__(prefix, **kwargs)
        self._driver = driver
        self._motor_config = motor_config
        self._idle_poll = idle_poll
        self._moving_poll = moving_poll
        self._move_queue: asyncio.Queue = asyncio.Queue()
        # Serializes every blocking driver transaction (getPos/moveTo/stop/
        # setAxisParams) for this motor. Motors that share a controller (and
        # therefore a single, non-reentrant link -- e.g. one FTDI handle for
        # both nPoint axes) MUST be given the SAME lock so their RBV pollers
        # and moves never interleave two write/read frames on the wire, which
        # otherwise corrupts one axis's response into garbage. A fly loop that
        # drives the same controller acquires this lock too. Drivers stay
        # lock-agnostic; all locking happens at this IOC orchestration layer,
        # so holding the lock while calling a driver method never re-enters it.
        self._io_lock = io_lock if io_lock is not None else threading.Lock()

    @motor.startup
    async def motor(self, instance, async_lib):
        fields = instance.field_inst
        cfg = self._motor_config

        await fields.user_low_limit.write(float(cfg.get("minValue", -1e12)))
        await fields.user_high_limit.write(float(cfg.get("maxValue", 1e12)))
        await fields.velocity.write(float(cfg.get("max velocity", 0.0)))
        await fields.engineering_units.write(
            cfg.get("epics", {}).get("egu", "um"))
        await fields.done_moving_to_value.write(1)
        await fields.motor_is_moving.write(0)
        await fields.stop.write(0)

        last_velocity = fields.velocity.value

        async def value_write_hook(fields_, value):
            lo = fields.user_low_limit.value
            hi = fields.user_high_limit.value
            if not (lo <= value <= hi):
                raise ValueError(
                    f"{self.prefix}: {value} outside limits [{lo}, {hi}]")
            # Block the .VAL put until the physical move actually finishes,
            # so CA put-completion (caput -c / write(..., wait=True)) carries
            # true motor-record busy semantics for every client. caproto
            # spawns each write handler as its own task
            # (VirtualCircuit._start_write_task -> tasks.create), so awaiting
            # here does NOT stall the circuit: STOP puts and RBV/MOVN reads
            # keep flowing while this put is pending.
            done_event = asyncio.Event()
            self._move_queue.put_nowait((value, done_event))
            await done_event.wait()

        fields.value_write_hook = value_write_hook

        loop = asyncio.get_running_loop()

        async def sync_velocity():
            nonlocal last_velocity
            current = fields.velocity.value
            if current != last_velocity:
                last_velocity = current
                if hasattr(self._driver, "setAxisParams"):
                    await loop.run_in_executor(
                        None, self._locked_call,
                        lambda: self._driver.setAxisParams(velocity=current))

        async def refresh_rbv():
            try:
                pos = await loop.run_in_executor(
                    None, self._locked_call, self._driver.getPos)
            except Exception as exc:
                # A transient driver read error (e.g. a truncated USB response
                # from the controller) must NOT kill the IOC. This runs inside
                # the startup hook, so an escaping exception propagates through
                # caproto's _server_startup and shuts the whole server down.
                # Log and keep the last-known RBV; the next poll retries.
                # Mirrors the move path's "driver error must not kill this
                # loop" guard below.
                print(f"{self.prefix}: position read failed: {exc!r}",
                      flush=True)
                return
            await fields.user_readback_value.write(pos)

        await refresh_rbv()

        while True:
            await sync_velocity()
            try:
                target, done_event = await asyncio.wait_for(
                    self._move_queue.get(), timeout=self._idle_poll)
            except asyncio.TimeoutError:
                await refresh_rbv()
                continue

            try:
                await fields.done_moving_to_value.write(0)
                await fields.motor_is_moving.write(1)
                move_future = loop.run_in_executor(
                    None, self._guarded_move_to, target)
                # Do NOT poll getPos() while the move runs: _guarded_move_to
                # holds the controller lock for the whole move, so a getPos on
                # the shared link would both collide with the move's own
                # transactions and block this loop (starving STOP). Just watch
                # for STOP -- issued WITHOUT the lock, because it must PREEMPT
                # the in-flight move; drivers implement stop() as an out-of-band
                # abort/flag, not a bus transaction that would queue behind the
                # move. RBV is refreshed once the move releases the link, below.
                while not move_future.done():
                    if fields.stop.value:
                        if hasattr(self._driver, "stop"):
                            await loop.run_in_executor(None, self._driver.stop)
                        await fields.stop.write(0)
                    await async_lib.library.sleep(self._moving_poll)
                try:
                    move_future.result()
                except Exception as exc:
                    # An unexpected driver error must not kill this loop --
                    # otherwise RBV/DMOV freeze forever. Log and recover.
                    print(f"{self.prefix}: move to {target} failed: {exc!r}",
                          flush=True)
                await refresh_rbv()
                await fields.motor_is_moving.write(0)
                await fields.done_moving_to_value.write(1)
            finally:
                # ALWAYS release the pending .VAL put -- on the happy path,
                # after a driver error (handled above), and even if this
                # block itself raises -- or the client's put-completion
                # would hang forever.
                done_event.set()

    def _locked_call(self, fn, *args):
        """Run a blocking driver call holding this motor's controller lock, so
        no two transactions on the shared link overlap. Runs in an executor
        thread; the lock is a plain threading.Lock (not reentrant), and driver
        methods never take it themselves, so nesting can't self-deadlock."""
        with self._io_lock:
            return fn(*args)

    def _guarded_move_to(self, target):
        with self._io_lock:
            try:
                self._driver.moveTo(target)
            except SoftwareLimitError:
                pass  # belt-and-braces; the write hook's HLM/LLM check runs first

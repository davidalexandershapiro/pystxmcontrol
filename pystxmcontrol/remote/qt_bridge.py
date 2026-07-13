"""RemoteBackend: QThread hosting an asyncio loop, bridging LightfallClient
to Qt signals for the pystxmcontrol remote GUI (spec #4 Task 5).

Usage::

    client = LightfallClient(nats_url, prefix, app_name)
    backend = RemoteBackend(client)
    backend.authenticated.connect(...)
    backend.start()
    backend.connect_and_authenticate()
    ...
    backend.shutdown()
    backend.wait()

All public methods are thread-safe: they schedule a coroutine onto the
backend's own asyncio loop via ``asyncio.run_coroutine_threadsafe`` and
return immediately. Results/errors surface as Qt signals, never as
exceptions raised back to the caller's thread.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import traceback

from PySide6 import QtCore

from .ca_monitors import MotorMonitorSet
from .client import RemoteError
from .scan_mapping import UnsupportedScanMode, map_scan


class RemoteBackend(QtCore.QThread):
    """Asyncio<->Qt bridge around a (constructed, not-yet-connected)
    LightfallClient.

    ``monitor_factory`` defaults to :class:`MotorMonitorSet` but is
    injectable for tests (a fake avoids any real Channel Access).
    """

    authenticated = QtCore.Signal(dict)
    auth_failed = QtCore.Signal(str)
    config_ready = QtCore.Signal(dict)
    motor_positions = QtCore.Signal(dict)
    engine_state = QtCore.Signal(str)
    scan_submitted = QtCore.Signal(dict)
    scan_error = QtCore.Signal(str)
    run_new = QtCore.Signal(dict)
    run_complete = QtCore.Signal(dict)
    remote_error = QtCore.Signal(str)

    def __init__(self, client, *, monitor_factory=MotorMonitorSet,
                 monitor_min_period_s: float = 0.2, parent=None) -> None:
        super().__init__(parent)
        self._client = client
        self._monitor_factory = monitor_factory
        self._monitor_min_period_s = monitor_min_period_s
        self._monitor = None
        # _monitor is set from the loop thread (_start_monitor) and
        # read/cleared from the caller thread (shutdown); _shutting_down
        # ensures no monitor starts after shutdown began.
        self._monitor_lock = threading.Lock()
        self._shutting_down = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = QtCore.QMutex()
        self._loop_ready_cond = QtCore.QWaitCondition()

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop_ready.lock()
        self._loop = loop
        self._loop_ready_cond.wakeAll()
        self._loop_ready.unlock()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            loop.close()

    def _wait_for_loop(self, timeout_ms: int = 5000) -> asyncio.AbstractEventLoop:
        self._loop_ready.lock()
        try:
            deadline_remaining = timeout_ms
            while self._loop is None and deadline_remaining > 0:
                self._loop_ready_cond.wait(self._loop_ready, 50)
                deadline_remaining -= 50
        finally:
            self._loop_ready.unlock()
        if self._loop is None:
            raise RuntimeError("RemoteBackend loop did not start in time")
        return self._loop

    def _schedule(self, coro) -> None:
        """Schedule a coroutine on the backend loop from any thread."""
        loop = self._wait_for_loop()

        def _runner():
            return asyncio.ensure_future(self._run_guarded(coro), loop=loop)

        loop.call_soon_threadsafe(_runner)

    async def _run_guarded(self, coro) -> None:
        try:
            await coro
        except RemoteError:
            # Individual call sites are expected to catch RemoteError
            # themselves and emit a structured signal; if one leaks here,
            # treat it like any other unexpected failure rather than
            # silently swallowing it.
            self._emit_unexpected(sys.exc_info())
        except asyncio.CancelledError:
            pass
        except Exception:
            self._emit_unexpected(sys.exc_info())

    def _emit_unexpected(self, exc_info) -> None:
        traceback.print_exception(*exc_info, file=sys.stderr)
        self.remote_error.emit(str(exc_info[1]))

    # ------------------------------------------------------------------
    # Public thread-safe API
    # ------------------------------------------------------------------

    def connect_and_authenticate(self) -> None:
        self._schedule(self._do_connect_and_authenticate())

    def fetch_config(self) -> None:
        self._schedule(self._do_fetch_config())

    def move_motor(self, name: str, position: float) -> None:
        self._schedule(self._do_move_motor(name, position))

    def submit_scan(self, scan_dict: dict) -> None:
        self._schedule(self._do_submit_scan(scan_dict))

    def abort_scan(self) -> None:
        self._schedule(self._do_abort_scan())

    def shutdown(self) -> bool:
        """Stop the monitor set and the asyncio loop, then join the thread.

        Returns True once the thread has exited. If the loop never became
        ready or the thread refuses to die within the timeout, emits
        remote_error and returns False (loudly, never silently).
        """
        with self._monitor_lock:
            self._shutting_down = True
            monitor, self._monitor = self._monitor, None
        if monitor is not None:
            try:
                monitor.stop()
            except Exception:
                traceback.print_exc(file=sys.stderr)
        if self.isRunning() or self._loop is not None:
            # Wait for run() to publish the loop before scheduling its stop;
            # reading self._loop directly races a just-started thread and
            # would silently leave it running forever.
            try:
                loop = self._wait_for_loop()
            except RuntimeError as exc:
                if self.isRunning():
                    self.remote_error.emit(str(exc))
                    return False
                return True
            if loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
        if not self.wait(5000):
            self.remote_error.emit(
                "RemoteBackend thread did not exit within 5 s of shutdown()")
            return False
        return True

    # ------------------------------------------------------------------
    # Coroutine bodies
    # ------------------------------------------------------------------

    async def _do_connect_and_authenticate(self) -> None:
        try:
            await self._client.connect()
            reply = await self._client.authenticate()
        except RemoteError as exc:
            self.auth_failed.emit(exc.message)
            return
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self.auth_failed.emit(str(exc))
            return
        if reply.get("status") != "approved":
            self.auth_failed.emit(reply.get("message", "authentication rejected"))
            return
        await self._subscribe_broadcasts()
        self.authenticated.emit(reply)

    async def _subscribe_broadcasts(self) -> None:
        await self._client.subscribe_event(
            "runs.new", lambda payload: self.run_new.emit(payload))
        await self._client.subscribe_event(
            "runs.complete", lambda payload: self.run_complete.emit(payload))
        await self._client.subscribe_event(
            "state.engine",
            lambda payload: self.engine_state.emit(payload.get("state", "")))

    async def _do_fetch_config(self) -> None:
        try:
            search_reply = await self._client.call("device.search", {})
            device_names = search_reply.get("devices", [])
            motors: dict[str, dict] = {}
            for name in device_names:
                info = await self._client.call("device.info", {"device": name})
                category = info.get("category", "")
                if "motor" in category:
                    motors[name] = {"pv": info.get("pv"), "category": category}
            plan_reply = await self._client.call("plan.list", {})
            plans = plan_reply.get("plans", [])
        except RemoteError as exc:
            self.remote_error.emit(exc.message)
            return
        config = {"motors": motors, "plans": plans}
        self.config_ready.emit(config)
        self._start_monitor(motors)

    def _start_monitor(self, motors: dict[str, dict]) -> None:
        with self._monitor_lock:
            old, self._monitor = self._monitor, None
        if old is not None:
            try:
                old.stop()
            except Exception:
                traceback.print_exc(file=sys.stderr)
        pv_map = {name: info["pv"] for name, info in motors.items()}
        if not pv_map:
            return
        monitor = self._monitor_factory(
            pv_map, self._on_monitor_update,
            min_period_s=self._monitor_min_period_s)
        with self._monitor_lock:
            if self._shutting_down:
                # shutdown() already ran its monitor sweep; starting now
                # would leak CA contexts/threads nobody will ever stop.
                return
            self._monitor = monitor
            monitor.start()

    def _on_monitor_update(self, payload: dict) -> None:
        # Signal emission is thread-safe from any thread (queued delivery
        # to receivers living on another thread's event loop).
        self.motor_positions.emit(payload)

    async def _do_move_motor(self, name: str, position: float) -> None:
        try:
            await self._client.call(
                "device.put", {"device": name, "value": position, "wait": True})
        except RemoteError as exc:
            self.remote_error.emit(exc.message)

    async def _do_submit_scan(self, scan_dict: dict) -> None:
        try:
            plan_name, params = map_scan(scan_dict)
        except UnsupportedScanMode as exc:
            self.scan_error.emit(str(exc))
            return
        except (KeyError, ValueError) as exc:
            self.scan_error.emit(str(exc))
            return
        try:
            reply = await self._client.call(
                "plan.run",
                {"plan_name": plan_name, "params": params, "behavior": "reject"})
        except RemoteError as exc:
            self.scan_error.emit(exc.message)
            return
        self.scan_submitted.emit(reply)

    async def _do_abort_scan(self) -> None:
        try:
            await self._client.call("plan.abort", {})
        except RemoteError as exc:
            self.remote_error.emit(exc.message)

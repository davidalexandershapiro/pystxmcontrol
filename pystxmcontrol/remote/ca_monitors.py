"""Coalesced caproto readback monitors for the remote GUI motor panel
(spec #4 Task 4).

MotorMonitorSet subscribes to ``<pv>.RBV`` and ``<pv>.MOVN`` for a set of
motors over a single caproto threading Context, and coalesces the resulting
callbacks into ``on_update({name: float, ..., "status": {name: bool}})``
calls at most every ``min_period_s`` (trailing-edge flush so the final value
always lands). No Qt here -- ``on_update`` is a plain callable; RemoteBackend
(Task 5) adapts it to a Qt signal.
"""
from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable


class MotorMonitorSet:
    """CA readback monitor set for a fleet of motors.

    ``motors`` maps display name -> PV prefix (e.g. ``{"SampleX":
    "STXMSIM:E712:SampleX"}``); ``<prefix>.RBV`` and ``<prefix>.MOVN`` are
    subscribed for each. ``connected`` reports per-motor CA connection state
    (both RBV and MOVN connected) and drives the panel grey-out.
    """

    def __init__(self, motors: dict[str, str],
                 on_update: Callable[[dict], None],
                 min_period_s: float = 0.2) -> None:
        self._motors = dict(motors)
        self._on_update = on_update
        self._min_period_s = min_period_s

        self._lock = threading.Lock()
        self._context = None
        self._subscriptions: list = []
        # caproto's CallbackHandler (both connection_state_callback and
        # Subscription.add_callback) stores callbacks via weakref -- a
        # functools.partial with no other strong reference is garbage
        # collected almost immediately, silently dropping the callback. Keep
        # every bound callback alive for the lifetime of this monitor set.
        self._callback_refs: list = []

        self._rbv_connected = {name: False for name in self._motors}
        self._movn_connected = {name: False for name in self._motors}
        self._connected = {name: False for name in self._motors}

        self._pending_positions: dict[str, float] = {}
        self._pending_status: dict[str, bool] = {}
        self._last_flush = 0.0
        self._timer: threading.Timer | None = None
        self._running = False

    @property
    def connected(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._connected)

    def start(self) -> None:
        from caproto.threading.client import Context

        self._context = Context()
        with self._lock:
            self._running = True
            self._last_flush = time.monotonic()

        for name, prefix in self._motors.items():
            conn_cb = functools.partial(self._on_connection_state, name)
            self._callback_refs.append(conn_cb)
            rbv_pv, movn_pv = self._context.get_pvs(
                f"{prefix}.RBV", f"{prefix}.MOVN",
                connection_state_callback=conn_cb)

            rbv_cb = functools.partial(self._on_rbv, name)
            movn_cb = functools.partial(self._on_movn, name)
            self._callback_refs.extend([rbv_cb, movn_cb])

            rbv_sub = rbv_pv.subscribe(data_type="time")
            rbv_sub.add_callback(rbv_cb)
            movn_sub = movn_pv.subscribe(data_type="time")
            movn_sub.add_callback(movn_cb)
            self._subscriptions.extend([rbv_sub, movn_sub])

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        for sub in self._subscriptions:
            sub.clear()
        self._subscriptions = []
        if self._context is not None:
            self._context.disconnect()
            self._context = None
        self._callback_refs = []

    # ---- connection state -------------------------------------------------

    def _on_connection_state(self, name, pv, state) -> None:
        connected = state == "connected"
        is_rbv = pv.name.endswith(".RBV")
        with self._lock:
            if is_rbv:
                self._rbv_connected[name] = connected
            else:
                self._movn_connected[name] = connected
            self._connected[name] = (
                self._rbv_connected.get(name, False)
                and self._movn_connected.get(name, False))

    # ---- value updates + coalescing ---------------------------------------

    def _on_rbv(self, name, sub, response) -> None:
        value = float(response.data[0])
        self._apply_and_maybe_flush(lambda: self._pending_positions.__setitem__(
            name, value))

    def _on_movn(self, name, sub, response) -> None:
        value = bool(response.data[0])
        self._apply_and_maybe_flush(lambda: self._pending_status.__setitem__(
            name, value))

    def _apply_and_maybe_flush(self, apply_fn: Callable[[], None]) -> None:
        payload = None
        with self._lock:
            if not self._running:
                return
            apply_fn()
            now = time.monotonic()
            elapsed = now - self._last_flush
            if elapsed >= self._min_period_s:
                payload = self._pop_pending_locked()
                self._last_flush = now
            elif self._timer is None:
                remaining = self._min_period_s - elapsed
                self._timer = threading.Timer(remaining, self._flush_from_timer)
                self._timer.daemon = True
                self._timer.start()
        if payload is not None:
            self._on_update(payload)

    def _flush_from_timer(self) -> None:
        payload = None
        with self._lock:
            self._timer = None
            if not self._running:
                return
            payload = self._pop_pending_locked()
            self._last_flush = time.monotonic()
        if payload is not None:
            self._on_update(payload)

    def _pop_pending_locked(self) -> dict | None:
        """Call with self._lock held."""
        if not self._pending_positions and not self._pending_status:
            return None
        payload = dict(self._pending_positions)
        payload["status"] = dict(self._pending_status)
        self._pending_positions = {}
        self._pending_status = {}
        return payload

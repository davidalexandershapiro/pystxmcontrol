"""Shared test doubles for the remote-GUI Qt test suite (spec #4 Tasks 5+7).

Moved out of test_qt_bridge.py so test_qt_integration.py (Task 7) can reuse
the same FakeLightfallClient / FakeMonitorSet without duplicating them.
"""
from __future__ import annotations

import time


class FakeLightfallClient:
    """Duck-types the async surface RemoteBackend consumes; canned replies."""

    def __init__(self):
        self.session_token = None
        self.tiled_url = None
        self.tiled_token = None
        self.call_log: list[tuple[str, dict]] = []
        self.subscriptions: dict[str, callable] = {}
        self.call_handlers: dict[str, callable] = {}
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def authenticate(self, timeout: float = 90.0) -> dict:
        self.session_token = "tok123"
        self.tiled_url = "http://tiled"
        self.tiled_token = "tt"
        return {"status": "approved", "session_token": "tok123"}

    async def call(self, suffix: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
        payload = dict(payload or {})
        self.call_log.append((suffix, payload))
        handler = self.call_handlers.get(suffix)
        if handler is not None:
            return handler(payload)
        return {"status": "ok"}

    async def subscribe_event(self, suffix: str, callback) -> None:
        self.subscriptions[suffix] = callback

    async def close(self) -> None:
        self.closed = True

    def tiled_client(self):
        raise AssertionError("tiled_client() not stubbed for this test")

    # test helper: fire a broadcast event as if received off the wire
    def fire(self, suffix: str, payload: dict) -> None:
        cb = self.subscriptions[suffix]
        cb(payload)


class FakeMonitorSet:
    """Stand-in for MotorMonitorSet -- injected via monitor_factory."""

    instances: list["FakeMonitorSet"] = []

    def __init__(self, motors, on_update, min_period_s: float = 0.2):
        self.motors = motors
        self.on_update = on_update
        self.started = False
        self.stopped = False
        FakeMonitorSet.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeRunStreamer:
    """Stand-in for RunStreamer -- captures the on_image/on_progress/on_error
    callbacks so a test can fire a synthesized image without any real Tiled
    connection or background thread."""

    instances: list["FakeRunStreamer"] = []

    def __init__(self, tiled_client_factory, run_uid, on_image, on_progress,
                 *, on_error=None, poll_s: float = 1.0, data_field: str = "Counter1"):
        self.tiled_client_factory = tiled_client_factory
        self.run_uid = run_uid
        self.on_image = on_image
        self.on_progress = on_progress
        self.on_error = on_error
        self.started = False
        self.stopped = False
        FakeRunStreamer.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    # test helper: synthesize a poll result directly (no thread, no Tiled)
    def fire_image(self, image_dict: dict, extents=((0, 1), (0, 1))) -> None:
        self.on_image(image_dict, extents)


def wait_for(qapp, predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()

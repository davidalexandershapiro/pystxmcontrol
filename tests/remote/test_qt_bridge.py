"""Tests for RemoteBackend (QThread + asyncio bridge), spec #4 Task 5."""
from __future__ import annotations

import asyncio

import pytest
from PySide6 import QtCore

from pystxmcontrol.remote.client import RemoteError
from pystxmcontrol.remote.qt_bridge import RemoteBackend

from .fakes import FakeLightfallClient, FakeMonitorSet


@pytest.fixture(autouse=True)
def _clear_monitor_instances():
    FakeMonitorSet.instances.clear()
    yield
    FakeMonitorSet.instances.clear()


@pytest.fixture
def qapp():
    app = QtCore.QCoreApplication.instance()
    if app is None:
        app = QtCore.QCoreApplication([])
    return app


def _wait_for(qapp, predicate, timeout_s: float = 5.0) -> bool:
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


@pytest.fixture
def fake_client():
    return FakeLightfallClient()


@pytest.fixture
def backend(qapp, fake_client):
    backend = RemoteBackend(fake_client, monitor_factory=FakeMonitorSet)
    backend.start()
    yield backend
    backend.shutdown()
    backend.wait(5000)


def test_connect_and_authenticate_emits_authenticated(qapp, backend):
    events = []
    backend.authenticated.connect(lambda d: events.append(d))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: len(events) == 1)
    assert events[0]["status"] == "approved"


def test_fetch_config_emits_config_ready_with_motors_filtered(qapp, backend, fake_client):
    fake_client.call_handlers["device.search"] = lambda p: {
        "status": "ok", "devices": ["SampleX", "SampleY", "Shutter"]}

    def _info(payload):
        device = payload["device"]
        table = {
            "SampleX": {"pv": "STXM:SampleX", "category": "motor"},
            "SampleY": {"pv": "STXM:SampleY", "category": "motor"},
            "Shutter": {"pv": "STXM:Shutter", "category": "shutter"},
        }
        return {"status": "ok", **table[device]}

    fake_client.call_handlers["device.info"] = _info
    fake_client.call_handlers["plan.list"] = lambda p: {
        "status": "ok", "plans": ["stxm_fly_raster", "stxm_energy_stack"]}

    events = []
    backend.config_ready.connect(lambda d: events.append(d))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.fetch_config()
    assert _wait_for(qapp, lambda: len(events) == 1)
    config = events[0]
    assert set(config["motors"]) == {"SampleX", "SampleY"}
    assert config["motors"]["SampleX"]["pv"] == "STXM:SampleX"
    assert config["plans"] == ["stxm_fly_raster", "stxm_energy_stack"]
    # MotorMonitorSet started with the fetched PVs after config_ready
    assert _wait_for(qapp, lambda: len(FakeMonitorSet.instances) == 1)
    monitor = FakeMonitorSet.instances[0]
    assert monitor.started
    assert monitor.motors == {"SampleX": "STXM:SampleX", "SampleY": "STXM:SampleY"}


def test_motor_positions_relayed_from_monitor(qapp, backend, fake_client):
    fake_client.call_handlers["device.search"] = lambda p: {
        "status": "ok", "devices": ["SampleX"]}
    fake_client.call_handlers["device.info"] = lambda p: {
        "status": "ok", "pv": "STXM:SampleX", "category": "motor"}
    fake_client.call_handlers["plan.list"] = lambda p: {"status": "ok", "plans": []}

    positions = []
    backend.motor_positions.connect(lambda d: positions.append(d))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.fetch_config()
    assert _wait_for(qapp, lambda: len(FakeMonitorSet.instances) == 1)
    monitor = FakeMonitorSet.instances[0]
    monitor.on_update({"SampleX": 1.5, "status": {"SampleX": False}})
    assert _wait_for(qapp, lambda: len(positions) == 1)
    assert positions[0]["SampleX"] == 1.5


def test_submit_scan_happy_path_calls_plan_run_with_mapped_params(qapp, backend, fake_client):
    fake_client.call_handlers["plan.run"] = lambda p: {"status": "ok", "run_id": "r1"}
    scan = {
        "scan_type": "Image",
        "scan_regions": {"r1": {
            "xStart": 0.0, "xStop": 1.0, "xPoints": 10,
            "yStart": 0.0, "yStop": 1.0, "yPoints": 10}},
        "energy_regions": {"e1": {"start": 500, "stop": 500, "n_energies": 1, "dwell": 5}},
    }
    events = []
    backend.scan_submitted.connect(lambda d: events.append(d))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.submit_scan(scan)
    assert _wait_for(qapp, lambda: len(events) == 1)
    suffix, payload = fake_client.call_log[-1]
    assert suffix == "plan.run"
    assert payload["plan_name"] == "stxm_fly_raster"
    assert payload["behavior"] == "reject"
    assert payload["params"]["nx"] == 10


def test_submit_scan_unsupported_mode_emits_scan_error(qapp, backend, fake_client):
    scan = {"scan_type": "Ptychography", "scan_regions": {}, "energy_regions": {}}
    errors = []
    backend.scan_error.connect(lambda m: errors.append(m))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.submit_scan(scan)
    assert _wait_for(qapp, lambda: len(errors) == 1)
    assert "Ptychography" in errors[0]
    assert not fake_client.call_log or fake_client.call_log[-1][0] != "plan.run"


def test_submit_scan_busy_remote_error_emits_scan_error_no_crash(qapp, backend, fake_client):
    def _busy(payload):
        raise RemoteError("busy", "engine busy")

    fake_client.call_handlers["plan.run"] = _busy
    scan = {
        "scan_type": "Image",
        "scan_regions": {"r1": {
            "xStart": 0.0, "xStop": 1.0, "xPoints": 5,
            "yStart": 0.0, "yStop": 1.0, "yPoints": 5}},
        "energy_regions": {"e1": {"start": 500, "stop": 500, "n_energies": 1, "dwell": 5}},
    }
    errors = []
    backend.scan_error.connect(lambda m: errors.append(m))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.submit_scan(scan)
    assert _wait_for(qapp, lambda: len(errors) == 1)
    assert "engine busy" in errors[0]
    # thread stays alive / responsive after the error
    positions = []
    backend.authenticated.connect(lambda d: positions.append(d))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: len(positions) == 1)


def test_move_motor_limits_error_emits_remote_error(qapp, backend, fake_client):
    def _limits(payload):
        raise RemoteError("limits", "target outside soft limits")

    fake_client.call_handlers["device.put"] = _limits
    errors = []
    backend.remote_error.connect(lambda m: errors.append(m))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.move_motor("SampleX", 42.0)
    assert _wait_for(qapp, lambda: len(errors) == 1)
    assert "target outside soft limits" in errors[0]


def test_move_motor_happy_path_calls_device_put(qapp, backend, fake_client):
    fake_client.call_handlers["device.put"] = lambda p: {"status": "ok"}
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.move_motor("SampleX", 3.5)

    def _called():
        return any(s == "device.put" for s, _ in fake_client.call_log)

    assert _wait_for(qapp, _called)
    suffix, payload = [c for c in fake_client.call_log if c[0] == "device.put"][-1]
    assert payload["device"] == "SampleX"
    assert payload["value"] == 3.5
    assert payload["wait"] is True


def test_runs_new_event_emits_run_new_signal(qapp, backend, fake_client):
    events = []
    backend.run_new.connect(lambda d: events.append(d))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    assert _wait_for(qapp, lambda: "runs.new" in fake_client.subscriptions)
    fake_client.fire("runs.new", {"uid": "abc"})
    assert _wait_for(qapp, lambda: len(events) == 1)
    assert events[0]["uid"] == "abc"


def test_runs_complete_and_engine_state_events(qapp, backend, fake_client):
    completes = []
    states = []
    backend.run_complete.connect(lambda d: completes.append(d))
    backend.engine_state.connect(lambda s: states.append(s))
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    assert _wait_for(qapp, lambda: "runs.complete" in fake_client.subscriptions)
    assert _wait_for(qapp, lambda: "state.engine" in fake_client.subscriptions)
    fake_client.fire("runs.complete", {"uid": "abc", "exit_status": "success"})
    fake_client.fire("state.engine", {"state": "running"})
    assert _wait_for(qapp, lambda: len(completes) == 1 and len(states) == 1)
    assert completes[0]["exit_status"] == "success"
    assert states[0] == "running"


def test_shutdown_immediately_after_start_joins_thread(qapp, fake_client):
    """shutdown() racing run()'s loop assignment must still stop the thread."""
    backend = RemoteBackend(fake_client, monitor_factory=FakeMonitorSet)
    backend.start()
    assert backend.shutdown() is True
    assert not backend.isRunning()


def test_shutdown_before_start_is_clean(qapp, fake_client):
    backend = RemoteBackend(fake_client, monitor_factory=FakeMonitorSet)
    assert backend.shutdown() is True
    assert not backend.isRunning()


def test_monitor_not_started_when_shutdown_interleaves_fetch_config(qapp, fake_client):
    """A fetch_config in flight during shutdown must not leak a started
    monitor: the factory blocks until shutdown has begun, then _start_monitor
    must refuse to start it (or stop it)."""
    import time

    fake_client.call_handlers["device.search"] = lambda p: {
        "status": "ok", "devices": ["SampleX"]}
    fake_client.call_handlers["device.info"] = lambda p: {
        "status": "ok", "pv": "STXM:SampleX", "category": "motor"}
    fake_client.call_handlers["plan.list"] = lambda p: {"status": "ok", "plans": []}

    holder = {}
    constructing = __import__("threading").Event()

    class LatchedMonitor(FakeMonitorSet):
        def __init__(self, motors, on_update, min_period_s=0.2):
            constructing.set()
            # Block construction (on the loop thread) until shutdown began,
            # guaranteeing the shutdown-vs-start interleaving under test.
            deadline = time.monotonic() + 5.0
            while not holder["backend"]._shutting_down:
                if time.monotonic() > deadline:
                    raise AssertionError("shutdown never began")
                time.sleep(0.005)
            super().__init__(motors, on_update, min_period_s)

    backend = RemoteBackend(fake_client, monitor_factory=LatchedMonitor)
    holder["backend"] = backend
    backend.start()
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.fetch_config()
    assert constructing.wait(5.0)
    assert backend.shutdown() is True
    assert not backend.isRunning()
    # The interleaved monitor must never remain started.
    for monitor in FakeMonitorSet.instances:
        assert not monitor.started or monitor.stopped


def test_shutdown_joins_thread_cleanly(qapp, fake_client):
    backend = RemoteBackend(fake_client, monitor_factory=FakeMonitorSet)
    backend.start()
    backend.connect_and_authenticate()
    assert _wait_for(qapp, lambda: fake_client.session_token is not None)
    backend.shutdown()
    assert backend.wait(5000)
    assert not backend.isRunning()

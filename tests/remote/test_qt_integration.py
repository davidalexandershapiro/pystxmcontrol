"""Integration tests: real MainController + models driven by a
FakeLightfallClient-backed RemoteBackend (spec #4 Task 7).

Pins (see s4-task-7-report.md for the full writeup):
  - motor_model.set_motor_info() is fed {motor_name: {}, ...} synthesized
    from config_ready's {"motors": {name: {"pv":..., "category":...}}}.
  - backend.motor_positions payload ({name: float, ..., "status": {name:
    bool}}) is routed through _handle_monitor_message as
    {"motorPositions": payload} -- the same shape the legacy ZMQ monitor
    message carries under that key.
  - RunStreamer.on_image(image_dict, extents) is synthesized into a message
    dict handled by the existing image branch of _handle_monitor_message:
    {"image": image_dict, "mode": "rasterLine", "type": "Image",
    "scanRegion": "Region1", "energyIndex": 0, "scanID": run_uid}.
  - run_complete drives _handle_monitor_message("scan_complete") (the same
    sentinel the legacy path uses).
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6 import QtCore

from pystxmcontrol.gui.controllers import main_controller as main_controller_mod
from pystxmcontrol.gui.controllers.main_controller import MainController
from pystxmcontrol.remote.qt_bridge import RemoteBackend

from .fakes import FakeLightfallClient, FakeMonitorSet, FakeRunStreamer, wait_for


@pytest.fixture(autouse=True)
def _clear_fake_instances():
    FakeMonitorSet.instances.clear()
    FakeRunStreamer.instances.clear()
    yield
    FakeMonitorSet.instances.clear()
    FakeRunStreamer.instances.clear()


@pytest.fixture
def qapp():
    # Full QApplication (not QCoreApplication): the window-construction test
    # needs widgets, and whichever test file runs first fixes the app type
    # for the whole process.
    from PySide6 import QtWidgets

    app = QtCore.QCoreApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture
def qapp_widgets(qapp):
    from PySide6 import QtWidgets

    if not isinstance(qapp, QtWidgets.QApplication):
        pytest.skip("process QCoreApplication is not a QApplication; "
                     "widget construction impossible in this run")
    return qapp


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


@pytest.fixture
def controller(qapp, backend, monkeypatch):
    # RunStreamer is constructed inside main_controller on run_new; patch the
    # module-level name so we can drive it without a real Tiled connection.
    monkeypatch.setattr(main_controller_mod, "RunStreamer", FakeRunStreamer)
    ctrl = MainController(backend=backend)
    yield ctrl


def _image_region(x_center=0.0, y_center=0.0, x_range=10.0, y_range=20.0,
                   x_points=10, y_points=20):
    x_step = x_range / x_points
    y_step = y_range / y_points
    return {
        "xCenter": x_center, "yCenter": y_center,
        "xRange": x_range, "yRange": y_range,
        "xPoints": x_points, "yPoints": y_points,
        "xStep": x_step, "yStep": y_step,
        "xStart": x_center - x_range / 2.0 + x_step / 2.0,
        "xStop": x_center + x_range / 2.0 - x_step / 2.0,
        "yStart": y_center - y_range / 2.0 + y_step / 2.0,
        "yStop": y_center + y_range / 2.0 - y_step / 2.0,
        "zCenter": 0, "zRange": 0, "zPoints": 1, "zStep": 0,
        "zStart": 0, "zStop": 0,
    }


def _energy_region(start=280.0, stop=280.0, n_energies=1, dwell=5.0, step=1.0):
    return {"start": start, "stop": stop, "step": step, "dwell": dwell,
            "n_energies": n_energies}


def _make_raster_scan_model(controller):
    controller.scan_model.set("scan_type", "Image")
    controller.scan_model.set("x_motor", "SampleX")
    controller.scan_model.set("y_motor", "SampleY")
    controller.scan_model.set("scan_regions", {"Region1": _image_region()})
    controller.scan_model.set("energy_regions", {"EnergyRegion1": _energy_region()})


# ---------------------------------------------------------------------------
# backend=None: legacy ZMQ path stays intact (import-only, no real server)
# ---------------------------------------------------------------------------

def test_backend_none_still_constructs_zmq_client(monkeypatch):
    calls = []

    class _DummyStxmClient:
        def __init__(self):
            calls.append("constructed")

    monkeypatch.setattr(main_controller_mod, "stxm_client", _DummyStxmClient)
    ctrl = MainController()
    assert calls == ["constructed"]
    assert ctrl.backend is None
    assert isinstance(ctrl.client, _DummyStxmClient)


# ---------------------------------------------------------------------------
# backend mode: initialization
# ---------------------------------------------------------------------------

def test_initialize_client_populates_motor_model_from_config(qapp, controller, fake_client):
    def _device_search(payload):
        return {"devices": ["SampleX", "SampleY"]}

    def _device_info(payload):
        name = payload["device"]
        return {"pv": f"STXMSIM:{name}", "category": "motor"}

    fake_client.call_handlers["device.search"] = _device_search
    fake_client.call_handlers["device.info"] = _device_info
    fake_client.call_handlers["plan.list"] = lambda payload: {"plans": ["stxm_fly_raster"]}

    assert controller.initialize_client() is True
    assert wait_for(qapp, lambda: controller.motor_model.get("motor_info") == {
        "SampleX": {}, "SampleY": {}})


def test_move_motor_routes_to_device_put(qapp, controller, fake_client):
    controller.motor_model.set_motor_info({"SampleX": {"minValue": -10, "maxValue": 10,
                                                         "minScanValue": -10, "maxScanValue": 10}})
    assert controller.move_motor("SampleX", 1.5) is True
    assert wait_for(qapp, lambda: ("device.put", {"device": "SampleX", "value": 1.5, "wait": True})
                     in fake_client.call_log)


def test_start_scan_raster_routes_to_plan_run(qapp, controller, fake_client):
    _make_raster_scan_model(controller)
    assert controller.start_scan() is True
    assert wait_for(qapp, lambda: any(suffix == "plan.run" for suffix, _ in fake_client.call_log))
    suffix, payload = next(c for c in fake_client.call_log if c[0] == "plan.run")
    assert payload["plan_name"] == "stxm_fly_raster"


def test_busy_scan_emits_error_occurred(qapp, controller):
    _make_raster_scan_model(controller)
    controller.scanning = True
    events = []
    controller.error_occurred.connect(lambda msg: events.append(msg))
    assert controller.start_scan() is False
    assert events == ["Scan already in progress"]


# ---------------------------------------------------------------------------
# run_new / run_complete -> RunStreamer -> image_model / scan_state
# ---------------------------------------------------------------------------

def test_run_new_starts_streamer_and_image_flows_to_image_model(qapp, controller, backend, fake_client):
    events = []
    controller.image_updated.connect(lambda img: events.append(img))

    controller.initialize_client()
    assert wait_for(qapp, lambda: "runs.new" in fake_client.subscriptions)
    fake_client.fire("runs.new", {"uid": "run-1"})
    assert wait_for(qapp, lambda: len(FakeRunStreamer.instances) == 1)
    streamer = FakeRunStreamer.instances[0]
    assert streamer.run_uid == "run-1"
    assert streamer.started is True

    image = np.zeros((20, 10))
    streamer.fire_image({"default": image})
    assert wait_for(qapp, lambda: len(events) >= 1)
    assert np.array_equal(events[-1], image)


def test_run_complete_stops_scanning_and_streamer(qapp, controller, backend, fake_client):
    controller.scanning = True
    controller.initialize_client()
    assert wait_for(qapp, lambda: "runs.new" in fake_client.subscriptions)
    fake_client.fire("runs.new", {"uid": "run-2"})
    assert wait_for(qapp, lambda: len(FakeRunStreamer.instances) == 1)
    streamer = FakeRunStreamer.instances[0]

    state_events = []
    controller.scan_state_changed.connect(lambda v: state_events.append(v))

    fake_client.fire("runs.complete", {"uid": "run-2", "exit_status": "success"})
    assert wait_for(qapp, lambda: controller.scanning is False)
    assert wait_for(qapp, lambda: False in state_events)
    assert streamer.stopped is True


# ---------------------------------------------------------------------------
# disabled-in-remote-mode surface
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# full-window construction tripwire (the stxmcontrol-remote entry point path)
# ---------------------------------------------------------------------------

def test_mainwindow_constructs_in_backend_mode(qapp_widgets, controller):
    """Regression tripwire: MainWindowMVC must construct with a backend-mode
    controller (client=None) -- exactly what app.py::main() does. Any
    unguarded self.controller.client.* reach during __init__ crashes the
    stxmcontrol-remote entry point before the window ever shows."""
    from pystxmcontrol.gui.mainwindow_mvc import MainWindowMVC

    window = MainWindowMVC(controller=controller)
    try:
        assert window.controller is controller
        assert controller.backend is not None
    finally:
        window.close()
        window.deleteLater()
        qapp_widgets.processEvents()


@pytest.mark.parametrize("method,args", [
    ("set_gate", ("auto",)),
    ("move_to_focus", ()),
    ("change_motor_config", ("SampleX", "offset", 1.0)),
    ("query_motor_history", ("SampleX", 0.0, 1.0)),
])
def test_disabled_methods_emit_not_available(qapp, controller, method, args):
    events = []
    controller.status_updated.connect(lambda msg: events.append(msg))
    result = getattr(controller, method)(*args)
    assert wait_for(qapp, lambda: any("not available in remote mode" in m for m in events))
    if method == "query_motor_history":
        assert result == []

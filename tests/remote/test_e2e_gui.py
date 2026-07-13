"""Golden-run e2e: offscreen Qt, real RemoteBackend + real MainController
against a REAL RemoteControlService + real NATS + real sim fleet + real
Tiled (spec #4 Task 8).

QT_QPA_PLATFORM=offscreen is set by the runner (see task brief); this file
adds no platform wiring of its own. Generous timeouts throughout -- the
whole module may take ~1-2 minutes against real EPICS/NATS/Tiled.
"""
from __future__ import annotations

import time

import numpy as np
import pytest
from PySide6 import QtCore

from pystxmcontrol.gui.controllers.main_controller import MainController
from pystxmcontrol.remote.client import LightfallClient
from pystxmcontrol.remote.qt_bridge import RemoteBackend


@pytest.fixture
def qapp(lightfall_service):
    # Reuse the session-wide QApplication the service fixture already made;
    # constructing a second QApplication in the same process is invalid.
    return lightfall_service.qapp


def _pump_qt_until(qapp, predicate, timeout=60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        # A longer sleep than the usual 0.02s Qt-pump idiom is deliberate:
        # this test's background RunStreamer thread does real HTTP I/O that
        # competes for the GIL with this loop, and a near-continuous
        # processEvents()-then-sleep(0.02) busy-loop starves that thread of
        # scheduling opportunities badly enough, in this environment, to
        # stall it indefinitely (observed: no exception, no server-side
        # request even logged, for minutes). 0.1s still pumps Qt responsively
        # for a test whose waits are measured in tens of seconds.
        time.sleep(0.3)
    return False


_GUI_APP_NAME = "stxm-remote-gui-test"


@pytest.fixture
def gui_client(lightfall_service):
    # TrustManager only pre-approves the app_name lightfall_service itself
    # used ("stxm-remote-test"); a different client identity is untrusted by
    # default and the auth handshake would otherwise hang/deny silently.
    lightfall_service.trust.approve(_GUI_APP_NAME)
    return LightfallClient(
        lightfall_service.ipc._nats_url,  # noqa: SLF001 - test-only introspection
        lightfall_service.prefix,
        _GUI_APP_NAME,
    )


@pytest.fixture
def backend(qapp, gui_client):
    be = RemoteBackend(gui_client)
    be.start()
    yield be
    be.shutdown()
    be.wait(5000)


@pytest.fixture
def controller(qapp, backend):
    ctrl = MainController(backend=backend)
    yield ctrl


def _image_region(x_center, y_center, x_range, y_range, x_points, y_points):
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


# Small enough that a real fly-raster over the sim fleet finishes quickly,
# but with >1 row so run-progress / partial-image behavior is exercised.
# _NX must exceed bluesky_tiled_plugins.writing.tiled_writer.MAX_ARRAY_SIZE
# (16): below that threshold the per-row array columns (X positions,
# detector counts) are embedded as list-type columns in the "internal" SQL
# table instead of routed to the zarr array-write path, and this fixture's
# Tiled server uses sqlite storage (see conftest.py's lightfall_service),
# whose dialect has no list column type.
_NX, _NY = 20, 3


def _make_small_raster_scan_model(controller):
    controller.scan_model.set("scan_type", "Image")
    controller.scan_model.set("x_motor", "SampleX")
    controller.scan_model.set("y_motor", "SampleY")
    controller.scan_model.set(
        "scan_regions",
        {"Region1": _image_region(0.0, 0.0, 4.0, 3.0, _NX, _NY)},
    )
    controller.scan_model.set(
        "energy_regions", {"EnergyRegion1": _energy_region(dwell=5.0)}
    )


def test_golden_run_raster_end_to_end(qapp, lightfall_service, controller):
    """The full loop: initialize -> submit raster -> image streams from Tiled
    -> motor panel tracks a commanded move -> run completes."""
    config_events: list[dict] = []
    controller.status_updated.connect(lambda *_: None)  # keep Qt busy-safe
    image_events: list[np.ndarray] = []
    controller.image_updated.connect(lambda img: image_events.append(np.asarray(img)))

    def _on_config_ready(cfg):
        config_events.append(cfg)

    controller.backend.config_ready.connect(_on_config_ready)

    # ---- 1. initialize -> config_ready --------------------------------
    assert controller.initialize_client() is True
    assert _pump_qt_until(qapp, lambda: len(config_events) >= 1, timeout=30), \
        "config_ready never fired"
    config = config_events[0]
    assert {"SampleX", "SampleY", "energy"} <= set(config["motors"])
    assert any(p.get("name") == "stxm_fly_raster" for p in config["plans"])
    assert _pump_qt_until(
        qapp, lambda: controller.motor_model.get("motor_info") == {
            "SampleX": {}, "SampleY": {}, "energy": {}},
        timeout=15,
    )

    # ---- 2. motor panel tracks a commanded move_motor -------------------
    controller.motor_model.set_motor_info({
        "SampleY": {"minValue": -50, "maxValue": 50,
                    "minScanValue": -50, "maxScanValue": 50},
    })
    position_events: list[tuple[str, float]] = []
    controller.motor_position_updated.connect(
        lambda name, pos: position_events.append((name, pos)))

    target = 1.5
    assert controller.move_motor("SampleY", target) is True
    assert _pump_qt_until(
        qapp,
        lambda: any(name == "SampleY" and pos == pytest.approx(target, abs=0.05)
                    for name, pos in position_events),
        timeout=20,
    ), f"motor panel never observed the commanded move; saw {position_events}"

    # ---- 3. submit a small fly raster via start_scan() -------------------
    _make_small_raster_scan_model(controller)
    scan_state_events: list[bool] = []
    controller.scan_state_changed.connect(lambda v: scan_state_events.append(v))
    run_new_events: list[dict] = []
    controller.backend.run_new.connect(lambda payload: run_new_events.append(payload))

    assert controller.start_scan() is True
    assert controller.scanning is True
    assert _pump_qt_until(qapp, lambda: True in scan_state_events, timeout=15), \
        "scan_state_changed(True) never fired"

    # ---- 4. run_new -> RunStreamer assembles the image from Tiled --------
    assert _pump_qt_until(qapp, lambda: len(run_new_events) >= 1, timeout=30), \
        "runs.new was never broadcast for the submitted raster"
    run_uid = run_new_events[0]["run_uid"]
    assert run_uid

    # Tiled reads racing the writer's concurrent node creation have been
    # observed, in this environment, to self-heal only after a long run of
    # internal client-side retries (the tiled HTTP client's own
    # retry_context()/stamina backoff, well outside RunStreamer's control) --
    # up to roughly a minute in the slowest observed case. Generous timeout.
    assert _pump_qt_until(qapp, lambda: len(image_events) >= 1, timeout=90), \
        "image_updated never fired from the real Tiled-backed RunStreamer"

    # ---- 5. run_complete -> scanning becomes False ------------------------
    assert _pump_qt_until(qapp, lambda: controller.scanning is False, timeout=180), \
        "run never completed (controller.scanning stayed True)"
    assert False in scan_state_events

    # ---- 6. final image: shape (ny, nx), all-finite, matches Tiled --------
    final_image = image_events[-1]
    assert final_image.shape == (_NY, _NX)
    assert np.isfinite(final_image).all(), \
        f"final image has non-finite values: {final_image}"

    # Independent read-back: a *separate* Tiled client (not the one wired
    # into the RunStreamer/TiledWriter machinery) fetches the same run and
    # its primary stream, and the image is reassembled by hand from that
    # table -- proving the GUI's image is not just an artifact of internal
    # state but genuinely reflects what landed in Tiled.
    from tiled.client import from_uri

    independent_client = from_uri(
        lightfall_service.tiled_url, api_key=lightfall_service.tiled_token)
    try:
        run = independent_client[run_uid]
        table = run["primary"].read()
        column = table["STXMLineFlyer"]
        assert len(column) == _NY
        expected = np.stack([np.asarray(row, dtype=float) for row in column])
        assert expected.shape == (_NY, _NX)
        np.testing.assert_allclose(final_image, expected)
    finally:
        independent_client.context.close()

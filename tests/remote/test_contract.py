"""Live contract tests: the REAL LightfallClient against a REAL
RemoteControlService + real NATS + real sim IOC fleet + real Tiled
(spec #4 Task 8).

Uses the ``lightfall_service`` fixture (tests/remote/conftest.py), which
wires the real fleet devices (SampleX/SampleY/energy EpicsMotors + the
StxmLineFlyer) and the real ``stxm_fly_raster`` plan into a real
RemoteControlService. No fakes/stubs anywhere in this module.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from pystxmcontrol.remote.client import LightfallClient, RemoteError


class _ClientRunner:
    """Drives the async LightfallClient from sync test code on a thread,
    pumping the session's Qt event loop while waiting (mirrors lightfall's
    own tests/integration/test_remote_control_e2e.py::_ClientRunner --
    engine document signals cross threads via Qt, so a plain blocking
    future.result(timeout) would starve that queue for the whole call)."""

    def __init__(self, nats_url, prefix, qapp, app_name="stxm-remote-test"):
        self.client = LightfallClient(nats_url, prefix, app_name)
        self.qapp = qapp
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro, timeout=30.0):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        deadline = time.monotonic() + timeout
        while not future.done():
            self.qapp.processEvents()
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        return future.result(timeout=0.1)

    def close(self):
        try:
            self.run(self.client.close(), timeout=5)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=5)


def _pump_qt_until(qapp, predicate, timeout=30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def nats_url(lightfall_service):
    # LocalNatsServer URL isn't stored on the namespace; reconstruct it from
    # the IPCService, which was constructed with it.
    return lightfall_service.ipc._nats_url  # noqa: SLF001 - test-only introspection


@pytest.fixture
def client(lightfall_service, nats_url):
    runner = _ClientRunner(nats_url, lightfall_service.prefix, lightfall_service.qapp)
    runner.run(runner.client.connect())
    yield runner
    runner.close()


def _read_rbv_via_ca(pv: str, timeout: float = 10.0) -> float:
    """Independent CA read of ``<pv>.RBV`` -- verifies device.put actually
    moved hardware rather than trusting the reply alone."""
    from caproto.threading.client import Context

    ctx = Context()
    try:
        (rbv_pv,) = ctx.get_pvs(f"{pv}.RBV")
        rbv_pv.wait_for_connection(timeout=timeout)
        response = rbv_pv.read(data_type="time")
        return float(response.data[0])
    finally:
        ctx.disconnect()


def test_authenticate_returns_token_and_tiled_fields(lightfall_service, client):
    auth = client.run(client.client.authenticate())
    assert auth["status"] == "approved"
    assert auth["contract_version"] == 1
    assert client.client.session_token
    assert client.client.tiled_url == lightfall_service.tiled_url
    assert client.client.tiled_token == lightfall_service.tiled_token


def test_bare_subject_call_is_denied(client):
    reply = client.run(client.client.call_bare("commands.engine.status", {}))
    assert reply["status"] == "error"
    assert reply["code"] == "denied"


def _device_info_by_name(client, name):
    return client.run(client.client.call("commands.device.info", {"device": name}))


def test_device_search_and_info_expose_pv(lightfall_service, client):
    client.run(client.client.authenticate())

    search = client.run(client.client.call("commands.device.search", {}))
    devices = set(search["devices"])
    assert {"SampleX", "SampleY", "energy"} <= devices

    for name in ("SampleX", "SampleY", "energy"):
        info = _device_info_by_name(client, name)
        pv = info.get("pv")
        assert pv, (
            f"device.info for {name!r} has no 'pv' field ({info!r}). "
            "Check out branch 'feature/device-info-pv' in the lightfall "
            "checkout used by this venv."
        )
        assert pv == lightfall_service.motor_pv[name], (
            f"device.info pv {pv!r} for {name!r} does not match the fleet's "
            f"actual PV {lightfall_service.motor_pv[name]!r}"
        )


def test_device_put_moves_sample_y_verified_over_ca(lightfall_service, client):
    client.run(client.client.authenticate())
    assert _pump_qt_until(lightfall_service.qapp, lambda: lightfall_service.engine.is_idle,
                           timeout=30), "engine never warmed up"

    target = 3.0
    reply = client.run(
        client.client.call("commands.device.put", {"device": "SampleY", "value": target},
                            timeout=20)
    )
    assert reply["status"] == "ok"

    rbv = _read_rbv_via_ca(lightfall_service.motor_pv["SampleY"])
    assert rbv == pytest.approx(target, abs=0.05)
    assert lightfall_service.motor_y.position == pytest.approx(target, abs=0.05)


def test_plan_list_contains_stxm_fly_raster(client):
    client.run(client.client.authenticate())
    plans = client.run(client.client.call("commands.plan.list", {}))["plans"]
    assert any(p["name"] == "stxm_fly_raster" for p in plans)


def test_busy_rejection_while_plan_runs(lightfall_service, client):
    client.run(client.client.authenticate())
    assert _pump_qt_until(lightfall_service.qapp, lambda: lightfall_service.engine.is_idle,
                           timeout=30), "engine never warmed up"

    # A slow-enough raster (small but nonzero dwell, several rows) to observe
    # the engine mid-flight without dragging the test out.
    reply = client.run(
        client.client.call(
            "commands.plan.run",
            {
                "plan_name": "stxm_fly_raster",
                "params": {
                    "y_start": -2.0, "y_stop": 2.0, "ny": 20,
                    "x_start": -2.0, "x_stop": 2.0, "nx": 20,
                    "dwell": 20.0,
                },
            },
            timeout=20,
        )
    )
    assert reply["status"] == "submitted"

    def _is_running() -> bool:
        status = client.run(client.client.call("commands.engine.status", {}))
        return status["state"] == "running"

    assert _pump_qt_until(lightfall_service.qapp, _is_running, timeout=20), \
        "engine never reported running"

    with pytest.raises(RemoteError) as exc_info:
        client.run(
            client.client.call("commands.plan.run",
                                {"plan_name": "stxm_fly_raster", "params": {}})
        )
    assert exc_info.value.code == "busy"

    with pytest.raises(RemoteError) as exc_info:
        client.run(
            client.client.call("commands.device.put",
                                {"device": "SampleY", "value": 0.0})
        )
    assert exc_info.value.code == "busy"

    def _is_idle_again() -> bool:
        status = client.run(client.client.call("commands.engine.status", {}))
        return status["state"] == "idle"

    assert _pump_qt_until(lightfall_service.qapp, _is_idle_again, timeout=30), \
        "engine never returned to idle -- long raster leaked into next test"

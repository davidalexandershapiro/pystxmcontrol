"""Stub NATS for unit-testing LightfallClient without a broker."""
import json

import pytest


class _StubMsg:
    def __init__(self, data: bytes):
        self.data = data


class StubNats:
    """Duck-types the nats-py client surface LightfallClient uses."""

    def __init__(self):
        self.handlers = {}       # exact subject -> callable(payload dict) -> dict
        self.subscriptions = {}  # subject -> cb
        self.requests = []       # (subject, payload) log

    async def request(self, subject, data, timeout=None):
        payload = json.loads(data.decode())
        self.requests.append((subject, payload))
        for pat, handler in self.handlers.items():
            if subject == pat or (pat.endswith(".*") and subject.startswith(pat[:-1])):
                return _StubMsg(json.dumps(handler(subject, payload)).encode())
        raise TimeoutError(f"no stub handler for {subject}")

    async def subscribe(self, subject, cb=None):
        self.subscriptions[subject] = cb

    async def drain(self):
        pass


async def stub_connect_factory(stub):
    async def _connect(url):
        return stub
    return _connect


# ---- EPICS fleet fixture (ported from spec #3, lightfall-pystxmcontrol) ---
import os
import random
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parent
_DATA_DIR = _HERE / "data"
# This worktree lives at <plugin-repo>/_pystxmcontrol_remote_wt and the iocs
# worktree at <plugin-repo>/_pystxmcontrol_iocs_wt: conftest.py -> parents[0]
# = tests/remote, [1] = tests, [2] = worktree root, so .parents[2].parent is
# the plugin repo root. PYSTXMCONTROL_IOCS_SRC env var overrides.
_DEFAULT_IOCS_SRC = (
    Path(__file__).resolve().parents[2].parent / "_pystxmcontrol_iocs_wt")


@pytest.fixture(scope="session")
def iocs_src() -> Path:
    src = Path(os.environ.get("PYSTXMCONTROL_IOCS_SRC", _DEFAULT_IOCS_SRC))
    if not (src / "pystxmcontrol" / "iocs" / "supervisor.py").exists():
        pytest.fail(
            f"spec-#2 IOC layer not found at {src}. Set PYSTXMCONTROL_IOCS_SRC "
            "to the pystxmcontrol fork checkout (branch feature/caproto-iocs).")
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    # This worktree's own "pystxmcontrol" package (remote/*) is also on
    # sys.path (installed editable / PYTHONPATH=cwd for the test run) and,
    # being a regular (non-namespace) package, wins the first import and
    # shadows the iocs_src copy entirely -- `import pystxmcontrol.iocs` would
    # otherwise fail with ModuleNotFoundError even though iocs_src is on
    # sys.path. Extend the already-imported package's __path__ so submodule
    # lookups (pystxmcontrol.iocs, pystxmcontrol.drivers, ...) also search
    # iocs_src's copy.
    import pystxmcontrol as _pystxmcontrol
    iocs_pkg_dir = str(src / "pystxmcontrol")
    if iocs_pkg_dir not in _pystxmcontrol.__path__:
        _pystxmcontrol.__path__.append(iocs_pkg_dir)
    return src


_issued_udp_ports: set[int] = set()


def _free_udp_port() -> int:
    """Find a UDP port free at bind-time and not already handed out this session.

    Binding and releasing only proves the port was free at that instant; a
    later call in the same fleet spawn loop could re-discover the same port
    before the first IOC has claimed it (TOCTOU). Track issued ports across
    calls so sequential spawns never collide with each other.
    """
    for _ in range(50):
        port = random.randint(40000, 60000)
        if port in _issued_udp_ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                _issued_udp_ports.add(port)
                return port
            except OSError:
                continue
    raise RuntimeError("no free UDP port found")


@pytest.fixture(scope="session")
def stxm_fleet(iocs_src, tmp_path_factory):
    """Spawn the full sim IOC fleet (spec-#2 supervisor plan) once per session.

    Uses the sim_motor.json / sim_daq.json copied locally into
    tests/remote/data/ rather than reaching across into the
    lightfall_pystxmcontrol plugin package (this repo is a separate
    checkout/worktree of pystxmcontrol itself).
    """
    import netifaces  # noqa: F401  (required optional caproto dep; fail fast)
    os.environ.setdefault("OPHYD_CONTROL_LAYER", "caproto")
    from pystxmcontrol.iocs.config import load_fleet
    from pystxmcontrol.iocs.supervisor import plan_fleet

    slice_dir = tmp_path_factory.mktemp("stxm_slices")
    fleet = load_fleet(str(_DATA_DIR / "sim_motor.json"),
                        str(_DATA_DIR / "sim_daq.json"), station="SIM")

    _DAQ_KEY = "default"  # sim_daq.json key; matches lightfall_pystxmcontrol.flyer
    assert fleet.daqs[0].key == _DAQ_KEY, (
        f"fleet daq key {fleet.daqs[0].key!r} != expected {_DAQ_KEY!r}; "
        "sim_daq.json was likely renamed/restructured (fails fast here "
        "instead of hanging on a PV connect below)")

    plans = plan_fleet(fleet, str(slice_dir))

    addr_entries: list[str] = []
    procs: list[subprocess.Popen] = []
    for plan in plans:
        port = _free_udp_port()
        addr_entries.append(f"127.0.0.1:{port}")
        env = dict(os.environ)
        env.update({
            "EPICS_CAS_SERVER_PORT": str(port),
            "EPICS_CA_SERVER_PORT": str(port),   # caproto server binds via this
            "EPICS_CA_ADDR_LIST": " ".join(addr_entries),
            "EPICS_CA_AUTO_ADDR_LIST": "NO",
            "PYTHONPATH": str(iocs_src),
        })
        procs.append(subprocess.Popen(
            [sys.executable, "-m", plan.module, "--slice", plan.slice_path,
             "--quiet"],
            env=env, cwd=str(iocs_src)))
        time.sleep(0.5)

    addr_list = " ".join(addr_entries)
    saved_env = {k: os.environ.get(k)
                 for k in ("EPICS_CA_ADDR_LIST", "EPICS_CA_AUTO_ADDR_LIST")}
    os.environ["EPICS_CA_ADDR_LIST"] = addr_list
    os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
    try:
        time.sleep(3.0)
        dead = [p.args for p in procs if p.poll() is not None]
        assert not dead, f"IOC(s) exited early: {dead}"

        e712_label = next(g.label for g in fleet.controller_groups
                          if g.controller_cls == "E712Controller")
        yield SimpleNamespace(
            addr_list=addr_list,
            motor_pv=fleet.motor_pv,
            fly_prefix=f"STXMSIM:{e712_label}:FLY",
            daq_prefix=fleet.daqs[0].prefix,
        )
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
        for key, prior in saved_env.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


# ---- Real Lightfall RemoteControlService fixture (Task 8) -----------------
#
# Wires a REAL lightfall.remote.service.RemoteControlService (real NATS via
# lightfall.ipc.local_server.LocalNatsServer, real BlueskyEngine, real
# TrustManager pre-approved), backed by:
#   - the sim IOC fleet (stxm_fleet) via real ophyd EpicsMotor devices for
#     SampleX/SampleY/energy and a real StxmLineFlyer for the FLY PVGroup;
#   - a duck-typed catalog (mirrors lightfall's own
#     tests/integration/test_remote_control_e2e.py::_Catalog pattern rather
#     than booting a full lightfall Application/PluginManager/GUI, which
#     would be disproportionate for exercising the remote contract);
#   - the stxm_fly_raster plan, bound directly to the real flyer/y-axis and
#     registered into lightfall's process-wide PlanRegistry singleton;
#   - a real (uvicorn, real TCP port) Tiled server via
#     tiled.server.SimpleTiledServer, with a TiledWriter subscribed to the
#     real RunEngine so runs actually land and are independently readable.
#
# Session-scoped and depends on stxm_fleet so EPICS_CA_ADDR_LIST/the fleet
# IOCs are up before any EpicsMotor/StxmLineFlyer tries to connect.

import inspect as _inspect
from types import SimpleNamespace as _SimpleNamespace
from urllib.parse import urlparse as _urlparse


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _assert_lightfall_has_pv_field() -> None:
    """Fail fast (not skip) if lightfall isn't on feature/device-info-pv.

    device.info replies must carry a ``pv`` field (spec #4 Task 1); rather
    than shelling out to git (this checkout may be a worktree/site-packages
    install with no .git at all), check the actual behavior we depend on:
    RemoteControlService._handle_device_info must emit ``pv=...`` in its
    reply. If it doesn't, every test here would fail confusingly deep inside
    the contract assertions instead of with an actionable message.
    """
    from lightfall.remote import service as _lf_service_mod

    src = _inspect.getsource(_lf_service_mod)
    if "pv=" not in src or "getattr(info, \"prefix\"" not in src.replace("'", '"'):
        pytest.fail(
            "lightfall's RemoteControlService.device.info reply has no 'pv' "
            "field. Check out branch 'feature/device-info-pv' (or its "
            "merge target) in the lightfall checkout used by this venv "
            "before running tests/remote/test_contract.py / "
            "test_e2e_gui.py."
        )


@pytest.fixture(scope="session")
def lightfall_nats_url():
    from lightfall.ipc.local_server import LocalNatsServer, resolve_nats_binary

    if resolve_nats_binary() is None:
        pytest.skip("nats-server binary not available (install extra local-nats)")
    port = _free_port()
    server = LocalNatsServer(port=port)
    server.start(timeout_s=10.0)
    yield f"nats://127.0.0.1:{port}"
    server.stop()


@pytest.fixture(scope="session")
def qapp_session():
    """One process-wide Qt application for the session-scoped service fixture
    to pump events on while waiting for NATS/engine warm-up."""
    from PySide6.QtCore import QCoreApplication
    from PySide6 import QtWidgets

    app = QCoreApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _pump_qt_until_session(qapp, predicate, timeout=30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture(scope="session")
def lightfall_service(stxm_fleet, lightfall_nats_url, qapp_session):
    """Real RemoteControlService + real fleet devices/plan + real Tiled.

    Yields a SimpleNamespace with: ipc, trust, engine, remote, prefix,
    catalog, motor_pv (name -> pv), tiled_url, tiled_token, tiled_client
    (a from_uri client independent of any LightfallClient, for cross-checks).
    """
    _assert_lightfall_has_pv_field()

    from lightfall.acquire.engine import get_engine, reset_engine
    from lightfall.acquire.plans.registry import get_registry
    from lightfall.devices.model import DeviceCategory, DeviceInfo
    from lightfall.ipc.service import IPCService
    from lightfall.ipc.trust import TrustManager, TrustState
    from lightfall.remote.service import RemoteControlService
    from lightfall.utils.threads import initialize_main_thread_invoker

    try:
        initialize_main_thread_invoker()
    except RuntimeError:
        pass  # already initialized by an earlier test/fixture in this process

    # Import AFTER stxm_fleet has set OPHYD_CONTROL_LAYER=caproto: these
    # modules build ophyd EpicsSignal-backed objects whose control layer is
    # selected at ophyd import time, so importing them before the fleet
    # fixture ran would silently pick the wrong (pyepics) control layer.
    from ophyd import EpicsMotor

    from lightfall_pystxmcontrol.flyer import StxmLineFlyer
    from lightfall_pystxmcontrol.plans import stxm_fly_raster

    motor_pv = dict(stxm_fleet.motor_pv)
    motor_x = EpicsMotor(motor_pv["SampleX"], name="SampleX")
    motor_y = EpicsMotor(motor_pv["SampleY"], name="SampleY")
    motor_e = EpicsMotor(motor_pv["energy"], name="energy")
    flyer = StxmLineFlyer(stxm_fleet.fly_prefix, name="STXMLineFlyer")
    for dev in (motor_x, motor_y, motor_e, flyer):
        dev.wait_for_connection(timeout=20)

    devices = {
        "SampleX": (
            DeviceInfo(name="SampleX", category=DeviceCategory.MOTOR,
                       device_class="ophyd.EpicsMotor", prefix=motor_pv["SampleX"]),
            motor_x,
        ),
        "SampleY": (
            DeviceInfo(name="SampleY", category=DeviceCategory.MOTOR,
                       device_class="ophyd.EpicsMotor", prefix=motor_pv["SampleY"]),
            motor_y,
        ),
        "energy": (
            DeviceInfo(name="energy", category=DeviceCategory.MOTOR,
                       device_class="ophyd.EpicsMotor", prefix=motor_pv["energy"]),
            motor_e,
        ),
    }

    class _Catalog:
        def list_devices(self, **kw):
            return [info for info, _ in devices.values()]

        def get_device_by_name(self, name):
            pair = devices.get(name)
            return pair[0] if pair else None

        def get_ophyd_device(self, name):
            pair = devices.get(name)
            return pair[1] if pair else None

    catalog = _Catalog()

    # Bind + register the real stxm_fly_raster plan (params exactly matching
    # scan_mapping.map_scan's stxm_fly_raster output: y_start/y_stop/ny/
    # x_start/x_stop/nx/dwell) against the real flyer + Y axis.
    def _stxm_fly_raster_bound(*, y_start, y_stop, ny, x_start, x_stop, nx, dwell):
        return (yield from stxm_fly_raster(
            flyer, motor_y, y_start=y_start, y_stop=y_stop, ny=ny,
            x_start=x_start, x_stop=x_stop, nx=nx, dwell=dwell))

    registry = get_registry()
    if "stxm_fly_raster" not in registry:
        registry.register("stxm_fly_raster", _stxm_fly_raster_bound, category="stxm")

    reset_engine()
    engine = get_engine("bluesky")

    prefix = "als.stxmtest"
    ipc = IPCService(nats_url=lightfall_nats_url, topic_prefix=prefix)
    trust = TrustManager()
    trust.approve("stxm-remote-test")
    ipc.set_trust_manager(trust)
    ipc.register_meta_endpoints()

    # Real (uvicorn, real TCP port) Tiled server -- LightfallClient.tiled_client()
    # makes real HTTP calls via tiled.client.from_uri, so an ASGI-only
    # Context.from_app() client (as lightfall's own test_run_lands_in_tiled
    # uses) is not sufficient here.
    #
    # NOT using tiled.server.SimpleTiledServer: it hardcodes a duckdb:///
    # SQLStorage backend for the "internal" (non-array event data) table,
    # and this venv's Python (3.14) has no adbc_driver_duckdb wheel
    # available -- every create_appendable_table() call for ANY run with
    # real event data (not just start/stop docs) 500s server-side on the
    # missing import, and the client's retry_context() then re-POSTs the
    # same (non-idempotent) create, which 409s because the metadata record
    # from the first, failed attempt already exists. Reproduced in
    # isolation with a bare RunEngine + ophyd.sim signals + TiledWriter --
    # nothing to do with pystxmcontrol/lightfall code. Root-caused via:
    # sqlite:/// storage instead of duckdb:/// (adbc_driver_sqlite IS
    # available for this Python) avoids the missing-driver 500/409 entirely.
    # sqlite's SQL dialect additionally has no list/array column type, so
    # array-shaped data_keys (X positions, detector counts) must clear
    # bluesky_tiled_plugins.writing.tiled_writer.MAX_ARRAY_SIZE (16
    # elements) to be routed to the zarr array-write path instead of an
    # embedded list column in the "internal" table -- callers must use
    # nx (or any array-shaped column length) > 16 in any plan run against
    # this fixture.
    import pathlib
    import tempfile
    import threading

    import uvicorn
    from tiled.catalog import in_memory as tiled_in_memory
    from tiled.config import Authentication
    from tiled.server.app import build_app

    tiled_api_key = "stxmremotetestkey123"  # must be alphanumeric-only (tiled requirement)
    tiled_dir = pathlib.Path(tempfile.mkdtemp(prefix="stxm_remote_test_tiled_"))
    (tiled_dir / "data").mkdir(parents=True, exist_ok=True)
    tiled_storage_uri = f"sqlite:///{tiled_dir / 'storage.sqlite'}"
    tiled_catalog = tiled_in_memory(
        writable_storage=[tiled_dir / "data", tiled_storage_uri])
    tiled_app = build_app(
        tiled_catalog,
        authentication=Authentication(single_user_api_key=tiled_api_key))

    class _ThreadedTiledServer(uvicorn.Server):
        def install_signal_handlers(self) -> None:
            pass  # not the main thread; would raise

    tiled_uvicorn_config = uvicorn.Config(
        tiled_app, host="127.0.0.1", port=0, loop="asyncio")
    tiled_uvicorn_server = _ThreadedTiledServer(config=tiled_uvicorn_config)
    tiled_thread = threading.Thread(target=tiled_uvicorn_server.run, daemon=True)
    tiled_thread.start()
    for _ in range(200):
        time.sleep(0.1)
        if tiled_uvicorn_server.started:
            break
    else:
        pytest.fail("Tiled server did not start in 20 seconds.")
    _tiled_host, _tiled_port = (
        tiled_uvicorn_server.servers[0].sockets[0].getsockname())
    tiled_url = f"http://{_tiled_host}:{_tiled_port}"

    def handle_auth(subject, data, reply):
        app_name = data.get("app_name", "unknown")
        if ipc.evaluate_trust(app_name) == TrustState.APPROVED:
            resp = {
                "status": "approved",
                "contract_version": 1,
                "tiled_url": tiled_url,
                "tiled_token": tiled_api_key,
            }
            resp["session_token"] = ipc.mint_session_channel(app_name)
            ipc.reply(reply, resp)
        else:
            ipc.reply(reply, {"status": "denied", "contract_version": 1})

    ipc.register_action("auth.request", handle_auth, main_thread=False)

    remote = RemoteControlService(ipc, engine=engine, catalog=catalog)
    remote.start()
    ipc.start()

    assert _pump_qt_until_session(qapp_session, lambda: ipc.is_connected, timeout=15), \
        "IPCService never connected to the local NATS server"

    # Wait for the BlueskyEngine's RunEngine to boot on its worker thread,
    # then attach a TiledWriter so runs actually land (mirrors lightfall's
    # own test_run_lands_in_tiled wiring, but against a real Tiled server).
    assert _pump_qt_until_session(qapp_session, lambda: engine.RE is not None, timeout=30), \
        "BlueskyEngine.RE never booted"
    assert _pump_qt_until_session(qapp_session, lambda: engine.is_idle, timeout=30), \
        "engine never reached idle after boot"

    from bluesky_tiled_plugins import TiledWriter
    from tiled.client import from_uri

    tiled_client = from_uri(tiled_url, api_key=tiled_api_key)
    writer_token = engine.RE.subscribe(TiledWriter(tiled_client))

    yield _SimpleNamespace(
        ipc=ipc, trust=trust, engine=engine, remote=remote, prefix=prefix,
        catalog=catalog, motor_pv=motor_pv, tiled_url=tiled_url,
        tiled_token=tiled_api_key, tiled_client=tiled_client,
        motor_x=motor_x, motor_y=motor_y, motor_e=motor_e, flyer=flyer,
        qapp=qapp_session,
    )

    try:
        engine.RE.unsubscribe(writer_token)
    except Exception:
        pass
    remote.stop()
    ipc.stop()
    reset_engine()
    for dev in (motor_x, motor_y, motor_e, flyer):
        try:
            dev.destroy()
        except Exception:
            pass
    try:
        tiled_uvicorn_server.should_exit = True
        tiled_thread.join(timeout=10)
    except Exception:
        pass

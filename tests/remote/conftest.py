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

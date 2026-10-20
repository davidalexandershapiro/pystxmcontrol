"""Shared IOC test harness: run a caproto asyncio server in a thread on a random port."""
import asyncio
import os
import random
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from caproto.threading.client import Context


def _free_udp_port() -> int:
    for _ in range(50):
        port = random.randint(40000, 60000)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port found")


class IocHarness:
    def __init__(self):
        self.port = _free_udp_port()
        self._loop = None
        self._thread = None
        self._started = threading.Event()

    def start(self, pvdb: dict):
        os.environ["EPICS_CA_ADDR_LIST"] = f"127.0.0.1:{self.port}"
        os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
        os.environ["EPICS_CAS_SERVER_PORT"] = str(self.port)
        # Client-side search (get_pvs/Context) uses EPICS_CA_SERVER_PORT, not
        # EPICS_CAS_SERVER_PORT (that one's server-side only) -- without this
        # the threading Context searches on the default port 5064 and the PV
        # search silently times out.
        os.environ["EPICS_CA_SERVER_PORT"] = str(self.port)

        def runner():
            from caproto.asyncio.server import start_server
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def main():
                self._started.set()
                await start_server(pvdb, interfaces=["127.0.0.1"])

            try:
                self._loop.run_until_complete(main())
            except (asyncio.CancelledError, RuntimeError):
                # RuntimeError: "Event loop stopped before Future completed"
                # -- expected on the teardown path (_shutdown cancels tasks
                # and stops the loop from another thread mid-await).
                pass

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
        assert self._started.wait(10), "IOC server thread failed to start"
        time.sleep(0.5)  # let the server bind before clients connect
        return self

    def client(self) -> Context:
        return Context()

    def call_soon(self, coro):
        """Schedule a coroutine on the IOC loop (e.g. server-side writes)."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)


@pytest.fixture
def ioc_harness():
    h = IocHarness()
    yield h
    # daemon thread; loop dies with the process. Stop the loop politely and
    # wait for the thread to actually exit -- a bare loop.stop() leaves
    # pending tasks (caproto's UDP broadcaster_queue_loop) which, once their
    # bound Queue outlives the loop, spin in a tight raise/retry loop that
    # pegs a CPU core and floods stderr for the rest of the process's life.
    if h._loop is not None:
        def _shutdown():
            for task in asyncio.all_tasks(loop=h._loop):
                task.cancel()
            h._loop.stop()

        h._loop.call_soon_threadsafe(_shutdown)
    if h._thread is not None:
        h._thread.join(timeout=5)


@pytest.fixture
def slow_sim_motor():
    """xpsMotor in sim mode with an artificial per-move duration, for DMOV tests."""
    from pystxmcontrol.drivers.xpsMotor import xpsMotor

    class SlowSimController:
        simulation = True
        moving = False

    class SlowSimMotor(xpsMotor):
        move_duration = 0.5

        def moveTo(self, pos):
            if self.checkLimits(pos):
                deadline = time.time() + self.move_duration
                self._stop_requested = False
                start = self._controller_position
                while time.time() < deadline:
                    if getattr(self, "_stop_requested", False):
                        return
                    frac = 1 - (deadline - time.time()) / self.move_duration
                    self._controller_position = start + frac * (pos - start)
                    time.sleep(0.02)
                self._controller_position = pos

        def stop(self):
            self._stop_requested = True

    m = SlowSimMotor()
    m.controller = SlowSimController()
    m.config = {"units": 1, "offset": 0, "minValue": -40, "maxValue": 40,
                "max velocity": 1000.0, "simulation": 1}
    m.simulation = True
    return m


@pytest.fixture
def free_port(monkeypatch):
    port = _free_udp_port()
    monkeypatch.setenv("EPICS_CA_ADDR_LIST", f"127.0.0.1:{port}")
    monkeypatch.setenv("EPICS_CA_AUTO_ADDR_LIST", "NO")
    monkeypatch.setenv("EPICS_CAS_SERVER_PORT", str(port))
    # Client-side search (Context/get_pvs in this test process) uses
    # EPICS_CA_SERVER_PORT, not EPICS_CAS_SERVER_PORT (server-side only) --
    # see ioc_harness.start() above for the same gotcha.
    monkeypatch.setenv("EPICS_CA_SERVER_PORT", str(port))
    return port


@pytest.fixture
def spawn_ioc(monkeypatch):
    """Spawn a motor/derived IOC subprocess.

    Multi-IOC tests (e.g. a controller IOC + a derived_remote IOC that is
    itself a CA client of the former) can't share one
    EPICS_CAS_SERVER_PORT -- each server needs its own port. So this fixture
    allocates a FRESH port on every call (the ``port`` argument passed in by
    callers -- typically the single value from the ``free_port`` fixture --
    is accepted for signature compatibility but ignored) and accumulates
    ``127.0.0.1:<port>`` into a shared address list for the whole fixture.

    Because caproto's EPICS_CA_ADDR_LIST entries carry an explicit port per
    host (``host:port``), a client Context search does not strictly NEED
    EPICS_CA_SERVER_PORT once every address in the list is fully qualified --
    that variable only supplies a default port for addr-list entries that
    omit one, which none of ours do. Empirically, though, unsetting it
    entirely regresses the existing single-IOC test
    (test_motor_ioc_subprocess), so it is still set here -- just to the
    latest spawned IOC's own port, since with fully-qualified addr-list
    entries its value is otherwise a no-op. This is set both in
    ``os.environ`` (for in-test ``Context()`` instances the caller constructs
    afterwards) and in every spawned child's env -- the derived IOC is itself
    a CA client of the motor IOCs, so it needs the full accumulated list too,
    not just its own port.
    """
    procs = []
    addrs: list[str] = []

    def _spawn(module: str, slice_path: str, port: int = None):
        new_port = _free_udp_port()
        addrs.append(f"127.0.0.1:{new_port}")
        addr_list = " ".join(addrs)

        monkeypatch.setenv("EPICS_CA_ADDR_LIST", addr_list)
        monkeypatch.setenv("EPICS_CA_AUTO_ADDR_LIST", "NO")
        monkeypatch.setenv("EPICS_CAS_SERVER_PORT", str(new_port))
        monkeypatch.setenv("EPICS_CA_SERVER_PORT", str(new_port))

        env = dict(os.environ)
        env.update({
            "EPICS_CAS_SERVER_PORT": str(new_port),
            "EPICS_CA_ADDR_LIST": addr_list,
            "EPICS_CA_AUTO_ADDR_LIST": "NO",
            "EPICS_CA_SERVER_PORT": str(new_port),
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        })
        p = subprocess.Popen([sys.executable, "-m", module, "--slice", slice_path],
                             env=env)
        procs.append(p)
        time.sleep(3.0)  # IOC startup (driver connect + server bind)
        assert p.poll() is None, f"{module} exited early with {p.returncode}"
        return p

    yield _spawn
    for p in procs:
        if p.poll() is None:
            p.terminate()
            p.wait(timeout=10)

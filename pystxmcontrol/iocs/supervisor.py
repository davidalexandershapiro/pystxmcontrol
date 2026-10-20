"""stxm-iocs: parse motor.json/daq.json, run one caproto IOC per controller.

    stxm-iocs --station 7011 --motor-config /path/motor.json --daq-config /path/daq.json
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from pystxmcontrol.iocs import require_caproto

require_caproto()

from pystxmcontrol.iocs.config import (  # noqa: E402
    FLY_CAPABLE_CONTROLLERS, FleetConfig, load_fleet, write_slice)


@dataclass
class IocPlan:
    name: str
    module: str | None  # None -> run slice_path as a plain script (tests)
    slice_path: str
    delay: float = 0.0


def plan_fleet(fleet: FleetConfig, slice_dir: str,
               shutter_iocs: bool = True, startup_delay: float = 3.0) -> list[IocPlan]:
    Path(slice_dir).mkdir(parents=True, exist_ok=True)
    plans: list[IocPlan] = []
    fly_groups = [g for g in fleet.controller_groups
                  if g.controller_cls in FLY_CAPABLE_CONTROLLERS]
    if len(fly_groups) > 1:
        raise ValueError(
            f"plan_fleet: {len(fly_groups)} fly-capable controller groups found "
            f"({[g.label for g in fly_groups]}); every fly group absorbs "
            "ALL daq entries, so multiple fly controllers would duplicate "
            "DAQ PVs across IOCs and give two controllers ownership of the "
            "same hardware. Multi-fly DAQ mapping is a follow-up "
            "(see docs/superpowers/2026-07-12-caproto-iocs-followups.md).")
    fly_ids = {id(g) for g in fly_groups}
    daqs_absorbed = bool(fly_groups)
    for g in fleet.controller_groups:
        p = str(Path(slice_dir) / f"{g.label}.json")
        if id(g) in fly_ids:
            write_slice(g, fleet, p, daqs=fleet.daqs)
            plans.append(IocPlan(name=g.label, module="pystxmcontrol.iocs.fly_ioc",
                                 slice_path=p))
        else:
            write_slice(g, fleet, p)
            plans.append(IocPlan(name=g.label, module="pystxmcontrol.iocs.motor_ioc",
                                 slice_path=p))
    if not daqs_absorbed:
        for d in fleet.daqs:
            p = str(Path(slice_dir) / f"daq_{d.key}.json")
            write_slice(d, fleet, p)
            plans.append(IocPlan(name=f"daq_{d.key}",
                                 module="pystxmcontrol.iocs.daq_ioc", slice_path=p))
    if shutter_iocs:
        for sh in fleet.shutters:
            p = str(Path(slice_dir) / f"{sh.key}.json")
            write_slice(sh, fleet, p)
            plans.append(IocPlan(name=sh.key,
                                 module="pystxmcontrol.iocs.shutter_ioc", slice_path=p))
    for d in fleet.derived_remote:  # LAST: they are CA clients of the above
        p = str(Path(slice_dir) / f"derived_{d.key}.json")
        write_slice(d, fleet, p)
        plans.append(IocPlan(name=f"derived_{d.key}",
                             module="pystxmcontrol.iocs.derived_ioc",
                             slice_path=p, delay=startup_delay))
    return plans


def _free_udp_port() -> int:
    """Find a free UDP port on 127.0.0.1.

    Copied (not imported) from tests/iocs/conftest.py: supervisor.py must not
    depend on the test tree.
    """
    for _ in range(50):
        port = random.randint(40000, 60000)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free port found")


def _make_pdeathsig_preexec():
    """Return a POSIX ``preexec_fn`` that asks the kernel to SIGTERM this child
    if the supervisor dies for ANY reason -- crucially including SIGKILL, which
    the supervisor itself can't catch and clean up after. Without it, a -9'd (or
    crashed) supervisor leaves every IOC orphaned to init, still holding
    hardware (e.g. the nPoint FTDI handle).

    libc/prctl are resolved here at import time (main thread), so the post-fork
    callback only makes bare syscalls -- no imports, allocations, or logging --
    keeping it as close to async-signal-safe as a Python preexec_fn gets (it
    runs after fork() in a child of a multithreaded process). Returns None where
    unsupported (non-Linux), so _spawn passes ``preexec_fn=None`` there.
    """
    if not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
    except Exception:
        return None
    PR_SET_PDEATHSIG = 1
    sigterm = int(signal.SIGTERM)

    def _preexec():
        libc.prctl(PR_SET_PDEATHSIG, sigterm, 0, 0, 0)
        # Race guard: if the supervisor already died between fork() and here,
        # we've been reparented to init -- exit now instead of lingering (the
        # parent-death signal only fires on a FUTURE parent death).
        if os.getppid() == 1:
            os._exit(0)

    return _preexec


# Resolved once at import (main thread); reused for every child spawn.
_PDEATHSIG_PREEXEC = _make_pdeathsig_preexec()


class Supervisor:
    def __init__(self, plans: list[IocPlan],
                 restart_backoff=(1, 2, 4, 8, 16, 30),
                 status_prefix: str | None = None,
                 status_interval: float = 0.0,
                 shared_ca_port: bool = False,
                 ca_host: str = "127.0.0.1",
                 slice_dir: str | None = None,
                 quiet_iocs: bool = False):
        self._plans = plans
        self._backoff = restart_backoff
        self._status_prefix = status_prefix
        self._status_interval = status_interval
        self._quiet_iocs = quiet_iocs
        self._procs: dict[str, subprocess.Popen | None] = {}
        self._restarts: dict[str, int] = {p.name: 0 for p in plans}
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []
        # Serializes writes to our own stdout: one relay thread per running
        # IOC plus the status table loop all print concurrently, so without
        # this a PV-list line can interleave mid-line with the status table.
        self._io_lock = threading.Lock()
        self._status_loop: asyncio.AbstractEventLoop | None = None
        self._status_channels: dict[str, tuple] = {}
        self._shared_ca_port = shared_ca_port
        self._ca_host = ca_host
        self._slice_dir = slice_dir
        # Per-IOC CA server ports + the accumulated address list, allocated
        # once so a crashed IOC restarts on the SAME port (clients reconnect
        # instead of racing a new one). Empty/unused when shared_ca_port=True.
        self._ports: dict[str, int] = {}
        self._addr_list: str = ""

    def _allocate_ports(self):
        if self._shared_ca_port:
            return
        for p in self._plans:
            self._ports[p.name] = _free_udp_port()
        self._addr_list = " ".join(
            f"{self._ca_host}:{self._ports[p.name]}" for p in self._plans)
        print(f"[stxm-iocs] EPICS_CA_ADDR_LIST={self._addr_list}")
        print("[stxm-iocs] (status server itself stays on the default CA port "
              "-- caget STXM<station>:SUP:... needs no special addr list)")
        if self._slice_dir:
            addr_file = Path(self._slice_dir) / "EPICS_CA_ADDR_LIST.txt"
            addr_file.write_text(self._addr_list + "\n")
            print(f"[stxm-iocs] addr list written to {addr_file}")

    # -- process control ---------------------------------------------------
    def _spawn(self, plan: IocPlan) -> subprocess.Popen:
        if plan.module is None:
            cmd = [sys.executable, plan.slice_path]
        else:
            cmd = [sys.executable, "-m", plan.module, "--slice", plan.slice_path]
            if self._quiet_iocs:
                cmd.append("--quiet")
        env = dict(os.environ)
        env.setdefault("PYTHONPATH", str(Path(__file__).resolve().parents[2]))
        # Children write to a pipe now (see stdout=PIPE below); force unbuffered
        # so their banner/PV-list lines reach our relay promptly instead of
        # sitting in a block buffer until the pipe fills or the IOC exits.
        env["PYTHONUNBUFFERED"] = "1"
        if not self._shared_ca_port and plan.name in self._ports:
            # NOTE: this caproto version's server binds using
            # EPICS_CA_SERVER_PORT (see caproto/server/common.py Context.__init__
            # -- "the default tcp/udp port from the environment"), NOT
            # EPICS_CAS_SERVER_PORT despite the latter existing as a distinct
            # env var name. Set both: CAS_SERVER_PORT for spec-correctness /
            # forward-compat, CA_SERVER_PORT because that's what this caproto
            # actually reads.
            env["EPICS_CAS_SERVER_PORT"] = str(self._ports[plan.name])
            env["EPICS_CA_SERVER_PORT"] = str(self._ports[plan.name])
            env["EPICS_CA_ADDR_LIST"] = self._addr_list
            env["EPICS_CA_AUTO_ADDR_LIST"] = "NO"
        # Capture the child's stdout+stderr on one pipe so we can relay it to
        # our own stdout tagged by IOC name (see _pump_output). Without this
        # the caproto startup banner and PV-name list -- which each IOC now
        # logs via configure_ioc_logging -- would either scatter unlabeled
        # across the shared console or be lost entirely when the supervisor's
        # stdout is redirected to a file/journal.
        return subprocess.Popen(
            cmd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            # Kernel-enforced cleanup: SIGTERM this IOC if the supervisor dies
            # for any reason (incl. SIGKILL/crash), so it can never outlive us
            # as an orphan. None (non-Linux) leaves default behavior.
            preexec_fn=_PDEATHSIG_PREEXEC)

    def _pump_output(self, name: str, proc: subprocess.Popen):
        """Relay one child's merged stdout/stderr to ours, line by line,
        prefixed with the IOC name. Runs on its own daemon thread and returns
        when the child's pipe reaches EOF (i.e. the process has exited)."""
        stream = proc.stdout
        if stream is None:  # e.g. a test double that didn't open a pipe
            return
        prefix = f"[{name}] "
        try:
            for line in stream:
                text = prefix + line.rstrip("\n") + "\n"
                with self._io_lock:
                    sys.stdout.write(text)
                    sys.stdout.flush()
        except (ValueError, OSError):
            # stream closed underneath us during shutdown -- nothing to relay
            return

    def _monitor(self, plan: IocPlan):
        if plan.delay and self._stopping.wait(plan.delay):
            return
        attempt = 0
        while not self._stopping.is_set():
            proc = self._spawn(plan)
            self._procs[plan.name] = proc
            # Fresh pipe per (re)spawn, so a fresh relay thread per (re)spawn;
            # each ends at its own pipe's EOF when that process exits.
            pump = threading.Thread(target=self._pump_output,
                                    args=(plan.name, proc), daemon=True)
            pump.start()
            self._publish(plan.name, running=1)
            healthy_since = time.monotonic()
            while proc.poll() is None:
                if self._stopping.wait(0.5):
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    self._publish(plan.name, running=0)
                    return
                if time.monotonic() - healthy_since > 60:
                    attempt = 0
            self._publish(plan.name, running=0)
            if self._stopping.is_set():
                return
            self._restarts[plan.name] += 1
            self._publish(plan.name, restarts=self._restarts[plan.name])
            delay = self._backoff[min(attempt, len(self._backoff) - 1)]
            attempt += 1
            with self._io_lock:
                print(f"[stxm-iocs] {plan.name} exited rc={proc.returncode}; "
                      f"restart in {delay}s (restart #{self._restarts[plan.name]})")
            if self._stopping.wait(delay):
                return

    def start(self):
        self._allocate_ports()
        if self._status_prefix:
            self._start_status_server()
        for plan in self._plans:
            t = threading.Thread(target=self._monitor, args=(plan,), daemon=True)
            t.start()
            self._threads.append(t)
        if self._status_interval:
            t = threading.Thread(target=self._table_loop, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stopping.set()
        for t in self._threads:
            t.join(timeout=15)
        for proc in self._procs.values():
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if self._status_loop is not None:
            self._status_loop.call_soon_threadsafe(self._shutdown_status_loop)

    def _shutdown_status_loop(self):
        for task in asyncio.all_tasks(loop=self._status_loop):
            task.cancel()
        self._status_loop.stop()

    def status(self):
        return {
            name: {
                "running": proc is not None and proc.poll() is None,
                "restarts": self._restarts[name],
                "pid": proc.pid if proc is not None and proc.poll() is None else None,
            }
            for name, proc in ((p.name, self._procs.get(p.name))
                               for p in self._plans)
        }

    def _table_loop(self):
        while not self._stopping.wait(self._status_interval):
            lines = [f"{'IOC':<24} {'RUNNING':<8} {'RESTARTS':<8} PID"]
            for name, st in self.status().items():
                lines.append(f"{name:<24} {int(st['running']):<8} "
                             f"{st['restarts']:<8} {st['pid'] or '-'}")
            with self._io_lock:
                print("\n".join(lines))

    # -- status PVs ---------------------------------------------------------
    def _start_status_server(self):
        from caproto import ChannelInteger

        pvdb = {}
        for plan in self._plans:
            running = ChannelInteger(value=0)
            restarts = ChannelInteger(value=0)
            pvdb[f"{self._status_prefix}:{plan.name}:RUNNING"] = running
            pvdb[f"{self._status_prefix}:{plan.name}:RESTARTS"] = restarts
            self._status_channels[plan.name] = (running, restarts)

        started = threading.Event()

        def runner():
            from caproto.asyncio.server import start_server
            self._status_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._status_loop)

            async def main():
                started.set()
                # Bind all interfaces, consistent with every IOC main
                # (e712/daq/shutter/motor/derived) -- real beamline hosts
                # need cross-host CA reachability. Tests scope via per-test
                # ports/EPICS_CA_ADDR_LIST, not interface binding.
                await start_server(pvdb)

            try:
                self._status_loop.run_until_complete(main())
            except (asyncio.CancelledError, RuntimeError):
                pass

        threading.Thread(target=runner, daemon=True).start()
        started.wait(10)
        time.sleep(0.5)

    def _publish(self, name: str, running: int | None = None,
                 restarts: int | None = None):
        if not self._status_channels or self._status_loop is None:
            return
        ch_running, ch_restarts = self._status_channels[name]

        async def _do():
            if running is not None:
                await ch_running.write(running)
            if restarts is not None:
                await ch_restarts.write(restarts)

        try:
            asyncio.run_coroutine_threadsafe(_do(), self._status_loop)
        except RuntimeError:
            pass


def _default_config(name: str) -> str:
    import pystxmcontrol
    pkg_root = Path(pystxmcontrol.__file__).resolve().parents[1]
    return str(pkg_root / "config" / name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motor-config", default=_default_config("motor.json"))
    parser.add_argument("--daq-config", default=_default_config("daq.json"))
    parser.add_argument("--station", default=os.environ.get("STXM_STATION", "SIM"))
    parser.add_argument("--slice-dir", default=None)
    parser.add_argument("--no-shutter-iocs", action="store_true")
    parser.add_argument("--status-interval", type=float, default=10.0)
    parser.add_argument("--startup-delay", type=float, default=3.0)
    parser.add_argument("--host", default="127.0.0.1",
                        help="host used in per-IOC EPICS_CA_ADDR_LIST entries")
    parser.add_argument("--quiet-iocs", action="store_true",
                        help="pass --quiet to each IOC, suppressing its "
                             "startup PV-name list. By default the supervisor "
                             "relays each IOC's stdout (banner + PV list) to "
                             "its own output, tagged with the IOC name.")
    parser.add_argument("--shared-ca-port", action="store_true",
                        help="disable per-IOC CA server ports and use the "
                             "default port 5064 for every IOC (prior "
                             "behavior). Only safe on hosts where UDP "
                             "broadcast search reaches every subprocess "
                             "(e.g. most Linux hosts); on Windows only one "
                             "process ever receives the search datagrams.")
    args = parser.parse_args(argv)

    slice_dir = args.slice_dir or tempfile.mkdtemp(prefix="stxm_iocs_")
    fleet = load_fleet(args.motor_config, args.daq_config, station=args.station)
    for key, reason in fleet.skipped:
        print(f"[stxm-iocs] skipping {key}: {reason}")
    plans = plan_fleet(fleet, slice_dir, shutter_iocs=not args.no_shutter_iocs,
                       startup_delay=args.startup_delay)
    print(f"[stxm-iocs] station STXM{args.station}: {len(plans)} IOCs")
    sup = Supervisor(plans, status_prefix=f"STXM{args.station}:SUP",
                     status_interval=args.status_interval,
                     shared_ca_port=args.shared_ca_port,
                     ca_host=args.host, slice_dir=slice_dir,
                     quiet_iocs=args.quiet_iocs)
    sup.start()

    # Stop gracefully on BOTH SIGTERM (a plain `kill`, and what most process
    # managers / `pkill` send) and SIGINT (Ctrl-C). Previously only
    # KeyboardInterrupt was caught, so `kill <supervisor>` terminated the
    # supervisor outright without running sup.stop() -- leaving every child
    # IOC running and re-parented to init (orphaned, still holding hardware).
    stop_requested = threading.Event()

    def _handle_signal(signum, _frame):
        stop_requested.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        while not stop_requested.wait(1.0):
            pass
    except KeyboardInterrupt:
        pass  # belt-and-braces if SIGINT is delivered as an exception
    print("[stxm-iocs] shutting down")
    sup.stop()


if __name__ == "__main__":
    main()

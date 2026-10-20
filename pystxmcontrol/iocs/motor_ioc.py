"""Generic per-controller motor IOC.

Usage (spawned by the supervisor, or standalone):
    python -m pystxmcontrol.iocs.motor_ioc --slice /path/to/slice.json
"""
from __future__ import annotations

import argparse

from pystxmcontrol.iocs import configure_ioc_logging, require_caproto

require_caproto()

from caproto.server import run  # noqa: E402

from pystxmcontrol.iocs.base import (  # noqa: E402
    MotorRecordGroup, build_controller, build_motor)
from pystxmcontrol.iocs.config import read_slice  # noqa: E402


def build_pvdb_from_slice(s: dict) -> dict:
    if s["kind"] != "controller":
        raise ValueError(f"motor_ioc requires kind=controller, got {s['kind']!r}")
    # Adapt slice format to build_controller API: controller_cls -> controller,
    # controller_id -> address (for hardware controllers). Everything else in
    # the dict (besides controller/simulation/motors) is passed straight
    # through as constructor kwargs by build_controller, so include port and
    # exclude slice bookkeeping keys (kind/station/label/derived/motor_pv).
    controller_dict = {
        "controller": s["controller_cls"],
        "address": s["controller_id"],
        "port": s["port"],
        "simulation": s["simulation"],
    }
    controller = build_controller(controller_dict)
    # One lock per controller: every motor on it serializes its blocking
    # driver transactions through this, so the axes' RBV pollers never
    # interleave two frames on a shared link (e.g. one FTDI handle for both
    # nPoint axes).
    import threading
    io_lock = threading.Lock()
    pvdb: dict = {}
    motors_by_key: dict = {}
    for m in s["motors"]:
        drv = build_motor(m["entry"]["driver"], controller,
                          m["entry"], m["entry"]["axis"])
        motors_by_key[m["key"]] = drv
        group = MotorRecordGroup(m["pv"], driver=drv, motor_config=m["entry"],
                                 io_lock=io_lock)
        pvdb.update(group.pvdb)
    # co-located derived motors are wired in Task 5 (build_derived_colocated)
    from pystxmcontrol.iocs.derived_ioc import build_derived_colocated
    pvdb.update(build_derived_colocated(s, motors_by_key, io_lock=io_lock))
    return pvdb


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    configure_ioc_logging()
    pvdb = build_pvdb_from_slice(read_slice(args.slice))
    run(pvdb, log_pv_names=not args.quiet)


if __name__ == "__main__":
    main()

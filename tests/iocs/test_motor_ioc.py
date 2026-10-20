import json
import time
from pathlib import Path

import pytest

from pystxmcontrol.iocs.config import load_fleet, write_slice

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def xps_slice(tmp_path):
    fleet = load_fleet(str(REPO / "config" / "motor.json"),
                       str(REPO / "config" / "daq.json"), station="SIM")
    xps = next(g for g in fleet.controller_groups if g.label == "XPS")
    p = tmp_path / "xps.json"
    write_slice(xps, fleet, str(p))
    return str(p)


def test_build_pvdb_from_slice(xps_slice):
    from pystxmcontrol.iocs.motor_ioc import build_pvdb_from_slice
    pvdb = build_pvdb_from_slice(json.load(open(xps_slice)))
    assert "STXMSIM:XPS:CoarseX" in pvdb
    assert "STXMSIM:XPS:CoarseY" in pvdb
    # Note: motor record fields like .RBV are created at runtime when the IOC
    # starts, not in the static pvdb dict


def test_motor_ioc_subprocess(xps_slice, free_port, spawn_ioc):
    proc = spawn_ioc("pystxmcontrol.iocs.motor_ioc", xps_slice, free_port)
    try:
        from caproto.threading.client import Context
        ctx = Context()
        (val, rbv) = ctx.get_pvs("STXMSIM:XPS:CoarseX", "STXMSIM:XPS:CoarseX.RBV",
                                 timeout=20)
        val.wait_for_connection(timeout=20)
        val.write(3.0, wait=True, timeout=20)
        deadline = time.time() + 10
        while time.time() < deadline and abs(rbv.read().data[0] - 3.0) > 1e-6:
            time.sleep(0.1)
        assert abs(rbv.read().data[0] - 3.0) < 1e-6
    finally:
        proc.terminate()
        proc.wait(timeout=10)

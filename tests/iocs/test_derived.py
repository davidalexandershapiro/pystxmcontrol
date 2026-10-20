import json
import time
from pathlib import Path

import pytest

from pystxmcontrol.iocs.config import load_fleet, write_slice

REPO = Path(__file__).resolve().parents[2]


def _synthetic_colocated_config(tmp_path):
    """FineQ + CoarseQ both on ONE xpsController + a derivedPiezo over them."""
    base = json.loads((REPO / "config" / "motor.json").read_text())
    fine = dict(base["CoarseX"]);  fine.update({"axis": "x"})
    coarse = dict(base["CoarseY"]); coarse.update({"axis": "y"})
    cfg = {
        "FineQ": fine,
        "CoarseQ": coarse,
        "SampleQ": {
            "type": "derived",
            "axes": {"axis1": "FineQ", "axis2": "CoarseQ"},
            "driver": "derivedPiezo",
            "reset_after_move": False,
            "max velocity": 1000.0,
            "minValue": -5000.0, "maxValue": 5000.0,
            "offset": 0.0, "units": 1.0,
            "simulation": 1,
        },
    }
    p = tmp_path / "motor.json"
    p.write_text(json.dumps(cfg))
    return p


def test_colocated_derived_in_process(tmp_path, ioc_harness):
    mp = _synthetic_colocated_config(tmp_path)
    fleet = load_fleet(str(mp), str(REPO / "config" / "daq.json"), station="SIM")
    assert not fleet.derived_remote  # all on one controller -> co-located
    g = fleet.controller_groups[0]
    assert [d.key for d in g.derived] == ["SampleQ"]

    sp = tmp_path / "slice.json"
    write_slice(g, fleet, str(sp))
    from pystxmcontrol.iocs.motor_ioc import build_pvdb_from_slice
    pvdb = build_pvdb_from_slice(json.load(open(sp)))
    assert "STXMSIM:XPS:SampleQ" in pvdb

    ioc_harness.start(pvdb)
    ctx = ioc_harness.client()
    val, rbv = ctx.get_pvs("STXMSIM:XPS:SampleQ", "STXMSIM:XPS:SampleQ.RBV")
    val.wait_for_connection(timeout=10)
    val.write(7.5, wait=True, timeout=15)
    deadline = time.time() + 5
    while time.time() < deadline and abs(rbv.read().data[0] - 7.5) > 1e-3:
        time.sleep(0.05)
    assert abs(rbv.read().data[0] - 7.5) < 1e-3


def test_ca_motor_proxy_against_live_ioc(ioc_harness, slow_sim_motor):
    from pystxmcontrol.iocs.base import MotorRecordGroup
    group = MotorRecordGroup("PROXY:M1", driver=slow_sim_motor,
                             motor_config=slow_sim_motor.config,
                             idle_poll=0.05, moving_poll=0.01)
    ioc_harness.start(group.pvdb)

    from pystxmcontrol.iocs.derived_ioc import CAMotorProxy
    ctx = ioc_harness.client()
    proxy = CAMotorProxy("PROXY:M1", ctx, axis_label="x")
    assert proxy.checkLimits(0.0) is True
    assert proxy.checkLimits(100.0) is False
    proxy.moveTo(4.0)
    assert abs(proxy.getPos() - 4.0) < 1e-3
    assert proxy.getStatus() is False
    assert proxy.config["minValue"] == -40.0
    assert proxy.config["maxValue"] == 40.0
    assert proxy.controller.getAxis("x") == 1


def test_cross_controller_derived_ioc_subprocess(tmp_path, free_port, spawn_ioc):
    """Full chain: 1 motor IOC (2 axes on distinct controllers is overkill —
    reuse one controller IOC) + derived_remote IOC composing over CA."""
    base = json.loads((REPO / "config" / "motor.json").read_text())
    fine = dict(base["CoarseX"]); fine.update({"axis": "x"})
    # second physical controller: same class, different controllerID
    coarse = dict(base["CoarseY"]); coarse.update({"axis": "y", "controllerID": "192.168.1.253"})
    cfg = {
        "FineQ": fine, "CoarseQ": coarse,
        "SampleQ": {
            "type": "derived",
            "axes": {"axis1": "FineQ", "axis2": "CoarseQ"},
            "driver": "derivedPiezo", "reset_after_move": False,
            "max velocity": 1000.0, "minValue": -5000.0, "maxValue": 5000.0,
            "offset": 0.0, "units": 1.0, "simulation": 0,
        },
    }
    mp = tmp_path / "motor.json"
    mp.write_text(json.dumps(cfg))
    fleet = load_fleet(str(mp), str(REPO / "config" / "daq.json"), station="SIM")
    assert [d.key for d in fleet.derived_remote] == ["SampleQ"]

    slices = {}
    for g in fleet.controller_groups:
        p = tmp_path / f"{g.label}.json"
        write_slice(g, fleet, str(p))
        slices[g.label] = str(p)
    dp = tmp_path / "derived.json"
    write_slice(fleet.derived_remote[0], fleet, str(dp))

    for label in slices:
        spawn_ioc("pystxmcontrol.iocs.motor_ioc", slices[label], free_port)
    spawn_ioc("pystxmcontrol.iocs.derived_ioc", str(dp), free_port)

    from caproto.threading.client import Context
    ctx = Context()
    pv_name = fleet.motor_pv["SampleQ"]
    val, rbv = ctx.get_pvs(pv_name, pv_name + ".RBV", timeout=30)
    val.wait_for_connection(timeout=30)
    val.write(2.5, wait=True, timeout=30)
    deadline = time.time() + 15
    while time.time() < deadline and abs(rbv.read().data[0] - 2.5) > 1e-3:
        time.sleep(0.1)
    assert abs(rbv.read().data[0] - 2.5) < 1e-3

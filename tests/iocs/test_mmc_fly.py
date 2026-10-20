"""MMC fly-capability routing + line_trigger plumbing (no hardware)."""
import time

import pytest


def test_mmc_is_fly_capable():
    from pystxmcontrol.iocs.config import FLY_CAPABLE_CONTROLLERS
    assert "mmcController" in FLY_CAPABLE_CONTROLLERS


def test_mmc_motor_declares_immediate_trigger():
    # "IMM" is the 53230A TRIG:SOUR free-run mnemonic (IMM|EXT|BUS);
    # "INT" is not a valid 53230A trigger source.
    from pystxmcontrol.drivers.mmcMotor import mmcMotor
    assert mmcMotor.line_trigger == "IMM"


def test_npt_default_stays_external():
    # Drivers without the attribute must keep today's EXT behavior.
    from pystxmcontrol.iocs import fly_ioc
    class NoAttr: pass
    assert getattr(NoAttr(), "line_trigger", "EXT") == "EXT"
    # and the source actually consults the attribute:
    import inspect
    src = inspect.getsource(fly_ioc)
    assert 'getattr(motor, "line_trigger", "EXT")' in src


def test_fly_free_run_prepares_before_arm():
    # With a non-EXT (free-run) trigger, initLine (INIT:IMM) starts
    # acquisition immediately, so _hw_line must run a "prepare" stage
    # (trajectory setup + pre-positioning via motor.prepareLine) BEFORE
    # the "arm" stage. EXT path stays unchanged (gated on the trigger).
    import inspect
    from pystxmcontrol.iocs import fly_ioc
    src = inspect.getsource(fly_ioc)
    assert 'if line_trigger != "EXT":' in src
    assert 'stage["name"] = "prepare"' in src
    assert 'motor.prepareLine()' in src
    # ordering: prepare stage precedes the arm stage in the source
    assert src.index('stage["name"] = "prepare"') < \
        src.index('stage["name"] = "arm"')


def test_fly_slice_builds_for_mmc(tmp_path):
    """fly_ioc.build_pvdb_from_slice accepts an mmcController group and
    serves motor records + FLY PVs (simulation)."""
    import json
    from pystxmcontrol.iocs.fly_ioc import build_pvdb_from_slice
    entry = {"type": "primary", "driver": "mmcMotor",
             "controller": "mmcController", "controllerID": "COM99",
             "axis": "x", "minValue": -10.0, "maxValue": 10.0,
             "offset": 0.0, "units": 1.0, "max velocity": 2.0,
             "simulation": 1}
    s = {"kind": "controller", "station": "SIM", "controller_id": "COM99",
         "controller_cls": "mmcController", "label": "MMC", "port": 0,
         "simulation": True,
         "motors": [{"key": "CoarseX", "entry": entry,
                     "pv": "STXMSIM:MMC:CoarseX"}],
         "derived": [], "motor_pv": {"CoarseX": "STXMSIM:MMC:CoarseX"},
         "daqs": [{"key": "default", "prefix": "STXMSIM:DEFAULT",
                   "entry": {"name": "Counter1", "driver": "keysight53230A",
                             "address": "sim", "port": 5025, "channel": 1,
                             "ndim": 0, "gate": False, "record": True,
                             "simulation": True}}]}
    p = tmp_path / "slice.json"
    p.write_text(json.dumps(s))
    from pystxmcontrol.iocs.config import read_slice
    pvdb = build_pvdb_from_slice(read_slice(str(p)))
    names = set(pvdb)
    assert "STXMSIM:MMC:CoarseX" in names
    assert "STXMSIM:MMC:FLY:GO" in names


FLY_PREFIX = "STXMSIM:MMC:FLY"


@pytest.fixture
def mmc_fly_ioc(ioc_harness):
    from pystxmcontrol.iocs.base import (MotorRecordGroup, build_controller,
                                         build_motor)
    from pystxmcontrol.iocs.daq_ioc import build_pvdb_for_entry
    from pystxmcontrol.iocs.fly_ioc import FlyGroup

    ctrl = build_controller({"controller": "mmcController",
                             "address": "COM99", "port": 0,
                             "simulation": True})
    entry = {"axis": "x", "minValue": -50.0, "maxValue": 50.0, "offset": 0.0,
             "units": 1.0, "max velocity": 1000.0, "simulation": 1}
    mx = build_motor("mmcMotor", ctrl, dict(entry), "x")
    my = build_motor("mmcMotor", ctrl, dict(entry, axis="y"), "y")

    daq_entry = {"name": "Counter1", "driver": "keysight53230A",
                 "address": "sim", "port": 5025, "channel": 1, "ndim": 0,
                 "gate": False, "record": True, "simulation": True}
    daq_pvdb, daq_group = build_pvdb_for_entry(daq_entry, "STXMSIM:DEFAULT")

    pvdb = {}
    pvdb.update(MotorRecordGroup("STXMSIM:MMC:CoarseX", driver=mx,
                                 motor_config=dict(entry)).pvdb)
    fly = FlyGroup(FLY_PREFIX, motors={"x": mx, "y": my},
                   daq_groups={"default": daq_group}, simulation=True)
    pvdb.update(daq_pvdb)
    pvdb.update(fly.pvdb)
    ioc_harness.start(pvdb)
    return ioc_harness, ioc_harness.client()


def _fly_pvs(ctx, *names):
    pvs = ctx.get_pvs(*names, timeout=15)
    for pv in pvs:
        pv.wait_for_connection(timeout=15)
    return pvs


def test_mmc_motor_record_moves(mmc_fly_ioc):
    _, ctx = mmc_fly_ioc
    val, rbv = _fly_pvs(ctx, "STXMSIM:MMC:CoarseX", "STXMSIM:MMC:CoarseX.RBV")
    val.write(7.25, wait=True, timeout=30)
    assert rbv.read().data[0] == pytest.approx(7.25, abs=1e-6)


def test_mmc_motor_record_rejects_out_of_limits(mmc_fly_ioc):
    _, ctx = mmc_fly_ioc
    (val,) = _fly_pvs(ctx, "STXMSIM:MMC:CoarseX")
    (rbv,) = _fly_pvs(ctx, "STXMSIM:MMC:CoarseX.RBV")
    before = rbv.read().data[0]
    with pytest.raises(Exception):
        val.write(500.0, wait=True, timeout=15)
    time.sleep(0.3)
    assert abs(rbv.read().data[0] - before) < 1e-6  # no motion happened


def test_mmc_fly_line_sim(mmc_fly_ioc):
    import numpy as np
    _, ctx = mmc_fly_ioc
    start, stop, npts, dwell, arm, go, index, data, pos = _fly_pvs(
        ctx, *[f"{FLY_PREFIX}:{s}" for s in (
            "START", "STOP", "NPOINTS", "DWELL", "ARM", "GO",
            "INDEX", "DATA:default", "POS")])
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(25, wait=True); dwell.write(1.0, wait=True)
    arm.write(1, wait=True, timeout=15)
    go.write(1, wait=True, timeout=60)
    assert index.read().data[0] == 1
    p = np.asarray(pos.read().data, dtype=float)
    d = np.asarray(data.read().data, dtype=float)
    assert len(p) == 25 and len(d) == 25
    assert p[0] == pytest.approx(-5.0) and p[-1] == pytest.approx(5.0)

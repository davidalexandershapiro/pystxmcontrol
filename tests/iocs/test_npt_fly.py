"""Fly-line support for nptController fleets.

The fly IOC (pystxmcontrol.iocs.e712_ioc) is controller-agnostic: its line
loop drives the selected-axis motor through the duck-typed fly interface, and
nptMotor implements it. These tests exercise the FLY PVGroup wired to sim
npt motors, mirroring test_e712_fly.py's sim path, to prove an nptController
group gets a working FLY group at STXM<station>:NPT:FLY.
"""
import numpy as np
import pytest

FLY_PREFIX = "STXMSIM:NPT:FLY"


@pytest.fixture
def npt_fly_ioc(ioc_harness):
    import pystxmcontrol.drivers as drv
    from pystxmcontrol.iocs.base import build_controller, build_motor
    from pystxmcontrol.iocs.daq_ioc import build_pvdb_for_entry
    from pystxmcontrol.iocs.e712_ioc import FlyGroup

    if not hasattr(drv, "nptController") or not hasattr(drv, "nptMotor"):
        pytest.skip("nptController/nptMotor unavailable in this env")

    ctrl = build_controller({"controller": "nptController",
                             "address": "7340015A", "port": 0,
                             "simulation": True})
    entry = {"axis": "x", "minValue": -50.0, "maxValue": 50.0, "offset": 0.0,
             "units": 1.0, "max velocity": 1000.0, "simulation": 1}
    mx = build_motor("nptMotor", ctrl, dict(entry), "x")
    my = build_motor("nptMotor", ctrl, dict(entry, axis="y"), "y")

    daq_entry = {"name": "Counter1", "driver": "keysight53230A",
                 "address": "sim", "port": 5025, "channel": 1, "ndim": 0,
                 "gate": False, "record": True, "simulation": True}
    daq_pvdb, daq_group = build_pvdb_for_entry(daq_entry, "STXMSIM:DEFAULT")

    fly = FlyGroup(FLY_PREFIX, motors={"x": mx, "y": my},
                   daq_groups={"default": daq_group}, simulation=True)
    pvdb = {}
    pvdb.update(daq_pvdb)
    pvdb.update(fly.pvdb)
    ioc_harness.start(pvdb)
    return ioc_harness, ioc_harness.client()


def _pvs(ctx, *suffixes):
    pvs = ctx.get_pvs(*[f"{FLY_PREFIX}:{s}" for s in suffixes], timeout=15)
    for pv in pvs:
        pv.wait_for_connection(timeout=15)
    return pvs


def test_npt_fly_pvs_exist(npt_fly_ioc):
    _, ctx = npt_fly_ioc
    axis, mode, state = _pvs(ctx, "AXIS", "MODE", "STATE")
    assert state.read().data[0] == 0  # IDLE


def test_npt_arm_validates_and_transitions(npt_fly_ioc):
    _, ctx = npt_fly_ioc
    start, stop, npts, dwell, arm, state = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "STATE")
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(20, wait=True); dwell.write(1.0, wait=True)
    arm.write(1, wait=True, timeout=15)
    assert state.read().data[0] == 1  # ARMED


def test_npt_arm_rejects_out_of_limit_line(npt_fly_ioc):
    _, ctx = npt_fly_ioc
    start, stop, npts, dwell, arm, state = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "STATE")
    start.write(-500.0, wait=True)  # axis limits are +/-50
    stop.write(5.0, wait=True); npts.write(20, wait=True); dwell.write(1.0, wait=True)
    arm.write(1, wait=True, timeout=15)
    assert state.read().data[0] == 3  # ERROR


def test_npt_fly_line_waveforms_and_index_ordering(npt_fly_ioc):
    _, ctx = npt_fly_ioc
    start, stop, npts, dwell, arm, go, index, data, pos = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "GO",
        "INDEX", "DATA:default", "POS")
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(25, wait=True); dwell.write(1.0, wait=True)
    arm.write(1, wait=True, timeout=15)
    assert index.read().data[0] == 0

    for line_no in (1, 2, 3):
        go.write(1, wait=True, timeout=60)  # put-completion == line done
        assert index.read().data[0] == line_no

    d = np.asarray(data.read().data, dtype=float)
    p = np.asarray(pos.read().data, dtype=float)
    assert len(d) == 25 and len(p) == 25
    assert (d > 0).all()  # Poisson counts at 1 ms dwell
    assert abs(p[0] - -5.0) < 1e-6 and abs(p[-1] - 5.0) < 1e-6

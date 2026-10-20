import threading
import time
from pathlib import Path

import numpy as np
import pytest

from pystxmcontrol.iocs.config import load_fleet

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def fly_ioc(ioc_harness):
    # sim E712 controller + x/y motors, wired David's way
    from pystxmcontrol.iocs.base import build_motor
    import pystxmcontrol.drivers as drv
    ctrl = drv.E712Controller(address="192.168.1.201", port=5000, simulation=True)
    ctrl.initialize(simulation=True)
    entry = {"axis": "x", "minValue": -50.0, "maxValue": 50.0, "offset": 0.0,
             "units": 1.0, "max velocity": 1000.0, "simulation": 1}
    mx = build_motor("E712Motor", ctrl, dict(entry), "x")
    my = build_motor("E712Motor", ctrl, dict(entry, axis="y"), "y")

    fleet = load_fleet(str(REPO / "config" / "motor.json"),
                       str(REPO / "config" / "daq.json"), station="SIM")
    from pystxmcontrol.iocs.daq_ioc import build_pvdb_for_entry
    daq_pvdb, daq_group = build_pvdb_for_entry(fleet.daqs[0].entry, "STXMSIM:DEFAULT")

    from pystxmcontrol.iocs.e712_ioc import FlyGroup
    fly = FlyGroup("STXMSIM:E712:FLY", motors={"x": mx, "y": my},
                   daq_groups={"default": daq_group}, simulation=True)
    pvdb = {}
    pvdb.update(daq_pvdb)
    pvdb.update(fly.pvdb)
    ioc_harness.start(pvdb)
    ctx = ioc_harness.client()
    return ioc_harness, ctx


def _pvs(ctx, *suffixes):
    pvs = ctx.get_pvs(*[f"STXMSIM:E712:FLY:{s}" for s in suffixes], timeout=15)
    for pv in pvs:
        pv.wait_for_connection(timeout=15)
    return pvs


def test_arm_validates_and_transitions(fly_ioc):
    h, ctx = fly_ioc
    start, stop, npts, dwell, arm, state, error = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "STATE", "ERROR")
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(20, wait=True); dwell.write(1.0, wait=True)
    arm.write(1, wait=True, timeout=15)
    assert state.read().data[0] == 1  # ARMED


def test_arm_rejects_out_of_limit_line(fly_ioc):
    h, ctx = fly_ioc
    start, stop, npts, dwell, arm, state, error = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "STATE", "ERROR")
    start.write(-500.0, wait=True)  # axis limits are +/-50
    stop.write(5.0, wait=True); npts.write(20, wait=True); dwell.write(1.0, wait=True)
    arm.write(1, wait=True, timeout=15)
    assert state.read().data[0] == 3  # ERROR
    msg = b"".join(error.read(data_type="native").data) if isinstance(
        error.read().data[0], (bytes, int)) else error.read().data[0]
    assert b"limit" in bytes(msg).lower() or "limit" in str(msg).lower()


def test_fly_line_waveforms_and_index_ordering(fly_ioc):
    h, ctx = fly_ioc
    start, stop, npts, dwell, arm, go, state, index, data, pos = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "GO", "STATE",
        "INDEX", "DATA:default", "POS")
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(25, wait=True); dwell.write(1.0, wait=True)
    arm.write(1, wait=True, timeout=15)
    assert index.read().data[0] == 0

    # monitor: on every INDEX increment the waveforms must ALREADY be fresh
    observed = []

    def on_index(sub, response):
        if response.data[0] > 0:
            observed.append((response.data[0],
                             len(data.read().data), len(pos.read().data)))

    sub = index.subscribe()
    token = sub.add_callback(on_index)

    for line_no in (1, 2, 3):
        go.write(1, wait=True, timeout=60)  # put-completion == line done
        assert index.read().data[0] == line_no

    d = np.asarray(data.read().data, dtype=float)
    p = np.asarray(pos.read().data, dtype=float)
    assert len(d) == 25 and len(p) == 25
    assert (d > 0).all()                       # Poisson counts at 1 ms dwell
    assert abs(p[0] - -5.0) < 1e-6 and abs(p[-1] - 5.0) < 1e-6
    time.sleep(0.5)
    idxs = [o[0] for o in observed]
    assert idxs == sorted(idxs) and len(set(idxs)) == len(idxs)  # monotonic
    assert all(nd == 25 and np_ == 25 for _, nd, np_ in observed)
    sub.remove_callback(token)


def test_abort_returns_to_idle(fly_ioc):
    h, ctx = fly_ioc
    start, stop, npts, dwell, arm, go, abort, state = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "GO", "ABORT", "STATE")
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(2000, wait=True); dwell.write(1.0, wait=True)  # ~2 s line
    arm.write(1, wait=True, timeout=15)
    t = threading.Thread(target=lambda: go.write(1, wait=True, timeout=60))
    t.start()
    time.sleep(0.3)
    abort.write(1, wait=True, timeout=15)
    t.join(timeout=30)
    assert state.read().data[0] == 0  # IDLE


def test_arm_while_flying_rejected(fly_ioc):
    h, ctx = fly_ioc
    start, stop, npts, dwell, arm, go, abort, state, index, error = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "GO", "ABORT",
        "STATE", "INDEX", "ERROR")
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(2000, wait=True); dwell.write(1.0, wait=True)  # ~2 s line
    arm.write(1, wait=True, timeout=15)
    t = threading.Thread(target=lambda: go.write(1, wait=True, timeout=60))
    t.start()
    time.sleep(0.3)
    assert state.read().data[0] == 2  # FLYING
    arm.write(1, wait=True, timeout=15)  # mid-flight ARM: must be rejected
    assert state.read().data[0] == 2  # still FLYING; STATE untouched
    msg = error.read(data_type="native").data
    msg = bytes(msg).lower() if isinstance(msg[0], int) else str(msg[0]).lower()
    assert b"arm while flying" in msg if isinstance(msg, bytes) else \
        "arm while flying" in msg
    # ABORT must still interrupt the line (abort event was not cleared)
    abort.write(1, wait=True, timeout=15)
    t.join(timeout=30)
    assert state.read().data[0] == 0  # IDLE
    assert index.read().data[0] == 0  # aborted line never incremented INDEX


def test_go_while_flying_rejected(fly_ioc):
    """A second GO during an in-flight line must not clobber STATE with
    ERROR (the GO-while-FLYING mirror of test_arm_while_flying_rejected)."""
    h, ctx = fly_ioc
    start, stop, npts, dwell, arm, go, abort, state, index, error = _pvs(
        ctx, "START", "STOP", "NPOINTS", "DWELL", "ARM", "GO", "ABORT",
        "STATE", "INDEX", "ERROR")
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(2000, wait=True); dwell.write(1.0, wait=True)  # ~2 s line
    arm.write(1, wait=True, timeout=15)
    t = threading.Thread(target=lambda: go.write(1, wait=True, timeout=60))
    t.start()
    time.sleep(0.3)
    assert state.read().data[0] == 2  # FLYING
    go.write(1, wait=True, timeout=15)  # mid-flight GO: must be rejected
    assert state.read().data[0] == 2  # still FLYING; STATE untouched
    msg = error.read(data_type="native").data
    msg = bytes(msg).lower() if isinstance(msg[0], int) else str(msg[0]).lower()
    assert b"line in progress" in msg if isinstance(msg, bytes) else \
        "line in progress" in msg
    # the original in-flight line must complete normally (unaffected by the
    # rejected racing GO)
    t.join(timeout=30)
    assert state.read().data[0] == 1  # ARMED (line completed, not aborted)
    assert index.read().data[0] == 1


def test_go_without_arm_errors(fly_ioc):
    h, ctx = fly_ioc
    go, state = _pvs(ctx, "GO", "STATE")
    # fresh fixture; STATE may be IDLE(0): GO must not fly
    go.write(1, wait=True, timeout=15)
    assert state.read().data[0] in (0, 3)  # IDLE or ERROR, never leaves data

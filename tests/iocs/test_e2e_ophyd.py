"""Spec §7 e2e: sim-backed IOC subprocess driven by real ophyd EpicsMotor + fly line over PVs."""
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("OPHYD_CONTROL_LAYER", "caproto")

from pystxmcontrol.iocs.config import load_fleet  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _e712_sim_config(tmp_path):
    cfg = {
        "FlyX": {
            "index": 0, "type": "primary", "axis": "x", "driver": "E712Motor",
            "controllerID": "192.168.1.201", "port": 5000,
            "controller": "E712Controller", "max velocity": 1000.0,
            "minValue": -50.0, "maxValue": 50.0, "offset": 0.0, "units": 1.0,
            "display": True, "simulation": 1,
        },
        "FlyY": {
            "index": 1, "type": "primary", "axis": "y", "driver": "E712Motor",
            "controllerID": "192.168.1.201", "port": 5000,
            "controller": "E712Controller", "max velocity": 1000.0,
            "minValue": -50.0, "maxValue": 50.0, "offset": 0.0, "units": 1.0,
            "display": True, "simulation": 1,
        },
    }
    p = tmp_path / "motor.json"
    p.write_text(json.dumps(cfg))
    return p


@pytest.fixture
def e712_fleet_up(tmp_path, free_port, spawn_ioc):
    pytest.importorskip("pipython", reason="E712Controller needs pipython even in sim")
    mp = _e712_sim_config(tmp_path)
    fleet = load_fleet(str(mp), str(REPO / "config" / "daq.json"), station="SIM")
    from pystxmcontrol.iocs.supervisor import plan_fleet
    plans = plan_fleet(fleet, str(tmp_path / "slices"))
    for plan in plans:
        spawn_ioc(plan.module, plan.slice_path, free_port)
    return fleet


def test_ophyd_epicsmotor_move_readback_stop_limits(e712_fleet_up):
    import ophyd
    ophyd.set_cl("caproto")  # belt-and-braces if OPHYD_CONTROL_LAYER env timing missed import
    from ophyd import EpicsMotor
    m = EpicsMotor("STXMSIM:E712:FlyX", name="flyx")
    m.wait_for_connection(timeout=30)

    st = m.move(7.0, timeout=60)
    assert st.done and st.success
    assert abs(m.position - 7.0) < 1e-3

    assert m.low_limit_travel.get() == -50.0
    assert m.high_limit_travel.get() == 50.0
    with pytest.raises(Exception):
        m.move(60.0, timeout=30)  # outside HLM -> rejected put
    assert abs(m.position - 7.0) < 1e-3

    # STOP PV is wired (sim moves are fast; just assert the put round-trips)
    m.motor_stop.put(1, wait=True)
    time.sleep(0.2)
    assert m.motor_done_move.get() == 1


def test_full_fly_line_over_pvs(e712_fleet_up):
    from caproto.threading.client import Context
    ctx = Context()
    names = ["START", "STOP", "NPOINTS", "DWELL", "AXIS", "ARM", "GO",
             "STATE", "INDEX", "DATA:default", "POS"]
    pvs = dict(zip(names, ctx.get_pvs(
        *[f"STXMSIM:E712:FLY:{n}" for n in names], timeout=30)))
    pvs["GO"].wait_for_connection(timeout=30)

    pvs["START"].write(-10.0, wait=True); pvs["STOP"].write(10.0, wait=True)
    pvs["NPOINTS"].write(40, wait=True); pvs["DWELL"].write(1.0, wait=True)
    # Enum PV: writing the bare native string is rejected by caproto's
    # ChannelEnum unless the write is either an integer index or explicitly
    # typed as a string (data_type=ChannelType.STRING triggers verify_value's
    # string->index mapping). "x" is axis_labels[0] -> index 0.
    pvs["AXIS"].write(0, wait=True)

    index_events = []
    sub = pvs["INDEX"].subscribe()
    token = sub.add_callback(
        lambda s, r: index_events.append(
            (int(r.data[0]), len(pvs["DATA:default"].read().data),
             len(pvs["POS"].read().data))))

    pvs["ARM"].write(1, wait=True, timeout=30)
    assert pvs["STATE"].read().data[0] == 1  # ARMED
    n_lines = 3
    for i in range(1, n_lines + 1):
        pvs["GO"].write(1, wait=True, timeout=120)
        assert pvs["INDEX"].read().data[0] == i

    data = np.asarray(pvs["DATA:default"].read().data, dtype=float)
    pos = np.asarray(pvs["POS"].read().data, dtype=float)
    assert len(data) == 40 and len(pos) == 40          # waveform lengths
    assert (data > 0).all()
    assert abs(pos[0] + 10.0) < 1e-6 and abs(pos[-1] - 10.0) < 1e-6
    time.sleep(0.5)
    nonzero = [e for e in index_events if e[0] > 0]
    idxs = [e[0] for e in nonzero]
    assert idxs == sorted(idxs) and len(set(idxs)) == len(idxs)  # INDEX monotonic
    assert all(nd == 40 and npos == 40 for _, nd, npos in nonzero)  # write-then-increment
    sub.remove_callback(token)


def test_acquire_completion_over_pvs(e712_fleet_up):
    from caproto.threading.client import Context
    ctx = Context()
    dwell, acq, counts = ctx.get_pvs(
        "STXMSIM:DEFAULT:DWELL", "STXMSIM:DEFAULT:ACQUIRE",
        "STXMSIM:DEFAULT:COUNTS", timeout=30)
    acq.wait_for_connection(timeout=30)
    dwell.write(150.0, wait=True)
    t0 = time.monotonic()
    acq.write(1, wait=True, timeout=60)
    assert time.monotonic() - t0 >= 0.13
    assert counts.read().data[0] > 0

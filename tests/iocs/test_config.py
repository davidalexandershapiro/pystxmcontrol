import json
from pathlib import Path

import pytest

from pystxmcontrol.iocs.config import load_fleet, sanitize, write_slice, read_slice

REPO = Path(__file__).resolve().parents[2]
MOTOR_JSON = REPO / "config" / "motor.json"
DAQ_JSON = REPO / "config" / "daq.json"


def test_sanitize():
    assert sanitize("Beamline Energy") == "Beamline_Energy"
    assert sanitize("FineX") == "FineX"
    assert sanitize("XS121 Vert Size") == "XS121_Vert_Size"


@pytest.fixture(scope="module")
def fleet():
    return load_fleet(str(MOTOR_JSON), str(DAQ_JSON), station="SIM")


def test_groups_by_controller_id(fleet):
    ids = {g.controller_id: g for g in fleet.controller_groups}
    # motor.json ships: bcsController@127.0.0.1, xerController@/dev/ttyACM1,
    # mclController@/usr/lib/..., xerController@COM3, xpsController@192.168.1.254
    assert "192.168.1.254" in ids
    xps = ids["192.168.1.254"]
    assert xps.controller_cls == "xpsController"
    assert xps.label == "XPS"
    assert sorted(m.key for m in xps.motors) == ["CoarseX", "CoarseY"]


def test_duplicate_label_disambiguation(fleet):
    xer_labels = sorted(g.label for g in fleet.controller_groups
                        if g.controller_cls == "xerController")
    assert xer_labels == ["XER", "XER_2"]


def test_motor_pv_naming(fleet):
    assert fleet.motor_pv["CoarseX"] == "STXMSIM:XPS:CoarseX"
    assert fleet.motor_pv["FineX"] == "STXMSIM:MCL:FineX"


def test_colocated_derived(fleet):
    # SampleX = derivedPiezo over FineX (mcl) + CoarseX (xps) -> CROSS-controller
    remote_keys = {d.key for d in fleet.derived_remote}
    assert "SampleX" in remote_keys and "SampleY" in remote_keys
    sx = next(d for d in fleet.derived_remote if d.key == "SampleX")
    assert sx.axis_pvs == {"axis1": "STXMSIM:MCL:FineX", "axis2": "STXMSIM:XPS:CoarseX"}
    # Energy = derivedEnergy over Beamline Energy (bcs) + ZonePlateZ (xer) -> also remote
    assert "Energy" in remote_keys


def test_epics_motors_skipped(fleet):
    skipped_keys = {k for k, _ in fleet.skipped}
    assert {"OSA_X", "OSA_Y", "OSA_Z"} <= skipped_keys
    assert "OSA_X" not in fleet.motor_pv


def test_daq_and_shutter(fleet):
    assert fleet.daqs[0].key == "default"
    assert fleet.daqs[0].prefix == "STXMSIM:DEFAULT"
    assert len(fleet.shutters) == 1
    assert fleet.shutters[0].prefix == "STXMSIM:SHUTTER1"
    assert fleet.shutters[0].simulation is True


def test_pv_override(tmp_path):
    cfg = json.loads(MOTOR_JSON.read_text())
    cfg["CoarseX"]["epics"] = {"pv": "BL7011:M1"}
    p = tmp_path / "motor.json"
    p.write_text(json.dumps(cfg))
    fleet = load_fleet(str(p), str(DAQ_JSON), station="SIM")
    assert fleet.motor_pv["CoarseX"] == "BL7011:M1"


def test_slice_roundtrip(tmp_path, fleet):
    g = fleet.controller_groups[0]
    p = tmp_path / "slice.json"
    write_slice(g, fleet, str(p))
    s = read_slice(str(p))
    assert s["station"] == "SIM"
    assert s["kind"] == "controller"
    assert s["controller_id"] == g.controller_id
    assert s["motor_pv"] == fleet.motor_pv
    # group entries must be carried VERBATIM in the slice
    assert s["motors"] == [
        {"key": m.key, "entry": m.entry, "pv": m.pv} for m in g.motors
    ]
    assert s["derived"] == [
        {"key": m.key, "entry": m.entry, "pv": m.pv} for m in g.derived
    ]

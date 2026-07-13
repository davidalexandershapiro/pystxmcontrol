"""Tests for scan_mapping.map_scan.

Test dicts are built to match the real shape produced by
main_controller.compile_scan_from_view / _extract_scan_region_data /
_extract_energy_region_data (pinned in pystxmcontrol/gui/models/scan_model.py
and pystxmcontrol/gui/controllers/main_controller.py):

- scan_regions[name] has xCenter/yCenter/xRange/yRange/xPoints/yPoints/
  xStep/yStep/xStart/xStop/yStart/yStop/z* (Start/Stop already derived from
  Center/Range/Points by the GUI).
- energy_regions[name] has start/stop/step/dwell/n_energies (dwell is
  milliseconds — ScanModel.calculate_estimated_time divides it by 1000.0).
"""
from __future__ import annotations

import pytest

from pystxmcontrol.remote.scan_mapping import UnsupportedScanMode, map_scan


def _image_region(x_center=0.0, y_center=0.0, x_range=10.0, y_range=10.0,
                   x_points=100, y_points=100):
    x_step = x_range / x_points
    y_step = y_range / y_points
    return {
        "xCenter": x_center, "yCenter": y_center,
        "xRange": x_range, "yRange": y_range,
        "xPoints": x_points, "yPoints": y_points,
        "xStep": x_step, "yStep": y_step,
        "xStart": x_center - x_range / 2.0 + x_step / 2.0,
        "xStop": x_center + x_range / 2.0 - x_step / 2.0,
        "yStart": y_center - y_range / 2.0 + y_step / 2.0,
        "yStop": y_center + y_range / 2.0 - y_step / 2.0,
        "zCenter": 0, "zRange": 0, "zPoints": 1, "zStep": 0,
        "zStart": 0, "zStop": 0,
    }


def _energy_region(start=280.0, stop=280.0, n_energies=1, dwell=1000.0, step=1.0):
    return {"start": start, "stop": stop, "step": step, "dwell": dwell,
            "n_energies": n_energies}


def _base_scan(scan_type="Image", scan_regions=None, energy_regions=None):
    return {
        "scan_type": scan_type,
        "scan_regions": scan_regions if scan_regions is not None else {"Region1": _image_region()},
        "energy_regions": energy_regions if energy_regions is not None else {"EnergyRegion1": _energy_region()},
        "x_motor": "SampleX",
        "y_motor": "SampleY",
        "energy_motor": "Energy",
        "single_energy": True,
        "dwell": 1.0,
    }


# --- single-region, single-energy Image scan -> stxm_fly_raster ---

def test_single_energy_image_scan_maps_to_fly_raster():
    scan = _base_scan(
        scan_regions={"Region1": _image_region(x_center=0.0, y_center=0.0,
                                                 x_range=10.0, y_range=20.0,
                                                 x_points=100, y_points=200)},
        energy_regions={"EnergyRegion1": _energy_region(start=280.0, stop=280.0,
                                                          n_energies=1, dwell=5.0)},
    )
    plan_name, params = map_scan(scan)
    assert plan_name == "stxm_fly_raster"
    region = scan["scan_regions"]["Region1"]
    assert params == {
        "y_start": region["yStart"], "y_stop": region["yStop"], "ny": 200,
        "x_start": region["xStart"], "x_stop": region["xStop"], "nx": 100,
        "dwell": 5.0,
    }


def test_fly_raster_dwell_is_milliseconds_passthrough():
    scan = _base_scan(
        energy_regions={"EnergyRegion1": _energy_region(dwell=12.5, n_energies=1)},
    )
    _, params = map_scan(scan)
    assert params["dwell"] == 12.5


# --- multi-energy Image scan -> stxm_energy_stack ---

def test_multi_energy_image_scan_maps_to_energy_stack():
    scan = _base_scan(
        scan_regions={"Region1": _image_region(x_points=50, y_points=60)},
        energy_regions={"EnergyRegion1": _energy_region(start=280.0, stop=282.0,
                                                          n_energies=3, dwell=8.0)},
    )
    plan_name, params = map_scan(scan)
    assert plan_name == "stxm_energy_stack"
    assert params["energies"] == [280.0, 281.0, 282.0]
    assert params["dwell_ms"] == 8.0
    region = scan["scan_regions"]["Region1"]
    assert params["nx"] == 50
    assert params["ny"] == 60
    assert params["x_start"] == region["xStart"]
    assert params["y_stop"] == region["yStop"]


def test_multiple_energy_regions_concatenate_in_order():
    scan = _base_scan(
        energy_regions={
            "EnergyRegion1": _energy_region(start=280.0, stop=281.0, n_energies=2, dwell=10.0),
            "EnergyRegion2": _energy_region(start=290.0, stop=290.0, n_energies=1, dwell=10.0),
        },
    )
    plan_name, params = map_scan(scan)
    assert plan_name == "stxm_energy_stack"
    assert params["energies"] == [280.0, 281.0, 290.0]


def test_energy_stack_uses_first_region_dwell():
    scan = _base_scan(
        energy_regions={
            "EnergyRegion1": _energy_region(start=280.0, stop=281.0, n_energies=2, dwell=3.0),
            "EnergyRegion2": _energy_region(start=290.0, stop=291.0, n_energies=2, dwell=99.0),
        },
    )
    _, params = map_scan(scan)
    assert params["dwell_ms"] == 3.0


# --- unsupported scan modes ---

@pytest.mark.parametrize("scan_type", [
    "Ptychography",
    "Focus",
    "Line Spectrum",
    "Single Motor",
    "Double Motor",
])
def test_unsupported_scan_types_raise(scan_type):
    scan = _base_scan(scan_type=scan_type)
    with pytest.raises(UnsupportedScanMode) as excinfo:
        map_scan(scan)
    assert excinfo.value.scan_type == scan_type


# --- missing keys ---

def test_missing_scan_type_raises_key_error():
    scan = _base_scan()
    del scan["scan_type"]
    with pytest.raises(KeyError, match="scan_type"):
        map_scan(scan)


def test_missing_scan_regions_raises_key_error():
    scan = _base_scan()
    del scan["scan_regions"]
    with pytest.raises(KeyError, match="scan_regions"):
        map_scan(scan)


def test_empty_scan_regions_raises_key_error():
    scan = _base_scan(scan_regions={})
    with pytest.raises(KeyError, match="scan_regions"):
        map_scan(scan)


def test_missing_region_key_names_the_key():
    region = _image_region()
    del region["xStart"]
    scan = _base_scan(scan_regions={"Region1": region})
    with pytest.raises(KeyError, match="xStart"):
        map_scan(scan)


def test_missing_energy_regions_raises_key_error():
    scan = _base_scan()
    del scan["energy_regions"]
    with pytest.raises(KeyError, match="energy_regions"):
        map_scan(scan)


def test_empty_energy_regions_raises_key_error():
    scan = _base_scan(energy_regions={})
    with pytest.raises(KeyError, match="energy_regions"):
        map_scan(scan)


def test_missing_energy_region_key_names_the_key():
    region = _energy_region()
    del region["dwell"]
    scan = _base_scan(energy_regions={"EnergyRegion1": region})
    with pytest.raises(KeyError, match="dwell"):
        map_scan(scan)

"""Tests for the dashboard's scan geometry.

``ScanDefinition`` is the Qt-free half of the acquisition dashboard: it holds
the regions the user edits and turns them into the dictionaries the server
scans.  These tests run without a display or a Qt import, so the arithmetic that
decides where the motors actually go can be checked directly — the golden tests
in ``test_dashboard_compile`` cover the same ground through the whole window,
but only pin it against change, whereas these say what it should be.
"""

import pytest

from pystxmcontrol.gui.dashboard_scan_definition import (
    ScanDefinition, energy_n, line_endpoints, motor_scan_region,
    region_scan_dict, resolve_daq_list,
)


def model_region(xc=0.0, yc=0.0, xr=10.0, yr=10.0, xp=10, yp=10):
    return {'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr,
            'xPoints': xp, 'yPoints': yp}


def energy_region(start=280.0, stop=290.0, step=0.5, dwell=1.0, n=21):
    return {'start': start, 'stop': stop, 'step': step, 'dwell': dwell, 'n': n}


class FakeScanModel:
    """The slice of the GUI ScanModel that emitting regions touches."""

    def __init__(self):
        self.values = {}
        self.scan_regions = {}
        self.energy_regions = {}

    def set(self, key, value):
        self.values[key] = value

    def add_scan_region(self, name, data):
        self.scan_regions[name] = data

    def add_energy_region(self, name, data):
        self.energy_regions[name] = data


# ── the full-field / half-pixel range convention ────────────────────────────

def test_region_spans_n_times_step_with_half_pixel_inset():
    """A region of N points spans N*step, and the first point sits half a step
    inside the edge — so the scan measures the range it claims to."""
    r = region_scan_dict(model_region(xc=0.0, xr=10.0, xp=10))
    assert r['xStep'] == pytest.approx(1.0)          # 10 µm over 10 points
    assert r['xStart'] == pytest.approx(-4.5)        # -5 + half a step
    assert r['xStop'] == pytest.approx(4.5)
    # The measured extent, edge to edge, is the full requested range.
    assert (r['xStop'] - r['xStart']) + r['xStep'] == pytest.approx(10.0)


def test_region_is_centred_on_its_centre():
    r = region_scan_dict(model_region(xc=7.5, yc=-3.25, xr=4.0, yr=2.0))
    assert (r['xStart'] + r['xStop']) / 2 == pytest.approx(7.5)
    assert (r['yStart'] + r['yStop']) / 2 == pytest.approx(-3.25)


def test_single_point_axis_does_not_divide_by_zero():
    r = region_scan_dict(model_region(xp=1, yp=1))
    assert r['xPoints'] == 1 and r['yPoints'] == 1
    assert r['xStep'] == pytest.approx(10.0)


def test_zero_points_is_clamped_rather_than_crashing():
    r = region_scan_dict(model_region(xp=0, yp=0))
    assert r['xPoints'] == 1 and r['yPoints'] == 1


# ── line geometry ───────────────────────────────────────────────────────────

def test_horizontal_line_matches_the_image_convention():
    """A line at 0° should sample exactly like one row of an image of the same
    length and point count."""
    x0, x1, y0, y1, ux, uy = line_endpoints(0.0, 0.0, 10.0, 0.0, 10)
    row = region_scan_dict(model_region(xc=0.0, xr=10.0, xp=10))
    assert x0 == pytest.approx(row['xStart'])
    assert x1 == pytest.approx(row['xStop'])
    assert y0 == pytest.approx(0.0) and y1 == pytest.approx(0.0)
    assert (ux, uy) == pytest.approx((1.0, 0.0))


def test_line_at_90_degrees_runs_along_y():
    x0, x1, y0, y1, ux, uy = line_endpoints(2.0, 5.0, 8.0, 90.0, 8)
    assert x0 == pytest.approx(2.0) and x1 == pytest.approx(2.0)
    assert y0 == pytest.approx(1.5) and y1 == pytest.approx(8.5)
    assert (ux, uy) == pytest.approx((0.0, 1.0), abs=1e-12)


def test_line_length_is_preserved_at_any_angle():
    for angle in (0.0, 30.0, 45.0, 90.0, 137.0):
        x0, x1, y0, y1, _, _ = line_endpoints(0.0, 0.0, 12.0, angle, 60)
        span = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        step = 12.0 / 60
        assert span + step == pytest.approx(12.0)


def test_line_is_centred_on_its_centre():
    x0, x1, y0, y1, _, _ = line_endpoints(-4.0, 9.0, 6.0, 33.0, 20)
    assert (x0 + x1) / 2 == pytest.approx(-4.0)
    assert (y0 + y1) / 2 == pytest.approx(9.0)


# ── focus and line-spectrum regions ─────────────────────────────────────────

def test_focus_region_sweeps_z_and_repeats_the_line():
    d = ScanDefinition(scan_regions=[model_region(xc=1.0, yc=2.0)])
    d.focus_region = {'length': 10.0, 'angle': 0.0, 'points': 20,
                      'zCenter': 0.0, 'zRange': 40.0, 'zPoints': 20}
    r = d.focus_scan_region()
    assert r['zPoints'] == 20
    assert r['zStep'] == pytest.approx(2.0)
    assert r['zStart'] == pytest.approx(-19.0)     # -20 + half a step
    assert r['zStop'] == pytest.approx(19.0)
    # A focus scan repeats the line once per Z step, so the slow axis is the line.
    assert r['yPoints'] == 20
    assert (r['xCenter'], r['yCenter']) == (1.0, 2.0)


def test_line_spectrum_region_has_one_row():
    """Energy is the outer loop for a line spectrum, so the line is scanned once."""
    d = ScanDefinition(scan_regions=[model_region()])
    d.focus_region = {'length': 6.0, 'angle': 0.0, 'points': 30,
                      'zCenter': 0.0, 'zRange': 0.0, 'zPoints': 1}
    r = d.line_spectrum_scan_region()
    assert r['yPoints'] == 1
    assert r['xPoints'] == 30
    assert r['xRange'] == pytest.approx(6.0)       # along-line distance


def test_line_regions_carry_true_length_as_xrange():
    """xRange is the along-line distance, not the x projection — that is what
    makes the display's horizontal axis read as distance along the line."""
    d = ScanDefinition(scan_regions=[model_region()])
    d.focus_region = {'length': 10.0, 'angle': 60.0, 'points': 10,
                      'zCenter': 0.0, 'zRange': 0.0, 'zPoints': 1}
    r = d.line_spectrum_scan_region()
    assert r['xRange'] == pytest.approx(10.0)
    assert r['xStop'] - r['xStart'] < 10.0         # the x projection is shorter


def test_focus_region_defaults_to_region_one_width():
    d = ScanDefinition(scan_regions=[model_region(xr=17.0)])
    fr = d.ensure_focus_region(z_center=-5600.0)
    assert fr['length'] == pytest.approx(17.0)
    assert fr['zCenter'] == pytest.approx(-5600.0)


def test_ensure_focus_region_does_not_overwrite_an_existing_model():
    d = ScanDefinition(scan_regions=[model_region()])
    first = d.ensure_focus_region(z_center=1.0)
    first['angle'] = 42.0
    assert d.ensure_focus_region(z_center=999.0) is first
    assert d.focus_region['angle'] == 42.0


# ── motor scans ─────────────────────────────────────────────────────────────

def test_single_motor_scan_has_one_row():
    r = motor_scan_region((0.0, 2.0, 21))
    assert r['xPoints'] == 21
    assert r['yPoints'] == 1
    assert r['yRange'] == 0.0


def test_double_motor_scan_uses_both_axes():
    r = motor_scan_region((0.0, 2.0, 21), (1.0, 1.0, 11))
    assert (r['xPoints'], r['yPoints']) == (21, 11)
    assert r['yCenter'] == pytest.approx(1.0)


# ── energy axis ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("start,stop,step,expected", [
    (280.0, 290.0, 0.5, 21),
    (280.0, 280.0, 0.5, 1),
    (280.0, 290.0, 0.0, 1),      # no step: a single energy, not a crash
    (290.0, 280.0, 0.5, 21),     # descending ranges count the same
])
def test_energy_point_count(start, stop, step, expected):
    assert energy_n(start, stop, step) == expected


def test_energy_span_covers_every_region():
    d = ScanDefinition(energy_regions=[
        energy_region(280.0, 290.0, n=21),
        energy_region(700.0, 710.0, n=11),
    ])
    assert d.energy_span() == (280.0, 710.0, 32)


def test_energy_span_falls_back_when_nothing_is_defined():
    assert ScanDefinition().energy_span() == (700.0, 730.0, 1)


def test_emit_energy_regions_marks_multi_energy_scans():
    sm = FakeScanModel()
    ScanDefinition(energy_regions=[energy_region(n=21)]).emit_energy_regions(sm)
    assert sm.values['single_energy'] is False
    assert sm.energy_regions['EnergyRegion1']['n_energies'] == 21


def test_emit_energy_regions_marks_a_single_energy_scan():
    sm = FakeScanModel()
    d = ScanDefinition(energy_regions=[energy_region(280.0, 280.0, 0.0, n=1)])
    d.emit_energy_regions(sm)
    assert sm.values['single_energy'] is True


def test_emit_single_energy_collapses_to_the_first_start():
    sm = FakeScanModel()
    d = ScanDefinition(energy_regions=[
        energy_region(280.0, 290.0, dwell=3.0, n=21),
        energy_region(700.0, 710.0, n=11),
    ])
    e0 = d.emit_single_energy(sm)
    region = sm.energy_regions['EnergyRegion1']
    assert (region['start'], region['stop']) == (280.0, 280.0)
    assert region['n_energies'] == 1
    assert region['dwell'] == 3.0            # keeps that region's own dwell
    assert len(sm.energy_regions) == 1
    assert e0['start'] == 280.0


# ── active region tracking ──────────────────────────────────────────────────

def test_active_region_follows_the_index():
    d = ScanDefinition(scan_regions=[model_region(xc=1.0), model_region(xc=2.0)])
    assert d.active_region_dict()['xCenter'] == 1.0
    d.active_region = 1
    assert d.active_region_dict()['xCenter'] == 2.0


def test_spectrum_is_edited_separately_from_the_scan_regions():
    """The spectrum ROI selects display pixels and is never scanned, so editing
    it must not touch Region 1."""
    d = ScanDefinition(scan_regions=[model_region(xc=1.0)],
                       spectrum_region=model_region(xc=9.0))
    d.active_region = 'spectrum'
    d.update_active_region({'xCenter': 5.0})
    assert d.spectrum_region['xCenter'] == 5.0
    assert d.scan_regions[0]['xCenter'] == 1.0

    sm = FakeScanModel()
    d.emit_image_regions(sm)
    assert list(sm.scan_regions) == ['Region1']


def test_out_of_range_active_region_is_not_an_error():
    d = ScanDefinition(scan_regions=[model_region()])
    d.active_region = 7
    assert d.active_region_dict() is None
    assert d.update_active_region({'xCenter': 3.0}) is None


# ── emitting spatial regions ────────────────────────────────────────────────

def test_every_region_is_emitted_in_order():
    sm = FakeScanModel()
    d = ScanDefinition(scan_regions=[model_region(xc=1.0), model_region(xc=2.0),
                                     model_region(xc=3.0)])
    first = d.emit_image_regions(sm)
    assert list(sm.scan_regions) == ['Region1', 'Region2', 'Region3']
    assert sm.scan_regions['Region2']['xCenter'] == 2.0
    assert first['xCenter'] == 1.0


def test_preview_emits_only_the_first_region():
    sm = FakeScanModel()
    d = ScanDefinition(scan_regions=[model_region(xc=1.0), model_region(xc=2.0)])
    d.emit_image_regions(sm, preview=True)
    assert list(sm.scan_regions) == ['Region1']


# ── the degenerate-grid guard ───────────────────────────────────────────────

def test_a_one_pixel_axis_is_refused():
    """A zero-width range gives the motor a NaN target, so it must be caught
    while compiling rather than at the stage."""
    d = ScanDefinition(scan_regions=[model_region(xp=1)])
    with pytest.raises(ValueError, match="Points greater than 1"):
        d.validate_image_grid()


def test_the_offending_region_is_named():
    d = ScanDefinition(scan_regions=[model_region(), model_region(yp=1)])
    with pytest.raises(ValueError, match="Region 2"):
        d.validate_image_grid()


def test_a_preview_only_validates_the_region_it_will_scan():
    d = ScanDefinition(scan_regions=[model_region(), model_region(xp=1)])
    d.validate_image_grid(preview=True)          # must not raise
    with pytest.raises(ValueError):
        d.validate_image_grid()


# ── DAQ selection ───────────────────────────────────────────────────────────

def test_daq_list_comes_from_the_scan_config():
    cfg = {'default': {'record': True}, 'ccd': {'record': True}}
    assert resolve_daq_list(cfg, {'daq_list': 'ccd'}) == ['ccd']


def test_daq_list_splits_a_comma_separated_string():
    cfg = {'a': {'record': True}, 'b': {'record': True}}
    assert resolve_daq_list(cfg, {'daq_list': 'a,b'}) == ['a', 'b']


def test_detectors_marked_not_to_record_are_dropped():
    cfg = {'a': {'record': True}, 'b': {'record': False}}
    assert resolve_daq_list(cfg, {'daq_list': 'a,b'}) == ['a']


def test_an_empty_request_uses_every_recording_detector():
    cfg = {'a': {'record': True}, 'b': {'record': False}}
    assert resolve_daq_list(cfg, {}) == ['a']


def test_a_scan_always_gets_at_least_one_detector():
    """Compiling with nothing recordable would otherwise ask the server for an
    empty detector list."""
    assert resolve_daq_list({}, {'daq_list': 'missing'}) == ['default']

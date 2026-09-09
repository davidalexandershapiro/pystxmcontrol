"""Tests for the dashboard's scan estimate, point count and stage velocity.

These three numbers are what the user reads before pressing Begin, and the
arithmetic deliberately mirrors ``ScanModel.calculate_estimated_time`` /
``get_scan_velocity`` on the server side.  Pinning the overhead constants here
is the point: if the two copies drift, the dashboard quietly starts lying about
how long a scan will take.
"""

import pytest

from pystxmcontrol.gui import dashboard_scan_stats as st


def scan_region(xp=10, yp=10, zp=1, xstep=1.0):
    return {"xPoints": xp, "yPoints": yp, "zPoints": zp, "xStep": xstep}


def erow(n=1, dwell=1.0):
    return {"n": n, "dwell": dwell}


# ── time formatting ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("seconds,expected", [
    (0, "0:00"), (5, "0:05"), (59, "0:59"), (60, "1:00"),
    (61, "1:01"), (599, "9:59"), (3600, "60:00"), (5.7, "0:05"),
])
def test_time_reads_as_minutes_and_seconds(seconds, expected):
    assert st.format_mmss(seconds) == expected


def test_a_negative_remaining_time_reads_as_zero():
    """The server's remaining-time estimate can go slightly negative at the tail
    of a scan; the user must not see a negative countdown."""
    assert st.format_mmss(-10) == "0:00"


@pytest.mark.parametrize("bad", [None, "abc", float("nan")])
def test_unusable_input_does_not_crash_the_readout(bad):
    assert st.format_mmss(bad) == "0:00"


# ── point counting ──────────────────────────────────────────────────────────

def test_points_are_the_grid_times_the_energies():
    regions = {"Region1": scan_region(xp=10, yp=20)}
    energies = {"EnergyRegion1": {"n_energies": 5}}
    assert st.total_scan_points(regions, energies) == 10 * 20 * 5


def test_points_sum_over_every_region():
    regions = {"Region1": scan_region(xp=10, yp=10),
               "Region2": scan_region(xp=5, yp=4)}
    energies = {"EnergyRegion1": {"n_energies": 2}}
    assert st.total_scan_points(regions, energies) == (100 + 20) * 2


def test_energies_sum_over_every_energy_region():
    regions = {"Region1": scan_region(xp=2, yp=2)}
    energies = {"EnergyRegion1": {"n_energies": 3},
                "EnergyRegion2": {"n_energies": 4}}
    assert st.total_scan_points(regions, energies) == 4 * 7


def test_a_focus_scan_counts_its_z_sweep_as_the_slow_axis():
    """Focus repeats the line once per Z step, so Z — not Y — is the row count."""
    regions = {"Region1": scan_region(xp=50, yp=50, zp=25)}
    energies = {"EnergyRegion1": {"n_energies": 1}}
    assert st.total_scan_points(regions, energies, is_focus=True) == 50 * 25


def test_no_energy_regions_still_counts_one_pass():
    regions = {"Region1": scan_region(xp=4, yp=4)}
    assert st.total_scan_points(regions, {}) == 16


# ── estimated time ──────────────────────────────────────────────────────────

def test_estimate_is_dominated_by_dwell():
    est, pts, n_e = st.estimate([scan_region(xp=100, yp=100)], [erow(n=1, dwell=10.0)])
    assert pts == 10000 and n_e == 1
    # 10000 points × 10 ms ≈ 100 s, plus small per-point and per-line overheads.
    assert est == pytest.approx(
        10000 * (0.010 + st.POINT_OVERHEAD_S) + 100 * 1 * st.LINE_OVERHEAD_S)


def test_ptychography_carries_a_much_larger_per_point_overhead():
    """A full CCD frame per point dominates the estimate at short dwell."""
    regions = [scan_region(xp=100, yp=100)]
    plain, _, _ = st.estimate(regions, [erow(dwell=1.0)])
    ptycho, _, _ = st.estimate(regions, [erow(dwell=1.0)], is_ptycho=True)
    assert ptycho > plain * 10


def test_no_monochromator_move_is_charged_before_the_first_energy():
    regions = [scan_region(xp=2, yp=2)]
    one, _, _ = st.estimate(regions, [erow(n=1, dwell=1.0)])
    two, _, _ = st.estimate(regions, [erow(n=2, dwell=1.0)])
    # The second energy adds exactly one monochromator move…
    assert (two - one) > st.ENERGY_OVERHEAD_S
    three, _, _ = st.estimate(regions, [erow(n=3, dwell=1.0)])
    # …and each further energy adds the same again.
    assert (three - two) == pytest.approx(two - one)


def test_per_region_dwells_are_honoured():
    """A fine near-edge region measured longer than the coarse pre-edge one."""
    regions = [scan_region(xp=10, yp=10)]
    est, pts, n_e = st.estimate(regions, [erow(n=5, dwell=1.0), erow(n=5, dwell=10.0)])
    assert n_e == 10 and pts == 1000
    same, _, _ = st.estimate(regions, [erow(n=10, dwell=5.5)])
    assert est == pytest.approx(same)      # the mean dwell gives the same total


def test_a_focus_estimate_uses_the_z_sweep():
    est_focus, pts, _ = st.estimate([scan_region(xp=50, yp=50, zp=10)],
                                    [erow(n=1, dwell=1.0)], is_focus=True)
    assert pts == 50 * 10
    est_image, _, _ = st.estimate([scan_region(xp=50, yp=50, zp=10)],
                                  [erow(n=1, dwell=1.0)])
    assert est_focus < est_image          # 10 rows instead of 50


def test_an_empty_scan_estimates_nothing():
    est, pts, n_e = st.estimate([], [])
    assert (est, pts, n_e) == (0.0, 0, 0)


# ── stage velocity ──────────────────────────────────────────────────────────

def test_velocity_is_step_over_dwell():
    """Steps are µm and dwell is ms, so µm/ms is already mm/s."""
    assert st.scan_velocity([scan_region(xstep=1.0)], 1.0) == pytest.approx(1.0)
    assert st.scan_velocity([scan_region(xstep=0.1)], 2.0) == pytest.approx(0.05)


def test_velocity_is_the_fastest_region():
    regions = [scan_region(xstep=0.1), scan_region(xstep=0.5)]
    assert st.scan_velocity(regions, 1.0) == pytest.approx(0.5)


def test_point_mode_scans_report_no_velocity():
    """Stepping to each point is not a continuous sweep, so a velocity would be
    meaningless — and would trip the over-speed warning for nothing."""
    assert st.scan_velocity([scan_region(xstep=99.0)], 1.0, point_mode=True) == 0.0


def test_zero_dwell_does_not_divide_by_zero():
    assert st.scan_velocity([scan_region(xstep=1.0)], 0.0) == pytest.approx(1.0)


def test_no_regions_has_no_velocity():
    assert st.scan_velocity([], 1.0) == 0.0

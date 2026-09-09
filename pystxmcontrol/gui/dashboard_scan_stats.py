"""How long a scan will take, how many points it measures, and how fast the
stage has to move.

Split out of ``mainwindow_dashboard``.  The window shows these three numbers
before the user presses Begin, and they have to agree with what the server will
actually do — the arithmetic mirrors ``ScanModel.calculate_estimated_time`` and
``ScanModel.get_scan_velocity``, so a duplicated constant drifting is a real
risk.  Keeping it here, and testing it, makes that drift visible.

The overheads are empirical, and they are what make the estimate more than
``points × dwell``:

* per point — the time to arm and read a detector, far larger for
  ptychography (a full CCD frame) than for a counter;
* per line — turning the stage around at the end of a row;
* per energy — moving the monochromator between energy steps.

Units are the ones the config uses: ranges and steps in µm, dwell in ms.  So
``xStep / dwell`` is already mm/s, which is why the velocity looks unit-free.
"""

POINT_OVERHEAD_S = 0.0001        # counter arm/read
PTYCHO_POINT_OVERHEAD_S = 0.1    # a full area-detector frame per point
LINE_OVERHEAD_S = 0.02           # stage turnaround at the end of a row
ENERGY_OVERHEAD_S = 5.0          # monochromator move between energies


def format_mmss(seconds):
    """``M:SS``.  Negative or non-finite input reads as ``0:00`` rather than
    showing the user a negative countdown."""
    try:
        seconds = max(0, int(seconds))
    except (TypeError, ValueError, OverflowError):
        return "0:00"
    return f"{seconds // 60:d}:{seconds % 60:02d}"


def region_points(scan_region, is_focus=False):
    """Points in one scan region.  A focus scan's slow axis is the ZonePlateZ
    sweep; every other family's is ``yPoints``."""
    rows = int(scan_region["zPoints"] if is_focus else scan_region["yPoints"])
    return int(scan_region["xPoints"]) * rows, rows


def total_scan_points(scan_regions, energy_regions, is_focus=False):
    """Every spatial point, summed over regions, measured at every energy.

    ``scan_regions`` and ``energy_regions`` are the compiled dictionaries as the
    scan model holds them (energies under ``n_energies``).
    """
    n_energies = sum(int(r.get("n_energies", 1))
                     for r in energy_regions.values()) or 1
    spatial = sum(region_points(r, is_focus)[0] for r in scan_regions.values())
    return spatial * n_energies


def estimate(regions, energy_regions, is_focus=False, is_ptycho=False):
    """``(est_seconds, total_points, n_energies)`` for a planned scan.

    ``regions`` are scan regions (start/stop/step expanded); ``energy_regions``
    are the view's own energy rows, which count points under ``n`` rather than
    ``n_energies``.
    """
    point_overhead = PTYCHO_POINT_OVERHEAD_S if is_ptycho else POINT_OVERHEAD_S
    n_points = n_lines = 0
    for rd in regions:
        pts, rows = region_points(rd, is_focus)
        n_points += pts
        n_lines += rows

    time_per_point = 0.0
    n_energies = 0
    for er in energy_regions:
        energies = int(er.get("n", 1))
        time_per_point += (er.get("dwell", 1.0) / 1000.0 + point_overhead) * energies
        n_energies += energies

    est = (n_points * time_per_point
           + n_lines * n_energies * LINE_OVERHEAD_S
           # No monochromator move before the first energy.
           + max(0, n_energies - 1) * ENERGY_OVERHEAD_S)
    return est, n_points * n_energies, n_energies


def scan_velocity(regions, dwell_ms, point_mode=False):
    """Fastest stage speed the scan demands, in mm/s.

    Point-mode scans step to each point instead of sweeping the stage
    continuously, so a velocity is meaningless there — report 0 rather than a
    number that would trip the over-speed warning for no reason.
    """
    if point_mode:
        return 0.0
    dwell_ms = dwell_ms or 1.0
    return max((rd.get("xStep", 0.0) / dwell_ms for rd in regions), default=0.0)

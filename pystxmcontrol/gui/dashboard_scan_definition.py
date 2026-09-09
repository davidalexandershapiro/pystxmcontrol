"""What the dashboard is about to scan, and how that becomes a scan model.

``ScanDefinition`` holds the editable scan geometry — the spatial regions, the
energy regions, the focus/line model — and turns it into the region dictionaries
the server expects.  It is deliberately Qt-free: the window reads its widgets,
pushes the values in here, and asks for the compiled result.  That split is what
makes the geometry testable on its own, and it keeps the region lists in one
named place instead of spread across a dozen window methods that each mutated
them.

Region dictionaries come in two shapes, and the difference matters:

*model* regions are what the user edits — ``{xCenter, yCenter, xRange, yRange,
xPoints, yPoints}``.  *scan* regions are what the server runs, adding the
start/stop/step the driver moves along.  Everything named ``*_scan_region``
converts the first into the second.

Ranges follow the full-field convention: a region of ``N`` points spans
``N * step``, and the first point sits half a step inside the edge.  The scan
therefore measures the region it says it does, and the same inset applies along
an angled line as along an axis.
"""

from dataclasses import dataclass, field as dc_field

import numpy as np


def energy_n(start, stop, step):
    """Number of energy points across ``start``..``stop`` at ``step`` eV."""
    if step and abs(step) > 0:
        return int(round(abs(stop - start) / abs(step))) + 1
    return 1


def resolve_daq_list(daq_config, scan_config):
    """DAQ channels the scan should record: those the scan config asks for,
    kept only when the detector exists and is marked ``record``."""
    requested = scan_config.get('daq_list', '')
    if isinstance(requested, str):
        requested = [t for t in requested.split(',') if t]
    if not requested:
        requested = list(daq_config or {})
    daq = [k for k in requested
           if k in (daq_config or {}) and daq_config[k].get('record', True)]
    return daq or ['default']


def region_scan_dict(r):
    """Expand a model region into a full Image scan region.

    Same shape and arithmetic as ``MainController._extract_scan_region_data``'s
    Image branch, so a dashboard scan and a classic-window scan of the same
    region ask the server for the same thing.
    """
    xc, yc = r['xCenter'], r['yCenter']
    xr, yr = r['xRange'], r['yRange']
    xp = max(1, int(r['xPoints']))
    yp = max(1, int(r['yPoints']))
    xs = xr / xp if xp > 0 else 0.1
    ys = yr / yp if yp > 0 else 0.1
    return {
        'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr,
        'xPoints': xp, 'yPoints': yp, 'xStep': xs, 'yStep': ys,
        'xStart': xc - xr / 2.0 + xs / 2.0, 'xStop': xc + xr / 2.0 - xs / 2.0,
        'yStart': yc - yr / 2.0 + ys / 2.0, 'yStop': yc + yr / 2.0 - ys / 2.0,
        'zCenter': 0, 'zRange': 0, 'zPoints': 1, 'zStep': 0,
        'zStart': 0, 'zStop': 0,
    }


def line_endpoints(xc, yc, length, angle_deg, n):
    """Endpoints of an ``n``-point scan line of ``length`` at ``angle_deg``,
    centred on ``(xc, yc)``.

    The endpoints are inset by half a point spacing, the same convention
    ``region_scan_dict`` applies per axis — so a line and an image row of equal
    length and point count sample the same physical extent.  Returns
    ``(x0, x1, y0, y1, ux, uy)``; the unit vector comes back because callers use
    it for the projected y extent.
    """
    n = max(1, int(n))
    ar = np.radians(angle_deg)
    ux, uy = np.cos(ar), np.sin(ar)
    s0 = -(length / 2.0) + (length / (2.0 * n))
    s1 = (length / 2.0) - (length / (2.0 * n))
    return xc + s0 * ux, xc + s1 * ux, yc + s0 * uy, yc + s1 * uy, ux, uy


@dataclass
class ScanDefinition:
    """The dashboard's editable scan geometry.

    ``active_region`` is an index into ``scan_regions``, or the string
    ``'spectrum'`` when the spatial fields are editing the display-only spectrum
    ROI.  That ROI selects which pixels the Profile spectrum averages; it is
    never scanned, so it is never emitted.
    """

    scan_regions: list = dc_field(default_factory=list)
    active_region: object = 0                 # int index, or 'spectrum'
    spectrum_region: dict | None = None
    energy_regions: list = dc_field(default_factory=list)
    active_energy_region: int = 0
    focus_region: dict | None = None

    # ── spatial regions ─────────────────────────────────────────────────
    def active_region_dict(self):
        """The region the spatial fields currently edit, or None."""
        if self.active_region == 'spectrum':
            return self.spectrum_region
        if isinstance(self.active_region, int) and \
                0 <= self.active_region < len(self.scan_regions):
            return self.scan_regions[self.active_region]
        return None

    def update_active_region(self, values):
        """Push edited field values into the active region, if there is one."""
        reg = self.active_region_dict()
        if reg is not None:
            reg.update(values)
        return reg

    def region(self, index=0):
        return self.scan_regions[index] if self.scan_regions else {}

    def line_center(self):
        """The focus/spectrum line is centred on Region 1."""
        r1 = self.region(0)
        return float(r1.get('xCenter', 0.0)), float(r1.get('yCenter', 0.0))

    def validate_image_grid(self, preview=False):
        """Raise if any region to be scanned is degenerate.

        An image needs more than one point on each axis; a stray ``Points=1``
        otherwise compiles a one-pixel scan whose zero-width range gives the
        motor a NaN target.
        """
        to_check = self.scan_regions[:1] if preview else self.scan_regions
        for i, r in enumerate(to_check):
            xp, yp = int(r.get('xPoints', 1)), int(r.get('yPoints', 1))
            if xp < 2 or yp < 2:
                raise ValueError(
                    f"Region {i + 1} spatial grid is {xp}×{yp} — an image scan "
                    f"needs X and Y Points greater than 1.")

    def emit_image_regions(self, sm, preview=False):
        """Add every spatial region to ``sm`` and return the first as a scan
        region.  A preview emits only the first."""
        first = region_scan_dict(self.region(0))
        if preview:
            sm.add_scan_region('Region1', first)
        else:
            for i, r in enumerate(self.scan_regions):
                sm.add_scan_region(f'Region{i + 1}', region_scan_dict(r))
        return first

    # ── energy regions ──────────────────────────────────────────────────
    def energy_span(self):
        """``(lo, hi, n)`` extent of the planned energy axis — the horizontal
        axis of the line-spectrum streak display."""
        regs = self.energy_regions or []
        if not regs:
            return 700.0, 730.0, 1
        lo = min(r['start'] for r in regs)
        hi = max(r['stop'] for r in regs)
        n = sum(int(r['n']) for r in regs) or 1
        return lo, hi, n

    def first_energy(self):
        """The first energy region, or a usable default when none is defined."""
        return self.energy_regions[0] if self.energy_regions else \
            {'start': 700.0, 'stop': 700.0, 'step': 0.0, 'dwell': 2.0, 'n': 1}

    def emit_energy_regions(self, sm):
        """Add the full multi-region energy axis to ``sm``."""
        total_n = 0
        for i, r in enumerate(self.energy_regions):
            total_n += r['n']
            sm.add_energy_region(f'EnergyRegion{i + 1}', {
                'start': r['start'], 'stop': r['stop'], 'step': r['step'],
                'dwell': r['dwell'], 'n_energies': r['n']})
        sm.set('single_energy', total_n <= 1)
        sm.set('energy_list', None)

    def emit_single_energy(self, sm):
        """Collapse the energy axis to one point: the first region's start, at
        that region's dwell.  Used by previews and by focus scans."""
        e0 = self.first_energy()
        sm.add_energy_region('EnergyRegion1', {
            'start': e0['start'], 'stop': e0['start'], 'step': 0.0,
            'dwell': e0['dwell'], 'n_energies': 1})
        sm.set('single_energy', True)
        sm.set('energy_list', None)
        return e0

    # ── focus / line geometry ───────────────────────────────────────────
    def ensure_focus_region(self, z_center=0.0):
        """Create the focus model on first use: the line spans Region 1's width,
        and the Z sweep is centred on the zone plate's current position."""
        if self.focus_region is None:
            r1 = self.region(0)
            self.focus_region = {
                'length': float(r1.get('xRange', 10.0)) or 10.0,
                'angle': 0.0, 'points': 50,
                'zCenter': z_center, 'zRange': 100.0, 'zPoints': 50}
        return self.focus_region

    def _line_scan_region(self, y_points):
        """Shared body of the focus and line-spectrum scan regions.

        Both are one angled line; they differ only in what the slow axis is.  A
        line spectrum sweeps energy, so it has a single row; a focus scan sweeps
        the zone plate, so it repeats the line once per Z step.  ``xRange``
        carries the true along-line length, which is what makes the display's
        horizontal axis read as distance along the line, while the start/stop
        pairs carry the real angled endpoints the driver moves between.
        """
        fr = self.ensure_focus_region()
        xc, yc = self.line_center()
        L = fr['length']
        n = max(1, int(fr['points']))
        x0, x1, y0, y1, _ux, uy = line_endpoints(xc, yc, L, fr['angle'], n)
        return {
            'xCenter': xc, 'yCenter': yc,
            'xRange': L, 'yRange': abs(L * uy),
            'xPoints': n, 'yPoints': y_points,
            'xStep': L / n,
            'yStep': abs(L * uy) / y_points if y_points else 0.0,
            'xStart': x0, 'xStop': x1, 'yStart': y0, 'yStop': y1,
            'zCenter': 0, 'zRange': 0, 'zPoints': 1, 'zStep': 0,
            'zStart': 0, 'zStop': 0,
        }

    def focus_scan_region(self):
        """The focus scan region: an angled line crossed with a ZonePlateZ sweep."""
        fr = self.ensure_focus_region()
        n = max(1, int(fr['points']))
        region = self._line_scan_region(y_points=n)
        zc, zr = fr['zCenter'], fr['zRange']
        zp = max(1, int(fr['zPoints']))
        zs = zr / zp if zp > 0 else 0.0
        region.update({
            'zCenter': zc, 'zRange': zr, 'zPoints': zp, 'zStep': zs,
            'zStart': zc - zr / 2.0 + zs / 2.0,
            'zStop': zc + zr / 2.0 - zs / 2.0,
        })
        return region

    def line_spectrum_scan_region(self):
        """The line-spectrum scan region: one angled line, energy as the outer
        loop, so a single slow-axis row."""
        return self._line_scan_region(y_points=1)


def motor_scan_region(x_axis, y_axis=None):
    """Scan region for a motor scan, from ``(center, range, points)`` per axis.

    A single-motor scan passes no ``y_axis``: it gets one row, and the caller
    mirrors ``y_motor`` onto ``x_motor`` so the scan model still validates.
    """
    xc, xr, xp = x_axis
    yc, yr, yp = y_axis if y_axis is not None else (0.0, 0.0, 1)
    return region_scan_dict({
        'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr,
        'xPoints': xp, 'yPoints': yp})

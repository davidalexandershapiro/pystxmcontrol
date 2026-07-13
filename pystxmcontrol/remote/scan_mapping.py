"""Pure functions mapping pystxmcontrol's scan-model dict to Lightfall plan
parameters (spec #4 Task 3).

Input shape is `ScanModel.to_dict()` as populated by
`main_controller.compile_scan_from_view` (see
`_extract_scan_region_data` / `_extract_energy_region_data`):

- ``scan['scan_regions']`` is a dict of region_name -> region dict with
  (among others) ``xStart``/``xStop``/``xPoints`` and
  ``yStart``/``yStop``/``yPoints`` (already center/range-derived — the GUI
  computes Start/Stop from xCenter/xRange/xPoints before scan_regions ever
  reaches this module, so no center/range math is needed here).
- ``scan['energy_regions']`` is a dict of region_name -> region dict with
  ``start``, ``stop``, ``n_energies``, and ``dwell`` (milliseconds — this is
  the same field `ScanModel.calculate_estimated_time` divides by 1000.0 to
  get seconds).

This module is pure: no Qt, no I/O, no lightfall imports. The energy-region
expansion (start/stop/n_energies rows -> flat eV list) mirrors
`ScanModel.get_energies()` / the plugin's `energy_ranges.expand_ranges`
convention, reimplemented standalone here.
"""
from __future__ import annotations

import numpy as np

#: scan_type values this module knows how to map. Anything else —
#: Ptychography, Focus, Line Spectrum, Single Motor, Double Motor, etc. —
#: raises UnsupportedScanMode.
_SUPPORTED_SCAN_TYPES = ("Image",)


class UnsupportedScanMode(ValueError):
    """Raised when scan['scan_type'] has no Lightfall plan mapping.

    The offending scan_type is available as `.scan_type`.
    """

    def __init__(self, scan_type: str) -> None:
        self.scan_type = scan_type
        super().__init__(f"unsupported scan_type: {scan_type!r}")


def _require(d: dict, key: str, context: str):
    if key not in d:
        raise KeyError(f"{context} missing required key {key!r}")
    return d[key]


def _scan_region_params(region: dict, context: str) -> dict:
    return {
        "y_start": float(_require(region, "yStart", context)),
        "y_stop": float(_require(region, "yStop", context)),
        "ny": int(_require(region, "yPoints", context)),
        "x_start": float(_require(region, "xStart", context)),
        "x_stop": float(_require(region, "xStop", context)),
        "nx": int(_require(region, "xPoints", context)),
    }


def _expand_energy_regions(energy_regions: dict) -> tuple[list[float], float]:
    """Expand energy_regions into a flat, ordered energies list plus the
    dwell (ms) to use for the scan.

    Each region contributes ``np.linspace(start, stop, n_energies)`` (rows
    concatenate in dict-iteration order; no dedup of shared boundary
    points — matches ScanModel.get_energies()). The first region's dwell is
    used as the scan-wide dwell; per-region dwell is not currently mixed
    into per-energy-point dwell (David's model has one dwell per region, not
    per energy plans downstream want a single dwell_ms).
    """
    energies: list[float] = []
    dwell_ms: float | None = None
    for name, region in energy_regions.items():
        context = f"energy_regions[{name!r}]"
        start = _require(region, "start", context)
        stop = _require(region, "stop", context)
        n = _require(region, "n_energies", context)
        dwell = _require(region, "dwell", context)
        if n < 1:
            raise ValueError(f"{context}: n_energies must be >= 1, got {n}")
        energies.extend(float(v) for v in np.linspace(start, stop, int(n)))
        if dwell_ms is None:
            dwell_ms = float(dwell)
    return energies, (dwell_ms if dwell_ms is not None else 1.0)


def map_scan(scan: dict) -> tuple[str, dict]:
    """Map a pystxmcontrol scan-model dict to a (plan_name, plan_kwargs) pair.

    Returns either:
      - ``("stxm_fly_raster", {y_start, y_stop, ny, x_start, x_stop, nx, dwell})``
        when the scan has exactly one (expanded) energy point, or
      - ``("stxm_energy_stack", {energies, y_start, y_stop, ny, x_start,
        x_stop, nx, dwell_ms})`` when it has more than one.

    Only ``scan_type == "Image"`` is supported; a single scan region is
    expected (the first entry of ``scan_regions`` is used — multi-region
    Image scans are out of scope for this mapping). Any other scan_type
    (Ptychography, Focus, Line Spectrum, Single Motor, Double Motor, ...)
    raises UnsupportedScanMode. Missing required keys raise KeyError naming
    the key.
    """
    scan_type = _require(scan, "scan_type", "scan")
    if scan_type not in _SUPPORTED_SCAN_TYPES:
        raise UnsupportedScanMode(scan_type)

    scan_regions = _require(scan, "scan_regions", "scan")
    if not scan_regions:
        raise KeyError("scan['scan_regions'] is empty")
    region_name = next(iter(scan_regions))
    region_params = _scan_region_params(
        scan_regions[region_name], f"scan_regions[{region_name!r}]"
    )

    energy_regions = _require(scan, "energy_regions", "scan")
    if not energy_regions:
        raise KeyError("scan['energy_regions'] is empty")
    energies, dwell_ms = _expand_energy_regions(energy_regions)

    if len(energies) <= 1:
        params = dict(region_params)
        params["dwell"] = dwell_ms
        return "stxm_fly_raster", params

    params = dict(region_params)
    params["energies"] = energies
    params["dwell_ms"] = dwell_ms
    return "stxm_energy_stack", params

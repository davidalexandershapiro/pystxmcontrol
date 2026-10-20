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

    def __init__(self, scan_type: str, message: str | None = None) -> None:
        self.scan_type = scan_type
        super().__init__(message or f"unsupported scan_type: {scan_type!r}")


class MultiRegionNotSupported(UnsupportedScanMode):
    """Raised when a scan defines more than one scan region.

    The GUI genuinely supports multi-region Image scans; remote v1 does
    not, and silently mapping only the first region would drop data.
    """


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


def _expand_energy_regions(
    energy_regions: dict, scan_type: str
) -> tuple[list[float], float]:
    """Expand energy_regions into a flat, ordered energies list plus the
    dwell (ms) to use for the scan.

    Each region contributes ``np.linspace(start, stop, n_energies)`` (rows
    concatenate in dict-iteration order; no dedup of shared boundary
    points — matches ScanModel.get_energies()). The Lightfall plans take a
    single scan-wide dwell, but David's model allows one dwell per energy
    region: if regions carry differing dwells we cannot honor them, so
    that raises UnsupportedScanMode rather than silently picking one.
    """
    energies: list[float] = []
    dwells: dict[str, float] = {}
    for name, region in energy_regions.items():
        context = f"energy_regions[{name!r}]"
        start = _require(region, "start", context)
        stop = _require(region, "stop", context)
        n = _require(region, "n_energies", context)
        dwells[name] = float(_require(region, "dwell", context))
        if n < 1:
            raise ValueError(f"{context}: n_energies must be >= 1, got {n}")
        energies.extend(float(v) for v in np.linspace(start, stop, int(n)))
    unique_dwells = set(dwells.values())
    if len(unique_dwells) > 1:
        detail = ", ".join(f"{name}={dwell}" for name, dwell in dwells.items())
        raise UnsupportedScanMode(
            scan_type,
            f"energy regions with differing dwells ({detail} ms) are not "
            "supported; Lightfall plans take a single scan-wide dwell",
        )
    return energies, (unique_dwells.pop() if unique_dwells else 1.0)


def map_scan(scan: dict) -> tuple[str, dict]:
    """Map a pystxmcontrol scan-model dict to a (plan_name, plan_kwargs) pair.

    Returns either:
      - ``("stxm_fly_raster", {y_start, y_stop, ny, x_start, x_stop, nx, dwell})``
        when the scan has exactly one (expanded) energy point, or
      - ``("stxm_energy_stack", {energies, y_start, y_stop, ny, x_start,
        x_stop, nx, dwell_ms})`` when it has more than one.

    Only ``scan_type == "Image"`` with exactly one scan region is
    supported: multi-region scans raise MultiRegionNotSupported (silently
    mapping one region would drop the rest). Any other scan_type
    (Ptychography, Focus, Line Spectrum, Single Motor, Double Motor, ...)
    raises UnsupportedScanMode, as do energy regions with differing dwells.
    Missing required keys raise KeyError naming the key.
    """
    scan_type = _require(scan, "scan_type", "scan")
    if scan_type not in _SUPPORTED_SCAN_TYPES:
        raise UnsupportedScanMode(scan_type)

    scan_regions = _require(scan, "scan_regions", "scan")
    if not scan_regions:
        raise KeyError("scan['scan_regions'] is empty")
    if len(scan_regions) > 1:
        raise MultiRegionNotSupported(
            scan_type,
            "multi-region scans not supported in remote v1; found "
            + ", ".join(scan_regions),
        )
    region_name = next(iter(scan_regions))
    region_params = _scan_region_params(
        scan_regions[region_name], f"scan_regions[{region_name!r}]"
    )

    energy_regions = _require(scan, "energy_regions", "scan")
    if not energy_regions:
        raise KeyError("scan['energy_regions'] is empty")
    energies, dwell_ms = _expand_energy_regions(energy_regions, scan_type)

    if len(energies) <= 1:
        params = dict(region_params)
        params["dwell"] = dwell_ms
        return "stxm_fly_raster", params

    params = dict(region_params)
    params["energies"] = energies
    params["dwell_ms"] = dwell_ms
    return "stxm_energy_stack", params

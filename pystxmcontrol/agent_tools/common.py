"""Constants and helpers shared by more than one tool domain.

Module-level, not methods, because they need no session state — keeping them out
of the mixins means a domain module can be read without holding ToolSet in mind.
"""

import json
import logging
import math

import numpy as np

from pystxmcontrol.controller.scan_conversion import build_server_scan, convert_scan
from pystxmcontrol.controller.scan_model import ScanModel
from pystxmcontrol.controller.tool_registry import tool

log = logging.getLogger(__name__)


"""
Instrument-control tool implementations for the TaskAgent.

Each public method on ToolSet is callable by the LLM.  Methods accept plain Python
types and return strings — the same contract as the original MCP server tools.

ToolSet holds a reference to the existing stxm_client so no second ZMQ connection
is needed.  Session state (current scan definition, cached config) lives on the
ToolSet instance and persists for the lifetime of one TaskAgent run.
"""


_TUNING_SETTLE_SECONDS = 2.0


_TUNING_MAX_STEPS = 10


_GAP_STEP_BY_HARMONIC = {1: 0.05, 3: 0.02, 5: 0.01}


_FEEDBACK_STEP = 0.1


_TUNING_MOTORS = {"gap": "EPU Gap", "feedback": "FBKOFFSET"}


_OSA_DEFAULT_VELOCITY_MM_S = 0.25


_OSA_DWELL_MIN_MS = 1.0


_OSA_DWELL_MAX_MS = 500.0


_OSA_X_MOTOR = "OSA_X"


_OSA_Y_MOTOR = "OSA_Y"


_ENERGY_MATCH_TOL_EV = 0.1


_BEAMLINE_DB_MOTOR_MAP = {
    "commanded_energy": "Energy",
    "harmonic":         "HARMONIC",
    "feedback_offset":  "FBKOFFSET",
    "epu_offset":       "EPUOFFSET",
}


def _round_to_eV(energy) -> int:
    """Round a photon energy to the nearest whole eV (half rounds up).

    Beamline-database entries do not need sub-eV precision in their key, so both
    lookups and new entries snap the energy to the nearest eV before touching the
    DB. Raises TypeError/ValueError on non-numeric input (callers report that).
    """
    return int(math.floor(float(energy) + 0.5))


def _focused_peak_center(arr: np.ndarray) -> dict | None:
    """Locate a compact bright peak (the focused OSA beam) amid smooth bright background.

    A small OSA scan can contain the faint, compact focused spot plus an off-centre ramp of
    unfocused zero-order light (often bright in one corner). The intensity-weighted centroid is
    pulled toward that bright corner. The focused spot differs from the background by its
    CURVATURE, not its brightness: it is a high-curvature peak (strongly concave-down), while
    the unfocused ramp is smooth (near-zero curvature).

    This is the 2-D, rotation-invariant form of "look at the second derivative of each line":
    a Laplacian-of-Gaussian (LoG) at the spot scale. The Laplacian is ~0 for any linear ramp,
    so the bright corner is suppressed regardless of how bright it is; the compact spot gives a
    strong positive -LoG response. We use mode='nearest' and zero a border margin to suppress the
    false Laplacian response at the abrupt bright scan edge (which otherwise wins the argmax — seen
    on real data), then take the argmax of the interior response and refine to sub-pixel with a
    local centroid of the response core. Returns {col_c,row_c,...} or None if there is no positive
    interior response (caller falls back to the plain centroid).

    Validated on synthetics: recovers a faint spot under a 6x corner ramp to ~0 px. Caveat: the
    inner edge of the unfocused annulus is a curved RIDGE that also has curvature, so if the beam
    is badly off-centre (a sharp bright annulus edge in view) the argmax can lock onto that edge.
    The large→small workflow keeps the beam centred enough to avoid this; 'prominence' is a
    relative confidence (higher = sharper, more isolated peak).
    """
    from scipy.ndimage import gaussian_laplace

    a = np.asarray(arr, dtype=float)
    if a.ndim != 2:
        return None
    ny, nx = a.shape
    a = a - float(a.min())            # shift to non-negative (LoG is invariant to a constant)

    # Spot scale ≈ a few pixels, derived from grid size so there is nothing to tune per scan.
    sigma = max(1.0, min(ny, nx) / 12.0)

    # mode='nearest' (vs the default 'reflect') avoids the large false Laplacian response that
    # the abrupt edge of a bright unfocused-light field produces at the scan boundary.
    resp = np.clip(-gaussian_laplace(a, sigma, mode="nearest"), 0.0, None)

    # Zero a border margin: even with 'nearest', residual response along the perimeter (from the
    # bright field meeting the scan edge) can beat the real interior peak. The focused beam sits
    # well inside the FOV after the large-scan recentre, so the interior is where it should be.
    margin = min(int(np.ceil(2.0 * sigma)), min(ny, nx) // 4)
    if margin > 0:
        keep = np.zeros_like(resp, dtype=bool)
        keep[margin:ny - margin, margin:nx - margin] = True
        resp = np.where(keep, resp, 0.0)
    if float(resp.max()) <= 0.0:
        return None

    # Coarse location: argmax of the (border-masked) LoG response. A linear ramp contributes ~0,
    # so this is not pulled by the bright corner. Refine to sub-pixel with a centroid of the core.
    pr, pc = np.unravel_index(int(np.argmax(resp)), resp.shape)
    win = max(1, int(round(sigma * 2.0)))
    r0, r1 = max(0, pr - win), min(ny, pr + win + 1)
    c0, c1 = max(0, pc - win), min(nx, pc + win + 1)
    sub = resp[r0:r1, c0:c1]
    t = float(sub.sum())
    if t > 0.0:
        col_c = float((sub.sum(axis=0) * np.arange(c0, c1)).sum() / t)
        row_c = float((sub.sum(axis=1) * np.arange(r0, r1)).sum() / t)
    else:
        col_c, row_c = float(pc), float(pr)

    interior = resp[margin:ny - margin, margin:nx - margin] if margin > 0 else resp
    prominence = float(resp.max()) / (float(interior.mean()) + 1e-12)
    return {"col_c": col_c, "row_c": row_c, "sigma_px": round(sigma, 2),
            "border_margin_px": margin, "prominence": round(prominence, 2)}


def _decimate(img: np.ndarray, max_particles: int | None = None) -> list[dict]:
    """Find dark (absorbing) particle regions in a transmission image.

    Uses Otsu thresholding on the inverted image, morphological cleanup, and
    connected-component labelling.  Returns a list of pixel-space bounding boxes,
    sorted by descending area, optionally capped at *max_particles*.

    Each entry: {'minr', 'minc', 'maxr', 'maxc', 'area_px'}.
    """
    from skimage.morphology import erosion, dilation
    from skimage.measure import label, regionprops
    from skimage.segmentation import clear_border
    from pystxmcontrol.utils.image import otsu_absorption_mask

    binary = otsu_absorption_mask(img)

    # Morphological cleanup: grow then shrink to merge nearby pixels and fill holes
    for _ in range(2):
        binary = dilation(binary)
    binary = erosion(binary)
    binary = clear_border(binary)

    label_img, _ = label(binary, return_num=True)
    regions = regionprops(label_img)

    boxes = sorted(
        [{'minr': r.bbox[0], 'minc': r.bbox[1],
          'maxr': r.bbox[2], 'maxc': r.bbox[3],
          'area_px': int(r.area)} for r in regions],
        key=lambda b: b['area_px'], reverse=True,
    )
    if max_particles is not None:
        boxes = boxes[:max_particles]
    return boxes


_SCAN_TYPE_ALIASES: dict[str, str] = {
    "image stack":         "Image",
    "stxm stack":          "Image",
    "ptychography stack":  "Ptychography Image",
    "ptycho stack":        "Ptychography Image",
}


def _motor_summary(motors: dict) -> dict:
    """Compact per-motor view: what an agent needs to plan a move or a scan.

    Units and travel limits only — the full motor config carries ~30 calibration and
    driver fields per motor that are noise to the agent and cost tokens on every
    get_config().  Prefers the SCAN limits where present, since those are the bounds a
    scan must fit inside.
    """
    out = {}
    for name, m in (motors or {}).items():
        if not isinstance(m, dict):
            out[name] = m
            continue
        out[name] = {
            "unit": m.get("unit"),
            "min":  m.get("minScanValue", m.get("minValue")),
            "max":  m.get("maxScanValue", m.get("maxValue")),
        }
    return out


def _resolve_scan_type(raw: str) -> str:
    """Normalise user-friendly scan type names (e.g. 'Image Stack') to server names."""
    return _SCAN_TYPE_ALIASES.get(raw.strip().lower(), raw)


def _convert_scan(scan: dict) -> dict:
    """Convert a pystxmcontrol scan dict (nested scan_regions) to the flat ScanModel format.

    Thin alias for the shared converter, which the MCP server uses too.
    """
    return convert_scan(scan)


def _build_scan_dict(scan: dict, scans_config: dict) -> dict:
    """Convert flat ScanModel dict back to the nested format expected by the server.

    Thin alias for the shared builder, which scripter (and so the MCP server) uses too.
    """
    return build_server_scan(scan, scans_config)


_UPDATE_SCAN_SCHEMA: dict = {'type': 'object',
 'properties': {'scan_type': {'type': 'string'},
                'x_motor': {'type': 'string'},
                'y_motor': {'type': 'string'},
                'x_center': {'type': 'number', 'description': 'µm'},
                'y_center': {'type': 'number', 'description': 'µm'},
                'x_range': {'type': 'number', 'description': 'µm'},
                'y_range': {'type': 'number', 'description': 'µm'},
                'x_points': {'type': 'integer'},
                'y_points': {'type': 'integer'},
                'dwell': {'type': 'number', 'description': 'ms per pixel'},
                'energy_start': {'type': 'number', 'description': 'eV'},
                'energy_stop': {'type': 'number', 'description': 'eV'},
                'energy_points': {'type': 'integer'},
                'energy_list': {'type': 'array',
                                'items': {'type': 'number'},
                                'description': 'Explicit energy list in eV'},
                'energy_preset': {'type': 'string',
                                  'description': 'Name of a saved energy definition to apply '
                                                 "(see list_energy_presets). Sets the scan's "
                                                 "energy regions, keeping each region's own "
                                                 'dwell. A path to a .json energy definition '
                                                 'also works.'},
                'autofocus': {'type': 'boolean'},
                'spiral': {'type': 'boolean'},
                'tiled': {'type': 'boolean',
                          'description': 'Large-scan mode: split into sub-regions that each '
                                         'fit the fine/piezo range (server stitches). Use '
                                         'when a range exceeds fine travel.'},
                'coarse_only': {'type': 'boolean',
                                'description': 'Large-scan mode: position with the coarse '
                                               'stage instead of the fine piezo. Use when a '
                                               'range exceeds fine travel.'},
                'sample_description': {'type': 'string'},
                'comment': {'type': 'string'},
                'proposal': {'type': 'string'},
                'experimenters': {'type': 'string'}},
 'required': []}

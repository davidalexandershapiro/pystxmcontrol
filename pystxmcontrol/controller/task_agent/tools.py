"""
Instrument-control tool implementations for the TaskAgent.

Each public method on ToolSet is callable by the LLM.  Methods accept plain Python
types and return strings — the same contract as the original MCP server tools.

ToolSet holds a reference to the existing stxm_client so no second ZMQ connection
is needed.  Session state (current scan definition, cached config) lives on the
ToolSet instance and persists for the lifetime of one TaskAgent run.
"""

import json
import logging
import time
import numpy as np
from .scan_model import ScanModel, validate_scan

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Beamline-tuning constants
# ---------------------------------------------------------------------------

# Slow-motor beam time constant: EPU Gap and the beam feedback take ~2 s for the
# beam to settle after the move command returns.  step_tuning_parameter() sleeps
# this long before yielding so the next measurement reflects the new beam.
_TUNING_SETTLE_SECONDS = 2.0
# Maximum steps from the search origin in either direction (per parameter).
_TUNING_MAX_STEPS = 10
# EPU gap step size (mm) by undulator harmonic.
_GAP_STEP_BY_HARMONIC = {1: 0.05, 3: 0.02, 5: 0.01}
# Feedback-offset step size (fixed).
_FEEDBACK_STEP = 0.1
# Logical tuning parameter name -> motor axis.
_TUNING_MOTORS = {"gap": "EPU Gap", "feedback": "FBKOFFSET"}

# ---------------------------------------------------------------------------
# OSA-alignment constants
# ---------------------------------------------------------------------------

# Target OSA stage velocity (mm/s) used to derive the per-pixel dwell.  OSA motors
# are finicky and per-instrument: too fast or too slow distorts the image.  This is
# the fallback when main.json["scan"]["osa_velocity_mm_s"] is absent.
_OSA_DEFAULT_VELOCITY_MM_S = 0.25
# Sane per-pixel dwell band (ms).  A computed dwell outside this range means the
# geometry/velocity combination is suspect — configure_osa_scan warns but proceeds.
_OSA_DWELL_MIN_MS = 1.0
_OSA_DWELL_MAX_MS = 500.0
# OSA scan motors (continuousLine double_motor_scan; never OSA_Z).
_OSA_X_MOTOR = "OSA_X"
_OSA_Y_MOTOR = "OSA_Y"

# Beamline-database columns that map cleanly to a live motor position, for
# save_beamline_entry(populate_from_current=True).  Other columns (grating, exit
# slits, m121/m101 angles) have no unambiguous motor and must be passed explicitly.
_BEAMLINE_DB_MOTOR_MAP = {
    "commanded_energy": "Energy",
    "harmonic":         "HARMONIC",
    "feedback_offset":  "FBKOFFSET",
    "epu_offset":       "EPUOFFSET",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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

def _resolve_scan_type(raw: str) -> str:
    """Normalise user-friendly scan type names (e.g. 'Image Stack') to server names."""
    return _SCAN_TYPE_ALIASES.get(raw.strip().lower(), raw)


def _convert_scan(scan: dict) -> dict:
    """Convert a pystxmcontrol scan dict (nested scan_regions) to the flat ScanModel format."""
    return {
        'scan_type':          scan['scan_type'],
        'proposal':           scan['proposal'],
        'experimenters':      scan['experimenters'],
        'nx_file_version':    float(scan.get('nx_file_version') or 3.0),
        'sample_description': scan['sample'],
        'x_motor':            scan['x_motor'],
        'y_motor':            scan['y_motor'],
        'z_motor':            scan.get('z_motor'),
        'x_center':           scan['scan_regions']['Region1']['xCenter'],
        'y_center':           scan['scan_regions']['Region1']['yCenter'],
        'z_center':           scan['scan_regions']['Region1']['zCenter'],
        'x_range':            scan['scan_regions']['Region1']['xRange'],
        'y_range':            scan['scan_regions']['Region1']['yRange'],
        'z_range':            scan['scan_regions']['Region1']['zRange'],
        'x_points':           scan['scan_regions']['Region1']['xPoints'],
        'y_points':           scan['scan_regions']['Region1']['yPoints'],
        'z_points':           scan['scan_regions']['Region1']['zPoints'],
        'energy_start':       scan['energy_regions']['EnergyRegion1']['start'],
        'energy_stop':        scan['energy_regions']['EnergyRegion1']['stop'],
        'energy_points':      scan['energy_regions']['EnergyRegion1']['n_energies'],
        'dwell':              scan['energy_regions']['EnergyRegion1']['dwell'],
        'spiral':             scan.get('spiral', False),
        'autofocus':          scan.get('autofocus', True),
        'defocus':            scan.get('defocus', False),
        'daq_list':           scan.get('daq_list', ['default']),
        'comment':            scan.get('comment', ''),
        'energy_list':        scan.get('energy_list'),
        'retract':            scan.get('retract', True),
        'double_exposure':    False,
        'loop_scan':          False,
    }


def _build_scan_dict(scan: dict, scans_config: dict) -> dict:
    """Convert flat ScanModel dict back to the nested format expected by the server."""
    # Match the GUI/server convention (mainwindow_mvc / main_controller._get_region):
    # x_range is the FULL field (N*step), so step = range/points and the first/last pixel
    # CENTERS are inset half a pixel from the field edges → the scanned span is (N-1)*step.
    # Using range/(points-1) with no inset (as the scripter does) makes the field one pixel
    # too big. Use the unrounded step for start/stop to match the GUI exactly; round only
    # the reported step field.
    x_step_raw = scan['x_range'] / scan['x_points'] if scan['x_points'] else 0.0
    x_start  = scan['x_center'] - scan['x_range'] / 2.0 + x_step_raw / 2.0
    x_stop   = scan['x_center'] + scan['x_range'] / 2.0 - x_step_raw / 2.0
    x_step   = round(x_step_raw, 3)
    y_step_raw = scan['y_range'] / scan['y_points'] if scan['y_points'] else 0.0
    y_start  = scan['y_center'] - scan['y_range'] / 2.0 + y_step_raw / 2.0
    y_stop   = scan['y_center'] + scan['y_range'] / 2.0 - y_step_raw / 2.0
    y_step   = round(y_step_raw, 3)
    z_step_raw = scan['z_range'] / scan['z_points'] if scan['z_points'] else 0.0
    z_start  = scan['z_center'] - scan['z_range'] / 2.0 + z_step_raw / 2.0
    z_stop   = scan['z_center'] + scan['z_range'] / 2.0 - z_step_raw / 2.0
    z_step   = round(z_step_raw, 3)

    energy_list = scan.get('energy_list')
    if energy_list:
        e_start  = energy_list[0]
        e_stop   = energy_list[-1]
        e_points = len(energy_list)
    else:
        e_start  = scan['energy_start']
        e_stop   = scan['energy_stop']
        e_points = scan['energy_points']
    e_step = (e_stop - e_start) / max(e_points, 1)

    scan_type = scan['scan_type']
    driver = scans_config.get(scan_type, {}).get('driver', 'derived_line_image')
    mode   = scans_config.get(scan_type, {}).get('mode', 'continuousLine')

    return {
        'scan_type':          scan_type,
        'proposal':           scan['proposal'],
        'experimenters':      scan['experimenters'],
        'sample':             scan['sample_description'],
        'x_motor':            scan['x_motor'],
        'y_motor':            scan['y_motor'],
        'z_motor':            scan.get('z_motor'),
        'energy_motor':       'Energy',
        'doubleExposure':     scan.get('double_exposure', False),
        'n_repeats':          1,
        'defocus':            scan.get('defocus', False),
        'autofocus':          scan.get('autofocus', True),
        'oversampling_factor': 3,
        'mode':               mode,
        'coarse_only':        scan.get('coarse_only', False),
        'spiral':             scan.get('spiral', False),
        'tiled':              scan.get('tiled', False),
        'daq_list':           scan.get('daq_list', ['default']),
        'comment':            scan.get('comment', ''),
        'loop_scan':          scan.get('loop_scan', False),
        'energy_list':        energy_list,
        'dwell':              scan['dwell'],
        'retract':            scan.get('retract', True),
        'driver':             driver,
        'scan_regions': {
            'Region1': {
                'xStart':  x_start, 'xStop':  x_stop,
                'xPoints': scan['x_points'], 'xStep': x_step,
                'xRange':  scan['x_range'],  'xCenter': scan['x_center'],
                'yStart':  y_start, 'yStop':  y_stop,
                'yPoints': scan['y_points'], 'yStep': y_step,
                'yRange':  scan['y_range'],  'yCenter': scan['y_center'],
                'zStart':  z_start, 'zStop':  z_stop,
                'zPoints': scan['z_points'], 'zStep': z_step,
                'zRange':  scan['z_range'],  'zCenter': scan['z_center'],
            }
        },
        'energy_regions': {
            'EnergyRegion1': {
                'dwell':      scan['dwell'],
                'start':      e_start,
                'stop':       e_stop,
                'step':       e_step,
                'n_energies': e_points,
                'energy_list': energy_list,
            }
        },
    }


# ---------------------------------------------------------------------------
# ToolSet
# ---------------------------------------------------------------------------

class ToolSet:
    """Wraps all task agent tools with shared client and session state.

    One ToolSet instance is created per TaskAgent run.  ``dispatch`` maps
    tool names to methods so the agent loop doesn't need to know about the
    individual functions.
    """

    def __init__(self, client, image_model=None):
        self._client = client
        self._image_model = image_model
        # Flat scan definition managed by update_scan / start_scan
        self._scan: dict = ScanModel().model_dump()
        # Cached config — populated on first get_config() call
        self._motors: dict | None = None
        self._scans_config: dict | None = None   # from scan.json — driver/mode metadata
        self._last_scans: dict | None = None      # from main_config["lastScan"] — actual params
        self._positions: dict | None = None

        self._particle_regions: list[dict] | None = None
        # Latest element-specific particle list from the intelligence two-energy map report,
        # cached whenever get_intelligence_recommendations() drains one so it survives the
        # queue clear and can be loaded into a multi-region scan.
        self._last_particle_report: list[dict] | None = None
        self._was_scanning: bool = False         # tracks scanning→idle transition
        self._last_was_multiregion: bool = False  # prevent lastScan contamination after multiregion

        # Most recent OSA beam-center result (µm in OSA_X/OSA_Y motor coordinates),
        # cached by get_osa_beam_center() and consumed by zero_osa_position().
        self._osa_beam_center: dict | None = None

        # Active beamline-tuning session (None when not tuning).  Holds the search
        # origins, harmonic-derived step sizes, and the current commanded positions
        # for EPU Gap / FBKOFFSET so the 1-D line searches stay bounded.
        self._tuning: dict | None = None

        # Eagerly seed from already-fetched client state.  The controller calls
        # get_config() before constructing TaskAgent, so these attributes are ready.
        # This means update_scan() works correctly even if the LLM skips get_config()
        # because it already saw the results in conversation history.
        self._seed_from_client()

    def _seed_from_client(self):
        """Populate cached state from whatever the client already holds."""
        if getattr(self._client, 'motorInfo', None):
            self._motors = self._client.motorInfo
        if getattr(self._client, 'scanConfig', None):
            self._scans_config = self._client.scanConfig
        if getattr(self._client, 'currentMotorPositions', None):
            self._positions = self._client.currentMotorPositions

        main_cfg = getattr(self._client, 'main_config', None) or {}
        self._last_scans = main_cfg.get('lastScan', {})
        scan_type = self._scan.get('scan_type', 'Image')
        server_scan = self._last_scans.get(scan_type)
        if server_scan:
            try:
                self._scan = ScanModel(**_convert_scan(server_scan)).model_dump()
            except Exception as e:
                log.warning("[ToolSet] _seed_from_client: _convert_scan failed for %r: %s", scan_type, e)
        else:
            log.warning("[ToolSet] _seed_from_client: no lastScan entry for %r (available: %s)",
                        scan_type, list(self._last_scans.keys()))

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def get_safety_instructions(self) -> str:
        return (
            "CRITICAL SAFETY RULES:\n"
            "  1. Always ask the user to confirm the scan configuration before executing.\n"
            "  2. Never move the OSA_Z motor — this can cause hardware failure.\n"
            "  3. Ask for confirmation before moving CoarseR by more than 5 degrees.\n"
            "  4. Ask for confirmation before moving Energy by more than 100 eV.\n"
            "  5. Never attempt to move a motor beyond its software limit.\n"
            "\n"
            "GENERAL OPERATING RULES:\n"
            "  1. If a tool fails, report the failure and ask how to proceed.\n"
            "  2. Ask for confirmation if scans are larger than 100x100 pixels or dwell > 5 ms.\n"
            "  3. Ask for confirmation if more than ~10 energies are requested.\n"
            "  4. Ask for confirmation if scan range > 50x50 µm (Sample) or 500x500 µm (OSA).\n"
            "  5. Ask for confirmation if scan positions are far from current motor positions.\n"
            "\n"
            "TYPICAL IMAGE SCAN WORKFLOW:\n"
            "  1. Call get_config() to get current state.\n"
            "  2. Call update_scan() with desired parameters.\n"
            "  3. Confirm the configuration with the user.\n"
            "  4. Call start_scan().\n"
            "  5. Call get_scan_status() to check progress.\n"
            "  6. Report results to the user."
        )

    def get_config(self) -> str:
        """Fetch current motor positions, scan configs, and DAQ settings from the server."""
        try:
            self._client.get_config()
            self._motors       = self._client.motorInfo
            self._scans_config = self._client.scanConfig        # scan.json: driver/mode metadata
            self._last_scans   = (self._client.main_config or {}).get("lastScan", {})
            self._positions    = self._client.currentMotorPositions

            # Seed self._scan from the server's last-used scan parameters so that
            # update_scan() starts from real values, not ScanModel defaults.
            # Skip if the last scan was a multiregion scan — its lastScan entry has
            # per-particle geometry (tiny x/y range and points) that would corrupt
            # the baseline for the next regular scan.
            scan_type = self._scan.get('scan_type', 'Image')
            server_scan = self._last_scans.get(scan_type)
            if server_scan and not self._last_was_multiregion:
                try:
                    self._scan = ScanModel(**_convert_scan(server_scan)).model_dump()
                except Exception as e:
                    log.warning("[ToolSet] get_config: _convert_scan failed for %r: %s", scan_type, e)
            elif not server_scan:
                log.warning("[ToolSet] get_config: no lastScan entry for %r (available: %s)",
                            scan_type, list(self._last_scans.keys()))
            self._last_was_multiregion = False

            config_summary = {
                "motors":     list(self._motors.keys()) if self._motors else [],
                "scan_types": list(self._scans_config.keys()) if self._scans_config else [],
                "positions":  self._positions,
            }
            return json.dumps(config_summary, indent=2)
        except Exception as e:
            return f"Failed to get config: {e}"

    def get_motor_position(self, axis: str) -> str:
        """Return the current position of a named motor."""
        if self._positions is None:
            self.get_config()
        if self._motors and axis not in self._motors:
            return f"Unknown motor '{axis}'. Call get_config() to see available motors."
        try:
            pos = self._positions.get(axis) if self._positions else None
            if pos is None:
                # Refresh positions
                self.get_config()
                pos = self._positions.get(axis) if self._positions else None
            return f"Current position of {axis}: {round(float(pos), 4)}" if pos is not None \
                   else f"Position not available for {axis}"
        except Exception as e:
            return f"Failed to get position for {axis}: {e}"

    def move_motor(self, axis: str, pos: float) -> str:
        """Move a named motor to the given position."""
        if self._motors is None:
            self.get_config()
        if self._motors and axis not in self._motors:
            return f"Unknown motor '{axis}'. Call get_config() for the motor list."
        try:
            response = self._client.send_message({"command": "moveMotor", "axis": axis, "pos": pos})
            if response and response.get('status'):
                return f"Successfully moved {axis} to {pos}"
            else:
                data = response.get('data', 'no details') if response else 'no response'
                return f"Move failed for {axis}: {data}"
        except Exception as e:
            return f"Failed to move {axis}: {e}"

    def update_scan(self, **kwargs) -> str:
        """Update the current scan definition.

        Call without arguments to inspect the current configuration.
        Pass keyword arguments matching ScanModel fields to change values.
        The updated scan is held in memory until start_scan() is called.
        """
        try:
            if kwargs:
                # Load the last-used scan for this scan_type as the baseline if
                # scan_type is changing or if we have a server-side baseline.
                scan_type = _resolve_scan_type(
                    kwargs.get('scan_type', self._scan.get('scan_type', 'Image'))
                )
                kwargs['scan_type'] = scan_type   # write resolved name back into kwargs
                if self._scans_config is not None and scan_type not in self._scans_config:
                    valid = ", ".join(sorted(self._scans_config.keys()))
                    return (
                        f"Unknown scan_type '{scan_type}'. "
                        f"Valid types are: {valid}. "
                        f"Note: colloquial terms like 'stack', 'z-stack', or 'tomo' are not valid — "
                        f"use the exact names listed above."
                    )
                # If the caller is setting an energy range but not an explicit energy_list,
                # clear any energy_list from the baseline — otherwise it silently overrides
                # energy_start/stop/points in both _build_scan_dict and stxm._extractEnergies.
                _energy_range_keys = {'energy_start', 'energy_stop', 'energy_points'}
                if _energy_range_keys & kwargs.keys() and 'energy_list' not in kwargs:
                    kwargs['energy_list'] = None

                # Seed from the server's last-used scan ONLY when switching scan types.
                # For repeated updates of the same type, build on the in-memory working scan
                # so earlier edits in this session (e.g. x_range, tiled) are preserved instead
                # of being reset to the stale server baseline.
                last_scans = self._last_scans or {}
                changing_type = scan_type != self._scan.get('scan_type')
                if changing_type and scan_type in last_scans:
                    try:
                        baseline = _convert_scan(last_scans[scan_type])
                        merged = {**baseline, **kwargs}
                    except Exception:
                        merged = {**self._scan, **kwargs}
                else:
                    merged = {**self._scan, **kwargs}
                ok, err = validate_scan(merged)
                if not ok:
                    return f"Invalid scan parameters: {err}"
                self._scan = ScanModel(**merged).model_dump()
                return "Scan updated: " + json.dumps(self._scan, indent=2)
            else:
                return "Current scan definition: " + json.dumps(self._scan, indent=2)
        except Exception as e:
            return f"Failed to update scan: {e}"

    def _validate_scan_limits(self) -> tuple:
        """Core scan-range check, mirroring the GUI's scan_model.validate_ranges.

        Each axis's scan range must fit within the motor's travel (maxValue - minValue,
        i.e. the fine/piezo range) from the motor config.  A range that exceeds it can still
        run as a tiled scan (split into sub-regions) or a coarse_only scan (coarse stage
        instead of the piezo) — exactly the escape hatches the GUI uses.  If a range is
        oversize and neither flag is set, this returns ok=False with needs_decision=True so
        the agent can ask the user which mode to use.

        Returns (ok: bool, result: dict).
        """
        if self._motors is None:
            self.get_config()
        motors = self._motors or {}
        tiled = bool(self._scan.get("tiled", False))
        coarse_only = bool(self._scan.get("coarse_only", False))

        checks = [
            ("x_range", self._scan.get("x_motor", ""), "X"),
            ("y_range", self._scan.get("y_motor", ""), "Y"),
            ("z_range", self._scan.get("z_motor") or "", "Z"),
        ]
        oversize, detail = [], []
        for range_key, motor_name, axis in checks:
            try:
                scan_range = float(self._scan.get(range_key, 0) or 0)
            except (TypeError, ValueError):
                scan_range = 0.0
            if scan_range <= 0 or not motor_name:
                continue
            info = motors.get(motor_name, {})
            if "minValue" not in info or "maxValue" not in info:
                detail.append(f"{axis} ({motor_name}): no limits in motor config — skipped")
                continue
            min_val, max_val = float(info["minValue"]), float(info["maxValue"])
            travel = max_val - min_val
            detail.append(f"{axis} {motor_name}: range {scan_range:.3f} vs "
                          f"travel {travel:.3f} [{min_val:.3f}, {max_val:.3f}]")
            if scan_range > travel:
                oversize.append(f"{axis} range {scan_range:.3f} exceeds {motor_name} "
                                f"fine travel {travel:.3f} ({min_val:.3f} to {max_val:.3f})")

        # No oversize axes, or the user already chose a large-scan mode → OK.
        if not oversize:
            return True, {"ok": True, "detail": detail,
                          "message": "Scan ranges fit within motor travel limits."}
        if tiled or coarse_only:
            mode = "tiled" if tiled else "coarse_only"
            return True, {"ok": True, "mode": mode, "oversize": oversize, "detail": detail,
                          "message": f"Range exceeds fine travel; will run as a {mode} scan."}

        # Oversize and no mode chosen → the agent must ask the user.
        return False, {
            "ok": False,
            "needs_decision": True,
            "scan_type": self._scan.get("scan_type", ""),
            "oversize": oversize,
            "detail": detail,
            "options": {
                "tiled": "Split into sub-regions that each fit the fine/piezo range; the "
                         "server stitches them. Set with update_scan(tiled=True). Typical for "
                         "large area Image scans.",
                "coarse_only": "Position with the coarse stage instead of the fine piezo. "
                               "Set with update_scan(coarse_only=True).",
            },
            "message": ("Scan range exceeds the fine/piezo travel. Ask the user whether to run "
                        "it as a 'tiled' or 'coarse_only' scan, set that flag via update_scan(), "
                        "then start_scan(). (These are the same options the GUI offers.)"),
        }

    def check_scan_limits(self) -> str:
        """Validate the current scan geometry against motor (fine/piezo) travel limits.

        Same check the GUI runs before starting a scan.  If a range exceeds the fine travel
        and no large-scan mode is selected, the result has needs_decision=True and lists the
        'tiled' vs 'coarse_only' options — ask the user, then set the chosen flag with
        update_scan(tiled=True) or update_scan(coarse_only=True) and start_scan().
        Call this before start_scan(); start_scan() also runs it and refuses if unresolved.
        """
        _, result = self._validate_scan_limits()
        return json.dumps(result, indent=2)

    def start_scan(self) -> str:
        """Submit the current scan definition to the server and start acquisition.

        Returns immediately once the server acknowledges the scan has started.
        Use get_scan_status() to poll for completion.
        """
        if self._scans_config is None:
            self.get_config()
        ok, result = self._validate_scan_limits()
        if not ok:
            return ("Scan not started — range exceeds the fine/piezo travel: "
                    + "; ".join(result["oversize"])
                    + ". Ask the user whether to run a tiled or coarse_only scan, then "
                      "update_scan(tiled=True) or update_scan(coarse_only=True) and retry.")
        try:
            scan_dict = _build_scan_dict(self._scan, self._scans_config or {})
            response = self._client.send_message({"command": "scan", "scan": scan_dict})
            if response and response.get('status'):
                self._was_scanning = True
                return f"Scan started: {self._scan['scan_type']} ({self._scan['x_range']}×{self._scan['y_range']} µm)"
            else:
                data = response.get('data', 'no details') if response else 'no response'
                return f"Scan failed to start: {data}"
        except Exception as e:
            return f"Failed to start scan: {e}"

    def get_scan_status(self) -> str:
        """Check whether a scan is currently running."""
        try:
            response = self._client.get_status()
            mode = response.get('mode', 'unknown') if response else 'unknown'
            if mode == 'scanning':
                self._was_scanning = True
                return "Scan is running."
            elif mode == 'idle':
                if self._was_scanning:
                    self._was_scanning = False
                    return ("Scan complete — instrument is now idle. "
                            "Call get_last_scan_stats() to analyse the result.")
                return "Instrument is idle."
            else:
                return f"Status: {mode}"
        except Exception as e:
            return f"Failed to get scan status: {e}"

    def wait_for_scan(self, timeout_seconds: float | None = None) -> str:
        """Block until the current scan finishes, then return a completion message.

        Uses the server's live time_remaining estimate (updated during the scan) to
        set the timeout.  Call this once after start_scan() instead of polling
        get_scan_status() in a loop — it consumes only one agent iteration.
        """
        import time as _time

        POLL_INTERVAL = 3.0   # seconds between status checks

        if timeout_seconds is None:
            # Use the most recently received time_remaining from the monitor stream,
            # or fall back to a conservative 30-minute ceiling.
            tr = (self._image_model.get('time_remaining')
                  if self._image_model is not None else None)
            timeout_seconds = (tr * 2.0) if (tr and tr > 0) else 1800.0

        deadline = _time.monotonic() + timeout_seconds
        self._was_scanning = True   # ensure completion message fires on idle

        while _time.monotonic() < deadline:
            try:
                response = self._client.get_status()
                mode = response.get('mode', 'unknown') if response else 'unknown'
            except Exception as e:
                return f"Error checking scan status: {e}"

            if mode == 'idle':
                self._was_scanning = False
                return ("Scan complete — instrument is now idle. "
                        "Call get_last_scan_stats() to analyse the result.")

            # Refresh timeout from the live time_remaining estimate if available
            if self._image_model is not None:
                tr = self._image_model.get('time_remaining')
                if tr and tr > 0:
                    deadline = _time.monotonic() + tr * 2.0

            _time.sleep(POLL_INTERVAL)

        self._was_scanning = False
        return (f"Timed out after {timeout_seconds:.0f} s waiting for scan to finish. "
                "Call get_scan_status() to check current state.")

    def get_last_scan_stats(self, daq: str = "default") -> str:
        """Return statistics and spatial analysis of the most recently completed scan image.

        Computes mean, std, contrast, and the physical coordinates (µm) of the
        darkest region — useful for locating absorbing features such as particles.
        """
        if self._image_model is None:
            return "Image model not available."

        all_images = self._image_model.get('all_detector_images')
        if not isinstance(all_images, dict):
            return "No scan image available yet — run a scan first."

        # Fall back to 'default' if the requested DAQ is absent
        image = all_images.get(daq)
        if image is None and daq != 'default':
            image = all_images.get('default')
            daq = 'default'
        if image is None or not isinstance(image, np.ndarray) or image.ndim < 2:
            return f"No valid image data for DAQ '{daq}'."

        ny, nx = image.shape[:2]
        flat = image.astype(float)

        mean_val  = float(np.mean(flat))
        std_val   = float(np.std(flat))
        min_val   = float(np.min(flat))
        max_val   = float(np.max(flat))
        contrast  = round(std_val / mean_val, 4) if mean_val > 0 else 0.0

        # Physical geometry from the model
        x_center = float(self._image_model.get('x_center') or 0.0)
        y_center = float(self._image_model.get('y_center') or 0.0)
        x_range  = float(self._image_model.get('x_range')  or 1.0)
        y_range  = float(self._image_model.get('y_range')  or 1.0)

        def px_to_um(col, row):
            x = x_center + (col / max(nx - 1, 1) - 0.5) * x_range
            y = y_center + (row / max(ny - 1, 1) - 0.5) * y_range
            return round(x, 3), round(y, 3)

        # Single darkest pixel
        min_row, min_col = np.unravel_index(np.argmin(flat), flat.shape)
        darkest_x, darkest_y = px_to_um(min_col, min_row)

        # Centroid of pixels in the darkest 20 % of the dynamic range.
        # Using a range-based threshold (not a rank percentile) so that a mostly
        # uniform image with a few dark spots still isolates those spots correctly.
        dyn_range = max_val - min_val
        if dyn_range > 0:
            threshold = min_val + 0.20 * dyn_range
            dark_rows, dark_cols = np.where(flat <= threshold)
            if len(dark_rows) == 0:
                dark_rows, dark_cols = np.array([min_row]), np.array([min_col])
        else:
            # Uniform image — centroid is the image centre
            dark_rows, dark_cols = np.array([ny // 2]), np.array([nx // 2])
        centroid_x, centroid_y = px_to_um(
            float(np.mean(dark_cols)), float(np.mean(dark_rows))
        )

        available_daqs = list(all_images.keys())

        result = {
            "daq": daq,
            "available_daqs": available_daqs,
            "image_shape_px": [ny, nx],
            "scan_area_um": {"x_range": x_range, "y_range": y_range,
                             "x_center": x_center, "y_center": y_center},
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "min": round(min_val, 4),
            "max": round(max_val, 4),
            "contrast": contrast,
            "darkest_pixel_um": {"x": darkest_x, "y": darkest_y},
            "dark_region_centroid_um": {"x": centroid_x, "y": centroid_y},
            "interpretation": (
                "High contrast (>0.3) suggests absorbing features present. "
                "dark_region_centroid_um gives the physical centre of the "
                "darkest 10% of pixels — a good re-centre target for a zoom scan."
            ),
        }
        return json.dumps(result, indent=2)

    def find_particles(self, max_particles: int | None = None, daq: str = "default") -> str:
        """Locate absorbing particles in a single transmission image and return scan regions.

        Uses Otsu thresholding on the inverted image plus connected-component analysis — this
        finds *generic* absorbers in ONE image; it is NOT element-specific.  For an element
        request (e.g. iron) after a two-energy scan, use the intelligence module's elemental-map
        result instead: get_intelligence_recommendations() -> load_intelligence_particles().
        Results are stored internally and can be submitted immediately with start_multiregion_scan().

        Args:
            max_particles: cap on regions returned, ordered by size (default: all found).
            daq: detector channel to analyse.
        """
        if self._image_model is None:
            return "Image model not available."

        all_images = self._image_model.get('all_detector_images')
        if not isinstance(all_images, dict):
            return "No scan image available — run an overview scan first."

        image = all_images.get(daq)
        if image is None and daq != 'default':
            image = all_images.get('default')
            daq = 'default'
        if image is None or not isinstance(image, np.ndarray) or image.ndim < 2:
            return f"No valid image for DAQ '{daq}'."

        ny, nx = image.shape[:2]
        x_center = float(self._image_model.get('x_center') or 0.0)
        y_center = float(self._image_model.get('y_center') or 0.0)
        x_range  = float(self._image_model.get('x_range')  or 1.0)
        y_range  = float(self._image_model.get('y_range')  or 1.0)
        px_x = x_range / nx   # µm per pixel in x
        px_y = y_range / ny   # µm per pixel in y

        boxes = _decimate(image, max_particles=max_particles)
        if not boxes:
            return "No particles found. Try a lower threshold or check that there is contrast in the image."

        # Convert pixel bboxes → µm scan regions with 30% padding (min 2 pixels each side)
        pad_px = 2
        regions = []
        for b in boxes:
            minr = max(0, b['minr'] - pad_px)
            minc = max(0, b['minc'] - pad_px)
            maxr = min(ny - 1, b['maxr'] + pad_px)
            maxc = min(nx - 1, b['maxc'] + pad_px)

            # Centre and size in µm
            cx = x_center + (((minc + maxc) / 2) / (nx - 1) - 0.5) * x_range
            cy = y_center + (((minr + maxr) / 2) / (ny - 1) - 0.5) * y_range
            rx = (maxc - minc) * px_x
            ry = (maxr - minr) * px_y

            regions.append({
                'xCenter': round(cx, 3), 'yCenter': round(cy, 3),
                'xRange':  round(rx, 3), 'yRange':  round(ry, 3),
            })

        self._particle_regions = regions
        # Store the overview pixel size (µm/px) so start_multiregion_scan() has a
        # sensible default if no pixel_size_nm is requested.
        self._overview_pixel_size_um = (px_x, px_y)

        overview_pixel_nm = round(px_x * 1000, 1)
        result = {
            "particles_found": len(regions),
            "overview_pixel_size_nm": overview_pixel_nm,
            "overview_scan_um": {"x_range": x_range, "y_range": y_range,
                                  "x_center": x_center, "y_center": y_center},
            "regions": regions,
            "next_step": "Call start_multiregion_scan() to image all regions. "
                         "Pass pixel_size_nm to scan at higher resolution than the overview "
                         f"(overview was {overview_pixel_nm} nm/px).",
        }
        return json.dumps(result, indent=2)

    def start_multiregion_scan(self, pixel_size_nm: float | None = None) -> str:
        """Start an image scan covering every loaded particle region.

        Region list comes from whichever you called last: load_intelligence_particles()
        (element-specific, from the two-energy map — preferred for element requests) or
        find_particles() (generic absorbers in a single image).
        Uses the current scan parameters (energy, dwell, proposal, etc.) but replaces
        the scan geometry with those particle regions.

        Args:
            pixel_size_nm: desired pixel size in nm for the zoom scans. Each region
                gets its own point count computed as round(range_um / pixel_size_um).
                If omitted, uses the overview scan's pixel size as the default.
        """
        if not getattr(self, '_particle_regions', None):
            return ("No particle regions available — call load_intelligence_particles() "
                    "(element-specific, from the two-energy map) or find_particles() first.")
        if self._scans_config is None:
            return "Scan config not loaded — call get_config() first."

        # Resolve pixel size: explicit arg → stored overview size → safe fallback
        if pixel_size_nm is not None:
            px_um = pixel_size_nm / 1000.0
        elif getattr(self, '_overview_pixel_size_um', None):
            px_um = float(np.mean(self._overview_pixel_size_um))
        else:
            px_um = 0.05  # 50 nm fallback

        # Build base scan dict from the current single-region definition
        base = _build_scan_dict(self._scan, self._scans_config)

        # Replace scan_regions with one entry per particle.
        # Point counts are derived from pixel_size_nm so every region has the same
        # physical pixel size regardless of its extent.
        scan_regions = {}
        for i, r in enumerate(self._particle_regions):
            xpts = max(10, round(r['xRange'] / px_um))
            ypts = max(10, round(r['yRange'] / px_um))
            # Full-field range with half-pixel inset, same convention as _build_scan_dict /
            # the GUI: step = range/points; pixel centers span (N-1)*step.
            x_step_raw = r['xRange'] / xpts
            y_step_raw = r['yRange'] / ypts
            scan_regions[f'Region{i + 1}'] = {
                'xStart':  r['xCenter'] - r['xRange'] / 2 + x_step_raw / 2,
                'xStop':   r['xCenter'] + r['xRange'] / 2 - x_step_raw / 2,
                'xCenter': r['xCenter'], 'xRange': r['xRange'],
                'xPoints': xpts,         'xStep':  round(x_step_raw, 4),
                'yStart':  r['yCenter'] - r['yRange'] / 2 + y_step_raw / 2,
                'yStop':   r['yCenter'] + r['yRange'] / 2 - y_step_raw / 2,
                'yCenter': r['yCenter'], 'yRange': r['yRange'],
                'yPoints': ypts,         'yStep':  round(y_step_raw, 4),
                'zStart': 0, 'zStop': 0, 'zCenter': 0,
                'zRange': 0, 'zPoints': 1, 'zStep': 0,
            }
        base['scan_regions'] = scan_regions

        n = len(scan_regions)
        try:
            response = self._client.send_message({"command": "scan", "scan": base})
        except Exception as e:
            return f"Failed to start multi-region scan: {e}"

        if response and response.get('status'):
            self._last_was_multiregion = True
            self._was_scanning = True
            return f"Multi-region scan started: {n} particle region(s)."
        data = response.get('data', 'no details') if response else 'no response'
        return f"Multi-region scan failed to start: {data}"

    def get_intelligence_recommendations(self) -> str:
        """Return any pending recommendations from the intelligence module and clear the queue.

        The intelligence module analyses each completed scan and posts structured
        recommendations here, e.g.:
          * recentre suggestions (off-centre feature, focus decline), and
          * 'two_energy_particles' — element-specific particle locations computed from a
            two-energy elemental map (edge/pre-edge).  These are the AUTHORITATIVE particle
            locations for an element-finding request and already give each particle's
            center_um and size_um.  To image them, call load_intelligence_particles() then
            start_multiregion_scan() — do NOT re-derive particles with find_particles(),
            which only thresholds a single transmission image (generic absorbers).

        This tool drains the queue — call it after every wait_for_scan().
        """
        if self._image_model is None:
            return "Image model not available."

        pending = list(self._image_model.get("pending_recommendations") or [])
        self._image_model.set("pending_recommendations", [])

        # Cache the most recent two-energy particle report so it survives the queue clear.
        for rec in pending:
            if rec.get("subtype") == "two_energy_particles" and rec.get("particles"):
                self._last_particle_report = rec["particles"]

        if not pending:
            return "No recommendations pending."

        return json.dumps({"recommendations": pending}, indent=2)

    def load_intelligence_particles(self, region_size_um: float | None = None,
                                    padding_fraction: float = 0.5) -> str:
        """Load the intelligence module's two-energy particle locations as multi-region scan targets.

        Prefer this over find_particles() for element-specific requests (e.g. 'iron particles'):
        the locations come from the two-energy elemental map, whereas find_particles() thresholds
        a single transmission image and finds generic absorbers (often a different count).

        Populates the region list consumed by start_multiregion_scan().  Each region is centred
        on a reported particle; its size is the particle's extent grown by padding_fraction on
        each side (floored at 0.5 µm), unless region_size_um forces a uniform square FOV.

        Args:
            region_size_um:   force a uniform square FOV (µm) per particle; omit to size each
                              region to its particle.
            padding_fraction: fractional margin added to each side of the particle extent
                              when region_size_um is not given (default 0.5 = +50%).
        """
        particles = self._last_particle_report
        if not particles and self._image_model is not None:
            # Fall back to peeking the queue (non-destructively) for the latest report.
            pending = list(self._image_model.get("pending_recommendations") or [])
            for rec in reversed(pending):
                if rec.get("subtype") == "two_energy_particles" and rec.get("particles"):
                    particles = rec["particles"]
                    break
        if not particles:
            return ("No intelligence particle report available. Run a two-energy scan, then "
                    "get_intelligence_recommendations(), before calling this.")

        regions = []
        for p in particles:
            c = p.get("center_um", {})
            s = p.get("size_um", {}) or {}
            if region_size_um is not None:
                rx = ry = float(region_size_um)
            else:
                rx = max(float(s.get("x", 0.0)) * (1.0 + 2.0 * padding_fraction), 0.5)
                ry = max(float(s.get("y", 0.0)) * (1.0 + 2.0 * padding_fraction), 0.5)
            regions.append({
                "xCenter": round(float(c.get("x", 0.0)), 3),
                "yCenter": round(float(c.get("y", 0.0)), 3),
                "xRange": round(rx, 3), "yRange": round(ry, 3),
            })

        self._particle_regions = regions
        self._overview_pixel_size_um = None  # no overview grid here; require explicit pixel size
        return json.dumps({
            "source": "intelligence two_energy_particles",
            "particle_regions_loaded": len(regions),
            "regions": regions,
            "next_step": "Call update_scan(energy_list=[...]) to set the follow-up energy, then "
                         "start_multiregion_scan(pixel_size_nm=...) to image these particles.",
        }, indent=2)

    def get_image_center_of_mass(self, daq: str = "default") -> str:
        """Return the center of mass of the Otsu-thresholded absorption mask.

        Inverts the transmission image so absorbing particles are bright, applies
        an Otsu threshold to produce a binary mask, then computes the unweighted
        centroid of that mask.  This is the same thresholding used by find_particles()
        so the result is consistent with particle detection.

        Returns physical µm coordinates that can be passed directly to
        update_scan(x_center=..., y_center=...) to re-centre the next scan on the feature.

        Args:
            daq: detector channel to use (default 'default').
        """
        from pystxmcontrol.utils.image import image_com, otsu_absorption_mask

        if self._image_model is None:
            return "Image model not available."

        all_images = self._image_model.get('all_detector_images')
        if not isinstance(all_images, dict):
            return "No scan image available — run a scan first."

        image = all_images.get(daq)
        if image is None and daq != 'default':
            image = all_images.get('default')
            daq = 'default'
        if image is None or not isinstance(image, np.ndarray) or image.ndim < 2:
            return f"No valid image data for DAQ '{daq}'."

        x_center = float(self._image_model.get('x_center') or 0.0)
        y_center = float(self._image_model.get('y_center') or 0.0)
        x_range  = float(self._image_model.get('x_range')  or 1.0)
        y_range  = float(self._image_model.get('y_range')  or 1.0)

        result = image_com(image, x_center, y_center, x_range, y_range)
        if result is None:
            return "Otsu threshold produced an empty mask — no absorbing features detected."
        com_x, com_y = result

        masked_pixels = int(otsu_absorption_mask(image).sum())
        return json.dumps({
            "daq": daq,
            "masked_pixels": masked_pixels,
            "center_of_mass_um": {"x": round(com_x, 3), "y": round(com_y, 3)},
            "scan_center_um":    {"x": x_center, "y": y_center},
            "offset_from_scan_center_um": {
                "x": round(com_x - x_center, 3),
                "y": round(com_y - y_center, 3),
            },
            "note": "Pass center_of_mass_um values to update_scan(x_center=..., y_center=...) "
                    "to re-centre the next scan on this feature.",
        }, indent=2)

    def get_last_scan_params(self, scan_type: str | None = None) -> str:
        """Refresh and return the most recently used parameters for a scan type.

        Always fetches fresh data from the server, so it reflects scans run
        after the session started.  Also updates the working scan definition so
        that subsequent update_scan() / start_scan() calls build on the latest state.

        Args:
            scan_type: scan type to retrieve (e.g. 'Image', 'Image Stack').
                       Defaults to the current working scan type if omitted.
        """
        try:
            self._client.get_config()
            self._last_scans = (self._client.main_config or {}).get("lastScan", {})
        except Exception as e:
            return f"Failed to refresh config from server: {e}"

        target_type = scan_type or self._scan.get('scan_type', 'Image')
        server_scan = self._last_scans.get(target_type)
        if not server_scan:
            available = list(self._last_scans.keys())
            return (f"No last scan recorded for type '{target_type}'. "
                    f"Types with recorded scans: {available}")

        if not self._last_was_multiregion:
            try:
                self._scan = ScanModel(**_convert_scan(server_scan)).model_dump()
            except Exception as e:
                log.warning("[ToolSet] get_last_scan_params: _convert_scan failed: %s", e)

        return f"Last '{target_type}' scan parameters:\n" + json.dumps(self._scan, indent=2)

    def read_daq(self, daq: str = "default", dwell: float = 100.0, shutter: bool = True) -> str:
        """Take a single-point DAQ reading without running a scan.

        Useful for checking beam intensity before committing to a full scan.
        """
        try:
            response = self._client.send_message({
                "command": "get_data",
                "daq": daq,
                "dwell": dwell,
                "shutter": shutter,
            })
            value = response.get('data') if response else None
            return f"DAQ reading ({daq}, {dwell} ms): {round(float(value), 4)}" \
                   if value is not None else "No data returned from DAQ"
        except Exception as e:
            return f"DAQ read failed: {e}"

    def get_toolset_debug(self) -> str:
        """Return a diagnostic dump of ToolSet internal state for debugging."""
        last_scan_keys = list((self._last_scans or {}).keys())
        scan_type = self._scan.get('scan_type', 'Image')
        server_scan_keys = list((self._last_scans or {}).get(scan_type, {}).keys()) if self._last_scans else []
        main_cfg = getattr(self._client, 'main_config', None) or {}
        return json.dumps({
            "last_scans_keys": last_scan_keys,
            "current_scan_type": scan_type,
            "server_scan_top_keys": server_scan_keys,
            "main_config_top_keys": list(main_cfg.keys()),
            "client_has_main_config": hasattr(self._client, 'main_config') and self._client.main_config is not None,
            "current_scan_summary": {
                k: self._scan.get(k)
                for k in ('scan_type', 'x_range', 'y_range', 'x_points', 'y_points',
                          'dwell', 'energy_start', 'proposal')
            },
        }, indent=2)

    # ------------------------------------------------------------------
    # Beamline tuning
    # ------------------------------------------------------------------

    def _motor_pos(self, axis: str) -> float | None:
        """Return a fresh float position for *axis*, refreshing config if needed."""
        pos = (self._positions or {}).get(axis)
        if pos is None:
            self.get_config()
            pos = (self._positions or {}).get(axis)
        try:
            return float(pos) if pos is not None else None
        except (TypeError, ValueError):
            return None

    def _beam_quality_window(self, daq: str, settle_lines: int) -> dict | None:
        """Measure beam quality over the most recently filled scan lines.

        Waits until *settle_lines* new rows fill (so the result reflects the latest
        parameter value), the instrument goes idle, or a timeout, then computes
        intensity (mean), noise RMS (std) and SNR (mean/std) over the trailing window.
        Returns None if no image data is available yet.
        """
        def _get_arr():
            if self._image_model is None:
                return None
            all_images = self._image_model.get('all_detector_images')
            if not isinstance(all_images, dict):
                return None
            img = all_images.get(daq)
            if img is None and daq != 'default':
                img = all_images.get('default')
            if not isinstance(img, np.ndarray) or img.ndim < 2:
                return None
            arr = np.asarray(img, dtype=float)
            return arr if arr.ndim == 2 else arr.reshape(arr.shape[0], -1)

        def _filled_rows(arr):
            return np.where(np.any(arr != 0.0, axis=1))[0]

        arr = _get_arr()
        if arr is None:
            return None

        start_filled = int(len(_filled_rows(arr)))
        nx = arr.shape[1]
        dwell_ms = float(self._scan.get('dwell', 1.0) or 1.0)
        # Generous ceiling: time to acquire settle_lines rows, ×3, floored at 5 s.
        timeout = max(5.0, (dwell_ms / 1000.0) * nx * settle_lines * 3.0)
        deadline = time.monotonic() + timeout
        scan_idle = False

        while time.monotonic() < deadline:
            arr = _get_arr()
            if arr is None:
                break
            if int(len(_filled_rows(arr))) >= start_filled + settle_lines:
                break
            try:
                status = self._client.get_status()
                if status and status.get('mode') == 'idle':
                    scan_idle = True
                    break
            except Exception:
                pass
            time.sleep(0.3)

        arr = _get_arr()
        if arr is None:
            return None
        rows = _filled_rows(arr)
        if len(rows) == 0:
            return None
        window = arr[rows[-settle_lines:], :]
        intensity = float(np.mean(window))
        noise_rms = float(np.std(window))
        snr = round(intensity / noise_rms, 4) if noise_rms > 1e-12 else 0.0
        return {
            "intensity": round(intensity, 4),
            "noise_rms": round(noise_rms, 4),
            "snr": snr,
            "n_filled_rows": int(len(rows)),
            "lines_measured": int(min(settle_lines, len(rows))),
            "scan_complete": bool(scan_idle),
        }

    def start_tuning_session(self, energy: float | None = None) -> str:
        """Begin a beamline-tuning session: anchor origins and pick step sizes.

        Reads the undulator harmonic to choose the EPU gap step, records the current
        EPU Gap / FBKOFFSET / EPUOFFSET as search origins, and reports the SampleX/Y
        position to centre the tuning scan on.  Call this first, then configure and
        start the tuning scan, then run the search with read_beam_quality() /
        step_tuning_parameter().
        """
        self.get_config()
        if energy is not None:
            move_res = self.move_motor("Energy", float(energy))
            if not move_res.startswith("Successfully"):
                return f"Could not move Energy to {energy}: {move_res}"
            self.get_config()

        positions = self._positions or {}

        # Harmonic: prefer the live motor reading, fall back to the beamline DB.
        harmonic = None
        h_raw = positions.get("HARMONIC")
        if h_raw is not None:
            try:
                harmonic = int(round(float(h_raw)))
            except (TypeError, ValueError):
                harmonic = None
        if harmonic is None and energy is not None:
            try:
                from pystxmcontrol.controller.beamline_database import BeamlineDatabaseClient
                # Access the server-side DB over the network (no local filesystem needed).
                energies = BeamlineDatabaseClient(self._client).get_desired_energies()
                if energies:
                    nearest = min(energies, key=lambda e: abs(e - float(energy)))
                    entry = BeamlineDatabaseClient(self._client).get_entry(nearest)
                    if entry and entry.get("harmonic") is not None:
                        harmonic = int(entry["harmonic"])
            except Exception as e:
                log.warning("[ToolSet] beamline DB harmonic lookup failed: %s", e)
        if harmonic is None:
            harmonic = 1

        gap_step = _GAP_STEP_BY_HARMONIC.get(harmonic)
        if gap_step is None:
            # Nearest known odd harmonic, else first-harmonic default.
            known = min(_GAP_STEP_BY_HARMONIC, key=lambda h: abs(h - harmonic))
            gap_step = _GAP_STEP_BY_HARMONIC[known]

        gap0 = self._motor_pos("EPU Gap")
        fbk0 = self._motor_pos("FBKOFFSET")
        off0 = self._motor_pos("EPUOFFSET")
        if gap0 is None or fbk0 is None or off0 is None:
            return ("Cannot start tuning — could not read EPU Gap / FBKOFFSET / EPUOFFSET "
                    "positions. Call get_config() and check the motor names.")

        sample_x = self._motor_pos("SampleX")
        sample_y = self._motor_pos("SampleY")

        self._tuning = {
            "energy": energy,
            "harmonic": harmonic,
            "gap_step": gap_step,
            "feedback_step": _FEEDBACK_STEP,
            "max_steps": _TUNING_MAX_STEPS,
            # "_start" = immutable position at session start (used by finalize_tuning for
            # the EPU-offset delta). "_origin" = the ±max_steps limit anchor, which can be
            # re-anchored between search phases via reanchor_tuning_limit().
            "gap_start": gap0, "gap_origin": gap0, "gap_cur": gap0,
            "feedback_start": fbk0, "feedback_origin": fbk0, "feedback_cur": fbk0,
            "offset_origin": off0,
        }

        return json.dumps({
            "status": "tuning session started",
            "energy_eV": energy,
            "harmonic": harmonic,
            "gap_step_mm": gap_step,
            "feedback_step": _FEEDBACK_STEP,
            "max_steps_each_direction": _TUNING_MAX_STEPS,
            "gap_travel_limit_mm": round(gap_step * _TUNING_MAX_STEPS, 4),
            "feedback_travel_limit": round(_FEEDBACK_STEP * _TUNING_MAX_STEPS, 4),
            "origins": {"EPU Gap": gap0, "FBKOFFSET": fbk0, "EPUOFFSET": off0},
            "sample_center_um": {"x": sample_x, "y": sample_y},
            "next_step": (
                "Configure the tuning scan centred on SampleX/Y with a small range, then "
                "start it (do not wait_for_scan): "
                f"update_scan(scan_type='Image', x_center={sample_x}, y_center={sample_y}, "
                "x_range=5, y_range=5, x_points=400, y_points=400, dwell=1.0), "
                "check_scan_limits(), start_scan(). Then run the search: read_beam_quality() "
                "for a baseline, step_tuning_parameter('gap', ±1) and re-measure, maximizing "
                "SNR. Optimize 'gap' first, then 'feedback'. Finish with finalize_tuning()."
            ),
        }, indent=2)

    def read_beam_quality(self, daq: str = "default", settle_lines: int = 5) -> str:
        """Measure live beam intensity, noise RMS, and SNR from the running tuning scan.

        Reads the most recently filled scan lines so the result reflects the current
        beamline-parameter values.  SNR = intensity / noise_RMS is the composite tuning
        objective — compare it across calls to judge whether a step helped or hurt.
        Returns scan_complete=true if the scan has finished (ask the user whether to
        start another scan to continue the search).
        """
        result = self._beam_quality_window(daq, max(1, int(settle_lines)))
        if result is None:
            return ("No live scan image yet — start the tuning scan first, or wait for the "
                    "first lines to acquire.")
        if self._tuning is not None:
            result["positions"] = {
                "EPU Gap": round(self._tuning["gap_cur"], 4),
                "FBKOFFSET": round(self._tuning["feedback_cur"], 4),
                "EPUOFFSET": round(self._tuning["offset_origin"], 4),
            }
        return json.dumps(result, indent=2)

    def step_tuning_parameter(self, parameter: str, n_steps: float) -> str:
        """Step a tuning parameter by n_steps × its step size (sign sets direction).

        parameter is 'gap' (EPU Gap) or 'feedback' (FBKOFFSET).  Movement is bounded to
        ±max_steps steps from the search origin; a step that would exceed the limit is
        refused.  Sleeps for the slow-motor beam settle time before returning, so the
        next read_beam_quality() reflects the new beam.
        """
        if self._tuning is None:
            return "No active tuning session — call start_tuning_session() first."
        if parameter not in _TUNING_MOTORS:
            return f"Unknown parameter '{parameter}'. Use 'gap' or 'feedback'."

        axis = _TUNING_MOTORS[parameter]
        step = self._tuning["gap_step"] if parameter == "gap" else self._tuning["feedback_step"]
        origin = self._tuning[f"{parameter}_origin"]
        cur = self._tuning[f"{parameter}_cur"]
        max_steps = self._tuning["max_steps"]

        target = cur + float(n_steps) * step
        # Bound to ±max_steps from origin (tiny epsilon for float rounding).
        limit = max_steps * step
        if abs(target - origin) > limit + 1e-9:
            return json.dumps({
                "status": "refused",
                "reason": (f"Step would move {axis} to {round(target, 4)}, "
                           f"{round((target - origin) / step, 2)} steps from origin — "
                           f"exceeds the ±{max_steps}-step limit "
                           f"(±{round(limit, 4)} from {round(origin, 4)})."),
                "parameter": parameter,
                "current": round(cur, 4),
                "steps_from_origin": round((cur - origin) / step, 2),
            }, indent=2)

        move_res = self.move_motor(axis, target)
        if not move_res.startswith("Successfully"):
            return f"Failed to step {parameter} ({axis}): {move_res}"

        self._tuning[f"{parameter}_cur"] = target
        time.sleep(_TUNING_SETTLE_SECONDS)

        return json.dumps({
            "status": "stepped",
            "parameter": parameter,
            "axis": axis,
            "position": round(target, 4),
            "steps_from_origin": round((target - origin) / step, 2),
            "step_size": step,
            "note": f"Beam settled {_TUNING_SETTLE_SECONDS:.0f} s. "
                    "Call read_beam_quality() to measure.",
        }, indent=2)

    def reanchor_tuning_limit(self, parameter: str) -> str:
        """Re-centre a parameter's ±max_steps travel limit on its current position.

        Use this between search phases on the same parameter (e.g. after the intensity
        search on 'gap', before the SNR search on 'gap') so the second phase gets a full
        ±max_steps window around the first phase's optimum. This moves only the limit
        anchor; the session start position used by finalize_tuning() is unchanged, so the
        EPU-offset correction still reflects the total gap change from the original gap.
        """
        if self._tuning is None:
            return "No active tuning session — call start_tuning_session() first."
        if parameter not in _TUNING_MOTORS:
            return f"Unknown parameter '{parameter}'. Use 'gap' or 'feedback'."

        cur = self._tuning[f"{parameter}_cur"]
        self._tuning[f"{parameter}_origin"] = cur
        step = self._tuning["gap_step"] if parameter == "gap" else self._tuning["feedback_step"]
        limit = self._tuning["max_steps"] * step
        return json.dumps({
            "status": "limit re-anchored",
            "parameter": parameter,
            "new_anchor": round(cur, 4),
            "new_window": [round(cur - limit, 4), round(cur + limit, 4)],
            "note": "Travel limit re-centred here; the finalize offset still uses the "
                    "original session position.",
        }, indent=2)

    def finalize_tuning(self) -> str:
        """Finish tuning: set EPUOFFSET by the EPU-gap delta and report the optimum.

        Computes new EPUOFFSET = origin EPUOFFSET + (current EPU Gap − origin EPU Gap),
        clamps it to the motor limits, and applies it.  EPU Gap and FBKOFFSET are left at
        their optimised positions (FBKOFFSET is the live feedback control).
        """
        if self._tuning is None:
            return "No active tuning session — nothing to finalize."

        t = self._tuning
        # Delta from the ORIGINAL session gap (not the re-anchored limit origin).
        gap_delta = t["gap_cur"] - t["gap_start"]
        new_offset = t["offset_origin"] + gap_delta

        # Clamp to EPUOFFSET limits from the motor config.
        clamped = False
        info = (self._motors or {}).get("EPUOFFSET", {})
        if "minValue" in info and "maxValue" in info:
            lo, hi = float(info["minValue"]), float(info["maxValue"])
            if new_offset < lo:
                new_offset, clamped = lo, True
            elif new_offset > hi:
                new_offset, clamped = hi, True

        move_res = self.move_motor("EPUOFFSET", round(new_offset, 4))
        if not move_res.startswith("Successfully"):
            return f"Failed to set EPUOFFSET to {round(new_offset, 4)}: {move_res}"

        summary = {
            "status": "tuning complete",
            "energy_eV": t["energy"],
            "harmonic": t["harmonic"],
            "epu_gap": {"origin": round(t["gap_start"], 4),
                        "optimum": round(t["gap_cur"], 4),
                        "delta": round(gap_delta, 4)},
            "feedback_offset": {"origin": round(t["feedback_start"], 4),
                                "optimum": round(t["feedback_cur"], 4)},
            "epu_offset": {"origin": round(t["offset_origin"], 4),
                           "applied": round(new_offset, 4),
                           "clamped_to_limit": clamped},
        }
        self._tuning = None
        return json.dumps(summary, indent=2)

    def save_beamline_entry(self, desired_energy: float,
                            populate_from_current: bool = False,
                            commanded_energy: float | None = None,
                            harmonic: int | None = None,
                            grating: str | None = None,
                            exit_slit_h_pos: float | None = None,
                            exit_slit_size: float | None = None,
                            m121_vertical_angle: float | None = None,
                            feedback_offset: float | None = None,
                            m101_angle: float | None = None,
                            epu_offset: float | None = None,
                            notes: str | None = None,
                            modified_by: str = "task_agent") -> str:
        """Insert or update a beamline-parameter database entry for *desired_energy*.

        Writes to the server-side beamline DB over the network. Only the fields you pass
        are written; an existing entry keeps its other fields. When populate_from_current
        is True, the commanded_energy / harmonic / feedback_offset / epu_offset fields are
        filled from the current motor positions for any you did not pass explicitly — ideal
        right after tuning, when the live positions already hold the tuned result.
        """
        from pystxmcontrol.controller.beamline_database import (
            BeamlineDatabaseClient, COLUMNS,
        )

        try:
            desired_energy = float(desired_energy)
        except (TypeError, ValueError):
            return f"Invalid desired_energy {desired_energy!r} — must be a number."

        fields = {
            "commanded_energy":    commanded_energy,
            "harmonic":            harmonic,
            "grating":             grating,
            "exit_slit_h_pos":     exit_slit_h_pos,
            "exit_slit_size":      exit_slit_size,
            "m121_vertical_angle": m121_vertical_angle,
            "feedback_offset":     feedback_offset,
            "m101_angle":          m101_angle,
            "epu_offset":          epu_offset,
        }
        if notes is not None:
            fields["notes"] = notes

        if populate_from_current:
            self.get_config()
            positions = self._positions or {}
            for col, axis in _BEAMLINE_DB_MOTOR_MAP.items():
                if fields.get(col) is None and positions.get(axis) is not None:
                    fields[col] = positions[axis]

        # Drop unset fields and coerce to the column dtype where known.
        dtype_map = {c: d for c, _label, d in COLUMNS}
        clean: dict = {}
        for key, val in fields.items():
            if val is None:
                continue
            dt = dtype_map.get(key)
            try:
                clean[key] = int(float(val)) if dt is int else (dt(val) if dt else val)
            except (TypeError, ValueError):
                clean[key] = val

        if not clean:
            return ("Nothing to save — pass at least one field, or "
                    "populate_from_current=True to capture the current beamline state.")

        try:
            db = BeamlineDatabaseClient(self._client)
            existed = db.get_entry(desired_energy) is not None
            db.upsert_entry(desired_energy, modified_by=modified_by, **clean)
        except Exception as e:
            return f"Failed to save beamline entry for {desired_energy} eV: {e}"

        return json.dumps({
            "status": "updated" if existed else "added",
            "desired_energy_eV": desired_energy,
            "fields_written": clean,
            "modified_by": modified_by,
        }, indent=2)

    def set_beamline_from_database(self, desired_energy: float) -> str:
        """Set the beamline from a stored database entry for *desired_energy*.

        Looks up the (exact) entry, applies its calibration knobs — harmonic, EPU offset,
        feedback offset — to the corresponding motors, then moves Energy to the entry's
        desired_energy (the desired→commanded mapping is handled at a lower level, so the
        high-level target is always the desired energy). Columns without a clean motor
        mapping (grating, exit slits, m121/m101 angles) are reported, not moved.
        Moving Energy can be a large move — confirm with the user first per the safety rules.
        """
        from pystxmcontrol.controller.beamline_database import (
            BeamlineDatabaseClient, COLUMN_NAMES,
        )

        try:
            desired_energy = float(desired_energy)
        except (TypeError, ValueError):
            return f"Invalid desired_energy {desired_energy!r} — must be a number."

        db = BeamlineDatabaseClient(self._client)
        try:
            entry = db.get_entry(desired_energy)
        except Exception as e:
            return f"Failed to read beamline database: {e}"

        if entry is None:
            try:
                energies = db.get_desired_energies()
            except Exception:
                energies = []
            return json.dumps({
                "status": "not_found",
                "desired_energy_eV": desired_energy,
                "available_energies": energies,
                "message": ("No entry for this energy. Pass an energy that exists, or create "
                            "one with save_beamline_entry()."),
            }, indent=2)

        # Apply the calibration knobs first (so the harmonic/offset are in place before the
        # Energy move drives the EPU gap), then move Energy to the desired energy.
        knob_map = [("harmonic", "HARMONIC"),
                    ("epu_offset", "EPUOFFSET"),
                    ("feedback_offset", "FBKOFFSET")]
        moves, skipped, errors = [], [], []
        for col, axis in knob_map:
            val = entry.get(col)
            if val is None:
                skipped.append(col)
                continue
            res = self.move_motor(axis, float(val))
            if res.startswith("Successfully"):
                moves.append({"motor": axis, "value": float(val)})
            else:
                errors.append(f"{axis}: {res}")

        e_res = self.move_motor("Energy", desired_energy)
        if e_res.startswith("Successfully"):
            moves.append({"motor": "Energy", "value": desired_energy})
        else:
            errors.append(f"Energy: {e_res}")

        # Columns that have a stored value but no motor mapping — the operator sets these by hand.
        _handled = {"desired_energy", "commanded_energy", "harmonic", "epu_offset",
                    "feedback_offset"}
        not_applied = {
            col: entry[col]
            for col in COLUMN_NAMES
            if col not in _handled and entry.get(col) is not None
        }

        result = {
            "status": "applied" if not errors else "partial",
            "desired_energy_eV": desired_energy,
            "moves": moves,
            "skipped_empty_fields": skipped,
        }
        if not_applied:
            result["set_manually"] = not_applied  # no motor mapping — for operator awareness
        if errors:
            result["errors"] = errors
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # OSA alignment
    # ------------------------------------------------------------------

    def configure_osa_scan(self, extent_um: float, points: int,
                           velocity_mm_s: float | None = None,
                           x_center: float | None = None,
                           y_center: float | None = None) -> str:
        """Configure an 'OSA Image' scan for alignment, deriving dwell from stage velocity.

        Sets up a square OSA_X/OSA_Y scan centred on the current OSA position (or the
        passed center) and computes the per-pixel dwell so the stage moves at the target
        velocity: dwell_ms = step_um / velocity_mm_s, step_um = extent_um / (points - 1).
        OSA motors are finicky — too fast or too slow distorts the image — so the dwell is
        derived here rather than guessed. Velocity defaults to main.json scan.osa_velocity_mm_s
        (fallback 0.25 mm/s). Energy is left unchanged. Call check_scan_limits() then
        start_scan() next; do not change the dwell afterwards.

        Args:
            extent_um: square scan range in µm (e.g. ~500 large, ~60 small).
            points:    points per axis (e.g. 50 large, 30 small).
            velocity_mm_s: override the configured target stage velocity.
            x_center, y_center: scan center in OSA µm; default to the current OSA position
                (use the large-scan beam center here for the follow-up small scan).
        """
        if self._motors is None or self._positions is None:
            self.get_config()
        try:
            extent_um = float(extent_um)
            points = int(points)
        except (TypeError, ValueError):
            return f"Invalid extent_um/points: {extent_um!r}, {points!r}"
        if extent_um <= 0 or points < 2:
            return "extent_um must be > 0 and points must be >= 2."

        if velocity_mm_s is None:
            main_cfg = getattr(self._client, 'main_config', None) or {}
            velocity_mm_s = (main_cfg.get('scan', {}) or {}).get(
                'osa_velocity_mm_s', _OSA_DEFAULT_VELOCITY_MM_S)
        velocity_mm_s = float(velocity_mm_s)
        if velocity_mm_s <= 0:
            return f"velocity_mm_s must be > 0 (got {velocity_mm_s})."

        if x_center is None:
            x_center = self._motor_pos(_OSA_X_MOTOR)
        if y_center is None:
            y_center = self._motor_pos(_OSA_Y_MOTOR)
        if x_center is None or y_center is None:
            return ("Could not read current OSA position for the scan center — "
                    "pass x_center and y_center explicitly.")

        step_um = extent_um / (points - 1)
        # 1 mm/s == 1 µm/ms, so step_um (µm) / velocity_mm_s (µm/ms) = dwell in ms.
        dwell_ms = round(step_um / velocity_mm_s, 4)

        warning = None
        if not (_OSA_DWELL_MIN_MS <= dwell_ms <= _OSA_DWELL_MAX_MS):
            warning = (f"Computed dwell {dwell_ms} ms is outside the expected "
                       f"[{_OSA_DWELL_MIN_MS}, {_OSA_DWELL_MAX_MS}] ms band — check "
                       f"extent/points/velocity before starting.")

        upd = self.update_scan(
            scan_type='OSA Image', x_motor=_OSA_X_MOTOR, y_motor=_OSA_Y_MOTOR,
            x_center=round(float(x_center), 3), y_center=round(float(y_center), 3),
            x_range=extent_um, y_range=extent_um,
            x_points=points, y_points=points, dwell=dwell_ms,
        )
        if upd.startswith("Invalid") or upd.startswith("Unknown") or upd.startswith("Failed"):
            return f"OSA scan configuration failed: {upd}"

        result = {
            "status": "OSA scan configured",
            "scan_type": "OSA Image",
            "center_um": {"x": round(float(x_center), 3), "y": round(float(y_center), 3)},
            "extent_um": extent_um,
            "points": points,
            "step_um": round(step_um, 4),
            "velocity_mm_s": velocity_mm_s,
            "dwell_ms": dwell_ms,
            "next_step": "Call check_scan_limits(), then start_scan(), then wait_for_scan().",
        }
        if warning:
            result["warning"] = warning
        return json.dumps(result, indent=2)

    def get_osa_beam_center(self, daq: str = "default", mode: str = "small") -> str:
        """Find the OSA beam center from the last scan image.

        The OSA beam is BRIGHT on a near-dark field. Two regimes:
        * mode='large': focused central spot inside a concentric annulus of unfocused
          zero-order light → the intensity-weighted centroid sum(I*x)/sum(I) gives the center
          (the annulus is concentric, so it does not bias the centroid).
        * mode='small': mainly the blurred central spot, but if the OSA is not yet centered
          some unfocused light leaks in — often bright in one CORNER — which pulls the plain
          centroid off. So small mode isolates the compact focused peak by curvature with a
          Laplacian-of-Gaussian (see _focused_peak_center), and only falls back to the centroid
          if no peak is found. The result reports the method used and a 'prominence' confidence.

        Returns the center in OSA_X/OSA_Y µm and caches it for zero_osa_position(). For a large
        scan, pass beam_center_um to configure_osa_scan() for the small follow-up; after the
        small scan, confirm with the user and call zero_osa_position().

        Args:
            daq:  detector channel to analyse (default 'default').
            mode: 'large' (centroid) or 'small' (DoG focused-peak, centroid fallback).
        """
        if self._image_model is None:
            return "Image model not available."

        all_images = self._image_model.get('all_detector_images')
        if not isinstance(all_images, dict):
            return "No scan image available — run an OSA scan first."

        image = all_images.get(daq)
        if image is None and daq != 'default':
            image = all_images.get('default')
            daq = 'default'
        if image is None or not isinstance(image, np.ndarray) or image.ndim < 2:
            return f"No valid image data for DAQ '{daq}'."

        ny, nx = image.shape[:2]
        flat = np.asarray(image, dtype=float)
        if flat.ndim > 2:
            flat = flat.reshape(ny, nx)
        # Clip any negative values so they can't pull the centroid the wrong way.
        weights = np.clip(flat, 0.0, None)
        total = float(weights.sum())
        if total <= 0:
            return "Image has no positive signal — cannot locate the beam (check exposure/shutter)."

        x_center = float(self._image_model.get('x_center') or 0.0)
        y_center = float(self._image_model.get('y_center') or 0.0)
        x_range  = float(self._image_model.get('x_range')  or 1.0)
        y_range  = float(self._image_model.get('y_range')  or 1.0)

        cols = np.arange(nx)
        rows = np.arange(ny)
        com_col = float((weights.sum(axis=0) * cols).sum() / total)
        com_row = float((weights.sum(axis=1) * rows).sum() / total)

        def px_to_um(col, row):
            x = x_center + (col / max(nx - 1, 1) - 0.5) * x_range
            y = y_center + (row / max(ny - 1, 1) - 0.5) * y_range
            return round(x, 3), round(y, 3)

        # Choose the center estimate. Small mode uses the curvature-based focused-peak finder
        # to reject off-centre unfocused light; large mode (and the small-mode fallback) uses
        # the plain intensity centroid.
        method = "centroid"
        dog_info = None
        col_c, row_c = com_col, com_row
        if mode == "small":
            peak = _focused_peak_center(flat)
            if peak is not None:
                col_c, row_c = peak["col_c"], peak["row_c"]
                method = "log_focused_peak"
                dog_info = {k: peak[k] for k in ("sigma_px", "border_margin_px", "prominence")}

        beam_x, beam_y = px_to_um(col_c, row_c)
        com_x, com_y = px_to_um(com_col, com_row)

        # Brightest pixel as a sanity check.
        peak_row, peak_col = np.unravel_index(np.argmax(weights), weights.shape)
        peak_x, peak_y = px_to_um(float(peak_col), float(peak_row))

        self._osa_beam_center = {"x": beam_x, "y": beam_y, "daq": daq, "mode": mode}

        result = {
            "daq": daq,
            "mode": mode,
            "method": method,
            "image_shape_px": [ny, nx],
            "scan_center_um": {"x": x_center, "y": y_center},
            "beam_center_um": {"x": beam_x, "y": beam_y},
            "centroid_um": {"x": com_x, "y": com_y},   # plain intensity COM, for comparison
            "brightest_pixel_um": {"x": peak_x, "y": peak_y},
            "offset_from_scan_center_um": {"x": round(beam_x - x_center, 3),
                                           "y": round(beam_y - y_center, 3)},
            "next_step": ("For a large scan, pass beam_center_um to configure_osa_scan() for "
                          "a small follow-up scan. For the final small scan, confirm with the "
                          "user, then call zero_osa_position() to set this position as the new OSA zero."),
        }
        if dog_info is not None:
            result["focused_peak"] = dog_info
            result["note"] = ("Small mode: center is the curvature-isolated focused peak. "
                              "Compare beam_center_um vs centroid_um — a large gap means "
                              "unfocused light was skewing the plain centroid. Low 'prominence' "
                              "means low confidence; recentre with a larger scan first.")
        return json.dumps(result, indent=2)

    def zero_osa_position(self) -> str:
        """Set the last-found OSA beam center as the new OSA zero (mirrors the GUI 'Set to 0').

        For OSA_X and OSA_Y, adjusts the motor config offset so the beam-center position
        found by get_osa_beam_center() reads as 0: new_offset = current_offset - beam_center.
        This does NOT move any motor — it relabels the coordinate origin, exactly like the
        GUI button. ALWAYS confirm with the user before calling this (it changes the stored
        OSA calibration). Requires a prior get_osa_beam_center() call.
        """
        if not self._osa_beam_center:
            return ("No OSA beam center available — run an OSA scan and call "
                    "get_osa_beam_center() first.")
        if self._motors is None:
            self.get_config()

        found = self._osa_beam_center
        applied = []
        for axis, key in ((_OSA_X_MOTOR, "x"), (_OSA_Y_MOTOR, "y")):
            info = (self._motors or {}).get(axis, {})
            if "offset" not in info:
                return f"No 'offset' field for {axis} in motor config — cannot zero."
            cur_offset = float(info["offset"])
            found_val = float(found[key])
            new_offset = round(cur_offset - found_val, 4)
            try:
                self._client.change_motor_config(axis, "offset", new_offset)
            except Exception as e:
                return f"Failed to set {axis} offset to {new_offset}: {e}"
            applied.append({"axis": axis, "beam_center_um": round(found_val, 3),
                            "old_offset": round(cur_offset, 4), "new_offset": new_offset})

        # change_motor_config refreshes the server config; re-cache it.
        self._motors    = getattr(self._client, 'motorInfo', None) or self._motors
        self._positions = getattr(self._client, 'currentMotorPositions', None) or self._positions
        self._osa_beam_center = None

        return json.dumps({
            "status": "OSA zeroed",
            "applied": applied,
            "note": "OSA_X/OSA_Y offsets updated so the beam center now reads as 0. No motors moved.",
        }, indent=2)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None)
        if fn is None:
            return f"Unknown tool: '{name}'"
        try:
            return fn(**args)
        except TypeError as e:
            return f"Bad arguments for tool '{name}': {e}"


# ---------------------------------------------------------------------------
# OpenAI-format tool schemas
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_safety_instructions",
            "description": "Return the safety rules and recommended workflows for operating this instrument. Call this first.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_config",
            "description": "Fetch current motor list, scan type configurations, and motor positions from the server.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_motor_position",
            "description": "Return the current position of a named motor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "axis": {"type": "string", "description": "Motor name, e.g. 'SampleX'"},
                },
                "required": ["axis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_motor",
            "description": "Move a named motor to the given position. Respects software limits on the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "axis": {"type": "string", "description": "Motor name"},
                    "pos":  {"type": "number", "description": "Target position in µm (or degrees for rotation)"},
                },
                "required": ["axis", "pos"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_scan",
            "description": (
                "Update the pending scan definition. Call without arguments to inspect the current config. "
                "Pass any subset of scan parameters to change them. "
                "Available scan_type values depend on the instrument configuration — check get_config(). "
                "Use the exact strings returned there; colloquial terms like 'stack', 'z-stack', or 'tomo' are not valid."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scan_type":          {"type": "string"},
                    "x_motor":            {"type": "string"},
                    "y_motor":            {"type": "string"},
                    "x_center":           {"type": "number", "description": "µm"},
                    "y_center":           {"type": "number", "description": "µm"},
                    "x_range":            {"type": "number", "description": "µm"},
                    "y_range":            {"type": "number", "description": "µm"},
                    "x_points":           {"type": "integer"},
                    "y_points":           {"type": "integer"},
                    "dwell":              {"type": "number", "description": "ms per pixel"},
                    "energy_start":       {"type": "number", "description": "eV"},
                    "energy_stop":        {"type": "number", "description": "eV"},
                    "energy_points":      {"type": "integer"},
                    "energy_list":        {"type": "array", "items": {"type": "number"}, "description": "Explicit energy list in eV"},
                    "autofocus":          {"type": "boolean"},
                    "spiral":             {"type": "boolean"},
                    "tiled":              {"type": "boolean", "description": "Large-scan mode: split into sub-regions that each fit the fine/piezo range (server stitches). Use when a range exceeds fine travel."},
                    "coarse_only":        {"type": "boolean", "description": "Large-scan mode: position with the coarse stage instead of the fine piezo. Use when a range exceeds fine travel."},
                    "sample_description": {"type": "string"},
                    "comment":            {"type": "string"},
                    "proposal":           {"type": "string"},
                    "experimenters":      {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_scan_limits",
            "description": (
                "Validate the current scan geometry against motor (fine/piezo) travel limits — "
                "the same check the GUI runs before starting a scan. If a range exceeds the fine "
                "travel and no large-scan mode is set, the result has needs_decision=True with "
                "'tiled' vs 'coarse_only' options: ask the user which to use, set it via "
                "update_scan(tiled=True) or update_scan(coarse_only=True), then start_scan(). "
                "start_scan() runs this automatically and refuses if unresolved."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_scan",
            "description": "Submit the current scan definition and start acquisition. Runs check_scan_limits() first and refuses if a range exceeds fine travel with no tiled/coarse_only mode set. Returns when the server acknowledges the start.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scan_status",
            "description": "Check whether a scan is currently running or the instrument is idle.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_for_scan",
            "description": (
                "Block until the running scan finishes and return a completion message. "
                "Preferred over polling get_scan_status() in a loop — call this once after "
                "start_scan() so the scan wait consumes only one agent iteration. "
                "Uses the server's live time_remaining estimate automatically; "
                "pass timeout_seconds only to override."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Maximum seconds to wait. Omit to use the server's time estimate.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_toolset_debug",
            "description": "Return a diagnostic dump of ToolSet internal state. Use when scan parameters look wrong.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_last_scan_stats",
            "description": (
                "Return statistical analysis of the most recently completed scan image: "
                "mean, std, contrast, and the physical coordinates (µm) of the darkest region. "
                "Use this after get_scan_status() returns idle to decide whether features "
                "were found and where to zoom in next."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "daq": {
                        "type": "string",
                        "default": "default",
                        "description": "DAQ channel to analyse (e.g. 'default', 'xrf', 'tey'). "
                                       "Falls back to 'default' if the requested channel is absent.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_intelligence_recommendations",
            "description": (
                "Return and clear pending recommendations from the intelligence module. "
                "Includes recentre suggestions AND 'two_energy_particles' reports — the "
                "AUTHORITATIVE element-specific particle locations from a two-energy elemental "
                "map (each with center_um and size_um). For an element-finding request, act on "
                "this: call load_intelligence_particles() then start_multiregion_scan(); do NOT "
                "re-derive counts with find_particles(). Call after every wait_for_scan()."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_intelligence_particles",
            "description": (
                "Load the intelligence module's two-energy particle locations (from "
                "get_intelligence_recommendations / the elemental map) as multi-region scan "
                "targets, then call start_multiregion_scan() to image them. PREFER this over "
                "find_particles() for element-specific requests (e.g. iron): it uses the "
                "edge/pre-edge map, not a single-image threshold. Each region is centred on a "
                "reported particle and sized to it (plus margin) unless region_size_um is given."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region_size_um": {
                        "type": "number",
                        "description": "Force a uniform square FOV (µm) per particle. "
                                       "Omit to size each region to its particle extent.",
                    },
                    "padding_fraction": {
                        "type": "number",
                        "description": "Margin added per side of the particle extent when "
                                       "region_size_um is omitted (default 0.5 = +50%).",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_image_center_of_mass",
            "description": (
                "Compute the centroid of the Otsu-thresholded absorption mask of the last scan image. "
                "Uses the same Otsu inversion used by find_particles(), so the result is consistent "
                "with particle detection. "
                "Returns physical µm coordinates — pass them to update_scan(x_center=..., y_center=...) "
                "to re-centre the next scan on the feature."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "daq": {
                        "type": "string",
                        "description": "DAQ channel to use (default 'default').",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_last_scan_params",
            "description": (
                "Fetch the most recently used scan parameters from the server for a given scan type. "
                "Always queries the server for fresh data — use this whenever the user asks about "
                "a recent scan, or before modifying parameters from the last scan. "
                "Also updates the working scan definition so update_scan() builds on the latest state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scan_type": {
                        "type": "string",
                        "description": "Scan type to retrieve (e.g. 'Image', 'Image Stack'). "
                                       "Omit to use the current working scan type.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_daq",
            "description": "Take a single-point intensity reading without running a full scan. Useful for checking beam before starting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "daq":     {"type": "string", "default": "default", "description": "DAQ channel name"},
                    "dwell":   {"type": "number", "default": 100.0, "description": "Integration time in ms"},
                    "shutter": {"type": "boolean", "default": True, "description": "Open shutter during measurement"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_particles",
            "description": (
                "Locate GENERIC absorbing particles in a SINGLE transmission image using Otsu "
                "thresholding + connected components (NOT element-specific). "
                "Returns scan regions (center, range, points) in µm per particle. Use for a plain "
                "'find absorbing features' request. For an element (e.g. iron) after a two-energy "
                "scan, use load_intelligence_particles() instead. "
                "Then call start_multiregion_scan() to image all particles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_particles": {
                        "type": "integer",
                        "description": "Cap on number of regions returned, ordered by size (default: all).",
                    },
                    "daq": {
                        "type": "string",
                        "default": "default",
                        "description": "Detector channel to analyse.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_multiregion_scan",
            "description": (
                "Start an image scan covering every loaded particle region (from "
                "load_intelligence_particles() or find_particles(), whichever you called last). "
                "Uses the current scan parameters (energy, dwell, proposal, etc.) with particle regions as geometry. "
                "Each region's point count is computed from pixel_size_nm so all regions have uniform pixel size. "
                "find_particles() reports the overview pixel size — pass a smaller value here for higher resolution. "
                "Call update_scan() first if you want to change energy or dwell for the follow-up scan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pixel_size_nm": {
                        "type": "number",
                        "description": (
                            "Desired pixel size in nm. Each region gets point count = range_um / pixel_size_um. "
                            "Omit to use the same pixel size as the overview scan."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_tuning_session",
            "description": (
                "Begin a beamline-tuning session. Optionally moves Energy to the target, reads the "
                "undulator harmonic to pick the EPU gap step (0.05/0.02/0.01 mm for harmonic 1/3/5; "
                "feedback step 0.1; max 10 steps each direction), records EPU Gap / FBKOFFSET / "
                "EPUOFFSET as search origins, and reports SampleX/Y so the tuning scan can be centred "
                "there. Call this FIRST, then configure & start the tuning scan, then run the search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "energy": {
                        "type": "number",
                        "description": "Target photon energy in eV to tune at. Omit to tune at the current energy.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_beam_quality",
            "description": (
                "Measure live beam intensity, noise RMS, and SNR from the running tuning scan, using "
                "the most recently filled scan lines. SNR = intensity / noise_RMS is the composite "
                "tuning objective — compare it across calls to judge whether a step helped. Returns "
                "scan_complete=true when the scan has finished (then ask the user whether to start "
                "another scan to continue the search)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "daq": {"type": "string", "default": "default",
                            "description": "Detector channel to measure."},
                    "settle_lines": {"type": "integer", "default": 5,
                                     "description": "Number of fresh scan lines to wait for and average over."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "step_tuning_parameter",
            "description": (
                "Step a tuning parameter by n_steps × its step size (sign sets direction). parameter "
                "is 'gap' (EPU Gap) or 'feedback' (FBKOFFSET). Bounded to ±10 steps from the search "
                "origin; an over-limit step is refused. Sleeps ~2 s for the slow-motor beam to settle "
                "before returning. Optimize 'gap' first to its local SNR maximum, then 'feedback'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parameter": {"type": "string", "enum": ["gap", "feedback"],
                                  "description": "Which parameter to step."},
                    "n_steps": {"type": "number",
                                "description": "Number of steps (e.g. +1, -1, +2). Sign sets direction."},
                },
                "required": ["parameter", "n_steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reanchor_tuning_limit",
            "description": (
                "Re-centre a parameter's ±10-step travel limit on its current position. Call "
                "this between two search phases on the SAME parameter (e.g. after the gap "
                "intensity search, before the gap SNR search) so the next phase gets a full "
                "±10-step window around the current optimum. Only the limit anchor moves; the "
                "EPU-offset correction in finalize_tuning() still uses the original gap."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "parameter": {"type": "string", "enum": ["gap", "feedback"],
                                  "description": "Which parameter's limit to re-anchor."},
                },
                "required": ["parameter"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finalize_tuning",
            "description": (
                "Finish the tuning session: set EPUOFFSET = origin EPUOFFSET + (best EPU Gap − origin "
                "EPU Gap), clamped to limits, and report the optimum gap / feedback / offset. EPU Gap "
                "and FBKOFFSET are left at their optimised positions. Call once both parameters are tuned."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_beamline_entry",
            "description": (
                "Insert or update an entry in the beamline-parameter database (keyed by desired "
                "energy in eV), written to the server over the network. Only the fields you pass are "
                "written; other fields of an existing entry are preserved. Set populate_from_current=true "
                "to fill commanded_energy/harmonic/feedback_offset/epu_offset from the current motor "
                "positions — use this right after tuning (the live positions hold the tuned result) or "
                "whenever the user asks to record the current beamline state. After a tuning run, ASK "
                "the user before saving."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "desired_energy":      {"type": "number", "description": "Photon energy in eV (the entry key)."},
                    "populate_from_current": {"type": "boolean", "description": "Fill mappable fields from current motor positions for any not passed explicitly."},
                    "commanded_energy":    {"type": "number"},
                    "harmonic":            {"type": "integer"},
                    "grating":             {"type": "string"},
                    "exit_slit_h_pos":     {"type": "number"},
                    "exit_slit_size":      {"type": "number"},
                    "m121_vertical_angle": {"type": "number"},
                    "feedback_offset":     {"type": "number"},
                    "m101_angle":          {"type": "number"},
                    "epu_offset":          {"type": "number"},
                    "notes":               {"type": "string"},
                    "modified_by":         {"type": "string", "description": "Who made the change (default 'task_agent')."},
                },
                "required": ["desired_energy"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_beamline_from_database",
            "description": (
                "Set the beamline from a stored database entry: apply the entry's harmonic, EPU "
                "offset, and feedback offset to their motors, then move Energy to the entry's "
                "desired_energy. Columns without a motor mapping (grating, exit slits, m121/m101 "
                "angles) are reported under 'set_manually', not moved. Returns 'not_found' (with the "
                "list of available energies) if no entry exists for that energy. This moves Energy, "
                "which can be a large move — confirm with the user before calling."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "desired_energy": {"type": "number", "description": "Photon energy in eV of the entry to apply."},
                },
                "required": ["desired_energy"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "configure_osa_scan",
            "description": (
                "Configure an 'OSA Image' alignment scan (OSA_X/OSA_Y, continuousLine) centred on "
                "the current OSA position or a passed center, and derive the per-pixel dwell from "
                "the target stage velocity: dwell_ms = step_um / velocity_mm_s. OSA motors are "
                "finicky — wrong velocity distorts the image — so dwell is computed here, not "
                "guessed. Velocity defaults to the configured osa_velocity_mm_s (~0.25 mm/s). Energy "
                "is left unchanged. Typical: large ~500 µm/50 pts, small ~60 µm/30 pts. After this, "
                "call check_scan_limits(), start_scan(), wait_for_scan()."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "extent_um": {"type": "number", "description": "Square scan range in µm (e.g. 500 large, 60 small)."},
                    "points":    {"type": "integer", "description": "Points per axis (e.g. 50 large, 30 small)."},
                    "velocity_mm_s": {"type": "number", "description": "Override the configured target stage velocity (mm/s)."},
                    "x_center": {"type": "number", "description": "Scan center X in OSA µm. Default: current OSA_X (use the large-scan beam center for the follow-up small scan)."},
                    "y_center": {"type": "number", "description": "Scan center Y in OSA µm. Default: current OSA_Y."},
                },
                "required": ["extent_um", "points"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_osa_beam_center",
            "description": (
                "Find the OSA beam center as the intensity-weighted centroid of the last OSA scan "
                "image. The OSA beam is BRIGHT on a near-dark field (large scan: focused spot plus a "
                "concentric annulus of zero-order light; small scan: blurred central spot); the "
                "centroid gives the center for both, no background subtraction. Returns the center in "
                "OSA_X/OSA_Y µm and caches it for zero_osa_position(). For a large scan, feed the "
                "result to configure_osa_scan() for the small follow-up; after the small scan, "
                "confirm with the user and call zero_osa_position()."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "daq":  {"type": "string", "default": "default", "description": "Detector channel to analyse."},
                    "mode": {"type": "string", "enum": ["large", "small"], "description": "Recorded for context; centroid math is identical for both."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "zero_osa_position",
            "description": (
                "Set the last get_osa_beam_center() result as the new OSA zero, mirroring the GUI "
                "'Set to 0' button: for OSA_X and OSA_Y, new_offset = current_offset - beam_center. "
                "This does NOT move any motor — it relabels the coordinate origin. ALWAYS confirm "
                "with the user before calling (it changes the stored OSA calibration). Requires a "
                "prior get_osa_beam_center() call."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

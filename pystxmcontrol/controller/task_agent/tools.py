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
import math
import os
import tempfile
import time
import numpy as np
from pystxmcontrol.controller.scan_model import ScanModel, validate_scan
from pystxmcontrol.controller.scan_conversion import (
    build_energy_regions, build_scan_region, build_server_scan, convert_scan,
    energy_list_for_scan,
)
from pystxmcontrol.controller import energy_presets
from pystxmcontrol.controller.tool_registry import openai_schemas, specs_for, tool
from pystxmcontrol.controller.agent_ports import (
    NullFrameSource, approval_or_auto, frame_geometry, frames_available,
    lifecycle_or_null,
)

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

# Single-energy scans do NOT command the Energy motor server-side (skipping the energy-change
# overhead lets them start faster). start_scan therefore moves Energy itself when the configured
# energy differs from the current position by more than this tolerance (eV); when already at the
# target it skips the move, preserving the fast start.
_ENERGY_MATCH_TOL_EV = 0.1

# Beamline-database columns that map cleanly to a live motor position, for
# save_beamline_entry(populate_from_current=True).  Other columns (grating, exit
# slits, m121/m101 angles) have no unambiguous motor and must be passed explicitly.
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


# update_scan takes **kwargs, so its parameters cannot be derived from the signature.
# This block is therefore the contract: every key must be a ScanModel field (a parity
# test enforces that), and giving update_scan a real typed signature would retire it.
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


# ---------------------------------------------------------------------------
# ToolSet
# ---------------------------------------------------------------------------

class ToolSet:
    """Wraps all task agent tools with shared client and session state.

    One ToolSet instance is created per TaskAgent run.  ``dispatch`` maps
    tool names to methods so the agent loop doesn't need to know about the
    individual functions.
    """

    def __init__(self, client, image_model=None, logbook_model=None, on_scan_started=None,
                 confirm_fn=None):
        self._client = client
        # The optional collaborators are normalised to ports (see agent_ports) so the
        # tools never test them for None: absent ones become null implementations that
        # read empty and write nowhere.  The constructor still takes the raw GUI objects,
        # so callers need no change.
        self._image_model = NullFrameSource() if image_model is None else image_model
        self._logbook_model = logbook_model   # shared LogbookModel for add_to_logbook
        # Gates an action on operator approval.  The GUI supplies a confirm_fn that shows
        # Approve/Decline buttons and BLOCKS this (agent) thread until the operator
        # chooses.  Headless ⇒ AutoApprove, whose interactive=False makes
        # request_confirmation() say so rather than claim a real approval.
        self._confirm_fn = approval_or_auto(confirm_fn)
        # Invoked when start_scan launches a scan, letting the GUI controller build the
        # live stxm object so the completed scan gets buffered for post-scan analysis
        # (agent scans otherwise bypass that GUI machinery).
        self._on_scan_started = lifecycle_or_null(on_scan_started)
        # Flat scan definition managed by update_scan / start_scan
        self._scan: dict = ScanModel().model_dump()
        # Cached config — populated on first get_config() call
        self._motors: dict | None = None
        self._scans_config: dict | None = None   # from scan.json — driver/mode metadata
        self._last_scans: dict | None = None      # from main_config["lastScan"] — actual params
        self._positions: dict | None = None

        self._particle_regions: list[dict] | None = None
        # Most recent image produced by a *calculation* tool (e.g. the two-energy
        # elemental/difference map) rather than read live from a scan.  Kept so
        # add_to_logbook(attach="computed") can embed it — computed arrays are not
        # in _image_model['all_detector_images'], which only holds live scan frames.
        # Shape: {'array': np.ndarray, 'label': str, 'meta': dict}.
        self._last_computed_image: dict | None = None
        self._was_scanning: bool = False         # tracks scanning→idle transition
        self._last_was_multiregion: bool = False  # prevent lastScan contamination after multiregion

        # Most recent scan launched from the GUI, pushed in by the controller so the agent's
        # baseline matches what the user sees without a get_config()/update_scan() round-trip.
        # _gui_scan_dirty signals run() to surface the new baseline at the start of the next turn.
        self._last_gui_scan: dict | None = None
        self._gui_scan_dirty: bool = False

        # Most recent OSA beam-center result (µm in OSA_X/OSA_Y motor coordinates),
        # cached by get_osa_beam_center() and consumed by zero_osa_position().
        self._osa_beam_center: dict | None = None

        # Most recent focus recommendation from the intelligence module (delta_z etc.),
        # cached when draining recommendations so apply_focus_calibration() can use it.
        self._last_focus_report: dict | None = None

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

    @tool()
    def get_safety_instructions(self) -> str:
        """Return the safety rules and recommended workflows for operating this
        instrument. Call this first."""
        # The confirmation mechanism differs by surface, and naming the wrong one is
        # worse than naming none: in-process the operator gets Approve/Decline buttons,
        # but out of process request_confirmation is not advertised at all, so telling
        # the agent to call it would point it at a tool that does not exist.
        if self._confirm_fn.interactive:
            how_to_confirm = (
                "HOW TO CONFIRM:\n"
                "  Whenever a rule below says to confirm/ask before acting, call "
                "request_confirmation(summary, details) and act on its result — it shows the "
                "operator Approve/Decline buttons and blocks until they choose. If it returns "
                "DECLINED, stop and report; do NOT act. Do not just ask in prose.\n")
            confirm_scan = ("  1. Always confirm the scan configuration (via "
                            "request_confirmation) before executing.\n")
        else:
            how_to_confirm = (
                "HOW TO CONFIRM:\n"
                "  This session has no confirmation tool. Where a rule below says to "
                "confirm, ask the user in your reply and WAIT for their answer before "
                "calling the tool that acts. Never carry out a rule-flagged action in the "
                "same turn you asked about it.\n")
            confirm_scan = "  1. Always confirm the scan configuration before executing.\n"

        return (
            how_to_confirm
            + "\n"
            "CRITICAL SAFETY RULES:\n"
            + confirm_scan +
            "  2. Never move the OSA_Z motor — this can cause hardware failure.\n"
            "  3. Confirm before moving CoarseR by more than 5 degrees.\n"
            "  4. Confirm before moving Energy by more than 100 eV.\n"
            "  5. Never attempt to move a motor beyond its software limit.\n"
            "\n"
            "GENERAL OPERATING RULES:\n"
            "  1. If a tool fails, report the failure and ask how to proceed.\n"
            "  2. Confirm if scans are larger than 100x100 pixels or dwell > 5 ms.\n"
            "  3. Confirm if more than ~10 energies are requested.\n"
            "  4. Confirm if scan range > 50x50 µm (Sample) or 500x500 µm (OSA).\n"
            "  5. Confirm if scan positions are far from current motor positions.\n"
            "\n"
            "TYPICAL IMAGE SCAN WORKFLOW:\n"
            "  1. Call get_config() to get current state.\n"
            "  2. Call update_scan() with desired parameters.\n"
            "  3. Confirm the configuration with the user.\n"
            "  4. Call start_scan().\n"
            "  5. Call get_scan_status() to check progress.\n"
            "  6. Report results to the user."
        )

    @tool(requires=('approval',))
    def request_confirmation(self, summary: str, details: str = "") -> str:
        """Ask the operator to approve an action BEFORE executing it.

        Shows Approve/Decline buttons in the GUI and BLOCKS until the operator chooses.
        Returns a string beginning with 'APPROVED' or 'DECLINED'.  Call this — not a prose
        question — wherever the safety rules require confirmation (scan config, large motor
        or energy move, applying a calibration, …).  If DECLINED, stop and report; do not act.

        Args:
            summary: One-line action to confirm, e.g. 'Run Image scan 5x5 um, 100x100,
                710 eV, 0.2 ms on SampleX/SampleY'.
            details: Optional extra context shown under the summary (key parameters,
                risks, current vs target positions).
        """
        if not self._confirm_fn.interactive:
            # No interactive UI (e.g. a headless / cron run) — cannot gate the action.
            return ("APPROVED (no interactive confirmation UI is available in this session, "
                    "so proceeding automatically). Action: " + (summary or ""))
        try:
            approved = bool(self._confirm_fn({"summary": summary or "Confirm this action?",
                                              "details": details or ""}))
        except Exception as e:
            return f"DECLINED — confirmation could not be obtained ({e}). Stop and report."
        if approved:
            return "APPROVED — the operator approved. Proceed."
        return "DECLINED — the operator declined. Do NOT proceed; stop and report."

    def set_baseline_from_server_scan(self, scan_config: dict) -> bool:
        """Adopt a GUI-launched scan (server nested format) as the working baseline.

        Lets the GUI PUSH the most-recent scan parameters into the agent so the user can
        say "repeat that scan but at 708 eV" and the agent only needs to set the delta —
        no get_config()/full update_scan() round-trip required. Returns True if adopted.
        """
        try:
            # Multiregion scans carry per-particle geometry beyond Region1; only Region1 is
            # convertible and would be a misleading baseline. Skip and force a clean re-seed.
            if len(scan_config.get('scan_regions', {})) > 1:
                self._last_was_multiregion = True
                return False
            self._scan = ScanModel(**_convert_scan(scan_config)).model_dump()
            self._last_gui_scan = dict(self._scan)
            self._gui_scan_dirty = True
            self._last_was_multiregion = False
            return True
        except Exception as e:
            log.warning("[ToolSet] set_baseline_from_server_scan failed: %s", e)
            return False

    @tool()
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

            # Motors carry their units and travel limits, not just their names: an agent
            # planning a move or a scan needs the bounds, and asking per motor would cost
            # a round trip each.
            config_summary = {
                "motors":     _motor_summary(self._motors),
                "scan_types": list(self._scans_config.keys()) if self._scans_config else [],
                "positions":  self._positions,
            }
            return json.dumps(config_summary, indent=2)
        except Exception as e:
            return f"Failed to get config: {e}"

    @tool()
    def get_motor_position(self, axis: str) -> str:
        """Return the current position of a named motor.

        Args:
            axis: Motor name, e.g. 'SampleX'
        """
        if self._motors is None:
            self.get_config()
        if self._motors and axis not in self._motors:
            return f"Unknown motor '{axis}'. Call get_config() to see available motors."
        try:
            # Force a live hardware poll rather than serving the cached positions,
            # which go stale after every move/scan (get_config does not re-poll).
            pos = self._refresh_positions().get(axis)
            return f"Current position of {axis}: {round(float(pos), 4)}" if pos is not None \
                   else f"Position not available for {axis}"
        except Exception as e:
            return f"Failed to get position for {axis}: {e}"

    @tool(mutates_hardware=True)
    def move_motor(self, axis: str, pos: float) -> str:
        """Move a named motor to the given position.

        Args:
            axis: Motor name
            pos: Target position in µm (or degrees for rotation)
        """
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

    @tool(schema=_UPDATE_SCAN_SCHEMA)
    def update_scan(self, **kwargs) -> str:
        """Update the current scan definition.

        Call without arguments to inspect the current configuration.
        Pass keyword arguments matching ScanModel fields to change values.
        The updated scan is held in memory until start_scan() is called.

        Energy presets: pass energy_preset="<name>" to apply a saved energy definition —
        the same files the GUI loads (see list_energy_presets). Multi-region presets keep
        each region's own dwell. An explicit energy_start/stop/points clears an applied
        preset, so set the preset in the same call as (or after) the other energy fields.

        Energy note: setting energy_start (a single-energy scan) only records the value in the
        scan config — it does NOT move the Energy motor. The motor is moved to that energy by
        start_scan() just before the scan runs, so a scan requested at a different energy than
        the current one runs at the requested energy without any extra step here.
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
                # A saved energy definition is applied here: it becomes the scan's
                # energy_regions (keeping each region's own dwell) and displaces any
                # energy_list, which would otherwise win server-side.
                preset_note = ""
                preset = kwargs.pop('energy_preset', None)
                if preset:
                    try:
                        preset_name, regions = energy_presets.resolve_preset(preset)
                    except energy_presets.PresetNotFound as e:
                        return str(e)
                    kwargs['energy_regions'] = regions
                    kwargs['energy_list'] = None
                    preset_note = (f"Applied energy preset '{preset_name}': "
                                   f"{energy_presets.summarize_regions(regions)}\n")

                # If the caller is setting an energy range but not an explicit energy_list,
                # clear any energy_list from the baseline — otherwise it silently overrides
                # energy_start/stop/points in both _build_scan_dict and stxm._extractEnergies.
                # Multi-region energy_regions take precedence over both, so an explicit range
                # has to clear those too or the change would be silently ignored.
                _energy_range_keys = {'energy_start', 'energy_stop', 'energy_points'}
                if _energy_range_keys & kwargs.keys() and 'energy_list' not in kwargs:
                    kwargs['energy_list'] = None
                if (_energy_range_keys & kwargs.keys()
                        and 'energy_regions' not in kwargs):
                    kwargs['energy_regions'] = None

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
                return preset_note + "Scan updated: " + json.dumps(self._scan, indent=2)
            else:
                return "Current scan definition: " + json.dumps(self._scan, indent=2)
        except Exception as e:
            return f"Failed to update scan: {e}"

    @tool()
    def list_energy_presets(self) -> str:
        """List the saved energy definitions available to apply with update_scan().

        These are the same presets the GUI loads: entries pinned to the dashboard's
        Favorites bar, plus JSON files in the shared energy-presets directory.  Apply one
        with update_scan(energy_preset="<name>") instead of typing out energy ranges.
        """
        presets = energy_presets.describe_presets()
        if not presets:
            return json.dumps({
                "presets": [],
                "note": ("No saved energy definitions found. They come from the dashboard "
                         f"Favorites bar ({energy_presets.favorites_file_path()}) or JSON "
                         f"files in {energy_presets.presets_dir()}."),
            }, indent=2)
        return json.dumps({"presets": presets}, indent=2)

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

    @tool()
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

    def _single_scan_energy(self) -> float | None:
        """Return the energy (eV) of a single-energy scan, or None for a multi-energy scan.

        Multi-energy scans (energy_list with >1 entry, or energy_points > 1) move the Energy
        motor per energy point in the driver, so they need no pre-move.
        """
        energy_list = self._scan.get('energy_list')
        if energy_list:
            return float(energy_list[0]) if len(energy_list) == 1 else None
        if int(self._scan.get('energy_points', 1) or 1) > 1:
            return None
        return float(self._scan.get('energy_start'))

    def _ensure_scan_energy(self) -> str | None:
        """Move the Energy motor to a single-energy scan's energy before it starts.

        Single-energy scans do NOT command the Energy motor server-side (to skip the
        energy-change overhead and start faster), so a scan configured at, say, 708 eV would
        otherwise run at whatever energy the motor currently sits at. Mirrors the GUI's
        "move to first energy" step. Skips the move when already at the target (within
        _ENERGY_MATCH_TOL_EV), preserving the fast start. Returns a human-readable note about
        the move, or None if no move was needed/applicable.
        """
        target = self._single_scan_energy()
        if target is None:
            return None
        current = self._motor_pos("Energy")
        if current is not None and abs(current - target) <= _ENERGY_MATCH_TOL_EV:
            return None
        res = self.move_motor("Energy", target)
        if not res.startswith("Successfully"):
            # Surface the failure to the caller so it doesn't scan at the wrong energy.
            return f"ENERGY MOVE FAILED: {res}"
        return f"moved Energy {current}→{target} eV before scan" if current is not None \
               else f"moved Energy to {target} eV before scan"

    @tool(mutates_hardware=True)
    def start_scan(self) -> str:
        """Submit the current scan definition to the server and start acquisition.

        Returns immediately once the server acknowledges the scan has started.
        Use get_scan_status() to poll for completion.

        Note: a single-energy scan does NOT change the Energy motor itself (the server skips
        the energy-change overhead so these scans start faster). start_scan therefore moves
        Energy to the configured scan energy first when it differs from the current position;
        if it already matches, the move is skipped.
        """
        if self._scans_config is None:
            self.get_config()
        ok, result = self._validate_scan_limits()
        if not ok:
            return ("Scan not started — range exceeds the fine/piezo travel: "
                    + "; ".join(result["oversize"])
                    + ". Ask the user whether to run a tiled or coarse_only scan, then "
                      "update_scan(tiled=True) or update_scan(coarse_only=True) and retry.")
        energy_note = self._ensure_scan_energy()
        if energy_note and energy_note.startswith("ENERGY MOVE FAILED"):
            return f"Scan not started — {energy_note}"
        try:
            scan_dict = _build_scan_dict(self._scan, self._scans_config or {})
            # Let the GUI controller build the live stxm object BEFORE the scan command
            # is sent, so no early frames are missed and the completed scan is buffered
            # for post-scan analysis (two-energy maps, particle counting).
            try:
                self._on_scan_started(scan_dict)
            except Exception as e:
                log.debug("on_scan_started callback failed: %s", e)
            response = self._client.send_message({"command": "scan", "scan": scan_dict})
            if response and response.get('status'):
                self._was_scanning = True
                self._clear_scan_alarms()   # fresh alarm slate for this scan
                msg = f"Scan started: {self._scan['scan_type']} ({self._scan['x_range']}×{self._scan['y_range']} µm)"
                return msg + (f" ({energy_note})" if energy_note else "")
            else:
                data = response.get('data', 'no details') if response else 'no response'
                return f"Scan failed to start: {data}"
        except Exception as e:
            return f"Failed to start scan: {e}"

    @tool(mutates_hardware=True)
    def cancel_scan(self) -> str:
        """Stop the scan currently running on the instrument.

        Sends the same 'cancel' command the acquisition tab's Cancel button issues, so the
        server aborts the in-progress acquisition. This is distinct from cancelling the agent's
        own tool loop (the GUI's stop-agent button) — that leaves the scan running; this stops
        the scan itself. Returns as soon as the server acknowledges.
        """
        try:
            response = self._client.send_message({"command": "cancel"})
        except Exception as e:
            return f"Failed to cancel scan: {e}"
        # The server replies status=True when it aborted a running scan, False when there was
        # no scan to cancel (see server.py cancel handler).
        self._was_scanning = False
        if response and response.get("status"):
            return "Scan cancelled — the server is aborting the current acquisition."
        return "No scan is currently running on the instrument, so there was nothing to cancel."

    @tool()
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

    @tool()
    def wait_for_scan(self, timeout_seconds: float | None = None) -> str:
        """Block until the current scan finishes, then return a completion message.

        Uses the server's live time_remaining estimate (updated during the scan) to
        set the timeout.  Call this once after start_scan() instead of polling
        get_scan_status() in a loop — it consumes only one agent iteration.

        Args:
            timeout_seconds: Maximum seconds to wait. Omit to use the server's time
                estimate.
        """
        import time as _time

        POLL_INTERVAL = 3.0   # seconds between status checks

        if timeout_seconds is None:
            # Use the most recently received time_remaining from the monitor stream,
            # or fall back to a conservative 30-minute ceiling.
            tr = self._image_model.get('time_remaining')
            timeout_seconds = (tr * 2.0) if (tr and tr > 0) else 1800.0

        deadline = _time.monotonic() + timeout_seconds
        self._was_scanning = True   # ensure completion message fires on idle

        while _time.monotonic() < deadline:
            # Break out immediately if the intelligence module raised an anomaly alarm
            # (e.g. beam loss) during the scan, so the agent can surface it and let the
            # user decide whether to abort. The scan keeps running; this just hands the
            # loop back to the agent instead of blocking until the scan finishes.
            alarm_msg = self._drain_scan_alarms()
            if alarm_msg is not None:
                return alarm_msg
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
            tr = self._image_model.get('time_remaining')
            if tr and tr > 0:
                deadline = _time.monotonic() + tr * 2.0

            _time.sleep(POLL_INTERVAL)

        # Timed out WITHOUT observing idle, so the scan is still running. Leave
        # _was_scanning=True so the follow-up get_scan_status() this message asks
        # for still reports "Scan complete" when it catches the idle transition.
        # (Clearing it here was a completion-signal leak: the deadline is
        # now+time_remaining*2 refreshed each loop, and time_remaining collapses to
        # ~0 at the tail of a scan, so wait_for_scan times out at the END of nearly
        # every scan. If the flag were cleared, the scan would finish moments later
        # and get_scan_status would report a bare "Instrument is idle" — the agent's
        # stall budget would never reset even as scans kept completing.)
        return (f"Timed out after {timeout_seconds:.0f} s waiting for scan to finish. "
                "Call get_scan_status() to check current state.")

    def _clear_scan_alarms(self) -> None:
        """Drop any queued anomaly alarms so a new scan starts with a clean slate."""
        self._image_model.set('pending_alarms', [])

    def _drain_scan_alarms(self) -> str | None:
        """Return a formatted anomaly-alarm message if the intelligence module raised one
        during the current scan, clearing the queue; else None.

        Alarms are anomaly diagnoses (e.g. beam loss, focus decline) posted by the server
        intelligence module and routed into image_model['pending_alarms'] by the GUI
        controller. wait_for_scan() drains them so it can hand control back to the agent —
        with the scan STILL RUNNING — instead of blocking until the scan finishes.
        """
        alarms = self._image_model.get('pending_alarms')
        if not alarms:
            return None
        self._image_model.set('pending_alarms', [])
        lines = []
        for a in alarms:
            sev = a.get('severity', 'unknown')
            atype = a.get('anomaly_type', 'anomaly')
            text = (a.get('suggestion') or a.get('message') or '').strip()
            lines.append(f"[{sev}] {atype}: {text}".rstrip(': ').strip())
        joined = "\n".join(lines)
        return (
            "SCAN INTERRUPTED BY ANOMALY ALARM — the scan is STILL RUNNING.\n"
            f"{joined}\n\n"
            "Report this alarm to the user and ask whether to abort the scan or continue. "
            "If they say abort, call cancel_scan(). If they say continue, call wait_for_scan() "
            "again to keep waiting. Do NOT silently proceed past this alarm."
        )

    @tool(requires=('frames',))
    def get_last_scan_stats(self, daq: str = "default") -> str:
        """Return statistics and spatial analysis of the most recently completed scan image.

        Computes mean, std, contrast, and the physical coordinates (µm) of the
        darkest region — useful for locating absorbing features such as particles.

        Args:
            daq: DAQ channel to analyse (e.g. 'default', 'xrf', 'tey'). Falls back to
                'default' if the requested channel is absent.
        """
        if not frames_available(self._image_model):
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
        x_center, y_center, x_range, y_range = frame_geometry(self._image_model)

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

    def _log_particle_map(self, qimg, meta: dict, text: str) -> str:
        """Write the just-rendered particle map to the open logbook. Returns a short status
        suffix for the finder's result. The map is always cached as the computed image
        (see caller) so add_to_logbook(attach='computed') can re-attach it even when no
        logbook is open here."""
        if qimg is None:
            return " (a particle map could not be rendered)."
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return (" A particle map was prepared but not saved — no logbook is open. Open one "
                    "and call add_to_logbook(attach='computed') to save it.")
        try:
            idx = model.add(snap_qimage=qimg, meta=meta, text=text, author="agent")
        except Exception as e:
            return f" (particle map prepared but the logbook write failed: {e})."
        return f" A particle map was saved to the logbook (entry #{idx})."

    @tool(requires=('frames',))
    def find_particles(self, max_particles: int | None = None, daq: str = "default",
                       save_map: bool = True) -> str:
        """Locate absorbing particles in a single transmission image and return scan regions.

        Uses Otsu thresholding on the inverted image plus connected-component analysis — this
        finds *generic* absorbers in ONE image; it is NOT element-specific.  For an element
        request (e.g. iron) after a two-energy scan, use count_element_particles() instead,
        which builds the elemental (OD-difference) map and finds the element-bearing particles.
        Results are stored internally and can be submitted immediately with start_multiregion_scan().

        Args:
            max_particles: cap on regions returned, ordered by size (default: all found).
            daq: detector channel to analyse.
            save_map: when True (default), render an overview image with a numbered box
                around each found region and save it to the open logbook (and cache it as the
                computed image for add_to_logbook(attach='computed')). Set False to skip.
        """
        if not frames_available(self._image_model):
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
        x_center, y_center, x_range, y_range = frame_geometry(self._image_model)
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

        # Render a map of the found regions on the overview and save it to the logbook so the
        # user gets a visual of where every ROI sits within the overview. The rendered figure
        # is also cached as the computed image (add_to_logbook(attach='computed')).
        logbook_note = ""
        if save_map:
            # col 0 → x_center - x_range/2, row 0 → y_center - y_range/2 (find_particles'
            # pixel-centre convention), drawn origin='lower' so boxes land on their features.
            extent = (x_center - x_range / 2.0, x_center + x_range / 2.0,
                      y_center - y_range / 2.0, y_center + y_range / 2.0)
            map_qimg = self._render_particle_map(
                image, regions, extent, title=f"Found {len(regions)} particle(s)")
            map_meta = {'result': 'particle map', 'particles': len(regions),
                        'overview_um': f"{x_range:.1f}×{y_range:.1f}"}
            if map_qimg is not None:
                self._remember_computed_figure(map_qimg, "particle map", map_meta)
            text = (f"Particle finder located {len(regions)} region(s) in a "
                    f"{x_range:.1f}×{y_range:.1f} µm overview. Numbered boxes mark each "
                    "region's footprint.")
            logbook_note = self._log_particle_map(map_qimg, map_meta, text)

        overview_pixel_nm = round(px_x * 1000, 1)
        result = {
            "particles_found": len(regions),
            "overview_pixel_size_nm": overview_pixel_nm,
            "overview_scan_um": {"x_range": x_range, "y_range": y_range,
                                  "x_center": x_center, "y_center": y_center},
            "regions": regions,
            "particle_map": logbook_note.strip() or "not requested (save_map=False)",
            "next_step": "Call start_multiregion_scan() to image all regions. "
                         "Pass pixel_size_nm to scan at higher resolution than the overview "
                         f"(overview was {overview_pixel_nm} nm/px).",
        }
        return json.dumps(result, indent=2)

    @tool(requires=('frames',), mutates_hardware=True)
    def start_multiregion_scan(self, pixel_size_nm: float | None = None) -> str:
        """Start an image scan covering every loaded particle region.

        Region list comes from whichever you called last: count_element_particles()
        (element-specific, from the two-energy map — preferred for element requests) or
        find_particles() (generic absorbers in a single image).
        Uses the current scan parameters (energy, dwell, proposal, etc.) but replaces
        the scan geometry with those particle regions.


        Call update_scan() first if you want to change energy or dwell for the follow-up
        scan.
        Args:
            pixel_size_nm: desired pixel size in nm for the zoom scans. Each region
                gets its own point count computed as round(range_um / pixel_size_um).
                If omitted, uses the overview scan's pixel size as the default.
        """
        if not getattr(self, '_particle_regions', None):
            return ("No particle regions available — call count_element_particles() "
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
            # Same builder (and so the same half-pixel inset) as the single-region path;
            # ndigits=4 because a particle ROI's pixel size is often below 10 nm, which
            # the default 3 decimals of the reported step cannot express.
            scan_regions[f'Region{i + 1}'] = build_scan_region(
                r['xCenter'], r['xRange'], xpts,
                r['yCenter'], r['yRange'], ypts,
                ndigits=4,
            )
        base['scan_regions'] = scan_regions

        n = len(scan_regions)
        try:
            response = self._client.send_message({"command": "scan", "scan": base})
        except Exception as e:
            return f"Failed to start multi-region scan: {e}"

        if response and response.get('status'):
            self._last_was_multiregion = True
            self._was_scanning = True
            self._clear_scan_alarms()   # fresh alarm slate for this scan
            return f"Multi-region scan started: {n} particle region(s)."
        data = response.get('data', 'no details') if response else 'no response'
        return f"Multi-region scan failed to start: {data}"

    @tool(requires=('frames',))
    def get_intelligence_recommendations(self) -> str:
        """Return any pending recommendations from the intelligence module and clear the queue.

        The intelligence module analyses each completed scan and posts structured
        recommendations here, e.g. recentre suggestions (off-centre feature) and focus
        calibrations. (Two-energy element mapping is NOT posted here — the task agent owns
        that: call count_element_particles() to build the elemental map and find element
        particles on demand.)

        This tool drains the queue — call it after every wait_for_scan().
        """
        if not frames_available(self._image_model):
            return "Image model not available."

        pending = list(self._image_model.get("pending_recommendations") or [])
        self._image_model.set("pending_recommendations", [])

        for rec in pending:
            # Cache the most recent focus recommendation for apply_focus_calibration().
            if rec.get("subtype") == "focus" and rec.get("delta_z") is not None:
                self._last_focus_report = rec

        if not pending:
            return "No recommendations pending."

        return json.dumps({"recommendations": pending}, indent=2)

    # ------------------------------------------------------------------
    # Multi-scan memory buffer (GUI-side ring buffer of completed scans)
    # ------------------------------------------------------------------

    def _get_scan_buffer(self) -> list:
        """Return the buffered-scan records (newest last), or [] if unavailable."""
        buf = self._image_model.get('scan_buffer')
        if buf is None:
            return []
        try:
            return list(buf)
        except TypeError:
            return []

    def _get_buffered_scan(self, scan_id: str | None = None,
                           index: int | None = None,
                           min_energies: int = 1) -> dict | None:
        """Resolve a single buffered-scan record.

        Selection order: explicit *index* (0 = oldest, -1 = newest), then *scan_id*
        substring match, otherwise the most recent record with >= min_energies frames.
        Returns None when nothing matches.
        """
        records = self._get_scan_buffer()
        if not records:
            return None
        if index is not None:
            try:
                return records[index]
            except IndexError:
                return None
        if scan_id:
            for rec in reversed(records):
                if scan_id in (rec.get('scan_id') or ''):
                    return rec
            return None
        for rec in reversed(records):
            if len(rec.get('energies') or []) >= min_energies:
                return rec
        return None

    @tool(requires=('frames',))
    def list_buffered_scans(self) -> str:
        """List the completed scans held in memory, newest last.

        The GUI retains the last several completed scans (full multi-energy stacks) so
        the agent can analyse a prior scan without re-running it — e.g. count_element_particles()
        on a two-energy scan that is no longer the most recent.  Each entry's 'index' can be
        passed to count_element_particles(scan_index=...).
        """
        records = self._get_scan_buffer()
        if not records:
            return ("No scans buffered yet. Buffering happens when an Image scan completes "
                    "in the GUI (requires the GUI controller; not available in headless runs).")
        out = []
        for i, rec in enumerate(records):
            energies = rec.get('energies') or []
            out.append({
                "index": i,
                "scan_id": os.path.basename(rec.get('scan_id') or '') or None,
                "scan_type": rec.get('scan_type') or None,
                "n_energies": len(energies),
                "energy_range_eV": ([round(float(min(energies)), 2),
                                     round(float(max(energies)), 2)] if energies else None),
            })
        return json.dumps({"buffered_scans": out, "count": len(out)}, indent=2)

    @tool(requires=('frames',))
    def count_element_particles(self, pre_energy: float | None = None,
                                edge_energy: float | None = None,
                                daq: str = "default", region: int = 0,
                                scan_id: str | None = None,
                                scan_index: int | None = None,
                                max_particles: int | None = None,
                                save_map: bool = True) -> str:
        """Count particles and how many contain an element, from a buffered two-energy scan.

        Builds the two-energy elemental map (the same OD-difference the Analysis tab's Map
        button computes) from a buffered multi-energy scan, then counts (a) all particles
        via pre-edge absorption and (b) the element-containing subset via the elemental map.
        Frames within one scan are already co-registered, so no alignment is needed.

        Use this for element questions (e.g. "how many particles contain iron?") after a
        two-energy scan (pre-edge + edge).  Unlike find_particles() (generic absorbers in one
        image) this needs two energies.  This is the single owner of two-energy elemental
        mapping — it works directly on the in-memory buffered scan and also caches the map so
        add_to_logbook(attach="computed") can save it.

        The element-containing regions are stored for start_multiregion_scan(), so you can
        immediately zoom into the element-bearing particles.

        Args:
            pre_energy:  pre-edge energy in eV; snaps to the nearest frame. Omit to use the
                         lowest-energy frame.
            edge_energy: on-edge energy in eV; snaps to the nearest frame. Omit to use the
                         highest-energy frame.
            daq:         detector channel to analyse (default 'default').
            region:      scan-region index for multi-region scans (default 0).
            scan_id:     analyse a specific buffered scan by id substring; default = most
                         recent scan with >= 2 energies.
            scan_index:  analyse a specific buffered scan by index (see list_buffered_scans);
                         takes precedence over scan_id.
            max_particles: cap on element regions returned, ordered by size (default: all).
            save_map: when True (default), render the elemental map with a numbered box around
                each element-containing region and save it to the open logbook (and cache it as
                the computed image for add_to_logbook(attach='computed')). Set False to skip.
        """
        from pystxmcontrol.utils.image import (two_energy_map, otsu_absorption_mask,
                                               find_feature_boxes)

        rec = self._get_buffered_scan(scan_id=scan_id, index=scan_index, min_energies=2)
        if rec is None:
            return ("No buffered two-energy scan found. Run a two-energy scan (pre-edge + edge), "
                    "or call list_buffered_scans() to see what is available.")

        stx = rec.get('stxm')
        energies = np.asarray(rec.get('energies') or [], dtype=float)
        if stx is None or energies.size < 2:
            return "Buffered scan has fewer than two energies — element mapping needs two."

        interp = getattr(stx, 'interp_counts', None)
        if not isinstance(interp, dict):
            return "Buffered scan has no image data."
        if daq not in interp and 'default' in interp:
            daq = 'default'
        if daq not in interp:
            return f"No detector channel '{daq}' in buffered scan."
        try:
            stack3 = np.asarray(interp[daq][region], dtype=float)
        except (IndexError, TypeError):
            return f"Region {region} not available in buffered scan."
        if stack3.ndim != 3 or stack3.shape[0] < 2:
            return "Buffered scan region does not contain a two-energy stack."

        # Resolve the two frame indices: nearest-energy snap, or first/last fallback.
        pre_idx = (int(np.argmin(np.abs(energies - pre_energy)))
                   if pre_energy is not None else 0)
        edge_idx = (int(np.argmin(np.abs(energies - edge_energy)))
                    if edge_energy is not None else energies.size - 1)
        if pre_idx == edge_idx:
            return ("Pre-edge and edge energies resolved to the same frame "
                    f"({float(energies[pre_idx])} eV). Choose two distinct energies.")
        pre = stack3[pre_idx]
        edge = stack3[edge_idx]

        # Element map (bright where the element absorbs more on the edge) and total particles.
        element_map, valid = two_energy_map(pre, edge)

        # Retain the computed map so the agent can save it to the logbook
        # (add_to_logbook(attach="computed")); it is not a live scan frame.
        self._remember_computed_image(
            element_map,
            label="two-energy elemental map",
            meta={
                "computation": "two-energy elemental (OD-difference) map",
                "pre_energy": f"{float(energies[pre_idx]):.2f} eV",
                "edge_energy": f"{float(energies[edge_idx]):.2f} eV",
                "daq": daq,
                "scan_id": os.path.basename(rec.get('scan_id') or '') or None,
            },
        )
        element_mask = otsu_absorption_mask(element_map, dark=False, valid=valid)
        total_mask = otsu_absorption_mask(pre, dark=True)

        element_boxes = find_feature_boxes(element_mask, max_features=max_particles)
        total_boxes = find_feature_boxes(total_mask)

        # Pixel boxes -> µm scan regions, using the buffered scan's requested grid.
        ny, nx = pre.shape[:2]
        try:
            xpos = np.asarray(stx.xPos[region], dtype=float)
            ypos = np.asarray(stx.yPos[region], dtype=float)
        except (AttributeError, IndexError, TypeError):
            xpos = ypos = None

        regions = []
        logbook_note = ""
        if xpos is not None and ypos is not None and xpos.size >= 2 and ypos.size >= 2:
            pad_px = 2
            cols = np.arange(xpos.size)
            rows = np.arange(ypos.size)
            for b in element_boxes:
                minr = max(0, b['minr'] - pad_px)
                minc = max(0, b['minc'] - pad_px)
                maxr = min(ny - 1, b['maxr'] + pad_px)
                maxc = min(nx - 1, b['maxc'] + pad_px)
                cx = float(np.interp((minc + maxc) / 2.0, cols, xpos))
                cy = float(np.interp((minr + maxr) / 2.0, rows, ypos))
                rx = abs(float(xpos[min(maxc, nx - 1)] - xpos[minc]))
                ry = abs(float(ypos[min(maxr, ny - 1)] - ypos[minr]))
                regions.append({
                    'xCenter': round(cx, 3), 'yCenter': round(cy, 3),
                    'xRange': round(rx, 3), 'yRange': round(ry, 3),
                })
            self._particle_regions = regions
            px_x = abs(float(xpos[-1] - xpos[0])) / max(nx - 1, 1)
            px_y = abs(float(ypos[-1] - ypos[0])) / max(ny - 1, 1)
            self._overview_pixel_size_um = (px_x, px_y)

            # Map the element-containing regions on the elemental map itself (bright = element)
            # so the user sees where every ROI sits. Extent uses the raw xPos/yPos endpoints
            # (col 0 → xpos[0], row 0 → ypos[0]) so the picture stays faithful to the scan
            # direction while the boxes, in absolute µm, stay aligned. Rendered even when no
            # element region is found — the map alone documents the negative result.
            if save_map:
                extent = (float(xpos[0]), float(xpos[-1]), float(ypos[0]), float(ypos[-1]))
                map_qimg = self._render_particle_map(
                    element_map, regions, extent,
                    title=f"{len(regions)} element particle(s)")
                map_meta = {
                    'result': 'element particle map',
                    'element_particles': len(regions),
                    'pre_energy': f"{float(energies[pre_idx]):.2f} eV",
                    'edge_energy': f"{float(energies[edge_idx]):.2f} eV",
                    'daq': daq,
                }
                if map_qimg is not None:
                    # Overwrite the cached elemental map with the boxed version so
                    # add_to_logbook(attach='computed') attaches the annotated map.
                    self._remember_computed_figure(map_qimg, "element particle map", map_meta)
                text = (f"Two-energy element map ({float(energies[pre_idx]):.1f} → "
                        f"{float(energies[edge_idx]):.1f} eV): {len(regions)} element-containing "
                        "region(s); numbered boxes mark each footprint.")
                logbook_note = self._log_particle_map(map_qimg, map_meta, text)
        elif save_map:
            logbook_note = (" A map could not be built — the buffered scan has no per-pixel "
                            "position data; the elemental map is still cached for "
                            "add_to_logbook(attach='computed').")

        total = len(total_boxes)
        n_elem = len(element_boxes)
        result = {
            "total_particles": total,
            "element_particles": n_elem,
            "fraction_with_element": round(n_elem / total, 3) if total else None,
            "pre_energy_eV": round(float(energies[pre_idx]), 2),
            "edge_energy_eV": round(float(energies[edge_idx]), 2),
            "daq": daq,
            "scan_id": os.path.basename(rec.get('scan_id') or '') or None,
            "element_regions": regions,
            "element_map": logbook_note.strip() or "not requested (save_map=False)",
            "next_step": ("Element regions stored. Call start_multiregion_scan(pixel_size_nm=...) "
                          "to image the element-containing particles at higher resolution."
                          if regions else
                          "No element-containing particles detected at these two energies."),
        }
        return json.dumps(result, indent=2)

    @tool(requires=('frames',))
    def analyze_energy_stack(self,
                             file: str | None = None,
                             daq: str = "default", region: int = 0,
                             scan_id: str | None = None,
                             scan_index: int | None = None,
                             n_components: int = 4, n_clusters: int = 4,
                             max_iter: int = 500, init: str = "nndsvda",
                             log: bool = True, note: str | None = None) -> str:
        """Analyse a multi-energy stack with autoProcess + non-negative matrix factorisation.

        Runs the same pipeline as the Analysis tab's Auto Process + Calculate NNMF buttons,
        headless: subtract dark field -> despike -> align frames -> optical density (calcOD),
        then NMF (sklearn) with k-means clustering of the NMF weight maps. Produces a
        colour-coded cluster map and the per-cluster mean OD spectra.

        Use this for a many-energy spectral stack (a NEXAFS / energy-stack scan), NOT a
        two-energy scan (use count_element_particles for two energies). By default it analyses
        the most recent buffered multi-energy scan; pass file=... to analyse a saved
        .stxm/.hdr/.cxi stack instead.

        When log is True (default) and a logbook is open, it posts one entry containing a
        combined figure — the cluster map beside the cluster spectra — authored as 'agent'.
        The figure is also cached so add_to_logbook(attach='computed') can re-post it.

        Args:
            file:         analyse a saved stack file (.stxm/.hdr/.cxi) by path; omit to use a
                          buffered in-memory scan.
            daq:          detector channel (buffered scans only; default 'default').
            region:       scan-region index for multi-region scans/files (default 0).
            scan_id:      analyse a specific buffered scan by id substring (buffered only).
            scan_index:   analyse a specific buffered scan by index (see list_buffered_scans);
                          takes precedence over scan_id.
            n_components: NMF components (default 4). Clamped to the number of energies.
            n_clusters:   k-means clusters of the NMF weight maps (default 4).
            max_iter:     NMF max iterations (default 500).
            init:         NMF initialisation ('nndsvda' default, or 'random').
            log:          post the result to the logbook (default True).
            note:         logbook entry text; a summary is generated when omitted.
        """
        from pystxmcontrol.utils.stack import stack

        # ---- resolve the stack: saved file, or in-memory buffered scan --------------
        if file:
            path = os.path.expanduser(file)
            if not os.path.isfile(path):
                return f"Stack file not found: {file}"
            if not path.lower().endswith(('.stxm', '.hdr', '.cxi')):
                return "Unsupported stack file — expected a .stxm, .hdr, or .cxi file."
            try:
                stk = stack(fileName=path, iRegion=region)
            except Exception as e:
                return f"Failed to open stack file {os.path.basename(path)}: {e}"
            source = os.path.basename(path)
            if getattr(stk, 'processedFrames', None) is None or len(stk.energies) < 3:
                return (f"Stack '{source}' has fewer than 3 energies — NMF needs a multi-energy "
                        "stack. Use count_element_particles for a two-energy scan.")
        else:
            rec = self._get_buffered_scan(scan_id=scan_id, index=scan_index, min_energies=3)
            if rec is None:
                return ("No buffered multi-energy stack found. Run an energy stack (>= 3 "
                        "energies), pass file=..., or call list_buffered_scans().")
            stk, err = self._stack_from_buffered_scan(rec, daq=daq, region=region)
            if stk is None:
                return err
            source = os.path.basename(rec.get('scan_id') or '') or "buffered scan"

        n_energies = int(len(stk.energies))
        # NMF requires n_components <= n_features (energies); clamp with a note.
        clamp_note = ""
        if n_components > n_energies:
            clamp_note = (f"n_components reduced from {n_components} to {n_energies} "
                          "to match the number of energies")
            n_components = n_energies

        # ---- autoProcess (dark field -> despike -> align -> OD), then NMF -----------
        try:
            stk.subtractDarkField()
            stk.despike()
            stk.alignFrames(mode='manualtranslation')
            stk.calcOD()
        except Exception as e:
            return f"autoProcess failed on '{source}': {e}"
        try:
            stk.calcNMF(n_components=n_components, n_clusters=n_clusters,
                        max_iter=max_iter, init=init)
        except Exception as e:
            return f"NMF failed on '{source}': {e}"

        energies = np.asarray(stk.energies, dtype=float)
        cluster_sizes = [int((stk.clusters == i).sum()) for i in range(n_clusters)]

        meta = {
            "computation": "autoProcess + NNMF (cluster map + cluster spectra)",
            "source": source,
            "n_components": n_components,
            "n_clusters": n_clusters,
            "n_energies": n_energies,
            "energy_range_eV": f"{energies.min():.2f}-{energies.max():.2f}",
            "daq": None if file else daq,
        }

        # Render the combined cluster-map + cluster-spectra figure and cache it so the
        # logbook post below (or a later add_to_logbook(attach='computed')) can embed it.
        title = f"NNMF of {source}: {n_components} components, {n_clusters} clusters"
        qimg = self._render_nmf_figure(stk, title=title)
        self._remember_computed_figure(qimg, label="NNMF cluster map + spectra", meta=meta)

        result = {
            "source": source,
            "n_components": n_components,
            "n_clusters": n_clusters,
            "n_energies": n_energies,
            "energy_range_eV": [round(float(energies.min()), 2),
                                round(float(energies.max()), 2)],
            "cluster_pixel_counts": cluster_sizes,
            "stack_shape": list(stk.odFrames.shape),
        }
        if clamp_note:
            result["clamp_note"] = clamp_note

        # ---- one-shot logbook post -------------------------------------------------
        if log:
            model = self._logbook_model
            if model is None or not getattr(model, "folder", None):
                result["logbook"] = ("not posted — no logbook is open; open one in the Logbook "
                                     "tab, then call add_to_logbook(attach='computed').")
            elif qimg is None:
                result["logbook"] = "not posted — the figure could not be rendered."
            else:
                text = note or (
                    f"NNMF analysis of {source}: {n_components} NMF components, "
                    f"{n_clusters} clusters over {n_energies} energies "
                    f"({energies.min():.2f}-{energies.max():.2f} eV). "
                    "Cluster map and per-cluster OD spectra attached.")
                try:
                    index = model.add(snap_qimage=qimg, meta=meta, text=text, author="agent")
                    result["logbook"] = (f"posted entry #{index} to "
                                         f"'{os.path.basename(model.folder)}'.")
                except Exception as e:
                    result["logbook"] = f"failed to post: {e}"
        else:
            result["logbook"] = ("not requested — the figure is cached; call "
                                 "add_to_logbook(attach='computed') to post it.")

        return json.dumps(result, indent=2)

    @tool(requires=('frames',))
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

        if not frames_available(self._image_model):
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

        x_center, y_center, x_range, y_range = frame_geometry(self._image_model)

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

    @tool()
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

    @tool(mutates_hardware=True)
    def read_daq(self, daq: str = "default", dwell: float = 100.0, shutter: bool = True) -> str:
        """Take a single-point DAQ reading without running a scan.

        Useful for checking beam intensity before committing to a full scan.

        Args:
            daq: DAQ channel name
            dwell: Integration time in ms
            shutter: Open shutter during measurement
        """
        try:
            response = self._client.send_message({
                "command": "get_data",
                "daq": daq,
                "dwell": dwell,
                "shutter": shutter,
            })
            value = response.get('data') if response else None
            scalar, n = self._daq_value_to_scalar(value)
            if scalar is None:
                return "No data returned from DAQ"
            suffix = f" (mean of {n} samples)" if n > 1 else ""
            return f"DAQ reading ({daq}, {dwell} ms): {round(scalar, 4)}{suffix}"
        except Exception as e:
            return f"DAQ read failed: {e}"

    @staticmethod
    def _daq_value_to_scalar(value):
        """Reduce a DAQ getPoint() result to (scalar, n_samples), or (None, 0).

        getPoint() shapes vary by DAQ: a bare scalar, a numpy array of raw samples
        (size 1 or more — float() on a size-≥1 array raises in modern numpy, which was
        the read_daq failure), or a {channel: array} dict for multi-channel counters.
        Reduce to a single mean intensity so read_daq can report one number.
        """
        if value is None:
            return None, 0
        # Multi-channel counters return {channel: array([...])}; pool all channels.
        if isinstance(value, dict):
            value = list(value.values())
        try:
            arr = np.asarray(value, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            return None, 0
        if arr.size == 0:
            return None, 0
        return float(arr.mean()), int(arr.size)

    @tool()
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

    def _refresh_positions(self) -> dict:
        """Force a live hardware poll and update the cached positions.

        get_config() does NOT re-poll the motors server-side, so the cached
        positions go stale after every move/scan. getMotorPositions forces the
        server to call getPos() on each motor (which also refreshes the Energy
        motor's calibratedPosition used by autofocus). Falls back to the cache
        if the live poll fails.
        """
        try:
            self._positions = self._client.getMotorPositions()
        except Exception:
            if self._positions is None:
                self.get_config()
        return self._positions or {}

    def _motor_pos(self, axis: str) -> float | None:
        """Return a fresh float position for *axis* via a live hardware poll."""
        pos = self._refresh_positions().get(axis)
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

    @tool(mutates_hardware=True)
    def start_tuning_session(self, energy: float | None = None) -> str:
        """Begin a beamline-tuning session: anchor origins and pick step sizes.

        Reads the undulator harmonic to choose the EPU gap step, records the current
        EPU Gap / FBKOFFSET / EPUOFFSET as search origins, and reports the SampleX/Y
        position to centre the tuning scan on.  Call this first, then configure and
        start the tuning scan, then run the search with read_beam_quality() /
        step_tuning_parameter().

        Args:
            energy: Target photon energy in eV to tune at. Omit to tune at the current
                energy.
        """
        self.get_config()
        if energy is not None:
            move_res = self.move_motor("Energy", float(energy))
            if not move_res.startswith("Successfully"):
                return f"Could not move Energy to {energy}: {move_res}"

        positions = self._refresh_positions()

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

    @tool(requires=('frames',))
    def read_beam_quality(self, daq: str = "default", settle_lines: int = 5) -> str:
        """Measure live beam intensity, noise RMS, and SNR from the running tuning scan.

        Reads the most recently filled scan lines so the result reflects the current
        beamline-parameter values.  SNR = intensity / noise_RMS is the composite tuning
        objective — compare it across calls to judge whether a step helped or hurt.
        Returns scan_complete=true if the scan has finished (ask the user whether to
        start another scan to continue the search).

        Args:
            daq: Detector channel to measure.
            settle_lines: Number of fresh scan lines to wait for and average over.
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

    @tool(mutates_hardware=True)
    def step_tuning_parameter(self, parameter: str, n_steps: float) -> str:
        """Step a tuning parameter by n_steps × its step size (sign sets direction).

        parameter is 'gap' (EPU Gap) or 'feedback' (FBKOFFSET).  Movement is bounded to
        ±max_steps steps from the search origin; a step that would exceed the limit is
        refused.  Sleeps for the slow-motor beam settle time before returning, so the
        next read_beam_quality() reflects the new beam.

        Args:
            parameter: Which parameter to step.
            n_steps: Number of steps (e.g. +1, -1, +2). Sign sets direction.
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

    @tool()
    def reanchor_tuning_limit(self, parameter: str) -> str:
        """Re-centre a parameter's ±max_steps travel limit on its current position.

        Use this between search phases on the same parameter (e.g. after the intensity
        search on 'gap', before the SNR search on 'gap') so the second phase gets a full
        ±max_steps window around the first phase's optimum. This moves only the limit
        anchor; the session start position used by finalize_tuning() is unchanged, so the
        EPU-offset correction still reflects the total gap change from the original gap.

        Args:
            parameter: Which parameter's limit to re-anchor.
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

    @tool(mutates_hardware=True)
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

    @tool()
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


        The desired_energy key is rounded to the nearest whole eV (entries do not need
        sub-eV precision; commanded_energy keeps its precise value). After a tuning run,
        ASK the user before saving.
        Args:
            desired_energy: Photon energy in eV (the entry key).
            populate_from_current: Fill mappable fields from current motor positions for
                any not passed explicitly.
            modified_by: Who made the change (default 'task_agent').
        """
        from pystxmcontrol.controller.beamline_database import (
            BeamlineDatabaseClient, COLUMNS,
        )

        try:
            # Entries are keyed to whole-eV granularity; round the key (the
            # commanded_energy column keeps the precise live value).
            desired_energy = _round_to_eV(desired_energy)
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
            positions = self._refresh_positions()
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

    @tool(mutates_hardware=True)
    def set_beamline_from_database(self, desired_energy: float) -> str:
        """Set the beamline from a stored database entry for *desired_energy*.

        Looks up the (exact) entry, applies its calibration knobs — harmonic, EPU offset,
        feedback offset — to the corresponding motors, then moves Energy to the entry's
        desired_energy (the desired→commanded mapping is handled at a lower level, so the
        high-level target is always the desired energy). Columns without a clean motor
        mapping (grating, exit slits, m121/m101 angles) are reported, not moved.
        Moving Energy can be a large move — confirm with the user first per the safety rules.


        The energy you pass is rounded to the nearest whole eV for the lookup (a live
        707.8 eV finds the 708 eV entry). If no entry exists this returns 'not_found'
        with the closest stored energy in 'nearest_energy_eV' — ASK the user whether to
        apply that nearest entry before calling again with it.
        Args:
            desired_energy: Photon energy in eV of the entry to apply.
        """
        from pystxmcontrol.controller.beamline_database import (
            BeamlineDatabaseClient, COLUMN_NAMES,
        )

        try:
            requested_energy = float(desired_energy)
        except (TypeError, ValueError):
            return f"Invalid desired_energy {desired_energy!r} — must be a number."
        # Entries are keyed to whole-eV granularity, so look up the rounded value
        # (e.g. a live energy of 707.8 eV finds the 708 eV entry).
        rounded_energy = _round_to_eV(requested_energy)

        db = BeamlineDatabaseClient(self._client)
        try:
            entry = db.get_entry(rounded_energy)
            if entry is None and rounded_energy != requested_energy:
                # Fall back to the exact requested value so a deliberately-passed
                # legacy/non-integer energy (e.g. a confirmed nearby entry) still matches.
                entry = db.get_entry(requested_energy)
        except Exception as e:
            return f"Failed to read beamline database: {e}"

        if entry is None:
            try:
                energies = db.get_desired_energies()
            except Exception:
                energies = []
            nearest = (min(energies, key=lambda e: abs(e - rounded_energy))
                       if energies else None)
            if nearest is not None:
                msg = (f"No beamline entry at {rounded_energy} eV. The closest stored entry is "
                       f"{nearest} eV. Ask the user whether to apply that entry; only if they "
                       f"agree, call set_beamline_from_database({nearest}). Do not apply it "
                       f"without confirmation.")
            else:
                msg = ("The beamline database is empty — create an entry with "
                       "save_beamline_entry().")
            return json.dumps({
                "status": "not_found",
                "requested_energy_eV": requested_energy,
                "rounded_energy_eV": rounded_energy,
                "available_energies": energies,
                "nearest_energy_eV": nearest,
                "message": msg,
            }, indent=2)

        # From here on use the matched entry's own desired_energy as the target.
        desired_energy = entry["desired_energy"]

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

    @tool()
    def configure_osa_scan(self, extent_um: float, points: int,
                           velocity_mm_s: float | None = None,
                           x_center: float | None = None,
                           y_center: float | None = None) -> str:
        """Configure an 'OSA Image' scan for alignment, deriving dwell from stage velocity.

        Sets up a square OSA_X/OSA_Y scan centred on OSA_X/Y = 0 (or the passed center)
        and computes the per-pixel dwell so the stage moves at the target velocity:
        dwell_ms = step_um / velocity_mm_s, step_um = extent_um / (points - 1).
        OSA motors are finicky — too fast or too slow distorts the image — so the dwell is
        derived here rather than guessed. Velocity defaults to main.json scan.osa_velocity_mm_s
        (fallback 0.25 mm/s). Energy is left unchanged. Call check_scan_limits() then
        start_scan() next; do not change the dwell afterwards.

        Args:
            extent_um: square scan range in µm (e.g. ~500 large, ~60 small).
            points:    points per axis (e.g. 50 large, 30 small).
            velocity_mm_s: override the configured target stage velocity.
            x_center, y_center: scan center in OSA µm; default to 0 (use the large-scan
                beam center here for the follow-up small scan).
            x_center: Scan center X in OSA µm. Default: current OSA_X (use the large-
                scan beam center for the follow-up small scan).
            y_center: Scan center Y in OSA µm. Default: current OSA_Y.
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

        # Default the scan center to OSA_X/Y = 0 (the nominal aligned position) rather
        # than the current stage position, unless the caller passes an explicit center.
        if x_center is None:
            x_center = 0.0
        if y_center is None:
            y_center = 0.0

        step_um = extent_um / (points - 1)
        # 1 mm/s == 1 µm/ms, so step_um (µm) / velocity_mm_s (µm/ms) = dwell in ms.
        dwell_ms = round(step_um / velocity_mm_s, 4)

        warning = None
        if not (_OSA_DWELL_MIN_MS <= dwell_ms <= _OSA_DWELL_MAX_MS):
            warning = (f"Computed dwell {dwell_ms} ms is outside the expected "
                       f"[{_OSA_DWELL_MIN_MS}, {_OSA_DWELL_MAX_MS}] ms band — check "
                       f"extent/points/velocity before starting.")

        # Run at the CURRENT energy. Switching scan_type to 'OSA Image' re-seeds the baseline
        # from the server's stale lastScan, which carries an old energy_start/energy_list;
        # start_scan() would then move Energy to that stale value. Pin the scan to a single
        # energy at the live Energy position (and clear energy_list) so _ensure_scan_energy()
        # is a no-op and the OSA scan never changes energy.
        current_energy = self._motor_pos("Energy")
        energy_kwargs: dict = {}
        if current_energy is not None:
            energy_kwargs = {
                'energy_start': round(current_energy, 3),
                'energy_stop':  round(current_energy, 3),
                'energy_points': 1,
                'energy_list':  None,
            }

        upd = self.update_scan(
            scan_type='OSA Image', x_motor=_OSA_X_MOTOR, y_motor=_OSA_Y_MOTOR,
            x_center=round(float(x_center), 3), y_center=round(float(y_center), 3),
            x_range=extent_um, y_range=extent_um,
            x_points=points, y_points=points, dwell=dwell_ms,
            **energy_kwargs,
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
            "energy_ev": round(current_energy, 3) if current_energy is not None else "unchanged",
            "next_step": "Call check_scan_limits(), then start_scan(), then wait_for_scan().",
        }
        if warning:
            result["warning"] = warning
        return json.dumps(result, indent=2)

    @tool(requires=('frames',))
    def get_osa_beam_center(self, daq: str = "default", mode: str = "small",
                            method: str = "auto") -> str:
        """Find the OSA beam center from the last scan image.

        The OSA beam is BRIGHT on a near-dark field. Two estimators are available, chosen with
        ``method``:
        * 'centroid' — the intensity-weighted center of mass sum(I*x)/sum(I). Robust for a single
          broad/concentric blob (a focused spot inside a concentric annulus, or a defocused blob):
          the symmetry keeps the centroid on the true center.
        * 'log' — the curvature-isolated focused peak (Laplacian-of-Gaussian, see
          _focused_peak_center). Rejects an off-centre RAMP of unfocused light (often bright in one
          CORNER) that would pull the plain centroid off. BUT on a single broad smooth blob with no
          compact spot the LoG response is a ring and its argmax can lock onto the blob's curvature
          shoulder — giving a center pushed off toward one side (use 'centroid' instead there).
        * 'auto' (default) — 'log' for mode='small', 'centroid' for mode='large'. Falls back to the
          centroid if the LoG finds no compact peak.

        The result always reports BOTH estimates (beam_center_um is the chosen one; centroid_um is
        the plain COM) plus their disagreement, so you can compare and re-run with an explicit
        method if the chosen estimate looks wrong.

        Returns the center in OSA_X/OSA_Y µm and caches it for zero_osa_position(). For a large
        scan, pass beam_center_um to configure_osa_scan() for the small follow-up; after the
        small scan, confirm with the user and call zero_osa_position().

        Args:
            daq:  detector channel to analyse (default 'default').
            mode: 'large' or 'small' — only affects the 'auto' estimator choice.
            method: 'auto' (default), 'centroid' (intensity COM), or 'log' (focused peak).
        """
        if not frames_available(self._image_model):
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

        x_center, y_center, x_range, y_range = frame_geometry(self._image_model)

        cols = np.arange(nx)
        rows = np.arange(ny)
        com_col = float((weights.sum(axis=0) * cols).sum() / total)
        com_row = float((weights.sum(axis=1) * rows).sum() / total)

        def px_to_um(col, row):
            x = x_center + (col / max(nx - 1, 1) - 0.5) * x_range
            y = y_center + (row / max(ny - 1, 1) - 0.5) * y_range
            return round(x, 3), round(y, 3)

        # Resolve the requested estimator. 'auto' picks LoG for small mode (reject off-centre
        # unfocused light) and the plain centroid for large mode; explicit 'centroid'/'log'
        # override that. The LoG can lock onto a broad blob's curvature ring, so 'centroid' is
        # the escape hatch for a single smooth blob.
        method_req = (method or "auto").strip().lower()
        if method_req in ("com", "center_of_mass"):
            method_req = "centroid"
        if method_req not in ("auto", "centroid", "log"):
            return (f"Unknown method '{method}'. Use 'auto' (default), 'centroid' "
                    f"(intensity center of mass), or 'log' (curvature-isolated focused peak).")

        method = "centroid"
        dog_info = None
        log_note = None
        col_c, row_c = com_col, com_row
        want_log = method_req == "log" or (method_req == "auto" and mode == "small")
        if want_log:
            peak = _focused_peak_center(flat)
            if peak is not None:
                col_c, row_c = peak["col_c"], peak["row_c"]
                method = "log_focused_peak"
                dog_info = {k: peak[k] for k in ("sigma_px", "border_margin_px", "prominence")}
            elif method_req == "log":
                log_note = ("Requested method='log' but no compact focused peak was found "
                            "(likely a broad smooth blob) — used the centroid instead.")

        beam_x, beam_y = px_to_um(col_c, row_c)
        com_x, com_y = px_to_um(com_col, com_row)

        # Brightest pixel as a sanity check.
        peak_row, peak_col = np.unravel_index(np.argmax(weights), weights.shape)
        peak_x, peak_y = px_to_um(float(peak_col), float(peak_row))

        self._osa_beam_center = {"x": beam_x, "y": beam_y, "daq": daq, "mode": mode}

        # Gap between the chosen center and the plain centroid — a large value flags that the
        # LoG and the COM disagree, so the caller can reconsider the method.
        disagreement_um = round(float(np.hypot(beam_x - com_x, beam_y - com_y)), 3)

        result = {
            "daq": daq,
            "mode": mode,
            "method_requested": method_req,
            "method": method,
            "image_shape_px": [ny, nx],
            "scan_center_um": {"x": x_center, "y": y_center},
            "beam_center_um": {"x": beam_x, "y": beam_y},
            "centroid_um": {"x": com_x, "y": com_y},   # plain intensity COM, for comparison
            "brightest_pixel_um": {"x": peak_x, "y": peak_y},
            "centroid_vs_chosen_gap_um": disagreement_um,
            "offset_from_scan_center_um": {"x": round(beam_x - x_center, 3),
                                           "y": round(beam_y - y_center, 3)},
            "next_step": ("For a large scan, pass beam_center_um to configure_osa_scan() for "
                          "a small follow-up scan. For the final small scan, confirm with the "
                          "user, then call zero_osa_position() to set this position as the new OSA zero."),
        }
        if log_note is not None:
            result["note"] = log_note
        elif dog_info is not None:
            result["focused_peak"] = dog_info
            result["note"] = ("Center is the curvature-isolated focused peak (LoG). Compare "
                              "beam_center_um vs centroid_um (gap = centroid_vs_chosen_gap_um): a "
                              "large gap with HIGH prominence means unfocused light was skewing the "
                              "centroid (trust the LoG). A large gap with LOW prominence on a single "
                              "broad smooth blob means the LoG locked onto the blob's curvature ring "
                              "— re-run with method='centroid'.")
        return json.dumps(result, indent=2)

    @tool(mutates_hardware=True)
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
    # Focus (OSA focus → Z=0 calibration)
    # ------------------------------------------------------------------

    @tool()
    def configure_focus_scan(self, scan_type: str = "OSA Focus",
                             line_center_x: float = 20.0, line_y: float = 0.0,
                             line_length: float = 50.0, line_points: int = 100,
                             z_range: float = 500.0, z_points: int = 100,
                             z_center: float | None = None,
                             velocity_mm_s: float | None = None) -> str:
        """Configure an OSA Focus (or Focus) scan: a line across the feature × ZonePlateZ.

        For OSA focus (the Z=0 calibration), the line runs along OSA_X at fixed OSA_Y (default
        OSA_Y=0 once the OSA is centered) and ZonePlateZ is stepped (the outer axis). Defaults
        match typical use: line centered slightly off-axis (line_center_x≈20 µm) so the scan
        crosses the OSA edge, 50 µm long, 100 points; Z range 500 µm, 100 points, centered on
        the current ZonePlateZ. The per-pixel dwell is derived from the OSA stage velocity (the
        line moves along OSA_X). Energy is left unchanged. After this: check_scan_limits(),
        start_scan(), wait_for_scan(); the intelligence module then posts a focus recommendation.

        Args:
            scan_type: 'OSA Focus' (default) or 'Focus' (sample).
            line_center_x: line center along the line axis (µm); ~20 for OSA so the line crosses the edge.
            line_y: fixed position of the off-line axis (µm); 0 for a centered OSA.
            line_length, line_points: line extent (µm) and point count.
            z_range, z_points: ZonePlateZ scan extent (µm) and step count.
            z_center: ZonePlateZ scan center; defaults to the current ZonePlateZ position.
            velocity_mm_s: override the OSA stage velocity used to derive dwell.
            line_length: Line length (µm), default 50.
            line_points: Points along the line, default 100.
            z_range: ZonePlateZ scan range (µm), default 500.
            z_points: ZonePlateZ steps, default 100.
        """
        if self._motors is None or self._positions is None:
            self.get_config()
        try:
            line_length = float(line_length); line_points = int(line_points)
            z_range = float(z_range); z_points = int(z_points)
        except (TypeError, ValueError):
            return "Invalid line/z parameters."
        if line_points < 2 or z_points < 3 or line_length <= 0 or z_range <= 0:
            return "line_points>=2, z_points>=3, line_length>0, z_range>0 required."

        is_osa = "OSA" in scan_type
        x_motor = _OSA_X_MOTOR if is_osa else "SampleX"
        y_motor = _OSA_Y_MOTOR if is_osa else "SampleY"

        if z_center is None:
            z_center = self._motor_pos("ZonePlateZ")
        if z_center is None:
            return ("Could not read current ZonePlateZ for the scan center — pass z_center.")

        if velocity_mm_s is None:
            main_cfg = getattr(self._client, 'main_config', None) or {}
            velocity_mm_s = (main_cfg.get('scan', {}) or {}).get(
                'osa_velocity_mm_s', _OSA_DEFAULT_VELOCITY_MM_S)
        velocity_mm_s = float(velocity_mm_s)
        if velocity_mm_s <= 0:
            return f"velocity_mm_s must be > 0 (got {velocity_mm_s})."
        # The line runs along OSA_X, so the dwell requirement is identical to an OSA Image scan:
        # dwell = step / velocity, step = line_length / (points - 1) — same formula as
        # configure_osa_scan, using the velocity from main.json scan.osa_velocity_mm_s.
        x_step = line_length / (line_points - 1)
        dwell_ms = round(x_step / velocity_mm_s, 4)

        # Run at the CURRENT energy. Switching scan_type re-seeds the baseline from the
        # server's stale lastScan (old energy_start/energy_list), which start_scan() would
        # then move Energy to. Pin to a single energy at the live position so the focus scan
        # never changes energy (mirrors configure_osa_scan).
        current_energy = self._motor_pos("Energy")
        energy_kwargs: dict = {}
        if current_energy is not None:
            energy_kwargs = {
                'energy_start': round(current_energy, 3),
                'energy_stop':  round(current_energy, 3),
                'energy_points': 1,
                'energy_list':  None,
            }

        upd = self.update_scan(
            scan_type=scan_type, x_motor=x_motor, y_motor=y_motor, z_motor="ZonePlateZ",
            x_center=round(float(line_center_x), 3), y_center=round(float(line_y), 3),
            x_range=line_length, y_range=0.0, x_points=line_points, y_points=1,
            z_center=round(float(z_center), 3), z_range=z_range, z_points=z_points,
            dwell=dwell_ms,
            **energy_kwargs,
        )
        if upd.startswith(("Invalid", "Unknown", "Failed")):
            return f"Focus scan configuration failed: {upd}"

        return json.dumps({
            "status": "focus scan configured",
            "scan_type": scan_type,
            "line": {"motor": x_motor, "center": round(float(line_center_x), 3),
                     "length_um": line_length, "points": line_points,
                     "fixed_y_motor": y_motor, "fixed_y": round(float(line_y), 3)},
            "z": {"motor": "ZonePlateZ", "center": round(float(z_center), 3),
                  "range_um": z_range, "points": z_points},
            "dwell_ms": dwell_ms,
            "next_step": "check_scan_limits(), start_scan(), wait_for_scan(), then "
                         "get_intelligence_recommendations() for the focus result.",
        }, indent=2)

    @tool(mutates_hardware=True)
    def apply_focus_calibration(self, delta_z: float | None = None) -> str:
        """Apply the focus correction to the ZonePlateZ offset (defines the Z=0 calibration).

        Uses the DELTA of the measured focus from the scan center (delta_z = focus_z - z_center)
        from the intelligence module's last focus recommendation, or an explicit delta_z. Sets
        new ZonePlateZ offset = current_offset - delta_z (same sign convention as zero_osa;
        the delta is frame-independent so no A0 handling is needed). Does NOT move any motor.
        ALWAYS confirm with the user first AND report the correction magnitude — this changes
        the stored Z calibration.

        Args:
            delta_z: Focus offset from the scan center (µm). Omit to use the last focus
                recommendation.
        """
        if delta_z is None:
            if not self._last_focus_report:
                return ("No focus recommendation available — run an OSA focus scan and call "
                        "get_intelligence_recommendations() first, or pass delta_z explicitly.")
            delta_z = self._last_focus_report.get("delta_z")
            if delta_z is None:
                return "Cached focus recommendation has no delta_z."
            if not self._last_focus_report.get("in_range", True):
                return json.dumps({
                    "status": "refused",
                    "reason": ("Focus was at the edge of the scan range (in_range=False) — it may "
                               "be outside the scanned Z. Rescan with the Z range shifted toward "
                               f"the {self._last_focus_report.get('edge_hint')} before calibrating."),
                }, indent=2)
        try:
            delta_z = float(delta_z)
        except (TypeError, ValueError):
            return f"Invalid delta_z {delta_z!r}."

        if self._motors is None:
            self.get_config()
        info = (self._motors or {}).get("ZonePlateZ", {})
        if "offset" not in info:
            return "No 'offset' field for ZonePlateZ in motor config — cannot calibrate."
        cur_offset = float(info["offset"])
        new_offset = round(cur_offset - delta_z, 4)

        try:
            self._client.change_motor_config("ZonePlateZ", "offset", new_offset)
        except Exception as e:
            return f"Failed to set ZonePlateZ offset to {new_offset}: {e}"

        self._motors = getattr(self._client, 'motorInfo', None) or self._motors
        self._positions = getattr(self._client, 'currentMotorPositions', None) or self._positions
        self._last_focus_report = None

        return json.dumps({
            "status": "focus calibration applied",
            "correction_um": round(delta_z, 4),
            "correction_magnitude_um": round(abs(delta_z), 4),
            "zoneplatez_offset": {"old": round(cur_offset, 4), "new": new_offset},
            "note": "ZonePlateZ offset updated by -delta so the measured focus now reads as the "
                    "scan center (Z calibration). No motor moved; move ZonePlateZ to focus separately.",
        }, indent=2)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _latest_two_energy_map(self):
        """Build the OD-difference (two-energy elemental) map from the newest buffered
        two-energy scan. Returns (array, meta) on success, or (None, reason).

        This lets add_to_logbook(attach="computed") save the map even when the agent
        obtained its particle count from the intelligence module (which computes the map
        server-side and cannot ship the array over the monitor stream) rather than from
        count_element_particles. Requires the GUI scan buffer — unavailable headless.
        """
        try:
            from pystxmcontrol.utils.image import two_energy_map
        except Exception as e:
            return None, f"image utilities unavailable ({e})"
        rec = self._get_buffered_scan(min_energies=2)
        if rec is None:
            return None, ("no buffered two-energy scan (buffering needs a completed two-energy "
                          "Image scan in the GUI; unavailable in headless runs)")
        stx = rec.get('stxm')
        energies = np.asarray(rec.get('energies') or [], dtype=float)
        interp = getattr(stx, 'interp_counts', None)
        if stx is None or energies.size < 2 or not isinstance(interp, dict):
            return None, "buffered scan has no two-energy image data"
        daq = 'default' if 'default' in interp else next(iter(interp), None)
        if daq is None:
            return None, "no detector channel in buffered scan"
        try:
            stack3 = np.asarray(interp[daq][0], dtype=float)
        except (IndexError, TypeError):
            return None, "buffered scan region unavailable"
        if stack3.ndim != 3 or stack3.shape[0] < 2:
            return None, "buffered scan is not a two-energy stack"
        diff, _valid = two_energy_map(stack3[0], stack3[-1])
        meta = {
            "computation": "two-energy elemental (OD-difference) map",
            "pre_energy": f"{float(energies[0]):.2f} eV",
            "edge_energy": f"{float(energies[-1]):.2f} eV",
            "daq": daq,
            "scan_id": os.path.basename(rec.get('scan_id') or '') or None,
        }
        return diff, meta

    def _remember_computed_image(self, arr, label: str, meta: dict | None = None) -> None:
        """Cache an image produced by a calculation tool for later logbook attachment.

        Calculation results (e.g. the two-energy difference map) never enter
        ``_image_model['all_detector_images']`` (which the GUI fills with live scan
        frames), so without this the agent has no way to embed them in the logbook.
        """
        try:
            a = np.asarray(arr, dtype=float)
        except (ValueError, TypeError):
            return
        if a.ndim >= 2 and a.size:
            self._last_computed_image = {
                "array": a,
                "label": label,
                "meta": dict(meta or {}),
            }

    @staticmethod
    def _array_to_qimage(arr):
        """Render a 2-D detector array to an autoscaled 8-bit grayscale QImage for a logbook
        snapshot. Returns None if rendering isn't possible. QImage construction is thread-safe
        (no widgets), so this is fine on the agent's worker thread."""
        try:
            from PySide6.QtGui import QImage
        except ImportError:
            return None
        a = np.asarray(arr, dtype=float)
        if a.ndim > 2:
            a = a.reshape(a.shape[0], a.shape[1])
        if a.ndim != 2 or a.size == 0:
            return None
        finite = a[np.isfinite(a)]
        if finite.size == 0:
            return None
        lo, hi = float(finite.min()), float(finite.max())
        scaled = (a - lo) / (hi - lo) * 255.0 if hi > lo else np.zeros_like(a)
        buf = np.ascontiguousarray(np.clip(scaled, 0, 255).astype(np.uint8))
        h, w = buf.shape
        qimg = QImage(buf.data, w, h, w, QImage.Format_Grayscale8)
        return qimg.copy()   # copy so the QImage owns its pixels (buf is local)

    def _stack_from_buffered_scan(self, rec: dict, daq: str = "default", region: int = 0):
        """Build a bare stack object from a buffered scan's in-memory transmission cube.

        Returns (stack, "") on success or (None, error_message).  The returned stack has
        processedFrames / energies populated so the autoProcess + NMF stack methods run
        headless exactly as they would on a file-loaded stack (they operate on ndarrays,
        not on the rawFrames image objects that file loading builds)."""
        from pystxmcontrol.utils.stack import stack
        stx = rec.get('stxm')
        energies = np.asarray(rec.get('energies') or [], dtype=float)
        if stx is None or energies.size < 3:
            return None, "Buffered scan has fewer than three energies — NMF needs a stack."
        interp = getattr(stx, 'interp_counts', None)
        if not isinstance(interp, dict):
            return None, "Buffered scan has no image data."
        if daq not in interp and 'default' in interp:
            daq = 'default'
        if daq not in interp:
            return None, f"No detector channel '{daq}' in buffered scan."
        try:
            cube = np.asarray(interp[daq][region], dtype=float)
        except (IndexError, TypeError):
            return None, f"Region {region} not available in buffered scan."
        if cube.ndim != 3 or cube.shape[0] < 3:
            return None, "Buffered scan region is not a multi-energy stack."
        stk = stack()
        stk.processedFrames = cube.copy()
        stk.energies = energies
        stk.shape = stk.processedFrames.shape
        return stk, ""

    def _render_nmf_figure(self, stk, title: str | None = None):
        """Render a combined NMF figure (colour cluster map + cluster OD spectra) to a
        QImage for a logbook snapshot.  Uses matplotlib's Agg canvas directly (no pyplot,
        no GUI backend) so it is safe on the agent's worker thread.  Returns None on failure."""
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
        except ImportError:
            return None
        try:
            rgb = stk.rgbClusterMap()
            energies = np.asarray(stk.energies, dtype=float)
            # ~2:1 landscape (image + plot side by side) so the logbook renders it double-width;
            # tall enough that the square cluster map fills its half rather than letterboxing.
            fig = Figure(figsize=(10.0, 5.0), dpi=120)
            FigureCanvasAgg(fig)
            ax_map = fig.add_subplot(1, 2, 1)
            ax_spec = fig.add_subplot(1, 2, 2)
            ax_map.imshow(rgb)
            ax_map.set_title("Cluster map")
            ax_map.set_xticks([])
            ax_map.set_yticks([])
            for i, spec in enumerate(stk.clusterSpectra):
                c = np.asarray(stk.penColors[i], dtype=float)
                if c.size >= 3 and c.max() > 1:   # 0-255 ints -> 0-1 for matplotlib
                    c = c / 255.0
                ax_spec.plot(energies, np.asarray(spec, dtype=float),
                             color=tuple(c[:3]), label=f"Cluster {i}")
            ax_spec.set_xlabel("Energy (eV)")
            ax_spec.set_ylabel("Optical density")
            ax_spec.set_title("Cluster spectra")
            ax_spec.legend(fontsize="small", loc="best")
            if title:
                fig.suptitle(title, fontsize="medium")
            fig.tight_layout()
            return self._figure_to_qimage(fig)
        except Exception as e:
            log.warning("[ToolSet] _render_nmf_figure failed: %s", e)
            return None

    # Distinct box colours cycled per particle, matching the Browser "Map Selected" palette
    # (data_browser_widget._map_selected) so the agent's map reads the same as the GUI's.
    _MAP_BOX_COLORS = ["#ff5252", "#ffd740", "#69f0ae", "#40c4ff",
                       "#e040fb", "#ffab40", "#b2ff59", "#64ffda"]

    def _render_particle_map(self, image, regions, extent, title=None):
        """Render a background image with a numbered box around each found particle region,
        to a QImage for a logbook snapshot.  Uses matplotlib's Agg canvas directly (no pyplot,
        no GUI backend) so it is safe on the agent's worker thread.  Returns None on failure.

        ``extent`` is (left, right, bottom, top) in µm, mapping array col 0 → left, row 0 →
        bottom (origin='lower').  It must use the SAME pixel→µm convention that produced the
        region boxes so every box lands on the feature it was measured from; passing the raw
        scan-direction endpoints (which may run high→low) keeps the picture faithful to the
        acquisition while the boxes, in absolute µm data coordinates, stay aligned."""
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from matplotlib.patches import Rectangle
        except ImportError:
            return None
        try:
            a = np.asarray(image, dtype=float)
            if a.ndim > 2:
                a = a.reshape(a.shape[0], a.shape[1])
            if a.ndim != 2 or a.size == 0:
                return None
            left, right, bottom, top = (float(v) for v in extent)
            fig = Figure(figsize=(6.5, 6.0), dpi=120)
            FigureCanvasAgg(fig)
            ax = fig.add_subplot(1, 1, 1)
            ax.imshow(a, cmap='gray', origin='lower',
                      extent=[left, right, bottom, top], aspect='equal')
            for i, r in enumerate(regions):
                rxc = float(r['xCenter']); ryc = float(r['yCenter'])
                rxr = float(r['xRange']);  ryr = float(r['yRange'])
                color = self._MAP_BOX_COLORS[i % len(self._MAP_BOX_COLORS)]
                ax.add_patch(Rectangle((rxc - rxr / 2.0, ryc - ryr / 2.0), rxr, ryr,
                                       fill=False, edgecolor=color, linewidth=1.5))
                # Number at the box's top-left (y increases upward with origin='lower').
                ax.text(rxc - rxr / 2.0, ryc + ryr / 2.0, str(i + 1),
                        color='black', fontsize=8, va='bottom', ha='left',
                        bbox=dict(facecolor=color, edgecolor='none', pad=1.0))
            ax.set_xlabel("X (µm)")
            ax.set_ylabel("Y (µm)")
            ax.set_title(title or f"{len(regions)} particle region(s)")
            fig.tight_layout()
            return self._figure_to_qimage(fig)
        except Exception as e:
            log.warning("[ToolSet] _render_particle_map failed: %s", e)
            return None

    @staticmethod
    def _figure_to_qimage(fig):
        """Convert a drawn matplotlib Figure to an RGBA QImage.  Thread-safe (no widgets)."""
        try:
            from PySide6.QtGui import QImage
        except ImportError:
            return None
        fig.canvas.draw()
        w, h = fig.canvas.get_width_height()
        buf = np.ascontiguousarray(np.asarray(fig.canvas.buffer_rgba()))
        qimg = QImage(buf.data, w, h, 4 * w, QImage.Format_RGBA8888)
        return qimg.copy()   # copy so the QImage owns its pixels (buf is local)

    def _remember_computed_figure(self, qimage, label: str, meta: dict | None = None) -> None:
        """Cache a pre-rendered figure (QImage) from a calculation tool so
        add_to_logbook(attach='computed') can embed it directly.  Used for colour/composite
        results (e.g. the NNMF cluster map + spectra) that _array_to_qimage cannot render."""
        if qimage is None:
            return
        self._last_computed_image = {
            "array": None,
            "qimage": qimage,
            "label": label,
            "meta": dict(meta or {}),
        }

    @tool(requires=('logbook',), hidden_params=("attach_last_scan",))
    def add_to_logbook(self, text: str, attach: str = "scan",
                       daq: str = "default", attach_last_scan: bool | None = None) -> str:
        """Add an entry to the active logbook on the user's behalf.

        Use this to record an observation, a result, or an intelligence recommendation —
        e.g. after a scan completes, summarise what was done and attach the image. The entry
        is stamped author='agent'. Requires a logbook to be open in the Logbook tab; if none
        is open, ask the user to open or create one.


        Only add entries the user asked for, or that clearly document the work just done
        — do not spam the logbook.
        Args:
            attach: which image to embed (grayscale, autoscaled):
                "scan"     — the most recent live scan image (default);
                "computed" — the most recent image produced by a calculation tool, e.g. the
                             two-energy elemental/difference map from count_element_particles
                             or the NNMF cluster map + spectra figure from analyze_energy_stack.
                             Use this to save a computed result, not a raw scan;
                "none"     — text-only entry, no image.
            daq:    detector channel for the "scan" image (default 'default').
            attach_last_scan: deprecated — True maps to attach="scan", False to attach="none".
            text: The entry body — the observation, result, or recommendation.
        """
        model = self._logbook_model
        if model is None:
            return "Logbook is not available in this session."
        if not getattr(model, "folder", None):
            return ("No logbook is open. Ask the user to open or create one in the Logbook "
                    "tab (New/Open), then try again.")
        if not (text or "").strip():
            return "Refusing to add an empty logbook entry — provide text."

        # Backward compatibility with the old boolean parameter.
        if attach_last_scan is not None:
            attach = "scan" if attach_last_scan else "none"
        attach = (attach or "scan").lower()
        if attach not in ("scan", "computed", "none"):
            return (f"Unknown attach mode '{attach}'. Use 'scan', 'computed', or 'none'.")

        # Best-effort metadata from the current scan context.
        meta = {}
        scan_type = self._image_model.get('scan_type', '')
        energy = self._image_model.get('current_energy')
        if scan_type:
            meta['scan_type'] = scan_type
        if energy is not None:
            meta['energy'] = f"{float(energy):.1f} eV"

        qimg = None
        attach_desc = ""
        snap_note = ""
        if attach == "computed":
            comp = self._last_computed_image
            # A pre-rendered figure (e.g. the NNMF cluster map + spectra) is embedded as-is;
            # only raw arrays go through _array_to_qimage's grayscale autoscale below.
            pre_qimg = comp.get('qimage') if isinstance(comp, dict) else None
            fallback_reason = ""
            if pre_qimg is not None:
                qimg = pre_qimg
                meta.update(comp.get('meta') or {})
                attach_desc = f" with the {comp.get('label', 'computed image')}"
            else:
                arr = comp.get('array') if isinstance(comp, dict) else None
                if not isinstance(arr, np.ndarray):
                    # Nothing cached (e.g. the count came from the intelligence module, which
                    # can't ship the map array): build the two-energy map from the buffered scan.
                    built, info = self._latest_two_energy_map()
                    if isinstance(built, np.ndarray):
                        self._remember_computed_image(built, "two-energy elemental map", info)
                        comp = self._last_computed_image
                        arr = comp.get('array')
                    else:
                        fallback_reason = info
                if isinstance(arr, np.ndarray):
                    qimg = self._array_to_qimage(arr)
                    meta.update(comp.get('meta') or {})
                    attach_desc = f" with the {comp.get('label', 'computed image')}"
            if qimg is None:
                snap_note = (f" (no computed image was available to attach — {fallback_reason}; "
                             "run a calculation such as count_element_particles first)"
                             if fallback_reason else
                             " (no computed image was available to attach — run a "
                             "calculation such as count_element_particles first)")
        elif attach == "scan":
            all_images = self._image_model.get('all_detector_images')
            image = all_images.get(daq) if isinstance(all_images, dict) else None
            if image is None and isinstance(all_images, dict):
                image = all_images.get('default')
            if isinstance(image, np.ndarray):
                qimg = self._array_to_qimage(image)
                attach_desc = " with the last scan image"
            if qimg is None:
                snap_note = " (no scan image was available to attach)"

        try:
            index = model.add(snap_qimage=qimg, meta=meta, text=text, author="agent")
        except Exception as e:
            return f"Failed to add logbook entry: {e}"
        return (f"Added logbook entry #{index} to '{os.path.basename(model.folder)}'"
                f"{attach_desc}{snap_note}.")

    # ── logbook-as-context (phase 5; only used when task_agent.logbook_context on) ──────
    def _logbook_entries_for_context(self, authors=None) -> list:
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return []
        entries = model.entries
        if authors:
            entries = [e for e in entries if e.get("author", "human") in authors]
        return entries

    def logbook_index(self, max_entries: int = 50, authors=None) -> str | None:
        """Compact one-line-per-entry index for auto-injection at task start.

        Returns None when no logbook is open or it has no (matching) entries. Entries keep
        their absolute #number so they line up with the full logbook and with citations.
        """
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return None
        entries = model.entries
        idx = list(enumerate(entries))                       # (0-based position, entry)
        if authors:
            idx = [(i, e) for i, e in idx if e.get("author", "human") in authors]
        if not idx:
            return None
        shown = idx[-max_entries:] if max_entries and len(idx) > max_entries else idx
        lines = []
        for i, e in shown:
            snippet = (e.get("text") or e.get("comment") or "").strip().replace("\n", " ")
            if len(snippet) > 90:
                snippet = snippet[:87] + "…"
            title = e.get("image_file") or "note"
            lines.append(f"#{i + 1} [{e.get('author', 'human')}] {e.get('timestamp', '')} "
                         f"{title} (id={e.get('id', '')}): {snippet}")
        header = f"Logbook '{os.path.basename(model.folder)}' — {len(entries)} entries"
        if len(shown) < len(idx):
            header += f" (showing last {len(shown)})"
        return header + "\n" + "\n".join(lines)

    @tool(requires=('logbook',), feature="logbook_context")
    def search_logbook(self, query: str = "", author: str = "", limit: int = 20) -> str:
        """Search the active logbook. Substring match (case-insensitive) over the entry text,
        comment, metadata, and filename; optionally filter by author ('human'/'agent'/
        'intelligence'). Returns compact hits (id, #, author, timestamp, title, snippet) —
        call get_logbook_entry(id) for the full text.


        Human-authored entries are the operator's own observations — weight them above
        your own prior agent entries.
        Args:
            query: Search text; empty lists recent entries.
            author: Optional: restrict to one author.
            limit: Max hits (default 20, most recent).
        """
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return "No logbook is open."
        q = (query or "").lower().strip()
        hits = []
        for i, e in enumerate(model.entries):
            if author and e.get("author", "human") != author:
                continue
            hay = " ".join([e.get("text", ""), e.get("comment", ""),
                            e.get("detail_text", ""), e.get("image_file", "")]).lower()
            if q and q not in hay:
                continue
            snippet = (e.get("text") or e.get("comment") or "").strip().replace("\n", " ")
            hits.append({"id": e.get("id"), "n": i + 1, "author": e.get("author", "human"),
                         "timestamp": e.get("timestamp"),
                         "title": e.get("image_file") or "note",
                         "snippet": snippet[:120]})
        hits = hits[-limit:]   # most recent matches if capped
        return json.dumps({"count": len(hits), "entries": hits}, indent=2)

    @tool(requires=('logbook',), feature="logbook_context")
    def get_logbook_entry(self, entry_id: str) -> str:
        """Return the full text/metadata of one logbook entry by id (image not included;
        has_image flags whether a snapshot exists).

        Args:
            entry_id: The entry id.
        """
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return "No logbook is open."
        e = next((x for x in model.entries if x.get("id") == entry_id), None)
        if e is None:
            return f"No logbook entry with id '{entry_id}'."
        out = {k: e.get(k) for k in ("id", "author", "timestamp", "image_file",
                                     "scan_type", "energy", "text", "comment", "detail_text")}
        out["has_image"] = bool(e.get("snap_file"))
        return json.dumps(out, indent=2)

    @tool()
    def define_scan_from_file(self, file_path: str) -> str:
        """Load the scan definition from an existing .stxm file, to repeat that scan.

        Reads the file's metadata and adopts it as the working scan, so the user can say
        "run that again" (optionally with update_scan() changes) without retyping the
        parameters. Call update_scan() with no arguments afterwards to review what was
        loaded before start_scan().

        Args:
            file_path: path to the existing .stxm file.
        """
        from pystxmcontrol.mcp.utilities import scan_from_stxm
        try:
            loaded = scan_from_stxm(file_path)
        except Exception as e:
            return f"Failed to read a scan from {file_path}: {e}"
        try:
            self._scan = ScanModel(**loaded).model_dump()
        except Exception as e:
            return f"Read {file_path} but its parameters are not a valid scan: {e}"
        return ("Scan definition loaded from " + file_path + ":\n"
                + json.dumps(self._scan, indent=2))

    @tool()
    def plot_motor_positions(self, axis: str, date: str | None = None,
                             start_date: str | None = None, end_date: str | None = None,
                             file_path: str | None = None) -> str:
        """Plot a motor's logged position history and return the saved image path.

        Reads the server's motor-history database, so it answers "was the energy drifting
        overnight?" without a scan. Give a time range one of three ways; a date range wins
        over a single date.

        Args:
            axis: motor name, e.g. 'Energy'.
            date: single date to plot, YYYY-MM-DD (default: today).
            start_date: start of a date range, YYYY-MM-DD.
            end_date: end of a date range, YYYY-MM-DD.
            file_path: where to save the PNG (default: a temporary file).
        """
        from pystxmcontrol.mcp.utilities import plot_motor_positions as _plot
        if self._motors is None:
            self.get_config()
        if self._motors and axis not in self._motors:
            return f"Unknown motor '{axis}'. Call get_config() to see available motors."
        main_cfg = getattr(self._client, "main_config", None) or {}
        db_base_dir = (main_cfg.get("server") or {}).get("data_dir")
        if not db_base_dir:
            return ("No motor-history database directory is configured "
                    "(server.data_dir), so position history cannot be plotted.")
        if file_path is None:
            file_path = os.path.join(tempfile.gettempdir(), f"{axis}_position_plot.png")
        try:
            img = _plot(axis, date=date, start_date=start_date, end_date=end_date,
                        db_base_dir=db_base_dir, file_path=file_path)
        except Exception as e:
            return f"Error generating plot for {axis}: {e}"
        if img and "No data found" in str(img):
            return str(img)
        return f"Saved {axis} position plot to {img}" if img else \
               f"Failed to generate a plot for {axis}"

    def capabilities(self) -> tuple[str, ...]:
        """The capability names this ToolSet can actually satisfy.

        Surfaces pass this to the emitters so a session advertises only tools it can
        run: a headless ToolSet has no frames, so it does not offer find_particles at
        all rather than offering it and failing at call time.
        """
        caps = []
        if frames_available(self._image_model):
            caps.append("frames")
        if self._logbook_model is not None:
            caps.append("logbook")
        if self._confirm_fn.interactive:
            caps.append("approval")
        return tuple(caps)

    def dispatch(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None)
        if fn is None:
            return f"Unknown tool: '{name}'"
        try:
            return fn(**args)
        except TypeError as e:
            return f"Bad arguments for tool '{name}': {e}"


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

# Every @tool-decorated method above, in definition order.  Surfaces advertise a
# filtered view of this: openai_schemas(TOOL_SPECS, have=..., features=...) for the
# task agent's loop, register_mcp(...) for the MCP server.
TOOL_SPECS = specs_for(ToolSet)

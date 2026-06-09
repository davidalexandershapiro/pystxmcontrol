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
import numpy as np
from .scan_model import ScanModel, validate_scan

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    x_start  = scan['x_center'] - scan['x_range'] / 2.0
    x_stop   = scan['x_center'] + scan['x_range'] / 2.0
    x_step   = round((x_stop - x_start) / max(scan['x_points'] - 1, 1), 3)
    y_start  = scan['y_center'] - scan['y_range'] / 2.0
    y_stop   = scan['y_center'] + scan['y_range'] / 2.0
    y_step   = round((y_stop - y_start) / max(scan['y_points'] - 1, 1), 3)
    z_start  = scan['z_center'] - scan['z_range'] / 2.0
    z_stop   = scan['z_center'] + scan['z_range'] / 2.0
    z_step   = round((z_stop - z_start) / max(scan['z_points'] - 1, 1), 3)

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
            x_step = round(r['xRange'] / max(xpts - 1, 1), 4)
            y_step = round(r['yRange'] / max(ypts - 1, 1), 4)
            scan_regions[f'Region{i + 1}'] = {
                'xStart':  r['xCenter'] - r['xRange'] / 2,
                'xStop':   r['xCenter'] + r['xRange'] / 2,
                'xCenter': r['xCenter'], 'xRange': r['xRange'],
                'xPoints': xpts,         'xStep':  x_step,
                'yStart':  r['yCenter'] - r['yRange'] / 2,
                'yStop':   r['yCenter'] + r['yRange'] / 2,
                'yCenter': r['yCenter'], 'yRange': r['yRange'],
                'yPoints': ypts,         'yStep':  y_step,
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
]

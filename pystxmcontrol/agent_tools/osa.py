"""Aligning the order-sorting aperture.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import json
import logging

import numpy as np

from pystxmcontrol.controller.agent_ports import frame_geometry, frames_available
from pystxmcontrol.controller.tool_registry import tool

from .common import (
    _OSA_DEFAULT_VELOCITY_MM_S, _OSA_DWELL_MAX_MS, _OSA_DWELL_MIN_MS, _OSA_X_MOTOR,
    _OSA_Y_MOTOR, _focused_peak_center,
)

log = logging.getLogger(__name__)


class OsaTools:
    """Aligning the order-sorting aperture."""

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

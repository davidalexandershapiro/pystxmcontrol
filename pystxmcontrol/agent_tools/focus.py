"""Focus scans and zone-plate calibration.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import json
import logging


from pystxmcontrol.controller.tool_registry import tool

from .common import _OSA_DEFAULT_VELOCITY_MM_S, _OSA_X_MOTOR, _OSA_Y_MOTOR

log = logging.getLogger(__name__)


class FocusTools:
    """Focus scans and zone-plate calibration."""

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

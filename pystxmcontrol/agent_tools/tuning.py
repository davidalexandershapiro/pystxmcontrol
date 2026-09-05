"""The beamline-tuning search over EPU gap and feedback.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import json
import logging
import time


from pystxmcontrol.controller.tool_registry import tool

from .common import (
    _FEEDBACK_STEP, _GAP_STEP_BY_HARMONIC, _TUNING_MAX_STEPS, _TUNING_MOTORS,
    _TUNING_SETTLE_SECONDS,
)

log = logging.getLogger(__name__)


class TuningTools:
    """The beamline-tuning search over EPU gap and feedback."""

    def _beam_quality_window(self, daq: str, settle_lines: int) -> dict | None:
        """Measure beam quality over the most recently filled scan lines.

        Asks the SERVER for the numbers rather than measuring an assembled image, so
        this works identically in the GUI and out of process — the tuning search was
        otherwise the one workflow an out-of-process agent could not finish.

        Waits until *settle_lines* fresh rows have filled (so the result reflects the
        latest parameter value), the instrument goes idle, or a timeout. The waiting is
        deliberately here and not on the server: the server answers each poll
        immediately, keeping the command socket free for everyone else.
        """
        def _measure():
            try:
                response = self._client.send_message(
                    {"command": "get_beam_quality", "daq": daq, "lines": settle_lines})
            except Exception as e:
                log.debug("get_beam_quality failed: %s", e)
                return None
            return response.get("data") if response and response.get("status") else None

        first = _measure()
        if first is None:
            return None

        start_filled = int(first.get("n_filled_rows", 0))
        nx = int(self._scan.get('x_points', 0) or 0)
        dwell_ms = float(self._scan.get('dwell', 1.0) or 1.0)
        timeout = max(5.0, (dwell_ms / 1000.0) * nx * settle_lines * 3.0)
        deadline = time.monotonic() + timeout
        scan_idle = False
        latest = first

        while time.monotonic() < deadline:
            if int(latest.get("n_filled_rows", 0)) >= start_filled + settle_lines:
                break
            try:
                status = self._client.get_status()
                if status and status.get('mode') == 'idle':
                    scan_idle = True
                    break
            except Exception:
                pass
            time.sleep(0.3)
            measured = _measure()
            if measured is None:
                break
            latest = measured

        latest = dict(latest)
        latest["scan_complete"] = bool(scan_idle)
        return latest

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

    @tool()
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
            return ("No scan data yet — start the tuning scan first, or wait for the "
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

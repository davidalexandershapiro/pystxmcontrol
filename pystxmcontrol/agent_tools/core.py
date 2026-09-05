"""Configuration, safety rules and operator confirmation.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import json
import logging


from pystxmcontrol.controller.scan_model import ScanModel
from pystxmcontrol.controller.tool_registry import tool

from .common import _convert_scan, _motor_summary

log = logging.getLogger(__name__)


class ConfigTools:
    """Configuration, safety rules and operator confirmation."""

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

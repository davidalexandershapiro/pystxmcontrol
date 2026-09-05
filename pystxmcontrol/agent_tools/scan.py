"""Defining, validating, launching and awaiting scans.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import json
import logging
import time

import numpy as np

from pystxmcontrol.controller import energy_presets
from pystxmcontrol.controller.scan_conversion import build_scan_region
from pystxmcontrol.controller.scan_model import ScanModel, validate_scan
from pystxmcontrol.controller.tool_registry import tool

from .common import (
    _ENERGY_MATCH_TOL_EV, _UPDATE_SCAN_SCHEMA, _build_scan_dict, _convert_scan,
    _resolve_scan_type,
)

log = logging.getLogger(__name__)


class ScanTools:
    """Defining, validating, launching and awaiting scans."""

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

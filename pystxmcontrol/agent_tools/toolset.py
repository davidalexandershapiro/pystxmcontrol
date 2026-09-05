"""The agent toolset: one class composed from the per-domain mixins.

Every tool runs on the same session state — the working scan, the cached config,
an active tuning session, the last computed image — so the domains are mixins on
one object rather than separate collaborators. Splitting the state apart would
mean routing it back through a context object for no gain.

What stays here is construction, that shared state, and dispatch. TOOL_SPECS walks
the MRO, so a tool is registered wherever it is defined.
"""

import json
import logging
import time

import numpy as np

from pystxmcontrol.controller.agent_ports import (
    NullFrameSource, approval_or_auto, frame_capabilities, lifecycle_or_null,
)
from pystxmcontrol.controller.scan_model import ScanModel
from pystxmcontrol.controller.tool_registry import openai_schemas, specs_for, tool

from .common import _convert_scan
from .core import ConfigTools
from .motors import MotorTools
from .scan import ScanTools
from .analysis import AnalysisTools
from .tuning import TuningTools
from .beamline import BeamlineTools
from .osa import OsaTools
from .focus import FocusTools
from .rendering import RenderTools
from .logbook import LogbookTools

log = logging.getLogger(__name__)


class ToolSet(ConfigTools, MotorTools, ScanTools, AnalysisTools, TuningTools, BeamlineTools, OsaTools, FocusTools, RenderTools, LogbookTools):
    """Wraps all agent tools with shared client and session state.

    One ToolSet instance is created per agent run.  ``dispatch`` maps tool names to
    methods so the agent loop does not need to know about the individual functions.
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

    def capabilities(self) -> tuple[str, ...]:
        """The capability names this ToolSet can actually satisfy.

        Surfaces pass this to the emitters so a session advertises only tools it can
        run: a headless ToolSet has no frames, so it does not offer find_particles at
        all rather than offering it and failing at call time.
        """
        caps = list(frame_capabilities(self._image_model))
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


# Every @tool-decorated method across the domain mixins, in MRO order.  Surfaces
# advertise a filtered view: openai_schemas(...) for the task agent's loop,
# register_mcp(...) for the MCP server.
TOOL_SPECS = specs_for(ToolSet)

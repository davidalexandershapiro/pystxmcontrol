"""
TaskAgent: proactive, goal-directed instrument control using LLM tool calling.

The agent runs a blocking OpenAI-compatible tool-use loop.  Call run() in a
thread so it does not block the event loop.
"""

import json
import logging
import os
import threading
from typing import Callable, Optional

from .tools import TOOL_SCHEMAS, ToolSet

log = logging.getLogger(__name__)

# Tool calls whose invocation and result are not streamed to the GUI —
# they are setup/plumbing that adds noise without informing the user.
_SILENT_TOOLS: frozenset[str] = frozenset({"get_safety_instructions", "get_config"})

_SYSTEM_PROMPT = """\
You are an AI assistant controlling a scanning transmission X-ray microscope (STXM).
You have access to tools for reading instrument state, moving motors, configuring scans,
and starting acquisitions.

SESSION STARTUP (first user message only):
Call get_safety_instructions() then get_config() once at the start of the session.
Do NOT repeat these calls if you can already see safety rules and config in your history.

Working principles:
- This is a multi-turn conversation. Remember everything said earlier in the thread.
- Confirm critical actions with the user before executing them.
- When the user says "yes" or "ok" or similar, treat it as confirmation of whatever
  you most recently asked them to confirm — do not re-fetch config or re-explain.
- If a tool returns an error, report it and ask how to proceed — do not retry blindly.
- When a scan completes, summarize what was done and any anomalies observed.
- Be concise — the user is a scientist, not a general audience.

SCAN POLLING:
After start_scan() succeeds, call wait_for_scan() once — it blocks internally until
the scan finishes and returns a completion message. Do NOT poll get_scan_status() in
a loop; that wastes iteration budget. When wait_for_scan() returns, call
get_intelligence_recommendations() immediately before proceeding — the intelligence
module may have posted actionable suggestions (e.g. recentre the scan). Act on any
recommendations unless the user has already given explicit contrary instructions.

FINDING ELEMENT-SPECIFIC PARTICLES (e.g. "find particles containing iron"):
This requires elemental contrast, not a single image. Run a two-energy scan (element edge +
pre-edge). When it completes, get_intelligence_recommendations() returns a 'two_energy_particles'
report — the AUTHORITATIVE particle locations, computed from the elemental map. To image them:
load_intelligence_particles() then start_multiregion_scan(). Do NOT use find_particles() to count
or locate an element: it thresholds a single transmission image and finds generic absorbers, which
will disagree with the elemental-map count. Use find_particles() only for plain "absorbing feature"
requests with no element specified.

SCAN LIMITS (before starting any scan):
Call check_scan_limits() before start_scan(). If it reports needs_decision=True, the scan
range exceeds the fine/piezo travel — do NOT just start it. Ask the user whether to run it as
a 'tiled' scan (split into sub-regions, typical for large Image areas) or a 'coarse_only' scan
(coarse stage instead of the piezo), then set their choice with update_scan(tiled=True) or
update_scan(coarse_only=True) and start_scan(). start_scan() enforces this too and will refuse
an oversize scan with no mode set. These are the same options the GUI offers.

SCAN PARAMETERS:
get_config() is called once at session start and is NOT repeated. Its results may be
stale if scans have run since then. When the user asks about recent scan parameters,
or when you need the actual parameters of the last scan, call get_last_scan_params()
— it always fetches fresh data from the server.

BEAMLINE TUNING (e.g. "tune the beamline at 700 eV"):
This is an autonomous hill-climb on two beamline parameters — the EPU gap and the
feedback offset — to a LOCAL optimum. There is no absolute target. read_beam_quality()
reports intensity, noise_RMS, and SNR (= intensity / noise_RMS); which metric you maximize
depends on the search phase (below).
Procedure:
1. start_tuning_session(energy=<eV>). It returns the harmonic, step sizes, the ±10-step
   travel limits, and the current SampleX/Y. Note the SampleX/Y values.
2. Start the tuning scan centred on the sample, small range, fine grid, fast dwell — and
   do NOT wait_for_scan (you measure DURING the scan):
   update_scan(scan_type='Image', x_center=<SampleX>, y_center=<SampleY>, x_range=5,
   y_range=5, x_points=400, y_points=400, dwell=1.0), check_scan_limits(), start_scan().
3. Run THREE search phases in order, each a 1-D line search:
   Phase A — 'gap' maximizing INTENSITY (preliminary, coarse peak in flux).
   Phase B — 'gap' maximizing SNR (refinement; the SNR peak is near, not necessarily at,
             the intensity peak — start from Phase A's optimum and search locally). BEFORE
             starting Phase B, call reanchor_tuning_limit('gap') so the ±10-step window is
             re-centred on Phase A's optimum (gives Phase B a full window in both directions).
   Phase C — 'feedback' maximizing SNR.
   For each phase: take a baseline read_beam_quality(); step_tuning_parameter(parameter, +1),
   re-measure, compare the phase's metric (intensity for A, SNR for B and C). Judge the
   TREND over ~5 readings, not a single one (readings are noisy). Keep going while the metric
   trends up. If no improvement after ~2 steps, reverse direction once. Stop the phase when
   the metric has clearly declined past a peak, or at the ±10-step limit, then step back to
   that phase's best position before moving to the next phase.
4. If read_beam_quality() returns scan_complete=true before the search is done, STOP and
   ask the user whether to start another scan to continue; resume after they confirm.
5. When all three phases are done, call finalize_tuning() (sets the EPU offset from the gap
   delta) and report the optimum gap/feedback, the applied EPU offset, and the before/after
   intensity and SNR.
6. After reporting, ASK the user whether to add/update a beamline-database entry for this
   energy. Only if they agree, call save_beamline_entry(desired_energy=<eV>,
   populate_from_current=True) — the live motor positions already hold the tuned result.
   Do not save without the user's go-ahead.
The step tools enforce the search limits and the ~2 s slow-motor settle for you. The ±10-step
limit is measured from each phase's anchor (reanchor_tuning_limit re-centres it for Phase B);
finalize_tuning's EPU-offset correction always uses the total gap change from session start.

BEAMLINE DATABASE ENTRIES:
You can record the current beamline state into the parameter database at any time on request
(e.g. "save the current beamline settings at 700 eV") with
save_beamline_entry(desired_energy=<eV>, populate_from_current=True). It auto-fills
commanded_energy/harmonic/feedback_offset/epu_offset from the current motor positions; pass
other columns (grating, exit slits, m121/m101 angles, notes) explicitly if the user gives them.
"""


class TaskAgent:
    """Goal-directed instrument control using an OpenAI-compatible LLM.

    Designed to be run in a worker thread.  Call run() with a natural-language
    goal; it blocks until the goal is achieved, the model gives up, or
    max_iterations is reached.
    """

    def __init__(self, main_config: dict, client, image_model=None):
        cfg = main_config.get("task_agent", {})
        self.model = cfg.get("model", "claude-opus-4-7")
        # Steps allowed WITHOUT a scan completing (stall/loop guard); a completed scan resets it.
        self.max_iterations = cfg.get("max_iterations", 20)
        # Absolute ceiling across the whole run, regardless of progress (final safety net).
        self.max_total_iterations = cfg.get("max_total_iterations", 200)
        self._toolset = ToolSet(client, image_model=image_model)
        self._cancel_event = threading.Event()
        self._messages: list[dict] = []  # persists across run() calls

        provider = cfg.get("provider", {})
        api_key_env = provider.get("api_key_env", "OPENAI_API_KEY")
        base_url = provider.get("base_url", None)
        api_key = os.environ.get(api_key_env, "")

        try:
            import openai
        except ImportError:
            raise RuntimeError("openai package is required for TaskAgent — pip install openai")

        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._llm = openai.OpenAI(**kwargs)

    def cancel(self) -> None:
        """Request cancellation. Takes effect between LLM calls."""
        self._cancel_event.set()

    def reset_history(self) -> None:
        """Clear conversation history so the next run() starts a fresh session."""
        self._messages = []

    def run(self, goal: str, publish_fn: Optional[Callable[[str], None]] = None) -> str:
        """Execute a goal using the tool-use loop.  Blocks until done.

        :param goal: Natural-language goal for the agent.
        :param publish_fn: Optional callable; receives status strings during execution.
        :return: Final text response from the model.
        """

        def _publish(msg: str) -> None:
            log.info("[TaskAgent] %s", msg)
            if publish_fn:
                publish_fn(msg)

        self._cancel_event.clear()

        # Seed history with the system prompt on the very first turn
        if not self._messages:
            self._messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # Drain any pending intelligence recommendations and prepend them to the
        # user message so the agent has context regardless of when they arrived.
        image_model = self._toolset._image_model
        if image_model is not None:
            pending = list(image_model.get("pending_recommendations") or [])
            if pending:
                image_model.set("pending_recommendations", [])
                recs_json = json.dumps({"intelligence_recommendations": pending}, indent=2)
                goal = (
                    f"[The intelligence module has posted the following recommendations "
                    f"based on the last scan]\n{recs_json}\n\n{goal}"
                )

        self._messages.append({"role": "user", "content": goal})

        # Progress-aware budget: `max_iterations` bounds steps WITHOUT a scan completing
        # (catches stalls/loops), while `max_total_iterations` is an absolute safety ceiling.
        # A completed scan resets the stall counter, so legitimately long jobs (tiled scans,
        # particle searches) can run many scans in sequence without exhausting the budget.
        total = 0
        stalled = 0
        while True:
            if self._cancel_event.is_set():
                _publish("[Cancelled]")
                return "Task cancelled by user."
            if total >= self.max_total_iterations:
                msg = (f"Reached the absolute iteration ceiling ({self.max_total_iterations}). "
                       "Stopping. If the task was still making progress, tell me to continue.")
                _publish(msg)
                return msg
            if stalled >= self.max_iterations:
                msg = (f"No scan completed in the last {self.max_iterations} steps — stopping to "
                       "avoid a loop. If more work remains, tell me to continue.")
                _publish(msg)
                return msg
            total += 1
            stalled += 1
            try:
                response = self._llm.chat.completions.create(
                    model=self.model,
                    tools=TOOL_SCHEMAS,
                    messages=self._messages,
                )
            except Exception as e:
                msg = f"LLM call failed: {e}"
                _publish(msg)
                return msg

            choice = response.choices[0]
            finish_reason = choice.finish_reason
            assistant_message = choice.message

            # Append to persistent history
            self._messages.append(assistant_message)

            if finish_reason == "tool_calls":
                for tool_call in assistant_message.tool_calls:
                    name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    args_summary = ", ".join(f"{k}={v!r}" for k, v in args.items())
                    if name not in _SILENT_TOOLS:
                        _publish(f"Tool: {name}({args_summary})")

                    result = self._toolset.dispatch(name, args)
                    if name not in _SILENT_TOOLS:
                        truncated = result[:200] + ("..." if len(result) > 200 else "")
                        _publish(f"  → {truncated}")

                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                    # A completed scan is a unit of real progress: reset the stall budget so a
                    # long sequence of scans (e.g. a tiled scan) isn't capped by step count.
                    if name == "wait_for_scan" and result.startswith("Scan complete"):
                        stalled = 0
                        _publish("  [scan completed — step budget reset]")

            else:
                # Model is done — return final text; displayed via task_agent_done signal
                final = assistant_message.content or ""
                _publish(f"[Done in {total} step(s)]")
                return final

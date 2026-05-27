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
a loop; that wastes iteration budget. When wait_for_scan() returns, immediately
proceed with the next step of the task without waiting for user input.
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
        self.max_iterations = cfg.get("max_iterations", 20)
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

        self._messages.append({"role": "user", "content": goal})

        for iteration in range(self.max_iterations):
            if self._cancel_event.is_set():
                _publish("[Cancelled]")
                return "Task cancelled by user."
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

            else:
                # Model is done — return final text; displayed via task_agent_done signal
                final = assistant_message.content or ""
                _publish(f"[Done in {iteration + 1} step(s)]")
                return final

        timeout_msg = (
            f"Reached maximum iterations ({self.max_iterations}) without completing goal."
        )
        _publish(timeout_msg)
        return timeout_msg

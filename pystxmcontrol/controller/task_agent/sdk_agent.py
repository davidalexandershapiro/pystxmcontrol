"""
SDKAgent: a Claude Code backend for the Agent tab, using the Claude Agent SDK.

This is a *prototype* alternative to TaskAgent (agent.py).  It exposes the same
run()/cancel()/is_cancelled()/reset_history() surface, so the existing
TaskAgentThread and the controller's confirm_fn / signal wiring drive it with no
changes — the only switch is which backend the controller instantiates.

Where TaskAgent runs a hand-rolled OpenAI tool loop over the curated ToolSet,
SDKAgent runs Claude Code headless in-process: it gets the STXM instrument tools
from the `pystxm` MCP server (.mcp.json) PLUS Claude Code's own coding tools
(Read/Grep/Bash/Edit), so this is the staff developer/troubleshooting agent.

Rendering contract (matches TaskAgent so AgentApp needs no changes):
  * tool calls are published as "Tool: name(args)" trace lines via publish_fn
  * the final assistant text is returned from run() (shown as the answer bubble)

Permission contract:
  * read-only tools (AUTO_ALLOW) run without prompting
  * everything else — Bash/Edit/Write and the hardware MCP tools
    (move_motor, stxm_scan) — routes through confirm_fn, i.e. the operator's
    Approve/Decline card, exactly like TaskAgent's request_confirmation.

Known prototype limitation: scans launched here go through the out-of-process
MCP server, so the GUI does NOT get the on_scan_started callback and will not
buffer the scan for the analysis/intelligence tools.  That is the out-of-process
tradeoff discussed for tier-2 unification; fine for a spike.
"""

import asyncio
import json
import logging
import os
import threading
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Tools that run without an Approve/Decline prompt: read-only STXM MCP tools and
# Claude Code's own read tools.  Anything not listed here (Bash, Edit, Write, and
# the hardware MCP tools move_motor / stxm_scan) is gated through confirm_fn.
AUTO_ALLOW: frozenset[str] = frozenset({
    # Claude Code built-in read tools
    "Read", "Grep", "Glob", "LS", "TodoWrite", "NotebookRead", "WebFetch", "WebSearch",
    # pystxm MCP read / no-hardware tools (namespaced mcp__<server>__<tool>)
    "mcp__pystxm__get_safety_instructions", "mcp__pystxm__get_config",
    "mcp__pystxm__get_motor_position", "mcp__pystxm__plot_motor_positions",
    "mcp__pystxm__connect_to_server", "mcp__pystxm__update_scan",
    "mcp__pystxm__define_scan_from_file",
})

_SYSTEM_PROMPT = """\
You are a staff developer assistant for a scanning transmission X-ray microscope (STXM).
You have two kinds of tools:
  - STXM instrument tools from the `pystxm` MCP server (motors, scans, config).
  - Claude Code coding tools (Read, Grep, Bash, Edit) for script development and troubleshooting.

Instrument rules:
- To reach the control server, call connect_to_server() with NO arguments — the address is
  resolved automatically from the instrument config. Do not pass 127.0.0.1.
- Read-only queries (positions, config) run freely. Moving a motor or starting a scan will ask
  the operator for approval — explain what you are about to do before you trigger it.
- Never move OSA_Z. Energy moves over ~100 eV and rotations over ~5 deg need explicit confirmation.
Be concise — the user is a scientist.
"""


def _fmt(value) -> str:
    """Compact one-line rendering of a tool-input dict for the trace line."""
    try:
        if isinstance(value, dict):
            return ", ".join(f"{k}={v!r}" for k, v in value.items())
        return str(value)
    except Exception:
        return str(value)


class SDKAgent:
    """Claude Code backend with the same call surface as TaskAgent.

    :param main_config: the server main_config dict (for task_agent settings).
    :param project_dir: dir holding .mcp.json and .claude/settings.json.
    :param confirm_fn: confirm_fn(request:{summary,details}) -> bool; the GUI's
        Approve/Decline gate (shared with TaskAgent).
    :param dev_dir: working directory (dev checkout); defaults to project_dir.
    """

    def __init__(self, main_config: dict, project_dir: str,
                 confirm_fn: Optional[Callable[[dict], bool]] = None,
                 dev_dir: Optional[str] = None, **_ignored):
        cfg = (main_config or {}).get("task_agent", {})
        # NOTE: task_agent.model is the id for the OpenAI-compatible endpoint the
        # TaskAgent backend uses (e.g. "claude-opus" on CBORG) and is NOT a valid
        # Claude Code model. Use a dedicated task_agent.sdk_model (a Claude Code
        # alias like "opus"/"sonnet" or a full id like "claude-opus-4-8"); when
        # unset, pass None so the SDK/CLI uses its own configured default.
        self.model = cfg.get("sdk_model") or None
        self._project_dir = project_dir
        self._dev_dir = dev_dir or project_dir
        self._confirm_fn = confirm_fn

        self._mcp_config = os.path.join(project_dir, ".mcp.json")
        self._settings = os.path.join(project_dir, ".claude", "settings.json")
        # main.json path for the MCP server to resolve the control-server address
        # (mirrors the env in .mcp.json; harmless if that already sets it).
        self._main_json = os.path.join(
            (main_config or {}).get("_prefix", os.sys.prefix), "pystxmcontrol_cfg", "main.json")

        self._cancel_event = threading.Event()
        self._started = False          # drives continue_conversation for multi-turn
        self._loop = None              # the run()'s event loop (for thread-safe interrupt)
        self._client = None            # the live ClaudeSDKClient (for interrupt)

    # ── TaskAgent-compatible surface ──────────────────────────────────────────
    def cancel(self) -> None:
        """Request cancellation; interrupts the live SDK client if one is running."""
        self._cancel_event.set()
        loop, client = self._loop, self._client
        if loop is not None and client is not None:
            try:
                loop.call_soon_threadsafe(lambda: asyncio.ensure_future(client.interrupt()))
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def reset_history(self) -> None:
        """Start a fresh conversation on the next run()."""
        self._started = False

    def set_last_gui_scan(self, scan_config: dict) -> None:
        """No-op: the SDK backend does not maintain an in-process scan baseline
        (scans go through the MCP server).  Present for interface parity."""
        return

    def run(self, goal: str, publish_fn: Optional[Callable[[str], None]] = None) -> str:
        """Blocking entry point (called on TaskAgentThread).  Runs one turn."""
        def _publish(msg: str) -> None:
            log.info("[SDKAgent] %s", msg)
            if publish_fn:
                publish_fn(msg)

        self._cancel_event.clear()
        try:
            return asyncio.run(self._arun(goal, _publish))
        except Exception as e:
            log.exception("SDKAgent run failed")
            return f"Claude Code backend error: {type(e).__name__}: {e}"

    # ── async driver ──────────────────────────────────────────────────────────
    async def _arun(self, goal: str, publish: Callable[[str], None]) -> str:
        from claude_agent_sdk import (
            ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage,
            ToolUseBlock, ResultMessage, PermissionResultAllow, PermissionResultDeny,
        )

        self._loop = asyncio.get_event_loop()

        async def can_use_tool(name, tool_input, ctx):
            # Read-only tools run silently; everything else asks the operator.
            if name in AUTO_ALLOW:
                return PermissionResultAllow()
            if self._confirm_fn is None:
                return PermissionResultAllow()
            request = {
                "summary": f"Allow Claude Code to run: {name}?",
                "details": _fmt(tool_input),
            }
            # confirm_fn blocks (Qt Event); run it off the event loop so streaming
            # and interrupts stay responsive while the card is up.
            approved = await self._loop.run_in_executor(None, self._confirm_fn, request)
            if approved:
                return PermissionResultAllow()
            return PermissionResultDeny(message="Declined by operator")

        options = ClaudeAgentOptions(
            cwd=self._dev_dir,
            mcp_servers=self._mcp_config,          # reuse the project's .mcp.json
            strict_mcp_config=True,                # ignore the operator's personal MCP servers
            settings=self._settings if os.path.isfile(self._settings) else None,
            setting_sources=["project"],
            permission_mode="default",
            system_prompt=_SYSTEM_PROMPT,
            can_use_tool=can_use_tool,
            continue_conversation=self._started,   # multi-turn continuity across run() calls
            env={"PYSTXM_MAIN_JSON": self._main_json} if os.path.isfile(self._main_json) else {},
            model=self.model,
        )

        final = ""
        async with ClaudeSDKClient(options) as client:
            self._client = client
            await client.query(goal)
            async for msg in client.receive_response():
                if self._cancel_event.is_set():
                    try:
                        await client.interrupt()
                    except Exception:
                        pass
                    break
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, ToolUseBlock):
                            publish(f"Tool: {block.name}({_fmt(block.input)})")
                elif isinstance(msg, ResultMessage):
                    if msg.result:
                        final = msg.result

        self._client = None
        self._started = True
        return final or "(no response)"

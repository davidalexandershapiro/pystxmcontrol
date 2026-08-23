"""
Read-only entrypoint for the STXM MCP server.

Sets ``PYSTXM_MCP_READONLY`` before the server module is imported, so the
hardware-mutating tools (``move_motor``, ``stxm_scan``) are never registered and
are invisible to the agent.  Read/query tools and scan-config building remain
available — the intended surface for general users writing acquisition scripts.

Run with::

    python -m pystxmcontrol.mcp.readonly

This relies on ``pystxmcontrol.mcp.__init__`` importing ``server`` lazily inside
``main()``; do not import ``pystxmcontrol.mcp.server`` before setting the env var.
"""

import os

os.environ["PYSTXM_MCP_READONLY"] = "1"

from pystxmcontrol.mcp import main  # noqa: E402 — must follow the env assignment

main()

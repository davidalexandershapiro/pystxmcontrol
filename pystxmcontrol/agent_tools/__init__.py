"""Instrument-control tools shared by the GUI task agent and the MCP server.

Each public method on ToolSet is callable by an LLM: they accept plain Python types
and return strings.  What each surface advertises is derived from the @tool decorators
rather than hand-written per surface — see controller/tool_registry.

The tools live in per-domain mixins (scan, motors, analysis, tuning, osa, focus,
logbook, beamline, rendering, core) that ToolSet composes, because they all run on one
piece of session state.  Import ToolSet from here, not from a domain module.
"""

from pystxmcontrol.controller.scan_model import ScanModel

from .common import _UPDATE_SCAN_SCHEMA, _build_scan_dict, _convert_scan
from .toolset import TOOL_SPECS, ToolSet

__all__ = ["TOOL_SPECS", "ToolSet", "ScanModel"]

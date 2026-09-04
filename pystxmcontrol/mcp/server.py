"""MCP surface over the shared agent toolset.

This server used to carry its own copies of the instrument tools, written against
``scripter`` while the GUI task agent's copies were written against ``stxm_client``.
The copies had drifted in ways that mattered at the beamline: the MCP ``update_scan``
re-seeded from ``lastScan`` on every call and so discarded the previous call's edits,
and ``stxm_scan`` ran no scan-limit check and never moved Energy to a single-energy
scan's configured energy, so a scan set up for 708 eV ran at whatever energy the
motor happened to sit at.

Both surfaces now advertise the SAME tool implementations, filtered by what each can
do (see controller/tool_registry).  Out of process there is no live image model, no
logbook and no operator confirmation dialog, so the frame/logbook/approval tools are
not advertised here at all rather than offered and failing when called.

Read-only mode (``PYSTXM_MCP_READONLY``, or ``python -m pystxmcontrol.mcp.readonly``)
drops every tool declared ``mutates_hardware``, so general users can read state and
build scan configurations but cannot move motors or start acquisitions.
"""

import json
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from pystxmcontrol.controller.instrument_client import ScripterClient
from pystxmcontrol.controller.remote_frames import RemoteFrameSource
from pystxmcontrol.controller.scripter import scripter
from pystxmcontrol.controller.task_agent.tools import TOOL_SPECS, ToolSet
from pystxmcontrol.controller.tool_registry import register_mcp

log = logging.getLogger(__name__)

mcp = FastMCP("pystxmcontrol-mcp")

READONLY = os.environ.get("PYSTXM_MCP_READONLY", "").strip().lower() in ("1", "true", "yes", "on")

# No open logbook and no way to ask the operator out of process, so those tools stay
# unadvertised.  What this surface CAN serve comes from its RemoteFrameSource and is
# discovered per connection (see _build_toolset), because it depends on whether the
# intelligence stream could be reached.
FEATURES: tuple[str, ...] = ()

# Built on first use by _toolset().
_TOOLSET: ToolSet | None = None


def _default_server() -> tuple[str, int]:
    """The control server (host, port) to use when none is given explicitly.

    Priority: PYSTXM_SERVER_HOST/PORT, then the ``server`` block of the installed
    main.json (via PYSTXM_MAIN_JSON, else this environment's prefix), then localhost.
    Reading main.json is what lets an agent just say "connect" and reach the real
    instrument instead of hanging on a localhost default.
    """
    host = os.environ.get("PYSTXM_SERVER_HOST")
    if host:
        return host, int(os.environ.get("PYSTXM_SERVER_PORT") or 9999)

    for path in (os.environ.get("PYSTXM_MAIN_JSON"),
                 os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json")):
        if path and os.path.isfile(path):
            try:
                with open(path) as f:
                    srv = json.load(f).get("server", {})
                return srv.get("stxm_address", "127.0.0.1"), int(srv.get("command_port", 9999))
            except Exception:
                pass
    return "127.0.0.1", 9999


def _build_toolset(host: str, port: int) -> ToolSet:
    """Connect to *host*:*port* and build a ToolSet on it.

    The config read is not just a warm-up: it is what verifies the connection (a dead
    server raises here rather than at the first tool call), it tells us which port the
    scan-data stream is on, and ToolSet seeds its working scan from the cached config
    when it is constructed, so it has to happen first.
    """
    client = ScripterClient(scripter(host, port))
    client.get_config()

    frames = RemoteFrameSource()
    data_port = ((client.main_config or {}).get("server") or {}).get("stxm_data_port")
    if data_port:
        # The intelligence module publishes its recommendations here as a scan runs.
        # Failing to subscribe must not stop the server coming up: the rest of the
        # tools work without it, and the registry simply will not advertise the ones
        # that need it.
        try:
            frames.start_recommendations(host, int(data_port))
        except Exception as e:
            log.warning("could not subscribe to the intelligence stream at %s:%s: %s",
                        host, data_port, e)
    else:
        log.warning("no server.stxm_data_port in the config; intelligence "
                    "recommendations will not be available")
    return ToolSet(client, image_model=frames)


def _toolset() -> ToolSet:
    """The shared ToolSet, connected on first use.

    Lazy so that starting the server never blocks on the instrument, and so a tool
    called before connect_to_server() still works instead of failing on an unset
    global — the "forgot to connect" class of failure this server used to have.
    """
    global _TOOLSET
    if _TOOLSET is None:
        _TOOLSET = _build_toolset(*_default_server())
    return _TOOLSET


@mcp.tool()
def connect_to_server(host: str = None, port: int = None) -> str:
    """Connect to a pystxmcontrol control server and read its configuration.

    Call with NO arguments to use the configured instrument — the address comes from
    the installed main.json. Do not pass 127.0.0.1 unless the user explicitly asks for
    a local server. Every other tool connects on demand, so this is only needed to
    point at a different server or to check that the instrument is reachable.

    Args:
        host: server address (default: from main.json).
        port: command port (default: from main.json).
    """
    global _TOOLSET
    d_host, d_port = _default_server()
    host, port = host or d_host, port or d_port
    try:
        _TOOLSET = _build_toolset(host, port)
    except TimeoutError as e:
        return (f"Connection to {host}:{port} timed out — the control server may not be "
                f"running or responding. Error: {e}")
    except Exception as e:
        return f"Failed to connect to {host}:{port}. Error: {type(e).__name__}: {e}"
    motors = list((_TOOLSET._motors or {}).keys())
    return (f"Connected to {host}:{port}. {len(motors)} motors: "
            f"{', '.join(motors[:5])}{'...' if len(motors) > 5 else ''}. "
            "Call get_safety_instructions() before operating the instrument.")


# The instrument tools themselves are the shared ones; this is the only place that
# decides which of them this surface advertises.
# Advertise everything this surface could serve once connected.  Registration happens
# at import, before any connection exists, so the capability set cannot be read off a
# live ToolSet — it is what a successful connection yields.
CAPABILITIES: tuple[str, ...] = ("recommendations",)

REGISTERED = register_mcp(mcp, _toolset, TOOL_SPECS,
                          have=CAPABILITIES, features=FEATURES, readonly=READONLY)

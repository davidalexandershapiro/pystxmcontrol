"""Parity between the two agent surfaces: the task agent's ToolSet and the MCP server.

The two grew on separate development paths and were joined later. They cannot be merged —
ToolSet's tools need GUI collaborators (operator confirmation, the live image model, the
logbook) that an out-of-process MCP server has no counterpart for — so what keeps them in
step is the shared domain layer beneath them plus this test.

These tests fail when a capability lands on one surface and not the other, or when the
shared conversion is forked back into per-surface copies. That is the whole point: drift
should break a test here rather than surface at the beamline.
"""

import inspect
import json
import pathlib
import re
import sys

import pytest

from pystxmcontrol.controller import scan_conversion as sc
from pystxmcontrol.controller.scan_model import ScanModel
from pystxmcontrol.controller import agent_ports as ap
from pystxmcontrol.controller import tool_registry as tr
from pystxmcontrol.controller import instrument_client as ic
from pystxmcontrol.controller.task_agent import tools as agent_tools

# The MCP server imports fastmcp, which is an optional extra.  Skip only the classes that
# actually need it — the shared-layer tests below must still run in an env without the
# extra, which is where most of this repo's development happens.
try:
    import pystxmcontrol.mcp.server as mcp_server
    import pystxmcontrol.mcp.utilities as stxm_utils
except ImportError:                                  # pragma: no cover - env-dependent
    mcp_server = stxm_utils = None

needs_mcp = pytest.mark.skipif(mcp_server is None, reason="mcp extra not installed")

# client.py imports PySide6 at module scope; the MCP-side env has no GUI stack.
try:
    import PySide6  # noqa: F401
    _HAS_GUI = True
except ImportError:                                  # pragma: no cover - env-dependent
    _HAS_GUI = False
needs_gui = pytest.mark.skipif(not _HAS_GUI, reason="PySide6 not installed")


ALL_CAPABILITIES = ("frames", "logbook", "approval")
ALL_FEATURES = ("logbook_context",)


def agent_schemas():
    """Every tool the agent can advertise, generated from the registry."""
    return tr.openai_schemas(agent_tools.TOOL_SPECS,
                             have=ALL_CAPABILITIES, features=ALL_FEATURES)


def agent_schema(name):
    for schema in agent_schemas():
        if schema["function"]["name"] == name:
            return schema["function"]
    raise AssertionError(f"No agent tool schema named {name!r}")


class TestOneScanModel:
    """Both surfaces must validate scans against the same model."""

    def test_agent_and_scripter_share_the_model(self):
        from pystxmcontrol.controller import scripter as scripter_mod
        assert agent_tools.ScanModel is ScanModel
        assert scripter_mod.ScanModel is ScanModel

    def test_no_second_scan_model_module(self):
        """task_agent.scan_model was a near-copy that had already drifted (it alone
        carried tiled/coarse_only). It must not come back."""
        with pytest.raises(ImportError):
            __import__("pystxmcontrol.controller.task_agent.scan_model")

    def test_large_scan_flags_present(self):
        m = ScanModel()
        assert m.tiled is False and m.coarse_only is False


@needs_mcp
class TestOneConverter:
    """A scan read back from the server must mean the same thing on both paths."""

    def test_same_function(self):
        assert stxm_utils.convert_scan(_SERVER_SCAN) == agent_tools._convert_scan(_SERVER_SCAN)

    def test_multi_region_survives_on_both(self):
        for convert in (stxm_utils.convert_scan, agent_tools._convert_scan):
            flat = convert(_SERVER_SCAN)
            assert [r["dwell"] for r in flat["energy_regions"]] == [1.0, 3.0]

    def test_agent_build_uses_shared_energy_builder(self):
        """_build_scan_dict must not re-derive energy regions locally."""
        scan = ScanModel(energy_regions=[
            {"start": 280.0, "stop": 282.0, "n_energies": 5, "dwell": 1.0},
            {"start": 284.0, "stop": 290.0, "n_energies": 13, "dwell": 3.0},
        ]).model_dump()
        built = agent_tools._build_scan_dict(scan, {})
        assert built["energy_regions"] == sc.build_energy_regions(scan)
        assert built["energy_list"] is None      # would override the regions server-side


class TestEnergyPresetParity:
    """Energy presets were the feature the shared layer was first built for.

    The original form of this class checked that the task agent and the MCP server had
    each grown the feature. There is one implementation now, so the question changed:
    what matters is that the MCP surface actually ADVERTISES it, and that the
    update_scan override still describes real fields.
    """

    def test_both_surfaces_advertise_energy_presets(self):
        gui = {s["function"]["name"] for s in agent_schemas()}
        assert "list_energy_presets" in gui
        if mcp_server is not None:
            assert "list_energy_presets" in mcp_server.REGISTERED

    def test_update_scan_accepts_energy_preset_on_both(self):
        assert "energy_preset" in agent_schema("update_scan")["parameters"]["properties"]
        assert "energy_preset" in agent_tools._UPDATE_SCAN_SCHEMA["properties"]

    def test_agent_schema_fields_are_scan_model_fields(self):
        """Every documented update_scan parameter must be something the model accepts,
        so an agent cannot be told about a field that silently does nothing."""
        documented = set(agent_schema("update_scan")["parameters"]["properties"])
        documented.discard("energy_preset")       # resolved into energy_regions
        assert documented <= set(ScanModel.model_fields)


@needs_mcp
class TestMcpServesTheSharedTools:
    """The MCP server advertises the shared implementations, not its own copies.

    These are the divergences that used to bite at the beamline; each is asserted
    through the real MCP call path rather than by calling ToolSet directly.
    """

    def _server(self):
        import asyncio
        srv = mcp_server
        srv._TOOLSET = agent_tools.ToolSet(ic.ScripterClient(_ConfiguredScripter()))
        return srv, asyncio

    def test_no_forked_tool_implementations_remain(self):
        """The server's own update_scan / get_config / move_motor / stxm_scan are gone."""
        for gone in ("update_scan", "get_config", "get_motor_position",
                     "move_motor", "stxm_scan", "check_motor_status"):
            assert not hasattr(mcp_server, gone), gone
        assert callable(mcp_server.connect_to_server)      # bootstrap stays

    def test_advertises_only_what_it_can_satisfy(self):
        names = set(mcp_server.REGISTERED)
        assert {"update_scan", "start_scan", "move_motor"} <= names
        # No live frames, no logbook, no operator dialog out of process.
        assert not ({"find_particles", "add_to_logbook", "request_confirmation"} & names)

    def test_update_scan_advertises_real_parameters(self):
        """FastMCP turns a **kwargs function into one bogus required string named
        'kwargs'; the registry's schema is used instead."""
        srv, asyncio = self._server()
        tool = next(t for t in asyncio.run(srv.mcp.list_tools()) if t.name == "update_scan")
        props = tool.inputSchema["properties"]
        assert "kwargs" not in props and len(props) > 20
        assert props["x_center"]["description"] == "µm"     # units survive

    def test_successive_update_scan_calls_accumulate(self):
        """The old MCP update_scan re-seeded from lastScan every call, silently
        discarding the previous call's edits."""
        srv, asyncio = self._server()
        asyncio.run(srv.mcp.call_tool("update_scan", {"x_range": 12.0}))
        out = asyncio.run(srv.mcp.call_tool("update_scan", {"dwell": 3.0}))
        scan = json.loads(_text(out).split("Scan updated: ", 1)[1])
        assert scan["x_range"] == 12.0 and scan["dwell"] == 3.0

    def test_scan_limits_are_enforced(self):
        """The old stxm_scan ran no limit check at all."""
        srv, asyncio = self._server()
        asyncio.run(srv.mcp.call_tool("update_scan", {"x_range": 900.0}))
        assert "exceeds" in _text(asyncio.run(srv.mcp.call_tool("start_scan", {})))

    def test_energy_is_moved_before_a_single_energy_scan(self):
        """The old stxm_scan never moved Energy, so a scan configured for 708 eV ran
        at whatever energy the motor was sitting at."""
        srv, asyncio = self._server()
        scripter = srv._TOOLSET._client._scripter
        asyncio.run(srv.mcp.call_tool("update_scan", {
            "x_range": 12.0, "energy_start": 708.0, "energy_stop": 708.0}))
        asyncio.run(srv.mcp.call_tool("start_scan", {}))
        assert {"command": "moveMotor", "axis": "Energy", "pos": 708.0} in scripter.sock.sent

    def test_safety_text_does_not_name_an_unavailable_tool(self):
        """request_confirmation is not advertised here, so the instructions must not
        tell the agent to call it."""
        srv, asyncio = self._server()
        text = _text(asyncio.run(srv.mcp.call_tool("get_safety_instructions", {})))
        assert "request_confirmation" not in text
        assert "no confirmation tool" in text

    def test_readonly_mode_hides_every_hardware_tool(self):
        """Not advertised at all, which is stronger than a permission rule."""
        readonly = tr.register_mcp(_NullMcp(), lambda: None, agent_tools.TOOL_SPECS,
                                   readonly=True)
        mutating = {s.name for s in agent_tools.TOOL_SPECS if s.mutates_hardware}
        assert not (set(readonly) & mutating)
        assert "update_scan" in readonly and "get_config" in readonly


def _text(result):
    content = result[0] if isinstance(result, tuple) else result
    return content[0].text


class _NullMcp:
    """Collects registrations without a real FastMCP server."""

    def __init__(self):
        self._tools = {}
        self._tool_manager = self

    def tool(self, name=None, description=None):
        def deco(fn):
            self._tools[name] = type("T", (), {"parameters": None})()
            return fn
        return deco

    def get_tool(self, name):
        return self._tools[name]


class _ConfiguredScripter:
    """A scripter whose fake server answers get_config with a usable instrument."""

    MOTORS = None

    CONFIG_TUPLE = (
        {"SampleX": {"minValue": -50.0, "maxValue": 50.0},
         "SampleY": {"minValue": -50.0, "maxValue": 50.0}, "Energy": {}},
        {"Image": {"driver": "derived_line_image", "mode": "continuousLine"}},
        {"SampleX": 0.0, "SampleY": 0.0, "Energy": 700.0},
        {"default": {}}, {"lastScan": {}})

    def __init__(self):
        self.sock = _ReplyingSock(self.CONFIG_TUPLE)
        self.get_config_calls = 0

    def get_config(self):
        self.get_config_calls += 1
        return self.CONFIG_TUPLE


class _ReplyingSock:
    """Answers whatever command it was last sent, recording everything."""

    def __init__(self, config_tuple):
        self.sent, self._config = [], config_tuple

    def send_pyobj(self, msg):
        self.sent.append(msg)

    def recv_pyobj(self):
        command = self.sent[-1].get("command")
        if command == "get_config":
            return {"status": True, "data": self._config}
        if command == "getMotorPositions":
            return {"status": True, "data": {"SampleX": 0.0, "Energy": 700.0}}
        return {"status": True, "data": "ok"}


class TestCollaboratorPorts:
    """The optional collaborators are ports with headless stand-ins.

    The tools must never test them for None again: absent ones read empty and write
    nowhere. What must NOT collapse is the operator-facing distinction between "no live
    frames in this session" and "no scan has run yet" — confusing those sends the
    operator chasing a scan that cannot help.
    """

    def test_ports_module_is_headless(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; import pystxmcontrol.controller.agent_ports; "
             "assert 'PySide6' not in sys.modules; print('clean')"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "clean" in r.stdout

    def test_no_none_checks_left_in_tools(self):
        """The whole point of the null implementations: the guards are gone."""
        source = pathlib.Path(agent_tools.__file__).read_text()
        assert not re.search(r"_image_model is (?:not )?None", source)
        assert not re.search(r"_confirm_fn is (?:not )?None", source)
        assert not re.search(r"_on_scan_started is (?:not )?None", source)

    def test_null_frame_source_reads_empty_writes_nowhere(self):
        f = ap.NullFrameSource()
        assert f.get("all_detector_images") is None
        assert f.get("scan_type", "") == ""
        f.set("pending_alarms", [1, 2, 3])         # must not raise
        assert f.get("pending_alarms") is None      # and must not remember

    def test_frames_available_distinguishes_the_two_absences(self):
        assert ap.frames_available(ap.NullFrameSource()) is False
        assert ap.frames_available(_DictFrames()) is True

    def test_frame_geometry_defaults_ranges_to_one(self):
        """Ranges are divisors in pixel->um conversion; 0.0 would divide by zero."""
        assert ap.frame_geometry(ap.NullFrameSource()) == (0.0, 0.0, 1.0, 1.0)
        frames = _DictFrames({"x_center": 3.0, "y_center": -2.0,
                              "x_range": 10.0, "y_range": 5.0})
        assert ap.frame_geometry(frames) == (3.0, -2.0, 10.0, 5.0)

    def test_toolset_normalises_absent_collaborators(self):
        ts = agent_tools.ToolSet(_FakeClient())
        assert isinstance(ts._image_model, ap.NullFrameSource)
        assert isinstance(ts._confirm_fn, ap.AutoApprove)
        assert isinstance(ts._on_scan_started, ap.NullScanLifecycle)

    def test_headless_approval_says_it_could_not_ask(self):
        """AutoApprove must not pass itself off as a real operator approval."""
        ts = agent_tools.ToolSet(_FakeClient())
        result = ts.request_confirmation("move Energy to 708 eV")
        assert result.startswith("APPROVED")
        assert "no interactive confirmation UI" in result

    def test_gui_approval_is_still_honoured(self):
        for approved, expected in ((True, "APPROVED"), (False, "DECLINED")):
            ts = agent_tools.ToolSet(_FakeClient(), confirm_fn=lambda req: approved)
            assert ts.request_confirmation("do the thing").startswith(expected)

    def test_declined_approval_reports_the_decline(self):
        ts = agent_tools.ToolSet(_FakeClient(), confirm_fn=lambda req: False)
        assert "Do NOT proceed" in ts.request_confirmation("risky")

    def test_approval_failure_declines_rather_than_proceeds(self):
        def boom(req):
            raise RuntimeError("dialog died")
        ts = agent_tools.ToolSet(_FakeClient(), confirm_fn=boom)
        assert ts.request_confirmation("x").startswith("DECLINED")

    def test_frameless_tools_explain_the_absence(self):
        """Not 'run a scan first' — that scan would not help in this session."""
        ts = agent_tools.ToolSet(_FakeClient())
        for result in (ts.get_last_scan_stats(), ts.find_particles(),
                       ts.get_intelligence_recommendations()):
            assert result == "Image model not available."

    def test_null_lifecycle_does_not_block_a_scan(self):
        """A headless start_scan must still reach the server."""
        client = _FakeClient()
        ts = agent_tools.ToolSet(client)
        ts._scans_config = {"Image": {"driver": "derived_line_image",
                                      "mode": "continuousLine"}}
        ts._motors = {"SampleX": {"minValue": -50.0, "maxValue": 50.0},
                      "SampleY": {"minValue": -50.0, "maxValue": 50.0},
                      "Energy": {}}
        # Already at the scan energy, so start_scan's pre-move is skipped.
        client.positions = {"Energy": ScanModel().energy_start}
        assert "Scan started" in ts.start_scan()
        assert any(m.get("command") == "scan" for m in client.sent)


class _DictFrames:
    """A live FrameSource backed by a plain dict (what ImageModel is, minus Qt)."""

    def __init__(self, data=None):
        self._d = dict(data or {})

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value


class TestOneScanBuilder:
    """One builder for every outbound scan, on both surfaces.

    scripter.stxm_scan used to build scan_regions inline with step = range/(points-1)
    and no half-pixel inset, so an MCP-launched scan came out one pixel larger than the
    same scan from the GUI. Both paths now go through scan_conversion.build_server_scan.
    """

    def test_agent_builder_is_the_shared_one(self):
        scan = ScanModel().model_dump()
        assert agent_tools._build_scan_dict(scan, {}) == sc.build_server_scan(scan, {})

    def test_gui_pixel_convention(self):
        """range is the FULL field: step = range/points, pixel centres inset half a step,
        so the centres span (points-1)*step — not points*step."""
        reg = sc.build_scan_region(0.0, 10.0, 100, 0.0, 10.0, 100)
        assert reg["xStep"] == pytest.approx(0.1)               # range/points, not /(points-1)
        assert reg["xStart"] == pytest.approx(-4.95)            # -5 + half a step
        assert reg["xStop"] == pytest.approx(4.95)
        assert reg["xStop"] - reg["xStart"] == pytest.approx(99 * 0.1)
        assert reg["xRange"] == 10.0 and reg["xCenter"] == 0.0

    def test_region_ndigits_keeps_small_pixels(self):
        """A particle ROI's pixel size can be under 10 nm; 3 decimals cannot express it."""
        assert sc.build_scan_region(0.0, 1.0, 100, 0.0, 1.0, 100)["xStep"] == 0.01
        assert sc.build_scan_region(0.0, 0.5, 100, 0.0, 0.5, 100,
                                    ndigits=4)["xStep"] == 0.005

    def test_scripter_scan_uses_the_shared_builder(self):
        """The dict scripter.stxm_scan puts on the wire is build_server_scan's, verbatim."""
        from pystxmcontrol.controller import scripter as scripter_mod

        s = scripter_mod.scripter.__new__(scripter_mod.scripter)   # no socket/connect
        s.scan = ScanModel(x_range=10.0, x_points=100,
                           y_range=10.0, y_points=100).model_dump()
        s.SCANS = {"Image": {"driver": "derived_line_image", "mode": "continuousLine"}}
        s.sock = _FakeSock([{"status": True, "data": "/data/f.stxm"}, {"status": True}])

        assert s.stxm_scan() == "/data/f.stxm"
        sent = s.sock.sent[0]
        assert sent["command"] == "scan"
        assert sent["scan"] == sc.build_server_scan(s.scan, s.SCANS)

    def test_multiregion_uses_the_shared_region_builder(self):
        """The agent's multi-region path must not re-derive the geometry either."""
        regions = [{"xCenter": 1.0, "yCenter": 2.0, "xRange": 0.5, "yRange": 0.5},
                   {"xCenter": -3.0, "yCenter": 4.0, "xRange": 0.8, "yRange": 0.4}]
        ts = agent_tools.ToolSet.__new__(agent_tools.ToolSet)
        ts._client = _FakeClient()
        # __new__ bypasses __init__, so establish the invariant it would have set:
        # _image_model is always a FrameSource, never None.
        ts._image_model = ap.NullFrameSource()
        ts._scan = ScanModel().model_dump()
        ts._scans_config = {"Image": {"driver": "derived_line_image",
                                      "mode": "continuousLine"}}
        ts._particle_regions = regions
        ts._overview_pixel_size_um = None

        assert "started" in ts.start_multiregion_scan(pixel_size_nm=10.0)
        sent = ts._client.sent[0]["scan"]["scan_regions"]
        for i, r in enumerate(regions):
            pts_x = max(10, round(r["xRange"] / 0.01))
            pts_y = max(10, round(r["yRange"] / 0.01))
            assert sent[f"Region{i + 1}"] == sc.build_scan_region(
                r["xCenter"], r["xRange"], pts_x,
                r["yCenter"], r["yRange"], pts_y, ndigits=4)


class _FakeSock:
    """Minimal stand-in for scripter's REQ socket: replies from a queued list."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def send_pyobj(self, msg):
        self.sent.append(msg)

    def recv_pyobj(self):
        return self.replies.pop(0)


class _FakeClient:
    """Minimal stand-in for stxm_client: records the scan commands it is sent."""

    def __init__(self):
        self.sent = []
        self.positions = {}

    def send_message(self, msg):
        self.sent.append(msg)
        return {"status": True, "data": "ok"}

    def getMotorPositions(self):
        return self.positions


_SERVER_SCAN = {
    "scan_type": "Image", "proposal": "p", "experimenters": "e", "sample": "s",
    "x_motor": "SampleX", "y_motor": "SampleY",
    "energy_regions": {
        "EnergyRegion1": {"start": 280.0, "stop": 282.0, "step": 0.5,
                          "n_energies": 5, "dwell": 1.0},
        "EnergyRegion2": {"start": 284.0, "stop": 290.0, "step": 0.5,
                          "n_energies": 13, "dwell": 3.0},
    },
    "scan_regions": {"Region1": {
        "xCenter": 0.0, "yCenter": 0.0, "zCenter": 0.0,
        "xRange": 5.0, "yRange": 5.0, "zRange": 0.0,
        "xPoints": 50, "yPoints": 50, "zPoints": 1}},
}

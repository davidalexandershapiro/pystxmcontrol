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
import os
from copy import deepcopy
import pathlib
import re
import sys

import pytest

from pystxmcontrol.controller import scan_conversion as sc
from pystxmcontrol.controller.scan_model import ScanModel
import numpy as np

from pystxmcontrol.controller import agent_ports as ap
from pystxmcontrol.controller import remote_frames as rf
from pystxmcontrol.controller import scan_files as sfiles
from pystxmcontrol.controller import tool_registry as tr
from pystxmcontrol.controller import instrument_client as ic
import pystxmcontrol.agent_tools as agent_tools

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


# The complete advertised tool surface. Spelled out rather than counted so a split, a
# refactor or a bad edit cannot quietly change it: this file has itself lost two whole
# test classes to a range-based edit that nothing but a name check would have caught.
EXPECTED_TOOLS = {
    'add_to_logbook', 'analyze_energy_stack', 'apply_focus_calibration',
    'cancel_scan', 'check_scan_limits', 'configure_focus_scan',
    'configure_osa_scan', 'count_element_particles', 'define_scan_from_file',
    'finalize_tuning', 'find_particles', 'get_config',
    'get_image_center_of_mass', 'get_intelligence_recommendations',
    'get_last_scan_params', 'get_last_scan_stats', 'get_logbook_entry',
    'get_motor_position', 'get_osa_beam_center', 'get_safety_instructions',
    'get_scan_status', 'get_toolset_debug', 'list_buffered_scans',
    'list_energy_presets', 'move_motor', 'plot_motor_positions',
    'read_beam_quality', 'read_daq', 'reanchor_tuning_limit',
    'request_confirmation', 'save_beamline_entry', 'search_logbook',
    'set_beamline_from_database', 'start_multiregion_scan', 'start_scan',
    'start_tuning_session', 'step_tuning_parameter', 'update_scan',
    'wait_for_scan', 'zero_osa_position',
}

# Everything a full GUI session serves. "recommendations" is separate from
# "frames": the two arrive by different routes and a surface can have either.
ALL_CAPABILITIES = ("frames", "recommendations", "logbook", "approval")
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
        # Completed scans come from the server, so the analysis tools are served here.
        assert {"find_particles", "get_intelligence_recommendations"} <= names
        # But there is no open logbook and no way to ask the operator out of process.
        assert not ({"add_to_logbook", "request_confirmation"} & names)

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


class TestRemoteIntelligence:
    """Recommendations reach an out-of-process agent without shipping it live frames.

    The intelligence module publishes task_recommendation / intelligence_suggestion
    dicts on the scan-data stream. They ride the same socket as the frame payloads but
    are small dicts, so collecting them needs none of the GUI's frame assembly.
    """

    def test_recommendations_and_alarms_are_routed(self):
        feed = rf.RemoteFrameSource()
        feed._handle({"type": "task_recommendation", "subtype": "focus", "delta_z": 1.5})
        feed._handle({"type": "intelligence_suggestion", "anomaly_type": "beam_loss"})
        assert len(feed.get("pending_recommendations")) == 1
        assert len(feed.get("pending_alarms")) == 1

    def test_a_user_query_answer_is_not_an_alarm(self):
        """Only diagnoses should interrupt a waiting agent, not answers to questions."""
        feed = rf.RemoteFrameSource()
        feed._handle({"type": "intelligence_suggestion", "anomaly_type": "user_query"})
        feed._handle({"type": "intelligence_suggestion"})
        assert feed.get("pending_alarms") == []

    def test_frame_payloads_are_ignored(self):
        """The stream carries scan data too; it must not end up in the queues."""
        feed = rf.RemoteFrameSource()
        feed._handle({"scan_data": [1, 2, 3]})
        feed._handle("scan_complete")
        assert feed.get("pending_recommendations") == []
        assert feed.get("pending_alarms") == []

    def test_reading_a_queue_hands_back_a_copy(self):
        """Tools drain by reading then setting []; a shared list would let an arriving
        message land in what the caller is still iterating."""
        feed = rf.RemoteFrameSource()
        feed._handle({"type": "task_recommendation"})
        first = feed.get("pending_recommendations")
        feed._handle({"type": "task_recommendation"})
        assert len(first) == 1

    def test_capabilities_reflect_what_is_actually_subscribed(self):
        feed = rf.RemoteFrameSource()
        assert ap.frame_capabilities(feed) == ()
        assert not ap.serves(feed, "recommendations")
        feed._subscriber = object()                    # as start_recommendations would
        assert ap.serves(feed, "recommendations")
        assert not ap.serves(feed, "frames")           # 5a, not yet

    def test_the_tool_guards_on_recommendations_not_frames(self):
        """A session with the stream but no scan data can serve recommendations fine;
        refusing it for want of 'frames' would be wrong."""
        feed = rf.RemoteFrameSource()
        feed._subscriber = object()
        feed._handle({"type": "task_recommendation", "subtype": "focus", "delta_z": 1.5})
        ts = agent_tools.ToolSet(_FakeClient(), image_model=feed)
        assert ts.capabilities() == ("recommendations",)
        assert "delta_z" in ts.get_intelligence_recommendations()

    def test_headless_says_why_rather_than_blaming_the_image_model(self):
        ts = agent_tools.ToolSet(_FakeClient())
        assert "not available in this session" in ts.get_intelligence_recommendations()


class TestScanDataFromTheServer:
    """Completed scans reach a client with no filesystem access to the data directory.

    The server reads the files and returns the arrays, which is not an MCP concession:
    data_browser_widget enumerates scans with os.listdir today, so a remotely-run GUI
    has the same limitation.
    """

    def test_scans_are_found_in_the_day_directory_layout(self, tmp_path):
        """dataHandler saves to <data_dir>/<yyyy>/<mm>/<yymmdd>/, so a listing that
        walked one level down found nothing at all on a real rig."""
        day = tmp_path / "2026" / "09" / "260905"
        day.mkdir(parents=True)
        (day / "MEGA_260905000.stxm").write_bytes(b"")
        (tmp_path / "loose.stxm").write_bytes(b"")
        # CCD frames of a ptychography scan are frames, not scans, and would bury them.
        frames = day / "MEGA_260905000"
        frames.mkdir()
        (frames / "MEGA_260905000_ccdframes_0_0.stxm").write_bytes(b"")

        found = [os.path.basename(path) for path, _mtime in sfiles._iter_scan_files(str(tmp_path))]
        assert sorted(found) == ["MEGA_260905000.stxm", "loose.stxm"]

    def test_frame_selection(self):
        assert sfiles._frame_indices(None, 5) is None          # full dataset default
        assert sfiles._frame_indices(2, 5) == [3, 4]           # the LAST N
        assert sfiles._frame_indices(9, 5) is None             # more than there are
        assert sfiles._frame_indices([0, 3], 5) == [0, 3]      # explicit
        assert sfiles._frame_indices([9], 5) is None           # out of range

    def test_buffer_records_match_the_gui_shape(self):
        """The analysis tools must not be able to tell a server-read scan from one the
        GUI buffered live. 'path' is the one addition: a GUI record keeps the full path
        in its scan_id, and these keep the basename there."""
        feed = rf.RemoteFrameSource(client=_ScanServer())
        record = feed.get("scan_buffer")[-1]
        assert set(record) == {"stxm", "scan_id", "energies", "scan_type", "timestamp",
                               "path"}
        assert record["scan_id"] == "b.stxm"
        assert record["path"] == "/d/b.stxm"

    def test_positions_are_indexed_per_region_like_a_live_scan(self):
        """The tools read xPos[region] beside interp_counts[daq][region]; a flat list
        would hand them one coordinate where a whole axis belongs."""
        scan = rf._LazyScan(_ScanServer(), "/d/b.stxm")
        assert len(scan.xPos) == 1 and len(scan.xPos[0]) == 8
        assert len(scan.yPos) == 1 and len(scan.yPos[0]) == 6

    def test_buffer_is_ordered_oldest_first(self):
        """The tools read the buffer with [-1] for 'most recent', so the server's
        newest-first listing has to be reversed once here, not in every tool."""
        feed = rf.RemoteFrameSource(client=_ScanServer())
        assert [r["scan_id"] for r in feed.get("scan_buffer")] == ["a.stxm", "b.stxm"]

    def test_listing_moves_no_image_data(self):
        """list_buffered_scans must not pull megabytes per entry just to list them."""
        client = _ScanServer()
        feed = rf.RemoteFrameSource(client=client)
        feed.get("scan_buffer")
        assert [m["command"] for m in client.sent] == ["list_scans"]

    def test_arrays_arrive_only_when_a_tool_reads_them(self):
        client = _ScanServer()
        feed = rf.RemoteFrameSource(client=client)
        record = feed.get("scan_buffer")[-1]
        assert record["stxm"].interp_counts["default"][0].shape == (2, 6, 8)
        assert any(m["command"] == "get_scan_data" for m in client.sent)

    def test_a_scan_is_fetched_once_and_cached(self):
        client = _ScanServer()
        scan = rf._LazyScan(client, "/d/a.stxm")
        scan.interp_counts, scan.xPos, scan.yPos
        assert sum(m["command"] == "get_scan_data" for m in client.sent) == 1

    def test_single_frame_keys_do_not_pull_a_stack(self):
        """all_detector_images needs the frame the scan ended on, not 50 energies."""
        client = _ScanServer()
        feed = rf.RemoteFrameSource(client=client)
        images = feed.get("all_detector_images")
        assert images["default"].shape == (6, 8)               # 2-D, not (2, 6, 8)
        request = next(m for m in client.sent if m["command"] == "get_scan_data")
        assert request["frames"] == 1

    def test_geometry_is_derived_from_the_position_arrays(self):
        feed = rf.RemoteFrameSource(client=_ScanServer())
        assert feed.get("x_center") == 0.0 and feed.get("x_range") == 4.0
        assert feed.get("y_center") == 0.0 and feed.get("y_range") == 3.0

    def test_an_unreadable_scan_degrades_instead_of_raising(self):
        feed = rf.RemoteFrameSource(client=_FailingScanServer())
        assert feed.get("all_detector_images") is None
        assert feed.get("all_detector_images", "fallback") == "fallback"

    def test_frames_capability_requires_a_client(self):
        assert ap.frame_capabilities(rf.RemoteFrameSource()) == ()
        assert ap.serves(rf.RemoteFrameSource(client=_ScanServer()), "frames")

    def test_the_analysis_tools_run_on_it(self):
        """The whole point: a frame tool works with no filesystem and no GUI."""
        feed = rf.RemoteFrameSource(client=_ScanServer())
        ts = agent_tools.ToolSet(_FakeClient(), image_model=feed)
        assert "frames" in ts.capabilities()
        stats = json.loads(ts.get_last_scan_stats())
        assert stats["image_shape_px"] == [6, 8]
        listed = json.loads(ts.list_buffered_scans())
        assert listed["count"] == 2
        assert [s["scan_id"] for s in listed["buffered_scans"]] == ["a.stxm", "b.stxm"]


class _ScanServer:
    """A control server holding two completed scans."""

    STACK = np.arange(2 * 6 * 8, dtype=float).reshape(2, 6, 8)

    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(msg)
        if msg["command"] == "list_scans":
            return {"status": True, "data": [                  # newest first
                {"scan_id": "b.stxm", "path": "/d/b.stxm", "timestamp": 200.0,
                 "scan_type": "Image", "energies": [700.0, 710.0]},
                {"scan_id": "a.stxm", "path": "/d/a.stxm", "timestamp": 100.0,
                 "scan_type": "Image", "energies": [700.0, 710.0]}]}
        if msg["command"] == "get_scan_data":
            frames = msg.get("frames")
            array = self.STACK[-frames:] if isinstance(frames, int) else self.STACK
            ny, nx = self.STACK.shape[1:]
            return {"status": True, "data": {
                "scan_id": "b.stxm", "path": "/d/b.stxm",
                "images": {"default": array},
                "x_positions": list(np.linspace(-2.0, 2.0, nx)),
                "y_positions": list(np.linspace(-1.5, 1.5, ny)),
                "energies": [700.0, 710.0], "scan_type": "Image"}}
        return {"status": True, "data": "ok"}


class _ParticleScanServer(_ScanServer):
    """A server holding a scan with one absorbing particle in the middle of the field."""

    STACK = np.ones((2, 32, 32), dtype=float)
    STACK[:, 12:20, 12:20] = 0.1


class _ElementScanServer(_ScanServer):
    """One particle that absorbs far more on the edge frame than below it."""

    STACK = np.ones((2, 32, 32), dtype=float)
    STACK[0, 12:20, 12:20] = 0.3
    STACK[1, 12:20, 12:20] = 0.05


class _FailingScanServer(_ScanServer):
    """A server that lists a scan it then cannot read."""

    def send_message(self, msg):
        response = super().send_message(msg)
        if msg["command"] == "get_scan_data":
            return {"status": False, "data": "unreadable"}
        return response


class TestAnalysingASavedScanFile:
    """"Load up the last scan and find the particles."

    The scan record names the file the data was saved to, and every image tool takes
    that path, so analysing a completed scan needs neither a live frame nor a question
    to the operator about where the data landed.
    """

    def test_the_scan_record_names_the_saved_file(self):
        client = _ScanRecordClient(file_name="/d/b.stxm")
        ts = agent_tools.ToolSet(client)
        params = json.loads(ts.get_last_scan_params().split("\n", 1)[1])
        assert params["data_file"] == "/d/b.stxm"

    def test_a_record_without_a_path_falls_back_to_the_newest_scan(self):
        """A server that predates recording the path still leaves the agent able to name
        a file — but only one whose scan type matches, since naming the wrong file is
        worse than naming none."""
        client = _ScanRecordClient(file_name=None)
        assert json.loads(agent_tools.ToolSet(client).get_last_scan_params()
                          .split("\n", 1)[1])["data_file"] == "/d/b.stxm"

        client = _ScanRecordClient(file_name=None, listed_type="Focus")
        assert "data_file" not in json.loads(
            agent_tools.ToolSet(client).get_last_scan_params().split("\n", 1)[1])

    def test_a_multiregion_record_reports_the_regions_that_ran(self):
        """The data_file belongs to the multiregion scan, so the geometry beside it must
        too — echoing the working definition would pair a new file with the geometry of
        the scan before it, which is what a follow-up then gets planned from."""
        client = _ScanRecordClient(file_name="/d/b.stxm", regions=3)
        ts = agent_tools.ToolSet(client)
        baseline = dict(ts._scan)

        result = ts.get_last_scan_params()
        assert "MULTIREGION" in result
        report = json.loads(result.split("\n", 1)[1])
        assert report["data_file"] == "/d/b.stxm"
        assert [r["region"] for r in report["regions"]] == ["Region1", "Region2", "Region3"]
        assert report["regions"][0]["pixel_size_nm"] == 25.0
        # The working definition is reported as itself, and left alone: ScanModel holds
        # one region, so adopting Region1 would make a per-particle box the new baseline.
        assert report["working_scan"] == baseline
        assert ts._scan == baseline

    def test_particles_are_found_in_a_file_the_server_reads(self):
        """No live frames, no filesystem: the regions still come back in µm."""
        client = _ParticleScanServer()
        ts = agent_tools.ToolSet(client)
        result = json.loads(ts.find_particles(file="/d/b.stxm", save_map=False))
        assert result["particles_found"] == 1
        assert result["source"] == "b.stxm"
        assert result["overview_scan_um"] == {"x_range": 4.0, "y_range": 3.0,
                                              "x_center": 0.0, "y_center": 0.0}
        request = next(m for m in client.sent if m["command"] == "get_scan_data")
        assert request["path"] == "/d/b.stxm" and request["frames"] == 1

    def test_stats_and_centre_of_mass_read_the_same_file(self):
        ts = agent_tools.ToolSet(_ScanServer())
        stats = json.loads(ts.get_last_scan_stats(file="/d/b.stxm"))
        assert stats["source"] == "b.stxm" and stats["image_shape_px"] == [6, 8]
        com = json.loads(ts.get_image_center_of_mass(file="/d/b.stxm"))
        assert com["source"] == "b.stxm"

    def test_element_mapping_reads_the_whole_stack_from_a_file(self):
        """Regions come back in µm, placed by the positions the file records, so
        start_multiregion_scan() can image them without any further conversion."""
        client = _ElementScanServer()
        ts = agent_tools.ToolSet(client)
        result = json.loads(ts.count_element_particles(file="/d/b.stxm", save_map=False))
        assert result["pre_energy_eV"] == 700.0 and result["edge_energy_eV"] == 710.0
        assert result["total_particles"] == 1 and result["element_particles"] == 1
        region = result["element_regions"][0]
        assert abs(region["xCenter"]) < 0.5 and abs(region["yCenter"]) < 0.5
        assert 1.0 < region["xRange"] < 2.5          # 8 of 32 px across 4 µm, padded
        # Both energies are needed, so this one does NOT ask for a single frame.
        request = next(m for m in client.sent if m["command"] == "get_scan_data")
        assert request["frames"] is None

    def test_a_file_the_server_cannot_read_says_so(self):
        ts = agent_tools.ToolSet(_FailingScanServer())
        result = ts.find_particles(file="/d/missing.stxm")
        assert "/d/missing.stxm" in result and "list_buffered_scans" in result

    def test_the_listing_names_a_path_for_every_scan(self):
        """What list_buffered_scans shows has to be what file= takes."""
        ts = agent_tools.ToolSet(_FakeClient(),
                                 image_model=rf.RemoteFrameSource(client=_ScanServer()))
        listed = json.loads(ts.list_buffered_scans())
        assert [s["path"] for s in listed["buffered_scans"]] == ["/d/a.stxm", "/d/b.stxm"]

    def test_a_local_file_is_read_without_the_server(self, tmp_path, monkeypatch):
        """A GUI on the server's own host still works when the server is an older build
        that has no get_scan_data command."""
        recorded = {}

        def fake_read_scan(path, frames=None, detector="default", region=0):
            recorded.update(path=path, frames=frames)
            return {"scan_id": "local.stxm", "images": {"default": _ScanServer.STACK},
                    "x_positions": list(np.linspace(-2.0, 2.0, 8)),
                    "y_positions": list(np.linspace(-1.5, 1.5, 6)),
                    "energies": [700.0, 710.0]}

        monkeypatch.setattr(sfiles, "read_scan", fake_read_scan)
        local = tmp_path / "local.stxm"
        local.write_bytes(b"")
        ts = agent_tools.ToolSet(_FailingScanServer())
        stats = json.loads(ts.get_last_scan_stats(file=str(local)))
        assert stats["source"] == "local.stxm"
        assert recorded["path"] == str(local) and recorded["frames"] == 1


class _ScanRecordClient(_ScanServer):
    """A server whose lastScan record may or may not name the file it saved."""

    def __init__(self, file_name=None, listed_type="Image", regions=1):
        super().__init__()
        self._listed_type = listed_type
        scan = deepcopy(_SERVER_SCAN)
        if file_name:
            scan["file_name"] = file_name
        if regions > 1:
            # What start_multiregion_scan submits: one small box per particle.
            scan["scan_regions"] = {
                f"Region{i + 1}": {"xCenter": float(i), "yCenter": -float(i),
                                   "zCenter": 0.0, "xRange": 1.0, "yRange": 1.0,
                                   "zRange": 0.0, "xPoints": 40, "yPoints": 40,
                                   "zPoints": 1}
                for i in range(regions)}
        self.main_config = {"lastScan": {"Image": scan}}
        self.motorInfo, self.scanConfig, self.currentMotorPositions = {}, {}, {}

    def get_config(self):
        return None

    def send_message(self, msg):
        response = super().send_message(msg)
        if msg["command"] == "list_scans":
            for record in response["data"]:
                record["scan_type"] = self._listed_type
        return response


class TestBeamQualityFromTheServer:
    """The tuning search runs identically in the GUI and out of process.

    read_beam_quality used to measure an assembled image, which an out-of-process agent
    does not have. It now asks the server, where the data already is.
    """

    def test_the_whole_tuning_workflow_needs_no_frames(self):
        client_only = {s.name for s in agent_tools.TOOL_SPECS if not s.requires}
        assert {"start_tuning_session", "read_beam_quality", "step_tuning_parameter",
                "reanchor_tuning_limit", "finalize_tuning"} <= client_only

    def test_it_asks_the_server_and_waits_for_fresh_lines(self):
        client = _FillingClient(rows_per_poll=4)
        ts = agent_tools.ToolSet(client)
        result = json.loads(ts.read_beam_quality(settle_lines=5))
        assert result["snr"] == 5.0 and result["scan_complete"] is False
        assert [m["command"] for m in client.sent].count("get_beam_quality") >= 2

    def test_it_stops_when_the_scan_finishes(self):
        client = _FillingClient(rows_per_poll=0, idle=True)
        ts = agent_tools.ToolSet(client)
        assert json.loads(ts.read_beam_quality())["scan_complete"] is True

    def test_no_scan_data_yet_is_reported_plainly(self):
        client = _FillingClient(rows_per_poll=0, no_data=True)
        assert "No scan data yet" in agent_tools.ToolSet(client).read_beam_quality()

    def test_server_side_math(self):
        """The computation moved to dataHandler; check it on a known image."""
        from pystxmcontrol.controller.dataHandler import dataHandler
        holder = type("D", (), {"beam_quality": dataHandler.beam_quality})()
        image = np.zeros((10, 8))
        image[:6] = 4.0
        holder.data = type("S", (), {"interp_counts": {"default": [image]}})()
        stats = holder.beam_quality("default", lines=2)
        assert stats["intensity"] == 4.0 and stats["noise_rms"] == 0.0
        assert stats["n_filled_rows"] == 6 and stats["lines_measured"] == 2

    def test_server_side_picks_the_filling_energy_slice(self):
        """interp_counts is (energy, y, x); measure the slice being acquired."""
        from pystxmcontrol.controller.dataHandler import dataHandler
        holder = type("D", (), {"beam_quality": dataHandler.beam_quality})()
        stack = np.zeros((3, 10, 8))
        stack[1, :7] = 2.0                       # the one with data
        holder.data = type("S", (), {"interp_counts": {"default": [stack]}})()
        assert holder.beam_quality()["n_filled_rows"] == 7

    def test_server_side_returns_none_without_data(self):
        from pystxmcontrol.controller.dataHandler import dataHandler
        holder = type("D", (), {"beam_quality": dataHandler.beam_quality})()
        holder.data = type("S", (), {"interp_counts": {}})()
        assert holder.beam_quality() is None


class _FillingClient:
    """A server whose tuning scan fills fresh lines between polls."""

    def __init__(self, rows_per_poll=4, idle=False, no_data=False):
        self.sent, self.positions = [], {}
        self._rows, self._per_poll = 3, rows_per_poll
        self._idle, self._no_data = idle, no_data

    def send_message(self, msg):
        self.sent.append(msg)
        if msg.get("command") == "get_beam_quality":
            if self._no_data:
                return {"status": False, "data": None}
            self._rows += self._per_poll
            return {"status": True,
                    "data": {"intensity": 10.0, "noise_rms": 2.0, "snr": 5.0,
                             "n_filled_rows": self._rows,
                             "lines_measured": msg.get("lines", 5)}}
        return {"status": True, "data": "ok"}

    def get_status(self):
        return {"mode": "idle" if self._idle else "scanning"}

    def getMotorPositions(self):
        return self.positions


class TestOneClientPort:
    """One client surface beneath both agent surfaces.

    ToolSet was written against the GUI's stxm_client but uses only nine of its members.
    instrument_client names those nine so the same tools can also run out of process over
    scripter. These tests fail if a tool starts depending on a tenth member, or if the two
    clients drift apart on the nine.
    """

    def test_port_module_is_headless(self):
        """It must not drag in Qt — the MCP server has no display and no PySide6."""
        import subprocess
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; import pystxmcontrol.controller.instrument_client; "
             "assert 'PySide6' not in sys.modules; print('clean')"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "clean" in r.stdout

    def test_tools_use_only_the_port(self):
        """Every self._client.<x> in tools.py must be a member of the port.

        This is the test that actually keeps the port honest: it fails the moment a tool
        reaches for something only stxm_client has.
        """
        # Every domain module, not one file: after the split, scanning a single module
        # would silently stop guarding most of the tools.
        package = pathlib.Path(agent_tools.__file__).parent
        modules = sorted(package.glob("*.py"))
        assert len(modules) >= 10, "domain modules not found — did the layout change?"
        source = "\n".join(m.read_text() for m in modules)
        used = set(re.findall(r"self\._client\.(\w+)", source))
        allowed = set(ic.CLIENT_METHODS) | set(ic.CLIENT_ATTRIBUTES)
        assert used <= allowed, f"tools.py uses non-port client members: {used - allowed}"

    def test_scripter_client_satisfies_the_port(self):
        client = ic.ScripterClient(_FakeScripter())
        assert ic.missing_members(client) == []
        assert isinstance(client, ic.InstrumentClient)      # methods only

    @needs_gui
    def test_stxm_client_satisfies_the_port(self):
        from pystxmcontrol.controller.client import stxm_client
        assert ic.missing_members(stxm_client) == []        # class: methods only

    @needs_gui
    def test_stxm_client_get_config_populates_the_attributes(self, tmp_path, monkeypatch):
        """The four data attributes are set by get_config(), not __init__, so check the
        method actually assigns all of them."""
        from pystxmcontrol.controller import client as client_mod

        cfg = tmp_path / "main.json"
        cfg.write_text('{"server": {}}')
        monkeypatch.setattr(client_mod, "MAINCONFIGFILE", str(cfg))

        c = client_mod.stxm_client.__new__(client_mod.stxm_client)   # no server needed
        c.send_message = lambda msg: {"data": ({"SampleX": {}}, {"Image": {}},
                                               {"SampleX": 1.0}, {"default": {}},
                                               {"lastScan": {}})}
        c.get_config()
        assert ic.missing_members(c) == []
        assert c.motorInfo == {"SampleX": {}}
        assert c.scanConfig == {"Image": {}}
        assert c.currentMotorPositions == {"SampleX": 1.0}
        assert c.main_config == {"lastScan": {}}

    def test_adapter_maps_the_same_server_tuple(self):
        """scripter and stxm_client unpack the SAME five-tuple; the adapter renames it."""
        client = ic.ScripterClient(_FakeScripter())
        client.get_config()
        assert client.motorInfo == {"SampleX": {}}
        assert client.scanConfig == {"Image": {}}
        assert client.currentMotorPositions == {"SampleX": 1.0}
        assert client.main_config == {"lastScan": {}}

    def test_adapter_adopts_an_already_connected_scripter(self):
        """The MCP server's _ensure_connected already called get_config; don't re-fetch."""
        s = _FakeScripter()
        s.MOTORS, s.SCANS, s.POSITIONS, s.DAQS, s.CONFIG = s._config_tuple()
        client = ic.ScripterClient(s)
        assert client.motorInfo == {"SampleX": {}}
        assert s.get_config_calls == 0

    def test_adapter_wire_messages(self):
        s = _FakeScripter()
        client = ic.ScripterClient(s)

        s.sock.replies = [{"status": True, "mode": "idle"}]
        assert client.get_status()["mode"] == "idle"
        assert s.sock.sent[-1] == {"command": "getStatus"}

        s.sock.replies = [{"status": True, "data": {"SampleX": 4.2}}]
        assert client.getMotorPositions() == {"SampleX": 4.2}
        assert s.sock.sent[-1] == {"command": "getMotorPositions"}

        s.sock.replies = [{"status": True}]
        client.change_motor_config("ZonePlateZ", "offset", 1.5)
        assert s.sock.sent[-1] == {
            "command": "changeMotorConfig",
            "data": {"motor": "ZonePlateZ", "config": "offset", "value": 1.5}}
        assert s.get_config_calls == 1          # re-reads after the write

    def test_toolset_constructs_over_the_adapter(self):
        """The point of Stage 1: the GUI's ToolSet runs on a scripter connection."""
        s = _FakeScripter()
        s.CONFIG = {"lastScan": {}}
        s.MOTORS, s.SCANS, s.POSITIONS, s.DAQS = ({"SampleX": {}}, {"Image": {}},
                                                  {"SampleX": 1.0}, {"default": {}})
        ts = agent_tools.ToolSet(ic.ScripterClient(s))

        s.sock.replies = [{"status": True, "mode": "idle"}]
        assert "idle" in ts.get_scan_status()

        s.sock.replies = [{"status": True}]
        assert "Successfully moved" in ts.move_motor("SampleX", 2.0)
        assert s.sock.sent[-1] == {"command": "moveMotor", "axis": "SampleX", "pos": 2.0}


class _FakeScripter:
    """Minimal stand-in for a connected scripter: a socket plus the config five-tuple."""

    MOTORS = None

    def __init__(self):
        self.sock = _FakeSock([])
        self.get_config_calls = 0

    @staticmethod
    def _config_tuple():
        return ({"SampleX": {}}, {"Image": {}}, {"SampleX": 1.0},
                {"default": {}}, {"lastScan": {}})

    def get_config(self):
        self.get_config_calls += 1
        return self._config_tuple()


class TestOneToolRegistry:
    """One decorated function per tool; every surface's advertisement is derived.

    The hand-written TOOL_SCHEMAS block this replaced is gone; these assert the
    invariants it used to be checked against. Parameter names, JSON types and required
    lists are DERIVED from the signature, so they cannot drift from the function.
    Prose comes from the docstring and is not asserted here — but it must not be empty,
    because a tool with no description is one the model cannot choose correctly.
    """

    def _generated(self):
        return agent_schemas()

    def test_the_exact_tool_surface_is_registered(self):
        """The full set, not just the count.

        A @tool-less method is invisible to every surface with no error, and so is an
        inherited one if specs_for stops walking the MRO. A count alone would pass a
        change that dropped one tool and added another — precisely what a by-domain
        split can do, and precisely what happened to this file's own test classes.
        Update this list deliberately when adding a tool.
        """
        assert {s.name for s in agent_tools.TOOL_SPECS} == EXPECTED_TOOLS

    def test_registration_survives_inheritance(self):
        """ToolSet is a composition of per-domain classes; vars() alone would silently
        drop every inherited tool."""
        class Domain:
            @tr.tool()
            def domain_tool(self):
                "A tool defined in a domain class."

        class Composed(Domain):
            @tr.tool()
            def own_tool(self):
                "A tool defined on the composed class."

        assert {s.name for s in tr.specs_for(Composed)} == {"domain_tool", "own_tool"}

    def test_an_override_is_registered_once_as_the_resolved_version(self):
        """Registering the shadowed copy too would advertise a schema that need not
        describe what getattr actually calls."""
        class Base:
            @tr.tool()
            def shared(self):
                "base"

        class Sub(Base):
            @tr.tool(mutates_hardware=True)
            def shared(self):
                "overridden"

        specs = tr.specs_for(Sub)
        assert [s.name for s in specs] == ["shared"]
        assert specs[0].mutates_hardware is True

    def test_a_tool_can_be_retired_by_overriding_it_undecorated(self):
        class Base:
            @tr.tool()
            def shared(self):
                "base"

        class Retires(Base):
            def shared(self):
                "no longer a tool"

        assert tr.specs_for(Retires) == []

    def test_no_tool_is_advertised_without_a_description(self):
        for entry in self._generated():
            assert entry["function"]["description"].strip(), entry["function"]["name"]

    def test_advertised_parameters_are_real_parameters(self):
        """A schema promising an argument the function does not accept fails only when
        an agent tries it. Derivation makes that impossible; this proves it."""
        for spec in agent_tools.TOOL_SPECS:
            advertised = set(tr.parameters_schema(spec)["properties"])
            accepted = set(inspect.signature(spec.fn).parameters) - {"self"}
            if any(p.kind is inspect.Parameter.VAR_KEYWORD
                   for p in inspect.signature(spec.fn).parameters.values()):
                continue                      # **kwargs tool: its override is the contract
            assert advertised <= accepted, spec.name

    def test_hidden_params_are_accepted_but_not_advertised(self):
        """add_to_logbook keeps a deprecated argument working without inviting its use."""
        spec = next(s for s in agent_tools.TOOL_SPECS if s.name == "add_to_logbook")
        assert "attach_last_scan" in inspect.signature(spec.fn).parameters
        assert "attach_last_scan" not in tr.parameters_schema(spec)["properties"]

    def test_update_scan_override_fields_are_scan_model_fields(self):
        """The **kwargs override is the contract, so it must still describe real fields."""
        documented = set(agent_tools._UPDATE_SCAN_SCHEMA["properties"])
        documented.discard("energy_preset")           # resolved into energy_regions
        assert documented <= set(ScanModel.model_fields)

    def test_capability_gating_selects_the_tier(self):
        """A surface advertises only what its capabilities can satisfy."""
        client_only = {s["function"]["name"] for s in tr.openai_schemas(agent_tools.TOOL_SPECS)}
        assert "move_motor" in client_only            # needs only the client
        assert "read_beam_quality" in client_only     # measured server-side since 5c
        assert "find_particles" not in client_only    # needs frames
        assert "add_to_logbook" not in client_only    # needs a logbook
        assert "request_confirmation" not in client_only
        assert "get_intelligence_recommendations" not in client_only

        with_frames = {s["function"]["name"]
                       for s in tr.openai_schemas(agent_tools.TOOL_SPECS, have=("frames",))}
        assert "find_particles" in with_frames

    def test_feature_gating_hides_the_logbook_context_tools(self):
        """They are off by default so they cost no tokens (agent.py's current rule)."""
        without = {s["function"]["name"] for s in tr.openai_schemas(
            agent_tools.TOOL_SPECS, have=ALL_CAPABILITIES)}
        assert "search_logbook" not in without
        assert "add_to_logbook" in without            # writing is always available
        assert len(without) == len(EXPECTED_TOOLS) - 2   # minus the two ctx tools

    def test_hardware_tools_are_declared(self):
        """mutates_hardware drives read-only mode, so the set must be exact."""
        mutating = {s.name for s in agent_tools.TOOL_SPECS if s.mutates_hardware}
        assert mutating == {
            "move_motor", "start_scan", "cancel_scan", "start_multiregion_scan",
            "start_tuning_session", "step_tuning_parameter", "finalize_tuning",
            "set_beamline_from_database", "zero_osa_position",
            "apply_focus_calibration", "read_daq"}


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
        for result in (ts.get_last_scan_stats(), ts.find_particles()):
            assert result == "Image model not available."

    def test_the_message_names_the_capability_that_is_missing(self):
        """get_intelligence_recommendations needs the intelligence stream, not images,
        so blaming the image model would point the operator at the wrong thing."""
        ts = agent_tools.ToolSet(_FakeClient())
        result = ts.get_intelligence_recommendations()
        assert "intelligence stream" in result
        assert "Image model" not in result

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

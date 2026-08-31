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
import pathlib
import re
import sys

import pytest

from pystxmcontrol.controller import scan_conversion as sc
from pystxmcontrol.controller.scan_model import ScanModel
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


def agent_schema(name):
    for schema in agent_tools.TOOL_SCHEMAS:
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


@needs_mcp
class TestEnergyPresetParity:
    """The feature this shared layer was built for must exist on both surfaces."""

    def test_both_expose_list_energy_presets(self):
        assert hasattr(agent_tools.ToolSet, "list_energy_presets")
        agent_schema("list_energy_presets")            # raises if missing
        assert callable(getattr(mcp_server, "list_energy_presets", None))

    def test_both_update_scan_accept_energy_preset(self):
        assert "energy_preset" in agent_schema("update_scan")["parameters"]["properties"]
        assert "energy_preset" in inspect.signature(mcp_server.update_scan).parameters

    def test_agent_update_scan_takes_kwargs(self):
        """The agent's update_scan is **kwargs-based, so its schema is the contract."""
        params = inspect.signature(agent_tools.ToolSet.update_scan).parameters
        assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())

    def test_agent_schema_fields_are_scan_model_fields(self):
        """Every documented update_scan parameter must be something the model accepts,
        so an agent cannot be told about a field that silently does nothing."""
        documented = set(agent_schema("update_scan")["parameters"]["properties"])
        documented.discard("energy_preset")       # resolved into energy_regions
        assert documented <= set(ScanModel.model_fields)

    def test_mcp_signature_fields_are_scan_model_fields(self):
        params = set(inspect.signature(mcp_server.update_scan).parameters)
        params.discard("energy_preset")
        assert params <= set(ScanModel.model_fields)


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
        source = pathlib.Path(agent_tools.__file__).read_text()
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
        ts._image_model = None
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

    def send_message(self, msg):
        self.sent.append(msg)
        return {"status": True, "data": "ok"}


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

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

import pytest

from pystxmcontrol.controller import scan_conversion as sc
from pystxmcontrol.controller.scan_model import ScanModel
from pystxmcontrol.controller.task_agent import tools as agent_tools

# The MCP server imports fastmcp, which is an optional extra; skip rather than fail when
# the mcp extra is not installed in this environment.
mcp_server = pytest.importorskip("pystxmcontrol.mcp.server",
                                 reason="mcp extra not installed")
import pystxmcontrol.mcp.utilities as stxm_utils   # noqa: E402


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

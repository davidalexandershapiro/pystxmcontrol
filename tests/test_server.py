"""The MCP server's own surface.

Most of this file used to test the server's private copies of the instrument tools —
update_scan, get_config, move_motor, stxm_scan and friends. Those copies are gone: the
server now advertises the shared ToolSet implementations (see tool_registry), and the
behaviour of those tools is covered in test_agent_surface_parity.py, which exercises
them through the real MCP call path.

What is left here is what the server still owns: resolving which control server to
talk to, and connecting to it.
"""

import json
from unittest.mock import Mock, patch

import pytest

server = pytest.importorskip("pystxmcontrol.mcp.server",
                             reason="mcp extra not installed")


@pytest.fixture(autouse=True)
def _reset_toolset():
    """Each test starts with no connection, and leaves none behind."""
    server._TOOLSET = None
    yield
    server._TOOLSET = None


class TestNoForkedToolsRemain:
    """The server must not grow private copies of the shared tools again."""

    @pytest.mark.parametrize("name", [
        "update_scan", "get_config", "get_motor_position", "move_motor",
        "stxm_scan", "check_motor_status", "list_energy_presets",
        "get_safety_instructions", "define_scan_from_file", "plot_motor_positions",
    ])
    def test_tool_is_not_defined_on_the_server(self, name):
        assert not hasattr(server, name), (
            f"{name} is back as a server-private copy; it belongs in the shared ToolSet")

    def test_the_shared_tools_are_registered_instead(self):
        assert "update_scan" in server.REGISTERED
        assert "define_scan_from_file" in server.REGISTERED   # moved into ToolSet
        assert "plot_motor_positions" in server.REGISTERED


class TestDefaultServer:
    """Resolving which instrument to talk to."""

    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("PYSTXM_SERVER_HOST", "10.0.0.5")
        monkeypatch.setenv("PYSTXM_SERVER_PORT", "1234")
        assert server._default_server() == ("10.0.0.5", 1234)

    def test_env_host_without_port_uses_the_default_port(self, monkeypatch):
        monkeypatch.setenv("PYSTXM_SERVER_HOST", "10.0.0.5")
        monkeypatch.delenv("PYSTXM_SERVER_PORT", raising=False)
        assert server._default_server() == ("10.0.0.5", 9999)

    def test_falls_back_to_main_json(self, monkeypatch, tmp_path):
        """Reading main.json is what lets an agent reach the real instrument instead of
        hanging on a localhost default."""
        cfg = tmp_path / "main.json"
        cfg.write_text(json.dumps(
            {"server": {"stxm_address": "beamline.example", "command_port": 4321}}))
        monkeypatch.delenv("PYSTXM_SERVER_HOST", raising=False)
        monkeypatch.setenv("PYSTXM_MAIN_JSON", str(cfg))
        assert server._default_server() == ("beamline.example", 4321)

    def test_unreadable_main_json_falls_back_to_localhost(self, monkeypatch, tmp_path):
        bad = tmp_path / "main.json"
        bad.write_text("{not json")
        monkeypatch.delenv("PYSTXM_SERVER_HOST", raising=False)
        monkeypatch.setenv("PYSTXM_MAIN_JSON", str(bad))
        assert server._default_server() == ("127.0.0.1", 9999)


class TestConnectToServer:
    """The one tool the server still owns."""

    @patch("pystxmcontrol.mcp.server.scripter")
    def test_success_reports_the_motors_it_found(self, mock_scripter):
        instance = Mock()
        instance.MOTORS = None
        instance.get_config.return_value = (
            {f"Motor{i}": {} for i in range(10)}, {"Image": {}}, {}, {}, {"lastScan": {}})
        mock_scripter.return_value = instance

        result = server.connect_to_server(host="192.168.1.100", port=8888)

        mock_scripter.assert_called_once_with("192.168.1.100", 8888)
        assert "192.168.1.100:8888" in result
        assert "10 motors" in result
        assert server._TOOLSET is not None

    @patch("pystxmcontrol.mcp.server._default_server", return_value=("127.0.0.1", 9999))
    @patch("pystxmcontrol.mcp.server.scripter")
    def test_no_arguments_uses_the_configured_instrument(self, mock_scripter, _default):
        instance = Mock()
        instance.MOTORS = None
        instance.get_config.return_value = ({"SampleX": {}}, {}, {}, {}, {})
        mock_scripter.return_value = instance

        server.connect_to_server()
        mock_scripter.assert_called_once_with("127.0.0.1", 9999)

    @patch("pystxmcontrol.mcp.server._default_server", return_value=("127.0.0.1", 9999))
    @patch("pystxmcontrol.mcp.server.scripter", side_effect=TimeoutError("timed out"))
    def test_timeout_is_reported_not_raised(self, _scripter, _default):
        result = server.connect_to_server()
        assert "timed out" in result and "127.0.0.1:9999" in result
        assert server._TOOLSET is None

    @patch("pystxmcontrol.mcp.server.scripter", side_effect=ConnectionError("refused"))
    def test_connection_error_is_reported_not_raised(self, _scripter):
        result = server.connect_to_server(host="h", port=1)
        assert "Failed to connect to h:1" in result and "refused" in result


class TestLazyConnection:
    """Tools connect on demand, so 'forgot to connect' is not a failure mode."""

    @patch("pystxmcontrol.mcp.server._default_server", return_value=("127.0.0.1", 9999))
    @patch("pystxmcontrol.mcp.server.scripter")
    def test_toolset_is_built_on_first_use(self, mock_scripter, _default):
        instance = Mock()
        instance.MOTORS = None
        instance.get_config.return_value = ({"SampleX": {}}, {}, {}, {}, {})
        mock_scripter.return_value = instance

        assert server._TOOLSET is None
        first = server._toolset()
        assert first is not None
        assert server._toolset() is first          # built once, reused
        assert mock_scripter.call_count == 1

import pytest
import json
from unittest.mock import Mock, MagicMock, patch, call
from pystxmcontrol.mcp import server


class TestCheckMotorStatus:
    """Test check_motor_status function"""

    def test_check_motor_status_exists(self):
        """Test motor status when motor exists"""
        server.MOTORS = {"SampleX": {}, "SampleY": {}, "Energy": {}}

        result = server.check_motor_status("SampleX")

        assert result is True

    def test_check_motor_status_not_exists(self):
        """Test motor status when motor doesn't exist"""
        server.MOTORS = {"SampleX": {}, "SampleY": {}}

        result = server.check_motor_status("InvalidMotor")

        assert result is False

    def test_check_motor_status_none(self):
        """Test motor status when MOTORS is None"""
        server.MOTORS = None

        with pytest.raises(AttributeError):
            server.check_motor_status("SampleX")


class TestDefineScanlFromFile:
    """Test define_scan_from_file function"""

    @patch('pystxmcontrol.mcp.server.stxm_utils.scan_from_stxm')
    def test_define_scan_from_file_success(self, mock_scan_from_stxm):
        """Test successful scan definition from file"""
        mock_scripter = Mock()
        server.SCRIPTER = mock_scripter

        mock_scan = {
            "proposal": "Test-001",
            "experimenters": "Smith",
            "xcenter": 0,
            "ycenter": 0
        }
        mock_scan_from_stxm.return_value = mock_scan

        result = server.define_scan_from_file("/path/to/file.nxs")

        mock_scan_from_stxm.assert_called_once_with("/path/to/file.nxs")
        assert mock_scripter.scan == mock_scan
        assert "Generated a new scan from file" in result

    @patch('pystxmcontrol.mcp.server.stxm_utils.scan_from_stxm')
    def test_define_scan_from_file_failure(self, mock_scan_from_stxm):
        """Test scan definition failure"""
        mock_scripter = Mock()
        server.SCRIPTER = mock_scripter

        mock_scan_from_stxm.side_effect = Exception("File not found")

        result = server.define_scan_from_file("/invalid/path.nxs")

        assert "Failed to generate the scan" in result


class TestUpdateScan:
    """Test update_scan function"""

    @patch('pystxmcontrol.mcp.server.stxm_utils.convert_scan')
    @patch('pystxmcontrol.mcp.server._ensure_connected', return_value=None)
    def test_update_scan_with_kwargs(self, mock_ensure, mock_convert):
        """update_scan loads the baseline then delegates only the changed
        (non-None) parameters to scripter.update_scan."""
        mock_scripter = Mock()
        mock_scripter.update_scan.return_value = "Scan updated."
        mock_convert.return_value = {"x_center": 0, "y_center": 0}
        server.SCRIPTER = mock_scripter
        server.CONFIG = {"lastScan": {"Image": {"scan_type": "Image"}}}

        result = server.update_scan(x_center=10.5, y_center=-5.0, dwell=0.5)

        _, called = mock_scripter.update_scan.call_args
        assert called["x_center"] == 10.5
        assert called["y_center"] == -5.0
        assert called["dwell"] == 0.5
        assert "x_range" not in called          # unset params are filtered out
        assert "updated" in result.lower()

    @patch('pystxmcontrol.mcp.server.stxm_utils.convert_scan')
    @patch('pystxmcontrol.mcp.server._ensure_connected', return_value=None)
    def test_update_scan_no_kwargs(self, mock_ensure, mock_convert):
        """update_scan with no changed params still loads the baseline and
        delegates (only the default scan_type is forwarded)."""
        mock_scripter = Mock()
        mock_scripter.update_scan.return_value = "Scan updated."
        mock_convert.return_value = {"x_center": 0}
        server.SCRIPTER = mock_scripter
        server.CONFIG = {"lastScan": {"Image": {"scan_type": "Image"}}}

        result = server.update_scan()

        mock_scripter.update_scan.assert_called_once()
        assert "updated" in result.lower()


class TestGetMotorPosition:
    """Test get_motor_position function"""

    def test_get_motor_position_success(self):
        """Test successful motor position retrieval"""
        server.MOTORS = {"SampleX": {}, "SampleY": {}}

        mock_scripter = Mock()
        mock_scripter.get_motor_position.return_value = 12.345
        server.SCRIPTER = mock_scripter

        result = server.get_motor_position("SampleX")

        mock_scripter.get_motor_position.assert_called_once_with("SampleX")
        assert "12.345" in result
        assert "SampleX" in result

    def test_get_motor_position_invalid_motor(self):
        """Test motor position with invalid motor"""
        server.MOTORS = {"SampleX": {}, "SampleY": {}}

        mock_scripter = Mock()
        server.SCRIPTER = mock_scripter

        result = server.get_motor_position("InvalidMotor")

        assert "failed" in result.lower()
        mock_scripter.get_motor_position.assert_not_called()

    def test_get_motor_position_exception(self):
        """Test motor position with exception"""
        server.MOTORS = {"SampleX": {}}

        mock_scripter = Mock()
        mock_scripter.get_motor_position.side_effect = Exception("Communication error")
        server.SCRIPTER = mock_scripter

        result = server.get_motor_position("SampleX")

        assert "Failed to get position" in result


class TestConnectToServer:
    """Test connect_to_server function"""

    @patch('pystxmcontrol.mcp.server.scripter')
    def test_connect_to_server_success(self, mock_scripter_class):
        """Test successful server connection"""
        mock_scripter_instance = Mock()
        mock_scripter_class.return_value = mock_scripter_instance

        motors = {f"Motor{i}": {} for i in range(10)}
        scans = {"Image": {}}
        positions = {}
        daqs = {}
        config = {}

        mock_scripter_instance.get_config.return_value = [motors, scans, positions, daqs, config]

        result = server.connect_to_server(host="192.168.1.100", port=8888)

        mock_scripter_class.assert_called_once_with("192.168.1.100", 8888)
        mock_scripter_instance.get_config.assert_called_once()

        assert server.SCRIPTER == mock_scripter_instance
        assert server.MOTORS == motors
        assert server.SCANS == scans

        assert "Successfully connected" in result
        assert "192.168.1.100:8888" in result
        assert "10 motors" in result

    @patch('pystxmcontrol.mcp.server._default_server', return_value=('127.0.0.1', 9999))
    @patch('pystxmcontrol.mcp.server.scripter')
    def test_connect_to_server_timeout(self, mock_scripter_class, mock_default):
        """Test server connection timeout (address resolved from _default_server)."""
        mock_scripter_instance = Mock()
        mock_scripter_class.return_value = mock_scripter_instance

        mock_scripter_instance.get_config.side_effect = TimeoutError("Connection timeout")

        result = server.connect_to_server()

        assert "Connection timeout" in result
        assert "127.0.0.1:9999" in result

    @patch('pystxmcontrol.mcp.server.scripter')
    def test_connect_to_server_connection_error(self, mock_scripter_class):
        """Test server connection error"""
        mock_scripter_instance = Mock()
        mock_scripter_class.return_value = mock_scripter_instance

        mock_scripter_instance.get_config.side_effect = ConnectionError("Cannot connect")

        result = server.connect_to_server()

        assert "Connection error" in result

    @patch('pystxmcontrol.mcp.server.scripter')
    def test_connect_to_server_generic_error(self, mock_scripter_class):
        """Test server connection generic error"""
        mock_scripter_instance = Mock()
        mock_scripter_class.return_value = mock_scripter_instance

        mock_scripter_instance.get_config.side_effect = ValueError("Invalid config")

        result = server.connect_to_server()

        assert "Failed to connect" in result
        assert "ValueError" in result


class TestMoveMotor:
    """Test move_motor function"""

    def test_move_motor_success(self):
        """Test successful motor move"""
        server.MOTORS = {"SampleX": {}, "SampleY": {}}

        mock_scripter = Mock()
        mock_scripter.move_motor.return_value = {"status": True, "data": "Move complete"}
        server.SCRIPTER = mock_scripter

        result = server.move_motor(axis="SampleX", pos=15.5)

        mock_scripter.move_motor.assert_called_once_with("SampleX", 15.5)
        assert "Successfully moved motor SampleX to 15.5" in result

    def test_move_motor_invalid_motor(self):
        """Test move motor with invalid motor name"""
        server.MOTORS = {"SampleX": {}, "SampleY": {}}

        mock_scripter = Mock()
        server.SCRIPTER = mock_scripter

        result = server.move_motor(axis="InvalidMotor", pos=10.0)

        assert "failed" in result.lower()
        mock_scripter.move_motor.assert_not_called()

    @patch('pystxmcontrol.mcp.server._ensure_connected')
    def test_move_motor_no_connection(self, mock_ensure):
        """Move motor surfaces a failure from lazy auto-connect (no server)."""
        mock_ensure.return_value = (
            "Not connected, and auto-connect to 1.2.3.4:9999 failed: boom")

        result = server.move_motor(axis="SampleX", pos=10.0)

        assert "auto-connect" in result
        mock_ensure.assert_called_once()

    def test_move_motor_failure(self):
        """Test motor move failure"""
        server.MOTORS = {"SampleX": {}}

        mock_scripter = Mock()
        mock_scripter.move_motor.return_value = {
            "status": False,
            "data": "Motor limit reached"
        }
        server.SCRIPTER = mock_scripter

        result = server.move_motor(axis="SampleX", pos=100.0)

        assert "Motor limit reached" in result

    def test_move_motor_exception(self):
        """Test motor move with exception"""
        server.MOTORS = {"SampleX": {}}

        mock_scripter = Mock()
        mock_scripter.move_motor.side_effect = Exception("Network error")
        server.SCRIPTER = mock_scripter

        result = server.move_motor(axis="SampleX", pos=10.0)

        assert "Failed to communicate" in result


class TestGetConfig:
    """Test get_config function"""

    @staticmethod
    def _mock_scripter():
        mock_scripter = Mock()
        motors = {"SampleX": {"type": "primary", "unit": "um",
                              "minScanValue": 0, "maxScanValue": 100,
                              "last value": 50, "driver": "smaract"}}
        scans = {"Image": {"driver": "line_image"}}
        positions = {"SampleX": 50}
        daqs = {"default": {}}
        config = {"server": {"data_dir": "/data"},
                  "lastScan": {"Image": {"dwell": 1.0}},
                  "staff_password_hash": "SECRET", "staff_password_salt": "SECRET"}
        mock_scripter.get_config.return_value = [motors, scans, positions, daqs, config]
        return mock_scripter, (motors, scans, positions, daqs, config)

    def test_get_config_summary_default(self):
        """Default returns a compact summary, not the full dump."""
        mock_scripter, (motors, scans, positions, daqs, config) = self._mock_scripter()
        server.SCRIPTER = mock_scripter

        result_dict = json.loads(server.get_config())

        assert result_dict["scan_types"] == ["Image"]
        assert result_dict["positions"] == positions
        assert result_dict["daqs"] == ["default"]
        # motor summary keeps units/limits, drops driver/calibration fields
        assert result_dict["motors"]["SampleX"] == {
            "type": "primary", "unit": "um", "min": 0, "max": 100, "value": 50}
        assert "driver" not in result_dict["motors"]["SampleX"]
        assert "hint" in result_dict

    def test_get_config_sections(self):
        """Named sections return the full underlying data."""
        mock_scripter, (motors, scans, positions, daqs, config) = self._mock_scripter()
        server.SCRIPTER = mock_scripter

        assert json.loads(server.get_config("scans")) == scans
        assert json.loads(server.get_config("motors")) == motors
        assert json.loads(server.get_config("positions")) == positions
        assert json.loads(server.get_config("daqs")) == daqs
        assert json.loads(server.get_config("lastScan")) == config["lastScan"]

        all_dict = json.loads(server.get_config("all"))
        assert all_dict["motors"] == motors
        assert all_dict["scans"] == scans

    def test_get_config_strips_secrets(self):
        """staff-password secrets never appear in any section."""
        mock_scripter, _ = self._mock_scripter()
        server.SCRIPTER = mock_scripter

        for sec in (None, "config", "all", "lastScan"):
            assert "staff_password" not in server.get_config(sec).lower()

    def test_get_config_unknown_section(self):
        """Unknown section returns a helpful error, not a crash."""
        mock_scripter, _ = self._mock_scripter()
        server.SCRIPTER = mock_scripter
        assert "Unknown section" in server.get_config("bogus")

    def test_get_config_exception(self):
        """Test get_config with exception"""
        mock_scripter = Mock()
        mock_scripter.get_config.side_effect = Exception("Network error")
        server.SCRIPTER = mock_scripter

        result = server.get_config()

        assert "Failed to communicate" in result
        assert "Network error" in result


class TestStxmScan:
    """Test stxm_scan function"""

    def test_stxm_scan_success(self):
        """Test successful STXM scan"""
        mock_scripter = Mock()
        mock_scripter.stxm_scan.return_value = "/data/scan_001.nxs"
        server.SCRIPTER = mock_scripter

        result = server.stxm_scan()

        mock_scripter.stxm_scan.assert_called_once()
        assert "Completed scan stxm" in result
        assert "/data/scan_001.nxs" in result

    def test_stxm_scan_failure(self):
        """Test STXM scan failure"""
        mock_scripter = Mock()
        mock_scripter.stxm_scan.side_effect = Exception("Scan error")
        server.SCRIPTER = mock_scripter

        result = server.stxm_scan()

        assert "Failed to execute the STXM scan" in result


class TestPlotMotorPositions:
    """Test plot_motor_positions function"""

    @patch('pystxmcontrol.mcp.server.stxm_utils.plot_motor_positions')
    def test_plot_motor_positions_default(self, mock_plot):
        """Test plotting with default parameters"""
        server.CONFIG = {"server": {"data_dir": "/data"}}

        mock_plot.return_value = "/tmp/SampleX_position_plot.png"

        result = server.plot_motor_positions(axis="SampleX")

        mock_plot.assert_called_once()
        assert result == "/tmp/SampleX_position_plot.png"

    @patch('pystxmcontrol.mcp.server.stxm_utils.plot_motor_positions')
    def test_plot_motor_positions_with_date(self, mock_plot):
        """Test plotting with specific date"""
        server.CONFIG = {"server": {"data_dir": "/data"}}

        mock_plot.return_value = "/tmp/plot.png"

        result = server.plot_motor_positions(
            axis="SampleX",
            date="2026-01-15",
            file_path="/tmp/plot.png"
        )

        assert result == "/tmp/plot.png"

    @patch('pystxmcontrol.mcp.server.stxm_utils.plot_motor_positions')
    def test_plot_motor_positions_with_time_range(self, mock_plot):
        """Test plotting with time range"""
        server.CONFIG = {"server": {"data_dir": "/data"}}

        mock_plot.return_value = "/tmp/plot.png"

        result = server.plot_motor_positions(
            axis="SampleX",
            start_time="1736420000",
            end_time="1736506400"
        )

        # Verify timestamps were converted to floats
        call_args = mock_plot.call_args
        assert isinstance(call_args[1]['start_time'], float)
        assert isinstance(call_args[1]['end_time'], float)

    @patch('pystxmcontrol.mcp.server.stxm_utils.plot_motor_positions')
    def test_plot_motor_positions_no_data(self, mock_plot):
        """Test plotting with no data found"""
        server.CONFIG = {"server": {"data_dir": "/data"}}

        mock_plot.return_value = "No data found for motor"

        result = server.plot_motor_positions(axis="SampleX")

        assert "No data found" in result

    @patch('pystxmcontrol.mcp.server.stxm_utils.plot_motor_positions')
    def test_plot_motor_positions_invalid_time_format(self, mock_plot):
        """Test plotting with invalid time format"""
        server.CONFIG = {"server": {"data_dir": "/data"}}

        result = server.plot_motor_positions(
            axis="SampleX",
            start_time="invalid-time"
        )

        assert "Invalid start_time format" in result

    @patch('pystxmcontrol.mcp.server.stxm_utils.plot_motor_positions')
    def test_plot_motor_positions_exception(self, mock_plot):
        """Test plotting with exception"""
        server.CONFIG = {"server": {"data_dir": "/data"}}

        mock_plot.side_effect = Exception("Database error")

        result = server.plot_motor_positions(axis="SampleX")

        assert "Error generating plot" in result
        assert "Database error" in result

import pytest
import zmq
from unittest.mock import Mock, MagicMock, patch
from pystxmcontrol.controller.scripter import scripter


class TestScripterInit:
    """Test scripter initialization"""

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_scripter_initialization(self, mock_context):
        """Test that scripter initializes with correct defaults"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter(host="192.168.1.1", port=8888, timeout=3000)

        # Verify ZMQ setup
        mock_context.assert_called_once()
        mock_context.return_value.socket.assert_called_once_with(zmq.REQ)
        mock_socket.setsockopt.assert_any_call(zmq.RCVTIMEO, 3000)
        mock_socket.setsockopt.assert_any_call(zmq.SNDTIMEO, 3000)
        mock_socket.connect.assert_called_once_with("tcp://192.168.1.1:8888")

        # Verify default scan parameters
        assert s.scan["proposal"] == "BLS-000001"
        assert s.scan["experimenters"] == "Shapiro"
        assert s.scan["x_center"] == 0
        assert s.scan["x_range"] == 5
        assert s.scan["x_points"] == 50
        assert s.scan["y_center"] == 0
        assert s.scan["y_range"] == 5
        assert s.scan["y_points"] == 50
        assert s.scan["dwell"] == 0.2
        assert s.scan["autofocus"] is True
        assert s.scan["spiral"] is False

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_scripter_default_host_port(self, mock_context):
        """Test scripter with default host and port"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()

        mock_socket.connect.assert_called_once_with("tcp://127.0.0.1:9999")


class TestScripterMethods:
    """Test scripter methods"""

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_move_motor_success(self, mock_context):
        """Test successful motor move"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()
        s.MOTORS = {"SampleX": {}, "SampleY": {}}

        mock_socket.recv_pyobj.return_value = {"status": True, "data": "Motor moved"}

        result = s.move_motor(axis="SampleX", pos=10.5)

        expected_message = {"command": "moveMotor", "axis": "SampleX", "pos": 10.5}
        mock_socket.send_pyobj.assert_called_once_with(expected_message)
        assert result == {"status": True, "data": "Motor moved"}

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_move_motor_invalid_motor(self, mock_context):
        """Test motor move with invalid motor name"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()
        s.MOTORS = {"SampleX": {}, "SampleY": {}}

        result = s.move_motor(axis="InvalidMotor", pos=10.5)

        # Should return early without sending message
        mock_socket.send_pyobj.assert_not_called()
        assert result is None

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_get_config_success(self, mock_context):
        """Test successful config retrieval"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()

        motors = {"SampleX": {}, "SampleY": {}}
        scans = {"Image": {"driver": "line_image"}}
        positions = {"SampleX": 0, "SampleY": 0}
        daqs = {"default": {}}
        config = {"server": {"data_dir": "/data"}}

        mock_socket.recv_pyobj.return_value = {
            "data": [motors, scans, positions, daqs, config]
        }

        result = s.get_config()

        expected_message = {"command": "get_config"}
        mock_socket.send_pyobj.assert_called_once_with(expected_message)

        assert result == [motors, scans, positions, daqs, config]
        assert s.MOTORS == motors
        assert s.SCANS == scans
        assert s.POSITIONS == positions
        assert s.DAQS == daqs
        assert s.CONFIG == config

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_get_config_timeout(self, mock_context):
        """Test config retrieval with timeout"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()

        mock_socket.recv_pyobj.side_effect = zmq.Again()

        with pytest.raises(TimeoutError, match="Timeout waiting for response"):
            s.get_config()

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_get_config_zmq_error(self, mock_context):
        """Test config retrieval with ZMQ error"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()

        mock_socket.recv_pyobj.side_effect = zmq.ZMQError("Connection failed")

        with pytest.raises(ConnectionError, match="ZMQ error communicating with server"):
            s.get_config()

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_read_daq(self, mock_context):
        """Test DAQ reading"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()

        mock_socket.recv_pyobj.return_value = {"data": 12345}

        result = s.read_daq(daq="default", dwell=0.5, shutter=True)

        expected_message = {"command": "get_data", "daq": "default", "dwell": 0.5, "shutter": True}
        mock_socket.send_pyobj.assert_called_once_with(expected_message)
        assert result == 12345

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_start_monitor(self, mock_context):
        """Test starting monitor"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()

        mock_socket.recv_pyobj.return_value = {"status": True}

        result = s.start_monitor()

        expected_message = {"command": "start_monitor"}
        mock_socket.send_pyobj.assert_called_once_with(expected_message)
        assert result is True

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_stop_monitor(self, mock_context):
        """Test stopping monitor"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()

        mock_socket.recv_pyobj.return_value = {"status": True}

        result = s.stop_monitor()

        expected_message = {"command": "stop_monitor"}
        mock_socket.send_pyobj.assert_called_once_with(expected_message)
        assert result is True

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_get_motor_position(self, mock_context):
        """Test getting motor position"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()

        mock_socket.recv_pyobj.return_value = {
            'data': {'SampleX': 12.345, 'SampleY': -5.678}
        }

        result = s.get_motor_position('SampleX')

        expected_message = {"command": "getMotorPositions"}
        mock_socket.send_pyobj.assert_called_once_with(expected_message)
        assert result == 12.345


class TestScripterScanMethods:
    """Test scripter scan-related methods"""

    @patch('pystxmcontrol.controller.scripter.sleep')
    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_stxm_scan_success(self, mock_context, mock_sleep):
        """Test successful STXM scan"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()
        s.SCANS = {"Image": {"driver": "line_image", "mode": "raster"}}

        # Mock responses
        mock_socket.recv_pyobj.side_effect = [
            {"status": True, "data": "/data/scan_001.nxs"},  # scan command response
            {"status": False},  # first getStatus (scan in progress)
            {"status": True}   # second getStatus (scan complete)
        ]

        result = s.stxm_scan()

        assert result == "/data/scan_001.nxs"
        assert mock_sleep.call_count == 2

    @patch('pystxmcontrol.controller.scripter.sleep')
    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_stxm_scan_with_energy_list(self, mock_context, mock_sleep):
        """Test STXM scan with energy list"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()
        s.SCANS = {"Image": {"driver": "line_image", "mode": "raster"}}
        s.scan["energy_list"] = [700, 705, 710, 715]

        mock_socket.recv_pyobj.side_effect = [
            {"status": True, "data": "/data/scan_001.nxs"},
            {"status": True}
        ]

        result = s.stxm_scan()

        # The energy list is resolved into the energy region the server receives.
        # (stxm_scan used to also back-fill energy_start/stop/points onto s.scan as a
        # side effect of launching; build_server_scan derives them without mutating the
        # caller's working definition, so assert on what actually goes on the wire.)
        assert result == "/data/scan_001.nxs"
        sent = mock_socket.send_pyobj.call_args_list[0][0][0]["scan"]
        region = sent["energy_regions"]["EnergyRegion1"]
        assert region["start"] == 700
        assert region["stop"] == 715
        assert region["n_energies"] == 4
        assert sent["energy_list"] == [700, 705, 710, 715]

    @patch('pystxmcontrol.controller.scripter.zmq.Context')
    def test_stxm_scan_failure(self, mock_context):
        """Test STXM scan failure"""
        mock_socket = MagicMock()
        mock_context.return_value.socket.return_value = mock_socket

        s = scripter()
        s.SCANS = {"Image": {"driver": "line_image", "mode": "raster"}}

        mock_socket.recv_pyobj.return_value = {"status": False}

        result = s.stxm_scan()

        assert result is False

"""
ZMQ Publisher for pystxmcontrol

Handles all ZeroMQ socket management and publishing for:
- CCD frame data
- STXM scan data
- Scan start/stop events

Separated from dataHandler for clarity and testability.
"""

import zmq
import zmq.asyncio
import atexit


class ZMQPublisher:
    """
    Manages ZeroMQ publishing sockets for real-time data streaming.

    Publishes:
    - CCD frames to preprocessing pipeline
    - STXM data to GUI and downstream viewers
    - Scan events (start/stop)
    """

    def __init__(self, config, daq_dict=None, logger=None):
        """
        Initialize ZMQ publisher sockets

        :param config: Configuration dictionary with server settings
        :param daq_dict: Dictionary of DAQ devices (optional, for CCD detection)
        :param logger: Optional logger for error reporting
        """
        self._logger = logger
        self._publish_zmq = config.get("publish_zmq", True)

        # Create async ZMQ context
        self.context = zmq.asyncio.Context()

        # Socket references
        self.ccd_pub_socket = None
        self.stxm_pub_socket = None

        # Setup CCD publisher if CCD DAQ is present
        if daq_dict and "CCD" in daq_dict and self._publish_zmq:
            self._setup_ccd_publisher(config)

        # Setup STXM publisher (always created)
        self._setup_stxm_publisher(config)

        # Register cleanup handler
        atexit.register(self.cleanup)

    def _setup_ccd_publisher(self, config):
        """Setup CCD frame publisher socket"""
        host = config.get("host", "localhost")
        port = config.get("ccd_data_port", 9997)

        self.ccd_pub_address = f'tcp://{host}:{port}'
        self.ccd_pub_socket = self.context.socket(zmq.PUB)
        self.ccd_pub_socket.set_hwm(2000)  # High water mark for buffering
        self.ccd_pub_socket.bind(self.ccd_pub_address)

        print(f"Publishing CCD frames on: {self.ccd_pub_address}")
        if self._logger:
            self._logger.log(f"CCD publisher bound to {self.ccd_pub_address}", level="info")

    def _setup_stxm_publisher(self, config):
        """Setup STXM data publisher socket"""
        host = config.get("host", "localhost")
        port = config.get("stxm_data_port", 9998)

        self.stxm_pub_address = f'tcp://{host}:{port}'
        self.stxm_pub_socket = self.context.socket(zmq.PUB)
        self.stxm_pub_socket.bind(self.stxm_pub_address)

        print(f"Publishing STXM data on: {self.stxm_pub_address}")
        if self._logger:
            self._logger.log(f"STXM publisher bound to {self.stxm_pub_address}", level="info")

    def publish_ccd_frame(self, data):
        """
        Publish CCD frame data

        :param data: Dictionary containing CCD frame data and metadata
        """
        if not self._publish_zmq or self.ccd_pub_socket is None:
            return

        try:
            self.ccd_pub_socket.send_pyobj(data)
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error publishing CCD frame: {e}", level="error")
            else:
                print(f"Error publishing CCD frame: {e}")

    def publish_stxm_data(self, data):
        """
        Publish STXM scan data, subscribed by mainwindow

        :param data: Dictionary containing STXM data and metadata
        """
        if self.stxm_pub_socket is None:
            return

        try:
            self.stxm_pub_socket.send_pyobj(data)
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error publishing STXM data: {e}", level="error")
            else:
                print(f"Error publishing STXM data: {e}")

    def publish_stxm_string(self, data):
        """
        Publish STXM data as JSON string

        :param data: Dictionary to be sent as JSON
        """
        if not self._publish_zmq or self.stxm_pub_socket is None:
            return

        try:
            import json
            self.stxm_pub_socket.send_string(json.dumps(data))
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error publishing STXM string: {e}", level="error")
            else:
                print(f"Error publishing STXM string: {e}")

    def send_scan_start_event(self, scan, metadata=None):
        """
        Send scan start event

        :param scan: Scan definition dictionary
        :param metadata: Optional additional metadata
        """
        if not self._publish_zmq or self.ccd_pub_socket is None:
            return

        event_data = {
            'event': 'start',
            'data': scan,
            'metadata': metadata
        }

        try:
            self.ccd_pub_socket.send_pyobj(event_data)
            if self._logger:
                self._logger.log("Scan start event published", level="debug")
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error publishing scan start event: {e}", level="error")
            else:
                print(f"Error publishing scan start event: {e}")

    def send_scan_stop_event(self):
        """Send scan stop event"""
        if not self._publish_zmq or self.ccd_pub_socket is None:
            return

        event_data = {
            'event': 'stop',
            'data': None
        }

        try:
            self.ccd_pub_socket.send_pyobj(event_data)
            if self._logger:
                self._logger.log("Scan stop event published", level="debug")
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error publishing scan stop event: {e}", level="error")
            else:
                print(f"Error publishing scan stop event: {e}")

    def cleanup(self):
        """
        Cleanup method to properly close ZMQ sockets.
        Called automatically on program exit via atexit.
        """
        try:
            if hasattr(self, 'stxm_pub_socket') and self.stxm_pub_socket is not None:
                self.stxm_pub_socket.close(linger=0)
                if self._logger:
                    self._logger.log("STXM publisher socket closed", level="info")
                else:
                    print("STXM publisher socket closed")
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error closing stxm_pub_socket: {e}", level="error")
            else:
                print(f"Error closing stxm_pub_socket: {e}")

        try:
            if hasattr(self, 'ccd_pub_socket') and self.ccd_pub_socket is not None:
                self.ccd_pub_socket.close(linger=0)
                if self._logger:
                    self._logger.log("CCD publisher socket closed", level="info")
                else:
                    print("CCD publisher socket closed")
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error closing ccd_pub_socket: {e}", level="error")
            else:
                print(f"Error closing ccd_pub_socket: {e}")

        try:
            if hasattr(self, 'context') and self.context is not None:
                self.context.term()
                if self._logger:
                    self._logger.log("ZMQ context terminated", level="info")
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error terminating ZMQ context: {e}", level="error")
            else:
                print(f"Error terminating ZMQ context: {e}")

    def __del__(self):
        """Destructor - ensure cleanup is called"""
        self.cleanup()

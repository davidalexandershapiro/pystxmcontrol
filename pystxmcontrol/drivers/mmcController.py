# -*- coding: utf-8 -*-
"""Micronix MMC controller driver.

Transaction layer only: framing (axis prefix + CR), response parsing
(# payload), and transport (serial or TCP, chosen from the address).
No locking here -- the IOC layer's per-controller io_lock serializes all
link I/O (see pystxmcontrol.iocs.base.MotorRecordGroup).
"""
import socket

from pystxmcontrol.controller.hardwareController import hardwareController


class MMCError(IOError):
    """A malformed/absent MMC response or a failed MMC motion."""


class _TcpLineTransport:
    """Line-oriented TCP transport matching pyserial's write/readline API."""

    def __init__(self, host, port, timeout=1.0):
        self._sock = socket.create_connection((host, int(port)), timeout=timeout)
        self._sock.settimeout(timeout)
        self._file = self._sock.makefile("rb")

    def write(self, data: bytes):
        self._sock.sendall(data)

    def readline(self) -> bytes:
        try:
            return self._file.readline()
        except socket.timeout:
            return b""

    def close(self):
        try:
            self._file.close()
        finally:
            self._sock.close()


class mmcController(hardwareController):

    def __init__(self, address="COM3", port=None, simulation=False):
        self.address = address
        self.port = port
        self.simulation = simulation
        self._transport = None
        # Simulation state, shared by all mmcMotor instances on this
        # controller: axis number -> position (controller units) / velocity.
        self.positions = {}
        self.velocities = {}

    def _is_serial_address(self) -> bool:
        addr = str(self.address)
        return addr.upper().startswith("COM") or addr.startswith("/dev/")

    def _open_transport(self):
        if self._is_serial_address():
            import serial
            return serial.Serial(port=str(self.address), baudrate=38400,
                                 bytesize=8, timeout=1,
                                 stopbits=serial.STOPBITS_ONE)
        if self.port in (None, 0):
            raise MMCError(
                f"TCP address {self.address!r} requires a nonzero port")
        return _TcpLineTransport(str(self.address), self.port, timeout=1.0)

    def initialize(self, simulation=False):
        self.simulation = simulation
        if self.simulation:
            return
        print(f"Connecting to MMC controller on {self.address}"
              + (f":{self.port}" if not self._is_serial_address() else ""),
              flush=True)
        self._transport = self._open_transport()

    def command(self, axis, cmd):
        """Fire-and-forget command; no reply expected."""
        if self.simulation:
            return
        self._transport.write(f"{int(axis)}{cmd}\r".encode())

    def query(self, axis, cmd) -> str:
        """Send a query and return the reply payload (text after '#')."""
        if self.simulation:
            raise MMCError("query() has no meaning in simulation mode")
        self._transport.write(f"{int(axis)}{cmd}\r".encode())
        raw = self._transport.readline().decode(errors="replace").strip()
        if not raw.startswith("#"):
            raise MMCError(
                f"malformed MMC reply to {cmd!r} on axis {axis}: {raw!r}")
        return raw[1:]

    def get_errors(self, axis) -> str:
        """Best-effort ERR? readout for diagnostics; never raises."""
        try:
            return self.query(axis, "ERR?")
        except Exception:
            return ""

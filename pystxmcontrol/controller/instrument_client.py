"""The narrow control-server surface the agent tools depend on, plus a scripter adapter.

``ToolSet`` was written against the GUI's ``stxm_client``, but it uses only nine of its
members.  Naming those nine is what lets the same tool implementations run on both agent
surfaces: in-process in the GUI over ``stxm_client``, and out-of-process in the MCP server
over ``ScripterClient`` below.

The member names are ``stxm_client``'s, camelCase and all — deliberately.  The point of a
port is that the widely-used side needs no edits; renaming them would touch every tool for
no behavioural gain.

``stxm_client`` lives in ``client.py``, which imports PySide6 at module scope.  This module
must NOT, or the MCP server could not use the port headlessly.
"""

from typing import Any, Protocol, runtime_checkable

# The nine members. Kept as data so tests (and the MCP server) can check conformance
# without instantiating a client, which would need a live control server.
CLIENT_METHODS = ("send_message", "get_status", "get_config",
                  "getMotorPositions", "change_motor_config")
# Populated by get_config(), so absent until it has been called once.
CLIENT_ATTRIBUTES = ("motorInfo", "scanConfig", "currentMotorPositions", "main_config")


@runtime_checkable
class InstrumentClient(Protocol):
    """What the agent tools need from a connection to the control server.

    Note ``runtime_checkable`` only verifies the METHODS at isinstance() time; the four
    data attributes are checked against :data:`CLIENT_ATTRIBUTES` explicitly.
    """

    # Refreshed by get_config(); the server returns all four in one response.
    motorInfo: dict
    scanConfig: dict
    currentMotorPositions: dict
    main_config: dict

    def send_message(self, message: dict) -> dict:
        """Send one command dict to the server and return its response."""
        ...

    def get_status(self) -> dict:
        """Server status; ``response["mode"]`` is 'scanning' or 'idle'."""
        ...

    def get_config(self) -> None:
        """Refresh the four cached config attributes from the server."""
        ...

    def getMotorPositions(self) -> dict:
        """Force a live hardware poll of every motor and return fresh positions."""
        ...

    def change_motor_config(self, motor: str, key: str, value: Any) -> None:
        """Write one motor-config field on the server, then re-read the config."""
        ...


def missing_members(obj) -> list[str]:
    """Names from the port that *obj* does not provide.

    Accepts a class or an instance.  On a CLASS the four data attributes are not
    expected — they are assigned by ``get_config()`` at runtime — so only the methods
    are checked there.
    """
    missing = [name for name in CLIENT_METHODS if not callable(getattr(obj, name, None))]
    if not isinstance(obj, type):
        missing += [name for name in CLIENT_ATTRIBUTES if not hasattr(obj, name)]
    return missing


class ScripterClient:
    """:class:`InstrumentClient` over a ``scripter`` connection.

    ``scripter`` and ``stxm_client`` are two ZMQ clients for the same server that grew
    apart: ``scripter`` exposes a raw socket and upper-case config attributes, while
    ``stxm_client`` exposes ``send_message`` and camelCase ones.  The two unpack the SAME
    five-tuple from the server's get_config response, so the mapping is exact:

        MOTORS -> motorInfo        SCANS -> scanConfig        POSITIONS -> currentMotorPositions
        DAQS   -> daqConfig        CONFIG -> main_config
    """

    def __init__(self, scripter):
        self._scripter = scripter
        self.motorInfo: dict = {}
        self.scanConfig: dict = {}
        self.currentMotorPositions: dict = {}
        self.daqConfig: dict = {}
        self.main_config: dict = {}
        # Adopt whatever the scripter already fetched, so a client built on an
        # already-connected scripter (the MCP server's _ensure_connected does that)
        # starts warm instead of needing a redundant round-trip.
        if getattr(scripter, "MOTORS", None) is not None:
            self._adopt(scripter.MOTORS, scripter.SCANS, scripter.POSITIONS,
                        scripter.DAQS, scripter.CONFIG)

    def _adopt(self, motors, scans, positions, daqs, config) -> None:
        self.motorInfo = motors
        self.scanConfig = scans
        self.currentMotorPositions = positions
        self.daqConfig = daqs
        self.main_config = config

    def send_message(self, message: dict) -> dict:
        sock = self._scripter.sock
        sock.send_pyobj(message)
        return sock.recv_pyobj()

    def get_status(self) -> dict:
        return self.send_message({"command": "getStatus"})

    def get_config(self) -> None:
        self._adopt(*self._scripter.get_config())

    def getMotorPositions(self) -> dict:
        response = self.send_message({"command": "getMotorPositions"})
        if response and response.get("status"):
            self.currentMotorPositions = response["data"]
        return self.currentMotorPositions

    def change_motor_config(self, motor: str, key: str, value: Any) -> None:
        # Same message shape stxm_client sends, and likewise re-reads the config after,
        # so the cached motorInfo reflects the write.
        self.send_message({"command": "changeMotorConfig",
                           "data": {"motor": motor, "config": key, "value": value}})
        self.get_config()

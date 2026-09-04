"""A FrameSource for agents running outside the GUI process.

The GUI's ImageModel is filled by ``main_controller``, which subscribes to the server's
data stream and assembles frames.  An out-of-process agent has neither, so this builds
the same key/value surface from what the control server can give a remote client.

Two sources, added independently, which is why the class reports its own
``capabilities()`` instead of being assumed to serve everything:

* **recommendations** — the intelligence module publishes ``task_recommendation`` and
  ``intelligence_suggestion`` dicts on the scan-data stream.  They ride the same socket
  as the frame data but are small dicts, so collecting them needs none of the frame
  assembly the GUI does.
* **frames** — completed scan data, fetched from the server on request.

Deliberately NOT here: live frame assembly.  Intermediate frames during a scan serve
GUI visualisation and the server-side intelligence module; an out-of-process agent
wants the finished result, and reproducing the assembly out here would fork it.
"""

import logging
import threading

log = logging.getLogger(__name__)

# Messages the intelligence module publishes for an agent to act on.
_RECOMMENDATION = "task_recommendation"
_SUGGESTION = "intelligence_suggestion"
# An intelligence_suggestion that is an ANSWER to a user query is not an alarm; only
# diagnoses (beam loss, focus decline, ...) should interrupt a waiting agent.
_NOT_AN_ALARM = (None, "user_query")


class RemoteFrameSource:
    """FrameSource fed by the control server rather than by the GUI.

    Implements the dict-shaped port (``get``/``set``).  Keys it does not serve read as
    the caller's default, exactly as NullFrameSource does, so a tool that reaches for
    something this source cannot provide degrades instead of raising — though the
    registry should have kept it unadvertised in the first place.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict = {"pending_recommendations": [], "pending_alarms": []}
        self._subscriber: "_StreamSubscriber | None" = None

    # ── FrameSource port ──────────────────────────────────────────────────────
    def get(self, key: str, default=None):
        with self._lock:
            value = self._data.get(key, default)
            # Hand back a copy of the queues: tools drain them by reading and then
            # setting [], and a shared list would let an arriving message land in
            # what the caller is still iterating.
            return list(value) if isinstance(value, list) else value

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value

    def capabilities(self) -> tuple[str, ...]:
        """Which capabilities this source is actually serving right now."""
        caps = []
        if self._subscriber is not None:
            caps.append("recommendations")
        return tuple(caps)

    # ── intelligence stream ───────────────────────────────────────────────────
    def start_recommendations(self, address: str, port: int) -> None:
        """Subscribe to the server's scan-data stream for intelligence messages."""
        if self._subscriber is not None:
            return
        self._subscriber = _StreamSubscriber(address, port, self._handle)
        self._subscriber.start()

    def stop(self) -> None:
        if self._subscriber is not None:
            self._subscriber.stop()
            self._subscriber = None

    def _handle(self, message) -> None:
        """Route one stream message, mirroring what main_controller does for the GUI."""
        if not isinstance(message, dict):
            return                                  # frame payloads: not ours
        kind = message.get("type")
        if kind == _RECOMMENDATION:
            self._append("pending_recommendations", message)
        elif kind == _SUGGESTION and message.get("anomaly_type") not in _NOT_AN_ALARM:
            self._append("pending_alarms", message)

    def _append(self, key: str, message: dict) -> None:
        with self._lock:
            self._data.setdefault(key, []).append(message)


class _StreamSubscriber(threading.Thread):
    """Background SUB socket on the server's scan-data port.

    A daemon thread so it never holds up interpreter shutdown, and every message is
    handled inside a try/except: a malformed or unexpected payload on a shared stream
    must not kill the subscription and silently stop all recommendations.
    """

    def __init__(self, address: str, port: int, handler):
        super().__init__(name="stxm-intelligence-sub", daemon=True)
        self._address, self._port, self._handler = address, port, handler
        self._running = threading.Event()
        self._running.set()

    def run(self) -> None:
        import zmq

        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        # Time out the receive so stop() is honoured promptly instead of blocking
        # forever on a quiet stream.
        socket.setsockopt(zmq.RCVTIMEO, 500)
        socket.connect(f"tcp://{self._address}:{self._port}")
        try:
            while self._running.is_set():
                try:
                    message = socket.recv_pyobj()
                except zmq.Again:
                    continue
                except Exception as e:
                    log.debug("intelligence stream receive failed: %s", e)
                    continue
                try:
                    self._handler(message)
                except Exception as e:
                    log.warning("failed to handle an intelligence message: %s", e)
        finally:
            socket.close(linger=0)
            context.term()

    def stop(self) -> None:
        self._running.clear()

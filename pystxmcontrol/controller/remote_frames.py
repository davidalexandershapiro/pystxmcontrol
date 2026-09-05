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
* **frames** — completed scan data, fetched from the server on request. The server
  reads the files, so this works from a host with no access to the data directory.

Deliberately NOT here: live frame assembly.  Intermediate frames during a scan serve
GUI visualisation and the server-side intelligence module; an out-of-process agent
wants the finished result, and reproducing the assembly out here would fork it.
"""

import logging
import threading
import time

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

    # Scan listings are re-fetched at most this often. A scan takes far longer than
    # this to run, so it is short enough that a just-finished scan appears promptly and
    # long enough that a tool reading several keys does not re-fetch for each.
    _LISTING_TTL_SECONDS = 5.0

    def __init__(self, client=None, buffer_depth: int = 8):
        self._lock = threading.Lock()
        self._data: dict = {"pending_recommendations": [], "pending_alarms": []}
        self._subscriber: "_StreamSubscriber | None" = None
        self._client = client
        self._buffer_depth = max(1, int(buffer_depth))
        self._listing: list | None = None
        self._listing_at = 0.0

    # ── FrameSource port ──────────────────────────────────────────────────────
    # Keys served by fetching completed scans from the server rather than from the
    # queues the subscriber fills.
    _SCAN_KEYS = ("scan_buffer", "all_detector_images", "scan_type", "current_energy",
                  "x_center", "y_center", "x_range", "y_range")

    def get(self, key: str, default=None):
        if key in self._SCAN_KEYS and self._client is not None:
            value = self._scan_key(key)
            if value is not None:
                return value
            return default
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
        """Which capabilities this source is actually serving right now.

        Reported rather than assumed because the two arrive independently: a server
        whose intelligence stream could not be reached still serves completed scans,
        and advertising tools for a capability that is not there would offer tools that
        cannot work.
        """
        caps = []
        if self._client is not None:
            caps.append("frames")
        if self._subscriber is not None:
            caps.append("recommendations")
        return tuple(caps)

    # ── completed scans ───────────────────────────────────────────────────────
    def _listing_now(self) -> list:
        """Recent scans, newest LAST to match the GUI buffer's ordering.

        The agent tools treat the buffer as oldest-first and read it with [-1], so the
        server's newest-first listing has to be reversed here rather than in each tool.
        """
        now = time.monotonic()
        if self._listing is not None and (now - self._listing_at) < self._LISTING_TTL_SECONDS:
            return self._listing
        try:
            response = self._client.send_message(
                {"command": "list_scans", "limit": self._buffer_depth})
        except Exception as e:
            log.debug("list_scans failed: %s", e)
            return self._listing or []
        if not response or not response.get("status"):
            return self._listing or []
        records = list(response.get("data") or [])
        records.reverse()
        self._listing, self._listing_at = records, now
        return records

    def _scan_key(self, key: str):
        records = self._listing_now()
        if not records:
            return None
        if key == "scan_buffer":
            # Same record shape the GUI buffers, so the analysis tools cannot tell the
            # difference. 'stxm' is lazy: listing is metadata-only, and the arrays move
            # only when a tool actually reads them.
            return [{"stxm": _LazyScan(self._client, rec.get("path")),
                     "scan_id": rec.get("scan_id", ""),
                     # The file this record came from, which the analysis tools' file=
                     # argument takes. A GUI record has the path in its scan_id; here the
                     # scan_id is the basename, so the path rides alongside.
                     "path": rec.get("path", ""),
                     "energies": rec.get("energies") or [],
                     "scan_type": rec.get("scan_type", ""),
                     "timestamp": rec.get("timestamp", 0.0)}
                    for rec in records]

        latest = records[-1]
        if key == "scan_type":
            return latest.get("scan_type", "")
        if key == "current_energy":
            energies = latest.get("energies") or []
            return energies[-1] if energies else None

        # frames=1: these keys need only the frame the scan ended on, so an energy
        # stack is not worth moving. The buffer records above keep frames=None, since
        # the analysis tools index across energies.
        scan = _LazyScan(self._client, latest.get("path"), frames=1).loaded()
        if scan is None:
            return None
        if key == "all_detector_images":
            # The tools want the 2-D frame per detector, so read the raw (energy, y, x)
            # arrays rather than interp_counts, which wraps each in a per-region list.
            # A stack yields its last frame — the one a completed scan ended on.
            return {daq: (arr[-1] if getattr(arr, "ndim", 0) == 3 else arr)
                    for daq, arr in (scan.images or {}).items()}
        return _geometry(scan, key)

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


def _geometry(scan: "_LazyScan", key: str):
    """Centre/range in µm from a scan's position arrays.

    The GUI gets these from the live scan's metadata; here they are derived from the
    positions the server returned, which is the same information by another route.
    """
    per_region = scan.xPos if key.startswith("x") else scan.yPos
    positions = per_region[0] if per_region else None
    if positions is None or len(positions) == 0:
        return None
    low, high = float(min(positions)), float(max(positions))
    return (low + high) / 2.0 if key.endswith("center") else (high - low)


class _LazyScan:
    """A buffered-scan record's ``stxm``, fetched on first array access.

    Exposes the three attributes the analysis tools read off a live scan object —
    ``interp_counts``, ``xPos``, ``yPos`` — so a record built from a server-side file
    read is interchangeable with one the GUI buffered from a live scan.

    Lazy because listing scans must stay cheap: ``list_buffered_scans`` shows the
    operator what is available and should not pull megabytes per entry to do it. The
    arrays move only when a tool actually reaches for them, and then once, cached.
    """

    def __init__(self, client, path: str | None, frames=None):
        self._client, self._path, self._frames = client, path, frames
        self._payload: dict | None = None
        self._failed = False

    def loaded(self) -> "_LazyScan | None":
        """Force the fetch; None if the scan could not be read."""
        self._fetch()
        return None if self._failed else self

    def _fetch(self) -> None:
        if self._payload is not None or self._failed:
            return
        if self._client is None or not self._path:
            self._failed = True
            return
        try:
            response = self._client.send_message(
                {"command": "get_scan_data", "path": self._path, "frames": self._frames})
        except Exception as e:
            log.warning("get_scan_data failed for %s: %s", self._path, e)
            self._failed = True
            return
        if not response or not response.get("status") or not isinstance(response.get("data"), dict):
            log.warning("get_scan_data returned no data for %s", self._path)
            self._failed = True
            return
        self._payload = response["data"]

    @property
    def interp_counts(self) -> dict:
        """``{detector: (energy, y, x) array}`` — the shape the tools index."""
        self._fetch()
        if self._payload is None:
            return {}
        # The tools index interp_counts[daq][region]; a file holds one region, so wrap
        # each array in a single-entry list to match.
        return {daq: [arr] for daq, arr in (self._payload.get("images") or {}).items()}

    @property
    def images(self) -> dict:
        """``{detector: (energy, y, x) array}`` as the server returned it."""
        self._fetch()
        return (self._payload or {}).get("images") or {}

    @property
    def xPos(self) -> list:
        """Per-region, as a live scan holds it — one region per file, so a single entry.

        The tools index these as ``xPos[region]`` alongside ``interp_counts[daq][region]``;
        handing back a flat list would leave them reading one coordinate as a whole axis.
        """
        self._fetch()
        return [(self._payload or {}).get("x_positions") or []]

    @property
    def yPos(self) -> list:
        self._fetch()
        return [(self._payload or {}).get("y_positions") or []]

    @property
    def energies(self):
        self._fetch()
        return (self._payload or {}).get("energies") or []

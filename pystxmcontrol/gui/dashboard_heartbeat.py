"""Server-reachability heartbeat for the acquisition dashboard.

Split out of ``mainwindow_dashboard`` — it talks to the control server over its
own socket and knows nothing about the window, so it lives on its own.
"""

import zmq

from PySide6.QtCore import QThread, Signal


class ServerHeartbeat(QThread):
    """Background poller that reports server reachability for the header LED.

    Owns its OWN ``zmq.REQ`` socket to the command port so it never touches the
    client's command socket (which is blocking, timeout-less, and strictly
    lock-step — a ping there could hang the UI or race an in-flight command).
    The server's REP loop serves this extra peer serially, so an idle/scanning
    server still answers ``getStatus`` cheaply.

    Every ``interval_ms`` it sends ``getStatus`` with a receive timeout.  Because
    a REQ socket that times out on ``recv`` is left in a broken state, we follow
    the "Lazy Pirate" pattern: on any failure we discard and recreate the socket
    before the next attempt.  ``status_changed`` is emitted edge-triggered (only
    when reachability flips) and is delivered to the GUI thread via a queued
    connection, so the slot may safely touch widgets.
    """

    status_changed = Signal(bool)  # True = server answered, False = unreachable

    def __init__(self, address, port, parent=None,
                 interval_ms=2000, timeout_ms=1000):
        super().__init__(parent)
        self._addr = address
        self._port = int(port)
        self._interval_ms = interval_ms
        self._timeout_ms = timeout_ms
        self._running = True
        self._last = None  # None until the first probe, so the first result emits

    def stop(self):
        self._running = False

    def _new_socket(self, ctx):
        s = ctx.socket(zmq.REQ)
        s.setsockopt(zmq.LINGER, 0)              # don't block on close
        s.setsockopt(zmq.RCVTIMEO, self._timeout_ms)
        s.setsockopt(zmq.SNDTIMEO, self._timeout_ms)
        s.connect("tcp://%s:%s" % (self._addr, self._port))
        return s

    def run(self):
        ctx = zmq.Context()
        sock = self._new_socket(ctx)
        try:
            while self._running:
                try:
                    sock.send_pyobj({"command": "getStatus"})
                    sock.recv_pyobj()
                    alive = True
                except Exception:
                    alive = False
                if not alive:
                    # A failed REQ recv leaves the socket unusable — rebuild it.
                    sock.close()
                    sock = self._new_socket(ctx)
                if alive != self._last:
                    self._last = alive
                    self.status_changed.emit(alive)
                # Sleep in short slices so stop() takes effect promptly.
                waited = 0
                while self._running and waited < self._interval_ms:
                    self.msleep(100)
                    waited += 100
        finally:
            sock.close()
            ctx.term()

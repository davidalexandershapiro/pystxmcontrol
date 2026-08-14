"""Display-only DAQ driver: mirror a cosmic-spark (cosmicstreams-style) ZMQ
frame stream into the GUI live view.

Unlike ``fccd_control`` this driver commands no hardware and records nothing.
It subscribes to a PUB stream (cosmic-spark's publisher on tcp://<host>:37013)
and keeps the most-recently-received image in ``self.display_data`` (and
``self.data``) for the operator's live view.  Cosmic-spark owns the real frame
capture / CXI writing; pystxmcontrol only shows the picture.

Wire format expected (cosmic-spark / cosmicstreams PreprocessorStream):

    [ b'frame',   json(metadata), frame-bytes ]
    [ b'preview', json(metadata), frame-bytes ]
    [ b'start' | b'stop' | b'abort', json ]      # ignored

where ``metadata`` carries the array geometry.  Which topics are treated as
images, and which metadata keys describe the array, are configurable so this
driver is not welded to one schema -- see ``start()``.

Everything is driven from a background thread so ``display_data`` stays fresh
independent of when the controller polls ``getPoint``.

Example ``daq.json`` entry (deployed at <sys.prefix>/pystxmcontrol_cfg/daq.json)::

    "CCD": {
        "driver": "zmq_display",
        "address": "10.0.5.55",
        "port": 37013,
        "record": true,
        "ndim": 2, "type": "image", "name": "FCCD",
        "x label": "X Position", "y label": "Y Position",
        "topics": ["frame", "preview"],
        "shape_keys": ["shape_y", "shape_x"],
        "dtype_key": "dtype",
        "byteorder_key": "byteorder",
        "log_scale": false
    }

``record`` must be true for the controller to load the driver at all; the keys
below ``name`` are optional and default to the cosmic-spark schema.
"""

import json
import threading

import numpy as np
import zmq

from pystxmcontrol.controller.daq import daq


class zmq_display(daq):
    def __init__(self, address="127.0.0.1", port=37013, simulation=False, shape=(1040, 1152)):
        self.address = address
        self.port = port
        self.addr = "tcp://%s:%s" % (self.address, self.port)
        self.simulation = simulation
        self.shape = tuple(shape)
        # display_data/data must exist up front: dataHandler.getPoint reads
        # display_data (and gates scan points on data) before the first frame
        # can possibly arrive.  None == "no frame yet".
        self.display_data = None
        self.data = None
        self._framenum = 0
        self._stop = threading.Event()
        self._thread = None
        # Overwritten by the controller with the daq.json entry, but keep a
        # sane default so the driver is usable standalone / in tests.
        self.meta = {"ndim": 2, "type": "image", "name": "FCCD",
                     "x label": "X Position", "y label": "Y Position",
                     "oversampling_factor": 1}

    # -- lifecycle -------------------------------------------------------------

    def start(self):
        """Read stream config from self.meta and spawn the SUB thread."""
        cfg = getattr(self, "meta", None) or {}
        topics = cfg.get("topics", ["frame", "preview"])
        self._image_topics = [t.encode() if isinstance(t, str) else t for t in topics]
        shape_keys = cfg.get("shape_keys", ["shape_y", "shape_x"])
        self._shape_keys = (shape_keys[0], shape_keys[1])
        self._dtype_key = cfg.get("dtype_key", "dtype")
        self._byteorder_key = cfg.get("byteorder_key", "byteorder")
        self._log_scale = bool(cfg.get("log_scale", False))
        if self.simulation:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="zmq_display", daemon=True
        )
        self._thread.start()
        print("[zmq_display] Subscribed to %s topics=%s"
              % (self.addr, [t.decode() for t in self._image_topics]))

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # -- background receiver ---------------------------------------------------

    def _run(self):
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.MAXMSGSIZE, 2 ** 34)
        sock.set_hwm(10000)
        for topic in self._image_topics:
            sock.setsockopt(zmq.SUBSCRIBE, topic)
        sock.connect(self.addr)
        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)
        try:
            while not self._stop.is_set():
                if dict(poller.poll(timeout=200)).get(sock) != zmq.POLLIN:
                    continue
                try:
                    parts = sock.recv_multipart()
                except zmq.ZMQError:
                    continue
                self._handle(parts)
        finally:
            poller.unregister(sock)
            sock.close(linger=0)

    def _handle(self, parts):
        # Only [topic, json, bytes] image messages carry a frame; control
        # messages (start/stop/abort) are filtered out at the SUB socket, but
        # guard the shape anyway so a stray message can never crash the thread.
        if len(parts) != 3:
            return
        topic, meta_bytes, buf = parts
        if topic not in self._image_topics:
            return
        try:
            md = json.loads(meta_bytes.decode())
            dt = np.dtype(md[self._dtype_key])
            bo = md.get(self._byteorder_key)
            if bo in ("<", ">"):
                dt = dt.newbyteorder(bo)
            ny = int(md[self._shape_keys[0]])
            nx = int(md[self._shape_keys[1]])
            # .astype gives us a writable, owned array (frombuffer is a
            # read-only view over the zmq frame's memory).
            img = np.frombuffer(buf, dtype=dt).reshape((ny, nx)).astype(np.float32)
            if self._log_scale:
                img = np.log(np.clip(img, 0.0, None) + 1e-4)
        except Exception as e:  # never let one bad frame kill the receiver
            print("[zmq_display] dropping bad frame on topic %r: %s" % (topic, e))
            return
        # Single attribute store is atomic in CPython, so the GUI reader never
        # sees a torn array -- no lock needed for latest-frame-wins.
        self.display_data = img
        self.data = img
        self._framenum += 1

    # -- daq interface (display-only: acquisition methods are no-ops) ----------

    async def getPoint(self, mode="full"):
        if self.simulation:
            img = (2.0 * np.random.random(self.shape)).astype(np.float32)
            self.display_data = img
            self.data = img
            return img
        # Non-blocking: hand back whatever the receiver thread last cached.
        return self.data

    async def getLine(self, *args, **kwargs):
        return self.data

    def config(self, *args, **kwargs):
        """No hardware to configure -- this driver only mirrors a stream."""
        pass

    def init(self):
        pass

    def set_dwell(self, dwell):
        self.dwell = dwell

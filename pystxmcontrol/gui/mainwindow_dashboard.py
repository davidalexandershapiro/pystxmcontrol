"""Acquisition dashboard main window — a single-window STXM/ptychography
acquisition interface, transcribed from the design handoff in
``design_handoff_stxm_main_window/``.

STATUS: static skeleton (Phase 0).  Layout, styling, and representative
placeholder content only — no controller/hardware wiring yet.  All numbers and
plots are dummy data so the layout can be evaluated in real Qt.  Later phases
subscribe this view to ``MainController`` signals (see the reuse map / README).

Run standalone via ``main_dashboard.py``.
"""

import os
import sys
import json
import numpy as np

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton, QComboBox, QLineEdit,
    QCheckBox, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QStackedWidget, QButtonGroup, QSizePolicy, QGraphicsOpacityEffect,
    QMessageBox,
)
from PySide6.QtGui import QPixmap, QImage, QColor, QFont, QIntValidator
from PySide6.QtCore import Qt, QTimer, QRectF, Signal, QThread

import zmq
import pyqtgraph as pg

from pystxmcontrol.gui.dashboard_theme import (
    C, MONO_FAMILY, SANS_FAMILY, build_stylesheet, make_lut, roi_colors,
    mono_font, sans_font, TravelBar, ProgressBar, EnergyRegionStrip,
    HistColorBar,
)

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")

pg.setConfigOptions(antialias=True, imageAxisOrder="row-major", background=C["plot_ground"])


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


# ── dummy data (placeholders for real client/dataHandler signals) ───────────
def _absorption_field(n=120, seed=1):
    """Procedural absorption map — mirrors the mock's makeField()."""
    rng = np.random.default_rng(seed)
    blobs = [(.46, .42, .13, 1), (.52, .5, .07, .85), (.38, .55, .05, .7),
             (.63, .36, .045, .6), (.3, .3, .03, .45), (.7, .62, .035, .5),
             (.24, .62, .022, .4), (.58, .7, .025, .35)]
    y, x = np.mgrid[0:n, 0:n] / n
    r = np.hypot(x - .5, y - .5)
    a = np.where(r < .44, .06, 0.0)
    for bx, by, br, amp in blobs:
        d2 = (x - bx) ** 2 + (y - by) ** 2
        a += amp * np.exp(-d2 / (2 * br * br))
    a += .05 * np.sin(x * 46) * np.sin(y * 38) * (r < .44)
    a += (rng.random((n, n)) - .5) * .035
    return np.clip(a, 0, 1)


def _diffraction(n=256, seed=2):
    """Log-scaled speckle with a central beamstop and centre-column gap."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] - n / 2
    r = np.hypot(x, y)
    base = np.exp(-r / 42.0)
    speckle = base * (0.4 + rng.random((n, n)))
    speckle += 0.02 * rng.random((n, n))
    speckle[r < 14] = 0                      # beamstop
    speckle[:, n // 2 - 1:n // 2 + 1] = 0    # fCCD centre gap
    return np.log1p(speckle * 4000)


def _spectrum():
    e = np.linspace(700, 730, 121)
    od = 0.25 + 0.05 * np.sin(e / 3)
    od += 0.9 * np.exp(-((e - 709) ** 2) / 1.5)     # L3
    od += 0.4 * np.exp(-((e - 722) ** 2) / 2.0)     # L2
    return e, od


def _thumb_field(seed, kind="Spiral Image", n=48):
    """Procedural absorption thumbnail — ports the mock's makeThumbField().
    'Focus' renders the vertical through-focus streak; everything else a
    circular-aperture particle field."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] / n
    if kind == "Focus":
        a = 0.5 + 0.45 * np.cos((x - .5) * np.pi * 2.2) * np.exp(-((x - .5) / .16) ** 2)
        a *= 0.7 + 0.3 * np.sin(y * 7 + seed)
        a += (rng.random((n, n)) - .5) * .06
        return np.clip(a, 0, 1)
    r = np.hypot(x - .5, y - .5)
    a = np.where(r < .47, .06, 0.0)
    nb = 4 + int(rng.random() * 10)
    for _ in range(nb):
        bx, by = .15 + rng.random() * .7, .15 + rng.random() * .7
        br, amp = .02 + rng.random() * .06, .3 + rng.random() * .7
        a += amp * np.exp(-((x - bx) ** 2 + (y - by) ** 2) / (2 * br * br))
    a += (rng.random((n, n)) - .5) * .05
    a = np.where(r < .47, a, 0.0)
    return np.clip(a, 0, 1)


def _field_pixmap(field, cmap_name, size):
    """Render an absorption field to a colour-mapped, pixelated QPixmap.
    Display value is ``1 - field`` (absorption → brightness), matching the
    ImageItem convention used elsewhere in this window."""
    lut = make_lut(cmap_name)                       # (256, 3) uint8
    idx = (np.clip(1.0 - field, 0, 1) * 255).astype(np.uint8)
    rgb = np.ascontiguousarray(lut[idx])            # (n, n, 3)
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg).scaled(
        size, size, Qt.IgnoreAspectRatio, Qt.FastTransformation)


_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _exp_str(exp):
    """'×10ⁿ' label for a power-of-ten, or '' when the exponent is zero."""
    return "" if exp == 0 else f"×10{str(exp).translate(_SUP)}"


# ── last recorded scan (startup image) ───────────────────────────────────────
def _runtime_main_config():
    """The server's runtime main.json (sys.prefix copy first, repo copy as a
    fallback) — the same file the server and _maybe_connect_controller read."""
    for path in (os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json"),
                 os.path.join(os.path.dirname(__file__), "..", "..", "config",
                              "main.json")):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _find_last_scan_file():
    """Newest ``.stxm`` data file under the server's ``data_dir`` (walking the
    YYYY/MM/YYMMDD hierarchy, then a flat fallback), or None when none exists."""
    import glob
    data_dir = (_runtime_main_config().get("server") or {}).get("data_dir")
    if not data_dir or not os.path.isdir(data_dir):
        return None
    files = [f for f in glob.glob(os.path.join(data_dir, "*", "*", "*", "*.stxm"))
             if "ccdframes" not in os.path.basename(f)]
    if not files:
        files = [f for f in glob.glob(os.path.join(data_dir, "*.stxm"))
                 if "ccdframes" not in os.path.basename(f)]
    if not files:
        return None
    try:
        return max(files, key=os.path.getmtime)
    except OSError:
        return None


def _load_last_scan(path):
    """Read the primary 2-D image frame and its physical extent from a ``.stxm``
    file's default NXdata group.  Returns ``(arr2d, extent)`` where ``extent`` is
    ``(xCenter, yCenter, xRange, yRange)`` in µm (full-field, N*step) or None if
    the geometry is unavailable; returns None entirely if no image can be read."""
    try:
        import h5py
        with h5py.File(path, "r") as f:
            base = None
            for b in ("entry0/default", "entry0/counter0"):
                if b + "/data" in f:
                    base = b
                    break
            if base is None:
                return None
            arr = np.asarray(f[base + "/data"][()], dtype=float)
            if arr.ndim == 3:                    # (n_energies, ny, nx) → frame 0
                arr = arr[0]
            if arr.ndim != 2 or not arr.size:
                return None
            extent = None
            try:
                sx = np.asarray(f[base + "/sample_x"][()], dtype=float).ravel()
                sy = np.asarray(f[base + "/sample_y"][()], dtype=float).ravel()

                def _span_center(v):
                    lo, hi = float(v.min()), float(v.max())
                    step = (hi - lo) / (len(v) - 1) if len(v) > 1 else 0.0
                    return (hi - lo) + step, (lo + hi) / 2.0   # full-field, centre

                xr, xc = _span_center(sx)
                yr, yc = _span_center(sy)
                if xr > 0 and yr > 0:
                    extent = (xc, yc, xr, yr)
            except Exception:
                pass
            return arr, extent
    except Exception:
        return None


class SciAxis(pg.AxisItem):
    """Left axis that renders each tick as a mantissa (one decimal) against a
    common power-of-ten shared by the whole axis, and reports that exponent via
    ``on_exp_changed`` so it can be shown once above the plot — keeping the tick
    labels narrow instead of spelling out full magnitudes like ``4218000``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._exp = None
        self.on_exp_changed = None
        # Take full control of tick formatting: pyqtgraph's auto SI prefix would
        # otherwise pre-scale the values handed to tickStrings, desyncing our
        # computed exponent from the mantissa actually drawn.
        self.enableAutoSIPrefix(False)

    def tickStrings(self, values, scale, spacing):
        if not len(values):
            return []
        mx = max(abs(float(v)) for v in values)
        exp = int(np.floor(np.log10(mx))) if mx > 0 else 0
        # Report the exponent for EVERY render (not only on change) so the label
        # above the plot can never lag the mantissa actually drawn on the ticks.
        self._exp = exp
        if self.on_exp_changed is not None:
            self.on_exp_changed(exp)
        div = 10.0 ** exp
        # One decimal for large-magnitude data (the wide-label case), but keep
        # enough precision that fine traces near the mantissa's tick spacing (e.g.
        # I0-normalised ~1.0 data) don't collapse to identical "1.0" labels.
        mant_space = abs(spacing) / div if spacing else 0.0
        dec = max(1, int(np.ceil(-np.log10(mant_space)))) if mant_space > 0 else 1
        dec = min(dec, 6)
        return [f"{float(v) / div:.{dec}f}" for v in values]


class ImageArea(QWidget):
    """The main image viewer: a pyqtgraph ViewBox+ImageItem with absolutely
    positioned overlay labels (scale bar, metadata) repositioned on resize.

    Spatial scan regions are drawn as interactive ``RectROI`` boxes in physical
    (µm / motor) coordinates.  The image pixel grid is mapped onto a physical
    field-of-view via ``set_fov`` so ROI geometry equals motor microns.  Boxes
    are keyed by a caller-supplied string; the widget emits:
      * ``roi_selected(key)``           — a box was clicked or a drag started
      * ``roi_moving(key, xc,yc,xr,yr)`` — geometry during an interactive drag
      * ``roi_moved(key, xc,yc,xr,yr)``  — geometry committed (drag finished)
    """

    roi_selected = Signal(str)
    roi_moving = Signal(str, float, float, float, float)
    roi_moved = Signal(str, float, float, float, float)
    cursor_changed = Signal(object)     # dict of cursor state, or None off-image
    # Focus / line-spectrum scan line: (xCenter, yCenter, length, angle°) in µm.
    line_moving = Signal(float, float, float, float)
    line_moved = Signal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C['plot_ground']};")
        self.glw = pg.GraphicsLayoutWidget(parent=self)
        self.glw.setBackground(C["plot_ground"])
        self.vb = self.glw.addViewBox()
        self.vb.setAspectLocked(True)
        self.vb.invertY(True)
        self.vb.setMouseEnabled(True, True)

        self._cmap = "gray"
        self.field = None
        self.img = pg.ImageItem()
        # Start black: real pixels arrive from the last recorded scan (on startup)
        # or from live frames during a scan — no procedural placeholder field.
        self.img.setImage(np.zeros((2, 2), dtype=float), autoLevels=False)
        self.img.setLevels([0.0, 1.0])
        self.img.setLookupTable(make_lut(self._cmap))
        self.img.setZValue(0)
        self.vb.addItem(self.img)
        # The image data occupies a physical µm extent (the scanned region);
        # the *view* is a wider field-of-view around it.  ``_primary_rect`` tracks
        # that extent (in µm) so mouse-driven line-outs can map pixels ↔ microns.
        self._primary_rect = QRectF(-6.0, -6.0, 12.0, 12.0)
        self.img.setRect(self._primary_rect)
        self.vb.autoRange(padding=0)
        # A persistent crosshair placed by a LEFT-CLICK on the image (not hover):
        # two InfiniteLines + a centre dot, drawn above the tiles/ROIs.  The click
        # also drives the line-outs and is registered as the current cursor point.
        _xh_pen = pg.mkPen("#ffd400", width=1)
        self.crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=_xh_pen)
        self.crosshair_h = pg.InfiniteLine(angle=0, movable=False, pen=_xh_pen)
        self.crosshair_dot = pg.ScatterPlotItem(
            size=7, pen=pg.mkPen("#1a1a1a", width=1),
            brush=pg.mkBrush("#ffd400"))
        for _it in (self.crosshair_v, self.crosshair_h, self.crosshair_dot):
            _it.setZValue(12)          # above image tiles (0) and ROI boxes (10/11)
            _it.setVisible(False)
            self.vb.addItem(_it)
        self._cursor_pt = None         # last clicked point (x, y) in µm, or None
        # Line-outs / crosshair are selected by CLICK, not by mouse move.
        self.glw.scene().sigMouseClicked.connect(self._on_mouse_clicked)

        # Live scan data is a spatial mosaic: one ImageItem per scan region,
        # each positioned at its own physical extent (mirrors the classic GUI).
        # The first region reuses self.img (the histogram-bound primary); the
        # rest are secondary tiles kept in LUT/levels sync with it.
        self._region_images = {}      # region key -> ImageItem
        self._region_rects = {}       # region key -> QRectF physical µm extent
        self._seeded_regions = set()  # regions that have auto-levelled once
        self._primary_seeded = False

        # Region ROI boxes, keyed by caller string.  _suppress guards against
        # our own programmatic geometry writes re-emitting change signals;
        # _dragging holds the key of a box under active interactive drag.
        self._roi_items = {}          # key -> {'roi': RectROI, 'label': TextItem}
        self._suppress = False
        self._dragging = None

        # A single draggable/rotatable scan LINE (Focus / Line-Spectrum), drawn
        # over the sample image to define the line endpoints.  Distinct from the
        # RectROI boxes above; only one ever exists.
        self._line_roi = None
        self._line_dragging = False
        # Focus-display mode: the frame is position-along-line (x) vs ZonePlateZ
        # (y), whose values dwarf the sample-µm x extent, so the square-pixel
        # aspect lock is released and the vertical axis is treated as Z.
        self._focus_display = False
        # 1-D plot mode: a single-motor scan is signal-vs-position, not an image,
        # so the ViewBox is swapped out for a PlotItem (built lazily).
        self._plot_mode = False
        self.plot_item = None
        self.plot_curve = None

        # (A contextual scan-progress line will be reintroduced later; for now the
        # image area carries no horizontal overlay line.)

        # Bottom metadata overlay — a translucent strip pinned to the bottom of
        # the image (mirrors mainwindow_mvc): facility logo + two metadata rows on
        # the left, a live scale bar on the right.  Transparent to mouse events so
        # cursor line-outs still update when hovering over the bar.
        self.meta_bar = QFrame(self)
        self.meta_bar.setObjectName("imgMetaBar")
        self.meta_bar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.meta_bar.setStyleSheet(
            "QFrame#imgMetaBar{background:rgba(0,0,0,0.62);border:none;}")
        mb = QHBoxLayout(self.meta_bar)
        mb.setContentsMargins(12, 6, 14, 6)
        mb.setSpacing(10)
        self.meta_logo = QLabel()
        _logo = QPixmap(os.path.join(_ICONS_DIR, "als-logo.png"))
        if not _logo.isNull():
            self.meta_logo.setPixmap(
                _logo.scaledToHeight(28, Qt.SmoothTransformation))
        mb.addWidget(self.meta_logo)
        meta_txt = QVBoxLayout()
        meta_txt.setContentsMargins(0, 0, 0, 0)
        meta_txt.setSpacing(1)
        self.meta_row1 = QLabel("")
        self.meta_row1.setFont(mono_font(9))
        self.meta_row1.setStyleSheet("color:#e6ebef;background:transparent;")
        self.meta_row2 = QLabel("")
        self.meta_row2.setFont(mono_font(8))
        self.meta_row2.setStyleSheet(
            "color:rgba(230,235,239,.72);background:transparent;")
        meta_txt.addWidget(self.meta_row1)
        meta_txt.addWidget(self.meta_row2)
        mb.addLayout(meta_txt)
        mb.addStretch(1)
        # Scale bar (right): a value label above a white bar whose pixel width
        # tracks the current zoom (see _update_scalebar).
        sb = QVBoxLayout()
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(3)
        self.scalebar_lbl = QLabel("2 µm")
        self.scalebar_lbl.setFont(mono_font(9))
        self.scalebar_lbl.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self.scalebar_lbl.setStyleSheet("color:#fff;background:transparent;")
        self.scalebar = QFrame()
        self.scalebar.setStyleSheet("background:#ffffff;border:none;")
        self.scalebar.setFixedHeight(3)
        self.scalebar.setFixedWidth(80)
        sb.addWidget(self.scalebar_lbl)
        sb.addWidget(self.scalebar, 0, Qt.AlignRight)
        mb.addLayout(sb)
        # Children must also ignore the mouse, or they'd swallow hover-move events
        # (blocking cursor line-outs) where they overlap the bottom of the image.
        for _w in (self.meta_logo, self.meta_row1, self.meta_row2,
                   self.scalebar_lbl, self.scalebar):
            _w.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._scale_bar_um = 2.0
        self.vb.sigRangeChanged.connect(lambda *a: self._update_scalebar())

    def set_cmap(self, name):
        self._cmap = name
        self.img.setLookupTable(make_lut(name))
        self._recolor()          # keep ROI outlines contrasting the new LUT

    def set_roi_cmap(self, name):
        """Note the active colormap for ROI-contrast purposes only — the image
        LUT itself is owned by the bound HistogramLUTWidget."""
        self._cmap = name
        self._recolor()

    def _roi_color(self, kind):
        region_c, spectrum_c = roi_colors(self._cmap)
        return spectrum_c if kind == "spectrum" else region_c

    # ── physical coordinate frame ────────────────────────────────────────
    def set_image_extent(self, xc, yc, width, height):
        """Place the image data at its physical µm extent — the region it was
        scanned over.  This is the *displayed data's* fixed extent; it is set when
        data arrives (file/live), NOT driven by the editable scan-region ROIs."""
        self._primary_rect = QRectF(xc - width / 2.0, yc - height / 2.0,
                                    width, height)
        self.img.setRect(self._primary_rect)

    def image_extent(self):
        """The displayed data's physical extent as ``(x0, y0, x1, y1)`` µm, or
        None if nothing meaningful is placed yet."""
        r = self._primary_rect
        if r is None or r.width() <= 0 or r.height() <= 0:
            return None
        return (r.left(), r.top(), r.right(), r.bottom())

    def set_view(self, xc, yc, width, height):
        """Set the visible field-of-view (µm) centred at (xc, yc).  ``width``/
        ``height`` are the exact requested extent — the caller (_fit_fov) already
        bakes the ROI margin into them, so no extra padding is added here."""
        self.vb.setRange(
            QRectF(xc - width / 2.0, yc - height / 2.0, width, height),
            padding=0)

    # ── live scan data (per-region mosaic) ───────────────────────────────
    def set_primary_frame(self, data):
        """Fallback for frames with no region geometry — draw on the primary
        item at its current rect (auto-levels only the first time)."""
        self.img.setImage(data, autoLevels=not self._primary_seeded)
        # setRect's scale transform is derived from the image's pixel dimensions,
        # so it must be re-applied whenever the frame shape changes (e.g. the 2×2
        # black seed → a real N×N scan) or the data would render at the seed scale.
        if self._primary_rect is not None:
            self.img.setRect(self._primary_rect)
        self._primary_seeded = True

    def set_region_frame(self, key, data, xc, yc, xr, yr):
        """Draw a scan frame for region ``key`` at its physical µm extent so
        different regions land in their own ROI boxes, not stacked in Region1."""
        item = self._region_images.get(key)
        if item is None:
            # First region reuses the histogram-bound primary; later regions
            # get their own tile beneath the ROI overlay.
            item = self.img if not self._region_images else pg.ImageItem()
            if item is not self.img:
                item.setZValue(0)
                self.vb.addItem(item)
            self._region_images[key] = item
        autolevel = key not in self._seeded_regions
        item.setImage(data, autoLevels=autolevel)
        self._seeded_regions.add(key)
        rect = QRectF(xc - xr / 2.0, yc - yr / 2.0, xr, yr)
        item.setRect(rect)
        self._region_rects[key] = rect
        if item is self.img:
            self._primary_rect = rect
        else:
            self._match_primary(item)

    def _match_primary(self, item):
        """Keep a secondary tile's LUT/levels matching the primary image."""
        if getattr(self.img, "lut", None) is not None:
            item.setLookupTable(self.img.lut)
        lv = self.img.getLevels()
        if lv is not None:
            item.setLevels(lv)

    def sync_lut_levels(self):
        """Propagate the primary's LUT/levels to every secondary tile — wired to
        the HistogramLUTWidget so dragging levels updates the whole mosaic."""
        for item in self._region_images.values():
            if item is not self.img:
                self._match_primary(item)

    def clear_region_frames(self):
        """Drop secondary tiles (e.g. at the start of a new scan)."""
        for item in self._region_images.values():
            if item is not self.img:
                self.vb.removeItem(item)
        self._region_images.clear()
        self._region_rects.clear()
        self._seeded_regions.clear()

    # ── region ROI boxes ─────────────────────────────────────────────────
    def sync_regions(self, regions):
        """Reconcile the drawn ROI boxes with ``regions`` — a list of dicts:
        {key, xCenter, yCenter, xRange, yRange, label, color, active}.
        Existing boxes are updated in place (so an active drag is never
        interrupted); missing keys are removed and new keys created."""
        self._suppress = True
        try:
            wanted = {r["key"] for r in regions}
            for key in [k for k in self._roi_items if k not in wanted]:
                it = self._roi_items.pop(key)
                self.vb.removeItem(it["roi"])
                self.vb.removeItem(it["label"])
            for r in regions:
                self._sync_one(r)
        finally:
            self._suppress = False

    def _sync_one(self, r):
        key = r["key"]
        kind = r.get("kind", "region")
        color = self._roi_color(kind)
        it = self._roi_items.get(key)
        if it is None:
            roi = pg.RectROI([r["xCenter"] - r["xRange"] / 2.0,
                              r["yCenter"] - r["yRange"] / 2.0],
                             [r["xRange"], r["yRange"]],
                             pen=pg.mkPen(color, width=2),
                             handlePen=pg.mkPen(color),
                             hoverPen=pg.mkPen(color, width=3))
            roi.setAcceptedMouseButtons(Qt.LeftButton)
            roi.setZValue(10)             # ROI boxes sit above the image tiles
            roi.sigRegionChangeStarted.connect(lambda _, k=key: self._on_start(k))
            roi.sigRegionChanged.connect(lambda _, k=key: self._on_changed(k))
            roi.sigRegionChangeFinished.connect(lambda _, k=key: self._on_finished(k))
            roi.sigClicked.connect(lambda _, __, k=key: self.roi_selected.emit(k))
            self.vb.addItem(roi)
            label = pg.TextItem("", color=color, anchor=(0, 1))
            label.setFont(mono_font(8))
            label.setZValue(11)
            self.vb.addItem(label)
            it = self._roi_items[key] = {"roi": roi, "label": label}
        it["kind"] = kind
        it["active"] = r.get("active", False)
        it["origin"] = (r["xCenter"] - r["xRange"] / 2.0,
                        r["yCenter"] - r["yRange"] / 2.0)
        roi, label = it["roi"], it["label"]
        # Geometry — never write to the box the user is actively dragging.
        if key != self._dragging:
            roi.setPos(list(it["origin"]), update=False, finish=False)
            roi.setSize([r["xRange"], r["yRange"]], update=True, finish=False)
        label.setText(r.get("label", ""))
        label.setPos(*it["origin"])
        self._style_one(key)

    def _style_one(self, key):
        """Apply active/inactive pen (full colour always — active is a thicker
        line + visible resize handle) using the current colormap's ROI colour."""
        it = self._roi_items.get(key)
        if it is None:
            return
        color = QColor(self._roi_color(it["kind"]))
        active = it["active"]
        it["roi"].setPen(pg.mkPen(color, width=3 if active else 1))
        it["roi"].hoverPen = pg.mkPen(color, width=3)
        for h in it["roi"].handles:
            h["item"].setVisible(active)
        it["label"].setColor(color)

    def _recolor(self):
        for key in self._roi_items:
            self._style_one(key)

    @staticmethod
    def _geom(roi):
        pos, size = roi.pos(), roi.size()
        xr, yr = abs(size[0]), abs(size[1])
        return (pos[0] + size[0] / 2.0, pos[1] + size[1] / 2.0, xr, yr)

    def _on_start(self, key):
        if self._suppress:
            return
        self._dragging = key
        self.roi_selected.emit(key)

    def _on_changed(self, key):
        if self._suppress:
            return
        self.roi_moving.emit(key, *self._geom(self._roi_items[key]["roi"]))

    def _on_finished(self, key):
        if self._suppress:
            return
        self._dragging = None
        self.roi_moved.emit(key, *self._geom(self._roi_items[key]["roi"]))

    # ── scan line (Focus / Line-Spectrum) ────────────────────────────────
    @staticmethod
    def _line_endpoints(xc, yc, length, angle_deg):
        """Endpoints ``((x1,y1),(x2,y2))`` of a line of ``length`` centred at
        (xc, yc) at ``angle_deg`` (0° = +x, CCW)."""
        ar = np.radians(angle_deg)
        hx, hy = (length / 2.0) * np.cos(ar), (length / 2.0) * np.sin(ar)
        return (xc - hx, yc - hy), (xc + hx, yc + hy)

    def sync_line(self, xc, yc, length, angle_deg, color="#ff3b30"):
        """Create or replace the scan line at the given centre/length/angle (µm).
        A no-op while the user is actively dragging the line (so we never fight
        the drag); otherwise the ROI is rebuilt at the new endpoints — the same
        clear-and-recreate approach the classic GUI uses for line ROIs."""
        if self._line_dragging:
            return
        (x1, y1), (x2, y2) = self._line_endpoints(xc, yc, length, angle_deg)
        self.clear_line()
        roi = pg.LineSegmentROI(positions=((x1, y1), (x2, y2)),
                                pen=pg.mkPen(color, width=3),
                                hoverPen=pg.mkPen(color, width=4))
        roi.setZValue(11)
        roi.sigRegionChangeStarted.connect(self._on_line_start)
        roi.sigRegionChanged.connect(self._on_line_changed)
        roi.sigRegionChangeFinished.connect(self._on_line_finished)
        self.vb.addItem(roi)
        self._line_roi = roi

    def clear_line(self):
        if self._line_roi is not None:
            self.vb.removeItem(self._line_roi)
            self._line_roi = None
            self._line_dragging = False

    def _line_geom(self):
        """Current line as ``(xCenter, yCenter, length, angle°)`` in µm."""
        h = self._line_roi.getHandles()
        p1 = self._line_roi.mapToParent(h[0].pos())
        p2 = self._line_roi.mapToParent(h[1].pos())
        dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
        return ((p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0,
                float(np.hypot(dx, dy)), float(np.degrees(np.arctan2(dy, dx))))

    def _on_line_start(self):
        if not self._suppress:
            self._line_dragging = True

    def _on_line_changed(self):
        if not self._suppress and self._line_roi is not None:
            self.line_moving.emit(*self._line_geom())

    def _on_line_finished(self):
        if self._suppress or self._line_roi is None:
            return
        self._line_dragging = False
        self.line_moved.emit(*self._line_geom())

    # ── snapshot / restore the displayed frames ──────────────────────────
    def snapshot(self):
        """Capture the currently displayed image data (primary + any secondary
        region tiles, their µm rects, and the primary levels) so it can be
        restored after a focus scan paints over the primary ImageItem."""
        def _grab(item):
            img = getattr(item, "image", None)
            return None if img is None else img.copy()
        snap = {"primary": (_grab(self.img),
                            QRectF(self._primary_rect) if self._primary_rect else None,
                            self.img.getLevels()),
                "regions": {}}
        for key, item in self._region_images.items():
            if item is self.img:
                continue
            rect = self._region_rects.get(key)
            snap["regions"][key] = (_grab(item),
                                    QRectF(rect) if rect else None)
        return snap

    def restore(self, snap):
        """Restore a snapshot taken by :meth:`snapshot`, dropping any focus tiles
        first.  The primary image is repainted at its saved extent + levels and
        each secondary tile is rebuilt at its own µm rect."""
        if not snap:
            return
        self.clear_region_frames()          # drop focus tiles + reset region maps
        arr, rect, levels = snap["primary"]
        if arr is not None:
            self.img.setImage(arr, autoLevels=False)
            if levels is not None:
                self.img.setLevels(levels)
        if rect is not None:
            self._primary_rect = QRectF(rect)
            self.img.setRect(self._primary_rect)
        for key, (a, r) in snap["regions"].items():
            if a is None or r is None:
                continue
            item = pg.ImageItem()
            item.setZValue(0)
            self.vb.addItem(item)
            item.setImage(a, autoLevels=False)
            item.setRect(QRectF(r))
            self._region_images[key] = item
            self._region_rects[key] = QRectF(r)
            self._match_primary(item)

    # ── focus-display mode ───────────────────────────────────────────────
    def set_focus_display(self, on):
        """Switch the viewer between the sample image (aspect-locked square µm)
        and a focus streak (position-along-line vs ZonePlateZ, aspect free)."""
        on = bool(on)
        if on == self._focus_display:
            return
        self._focus_display = on
        self.vb.setAspectLocked(not on)
        # The scale bar assumes an isotropic µm axis; meaningless on a Z streak.
        self.meta_bar.setVisible(not on)
        self.clear_crosshair()

    # ── 1-D plot mode (single-motor scans) ───────────────────────────────
    def _ensure_plot_item(self):
        """Build the PlotItem + curve on first use (lazy; theme-styled)."""
        if self.plot_item is not None:
            return
        self.plot_item = pg.PlotItem()
        self.plot_item.showGrid(x=True, y=True, alpha=0.15)
        for ax in ("bottom", "left"):
            self.plot_item.getAxis(ax).setPen(C["border"])
            self.plot_item.getAxis(ax).setTextPen(C["text_faint"])
        self.plot_curve = self.plot_item.plot(
            [], [], pen=pg.mkPen(C["accent"], width=1.6),
            symbol='o', symbolSize=4,
            symbolPen=pg.mkPen(C["accent"]), symbolBrush=pg.mkBrush(C["accent"]))

    def set_plot_mode(self, on):
        """Swap the image ViewBox for a 1-D curve plot (single-motor scans) and
        back.  The scale bar / crosshair are image-only, so they hide here."""
        on = bool(on)
        if on == self._plot_mode:
            return
        self._plot_mode = on
        if on:
            self._ensure_plot_item()
            self.clear_crosshair()
            self.glw.removeItem(self.vb)
            self.glw.addItem(self.plot_item, 0, 0)
            self.meta_bar.setVisible(False)
        else:
            self.glw.removeItem(self.plot_item)
            self.glw.addItem(self.vb, 0, 0)
            self.meta_bar.setVisible(True)

    def set_curve(self, x, y, x_label="", y_label="signal"):
        """Draw a 1-D trace (single-motor scan).  Enters plot mode if needed."""
        self.set_plot_mode(True)
        x = np.asarray(x, dtype=float).ravel()
        y = np.asarray(y, dtype=float).ravel()
        n = min(x.size, y.size)
        self.plot_curve.setData(x[:n], y[:n])
        self.plot_item.setLabel("bottom", x_label or "position")
        self.plot_item.setLabel("left", y_label or "signal")
        self.plot_item.enableAutoRange()

    # ── cursor crosshair + line-outs (click-driven) ──────────────────────
    def _data_regions(self):
        """Yield ``(image_item, µm_rect)`` for every region that holds a 2-D
        frame — the per-region mosaic tiles, plus the primary image when it isn't
        already one of them (e.g. a pre-scan / file frame)."""
        seen = set()
        for key, item in self._region_images.items():
            rect = self._region_rects.get(key)
            if rect is not None:
                seen.add(id(item))
                yield item, rect
        if id(self.img) not in seen and self._primary_rect is not None:
            yield self.img, self._primary_rect

    def _payload_at(self, scene_pos):
        """Map a scene position to a cursor payload.  The point (physical µm) is
        ALWAYS returned so the crosshair can be placed anywhere in the view.  When
        the point falls inside a region's data, the payload also carries the image
        row/col, value, and the two line-cuts; otherwise those keys are absent."""
        if not self.vb.sceneBoundingRect().contains(scene_pos):
            return None
        pt = self.vb.mapSceneToView(scene_pos)
        payload = {"x": float(pt.x()), "y": float(pt.y())}
        for arr, rect in self._data_regions():
            if (arr is None or getattr(arr, "image", None) is None
                    or rect is None or rect.width() <= 0 or rect.height() <= 0):
                continue
            data = arr.image
            if getattr(data, "ndim", 0) != 2:
                continue
            fx = (pt.x() - rect.left()) / rect.width()
            fy = (pt.y() - rect.top()) / rect.height()
            if not (0.0 <= fx < 1.0 and 0.0 <= fy < 1.0):
                continue
            h, w = data.shape
            c = min(w - 1, int(fx * w))
            r = min(h - 1, int(fy * h))
            xs = rect.left() + (np.arange(w) + 0.5) / w * rect.width()
            ys = rect.top() + (np.arange(h) + 0.5) / h * rect.height()
            payload.update({
                "row": r, "col": c, "value": float(data[r, c]),
                "hx": xs, "hy": np.asarray(data[r, :], dtype=float),  # along x (red)
                "vx": ys, "vy": np.asarray(data[:, c], dtype=float)})  # along y
            break
        return payload

    def _on_mouse_clicked(self, ev):
        """Left-click on the image → place the crosshair, register the point, and
        emit ``cursor_changed`` so the line-outs and readout update.  Clicks that
        land off the image data are ignored so panning is undisturbed.  (The
        ViewBox marks left clicks as accepted during its own handling, so we do
        NOT gate on ``ev.isAccepted()`` — that would suppress every click; drags
        pan the view and never arrive here as clicks.)"""
        if self._plot_mode:
            return          # the 1-D plot has its own pan/zoom; no crosshair
        try:
            if ev.button() != Qt.LeftButton:
                return
            scene_pos = ev.scenePos()
        except Exception:
            return
        payload = self._payload_at(scene_pos)
        if payload is None:
            return
        ev.accept()
        self.set_crosshair(payload["x"], payload["y"])
        self.cursor_changed.emit(payload)

    def set_crosshair(self, x, y):
        """Show the crosshair at physical µm (x, y) and record it as the current
        cursor point."""
        self.crosshair_v.setPos(x)
        self.crosshair_h.setPos(y)
        self.crosshair_dot.setData([x], [y])
        for it in (self.crosshair_v, self.crosshair_h, self.crosshair_dot):
            it.setVisible(True)
        self._cursor_pt = (float(x), float(y))

    def clear_crosshair(self):
        """Hide the crosshair and forget the current cursor point."""
        for it in (self.crosshair_v, self.crosshair_h, self.crosshair_dot):
            it.setVisible(False)
        self._cursor_pt = None

    # ── metadata overlay ─────────────────────────────────────────────────
    _META_BAR_H = 46

    def set_metadata(self, scan_type="", sample="", proposal="", channel="",
                     pixel_um=None, dwell_ms=None, energy_ev=None):
        """Fill the bottom overlay: row 1 = proposal · scan · sample · channel,
        row 2 = pixel size · dwell · energy (blank fields are dropped)."""
        row1 = "   ".join(p for p in (
            proposal, scan_type, sample,
            f"Channel: {channel}" if channel else "") if p)
        parts = []
        if pixel_um is not None:
            parts.append(f"Pixel: {pixel_um:.3f} µm")
        if dwell_ms is not None:
            parts.append(f"Dwell: {dwell_ms:g} ms")
        if energy_ev is not None:
            parts.append(f"Energy: {energy_ev:.1f} eV")
        self.meta_row1.setText(row1)
        self.meta_row2.setText("   ".join(parts))

    def _update_scalebar(self):
        """Size the scale bar to a 'nice' physical length (~1/5 of the view
        width) and label it, so it stays truthful as the view zooms."""
        try:
            (x0, x1), _ = self.vb.viewRange()
        except Exception:
            return
        span = abs(x1 - x0)
        gw = self.glw.width()
        if span <= 0 or gw <= 0:
            return
        nice = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
        bar_um = min(nice, key=lambda v: abs(v - span / 5.0))
        self._scale_bar_um = bar_um
        self.scalebar.setFixedWidth(max(6, int(bar_um * gw / span)))
        self.scalebar_lbl.setText(
            f"{bar_um * 1000:g} nm" if bar_um < 1.0 else f"{bar_um:g} µm")

    def resizeEvent(self, e):
        self.glw.setGeometry(0, 0, self.width(), self.height())
        h = self._META_BAR_H
        self.meta_bar.setGeometry(0, self.height() - h, self.width(), h)
        self.meta_bar.raise_()
        self._update_scalebar()
        super().resizeEvent(e)


class OverlayImageView(QWidget):
    """A pyqtgraph image viewer with absolutely-positioned overlay labels
    (scale bar + metadata) and optional circular ROI overlays — the shared
    viewer body for the Browser and Analysis views.  Simpler than ``ImageArea``
    (no interactive scan-line/rect-ROI); the field is swapped as state changes."""

    def __init__(self, field, cmap="gray", meta_text="", scale_text="2 µm",
                 parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C['plot_ground']};")
        self.glw = pg.GraphicsLayoutWidget(parent=self)
        self.glw.setBackground(C["plot_ground"])
        self.vb = self.glw.addViewBox()
        self.vb.setAspectLocked(True)
        self.vb.invertY(True)
        self.img = pg.ImageItem()
        self.img.setImage(1 - field)
        self.img.setLookupTable(make_lut(cmap))
        self.vb.addItem(self.img)
        self.vb.autoRange(padding=0)
        self._rois = []

        self.scalebar = QFrame(self)
        self.scalebar.setStyleSheet("background:#ffffff;border:none;")
        self.scalebar.setFixedSize(120, 3)
        self.scalebar_lbl = QLabel(scale_text, self)
        self.scalebar_lbl.setFont(mono_font(9))
        self.scalebar_lbl.setStyleSheet("color:#fff;background:transparent;")
        self.meta = QLabel(meta_text, self)
        self.meta.setFont(mono_font(8))
        self.meta.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.meta.setStyleSheet("color:rgba(255,255,255,.72);background:transparent;")

    def add_circle_roi(self, cx, cy, r, color, label):
        """Non-interactive circular ROI overlay + label chip (Analysis view).
        A plain ellipse item — no drag handles — with a cosmetic (pixel-width) pen."""
        from PySide6.QtWidgets import QGraphicsEllipseItem
        ell = QGraphicsEllipseItem(cx - r, cy - r, 2 * r, 2 * r)
        pen = pg.mkPen(color, width=2)
        pen.setCosmetic(True)
        ell.setPen(pen)
        self.vb.addItem(ell)
        t = pg.TextItem(label, color=color, anchor=(0, 1))
        t.setFont(mono_font(8))
        t.setPos(cx - r, cy - r)
        self.vb.addItem(t)
        self._rois.append((ell, t))

    def set_field(self, field, autolevels=False):
        self.img.setImage(1 - field, autoLevels=autolevels)

    def set_cmap(self, name):
        self.img.setLookupTable(make_lut(name))

    def set_meta(self, text):
        self.meta.setText(text)
        self._reposition()

    def _reposition(self):
        m = 16
        self.scalebar.move(m, self.height() - m - 20)
        self.scalebar_lbl.move(m, self.height() - m - 16)
        self.meta.adjustSize()
        self.meta.move(self.width() - self.meta.width() - m, m)
        for w in (self.scalebar, self.scalebar_lbl, self.meta):
            w.raise_()

    def resizeEvent(self, e):
        self.glw.setGeometry(0, 0, self.width(), self.height())
        self._reposition()
        super().resizeEvent(e)


class MainWindowDashboard(QMainWindow):
    def __init__(self, parent=None, live=True):
        super().__init__(parent)
        self.setWindowTitle("STXM Control — Acquisition")
        self.setStyleSheet(build_stylesheet())
        self.statusBar().setStyleSheet(
            f"QStatusBar{{background:{C['panel_footer']};color:{C['text_dim']};"
            f"border-top:1px solid {C['border']};}}")
        self._scanning = False
        self._move_mode = True          # True = absolute Move, False = relative Jog
        self._motor_group_index = 0     # index into the data-driven motor groups
        self._expert = True
        self._staff_widgets = []          # widgets shown only in Staff mode
        self._motor_widgets = {}          # name -> {value,bar,lo,hi} for live updates
        self._image_seeded = False
        self._ccd_seeded = False
        self._motor_panel = None          # lazily-created Motor Panel window
        self._beamline_panel = None       # lazily-created Beamline Panel window
        # Selected image cursor point (set by clicking the image); read by other
        # actions via cursor_position().  None until the user clicks.
        self._cursor_state = None
        self._cursor_um = None

        # Phase 1: optionally connect to the live server via MainController.
        # The client blocks in its constructor waiting for get_config, so we
        # probe the command port first and only build the controller if a server
        # actually answers — otherwise we run in placeholder mode (dev / no server).
        self.controller = self._maybe_connect_controller(live)

        # Motor config: prefer the server's (authoritative, live positions),
        # fall back to the on-disk file for placeholder mode.
        self._motor_info = {}
        if self.controller is not None:
            self._motor_info = dict(
                self.controller.get_motor_model().get("motor_info", {}) or {})
        if not self._motor_info:
            self._motor_info = self._load_motor_info()

        # DAQ (detector) config: prefer the connected client's live daqConfig,
        # fall back to the on-disk daq.json for placeholder mode.  Drives the
        # Live-detector panel — one tab per detector, typed point/spectrum/image.
        self._daq_info = {}
        client = getattr(self.controller, "client", None)
        if client is not None:
            self._daq_info = dict(getattr(client, "daqConfig", {}) or {})
        if not self._daq_info:
            self._daq_info = self._load_daq_info()

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        # Four top-level views behind the header tab bar.  All stay mounted; only
        # the active one is shown (README §"Interactions": QStackedWidget, inactive
        # timers stopped).  Acquisition is built first so its live-data widgets and
        # signal wiring exist before the placeholder views reuse shared helpers.
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self._build_acquisition_view())
        self.view_stack.addWidget(self._build_browser_view())
        self.view_stack.addWidget(self._build_analysis_view())
        self.view_stack.addWidget(self._build_agent_view())
        outer.addWidget(self.view_stack, 1)
        self.nav_grp.idClicked.connect(self._switch_view)

        # Subscribe to controller signals (read-only live data).
        if self.controller is not None:
            self._connect_controller_signals()
            self._seed_from_controller()
            self._prefill_from_last_scan()

        # Startup image: paint the most recently recorded scan (read from disk),
        # falling back to the black canvas + ROI boxes when none is available.
        self._show_last_scan_image()
        # Sync per-scan-type panel visibility (Focus Z / Line groups hidden unless
        # the initial scan type is Focus).  Runs after the image + controls exist.
        self._on_scan_type(self.scan_type.currentText())
        self._refresh_image_meta()

        # light "live" animation.  When connected, the counter trace is driven by
        # real monitor data, so only the live-detector dot keeps pulsing.
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(66)

        # Server-connection heartbeat: a background thread pings getStatus over a
        # dedicated ZMQ REQ socket (never the client's command socket) and drives
        # the header LED green/red as the server becomes reachable/unreachable.
        # Runs even in placeholder mode so the LED honestly reflects reachability.
        self.server_heartbeat = None
        addr, port = self._server_endpoint()
        if addr and port:
            self.server_heartbeat = ServerHeartbeat(addr, port, self)
            self.server_heartbeat.status_changed.connect(self._on_server_status)
            self.server_heartbeat.start()

        self.resize(2000, 1200)

    def closeEvent(self, event):
        if self.server_heartbeat is not None:
            self.server_heartbeat.stop()
            self.server_heartbeat.wait(2000)
        if self.controller is not None:
            try:
                self.controller.quit_application()
            except Exception:
                pass
        super().closeEvent(event)

    # ── generic builders ────────────────────────────────────────────────
    def _vline(self):
        f = QFrame()
        f.setFixedWidth(1)
        f.setStyleSheet(f"background:{C['border']};border:none;")
        return f

    # ── motor config ────────────────────────────────────────────────────
    _DRIVER_KIND = {
        "derivedPiezo": "PIEZO", "inclinedDerivedPiezo": "PIEZO",
        "mclMotor": "MCL", "xpsMotor": "XPS", "xerMotor": "XERYON",
        "bcsMotor": "BCS", "derivedEnergy": "DERIVED", "epicsMotor": "EPICS",
    }

    # Motor-scan drivers: a scan that steps one or two arbitrary motors, driven
    # from the Motor-scan control group rather than the SampleX/SampleY ROI.  The
    # single variant has one axis; the double variants have two.
    _MOTOR_DRIVERS = {"single_motor_scan", "double_motor_scan",
                      "XRF_double_motor_scan"}
    _SINGLE_MOTOR_DRIVERS = {"single_motor_scan"}

    # Supported scan drivers.  Other scan types (spiral, tomography) report
    # "not yet supported" until their panels are wired.
    _SUPPORTED_SCAN_DRIVERS = {"linear_image", "derived_ptychography_image",
                               "linear_focus", "linear_spectrum",
                               "single_motor_scan", "double_motor_scan",
                               "XRF_double_motor_scan"}

    def _load_motor_info(self):
        """Load motor config from the runtime file the server also reads
        (sys.prefix/pystxmcontrol_cfg/motor.json), falling back to the repo copy.
        Phase 1 will instead read this from controller.get_motor_model()."""
        candidates = [
            os.path.join(sys.prefix, "pystxmcontrol_cfg", "motor.json"),
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "motor.json"),
        ]
        for path in candidates:
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue
        return {}

    def _load_daq_info(self):
        """Load DAQ (detector) config from the runtime file the server also reads
        (sys.prefix/pystxmcontrol_cfg/daq.json), falling back to the repo copy.
        When connected the live client.daqConfig is preferred instead."""
        candidates = [
            os.path.join(sys.prefix, "pystxmcontrol_cfg", "daq.json"),
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "daq.json"),
        ]
        for path in candidates:
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue
        return {}

    def _daqs_sorted(self):
        """Detectors as ``(key, cfg)`` tuples, ordered by the config ``index``
        field (missing → last).  Python's stable sort preserves insertion order
        within equal indices; the ``default`` key naturally sorts first (index 0)."""
        return sorted(self._daq_info.items(),
                      key=lambda kv: kv[1].get("index", 999))

    def _server_endpoint(self):
        """``(address, port)`` of the STXM command server from main.json, or
        ``(None, None)`` if it can't be read.  Wildcard bind addresses are mapped
        to loopback so a client can actually connect."""
        try:
            with open(os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json")) as f:
                srv = json.load(f).get("server", {})
            addr = srv.get("stxm_address", "127.0.0.1")
            if addr in ("*", "0.0.0.0", "::"):
                addr = "127.0.0.1"
            return addr, int(srv.get("command_port"))
        except Exception:
            return None, None

    def _maybe_connect_controller(self, live):
        """Return a connected MainController, or None (placeholder mode).

        We probe the command port with a short socket timeout first: the client
        blocks in its constructor on get_config, so building it against an absent
        server would hang the GUI.  Only build it when a server answers."""
        if not live:
            return None
        addr, port = self._server_endpoint()
        if addr is None or port is None:
            return None
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.6)
        try:
            s.connect((addr, port))
        except Exception:
            print(f"[dashboard] no server at {addr}:{port} — placeholder mode")
            return None
        finally:
            s.close()
        try:
            from pystxmcontrol.gui.controllers.main_controller import MainController
            controller = MainController()
            if controller.initialize_client():
                print(f"[dashboard] connected to server at {addr}:{port}")
                return controller
            print("[dashboard] initialize_client() failed — placeholder mode")
        except Exception as e:
            print(f"[dashboard] controller connection failed ({e}) — placeholder mode")
        return None

    def _on_server_status(self, alive):
        """Heartbeat slot (runs on the GUI thread via a queued connection):
        recolour the LED, and if the server has just appeared while we're still
        in placeholder mode, upgrade the running GUI to live mode."""
        self._set_server_led(alive)
        if alive and self.controller is None:
            self._go_live()

    def _go_live(self):
        """Upgrade a placeholder-mode GUI to live mode once the server appears.

        Adopts the server's *authoritative* motor/detector/scan config (the GUI
        may connect to any of several servers, each with its own hardware) and
        rebuilds the config-driven acquisition view from it, rather than assuming
        the on-disk config the placeholder view was built from still matches.
        The header (server/shutter/energy) and the Browser/Analysis/Agent views
        don't depend on this config, so they're left in place.

        Safe to call repeatedly: it no-ops once a controller exists.  The
        heartbeat only reaches here when getStatus just succeeded, so the
        controller's (blocking) construction won't hang the GUI thread.  This is
        also the intended entry point for a future live server-switch."""
        if self.controller is not None:
            return
        controller = self._maybe_connect_controller(True)
        if controller is None:
            return
        self.controller = controller
        self._adopt_server_config(controller)
        self._rebuild_acquisition_view()
        self._connect_controller_signals()
        self._seed_from_controller()
        self._prefill_from_last_scan()
        # The rebuild reset the image widgets to a black canvas — repaint the
        # last recorded scan and its metadata overlay.
        self._show_last_scan_image()
        self._refresh_image_meta()

        print("[dashboard] server appeared — switched to live mode")
        self.statusBar().showMessage("Connected to server — live mode", 5000)

    def _adopt_server_config(self, controller):
        """Replace the placeholder (on-disk) motor/detector config with the
        connected server's live config, so the rebuilt views reflect whatever
        server we actually connected to.  Falls back to the existing config if
        the server didn't supply a section."""
        motor_info = dict(
            controller.get_motor_model().get("motor_info", {}) or {})
        if motor_info:
            self._motor_info = motor_info
        client = getattr(controller, "client", None)
        daq_info = dict(getattr(client, "daqConfig", {}) or {}) if client else {}
        if daq_info:
            self._daq_info = daq_info

    def _rebuild_acquisition_view(self):
        """Rebuild the acquisition view (stack index 0) in place from the current
        self.controller / self._motor_info / self._daq_info.  The view's builders
        read those at build time (motor tabs, detector panels, and the scan-type
        list all key off them), so a fresh build adopts the live config.  Other
        stack entries keep their fixed indices (Browser 1 / Analysis 2 / Agent 3),
        which _switch_view relies on.  Transient view state (selected tab, image
        seed flags) is intentionally reset — callers repaint afterwards."""
        old = self.view_stack.widget(0)
        was_current = self.view_stack.currentIndex() == 0
        self._image_seeded = False
        self._ccd_seeded = False
        new = self._build_acquisition_view()
        self.view_stack.insertWidget(0, new)   # old shifts to index 1
        self.view_stack.removeWidget(old)
        old.deleteLater()
        if was_current:
            self.view_stack.setCurrentIndex(0)

    def _connect_controller_signals(self):
        c = self.controller
        c.motor_position_updated.connect(self._on_motor_position)
        c.motor_status_updated.connect(self._on_motor_status)
        c.image_updated.connect(self._on_image)
        c.scan_state_changed.connect(self._set_scanning)
        c.external_scan_started.connect(self._on_external_scan_started)
        c.shutter_state_changed.connect(self._on_shutter)
        c.daq_value_updated.connect(self._on_daq_value)
        c.monitor_data_updated.connect(self._on_monitor_data)
        c.scan_progress_updated.connect(self._on_progress_text)
        c.estimated_time_updated.connect(self._on_est_time)
        c.elapsed_time_updated.connect(self._on_elapsed_time)
        c.error_occurred.connect(self._on_error)
        c.status_updated.connect(self._on_status)

    def _seed_from_controller(self):
        """Paint the initial motor positions the server already reported."""
        mm = self.controller.get_motor_model()
        for name in self._motor_info:
            pos = mm.get_position(name)
            if isinstance(pos, (int, float)):
                self._on_motor_position(name, float(pos))

    @staticmethod
    def _frac(val, lo, hi):
        try:
            return max(0.0, min(1.0, (val - lo) / (hi - lo)))
        except (TypeError, ZeroDivisionError):
            return 0.5

    def _group_of(self, d):
        """The motor's tab group, from motor.json's ``group`` field.  Falls back
        to the legacy ``panel`` field (for configs not yet migrated), then to
        ``beamline`` as the default when a motor declares no group at all."""
        for key in ("group", "panel"):
            v = d.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return "beamline"

    def _motors_sorted(self):
        """All motors, index-ordered.  Includes motors flagged ``display: false``
        — use :meth:`_visible_motors` for anything the user sees."""
        return sorted(self._motor_info.items(), key=lambda kv: kv[1].get("index", 999))

    @staticmethod
    def _motor_visible(d):
        """motor.json ``display`` flag → whether the user sees the motor.  Shown
        only when display is truthy (matches the classic GUI's
        ``get('display', False)``), so a motor must opt in to appear."""
        v = d.get("display", False)
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes")
        return bool(v)

    def _visible_motors(self):
        """Index-ordered motors selectable as a scan axis (drops ``display: false``
        ones) — the basis for every motor dropdown.  The move/jog list uses the
        full set instead."""
        return [(n, d) for n, d in self._motors_sorted() if self._motor_visible(d)]

    @staticmethod
    def _fmt_enum(v):
        """Format an allowed-value entry: an integer when whole, else compact."""
        try:
            f = float(v)
            return str(int(f)) if f == int(f) else f"{f:g}"
        except (TypeError, ValueError):
            return str(v)

    @staticmethod
    def _target_text(widget):
        """Read the move/jog target — a dropdown (enumerated motor) or line edit."""
        return (widget.currentText() if isinstance(widget, QComboBox)
                else widget.text())

    def _motor_groups(self):
        """Ordered list of distinct motor groups (tab names).  Order = first
        appearance in index order, i.e. each group ranked by its lowest-index
        motor; the GUI builds one tab per group on startup.  The move/jog panel
        shows every motor (``display`` only gates the scan dropdowns)."""
        groups = []
        for _name, d in self._motors_sorted():
            g = self._group_of(d)
            if g not in groups:
                groups.append(g)
        return groups

    def _motor_rows(self, group):
        """Return row tuples (name, kind, pos, unit, frac, moving) for a group,
        sourced from motor.json (`group`/`unit` fields), sorted by index.  All
        motors are movable here — ``display: false`` only hides a motor from the
        scan-axis dropdowns, not from the move/jog dashboard."""
        rows = []
        for name, d in self._motors_sorted():
            if self._group_of(d) != group:
                continue
            kind = self._DRIVER_KIND.get(d.get("driver"),
                                         str(d.get("driver", "")).upper())
            val = float(d.get("last value", 0.0) or 0.0)
            lo, hi = d.get("minValue"), d.get("maxValue")
            try:
                frac = max(0.0, min(1.0, (val - lo) / (hi - lo)))
            except (TypeError, ZeroDivisionError):
                frac = 0.5
            rows.append((name, kind, f"{val:.2f}", d.get("unit", ""), frac, False))
        return rows

    def _label(self, text, role=None, font=None, color=None):
        lbl = QLabel(text)
        if role:
            lbl.setProperty("role", role)
        if font:
            lbl.setFont(font)
        if color:
            lbl.setStyleSheet(f"color:{color};background:transparent;")
        return lbl

    def _card(self, title, note=None):
        """Return (card QFrame, body QVBoxLayout). Body has no padding — callers
        add their own content widgets/layouts."""
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        header = QFrame()
        header.setObjectName("cardHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 11, 14, 11)
        h = self._label(title.upper())
        h.setObjectName("panelHeading")
        hl.addWidget(h)
        hl.addStretch(1)
        if note is not None:
            self._note_lbl = self._label(note)
            self._note_lbl.setObjectName("panelNote")
            hl.addWidget(self._note_lbl)
        cl.addWidget(header)
        card._header_layout = hl        # expose for extra header controls
        return card, cl

    def _field(self, value="", derived=False, mono=True, align_right=True):
        e = QLineEdit(value)
        if derived:
            e.setProperty("derived", "true")
            e.setReadOnly(True)
        if align_right:
            e.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return e

    def _labeled_field(self, label, value="", derived=False, micro=False):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        lbl = self._label(label, role="microLabel" if micro else "fieldLabel")
        v.addWidget(lbl)
        e = self._field(value, derived=derived)
        v.addWidget(e)
        return w, e

    def _segmented(self, items, checked=0, role="pill"):
        """Segmented pill control inside a well. Returns (frame, [buttons])."""
        well = QFrame()
        well.setProperty("role", "pillWell")
        wl = QHBoxLayout(well)
        wl.setContentsMargins(2, 2, 2, 2)
        wl.setSpacing(2)
        grp = QButtonGroup(well)
        grp.setExclusive(True)
        btns = []
        for i, name in enumerate(items):
            b = QPushButton(name)
            b.setProperty("role", role)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if i == checked:
                b.setChecked(True)
            grp.addButton(b, i)
            wl.addWidget(b)
            btns.append(b)
        well._group = grp
        return well, btns

    def _group_box(self, title, note=None, sep=True):
        """A group in a scrolling controls panel: title row + body layout."""
        w = QFrame()
        if sep:
            w.setObjectName("rowSep")
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(9)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self._label(title.upper(), role="fieldLabel"))
        top.addStretch(1)
        if note:
            top.addWidget(self._label(note, role="monoFaint"))
        v.addLayout(top)
        return w, v

    def _grid4(self, specs):
        """4-column labeled-field grid. specs = [(label, value, derived), ...]."""
        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        edits = []
        for col, (lbl, val, derived) in enumerate(specs):
            g.addWidget(self._label(lbl, role="microLabel"), 0, col)
            e = self._field(val, derived=derived)
            g.addWidget(e, 1, col)
            edits.append(e)
        return g, edits

    # ── header ───────────────────────────────────────────────────────────
    def _build_header(self):
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)

        # logo + title
        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(20, 0, 20, 0)
        bl.setSpacing(14)
        logo = QLabel()
        px = QPixmap(os.path.join(_ICONS_DIR, "als-logo.png"))
        if not px.isNull():
            logo.setPixmap(px.scaledToHeight(26, Qt.SmoothTransformation))
        bl.addWidget(logo)
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        t = self._label("STXM Control")
        t.setFont(sans_font(11, QFont.DemiBold))
        sub = self._label("7.0.1.2 COSMIC · 250–2500 eV", role="monoFaint")
        title_box.addWidget(t)
        title_box.addWidget(sub)
        bl.addLayout(title_box)
        hl.addWidget(brand)
        hl.addWidget(self._vline())

        # app nav tabs
        nav = QWidget()
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(16, 0, 16, 0)
        nl.setSpacing(2)
        self.nav_grp = QButtonGroup(nav)
        self.nav_grp.setExclusive(True)
        for i, name in enumerate(("Acquisition", "Browser", "Analysis", "Agent")):
            b = QPushButton(name)
            b.setProperty("role", "navtab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if i == 0:
                b.setChecked(True)
            self.nav_grp.addButton(b, i)
            nl.addWidget(b)
        hl.addWidget(nav)

        hl.addStretch(1)

        # readouts
        def readout(label, value, role="value"):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(22, 0, 22, 0)
            v.setSpacing(2)
            v.addStretch(1)
            lab = self._label(label.upper(), role="fieldLabel")
            val = self._label(value, role=role)
            val.setFont(mono_font(12, QFont.Medium))
            v.addWidget(lab)
            v.addWidget(val)
            v.addStretch(1)
            return w, val

        rc, self.beam_val = readout("Beam current", "499.6 mA")
        hl.addWidget(self._vline()); hl.addWidget(rc)
        pe, self.energy_val = readout("Photon energy", "705.0 eV", role="accent")
        hl.addWidget(self._vline()); hl.addWidget(pe)
        hl.addWidget(self._vline()); hl.addWidget(self._build_shutter_control())

        # server status
        hl.addWidget(self._vline())
        srv = QWidget()
        sv = QHBoxLayout(srv)
        sv.setContentsMargins(20, 0, 20, 0)
        sv.setSpacing(9)
        # LED starts grey (status unknown) until the first heartbeat probe
        # resolves it to green (reachable) or red (unreachable).
        self.server_led = QLabel("●")
        self._set_server_led(None)
        sv.addWidget(self.server_led)
        sbox = QVBoxLayout()
        sbox.setSpacing(1)
        addr, port = self._server_endpoint()
        endpoint = f"{addr}:{port}" if addr and port else "not configured"
        sbox.addWidget(self._label("stxmserver", font=sans_font(10, QFont.Medium)))
        sbox.addWidget(self._label(endpoint, role="monoFaint"))
        sv.addLayout(sbox)
        hl.addWidget(srv)

        # mode toggle
        hl.addWidget(self._vline())
        modew = QWidget()
        mv = QHBoxLayout(modew)
        mv.setContentsMargins(20, 0, 20, 0)
        self.mode_btn = QPushButton("Staff mode")
        self.mode_btn.setObjectName("modeToggle")
        self.mode_btn.setCursor(Qt.PointingHandCursor)
        self.mode_btn.clicked.connect(self._toggle_expert)
        mv.addWidget(self.mode_btn)
        hl.addWidget(modew)
        return header

    # Shutter (gate) mode: combobox index ↔ setGate command ↔ reported gate mode.
    _SHUTTER_INDEX_TO_CMD = {0: "auto", 1: "open", 2: "closed"}
    _SHUTTER_MODE_TO_INDEX = {"auto": 0, "open": 1, "close": 2, "closed": 2}

    # Shutter-state LED colour per combobox index (auto / open / closed).
    _SHUTTER_LED_COLOR = {0: "ok", 1: "ok", 2: "alert"}

    def _build_shutter_control(self):
        """Selectable shutter control (Auto / Open / Closed) with a status LED to
        its left (red when Closed).  The label sits left of the dropdown.
        Selecting a mode sends ``setGate`` to the server; ``_on_shutter`` syncs it
        back to the gate mode the server reports."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(22, 0, 22, 0)
        h.setSpacing(9)
        self.shutter_led = QLabel("●")
        h.addWidget(self.shutter_led)
        h.addWidget(self._label("SHUTTER", role="fieldLabel"))
        self.shutter_combo = QComboBox()
        self.shutter_combo.addItems(["Auto", "Open", "Closed"])
        self.shutter_combo.setCursor(Qt.PointingHandCursor)
        # Connect after populating so the initial index-0 signal isn't sent as a
        # command at startup (we wait for the server's reported state instead).
        self.shutter_combo.currentIndexChanged.connect(self._on_shutter_selected)
        h.addWidget(self.shutter_combo)
        self._set_shutter_led(0)
        return w

    def _set_server_led(self, alive):
        """Colour the server-connection LED: reachable→green, unreachable→red,
        unknown (None, before the first probe)→grey.  Slot for
        ``ServerHeartbeat.status_changed`` (delivered on the GUI thread)."""
        token = "ok" if alive else ("alert" if alive is False else "text_faint")
        self.server_led.setStyleSheet(
            f"color:{C[token]};background:transparent;font-size:11px;")

    def _set_shutter_led(self, index):
        """Colour the shutter LED from the (index-mapped) state: closed→red,
        open/auto→green."""
        color = C[self._SHUTTER_LED_COLOR.get(index, "motion")]
        self.shutter_led.setStyleSheet(
            f"color:{color};background:transparent;font-size:11px;")

    def _on_shutter_selected(self, index):
        """User picked a shutter mode → send the setGate command to the server."""
        self._set_shutter_led(index)
        if self.controller is not None:
            self.controller.set_gate(
                self._SHUTTER_INDEX_TO_CMD.get(index, "auto"))

    # ── acquisition view (3-column body) ─────────────────────────────────
    def _build_acquisition_view(self):
        body = QWidget()
        body.setStyleSheet(f"background:{C['canvas']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(10)
        col1 = self._build_col1(); col1.setFixedWidth(474)
        col2 = self._build_col2()
        col3 = self._build_col3(); col3.setFixedWidth(500)
        bl.addWidget(col1)
        bl.addWidget(col2, 1)
        bl.addWidget(col3)
        return body

    def _switch_view(self, index):
        """Header tab → body view.  Pause the analysis filmstrip when it isn't
        on screen so its timer doesn't run in the background."""
        self.view_stack.setCurrentIndex(index)
        if index != 2 and getattr(self, "_a_playing", False):
            self._toggle_analysis_play()

    # ── column 1: scan config + acquisition controls ────────────────────
    def _build_col1(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(self._build_scan_def())
        v.addWidget(self._build_acq_controls(), 1)
        return col

    def _build_scan_def(self):
        card, body = self._card("Scan definition", "scan.json")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(14, 14, 14, 14)
        cv.setSpacing(12)

        # scan type + mode
        row = QGridLayout()
        row.setHorizontalSpacing(10)
        row.setVerticalSpacing(5)
        row.addWidget(self._label("SCAN TYPE", role="fieldLabel"), 0, 0)
        self.scan_type = QComboBox()
        # When connected, the scan types must be the real scan.json keys (so
        # client.scanConfig[scan_type] resolves at compile time); otherwise use
        # the design's placeholder list for offline layout review.
        live_types = (self.controller.get_available_scan_types()
                      if self.controller is not None else [])
        if live_types:
            self.scan_type.addItems(live_types)
            self.scan_type.setCurrentText("Image" if "Image" in live_types
                                          else live_types[0])
        else:
            self.scan_type.addItems(["Image", "Ptychography Image", "Image Stack (XANES)",
                                     "Line Spectrum", "Tomography", "Focus", "OSA Image",
                                     "Single Motor", "Double Motor"])
            self.scan_type.setCurrentText("Image Stack (XANES)")
        self.scan_type.setCursor(Qt.PointingHandCursor)
        self.scan_type.currentTextChanged.connect(self._on_scan_type)
        row.addWidget(self.scan_type, 1, 0)
        row.addWidget(self._label("MODE", role="fieldLabel"), 0, 1)
        self.mode_field = QLineEdit("continuousLine")
        self.mode_field.setReadOnly(True)
        self.mode_field.setProperty("derived", "true")
        row.addWidget(self.mode_field, 1, 1)
        cv.addLayout(row)

        # sub-tabs
        subbar = QHBoxLayout()
        subbar.setContentsMargins(0, 0, 0, 0)
        subbar.setSpacing(2)
        self.sub_grp = QButtonGroup(self)
        self.sub_grp.setExclusive(True)
        for i, name in enumerate(("Spatial", "Energy", "Detector")):
            b = QPushButton(name)
            b.setProperty("role", "subtab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if i == 0:
                b.setChecked(True)
            self.sub_grp.addButton(b, i)
            subbar.addWidget(b)
        subbar.addStretch(1)
        subwrap = QFrame()
        subwrap.setStyleSheet(f"border-bottom:1px solid {C['border']};")
        subwrap.setLayout(subbar)
        cv.addWidget(subwrap)

        # stacked config bodies
        self.config_stack = QStackedWidget()
        self.config_stack.addWidget(self._spatial_page())
        self.config_stack.addWidget(self._energy_page())
        self.config_stack.addWidget(self._detector_page())
        self.sub_grp.idClicked.connect(self.config_stack.setCurrentIndex)
        cv.addWidget(self.config_stack)

        body.addWidget(content)

        # footer: stats + begin/preview
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(14, 12, 14, 12)
        fv.setSpacing(11)
        stats = QHBoxLayout()
        self._stat_labels = {}
        for lbl, val in (("Est. time", "18:24"), ("Velocity", "0.500 mm/s"),
                         ("Points", "14 400")):
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(self._label(lbl.upper(), role="fieldLabel"))
            v_ = self._label(val, role="valueBig")
            box.addWidget(v_)
            self._stat_labels[lbl] = v_
            stats.addLayout(box)
        fv.addLayout(stats)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.begin_btn = QPushButton("Begin scan")
        self.begin_btn.setObjectName("beginScan")
        self.begin_btn.setCursor(Qt.PointingHandCursor)
        self.begin_btn.clicked.connect(self._toggle_scan)
        preview = QPushButton("Preview")
        preview.setCursor(Qt.PointingHandCursor)
        preview.setToolTip("Run an abridged scan — first region, single energy — "
                           "as a quick check without disturbing the full definition.")
        preview.clicked.connect(self._preview_scan)
        self.preview_btn = preview
        btns.addWidget(self.begin_btn, 1)
        btns.addWidget(preview)
        fv.addLayout(btns)
        body.addWidget(footer)
        return card

    def _spatial_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(6)
        for col, h in enumerate(("", "Center", "Range", "N pts", "Step")):
            lbl = self._label(h, role="microLabel")
            lbl.setAlignment(Qt.AlignCenter)
            g.addWidget(lbl, 0, col)
        rows = [("SampleX", "-315.000", "12.000", "120", "0.100"),
                ("SampleY", "166.000", "12.000", "120", "0.100")]
        # Field refs keyed by motor, used by _compile_scan to build the region.
        self._spatial_fields = {}
        for r, (name, c, rng, n, step) in enumerate(rows, start=1):
            g.addWidget(self._label(name, role="mono"), r, 0)
            e_c = self._field(c); e_rng = self._field(rng)
            e_n = self._field(n); e_step = self._field(step, derived=True)
            g.addWidget(e_c, r, 1)
            g.addWidget(e_rng, r, 2)
            g.addWidget(e_n, r, 3)
            g.addWidget(e_step, r, 4)
            # Any edit re-derives Step and pushes the row into the active region.
            for e in (e_c, e_rng, e_n):
                e.editingFinished.connect(self._on_spatial_edit)
            self._spatial_fields[name] = {
                "center": e_c, "range": e_rng, "npts": e_n, "step": e_step}
        g.setColumnStretch(0, 0)
        for col in range(1, 5):
            g.setColumnStretch(col, 1)
        v.addLayout(g)

        # Region model: image regions are drawn as ROI boxes on the live image
        # and edited through the single grid above; the *active* box indicates
        # which region the grid drives.  Seed one region from the field values.
        self._active_region = 0          # int index, or 'spectrum'
        self._spectrum_region = None
        self._syncing_spatial = False
        self._scan_regions = [self._read_spatial_fields()]

        # Focus-scan state.  A focus scan uses the R1 centre as the line centre
        # plus its own line length/angle/points and a ZonePlateZ sweep.  Built on
        # first switch to Focus (defaults from live ZonePlateZ + R1 width).
        self._focus_mode = False
        # Line-Spectrum shares the single-line ROI machinery with Focus, but its
        # slow axis is energy (multi-region, like Image) rather than ZonePlateZ,
        # and its streak display is energy (x) × position-along-line (y).  The
        # shared "line model" below (self._focus_region) carries the line's
        # length/angle/points in both modes.
        self._ls_mode = False
        # Motor scans (single_motor_scan / double_motor_scan / XRF variant) replace
        # the SampleX/SampleY ROI with explicit motor-selection + range controls
        # (built in _build_acq_controls).  Like the line scans they take over the
        # image display; unlike them they draw no ROI on the sample image.
        self._motor_scan_mode = False
        self._focus_region = None
        # Saved image state captured on entering a single-line mode (Focus or Line
        # Spectrum), so leaving it can drop the (distant) streak and put the sample
        # image back.
        self._pre_focus_snapshot = None      # ImageArea frame snapshot
        self._pre_focus_regions = None       # (regions, active, spectrum) tuple
        self._last_image_scan_type = None    # combo returns here after a line scan

        # Checkboxes on their own row …
        checks = QHBoxLayout()
        checks.setSpacing(7)
        self._scan_checks = {}
        for name, on in (("spectrum", False), ("autofocus", True),
                         ("show ROI", True), ("tiled", False), ("defocus", False)):
            cb = QCheckBox(name)
            cb.setChecked(on)
            cb.setCursor(Qt.PointingHandCursor)
            checks.addWidget(cb)
            self._scan_checks[name] = cb
        self._scan_checks["spectrum"].toggled.connect(self._toggle_spectrum)
        self._scan_checks["show ROI"].toggled.connect(
            lambda _on: self._refresh_spatial_image())
        checks.addStretch(1)
        v.addLayout(checks)

        # … and the region add/remove buttons on a row below (so neither is
        # squeezed by the other).
        btns = QHBoxLayout()
        btns.setSpacing(7)
        add = QPushButton("+ Region")
        add.setProperty("role", "small")
        add.clicked.connect(self._add_spatial_region)
        self._add_region_btn = add
        btns.addWidget(add)
        self._del_region_btn = QPushButton("− Region")
        self._del_region_btn.setProperty("role", "small")
        self._del_region_btn.clicked.connect(self._remove_spatial_region)
        btns.addWidget(self._del_region_btn)
        btns.addStretch(1)
        v.addLayout(btns)
        v.addStretch(1)
        return page

    def _energy_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        specs = [("Start", "700.0", False), ("Stop", "730.0", False),
                 ("Step", "0.25", False), ("N", "121", False),
                 ("Dwell ms", "2.0", False)]
        self._energy_fields = {}
        keys = ["start", "stop", "step", "n", "dwell"]
        for col, (lbl, val, derived) in enumerate(specs):
            g.addWidget(self._label(lbl, role="microLabel"), 0, col)
            e = self._field(val, derived=derived)
            g.addWidget(e, 1, col)
            g.setColumnStretch(col, 1)
            self._energy_fields[keys[col]] = e
        # Step and N are co-dependent over the range: editing Start/Stop/Step
        # updates N, editing N updates Step.  Any edit is written back into the
        # active region so the strip below reflects it.
        for k in ("start", "stop", "step"):
            self._energy_fields[k].editingFinished.connect(self._recompute_energy_n)
        self._energy_fields['n'].editingFinished.connect(self._recompute_energy_step)
        self._energy_fields['dwell'].editingFinished.connect(
            self._sync_active_energy_region)
        v.addLayout(g)

        # Energy regions: a list of {start, stop, step, dwell, n}; the field row
        # above edits whichever region is active.  Seed with one region from the
        # default field values.
        self._energy_regions = [self._read_energy_fields()]
        self._active_energy_region = 0

        well = QFrame()
        well.setStyleSheet(f"background:{C['well']};border:1px solid {C['border']};"
                           "border-radius:6px;")
        wv = QVBoxLayout(well)
        wv.setContentsMargins(12, 10, 12, 6)
        wv.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(self._label("ENERGY REGIONS", role="fieldLabel"))
        top.addStretch(1)
        self._energy_summary_lbl = self._label("", role="accent")
        top.addWidget(self._energy_summary_lbl)
        wv.addLayout(top)
        self._energy_strip = EnergyRegionStrip([])
        self._energy_strip.region_clicked.connect(self._select_energy_region)
        wv.addWidget(self._energy_strip)
        self._energy_axis = QHBoxLayout()
        self._energy_axis_lbls = []
        for i in range(4):
            lbl = self._label("", role="monoFaint")
            self._energy_axis_lbls.append(lbl)
            self._energy_axis.addWidget(lbl)
            if i < 3:
                self._energy_axis.addStretch(1)
        wv.addLayout(self._energy_axis)
        v.addWidget(well)

        btns = QHBoxLayout()
        btns.setSpacing(7)
        add_btn = QPushButton("+ Energy region")
        add_btn.setProperty("role", "small")
        add_btn.clicked.connect(self._add_energy_region)
        btns.addWidget(add_btn)
        self._del_energy_btn = QPushButton("− Remove region")
        self._del_energy_btn.setProperty("role", "small")
        self._del_energy_btn.clicked.connect(self._remove_energy_region)
        btns.addWidget(self._del_energy_btn)
        preset_btn = QPushButton("Load edge preset")
        preset_btn.setProperty("role", "small")
        btns.addWidget(preset_btn)
        btns.addStretch(1)
        v.addLayout(btns)

        self._refresh_energy_strip()
        return page

    def _detector_page(self):
        page = QWidget()
        g = QGridLayout(page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(10)
        fields = [("DAQ", "Counter1 · 53230A", "mono", False),
                  ("Area detector", "fCCD 1k · binned 2×", "mono", False),
                  ("Exposure ms", "20.0", None, True),
                  ("Double exposure", "enabled · 1:8", "ok", False),
                  ("Trigger", "position · line", "mono", False),
                  ("ZMQ stream", "tcp://*:5556", "ok", False)]
        self._exposure_field = None
        self._double_exposure_ro = None
        for i, (lbl, val, role, editable) in enumerate(fields):
            r, c = divmod(i, 2)
            box = QVBoxLayout()
            box.setSpacing(4)
            box.addWidget(self._label(lbl, role="microLabel"))
            if editable:
                e = self._field(val)
                if lbl.startswith("Exposure"):
                    self._exposure_field = e
                box.addWidget(e)
            else:
                ro = QLineEdit(val)
                ro.setReadOnly(True)
                ro.setProperty("derived", "true")
                if role == "ok":
                    ro.setStyleSheet(f"color:{C['ok']};")
                ro.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if lbl.startswith("Double exposure"):
                    self._double_exposure_ro = ro
                box.addWidget(ro)
            g.addLayout(box, r, c)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        g.setRowStretch(3, 1)
        return page

    def _build_acq_controls(self):
        card, body = self._card("Acquisition controls", "continuousLine")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(0)

        # Focus Z
        w, gv = self._group_box("Focus Z", "ZonePlateZ · Focus, Image Stack")
        self._focus_group = w
        grid, fz_edits = self._grid4([("Center", "0.000", False), ("Range", "100.000", False),
                               ("Points", "50", False), ("Step µm", "2.000", True)])
        self._focus_fields = {"center": fz_edits[0], "range": fz_edits[1],
                              "points": fz_edits[2], "step": fz_edits[3]}
        for e in (fz_edits[1], fz_edits[2]):     # range / points re-derive step
            e.editingFinished.connect(self._on_focus_edit)
        fz_edits[0].editingFinished.connect(self._on_focus_edit)
        gv.addLayout(grid)
        r = QHBoxLayout()
        b = QPushButton("Set center to current"); b.setProperty("role", "small")
        b.clicked.connect(self._focus_center_to_current)
        r.addWidget(b)
        cb = QCheckBox("move to best focus"); cb.setChecked(True)
        self._focus_move_to_best = cb
        r.addWidget(cb); r.addStretch(1)
        gv.addLayout(r)
        # Zone-plate focus calibration (from the Energy motor's A0/A1). A0 sets the
        # focus offset (shown to all); A1 is the slope coefficient (staff-only).
        energy = self._motor_info.get("Energy", {})
        zp = QGridLayout()
        zp.setHorizontalSpacing(6)
        zp.setVerticalSpacing(4)
        zp.addWidget(self._label("Zone Plate A0", role="microLabel"), 0, 0)
        self._a0_field = self._field(f"{float(energy.get('A0', 0.0)):.4f}")
        zp.addWidget(self._a0_field, 1, 0)
        a1_lbl = self._label("Zone Plate A1 · staff", role="microLabel")
        a1_edit = self._field(f"{float(energy.get('A1', 0.0)):.4f}")
        zp.addWidget(a1_lbl, 0, 1)
        zp.addWidget(a1_edit, 1, 1)
        zp.setColumnStretch(0, 1)
        zp.setColumnStretch(1, 1)
        gv.addLayout(zp)
        self._staff_widgets += [a1_lbl, a1_edit]
        iv.addWidget(w)

        # Line
        w, gv = self._group_box("Line", "Focus, Line Spectrum")
        self._line_group = w
        grid, ln_edits = self._grid4([("Length µm", "10.000", False), ("Angle °", "0.0", False),
                               ("Points", "50", False), ("Step µm", "0.200", True)])
        self._line_fields = {"length": ln_edits[0], "angle": ln_edits[1],
                             "points": ln_edits[2], "step": ln_edits[3]}
        for e in ln_edits[:3]:                   # length / angle / points
            e.editingFinished.connect(self._on_line_edit)
        gv.addLayout(grid)
        r = QHBoxLayout()
        b = QPushButton("Draw line on image"); b.setProperty("role", "small")
        b.clicked.connect(self._refresh_focus_line)
        r.addWidget(b)
        self._line_endpoints_lbl = self._label("", role="monoFaint")
        r.addWidget(self._line_endpoints_lbl)
        r.addStretch(1)
        gv.addLayout(r)
        iv.addWidget(w)

        # Motor scan — one axis (Single Motor) or two (Double Motor / OSA Image /
        # any double_motor_scan family).  Each axis is a motor dropdown + a
        # Center / Range / Points / Step grid (mirrors the Loop sequence widget).
        # The dropdowns pre-select from the scan config's x_motor / y_motor.
        w, gv = self._group_box("Motor scan", "Single / Double Motor")
        self._motor_group = w
        self._motor_axis_widgets = []
        for axis in range(2):
            block = QWidget()
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            lbl = self._label("X MOTOR" if axis == 0 else "Y MOTOR",
                              role="microLabel")
            bl.addWidget(lbl)
            combo = QComboBox()
            combo.addItems([name for name, _ in self._visible_motors()])
            combo.setCursor(Qt.PointingHandCursor)
            combo.currentIndexChanged.connect(
                lambda _i, a=axis: self._on_motor_selected(a))
            bl.addWidget(combo)
            grid, edits = self._grid4([("Center", "0.000", False),
                                       ("Range", "10.000", False),
                                       ("Points", "50", False),
                                       ("Step", "0.200", True)])
            bl.addLayout(grid)
            for e in edits[:3]:
                e.editingFinished.connect(self._on_motor_edit)
            gv.addWidget(block)
            self._motor_axis_widgets.append({
                "block": block, "label": lbl, "combo": combo, "center": edits[0],
                "range": edits[1], "npts": edits[2], "step": edits[3]})
        iv.addWidget(w)

        # Loop sequence
        w, gv = self._group_box("Loop sequence", "outer motor loop")
        lbl = self._label("MOTOR", role="microLabel")
        gv.addWidget(lbl)
        combo = QComboBox()
        combo.addItems([name for name, _ in self._visible_motors()])
        combo.setCursor(Qt.PointingHandCursor)
        gv.addWidget(combo)
        grid, _ = self._grid4([("Center", "-118.400", False), ("Range", "20.000", False),
                               ("Points", "11", False), ("Step", "2.000", True)])
        gv.addLayout(grid)
        r = QHBoxLayout()
        b = QPushButton("+ Nested loop"); b.setProperty("role", "small")
        r.addWidget(b)
        cb = QCheckBox("return to center after"); cb.setChecked(True)
        r.addWidget(cb); r.addStretch(1)
        gv.addLayout(r)
        iv.addWidget(w)

        # Output
        w, gv = self._group_box("Output")
        r = QGridLayout()
        r.setHorizontalSpacing(7)
        r.addWidget(self._label("File prefix", role="microLabel"), 0, 0)
        r.addWidget(self._label("Index", role="microLabel"), 0, 1)
        prefix = self._field("NS_260807", align_right=False)
        idx = self._field("045", derived=True)
        r.addWidget(prefix, 1, 0)
        r.addWidget(idx, 1, 1)
        r.setColumnStretch(0, 1)
        gv.addLayout(r)
        gv.addWidget(self._label("Sample", role="microLabel"))
        sample = QLineEdit("particle collection, Fe screening")
        sample.setFont(sans_font(10))
        self._sample_field = sample
        self._prefix_field = prefix
        gv.addWidget(sample)
        iv.addWidget(w)

        # Presets
        w, gv = self._group_box("Presets", sep=False)
        pr = QHBoxLayout()
        pr.setSpacing(6)
        for name in ("Fe L₃ survey", "Fine ptycho 5 nm", "Focus series", "Save current…"):
            b = QPushButton(name); b.setProperty("role", "preset")
            pr.addWidget(b)
        pr.addStretch(1)
        gv.addLayout(pr)
        iv.addWidget(w)

        iv.addStretch(1)
        scroll.setWidget(inner)
        body.addWidget(scroll, 1)

        # footer: proposal + load/script
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QHBoxLayout(footer)
        fv.setContentsMargins(14, 10, 14, 10)
        pbox = QVBoxLayout()
        pbox.setSpacing(3)
        pbox.addWidget(self._label("Proposal", font=sans_font(10), color=C["text_dim"]))
        self._proposal_lbl = self._label("ALS-14872 · Shapiro", role="mono")
        pbox.addWidget(self._proposal_lbl)
        fv.addLayout(pbox)
        fv.addStretch(1)
        for name in ("Load scan", "Script"):
            b = QPushButton(name); b.setProperty("role", "small")
            fv.addWidget(b)
        body.addWidget(footer)
        return card

    # ── column 2: image viewer + bottom strip ───────────────────────────
    def _build_col2(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(self._build_image_viewer(), 1)
        v.addWidget(self._build_bottom_strip())
        return col

    def _build_image_viewer(self):
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # toolbar
        tb = QFrame()
        tb.setObjectName("cardHeader")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(16)
        fn = self._label("NS_260806042.stxm", role="value")
        fn.setFont(mono_font(16, QFont.DemiBold))
        self._image_title_lbl = fn
        tl.addWidget(fn)
        tl.addWidget(self._label("Region 1 of 1 · Energy 82 of 121",
                                 font=sans_font(10), color=C["text_dim"]))
        tl.addStretch(1)
        cmap_well, self.cmap_btns = self._segmented(["gray", "viridis", "inferno"], 0)
        for i, b in enumerate(self.cmap_btns):
            b.clicked.connect(lambda _=False, n=("gray", "viridis", "inferno")[i]:
                              self._set_cmap(n))
        tl.addWidget(cmap_well)
        for name in ("Levels", "FFT", "Unzoom", "Save"):
            b = QPushButton(name); b.setProperty("role", "small")
            tl.addWidget(b)
        cl.addWidget(tb)

        # body: image + right rail
        bodyw = QWidget()
        bl = QHBoxLayout(bodyw)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.image_area = ImageArea()
        self.image_area.roi_selected.connect(self._on_roi_selected)
        self.image_area.roi_moving.connect(self._on_roi_moving)
        self.image_area.roi_moved.connect(self._on_roi_moved)
        self.image_area.line_moving.connect(self._on_line_moving)
        self.image_area.line_moved.connect(self._on_line_moved)
        self.image_area.cursor_changed.connect(self._on_cursor)
        bl.addWidget(self.image_area, 1)
        # Region model was built in _spatial_page (col1, earlier); paint it now
        # that the image exists.
        self._refresh_spatial_image(fit=True)

        # Right rail: the real pyqtgraph HistogramLUTWidget (draggable levels +
        # gradient/LUT editor), bound to the image's ImageItem.  This is the same
        # control pg.ImageView exposes, minus the timeline.  The colormap pills
        # load gradient presets into it.
        rail = QFrame()
        rail.setFixedWidth(150)
        rail.setStyleSheet(f"background:{C['panel_footer']};border:none;"
                           f"border-left:1px solid {C['border']};")
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(6, 12, 8, 12)
        rv.setSpacing(6)
        self.hist_lut = pg.HistogramLUTWidget()
        self.hist_lut.setBackground(C["panel_footer"])
        self.hist_lut.setImageItem(self.image_area.img)
        self.hist_lut.gradient.loadPreset("grey")
        # Keep the mosaic's secondary tiles in LUT/levels sync with the primary.
        self.hist_lut.sigLookupTableChanged.connect(
            lambda _h: self.image_area.sync_lut_levels())
        self.hist_lut.sigLevelsChanged.connect(
            lambda _h: self.image_area.sync_lut_levels())
        for ax in ("axis",):
            try:
                self.hist_lut.axis.setPen(C["border"])
                self.hist_lut.axis.setTextPen(C["text_faint"])
            except Exception:
                pass
        rv.addWidget(self.hist_lut, 1)
        bl.addWidget(rail)
        cl.addWidget(bodyw, 1)

        # footer: cursor readout + buttons
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QHBoxLayout(footer)
        fv.setContentsMargins(14, 10, 14, 10)
        fv.setSpacing(22)
        self._cursor_readout = {}
        self._cursor_readout_keys = {}
        for lbl, val in (("X", "—"), ("Y", "—"), ("I", "—"), ("OD", "—")):
            cur = QHBoxLayout()
            cur.setSpacing(6)
            k = self._label(lbl, font=mono_font(11), color=C["text_dim"])
            val_l = self._label(val, font=mono_font(11), color=C["text"])
            cur.addWidget(k); cur.addWidget(val_l)
            fv.addLayout(cur)
            self._cursor_readout[lbl] = val_l
            self._cursor_readout_keys[lbl] = k
        fv.addStretch(1)
        self._cursor_action_btns = {}
        for name in ("Set cursor to 0", "Move to cursor", "Focus to cursor"):
            b = QPushButton(name); b.setProperty("role", "small")
            fv.addWidget(b)
            self._cursor_action_btns[name] = b
        # Focus-to-cursor calibration is only meaningful on a focus streak after a
        # click; enabled by _on_cursor in focus-display mode, disabled otherwise.
        fbtn = self._cursor_action_btns["Focus to cursor"]
        fbtn.clicked.connect(self._on_focus_to_cursor)
        fbtn.setEnabled(False)
        cl.addWidget(footer)
        return card

    def _build_bottom_strip(self):
        strip = QWidget()
        strip.setFixedHeight(214)
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)

        # Profile: ROI spectrum OR live cursor line-outs, switched by a pill group
        # in the card header (spectrum isn't always the relevant readout).
        prof_card, prof_body = self._card("Profile")
        prof_well, _ = self._segmented(["Spectrum", "Line-outs"], 1)
        prof_card._header_layout.insertWidget(1, prof_well)
        prof_card._header_layout.insertSpacing(2, 10)
        # Right side of the header: the spectrum note OR the X/Y line-cut pill,
        # whichever the active tab needs (they share the slot; only one shows).
        self._profile_note = self._label("Fe L3 · OD vs eV", role="accent")
        prof_card._header_layout.addWidget(self._profile_note)
        self._lineout_axis_well, _ = self._segmented(["X", "Y"], 0)
        prof_card._header_layout.addWidget(self._lineout_axis_well)

        self._profile_stack = QStackedWidget()
        self._profile_stack.addWidget(self._spectrum_panel())
        self._profile_stack.addWidget(self._lineout_panel())
        prof_body.addWidget(self._profile_stack, 1)
        prof_well._group.idClicked.connect(self._switch_profile)
        self._lineout_axis_well._group.idClicked.connect(self._set_lineout_axis)
        # Default to the Line-outs tab (matches the checked pill above).
        self._switch_profile(1)
        sl.addWidget(prof_card, 135)

        # scan progress
        prog_card, prog_body = self._card("Scan progress", "12:47 / 18:24")
        self.progress_time_lbl = self._note_lbl      # header "elapsed / est"
        content = QWidget()
        pv = QVBoxLayout(content)
        pv.setContentsMargins(14, 14, 14, 14)
        pv.setSpacing(12)
        top = QHBoxLayout()
        self.progress_caption = self._label("—",
                                             font=sans_font(10), color=C["text_dim"])
        top.addWidget(self.progress_caption)
        top.addStretch(1)
        self.pct_lbl = self._label("0%", role="value")
        top.addWidget(self.pct_lbl)
        pv.addLayout(top)
        self.progress = ProgressBar(0.0)
        pv.addWidget(self.progress)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self._progress_stats = {}
        stats = [("Lines done", "—", "value"), ("Estimated time", "—", "value"),
                 ("Missed triggers", "0", "ok"), ("Elapsed time", "—", "value")]
        for i, (lbl, val, role) in enumerate(stats):
            r, c = divmod(i, 2)
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(self._label(lbl.upper(), role="fieldLabel"))
            v_ = self._label(val, role=role)
            v_.setFont(mono_font(14))
            box.addWidget(v_)
            grid.addLayout(box, r, c)
            self._progress_stats[lbl] = v_
        pv.addLayout(grid)
        prog_body.addWidget(content, 1)
        sl.addWidget(prog_card, 100)
        return strip

    @staticmethod
    def _style_plot(pw):
        pw.setBackground(C["plot_ground"])
        pw.showGrid(x=True, y=True, alpha=0.15)
        for ax in ("bottom", "left"):
            pw.getAxis(ax).setPen(C["border"])
            pw.getAxis(ax).setTextPen(C["text_faint"])
        return pw

    def _spectrum_panel(self):
        """ROI absorption spectrum (OD vs eV) — placeholder trace for now."""
        pw = self._style_plot(pg.PlotWidget())
        e, od = _spectrum()
        pw.plot(e[:82], od[:82], pen=pg.mkPen(C["accent"], width=2))
        cursor = pg.InfiniteLine(pos=e[81], angle=90,
                                 pen=pg.mkPen(QColor(95, 212, 214, 90), width=1))
        pw.addItem(cursor)
        return pw

    def _lineout_panel(self):
        """A single cursor line-cut through the image, in physical µm — the
        horizontal (X, red) or vertical (Y, cyan) cut, toggled by the X/Y pill in
        the card header.  The two cuts live on very different position axes, so
        only one shows at a time.  Fed live by ImageArea.cursor_changed."""
        pw = self._style_plot(pg.PlotWidget())
        pw.setLabel("bottom", "x", units="µm")
        self._lineout_plot = pw
        self._lineout_h = pw.plot([], [], pen=pg.mkPen("#ff3b30", width=1.6))
        self._lineout_v = pw.plot([], [], pen=pg.mkPen("#37d7ff", width=1.6))
        self._lineout_axis = 0          # 0 = X (horizontal cut), 1 = Y (vertical)
        self._last_cursor = None
        return pw

    def _switch_profile(self, index):
        """Swap the header's right-hand control with the tab: the spectrum note
        for Spectrum, the X/Y line-cut pill for Line-outs."""
        self._profile_stack.setCurrentIndex(index)
        lineout = index == 1
        self._profile_note.setVisible(not lineout)
        self._lineout_axis_well.setVisible(lineout)

    def _set_lineout_axis(self, index):
        self._lineout_axis = index
        self._lineout_plot.setLabel("bottom", "x" if index == 0 else "y",
                                    units="µm")
        self._render_lineout()

    def _render_lineout(self):
        """Draw only the active axis's cut from the last cursor sample."""
        if not hasattr(self, "_lineout_h"):
            return
        p = self._last_cursor
        if p is None or "hx" not in p:
            # No point selected, or the point has no underlying data (clicked
            # outside every scan region) — nothing to plot.
            self._lineout_h.setData([], [])
            self._lineout_v.setData([], [])
        elif self._lineout_axis == 0:
            self._lineout_h.setData(p["hx"], p["hy"])
            self._lineout_v.setData([], [])
        else:
            self._lineout_h.setData([], [])
            self._lineout_v.setData(p["vx"], p["vy"])

    def _on_cursor(self, payload):
        """A click selected a cursor point on the image: register it, update the
        active line-cut, and refresh the footer X/Y/I readout.

        ``self._cursor_state`` (full payload) and ``self._cursor_um`` (the (x, y)
        µm tuple) are the persistent record of the selected point — read by other
        actions (e.g. the Move-to-cursor / Focus-to-cursor / Set-cursor-to-0
        controls and the task agent) via ``cursor_position()``."""
        self._last_cursor = payload
        self._cursor_state = payload
        self._cursor_um = (payload["x"], payload["y"]) if payload else None
        self._render_lineout()
        rd = getattr(self, "_cursor_readout", {})
        if rd and payload is not None:
            rd["X"].setText(f"{payload['x']:.2f}")
            rd["Y"].setText(f"{payload['y']:.2f}")
            # Intensity only exists when the point lands inside a region's data.
            rd["I"].setText(f"{payload['value']:.4g}"
                            if "value" in payload else "—")
        # Focus-to-cursor calibration needs a Z click on a completed focus streak
        # (not mid-scan) — enabled only after the scan finishes/aborts.
        fbtn = getattr(self, "_cursor_action_btns", {}).get("Focus to cursor")
        if fbtn is not None:
            in_focus_streak = (getattr(self, "image_area", None) is not None
                               and self.image_area._focus_display
                               and self._focus_mode)
            fbtn.setEnabled(bool(in_focus_streak and payload is not None
                                 and self.controller is not None
                                 and not self._scanning))

    def cursor_position(self):
        """The currently selected cursor point as an ``(x, y)`` tuple in physical
        µm (sample coordinates), or ``None`` if no point has been clicked yet."""
        return getattr(self, "_cursor_um", None)

    def _on_focus_to_cursor(self):
        """Calibrate focus from the ZonePlateZ position the user clicked on a
        focus streak.  Mirrors mainwindow_mvc.on_focus_to_cursor / the legacy
        setFocusZ():

        - OSA Focus, or A0 not yet calibrated → shift the **ZonePlateZ offset** so
          the clicked Z maps to the zone-plate calibration position.
        - Regular Focus with a calibrated A0 → shift **A0** (and the SampleZ
          offset) instead.

        Either way, ZonePlateZ is then moved to the calibration position.  A
        guard-rail dialog appears when the correction exceeds 100 µm."""
        c = self.controller
        fbtn = getattr(self, "_cursor_action_btns", {}).get("Focus to cursor")
        if fbtn is not None:
            fbtn.setEnabled(False)
        if c is None:
            return
        # On a focus streak the clicked y IS ZonePlateZ (see set_focus_display).
        cursor = self.cursor_position()
        if cursor is None or not (getattr(self, "image_area", None)
                                  and self.image_area._focus_display):
            c.error_occurred.emit("Click a point on the focus image first.")
            return
        cursor_focus_z = float(cursor[1])

        try:
            im = c.get_image_model()
            zp_cal = float(im.get('zonePlateCalibration', 0.0) or 0.0)
            zp_off = float(im.get('zonePlateOffset', 0.0) or 0.0)
            mm = c.get_motor_model()
            motor_info = mm.get('motor_info', {}) or {}
            a0 = float(motor_info.get('Energy', {}).get('A0', 0.0) or 0.0)
            positions = mm.get('current_positions', {}) or {}
            scan_type = im.get('scan_type', '') or self.scan_type.currentText()
            a0_calibrated = False
            try:
                a0_calibrated = bool(c.client.main_config.get('geometry', {})
                                     .get('A0_calibrated', False))
            except Exception:
                a0_calibrated = False

            if "OSA" in scan_type or not a0_calibrated:
                # Adjust the ZonePlateZ offset to bring the click to calibration.
                offset_delta = zp_cal - cursor_focus_z
                new_offset = zp_off + offset_delta
                if abs(offset_delta) > 100 and not self._confirm_large_focus(
                        f"This would change the ZonePlateZ offset by "
                        f"{offset_delta:.1f} µm (from {zp_off:.1f} to "
                        f"{new_offset:.1f} µm), larger than 100 µm.\n\n"
                        f"Apply anyway?"):
                    return
                c.handle_motor_config_change("ZonePlateZ", "offset", new_offset)
                c.status_updated.emit(
                    f"ZonePlateZ offset → {new_offset:.2f} µm (focus at "
                    f"{cursor_focus_z:.2f})")
            else:
                # Calibrated A0 path: adjust A0 and the SampleZ offset.
                focus_delta = zp_cal - cursor_focus_z
                if abs(focus_delta) > 100 and not self._confirm_large_focus(
                        f"The requested focus correction is {focus_delta:.1f} µm, "
                        f"larger than 100 µm.\n\nApply anyway?"):
                    return
                new_a0 = a0 - focus_delta
                sample_z = float(positions.get('SampleZ', 0.0) or 0.0)
                sample_z_off = float(motor_info.get('SampleZ', {})
                                     .get('offset', 0.0) or 0.0)
                new_sample_z_off = sample_z_off + (new_a0 - sample_z)
                c.handle_motor_config_change("SampleZ", "offset", new_sample_z_off)
                c.handle_motor_config_change("Energy", "A0", new_a0)
                if getattr(self, "_a0_field", None):
                    self._a0_field.setText(f"{new_a0:.4f}")
                c.status_updated.emit(
                    f"A0 → {new_a0:.3f}, SampleZ offset → {new_sample_z_off:.3f}")

            # Move ZonePlateZ to the calibration position.
            c.move_motor("ZonePlateZ", zp_cal)
            self.image_area.clear_crosshair()
            # Calibration done — drop the focus streak and return to the image.
            target = self._last_image_scan_type
            if (target and self.scan_type.findText(target) >= 0
                    and not self._scan_is_focus(target)):
                self.scan_type.setCurrentText(target)   # → _on_scan_type restores
            else:
                self._restore_pre_focus_display()
                self._refresh_spatial_image(fit=True)
                self._refresh_image_meta()
        except Exception as e:
            c.error_occurred.emit(f"Focus-to-cursor failed: {e}")

    def _confirm_large_focus(self, message):
        """Guard-rail dialog for a >100 µm focus correction; True = proceed."""
        reply = QMessageBox.question(
            self, "Large focus correction", message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return reply == QMessageBox.StandardButton.Yes

    # ── column 3: live detector + motors ────────────────────────────────
    def _build_col3(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(self._build_detector())
        v.addWidget(self._build_motors(), 1)
        return col

    def _build_detector(self):
        card, body = self._card("Live detector")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # Live status + pulse dot live in the header, right-aligned.
        self.live_dot = QLabel("●")
        self.live_dot.setStyleSheet(f"color:{C['alert']};background:transparent;font-size:10px;")
        card._header_layout.addWidget(self.live_dot)
        self.det_status = self._label("", role="mono")
        self.det_status.setFont(mono_font(10))
        card._header_layout.addWidget(self.det_status)

        # One tab + one page per configured detector.  Point/spectrum detectors
        # get a trace/spectrum plot; image detectors get a 2-D viewer with an
        # interactive contrast (histogram) control.  Keyed by DAQ config key.
        self._det_keys = [k for k, _ in self._daqs_sorted()]
        self._det_pages = {}
        names = [cfg.get("name", k) for k, cfg in self._daqs_sorted()]
        default_idx = self._det_keys.index("default") if "default" in self._det_keys else 0

        wrap = QWidget()
        wrap.setFixedHeight(400)          # taller than before; motors compress
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(14, 14, 14, 14)
        wl.setSpacing(10)

        det_well, self.det_btns = self._segmented(names or ["—"], default_idx)
        wl.addWidget(det_well)

        self.det_stack = QStackedWidget()
        for key, cfg in self._daqs_sorted():
            if cfg.get("type") == "image":
                pagew = self._image_detector_page(key, cfg)
            else:
                pagew = self._trace_detector_page(key, cfg)
            self.det_stack.addWidget(pagew)
        wl.addWidget(self.det_stack, 1)
        body.addWidget(wrap)

        det_well._group.idClicked.connect(self._switch_detector)
        if self._det_keys:
            self.det_stack.setCurrentIndex(default_idx)
            self._update_det_status(default_idx)
        return card

    def _switch_detector(self, i):
        self.det_stack.setCurrentIndex(i)
        self._update_det_status(i)

    def _update_det_status(self, i):
        """Header status line for the selected detector: name · type."""
        if not (0 <= i < len(self._det_keys)):
            return
        cfg = self._daq_info.get(self._det_keys[i], {})
        self.det_status.setText(
            f"{cfg.get('name', self._det_keys[i])} · {cfg.get('type', 'point')}")

    def _active_det_key(self):
        """DAQ config key of the currently displayed detector tab, or None."""
        i = self.det_stack.currentIndex() if hasattr(self, "det_stack") else -1
        return self._det_keys[i] if 0 <= i < len(self._det_keys) else None

    def _chip(self, label, value, ok=False):
        chip = QFrame()
        chip.setStyleSheet(f"background:{C['well']};border:1px solid {C['border']};"
                           "border-radius:5px;")
        cv = QVBoxLayout(chip)
        cv.setContentsMargins(9, 7, 9, 7)
        cv.setSpacing(2)
        cv.addWidget(self._label(label.upper(), role="microLabel"))
        v = self._label(value, role="ok" if ok else "value")
        v.setFont(mono_font(12))
        cv.addWidget(v)
        return chip

    def _image_detector_page(self, key, cfg):
        """A 2-D viewer for an image-type detector: pyqtgraph image on the left,
        an interactive contrast control (HistogramLUTWidget) on the right.  No
        statistics chips — a compact dims/sum caption sits below the image."""
        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(6)
        glw = pg.GraphicsLayoutWidget()
        glw.setBackground("#000000")
        vb = glw.addViewBox()
        vb.setAspectLocked(True)
        vb.invertY(True)
        # Seeded with a placeholder frame; replaced by live area-detector frames
        # (see _refresh_ccd) once a scan with an image-type DAQ is running.
        img = pg.ImageItem(_diffraction())
        img.setLookupTable(make_lut("inferno"))
        vb.addItem(img)
        vb.autoRange(padding=0)
        left.addWidget(glw, 1)
        cap = QHBoxLayout()
        dims_lbl = self._label("256² · log", role="monoFaint")
        sum_lbl = self._label("Σ 1.9e6", role="monoFaint")
        cap.addWidget(dims_lbl)
        cap.addStretch(1)
        cap.addWidget(sum_lbl)
        left.addLayout(cap)
        h.addLayout(left, 1)

        # Contrast control: the same draggable levels + gradient editor the main
        # image uses, bound directly to this detector's ImageItem.
        hist = pg.HistogramLUTWidget()
        hist.setBackground(C["panel_footer"])
        hist.setImageItem(img)
        hist.gradient.loadPreset("inferno")
        hist.setFixedWidth(120)
        try:
            hist.axis.setPen(C["border"])
            hist.axis.setTextPen(C["text_faint"])
        except Exception:
            pass
        h.addWidget(hist)

        self._det_pages[key] = {
            "type": "image", "name": cfg.get("name", key),
            "img": img, "vb": vb, "hist": hist,
            "dims_lbl": dims_lbl, "sum_lbl": sum_lbl, "seeded": False}
        # First image detector keeps the legacy ``ccd_img`` alias so any older
        # references still resolve.
        if not hasattr(self, "ccd_img"):
            self.ccd_img = img
        return page

    def _trace_detector_page(self, key, cfg):
        """A trace/spectrum plot for a point- or spectrum-type detector.  Point
        detectors show a scrolling monitor trace; spectrum detectors show the
        latest full spectrum.  Live data arrives per-key via _on_monitor_data."""
        dtype = cfg.get("type", "point")
        name = cfg.get("name", key)
        driver = cfg.get("driver", "")
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(9)
        top = QHBoxLayout()
        title = f"{name} monitor" + (f" · {driver}" if driver else "")
        top.addWidget(self._label(title, role="fieldLabel"))
        top.addStretch(1)
        value_lbl = self._label("—", role="ok")
        value_lbl.setFont(mono_font(11))
        top.addWidget(value_lbl)
        v.addLayout(top)

        # Exponent shown once above the plot (SciAxis reports it) so the y tick
        # labels stay a compact one-decimal mantissa instead of full magnitudes.
        exp_row = QHBoxLayout()
        exp_row.setContentsMargins(0, 0, 0, 0)
        exp_lbl = self._label("", role="monoFaint")
        exp_row.addWidget(exp_lbl)
        exp_row.addStretch(1)
        v.addLayout(exp_row)

        left_axis = SciAxis(orientation="left")
        left_axis.on_exp_changed = lambda e, lbl=exp_lbl: lbl.setText(_exp_str(e))
        plot = pg.PlotWidget(axisItems={"left": left_axis})
        plot.setBackground(C["plot_ground"])
        plot.showGrid(x=False, y=True, alpha=0.2)
        plot.enableAutoRange("y", True)
        pi = plot.getPlotItem()
        # Full bounding box: draw all four axes; only left/bottom carry tick values.
        pi.showAxis("top"); pi.showAxis("right")
        pi.getAxis("top").setStyle(showValues=False)
        pi.getAxis("right").setStyle(showValues=False)
        for ax in ("left", "bottom", "top", "right"):
            pi.getAxis(ax).setPen(C["border"])
            pi.getAxis(ax).setTextPen(C["text_faint"])

        if dtype == "spectrum":
            e, od = _spectrum()
            curve = plot.plot(e, od, pen=pg.mkPen(C["ok"], width=1.4))
            plot.setLabel("bottom", cfg.get("x label", "Energy (eV)"))
            trace = None
        else:
            trace = 1 + (np.random.default_rng(4).random(220) - .5) * .004
            curve = plot.plot(trace, pen=pg.mkPen(C["ok"], width=1.4))
        v.addWidget(plot, 1)

        self._det_pages[key] = {
            "type": dtype, "name": name, "plot": plot, "curve": curve,
            "value": value_lbl, "exp_lbl": exp_lbl, "trace": trace}
        # First point detector keeps the legacy trace/counts aliases.
        if dtype == "point" and not hasattr(self, "trace_curve"):
            self.trace_curve = curve
            self.counts_lbl = value_lbl
            self._trace = trace
        return page

    def _build_motors(self):
        card, body = self._card("Motors")
        # Tabs are data-driven: one per distinct motor `group` in motor.json.
        self._motor_group_names = self._motor_groups()
        labels = [g.title() for g in self._motor_group_names] or ["Motors"]
        if self._motor_group_index >= len(self._motor_group_names):
            self._motor_group_index = 0
        grp_well, _ = self._segmented(labels, self._motor_group_index)
        card._header_layout.addWidget(grp_well)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.motor_inner = QWidget()
        self.motor_layout = QVBoxLayout(self.motor_inner)
        self.motor_layout.setContentsMargins(0, 0, 0, 0)
        self.motor_layout.setSpacing(0)

        self.motor_layout.addStretch(1)
        self._repopulate_motors()
        scroll.setWidget(self.motor_inner)
        body.addWidget(scroll, 1)

        def show_group(i):
            self._motor_group_index = i
            self._repopulate_motors()
        grp_well._group.idClicked.connect(show_group)

        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(14, 11, 14, 11)
        fv.setSpacing(8)
        btns = QHBoxLayout()
        btns.setSpacing(7)
        self.jogmove_btn = QPushButton()
        self.jogmove_btn.setCursor(Qt.PointingHandCursor)
        self.jogmove_btn.clicked.connect(self._toggle_move_mode)
        self._update_jogmove_btn()
        jm = self.jogmove_btn
        mp = QPushButton("Motor panel")
        mp.setCursor(Qt.PointingHandCursor)
        mp.setToolTip("Open the motor inspection & history panel.")
        mp.clicked.connect(self._open_motor_panel)
        bp = QPushButton("Beamline panel")
        bp.setCursor(Qt.PointingHandCursor)
        bp.setToolTip("View / edit the beamline parameter database.")
        bp.clicked.connect(self._open_beamline_panel)
        stop = QPushButton("Stop all"); stop.setObjectName("stopAll")
        # Inactive until a server-side motor-stop command exists (none in the
        # current protocol).  Kept visible for layout; wired later.
        stop.setEnabled(False)
        stop.setToolTip("Motor stop not yet implemented (pending a server-side "
                        "stop command).")
        self.stop_all_btn = stop
        btns.addWidget(jm, 1); btns.addWidget(mp, 1); btns.addWidget(bp, 1)
        btns.addWidget(stop)
        fv.addLayout(btns)
        self.cmd_log = QFrame()
        self.cmd_log.setStyleSheet(f"border-top:1px solid {C['border']};")
        lv = QVBoxLayout(self.cmd_log)
        lv.setContentsMargins(0, 8, 0, 0)
        lv.setSpacing(3)
        lv.addWidget(self._label("14:22:07  move Energy → 709.0 eV  [ok]",
                                 font=mono_font(9), color=C["text_dim"]))
        lv.addWidget(self._label("14:22:09  scan line 82/120  frames 9840",
                                 font=mono_font(9), color=C["text_faint"]))
        fv.addWidget(self.cmd_log)
        body.addWidget(footer)
        return card

    def _populate_motors(self, motors):
        # clear existing rows (keep trailing stretch) and drop stale widget refs
        while self.motor_layout.count() > 1:
            item = self.motor_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._motor_widgets = {}
        for name, kind, pos, unit, frac, moving in motors:
            row = QFrame()
            row.setObjectName("rowSep")
            # Fixed vertical size so rows keep a tight, uniform height and never
            # stretch to fill the scroll viewport.
            row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            g = QGridLayout(row)
            g.setContentsMargins(14, 5, 14, 5)
            g.setHorizontalSpacing(8)
            g.setVerticalSpacing(2)
            # name + kind
            nb = QVBoxLayout()
            nb.setSpacing(1)
            nb.addWidget(self._label(name, role="mono"))
            nb.addWidget(self._label(kind, role="microLabel"))
            nw = QWidget(); nw.setFixedWidth(118); nw.setLayout(nb)
            g.addWidget(nw, 0, 0)
            # value + travel bar
            vb = QVBoxLayout()
            vb.setSpacing(3)
            vrow = QHBoxLayout()
            vrow.setSpacing(6)
            val = self._label(pos, role="motion" if moving else "value")
            val.setFont(mono_font(13, QFont.Medium))
            vrow.addWidget(val)
            if unit:
                vrow.addWidget(self._label(unit, role="monoFaint"))
            vrow.addStretch(1)
            vb.addLayout(vrow)
            bar = TravelBar(frac, moving)
            vb.addWidget(bar)
            vw = QWidget(); vw.setLayout(vb)
            g.addWidget(vw, 0, 1)
            info = self._motor_info.get(name, {})
            enum_values = info.get("values")
            is_enum = isinstance(enum_values, (list, tuple)) and len(enum_values) > 0
            is_int = str(info.get("varType", "")).strip().lower() == "int"
            # Per-row action cell, driven by _move_mode (toggled by "Jog / Move"):
            #  - Move mode: field holds an ABSOLUTE destination (pre-filled with the
            #    current position); a "Move" button (or Enter) commits move_motor().
            #  - Jog mode: field holds a RELATIVE step (pre-filled with a small default);
            #    − / + jog by that amount via jog_motor().
            # An enumerated motor (motor.json "values", e.g. EPU Harmonic ∈ {1,3,5})
            # is a dropdown of its allowed values + Move, in both modes — jogging a
            # discrete axis is meaningless.
            if is_enum:
                tgt = QComboBox()
                tgt.setFixedWidth(84)
                tgt.setCursor(Qt.PointingHandCursor)
                tgt.addItems([self._fmt_enum(v) for v in enum_values])
                cur = self._fmt_enum(info.get("last value"))
                if tgt.findText(cur) >= 0:
                    tgt.setCurrentText(cur)
                g.addWidget(tgt, 0, 2)
                action_widgets = [tgt]
                move = QPushButton("Move"); move.setProperty("role", "jog")
                move.setCursor(Qt.PointingHandCursor)
                move.clicked.connect(lambda _=False, n=name: self._move_motor_to_target(n))
                g.addWidget(move, 0, 3, 1, 2)
                action_widgets.append(move)
            else:
                fill = pos if self._move_mode else f"{self._jog_step(name):g}"
                if is_int:                    # integer motor: no fractional entry
                    try:
                        fill = str(int(round(float(fill))))
                    except (TypeError, ValueError):
                        pass
                tgt = self._field(fill, align_right=True)
                tgt.setFixedWidth(84)
                tgt.setStyleSheet("font-size:11px;padding:5px 7px;")
                if is_int:
                    validator = QIntValidator()
                    lo, hi = info.get("minValue"), info.get("maxValue")
                    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                        validator.setRange(int(lo), int(hi))
                    tgt.setValidator(validator)
                g.addWidget(tgt, 0, 2)
                action_widgets = [tgt]
                if self._move_mode:
                    tgt.returnPressed.connect(lambda n=name: self._move_motor_to_target(n))
                    move = QPushButton("Move"); move.setProperty("role", "jog")
                    move.setCursor(Qt.PointingHandCursor)
                    move.clicked.connect(lambda _=False, n=name: self._move_motor_to_target(n))
                    g.addWidget(move, 0, 3, 1, 2)     # span both jog-button columns
                    action_widgets.append(move)
                else:
                    tgt.returnPressed.connect(lambda n=name: self._jog_motor(n, +1))
                    minus = QPushButton("−"); minus.setProperty("role", "jog"); minus.setFixedWidth(26)
                    plus = QPushButton("+"); plus.setProperty("role", "jog"); plus.setFixedWidth(26)
                    for b in (minus, plus):
                        b.setCursor(Qt.PointingHandCursor)
                    minus.clicked.connect(lambda _=False, n=name: self._jog_motor(n, -1))
                    plus.clicked.connect(lambda _=False, n=name: self._jog_motor(n, +1))
                    g.addWidget(minus, 0, 3)
                    g.addWidget(plus, 0, 4)
                    action_widgets += [minus, plus]
            g.setColumnStretch(1, 1)
            self._motor_widgets[name] = {
                "value": val, "bar": bar, "unit": unit, "target": tgt,
                "lo": info.get("minValue"), "hi": info.get("maxValue"),
            }
            # In placeholder mode (no server) the move/jog controls are inert.
            if self.controller is None:
                for w in action_widgets:
                    w.setEnabled(False)
            self.motor_layout.insertWidget(self.motor_layout.count() - 1, row)

    def _repopulate_motors(self):
        """Rebuild the currently-shown motor group from live positions (used on
        group switch and Move/Jog mode toggle)."""
        names = getattr(self, "_motor_group_names", []) or self._motor_groups()
        if not names:
            self._populate_motors([])
            return
        i = min(self._motor_group_index, len(names) - 1)
        self._populate_motors(self._motor_rows(names[i]))

    def _open_motor_panel(self):
        """Open (or raise) the dashboard-styled Motor Panel window — a floating
        utility for inspecting/jogging any motor with Live/History plots."""
        panel = getattr(self, "_motor_panel", None)
        if panel is None or not panel.isVisible():
            from pystxmcontrol.gui.motor_panel_dashboard import MotorPanelWindow
            self._motor_panel = MotorPanelWindow(
                controller=self.controller, motor_info=self._motor_info,
                parent=self)
            self._motor_panel.show()
        else:
            self._motor_panel.raise_()
            self._motor_panel.activateWindow()

    def _open_beamline_panel(self):
        """Open (or raise) the dashboard-styled Beamline Panel window — a floating
        view/edit utility for the beamline parameter database.  Editing is enabled
        only in Staff mode (``self._expert``)."""
        panel = getattr(self, "_beamline_panel", None)
        if panel is None or not panel.isVisible():
            client = getattr(self.controller, "client", None)
            if client is None:
                self.statusBar().showMessage(
                    "Beamline database unavailable (no server connection).", 5000)
                return
            from pystxmcontrol.gui.beamline_panel_dashboard import BeamlinePanelWindow
            from pystxmcontrol.controller.beamline_database import BeamlineDatabaseClient
            self._beamline_panel = BeamlinePanelWindow(
                db=BeamlineDatabaseClient(client),
                is_staff=self._expert,
                parent=self)
            self._beamline_panel.show()
        else:
            self._beamline_panel.raise_()
            self._beamline_panel.activateWindow()

    # ════════════════════════════════════════════════════════════════════
    #  Shared helpers for the Browser / Analysis / Agent views
    # ════════════════════════════════════════════════════════════════════
    def _filter_pills(self, items, checked=0):
        """A wrapping row of exclusive filter pills (README: same styling as the
        colormap segmented control).  Returns (button group, [buttons])."""
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        btns = []
        for i, name in enumerate(items):
            b = QPushButton(name)
            b.setProperty("role", "pill")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if i == checked:
                b.setChecked(True)
            grp.addButton(b, i)
            btns.append(b)
        return grp, btns

    def _cmap_pills(self, on_change, checked=0):
        """Colormap segmented control (gray/viridis/inferno) wired to on_change."""
        well, btns = self._segmented(["gray", "viridis", "inferno"], checked)
        names = ("gray", "viridis", "inferno")
        for i, b in enumerate(btns):
            b.clicked.connect(lambda _=False, n=names[i]: on_change(n))
        return well

    def _viewer_rail(self, cmap, top="6 214", bottom="0"):
        """Right rail: top/bottom value labels + histogram/colorbar (HistColorBar)."""
        rail = QFrame()
        rail.setObjectName("viewerRail")
        rail.setFixedWidth(96)
        rail.setStyleSheet(f"QFrame#viewerRail {{background:{C['panel_footer']};"
                           f"border:none;border-left:1px solid {C['border']};}}")
        rv = QVBoxLayout(rail)
        rv.setContentsMargins(10, 12, 10, 12)
        rv.setSpacing(6)
        t = self._label(top, role="monoFaint"); t.setAlignment(Qt.AlignRight)
        rv.addWidget(t)
        hb = HistColorBar(cmap)
        rv.addWidget(hb, 1)
        b = self._label(bottom, role="monoFaint"); b.setAlignment(Qt.AlignRight)
        rv.addWidget(b)
        return rail, hb

    def _go_view(self, index):
        """Programmatically switch the top-level view and sync its nav tab."""
        b = self.nav_grp.button(index)
        if b is not None:
            b.setChecked(True)
        self._switch_view(index)

    def _viewer_toolbar(self, filename, subline, cmap_cb, buttons):
        """Shared viewer toolbar: filename + subline, colormap pills, buttons.
        Returns (toolbar frame, filename label, subline label)."""
        tb = QFrame()
        tb.setObjectName("cardHeader")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(16)
        fn = self._label(filename, role="value")
        fn.setFont(mono_font(16, QFont.DemiBold))
        tl.addWidget(fn)
        sub = self._label(subline, font=sans_font(10), color=C["text_dim"])
        tl.addWidget(sub)
        tl.addStretch(1)
        tl.addWidget(self._cmap_pills(cmap_cb))
        for name in buttons:
            b = QPushButton(name); b.setProperty("role", "small")
            tl.addWidget(b)
        return tb, fn, sub

    # ════════════════════════════════════════════════════════════════════
    #  Browser view
    # ════════════════════════════════════════════════════════════════════
    # Sample session files (shape reference for the real HDF5 listing).
    _BROWSER_FILES = [
        ("NS_260809051.stxm", "Focus"), ("NS_260809052.stxm", "Focus"),
        ("NS_260809053.stxm", "Spiral Image"), ("NS_260809054.stxm", "Spiral Image"),
        ("NS_260809055.stxm", "Spiral Image"), ("NS_260809056.stxm", "Spiral Image"),
        ("NS_260809057.stxm", "Spiral Stack"), ("NS_260809058.stxm", "Spiral Stack"),
        ("NS_260809059.stxm", "Spiral Image"), ("NS_260809060.stxm", "Ptychography"),
        ("NS_260809061.stxm", "Focus"), ("NS_260809062.stxm", "Spiral Image"),
        ("NS_260809063.stxm", "Line Spectrum"), ("NS_260809064.stxm", "Spiral Image"),
        ("NS_260809065.stxm", "Spiral Stack"), ("NS_260809066.stxm", "Ptychography"),
        ("NS_260809067.stxm", "Spiral Image"), ("NS_260809068.stxm", "Tomography"),
        ("NS_260809069.stxm", "Spiral Image"), ("NS_260809070.stxm", "Spiral Image"),
    ]
    _BROWSER_FILTERS = ["All", "Focus", "Spiral Image", "Spiral Stack",
                        "Line Spectrum", "Ptychography"]

    @staticmethod
    def _file_seed(name):
        try:
            return int(name.split(".")[0][-3:])
        except ValueError:
            return 1

    def _build_browser_view(self):
        self._browser_cmap = "gray"
        self._browser_filter = "All"
        self._browser_sel = 5
        self._browser_tiles = []

        body = QWidget()
        body.setStyleSheet(f"background:{C['canvas']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(10)
        col1 = self._browser_files_col(); col1.setFixedWidth(660)
        col2 = self._browser_viewer_col()
        col3 = self._browser_details_col(); col3.setFixedWidth(460)
        bl.addWidget(col1)
        bl.addWidget(col2, 1)
        bl.addWidget(col3)

        self._browser_render_grid()
        self._browser_select(self._browser_sel)
        return body

    def _browser_files_col(self):
        card, cbody = self._card("Session files")
        path = self._label("/data/2026/08/09", role="monoFaint")
        card._header_layout.insertWidget(1, path)
        card._header_layout.insertSpacing(2, 10)
        refresh = QPushButton("Refresh"); refresh.setProperty("role", "small")
        card._header_layout.addWidget(refresh)

        # filter row
        frow = QFrame()
        frow.setObjectName("filterRow")
        frow.setStyleSheet(f"QFrame#filterRow {{background:{C['panel_footer']};"
                           f"border:none;border-bottom:1px solid {C['border']};}}")
        fl = QHBoxLayout(frow)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(6)
        self._browser_filter_grp, fbtns = self._filter_pills(self._BROWSER_FILTERS)
        for i, b in enumerate(fbtns):
            fl.addWidget(b)
            b.clicked.connect(
                lambda _=False, k=self._BROWSER_FILTERS[i]: self._browser_set_filter(k))
        fl.addStretch(1)
        self._browser_count = self._label("20 of 20 shown", role="monoFaint")
        fl.addWidget(self._browser_count)
        cbody.addWidget(frow)

        # thumbnail grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self._browser_grid = QGridLayout(inner)
        self._browser_grid.setContentsMargins(12, 12, 12, 12)
        self._browser_grid.setHorizontalSpacing(10)
        self._browser_grid.setVerticalSpacing(10)
        for c in range(4):
            self._browser_grid.setColumnStretch(c, 1)
        scroll.setWidget(inner)
        cbody.addWidget(scroll, 1)
        return card

    def _browser_tile(self, idx):
        name, kind = self._BROWSER_FILES[idx]
        field = _thumb_field(self._file_seed(name), kind, 64)
        tile = QFrame()
        tile.setObjectName("browserTile")
        tile.setCursor(Qt.PointingHandCursor)
        tv = QVBoxLayout(tile)
        tv.setContentsMargins(6, 6, 6, 6)
        tv.setSpacing(5)
        canvas = QLabel()
        canvas.setFixedHeight(140)
        canvas.setScaledContents(True)
        canvas.setStyleSheet("background:#000;border:none;")
        canvas.setPixmap(_field_pixmap(field, self._browser_cmap, 140))
        tv.addWidget(canvas)
        cap = QVBoxLayout(); cap.setSpacing(1)
        fn = self._label(name, role="mono"); fn.setFont(mono_font(11))
        cap.addWidget(fn)
        cap.addWidget(self._label(kind.upper(), role="microLabel"))
        tv.addLayout(cap)
        tile.mousePressEvent = lambda e, i=idx: self._browser_select(i)
        self._browser_tiles.append(
            {"frame": tile, "canvas": canvas, "field": field, "idx": idx, "name": fn})
        return tile

    def _browser_render_grid(self):
        # clear
        while self._browser_grid.count():
            item = self._browser_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._browser_tiles = []
        shown = [i for i, (_, kind) in enumerate(self._BROWSER_FILES)
                 if self._browser_filter == "All" or kind == self._browser_filter]
        for pos, idx in enumerate(shown):
            r, c = divmod(pos, 4)
            self._browser_grid.addWidget(self._browser_tile(idx), r, c)
        self._browser_count.setText(
            f"{len(shown)} of {len(self._BROWSER_FILES)} shown")
        # keep selection if still visible, else pick the first shown
        if self._browser_sel not in shown and shown:
            self._browser_sel = shown[0]
        self._browser_apply_selection_style()

    def _browser_set_filter(self, kind):
        self._browser_filter = kind
        self._browser_render_grid()
        self._browser_select(self._browser_sel)

    def _browser_apply_selection_style(self):
        for t in self._browser_tiles:
            sel = t["idx"] == self._browser_sel
            t["frame"].setStyleSheet(
                f"QFrame#browserTile {{background:"
                f"{'#131a20' if sel else C['panel_footer']};"
                f"border:1px solid {C['accent'] if sel else C['border']};"
                "border-radius:6px;}")
            t["name"].setStyleSheet(
                f"color:{C['text'] if sel else C['text_2']};background:transparent;")

    def _browser_select(self, idx):
        self._browser_sel = idx
        self._browser_apply_selection_style()
        name, kind = self._BROWSER_FILES[idx]
        field = _thumb_field(self._file_seed(name), kind, 150)
        self._browser_big.set_field(field, autolevels=True)
        self._browser_fn.setText(name)
        self._browser_sub.setText(f"{kind} · 2026-08-09 10:02")
        # rebuild parameters
        while self._browser_params.count():
            item = self._browser_params.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for k, val in self._browser_detail(name, kind):
            self._browser_params.addWidget(self._param_row(k, val))

    @staticmethod
    def _browser_detail(name, kind):
        is_stack = kind == "Spiral Stack"
        return [
            ("File", name), ("Scan type", kind),
            ("Start", "2026-08-09T10:02:03"), ("End", "2026-08-09T10:02:11"),
            ("Experimenters", "Jeongho Cho, Gibeom Kim, Eunsoo Nam"),
            ("Proposal", "ALS-12941-009"),
            ("Sample", "particle collection, Fe screening"),
            ("X range", "-138.821 – -119.021 µm  (100 pts, 0.2000 µm/pt)"),
            ("Y range", "36.365 – 56.165 µm  (100 pts, 0.2000 µm/pt)"),
            ("Energies", "12  (695.50 – 705.50 eV)" if is_stack
             else "1 energy  700.75 eV"),
            ("Dwell", "0.500 ms"), ("X motor", "SampleX"), ("Y motor", "SampleY"),
            ("Size", "48.2 MB" if is_stack else "4.1 MB"),
        ]

    def _param_row(self, key, value):
        row = QFrame()
        row.setObjectName("rowSep")
        g = QHBoxLayout(row)
        g.setContentsMargins(0, 7, 0, 7)
        g.setSpacing(10)
        k = self._label(key, font=sans_font(10.5), color=C["text_dim"])
        k.setFixedWidth(96)
        g.addWidget(k)
        v = self._label(value, role="mono")
        v.setWordWrap(True)
        g.addWidget(v, 1)
        return row

    def _browser_viewer_col(self):
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        tb, self._browser_fn, self._browser_sub = self._viewer_toolbar(
            "NS_260809056.stxm", "Spiral Image · 2026-08-09 10:02",
            self._browser_set_cmap, ("Levels", "Unzoom", "Save PNG"))
        cl.addWidget(tb)

        bodyw = QWidget()
        bh = QHBoxLayout(bodyw)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)
        self._browser_big = OverlayImageView(
            _thumb_field(56, "Spiral Image", 150), cmap="gray",
            meta_text="Spiral Image · channel default\n"
                      "pixel 0.200 µm · dwell 0.5 ms\n"
                      "700.75 eV · circ. polarization")
        bh.addWidget(self._browser_big, 1)
        rail, self._browser_rail = self._viewer_rail("gray")
        bh.addWidget(rail)
        cl.addWidget(bodyw, 1)

        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QHBoxLayout(footer)
        fv.setContentsMargins(14, 10, 14, 10)
        fv.setSpacing(10)
        for name in ("◀", "▶"):
            b = QPushButton(name); b.setProperty("role", "jog"); b.setFixedWidth(30)
            fv.addWidget(b)
        fv.addWidget(self._label("energy 1 of 1", role="monoFaint"))
        fv.addStretch(1)
        for lbl, val in (("X", "-128.4"), ("Y", "46.1"), ("I", "8421")):
            fv.addWidget(self._label(lbl, font=mono_font(11), color=C["text_dim"]))
            fv.addWidget(self._label(val, font=mono_font(11), color=C["text"]))
        cl.addWidget(footer)
        return card

    def _browser_set_cmap(self, name):
        self._browser_cmap = name
        self._browser_big.set_cmap(name)
        self._browser_rail.set_lut(name)
        for t in self._browser_tiles:
            t["canvas"].setPixmap(_field_pixmap(t["field"], name, 140))

    def _browser_details_col(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # parameters
        pcard, pbody = self._card("Parameters")
        pscroll = QScrollArea()
        pscroll.setWidgetResizable(True)
        pscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pinner = QWidget()
        self._browser_params = QVBoxLayout(pinner)
        self._browser_params.setContentsMargins(14, 4, 14, 4)
        self._browser_params.setSpacing(0)
        self._browser_params.addStretch(1)
        pscroll.setWidget(pinner)
        pbody.addWidget(pscroll, 1)
        v.addWidget(pcard, 1)

        # actions
        acard, abody = self._card("Actions")
        acontent = QWidget()
        av = QVBoxLayout(acontent)
        av.setContentsMargins(14, 14, 14, 14)
        av.setSpacing(10)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        send_acq = QPushButton("Send to Acquisition")
        send_acq.setObjectName("beginScan")
        send_acq.setCursor(Qt.PointingHandCursor)
        send_acq.clicked.connect(lambda: self._go_view(0))
        send_ana = QPushButton("Send to Analysis")
        send_ana.setCursor(Qt.PointingHandCursor)
        send_ana.clicked.connect(lambda: self._go_view(2))
        btns.addWidget(send_acq, 1)
        btns.addWidget(send_ana, 1)
        av.addLayout(btns)
        note = self._label(
            "Send to Acquisition loads the scan's region, energy and dwell into "
            "the scan definition; Send to Analysis opens the stack.",
            font=sans_font(10.5), color=C["text_faint"])
        note.setWordWrap(True)
        av.addWidget(note)
        crow = QHBoxLayout()
        crow.setSpacing(8)
        comment = QLineEdit()
        comment.setPlaceholderText("Comment for logbook…")
        comment.setFont(sans_font(11))
        crow.addWidget(comment, 1)
        addb = QPushButton("Add"); addb.setProperty("role", "small")
        crow.addWidget(addb)
        av.addLayout(crow)
        abody.addWidget(acontent)
        v.addWidget(acard)
        return col

    # ════════════════════════════════════════════════════════════════════
    #  Analysis view
    # ════════════════════════════════════════════════════════════════════
    ENERGIES = [695.5, 696.5, 697.5, 698.75, 699.5, 700.5,
                701.0, 701.5, 702.5, 703.5, 704.5, 705.5]
    _ANALYSIS_TOOLS = ["Main", "Filtering", "Registration", "PCA", "NNMF",
                       "Line Spectrum"]

    def _build_analysis_view(self):
        self._analysis_cmap = "gray"
        self._a_energy = 3
        self._a_playing = False

        body = QWidget()
        body.setStyleSheet(f"background:{C['canvas']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(10)
        col1 = self._analysis_tools_col(); col1.setFixedWidth(700)
        col2 = self._analysis_viewer_col()
        col3 = self._analysis_side_col(); col3.setFixedWidth(460)
        bl.addWidget(col1)
        bl.addWidget(col2, 1)
        bl.addWidget(col3)

        self._set_a_energy(self._a_energy)
        return body

    def _od_curve(self, kind):
        e = np.array(self.ENERGIES)
        if kind == 0:
            return (0.5 + 0.07 * (e - 695.5) / 10
                    + 0.62 * np.exp(-((e - 700.9) / 1.05) ** 2)
                    + 0.30 * np.exp(-((e - 698.9) / 0.7) ** 2))
        return (0.22 + 0.04 * (e - 695.5) / 10
                + 0.30 * np.exp(-((e - 701.6) / 1.3) ** 2)
                + 0.10 * np.exp(-((e - 699.2) / 0.8) ** 2))

    def _analysis_field(self, n=150):
        """Weighted two-phase absorption map for the current energy plane."""
        if not hasattr(self, "_phase_blobs"):
            r = np.random.default_rng(65)
            self._phase_blobs = (
                [(.15 + r.random() * .7, .15 + r.random() * .7, .03 + r.random() * .05)
                 for _ in range(9)],
                [(.15 + r.random() * .7, .15 + r.random() * .7, .025 + r.random() * .04)
                 for _ in range(7)])
        i = self._a_energy - 1
        w1 = self._od_curve(0)[i] / 1.2
        w2 = self._od_curve(1)[i] / 1.2
        y, x = np.mgrid[0:n, 0:n] / n
        rad = np.hypot(x - .5, y - .5)
        a = np.full((n, n), 0.05)
        for bx, by, br in self._phase_blobs[0]:
            a += w1 * np.exp(-((x - bx) ** 2 + (y - by) ** 2) / (2 * br * br))
        for bx, by, br in self._phase_blobs[1]:
            a += w2 * np.exp(-((x - bx) ** 2 + (y - by) ** 2) / (2 * br * br))
        # deterministic per-size noise (seed varies with n so caching can't
        # cross-contaminate the 150 px viewer and the 48 px filmstrip frames)
        a += (np.random.default_rng(66 + n).random((n, n)) - .5) * .03
        a = np.where(rad > .47, 0.0, a)
        return np.clip(a, 0, 1)

    def _analysis_tools_col(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # OD vs energy spectrum
        scard, sbody = self._card("OD vs energy")
        legend = QHBoxLayout(); legend.setSpacing(12)
        for color, lbl in ((C["ok"], "ROI 1"), (C["motion"], "ROI 2")):
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{color};background:transparent;font-size:9px;")
            legend.addWidget(dot)
            legend.addWidget(self._label(lbl, role="monoFaint"))
        legw = QWidget(); legw.setLayout(legend)
        scard._header_layout.addWidget(legw)

        pw = pg.PlotWidget()
        pw.setFixedHeight(300)
        pw.setBackground(C["plot_ground"])
        pw.showGrid(x=True, y=True, alpha=0.15)
        for ax in ("bottom", "left"):
            pw.getAxis(ax).setPen(C["border"])
            pw.getAxis(ax).setTextPen(C["text_faint"])
        pw.setLabel("bottom", "Energy (eV)")
        e = np.array(self.ENERGIES)
        for kind, color in ((0, C["ok"]), (1, C["motion"])):
            od = self._od_curve(kind)
            pw.plot(e, od, pen=pg.mkPen(color, width=2),
                    symbol="o", symbolSize=5, symbolBrush=color, symbolPen=None)
        self._a_cursor = pg.InfiniteLine(
            pos=self.ENERGIES[self._a_energy - 1], angle=90, movable=True,
            pen=pg.mkPen(QColor(95, 212, 214, 140), width=2),
            hoverPen=pg.mkPen(C["accent"], width=2))
        self._a_cursor.sigPositionChanged.connect(self._a_cursor_moved)
        pw.addItem(self._a_cursor)
        sbody.addWidget(pw)
        v.addWidget(scard)

        # tool tabs
        tcard, tbody = self._card("Tools")
        tabbar = QHBoxLayout()
        tabbar.setContentsMargins(0, 0, 0, 0)
        tabbar.setSpacing(2)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for i, name in enumerate(self._ANALYSIS_TOOLS):
            b = QPushButton(name)
            b.setProperty("role", "subtab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if i == 0:
                b.setChecked(True)
            grp.addButton(b, i)
            tabbar.addWidget(b)
        tabbar.addStretch(1)
        tabwrap = QFrame()
        tabwrap.setStyleSheet(f"border-bottom:1px solid {C['border']};")
        tabwrap.setLayout(tabbar)
        tbody.addWidget(tabwrap)

        self._analysis_stack = QStackedWidget()
        for page in (self._atool_main(), self._atool_filtering(),
                     self._atool_registration(), self._atool_decomp("PCA"),
                     self._atool_decomp("NNMF"), self._atool_line()):
            self._analysis_stack.addWidget(page)
        grp.idClicked.connect(self._analysis_stack.setCurrentIndex)
        tbody.addWidget(self._analysis_stack, 1)

        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QHBoxLayout(footer)
        fv.setContentsMargins(14, 10, 14, 10)
        fv.setSpacing(8)
        for name in ("Save data", "Save PNG", "Record"):
            b = QPushButton(name); b.setProperty("role", "small")
            fv.addWidget(b)
        fv.addStretch(1)
        addlog = QPushButton("Add to logbook"); addlog.setProperty("role", "small")
        fv.addWidget(addlog)
        tbody.addWidget(footer)
        v.addWidget(tcard, 1)
        return col

    def _tool_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
        return page, v

    def _select_row(self, label, items):
        row = QVBoxLayout(); row.setSpacing(4)
        row.addWidget(self._label(label, role="microLabel"))
        cb = QComboBox(); cb.addItems(items); cb.setCursor(Qt.PointingHandCursor)
        row.addWidget(cb)
        w = QWidget(); w.setLayout(row)
        return w

    def _atool_main(self):
        page, v = self._tool_page()
        v.addWidget(self._select_row("I₀ source", ["ROI", "Region", "File"]))
        grid, _ = self._grid4([("Pre-edge start", "695.5", False),
                               ("Pre-edge stop", "698.0", False),
                               ("Post-edge start", "704.0", False),
                               ("Post-edge stop", "705.5", False)])
        v.addLayout(grid)
        v.addWidget(self._select_row("OD conversion", ["-log(I/I₀)", "linear"]))
        b = QPushButton("Compute OD"); b.setObjectName("beginScan")
        b.setCursor(Qt.PointingHandCursor)
        v.addWidget(b)
        v.addStretch(1)
        return page

    def _atool_filtering(self):
        page, v = self._tool_page()
        grid, _ = self._grid4([("Median k", "3", False), ("Gaussian σ", "1.0", False),
                               ("Despike σ", "4.0", False), ("Passes", "1", False)])
        v.addLayout(grid)
        row = QHBoxLayout(); row.setSpacing(8)
        ap = QPushButton("Apply to stack"); ap.setObjectName("beginScan")
        ap.setCursor(Qt.PointingHandCursor)
        pv = QPushButton("Preview")
        row.addWidget(ap, 1); row.addWidget(pv)
        v.addLayout(row)
        v.addStretch(1)
        return page

    def _atool_registration(self):
        page, v = self._tool_page()
        v.addWidget(self._select_row("Reference frame",
                                     ["first", "previous", "mean"]))
        v.addWidget(self._select_row(
            "Method", ["cross-correlation", "Fourier", "manual"]))
        grid, _ = self._grid4([("Subpixel", "10", False), ("Max shift", "20", False),
                               ("", "", True), ("", "", True)])
        v.addLayout(grid)
        row = QHBoxLayout(); row.setSpacing(8)
        al = QPushButton("Align stack"); al.setObjectName("beginScan")
        al.setCursor(Qt.PointingHandCursor)
        sh = QPushButton("Show shifts")
        row.addWidget(al, 1); row.addWidget(sh)
        v.addLayout(row)
        # shift plot
        pw = pg.PlotWidget()
        pw.setFixedHeight(90)
        pw.setBackground(C["plot_ground"])
        pw.getAxis("bottom").setPen(C["border"])
        pw.getAxis("left").setPen(C["border"])
        pw.getAxis("bottom").setTextPen(C["text_faint"])
        pw.getAxis("left").setTextPen(C["text_faint"])
        r = np.random.default_rng(11)
        for color in (C["accent"], C["motion"]):
            pw.plot((r.random(12) - .5) * 4, pen=pg.mkPen(color, width=2))
        v.addWidget(pw)
        v.addStretch(1)
        return page

    def _atool_decomp(self, label):
        page, v = self._tool_page()
        specs = [("Components", "4", False), ("Iterations", "200", False)]
        if label == "NNMF":
            specs.append(("Tolerance", "1e-4", False))
        specs.append(("", "", True))
        grid, _ = self._grid4(specs[:4])
        v.addLayout(grid)
        b = QPushButton(f"Run {label}"); b.setObjectName("beginScan")
        b.setCursor(Qt.PointingHandCursor)
        v.addWidget(b)
        # component thumbnails strip
        strip = QHBoxLayout(); strip.setSpacing(8)
        for i in range(4):
            box = QVBoxLayout(); box.setSpacing(3)
            canvas = QLabel(); canvas.setFixedSize(72, 72); canvas.setScaledContents(True)
            canvas.setStyleSheet("background:#000;")
            f = _thumb_field(31 + i * 7, "Spiral Image", 48)
            canvas.setPixmap(_field_pixmap(f, "viridis", 72))
            box.addWidget(canvas)
            box.addWidget(self._label(f"C{i}", role="microLabel"))
            w = QWidget(); w.setLayout(box)
            strip.addWidget(w)
        strip.addStretch(1)
        v.addLayout(strip)
        v.addStretch(1)
        return page

    def _atool_line(self):
        page, v = self._tool_page()
        grid, _ = self._grid4([("Samples", "100", False),
                               ("", "", True), ("", "", True), ("", "", True)])
        v.addLayout(grid)
        v.addWidget(self._select_row("Interpolation", ["bilinear", "nearest"]))
        row = QHBoxLayout(); row.setSpacing(8)
        ex = QPushButton("Extract line spectrum"); ex.setObjectName("beginScan")
        ex.setCursor(Qt.PointingHandCursor)
        dr = QPushButton("Draw line")
        row.addWidget(ex, 1); row.addWidget(dr)
        v.addLayout(row)
        note = self._label("Drag a line on the stack image to define the cut; "
                           "the spectrum is sampled along it.",
                           font=sans_font(10.5), color=C["text_dim"])
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)
        return page

    def _analysis_viewer_col(self):
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        tb, self._analysis_fn, self._analysis_sub = self._viewer_toolbar(
            "NS_260809057.stxm", "Energy 3 of 12 · 697.50 eV",
            self._analysis_set_cmap, ("ROI", "Levels", "Unzoom"))
        cl.addWidget(tb)

        bodyw = QWidget()
        bh = QHBoxLayout(bodyw)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)
        self._analysis_img = OverlayImageView(
            self._analysis_field(150), cmap="gray",
            meta_text="Spiral Stack · OD\npixel 0.200 µm · 12 energies\n"
                      "Fe L₃ · circ. polarization")
        # circular ROI overlays (field is 150 px; place two ROIs)
        self._analysis_img.add_circle_roi(58, 62, 14, C["ok"], "ROI 1")
        self._analysis_img.add_circle_roi(96, 92, 10, C["motion"], "ROI 2")
        bh.addWidget(self._analysis_img, 1)
        rail, self._analysis_rail = self._viewer_rail("gray")
        bh.addWidget(rail)
        cl.addWidget(bodyw, 1)

        # energy filmstrip
        strip = QFrame()
        strip.setObjectName("cardFooter")
        strip.setFixedHeight(96)
        slv = QVBoxLayout(strip)
        slv.setContentsMargins(10, 8, 10, 8)
        slv.setSpacing(6)
        top = QHBoxLayout()
        self._a_play_btn = QPushButton("▶ Play")
        self._a_play_btn.setProperty("role", "small")
        self._a_play_btn.setCursor(Qt.PointingHandCursor)
        self._a_play_btn.clicked.connect(self._toggle_analysis_play)
        top.addWidget(self._a_play_btn)
        top.addStretch(1)
        slv.addLayout(top)
        fscroll = QScrollArea()
        fscroll.setWidgetResizable(True)
        fscroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        fscroll.setFixedHeight(56)
        finner = QWidget()
        frow = QHBoxLayout(finner)
        frow.setContentsMargins(0, 0, 0, 0)
        frow.setSpacing(6)
        self._a_film = []
        for i in range(len(self.ENERGIES)):
            canvas = QLabel()
            canvas.setFixedSize(48, 48)
            canvas.setScaledContents(True)
            canvas.setCursor(Qt.PointingHandCursor)
            self._a_energy = i + 1
            f = self._analysis_field(48)
            canvas.setPixmap(_field_pixmap(f, self._analysis_cmap, 48))
            canvas.mousePressEvent = lambda e, k=i + 1: self._set_a_energy(k)
            frow.addWidget(canvas)
            self._a_film.append(canvas)
        self._a_energy = 3
        frow.addStretch(1)
        fscroll.setWidget(finner)
        slv.addWidget(fscroll)
        cl.addWidget(strip)
        return card

    def _analysis_set_cmap(self, name):
        self._analysis_cmap = name
        self._analysis_img.set_cmap(name)
        self._analysis_rail.set_lut(name)
        self._refresh_filmstrip()

    def _refresh_filmstrip(self):
        keep = self._a_energy
        for i, canvas in enumerate(self._a_film):
            self._a_energy = i + 1
            f = self._analysis_field(48)
            canvas.setPixmap(_field_pixmap(f, self._analysis_cmap, 48))
            sel = (i + 1) == keep
            canvas.setStyleSheet(
                f"background:#000;border:2px solid "
                f"{C['accent'] if sel else 'transparent'};")
        self._a_energy = keep

    def _a_cursor_moved(self):
        """Snap the draggable spectrum cursor to the nearest energy point."""
        x = self._a_cursor.value()
        i = int(np.argmin(np.abs(np.array(self.ENERGIES) - x)))
        if i + 1 != self._a_energy:
            self._set_a_energy(i + 1)

    def _set_a_energy(self, k):
        self._a_energy = int(max(1, min(len(self.ENERGIES), k)))
        ev = self.ENERGIES[self._a_energy - 1]
        # image plane
        self._analysis_img.set_field(self._analysis_field(150), autolevels=True)
        # spectrum cursor (block to avoid recursion)
        if hasattr(self, "_a_cursor"):
            self._a_cursor.blockSignals(True)
            self._a_cursor.setValue(ev)
            self._a_cursor.blockSignals(False)
        # filmstrip highlight
        for i, canvas in enumerate(getattr(self, "_a_film", [])):
            sel = (i + 1) == self._a_energy
            canvas.setStyleSheet(
                f"background:#000;border:2px solid "
                f"{C['accent'] if sel else 'transparent'};")
        # toolbar label
        if hasattr(self, "_analysis_sub"):
            self._analysis_sub.setText(
                f"Energy {self._a_energy} of {len(self.ENERGIES)} · {ev:.2f} eV")

    def _toggle_analysis_play(self):
        self._a_playing = not self._a_playing
        self._a_play_btn.setText("⏸ Pause" if self._a_playing else "▶ Play")
        if not hasattr(self, "_a_play_timer"):
            self._a_play_timer = QTimer(self)
            self._a_play_timer.timeout.connect(self._a_advance)
        if self._a_playing:
            self._a_play_timer.start(500)
        else:
            self._a_play_timer.stop()

    def _a_advance(self):
        nxt = 1 if self._a_energy >= len(self.ENERGIES) else self._a_energy + 1
        self._set_a_energy(nxt)

    def _analysis_side_col(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # ROIs
        rcard, rbody = self._card("ROIs")
        rc = QWidget()
        rv = QVBoxLayout(rc)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        roi_rows = [(C["ok"], "ROI 1", "ellipse · 41 px · Fe-rich", "1.14 max"),
                    (C["motion"], "ROI 2", "ellipse · 22 px · matrix", "0.52 max"),
                    (C["inactive_bar"], "I₀", "clear area · 180 px", "—")]
        for color, name, detail, od in roi_rows:
            rv.addWidget(self._roi_row(color, name, detail, od))
        rbody.addWidget(rc)
        v.addWidget(rcard)

        # processing
        pcard, pbody = self._card("Processing")
        pc = QWidget()
        pv = QVBoxLayout(pc)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        pipeline = [("✓", C["ok"], "Dark subtract", "auto"),
                    ("✓", C["ok"], "Despike", "4.0 σ"),
                    ("✓", C["ok"], "Align stack", "rms 1.4 px"),
                    ("✓", C["ok"], "Optical density", "I₀ ROI"),
                    ("·", C["text_faint"], "Pre-edge subtract", "not run")]
        for mark, color, step, note in pipeline:
            pv.addWidget(self._pipeline_row(mark, color, step, note))
        pbody.addWidget(pc)
        v.addWidget(pcard)

        # export
        ecard, ebody = self._card("Export")
        ec = QWidget()
        ev = QVBoxLayout(ec)
        ev.setContentsMargins(14, 14, 14, 14)
        ev.setSpacing(10)
        grid = QGridLayout(); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(8)
        for i, name in enumerate(("Spectra CSV", "Stack HDF5", "Figure PNG", "Maps TIFF")):
            b = QPushButton(name); b.setProperty("role", "small")
            grid.addWidget(b, *divmod(i, 2))
        ev.addLayout(grid)
        path = QLineEdit("/data/2026/08/09/analysis")
        ev.addWidget(path)
        exp = QPushButton("Export && log"); exp.setObjectName("beginScan")
        exp.setCursor(Qt.PointingHandCursor)
        ev.addWidget(exp)
        ebody.addWidget(ec)
        v.addWidget(ecard)
        v.addStretch(1)
        return col

    def _roi_row(self, color, name, detail, od):
        row = QFrame()
        row.setObjectName("rowSep")
        g = QHBoxLayout(row)
        g.setContentsMargins(14, 9, 14, 9)
        g.setSpacing(9)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color};background:transparent;font-size:9px;")
        g.addWidget(dot)
        nb = QVBoxLayout(); nb.setSpacing(1)
        nb.addWidget(self._label(name, role="mono"))
        nb.addWidget(self._label(detail, font=sans_font(10.5), color=C["text_dim"]))
        nw = QWidget(); nw.setLayout(nb)
        g.addWidget(nw, 1)
        odl = self._label(od, role="value"); odl.setFont(mono_font(11))
        g.addWidget(odl)
        return row

    def _pipeline_row(self, mark, color, step, note):
        row = QFrame()
        row.setObjectName("rowSep")
        g = QHBoxLayout(row)
        g.setContentsMargins(14, 9, 14, 9)
        g.setSpacing(10)
        m = QLabel(mark)
        m.setFont(mono_font(12))
        m.setStyleSheet(f"color:{color};background:transparent;")
        m.setFixedWidth(14)
        g.addWidget(m)
        g.addWidget(self._label(step, font=sans_font(12), color=C["text_2"]), 1)
        g.addWidget(self._label(note, role="monoFaint"))
        return row

    # ════════════════════════════════════════════════════════════════════
    #  Agent view — the standalone dashboard-styled task-agent console
    # ════════════════════════════════════════════════════════════════════
    def _build_agent_view(self):
        """The Agent tab: the standalone ``AgentApp`` console (conversation +
        logbook), wired to the live controller when connected and degrading to a
        read-only placeholder otherwise.  See ``agent_app_dashboard``."""
        from pystxmcontrol.gui.agent_app_dashboard import AgentApp
        self._agent_app = AgentApp(
            controller=self.controller,
            logbook_model=getattr(self.controller, "logbook_model", None),
            default_dir_provider=self._logbook_default_dir,
            parent=self)
        return self._agent_app

    def _logbook_default_dir(self):
        """Base directory for New/Open logbook dialogs — the server's data
        directory when configured, else the user's home."""
        data_dir = (_runtime_main_config().get("server") or {}).get("data_dir")
        if data_dir and os.path.isdir(data_dir):
            return data_dir
        return os.path.expanduser("~")

    # ── motor actions ────────────────────────────────────────────────────
    def _jog_step(self, name):
        """Per-motor jog step: the motor's configured scan step if positive,
        else 1% of its travel range, else 1.0.  (motor.json has no dedicated
        jog-step field, so we derive a sensible per-axis nudge.)"""
        info = self._motor_info.get(name, {})
        try:
            step = float(info.get("last step:"))
        except (TypeError, ValueError):
            step = 0.0
        if step > 0:
            return step
        try:
            span = float(info.get("maxValue")) - float(info.get("minValue"))
            if span > 0:
                return span * 0.01
        except (TypeError, ValueError):
            pass
        return 1.0

    def _move_motor_to_target(self, name):
        """Absolute move: send the target field's value to the motor."""
        if self.controller is None:
            return
        wd = self._motor_widgets.get(name)
        if not wd:
            return
        try:
            pos = float(self._target_text(wd["target"]))
        except (TypeError, ValueError):
            return
        self.controller.move_motor(name, pos)

    def _jog_motor(self, name, direction):
        """Relative jog by the step typed in the row's field; the controller adds
        it to the model's current position."""
        if self.controller is None:
            return
        wd = self._motor_widgets.get(name)
        if not wd:
            return
        try:
            step = float(self._target_text(wd["target"]))
        except (TypeError, ValueError):
            self.controller.error_occurred.emit(f"Invalid jog step for {name}")
            return
        self.controller.jog_motor(name, step, direction)

    def _toggle_move_mode(self):
        """Flip between absolute Move and relative Jog for the motor rows."""
        self._move_mode = not self._move_mode
        self._update_jogmove_btn()
        self._repopulate_motors()

    def _update_jogmove_btn(self):
        self.jogmove_btn.setText("Move mode" if self._move_mode else "Jog mode")
        self.jogmove_btn.setToolTip(
            "Absolute moves — each row's field is a destination; Move (or Enter) "
            "goes there. Click to switch to relative Jog." if self._move_mode else
            "Relative jog — each row's field is a step; − / + jog by that amount. "
            "Click to switch to absolute Move.")

    # ── scan actions ─────────────────────────────────────────────────────
    def _toggle_scan(self):
        """Begin or cancel a scan.  In placeholder mode (no controller) fall back
        to the local visual toggle so the offline layout demo still animates."""
        c = self.controller
        if c is None:
            self._set_scanning(not self._scanning)
            return
        if c.scanning:
            c.cancel_scan()
            return
        if self._compile_scan():
            self.image_area.clear_region_frames()   # fresh mosaic for the new scan
            if self._is_single_motor():
                # A single-motor scan is 1-D — swap the image for a curve plot.
                self.image_area.clear_line()
                self.image_area.set_plot_mode(True)
                self._focus_view_fitted = False
            elif self._takes_over_image():
                # Switch the viewer to the take-over frame (Focus: line × ZonePlateZ;
                # Line Spectrum: position-along-line × energy; double-motor scan:
                # its own motor coordinates).  The first frame fits the view to it.
                self.image_area.clear_line()
                self.image_area.set_focus_display(True)
                self._focus_view_fitted = False
            c.start_scan()
        # start_scan / cancel_scan emit scan_state_changed → _set_scanning keeps
        # the Begin/Cancel button in sync with the controller's real state.

    def _preview_scan(self):
        """Run an abridged sanity-check scan: the first spatial region at a single
        energy.  A real server scan (motors move, a 'preview'-tagged file is
        written), but it never touches the full scan definition and is not pushed
        to the TaskAgent as the last scan.  Disabled in single-line modes (Focus /
        Line Spectrum) and while any scan is already running."""
        c = self.controller
        if c is None or c.scanning or self._takes_over_image():
            return
        if self._compile_scan(preview=True):
            self.image_area.clear_region_frames()
            c.start_scan(preview=True)

    def _compile_scan(self, preview=False):
        """Populate the controller's scan_model from the dashboard widgets,
        mirroring MainController.compile_scan_from_view but reading THIS view's
        widgets.  Returns True on success.

        Handles Image-family scans (SampleX/SampleY spatial grid + energy
        regions) and single-line Focus scans (angled line × ZonePlateZ sweep,
        single energy).  Other scan types report an error until wired.

        ``preview=True`` compiles an abridged sanity-check scan — only the first
        spatial region at a single energy — into the scan model.  It never
        mutates the view's region/energy lists (the model is rebuilt from them on
        the next compile) and leaves the full-scan stats readout untouched.
        """
        c = self.controller
        client = c.client
        scan_type = self.scan_type.currentText()
        sc = (getattr(client, "scanConfig", None) or {}).get(scan_type)
        if sc is None:
            c.error_occurred.emit(f"Unknown scan type '{scan_type}'")
            return False
        driver = sc.get("driver", "")
        if driver not in self._SUPPORTED_SCAN_DRIVERS:
            c.error_occurred.emit(
                f"'{scan_type}' ({driver}) is not yet supported in the dashboard "
                f"— use the classic window for this scan type.")
            return False

        sm = c.get_scan_model()
        try:
            sm.set('scan_regions', {})
            sm.set('energy_regions', {})
            sm.set('scan_type', scan_type)
            sm.set('x_motor', sc.get('x_motor', 'SampleX'))
            sm.set('y_motor', sc.get('y_motor', 'SampleY'))
            sm.set('tiled', self._scan_checks['tiled'].isChecked())
            sm.set('coarse_only', False)   # validate_ranges may set True
            sm.set('defocus', self._scan_checks['defocus'].isChecked())
            sm.set('autofocus', self._scan_checks['autofocus'].isChecked())
            de = self._double_exposure_ro
            sm.set('doubleExposure', bool(de and 'enabled' in de.text().lower()))
            proposal, experimenters = self._proposal_parts()
            sm.set('proposal', proposal)
            sm.set('experimenters', experimenters)
            sm.set('sample', self._sample_field.text())
            sm.set('comment', 'preview' if preview else '')
            sm.set('driver', driver)
            sm.set('mode', sc.get('mode', 'continuousLine'))
            sm.set('loop_scan', False)   # loop sequence not yet wired in dashboard
            sm.set('daq_list', self._resolve_daq_list(client, sc))

            if self._focus_mode:
                region = self._compile_focus(sm, sc)
            elif self._ls_mode:
                region = self._compile_line_spectrum(sm, sc)
            elif self._motor_scan_mode:
                region = self._compile_motor_scan(sm, sc)
            else:
                region = self._compile_image_regions(sm, preview=preview)

            est = sm.calculate_estimated_time()
            if preview:
                # Leave the stats panel showing the full scan; just report the est.
                c.status_updated.emit(f"Preview compiled — est. {self._fmt_mmss(est)}")
            else:
                self._set_scan_stats(est, self._total_scan_points(sm),
                                     sm.get_scan_velocity())
                c.status_updated.emit(f"Scan compiled — est. {self._fmt_mmss(est)}")
            return True
        except ValueError as e:
            c.error_occurred.emit(f"Invalid scan value: {e}")
            return False
        except Exception as e:
            c.error_occurred.emit(f"Failed to compile scan: {e}")
            return False

    def _compile_image_regions(self, sm, preview=False):
        """Populate ``sm`` with the image-family spatial + energy regions and
        return the primary region dict (for the stats readout).

        ``preview=True`` emits only the first spatial region at a single energy
        (the start of the first energy region) — an abridged sanity check.  The
        view's region/energy lists are only read, never reassigned."""
        # Spatial regions — flush the grid into the active region, then emit
        # every image region (plus the spectrum region, if enabled).
        if isinstance(self._active_region, int):
            self._scan_regions[self._active_region].update(
                self._read_spatial_fields())
        elif self._spectrum_region is not None:
            self._spectrum_region.update(self._read_spatial_fields())
        region = self._region_scan_dict(self._scan_regions[0])
        if preview:
            # First region only; no extra regions, no spectrum region.
            sm.add_scan_region('Region1', region)
        else:
            for i, r in enumerate(self._scan_regions):
                sm.add_scan_region(f'Region{i + 1}', self._region_scan_dict(r))
            if self._spectrum_region is not None:
                spec = self._region_scan_dict(self._spectrum_region)
                spec['spectrum'] = True
                sm.add_scan_region('SpectrumRegion', spec)

        # Energy regions — flush the field row into the active region first.
        self._sync_active_energy_region()
        if preview:
            # Collapse to a single energy: the start of the first energy region.
            e0 = self._energy_regions[0]
            sm.add_energy_region('EnergyRegion1', {
                'start': e0['start'], 'stop': e0['start'], 'step': 0.0,
                'dwell': e0['dwell'], 'n_energies': 1})
            sm.set('single_energy', True)
        else:
            total_n = 0
            for i, r in enumerate(self._energy_regions):
                total_n += r['n']
                sm.add_energy_region(f'EnergyRegion{i + 1}', {
                    'start': r['start'], 'stop': r['stop'], 'step': r['step'],
                    'dwell': r['dwell'], 'n_energies': r['n']})
            sm.set('single_energy', total_n <= 1)
        sm.set('energy_list', None)
        return region

    def _compile_focus(self, sm, sc):
        """Populate ``sm`` for a single-line focus scan: one scan region (angled
        line × ZonePlateZ sweep) at a single energy.  Returns the region dict."""
        # Flush live edits from the fields into the focus model + R1 centre.
        self._on_focus_edit()
        self._on_line_edit()
        if isinstance(self._active_region, int):
            self._scan_regions[self._active_region].update(
                self._read_spatial_fields())
        sm.set('z_motor', sc.get('z_motor', 'ZonePlateZ'))
        sm.set('tiled', False)          # focus is a single line, never tiled
        sm.set('autofocus', bool(getattr(self, '_focus_move_to_best', None)
                                 and self._focus_move_to_best.isChecked()))
        region = self._focus_region_scan_dict()
        sm.add_scan_region('Region1', region)

        # Single energy: take the first energy region's start + dwell.
        self._sync_active_energy_region()
        e0 = self._energy_regions[0] if getattr(self, '_energy_regions', None) else \
            {'start': 700.0, 'dwell': 2.0}
        sm.add_energy_region('EnergyRegion1', {
            'start': e0['start'], 'stop': e0['start'], 'step': 0.0,
            'dwell': e0['dwell'], 'n_energies': 1})
        sm.set('single_energy', True)
        sm.set('energy_list', None)
        sm.set('dwell', e0['dwell'])
        return region

    def _compile_line_spectrum(self, sm, sc):  # noqa: ARG002
        """Populate ``sm`` for a line-spectrum scan: one single-line scan region
        (the line is the fast axis) crossed with the full multi-region energy
        axis — energy behaves exactly as it does for an Image scan.  Returns the
        region dict."""
        # Flush live edits from the fields into the line model + R1 projection.
        self._on_line_edit()
        if isinstance(self._active_region, int):
            self._scan_regions[self._active_region].update(
                self._read_spatial_fields())
        sm.set('tiled', False)          # a single line is never tiled
        region = self._line_spectrum_region_scan_dict()
        sm.add_scan_region('Region1', region)
        # Energy regions — identical to the Image path (multi-region, multi-energy).
        self._emit_energy_regions(sm)
        return region

    def _emit_energy_regions(self, sm):
        """Flush the active energy row and add every energy region to ``sm`` (the
        full multi-region / multi-energy axis, as an Image scan uses)."""
        self._sync_active_energy_region()
        total_n = 0
        for i, r in enumerate(self._energy_regions):
            total_n += r['n']
            sm.add_energy_region(f'EnergyRegion{i + 1}', {
                'start': r['start'], 'stop': r['stop'], 'step': r['step'],
                'dwell': r['dwell'], 'n_energies': r['n']})
        sm.set('single_energy', total_n <= 1)
        sm.set('energy_list', None)

    def _compile_motor_scan(self, sm, sc):
        """Populate ``sm`` for a single- or double-motor scan: one scan region
        whose geometry comes from the Motor-scan control group (one or two motors,
        each with center/range/points), crossed with the energy axis (dwell +
        energies from the Energy tab, as an Image scan).  Returns the region dict."""
        scan_type = self.scan_type.currentText()
        axes = self._motor_axis_count(scan_type)
        self._on_motor_edit()   # flush derived steps
        # Motor selection overrides the config defaults set by _compile_scan.
        x_motor = self._motor_axis_widgets[0]['combo'].currentText() \
            or sc.get('x_motor', '')
        sm.set('x_motor', x_motor)
        if axes >= 2:
            sm.set('y_motor', self._motor_axis_widgets[1]['combo'].currentText()
                   or sc.get('y_motor', ''))
        else:
            # A single-motor scan never moves a y motor, but the scan model still
            # requires a non-empty y_motor to validate — mirror it to x_motor (the
            # server ignores it; its yRange is 0 so range checks skip it too).
            sm.set('y_motor', x_motor)
        sm.set('tiled', False)
        region = self._motor_region_scan_dict(axes)
        sm.add_scan_region('Region1', region)
        self._emit_energy_regions(sm)
        return region

    def _motor_region_scan_dict(self, axes):
        """Scan-region dict for a motor scan, built from the Motor-scan group's
        center/range/points fields (full-field half-pixel convention via
        _region_scan_dict).  A single-motor scan has one row (yPoints=1)."""
        def read(ax):
            try:
                c = float(ax['center'].text() or 0)
                r = abs(float(ax['range'].text() or 0))
                n = max(1, int(float(ax['npts'].text() or 1)))
            except ValueError:
                c, r, n = 0.0, 0.0, 1
            return c, r, n
        xc, xr, xp = read(self._motor_axis_widgets[0])
        if axes >= 2:
            yc, yr, yp = read(self._motor_axis_widgets[1])
        else:
            yc, yr, yp = 0.0, 0.0, 1
        return self._region_scan_dict({
            'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr,
            'xPoints': xp, 'yPoints': yp})

    def _line_spectrum_region_scan_dict(self):
        """Single-line scan-region dict for a line spectrum: an angled line (the
        fast axis, ``xPoints`` points) with a single slow-axis row (``yPoints`` =
        1); energy is swept by the outer loop.  ``xRange`` carries the true
        along-line length so the display's position axis is line distance, while
        ``xStart/xStop/yStart/yStop`` carry the real angled endpoints."""
        fr = self._ensure_focus_region()
        xc, yc = self._line_center()
        L = fr['length']
        n = max(1, int(fr['points']))
        ar = np.radians(fr['angle'])
        ux, uy = np.cos(ar), np.sin(ar)
        # Half-pixel inset along the line direction (matches the Image convention).
        s0 = -(L / 2.0) + (L / (2.0 * n))
        s1 = (L / 2.0) - (L / (2.0 * n))
        return {
            'xCenter': xc, 'yCenter': yc,
            'xRange': L, 'yRange': abs(L * uy),
            'xPoints': n, 'yPoints': 1,
            'xStep': L / n, 'yStep': abs(L * uy),
            'xStart': xc + s0 * ux, 'xStop': xc + s1 * ux,
            'yStart': yc + s0 * uy, 'yStop': yc + s1 * uy,
            'zCenter': 0, 'zRange': 0, 'zPoints': 1, 'zStep': 0,
            'zStart': 0, 'zStop': 0,
        }

    def _ls_energy_span(self):
        """(lo, hi, n) energy extent of the planned line-spectrum scan, from the
        view's energy-region list — the horizontal axis of the streak display."""
        regs = getattr(self, '_energy_regions', None) or []
        if not regs:
            return 700.0, 730.0, 1
        lo = min(r['start'] for r in regs)
        hi = max(r['stop'] for r in regs)
        n = sum(int(r['n']) for r in regs) or 1
        return lo, hi, n

    def _show_last_scan_image(self):
        """Paint the most recently recorded ``.stxm`` scan at its *own* fixed
        physical extent (the region it was scanned over), independent of the
        editable scan-region ROIs.  Region1 is aligned to that extent so a new
        scan starts as "the whole displayed image", ready to be shrunk to a
        sub-region.  No-op — black canvas + ROI boxes — when no file is readable."""
        if not hasattr(self, "image_area"):
            return
        try:
            path = _find_last_scan_file()
            if not path:
                return
            loaded = _load_last_scan(path)
            if loaded is None:
                return
            arr, extent = loaded
            if extent is not None:
                xc, yc, xr, yr = extent
                # Fix the displayed data at its scanned extent …
                self.image_area.set_image_extent(xc, yc, xr, yr)
                # … and start Region1 covering it (user then drags it smaller).
                self._scan_regions[0] = {
                    'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr,
                    'xPoints': int(arr.shape[1]), 'yPoints': int(arr.shape[0])}
                if self._active_region == 0:
                    self._write_spatial_fields(self._scan_regions[0])
            self.image_area.set_primary_frame(arr)
            self._image_seeded = True
            self._refresh_spatial_image(fit=True)
            if hasattr(self, "_image_title_lbl"):
                self._image_title_lbl.setText(os.path.basename(path))
        except Exception as e:
            print(f"[dashboard] could not display last scan: {e}")

    def _refresh_image_meta(self):
        """Refresh the image's bottom metadata overlay from the current scan
        definition (proposal, scan type, sample, pixel size, dwell, energy)."""
        if not hasattr(self, "image_area"):
            return
        try:
            proposal = self._proposal_parts()[0]
        except Exception:
            proposal = ""
        scan_type = self.scan_type.currentText() if hasattr(self, "scan_type") else ""
        sample = (self._sample_field.text()
                  if getattr(self, "_sample_field", None) else "")
        pixel_um = None
        try:
            reg = self._scan_regions[0]
            if reg.get("xPoints"):
                pixel_um = reg["xRange"] / reg["xPoints"]
        except Exception:
            pass
        dwell_ms = energy_ev = None
        try:
            dwell_ms = self._energy_regions[self._active_energy_region]["dwell"]
        except Exception:
            pass
        energy_ev = self._motor_info.get("Energy", {}).get("last value")
        if energy_ev is None:
            try:
                energy_ev = float(self._energy_fields["start"].text())
            except (ValueError, KeyError, AttributeError):
                pass
        self.image_area.set_metadata(
            scan_type=scan_type, sample=sample, proposal=proposal,
            channel="default", pixel_um=pixel_um, dwell_ms=dwell_ms,
            energy_ev=energy_ev)

    def _prefill_from_last_scan(self):
        """Pre-fill the spatial + energy regions from the last executed Image
        scan, which the server ships in ``client.main_config['lastScan']['Image']``
        on connect.  No-op if unavailable (fresh install / non-Image history)."""
        client = getattr(self.controller, 'client', None)
        main_cfg = getattr(client, 'main_config', None) or {}
        last = (main_cfg.get('lastScan') or {}).get('Image')
        if not last:
            return
        try:
            regs = []
            for r in (last.get('scan_regions') or {}).values():
                regs.append({
                    'xCenter': float(r.get('xCenter', 0.0)),
                    'yCenter': float(r.get('yCenter', 0.0)),
                    'xRange': float(r.get('xRange', 10.0)),
                    'yRange': float(r.get('yRange', 10.0)),
                    'xPoints': max(1, int(r.get('xPoints', 100))),
                    'yPoints': max(1, int(r.get('yPoints', 100)))})
            if regs:
                self._scan_regions = regs
                self._active_region = 0
                self._spectrum_region = None
                self._write_spatial_fields(regs[0])
                self._refresh_spatial_image(fit=True)

            eregs = []
            for e in (last.get('energy_regions') or {}).values():
                start = float(e.get('start', 0.0)); stop = float(e.get('stop', 0.0))
                step = float(e.get('step', 0.0))
                eregs.append({'start': start, 'stop': stop, 'step': step,
                              'dwell': float(e.get('dwell', 1.0)),
                              'n': int(e.get('n_energies', 1)) or 1})
            if eregs:
                self._energy_regions = eregs
                self._active_energy_region = 0
                self._load_energy_region(0)

            sample = last.get('sample')
            if sample and getattr(self, '_sample_field', None):
                self._sample_field.setText(str(sample))
        except (ValueError, TypeError, KeyError) as ex:
            self._on_error(f"Could not pre-fill last scan: {ex}")

    @staticmethod
    def _region_scan_dict(r):
        """Expand a region-model dict {xCenter,yCenter,xRange,yRange,xPoints,
        yPoints} into a full Image scan-region dict (same shape/math as
        MainController._extract_scan_region_data's Image branch)."""
        xc, yc = r['xCenter'], r['yCenter']
        xr, yr = r['xRange'], r['yRange']
        xp = max(1, int(r['xPoints']))
        yp = max(1, int(r['yPoints']))
        xs = xr / xp if xp > 0 else 0.1
        ys = yr / yp if yp > 0 else 0.1
        return {
            'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr,
            'xPoints': xp, 'yPoints': yp, 'xStep': xs, 'yStep': ys,
            'xStart': xc - xr / 2.0 + xs / 2.0, 'xStop': xc + xr / 2.0 - xs / 2.0,
            'yStart': yc - yr / 2.0 + ys / 2.0, 'yStop': yc + yr / 2.0 - ys / 2.0,
            'zCenter': 0, 'zRange': 0, 'zPoints': 1, 'zStep': 0,
            'zStart': 0, 'zStop': 0,
        }

    @staticmethod
    def _resolve_daq_list(client, sc):
        """DAQ channels from scan config, filtered to those present and
        record=True in daqConfig (mirrors compile_scan_from_view)."""
        requested = sc.get('daq_list', '')
        if isinstance(requested, str):
            requested = [t for t in requested.split(',') if t]
        if not requested:
            requested = list(getattr(client, 'daqConfig', {}).keys())
        daq_cfg = getattr(client, 'daqConfig', {})
        daq = [k for k in requested
               if k in daq_cfg and daq_cfg[k].get('record', True)]
        return daq or ['default']

    def _proposal_parts(self):
        """Split the 'ALS-14872 · Shapiro' proposal label into (proposal,
        experimenters).  Placeholder until a real proposal selector exists."""
        txt = self._proposal_lbl.text()
        if '·' in txt:
            p, e = txt.split('·', 1)
            return p.strip(), e.strip()
        return txt.strip(), ''

    @staticmethod
    def _energy_n(start, stop, step):
        if step and abs(step) > 0:
            return int(round(abs(stop - start) / abs(step))) + 1
        return 1

    # Continuous-line stages must not be driven faster than this (mm/s); the
    # Velocity readout turns red past it so it is caught before Begin.
    _MAX_SCAN_VELOCITY = 1.0

    def _set_scan_stats(self, est_seconds, n_points, velocity_mm_s):
        """Write the Est. time / Velocity / Points readout.  Any value passed as
        ``None`` leaves its label untouched.  Velocity turns red past the
        continuous-scan speed limit (``_MAX_SCAN_VELOCITY``)."""
        lbls = getattr(self, "_stat_labels", {})
        if est_seconds is not None and 'Est. time' in lbls:
            lbls['Est. time'].setText(self._fmt_mmss(est_seconds))
        if n_points is not None and 'Points' in lbls:
            lbls['Points'].setText(f"{int(n_points):,}".replace(',', ' '))
        if velocity_mm_s is not None and 'Velocity' in lbls:
            v = lbls['Velocity']
            v.setText(f"{velocity_mm_s:.3f} mm/s")
            v.setStyleSheet(f"color:{C['alert']};"
                            if velocity_mm_s > self._MAX_SCAN_VELOCITY else "")

    def _refresh_scan_stats(self):
        """Recompute the Est. time / Velocity / Points readout from the current
        view state, so the stats reflect the scan definition live (before Begin).
        Controller-free; a no-op until the stat labels and scan state exist."""
        if not getattr(self, "_stat_labels", None):
            return
        try:
            est, pts, vel = self._scan_stats_from_view()
        except Exception:
            return
        self._set_scan_stats(est, pts, vel)

    def _total_scan_points(self, sm):
        """Total acquisition points in a compiled scan model: every spatial point
        (summed over scan regions) measured at every energy.  Focus counts the
        ZonePlateZ sweep as its slow axis; Image/Ptychography count yPoints."""
        scan_regions = sm.get('scan_regions', {}) or {}
        energy_regions = sm.get('energy_regions', {}) or {}
        n_energies = sum(int(r.get('n_energies', 1))
                         for r in energy_regions.values()) or 1
        spatial = 0
        for r in scan_regions.values():
            rows = int(r['zPoints']) if self._focus_mode else int(r['yPoints'])
            spatial += int(r['xPoints']) * rows
        return spatial * n_energies

    def _scan_stats_from_view(self):
        """(est_seconds, points, velocity_mm_s) computed from the current view.

        Mirrors ``ScanModel.calculate_estimated_time`` / ``get_scan_velocity`` for
        the dashboard-supported families (Image, Ptychography, Focus), reading the
        already-flushed region/energy models rather than the shared scan model so
        it stays a pure, side-effect-free read.  ``xStep`` is µm and dwell is ms,
        so ``xStep / dwell`` is already mm/s."""
        scan_type = self.scan_type.currentText()
        is_ptycho = "Ptychography" in scan_type
        is_focus = self._focus_mode

        is_motor = getattr(self, "_motor_scan_mode", False)

        # Region dicts from the already-flushed models.
        if is_focus:
            regions = [self._focus_region_scan_dict()]
        elif self._ls_mode:
            # Single line (yPoints=1) swept over the full multi-region energy axis.
            regions = [self._line_spectrum_region_scan_dict()]
        elif is_motor:
            regions = [self._motor_region_scan_dict(self._motor_axis_count(scan_type))]
        else:
            regions = [self._region_scan_dict(r) for r in self._scan_regions]
            if self._spectrum_region is not None:
                regions.append(self._region_scan_dict(self._spectrum_region))

        # Energy regions.  Focus is always a single energy (compile forces it),
        # so use only the first region's dwell there.
        eregs = list(getattr(self, "_energy_regions", None) or [])
        if is_focus:
            d0 = eregs[0]["dwell"] if eregs else 2.0
            eff = [{"dwell": d0, "n": 1}]
        else:
            eff = eregs

        # ── points / lines (ScanModel.calculate_estimated_time) ──────────────
        point_overhead = 0.1 if is_ptycho else 0.0001
        line_overhead, energy_overhead = 0.02, 5.0
        n_points = n_lines = 0
        for rd in regions:
            rows = int(rd["zPoints"]) if is_focus else int(rd["yPoints"])
            n_points += int(rd["xPoints"]) * rows
            n_lines += rows
        time_per_point = 0.0
        n_energies = 0
        for er in eff:
            energies = int(er.get("n", 1))
            time_per_point += (er.get("dwell", 1.0) / 1000.0 + point_overhead) * energies
            n_energies += energies
        est = (n_points * time_per_point
               + n_lines * n_energies * line_overhead
               + max(0, n_energies - 1) * energy_overhead)

        # ── velocity (ScanModel.get_scan_velocity): max xStep/dwell over regions
        #     using the first energy region's dwell ───────────────────────────
        d_first = (eff[0]["dwell"] if eff else 1.0) or 1.0
        # Point-mode scans step to each point (no continuous stage sweep), so a
        # scan velocity is meaningless — report 0 rather than a false red alarm.
        if is_motor and (self._scan_cfg(scan_type) or {}).get("mode") == "point":
            vel = 0.0
        else:
            vel = max((rd.get("xStep", 0.0) / d_first for rd in regions), default=0.0)

        # Total acquisition points: every spatial point (summed over regions)
        # measured at every energy.
        pts = n_points * n_energies
        return est, pts, vel

    def _recompute_step(self, range_e, npts_e, step_e):
        """Derived spatial step = Range / N pts (full-field convention)."""
        try:
            rng = float(range_e.text()); n = int(float(npts_e.text()))
            step_e.setText(f"{rng / n:.3f}" if n > 0 else "0.000")
        except ValueError:
            pass

    # ── spatial-region model ─────────────────────────────────────────────
    def _read_spatial_fields(self):
        """Snapshot the SampleX / SampleY grid into a region dict."""
        def rd(name):
            f = self._spatial_fields[name]
            try:
                c = float(f['center'].text() or 0)
                rng = float(f['range'].text() or 0)
                n = int(float(f['npts'].text() or 1))
            except ValueError:
                c, rng, n = 0.0, 0.0, 1
            return c, rng, max(1, n)
        xc, xr, xn = rd('SampleX')
        yc, yr, yn = rd('SampleY')
        return {'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr,
                'xPoints': xn, 'yPoints': yn}

    def _write_spatial_fields(self, r):
        """Load a region dict back into the grid (does not fire edit signals)."""
        for name, c, rng, n in (('SampleX', r['xCenter'], r['xRange'], r['xPoints']),
                                ('SampleY', r['yCenter'], r['yRange'], r['yPoints'])):
            f = self._spatial_fields[name]
            f['center'].setText(f"{c:.3f}")
            f['range'].setText(f"{rng:.3f}")
            f['npts'].setText(str(int(n)))
            f['step'].setText(f"{rng / n:.3f}" if n > 0 else "0.000")

    def _active_region_dict(self):
        """The region dict the grid currently edits (image region or spectrum)."""
        if self._active_region == 'spectrum':
            return self._spectrum_region
        if 0 <= self._active_region < len(self._scan_regions):
            return self._scan_regions[self._active_region]
        return None

    def _on_spatial_edit(self):
        """A grid field was typed: re-derive steps, push into the active region,
        then refit the field-of-view so the box stays in view."""
        for name in ('SampleX', 'SampleY'):
            f = self._spatial_fields[name]
            self._recompute_step(f['range'], f['npts'], f['step'])
        reg = self._active_region_dict()
        if reg is not None:
            reg.update(self._read_spatial_fields())
        self._refresh_spatial_image(fit=True)
        self._refresh_image_meta()
        self._refresh_scan_stats()

    def _load_spatial_region(self, target):
        """Make ``target`` (an int index or 'spectrum') active and load it."""
        reg = (self._spectrum_region if target == 'spectrum'
               else self._scan_regions[target] if 0 <= target < len(self._scan_regions)
               else None)
        if reg is None:
            return
        self._active_region = target
        self._write_spatial_fields(reg)
        self._refresh_spatial_image()
        self._refresh_scan_stats()

    def _add_spatial_region(self):
        """Append a region offset from the active one and select it."""
        base = self._active_region_dict() or self._read_spatial_fields()
        new = dict(base)
        new['xCenter'] = base['xCenter'] + base['xRange']
        self._scan_regions.append(new)
        self._load_spatial_region(len(self._scan_regions) - 1)
        self._refresh_spatial_image(fit=True)

    def _remove_spatial_region(self):
        """Remove the active region (spectrum box, or an image region if >1)."""
        if self._active_region == 'spectrum':
            self._spectrum_region = None
            self._scan_checks['spectrum region'].setChecked(False)
            self._load_spatial_region(0)
        elif len(self._scan_regions) > 1:
            del self._scan_regions[self._active_region]
            self._load_spatial_region(min(self._active_region,
                                          len(self._scan_regions) - 1))
        self._refresh_spatial_image(fit=True)

    def _toggle_spectrum(self, on):
        """Show/hide the special spectrum ROI (a distinct-coloured box)."""
        if on:
            base = self._active_region_dict() or self._read_spatial_fields()
            self._spectrum_region = {
                'xCenter': base['xCenter'], 'yCenter': base['yCenter'],
                'xRange': max(base['xRange'] * 0.4, 1.0),
                'yRange': max(base['yRange'] * 0.4, 1.0),
                'xPoints': 1, 'yPoints': 1}
            self._load_spatial_region('spectrum')
        else:
            self._spectrum_region = None
            if self._active_region == 'spectrum':
                self._load_spatial_region(0)
        self._refresh_spatial_image(fit=True)

    def _spatial_region_list(self):
        """Combined list of {key, geometry, label, kind, active} for the image."""
        out = []
        for i, r in enumerate(self._scan_regions):
            out.append({'key': str(i), 'label': f"R{i + 1}", 'kind': 'region',
                        'active': self._active_region == i,
                        **{k: r[k] for k in
                           ('xCenter', 'yCenter', 'xRange', 'yRange')}})
        if self._spectrum_region is not None:
            r = self._spectrum_region
            out.append({'key': 'spectrum', 'label': "Spec", 'kind': 'spectrum',
                        'active': self._active_region == 'spectrum',
                        **{k: r[k] for k in
                           ('xCenter', 'yCenter', 'xRange', 'yRange')}})
        return out

    def _fit_fov(self):
        """Fit the *view* to hold the displayed data plus all scan-region ROIs.

        The displayed data has its OWN fixed extent (set when data arrives); the
        ROIs float over it and are edited to define a new scan.  We therefore
        never move or resize the image from here — except as a fallback when no
        real data has been shown yet, where the black placeholder is aligned under
        Region1 so an empty canvas still tracks the region being defined."""
        regs = list(self._scan_regions)
        if self._spectrum_region is not None:
            regs.append(self._spectrum_region)

        if not self._image_seeded and self._scan_regions:
            # No real data yet: keep the placeholder aligned under Region1.
            primary = self._scan_regions[0]
            self.image_area.set_image_extent(
                primary['xCenter'], primary['yCenter'],
                primary['xRange'], primary['yRange'])

        # View = bounding box of the fixed image extent + every ROI box.
        boxes = []
        img = self.image_area.image_extent()
        if img is not None:
            boxes.append(img)                        # (x0, y0, x1, y1)
        for r in regs:
            boxes.append((r['xCenter'] - r['xRange'] / 2,
                          r['yCenter'] - r['yRange'] / 2,
                          r['xCenter'] + r['xRange'] / 2,
                          r['yCenter'] + r['yRange'] / 2))
        if not boxes:
            return
        x0 = min(b[0] for b in boxes); x1 = max(b[2] for b in boxes)
        y0 = min(b[1] for b in boxes); y1 = max(b[3] for b in boxes)
        xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
        # View so the content fills ~80% of it (10% margin each side).
        span = max(x1 - x0, y1 - y0)
        w = max(span, 0.5) / 0.8
        self.image_area.set_view(xc, yc, w, w)

    def _refresh_spatial_image(self, fit=False):
        """Redraw the ROI boxes (and optionally refit the FOV) from the model.

        In a single-line mode (Focus / Line Spectrum) the scan LINE replaces the
        RectROI boxes."""
        if self._syncing_spatial or not hasattr(self, 'image_area'):
            return
        if getattr(self, '_del_region_btn', None):
            self._del_region_btn.setEnabled(
                not self._takes_over_image()
                and (self._active_region == 'spectrum'
                     or len(self._scan_regions) > 1))
        if self._is_line_scan():
            self.image_area.sync_regions([])
            self._refresh_focus_line()
            if fit:
                self._fit_fov()
            return
        if getattr(self, '_motor_scan_mode', False):
            # A motor scan lives in its own coordinate space — draw no ROI or line
            # on the sample image; the result frame takes the display over at scan
            # time (see _on_image / _toggle_scan).
            self.image_area.sync_regions([])
            self.image_area.clear_line()
            return
        self.image_area.clear_line()
        show = self._scan_checks['show ROI'].isChecked()
        if fit:
            self._fit_fov()
        self.image_area.sync_regions(self._spatial_region_list() if show else [])

    # ── image ROI → model (graphical editing) ────────────────────────────
    def _key_to_target(self, key):
        return 'spectrum' if key == 'spectrum' else int(key)

    def _on_roi_selected(self, key):
        target = self._key_to_target(key)
        if target != self._active_region:
            self._load_spatial_region(target)

    def _on_roi_moving(self, key, xc, yc, xr, yr):
        """Live geometry during a drag: update grid + model, no FOV refit."""
        target = self._key_to_target(key)
        reg = (self._spectrum_region if target == 'spectrum'
               else self._scan_regions[target])
        reg.update({'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr})
        if target == self._active_region:
            self._syncing_spatial = True
            try:
                self._write_spatial_fields(reg)
            finally:
                self._syncing_spatial = False

    def _on_roi_moved(self, key, xc, yc, xr, yr):
        """Drag finished: commit geometry and refit the FOV."""
        self._on_roi_moving(key, xc, yc, xr, yr)
        self._refresh_spatial_image(fit=True)
        self._refresh_scan_stats()

    # ── focus-scan model ─────────────────────────────────────────────────
    def _current_motor_pos(self, name, default=0.0):
        """Live position of ``name`` from the controller motor model, falling
        back to the loaded motor config's 'last value', then ``default``."""
        try:
            pos = (self.controller.get_motor_model()
                   .get('current_positions', {}).get(name))
            if isinstance(pos, (int, float)):
                return float(pos)
        except Exception:
            pass
        v = self._motor_info.get(name, {}).get('last value')
        return float(v) if isinstance(v, (int, float)) else float(default)

    def _ensure_focus_region(self):
        """Create the focus-scan model with sensible defaults the first time
        (ZonePlateZ centre = current position, range 100 / 50 pts; line length =
        Region 1 width, 50 pts, angle 0)."""
        if self._focus_region is None:
            r1 = self._scan_regions[0] if self._scan_regions else {}
            self._focus_region = {
                'length': float(r1.get('xRange', 10.0)) or 10.0,
                'angle': 0.0, 'points': 50,
                'zCenter': self._current_motor_pos('ZonePlateZ'),
                'zRange': 100.0, 'zPoints': 50}
        return self._focus_region

    def _line_center(self):
        """The focus line's centre = Region 1 centre (SampleX/SampleY)."""
        r1 = self._scan_regions[0] if self._scan_regions else {}
        return float(r1.get('xCenter', 0.0)), float(r1.get('yCenter', 0.0))

    def _write_focus_fields(self):
        """Load the focus-Z model into the Focus Z + Line control fields."""
        fr = self._ensure_focus_region()
        f = self._focus_fields
        f['center'].setText(f"{fr['zCenter']:.3f}")
        f['range'].setText(f"{fr['zRange']:.3f}")
        f['points'].setText(str(int(fr['zPoints'])))
        f['step'].setText(f"{fr['zRange'] / fr['zPoints']:.3f}"
                          if fr['zPoints'] else "0.000")
        ln = self._line_fields
        ln['length'].setText(f"{fr['length']:.3f}")
        ln['angle'].setText(f"{fr['angle']:.1f}")
        ln['points'].setText(str(int(fr['points'])))
        ln['step'].setText(f"{fr['length'] / fr['points']:.3f}"
                           if fr['points'] else "0.000")

    def _on_focus_edit(self):
        """A Focus Z field was typed: re-derive Z step and store into the model."""
        fr = self._ensure_focus_region()
        try:
            fr['zCenter'] = float(self._focus_fields['center'].text() or 0)
            fr['zRange'] = abs(float(self._focus_fields['range'].text() or 0))
            fr['zPoints'] = max(1, int(float(self._focus_fields['points'].text() or 1)))
        except ValueError:
            return
        self._focus_fields['step'].setText(
            f"{fr['zRange'] / fr['zPoints']:.3f}" if fr['zPoints'] else "0.000")
        self._refresh_scan_stats()

    def _on_line_edit(self):
        """A Line field was typed: re-derive step, store, and redraw the line."""
        fr = self._ensure_focus_region()
        try:
            fr['length'] = abs(float(self._line_fields['length'].text() or 0))
            fr['angle'] = float(self._line_fields['angle'].text() or 0)
            fr['points'] = max(1, int(float(self._line_fields['points'].text() or 1)))
        except ValueError:
            return
        self._line_fields['step'].setText(
            f"{fr['length'] / fr['points']:.3f}" if fr['points'] else "0.000")
        self._apply_line_projection(fr['length'], fr['angle'])
        self._refresh_focus_line()
        self._refresh_scan_stats()

    def _focus_center_to_current(self):
        """'Set center to current' — snap the focus Z centre to live ZonePlateZ."""
        fr = self._ensure_focus_region()
        fr['zCenter'] = self._current_motor_pos('ZonePlateZ')
        self._focus_fields['center'].setText(f"{fr['zCenter']:.3f}")

    def _refresh_focus_line(self):
        """Draw/update the scan line on the sample image from the focus model
        and refresh the endpoint label."""
        if not hasattr(self, 'image_area') or not self._is_line_scan():
            return
        fr = self._ensure_focus_region()
        xc, yc = self._line_center()
        self.image_area.sync_line(xc, yc, fr['length'], fr['angle'])
        self._syncing_spatial = True
        try:
            self._apply_line_projection(fr['length'], fr['angle'])
        finally:
            self._syncing_spatial = False
        (x1, y1), (x2, y2) = ImageArea._line_endpoints(
            xc, yc, fr['length'], fr['angle'])
        if hasattr(self, '_line_endpoints_lbl'):
            self._line_endpoints_lbl.setText(
                f"from ({x1:.1f}, {y1:.1f}) → ({x2:.1f}, {y2:.1f})")

    def _apply_line_projection(self, length, angle):
        """Push the line's projected X/Y extents into Region 1 + the SampleX /
        SampleY range+step grid fields.  The scan LINE has a length and angle,
        but its bounding box on the sample axes is xRange = L·|cosθ|,
        yRange = L·|sinθ| — so the spatial grid tracks the line as it rotates."""
        ar = np.radians(angle)
        xr = abs(length * np.cos(ar))
        yr = abs(length * np.sin(ar))
        if self._scan_regions:
            self._scan_regions[0]['xRange'] = xr
            self._scan_regions[0]['yRange'] = yr
        if self._active_region != 0:
            return
        for name, rng in (('SampleX', xr), ('SampleY', yr)):
            f = self._spatial_fields[name]
            f['range'].setText(f"{rng:.3f}")
            try:
                n = int(float(f['npts'].text() or 1))
            except ValueError:
                n = 1
            f['step'].setText(f"{rng / n:.3f}" if n > 0 else "0.000")

    def _on_line_moving(self, xc, yc, length, angle):
        """Live line drag: update R1 centre + line model + fields (no refit)."""
        if not self._is_line_scan():
            return
        fr = self._ensure_focus_region()
        fr['length'], fr['angle'] = float(length), float(angle)
        if self._scan_regions:
            self._scan_regions[0]['xCenter'] = float(xc)
            self._scan_regions[0]['yCenter'] = float(yc)
        self._syncing_spatial = True
        try:
            self._line_fields['length'].setText(f"{fr['length']:.3f}")
            self._line_fields['angle'].setText(f"{fr['angle']:.1f}")
            self._line_fields['step'].setText(
                f"{fr['length'] / fr['points']:.3f}" if fr['points'] else "0.000")
            if self._active_region == 0:
                self._spatial_fields['SampleX']['center'].setText(f"{xc:.3f}")
                self._spatial_fields['SampleY']['center'].setText(f"{yc:.3f}")
            self._apply_line_projection(fr['length'], fr['angle'])
        finally:
            self._syncing_spatial = False
        (x1, y1), (x2, y2) = ImageArea._line_endpoints(xc, yc, length, angle)
        if hasattr(self, '_line_endpoints_lbl'):
            self._line_endpoints_lbl.setText(
                f"from ({x1:.1f}, {y1:.1f}) → ({x2:.1f}, {y2:.1f})")

    def _on_line_moved(self, xc, yc, length, angle):
        """Line drag finished: commit and refit the FOV around it."""
        self._on_line_moving(xc, yc, length, angle)
        self._fit_fov()
        self._refresh_scan_stats()

    def _focus_region_scan_dict(self):
        """Full focus scan-region dict: an angled line (endpoints encode the
        rotation) crossed with a ZonePlateZ sweep.  ``xRange`` carries the true
        along-line length so the display's horizontal axis is line distance,
        while ``xStart/xStop/yStart/yStop`` carry the real angled endpoints the
        driver actually moves along."""
        fr = self._ensure_focus_region()
        xc, yc = self._line_center()
        L = fr['length']
        n = max(1, int(fr['points']))
        ar = np.radians(fr['angle'])
        ux, uy = np.cos(ar), np.sin(ar)
        # Half-pixel inset along the line direction (matches the Image convention).
        s0 = -(L / 2.0) + (L / (2.0 * n))
        s1 = (L / 2.0) - (L / (2.0 * n))
        zc, zr = fr['zCenter'], fr['zRange']
        zp = max(1, int(fr['zPoints']))
        zs = zr / zp if zp > 0 else 0.0
        return {
            'xCenter': xc, 'yCenter': yc,
            'xRange': L, 'yRange': abs(L * uy),
            'xPoints': n, 'yPoints': n,
            'xStep': L / n, 'yStep': abs(L * uy) / n if n else 0.0,
            'xStart': xc + s0 * ux, 'xStop': xc + s1 * ux,
            'yStart': yc + s0 * uy, 'yStop': yc + s1 * uy,
            'zCenter': zc, 'zRange': zr, 'zPoints': zp, 'zStep': zs,
            'zStart': zc - zr / 2.0 + zs / 2.0,
            'zStop': zc + zr / 2.0 - zs / 2.0,
        }

    def _recompute_energy_n(self):
        """N = round(|stop-start| / |step|) + 1, from the current Start/Stop/Step."""
        try:
            s = float(self._energy_fields['start'].text())
            e = float(self._energy_fields['stop'].text())
            st = float(self._energy_fields['step'].text() or 0)
            self._energy_fields['n'].setText(str(self._energy_n(s, e, st)))
        except ValueError:
            pass
        self._sync_active_energy_region()

    def _recompute_energy_step(self):
        """Step = |stop-start| / (N-1), from the user-edited N over the range."""
        try:
            s = float(self._energy_fields['start'].text())
            e = float(self._energy_fields['stop'].text())
            n = int(float(self._energy_fields['n'].text()))
        except ValueError:
            return
        n = max(1, n)
        self._energy_fields['n'].setText(str(n))
        span = abs(e - s)
        step = span / (n - 1) if n > 1 else 0.0
        self._energy_fields['step'].setText(f"{step:.4g}")
        self._sync_active_energy_region()

    # ── energy-region model ──────────────────────────────────────────────
    def _read_energy_fields(self):
        """Snapshot the field row into a region dict (missing/bad → safe defaults)."""
        def f(key, default):
            try:
                return float(self._energy_fields[key].text())
            except (ValueError, KeyError):
                return default
        start = f('start', 0.0)
        stop = f('stop', 0.0)
        step = f('step', 0.0)
        return {'start': start, 'stop': stop, 'step': step,
                'dwell': f('dwell', 1.0),
                'n': self._energy_n(start, stop, step)}

    def _load_energy_region(self, idx):
        """Load region ``idx`` into the field row and make it active."""
        if not (0 <= idx < len(self._energy_regions)):
            return
        self._active_energy_region = idx
        r = self._energy_regions[idx]
        self._energy_fields['start'].setText(f"{r['start']:g}")
        self._energy_fields['stop'].setText(f"{r['stop']:g}")
        self._energy_fields['step'].setText(f"{r['step']:g}")
        self._energy_fields['dwell'].setText(f"{r['dwell']:g}")
        self._energy_fields['n'].setText(str(r['n']))
        self._refresh_energy_strip()
        self._refresh_scan_stats()

    def _select_energy_region(self, idx):
        self._load_energy_region(idx)

    def _sync_active_energy_region(self):
        """Write the current field row back into the active region, then redraw."""
        if not getattr(self, '_energy_regions', None):
            return
        self._energy_regions[self._active_energy_region] = self._read_energy_fields()
        self._refresh_energy_strip()
        self._refresh_image_meta()
        self._refresh_scan_stats()

    def _add_energy_region(self):
        """Append a region continuing past the last one and make it active."""
        self._sync_active_energy_region()
        last = self._energy_regions[-1]
        step = last['step'] or 0.25
        start = last['stop']
        stop = start + max(step, 1.0) * 10
        self._energy_regions.append({
            'start': start, 'stop': stop, 'step': step,
            'dwell': last['dwell'], 'n': self._energy_n(start, stop, step)})
        self._load_energy_region(len(self._energy_regions) - 1)

    def _remove_energy_region(self):
        """Remove the active region (keeping at least one)."""
        if len(self._energy_regions) <= 1:
            return
        del self._energy_regions[self._active_energy_region]
        self._load_energy_region(min(self._active_energy_region,
                                     len(self._energy_regions) - 1))

    def _refresh_energy_strip(self):
        """Redraw the strip, axis, and summary from the region list."""
        if not getattr(self, '_energy_strip', None):
            return
        regs = self._energy_regions
        self._energy_strip.set_regions([
            {'start': r['start'], 'stop': r['stop'], 'n': r['n'],
             'active': i == self._active_energy_region}
            for i, r in enumerate(regs)])
        lo = min(r['start'] for r in regs)
        hi = max(r['stop'] for r in regs)
        for i, lbl in enumerate(self._energy_axis_lbls):
            e = lo + (hi - lo) * i / 3
            lbl.setText(f"{e:g} eV" if i == 3 else f"{e:g}")
        total = sum(r['n'] for r in regs)
        self._energy_summary_lbl.setText(
            f"{len(regs)} region{'s' if len(regs) != 1 else ''} · {total} pts")
        self._del_energy_btn.setEnabled(len(regs) > 1)

    def _on_error(self, msg):
        print(f"[dashboard] ERROR: {msg}")
        self.statusBar().showMessage(f"⚠  {msg}", 8000)

    def _on_status(self, msg):
        self.statusBar().showMessage(msg, 5000)

    # ── interactions ─────────────────────────────────────────────────────

    def _set_scanning(self, scanning):
        was_scanning = self._scanning
        self._scanning = bool(scanning)
        if self._scanning and not was_scanning:
            # Fresh scan: clear stale progress until the first time/frame arrives.
            self._elapsed_seconds = 0.0
            self._remaining_seconds = 0.0
            for k in ("Lines done", "Estimated time", "Elapsed time"):
                if k in getattr(self, "_progress_stats", {}):
                    self._progress_stats[k].setText("—")
            self.pct_lbl.setText("0%")
            self.progress.set_frac(0.0)
        if self._scanning:
            self.begin_btn.setText("Cancel scan")
            self.begin_btn.setObjectName("cancelScan")
        else:
            self.begin_btn.setText("Begin scan")
            self.begin_btn.setObjectName("beginScan")
        # No previewing mid-scan; restore it when idle (unless Focus mode).
        if getattr(self, "preview_btn", None):
            self.preview_btn.setEnabled(
                not self._scanning and not self._takes_over_image())
        # re-polish so the objectName-based style applies
        self.begin_btn.style().unpolish(self.begin_btn)
        self.begin_btn.style().polish(self.begin_btn)

    def _on_external_scan_started(self, scan_type):
        """A scan was started outside the Begin button — by the task agent, a
        remote script, or already running when the GUI attached.  The controller
        has already flipped its own ``scanning`` flag and is streaming data into
        the view; put the button into Cancel mode so the operator can still stop
        the scan (scan completion emits scan_state_changed(False), which restores
        the button via _set_scanning).  The scan-type combo is intentionally left
        untouched: retargeting it mid-scan would run _on_scan_type and tear down
        the region widgets / display while data is arriving."""
        self._set_scanning(True)

    def _toggle_expert(self):
        self._expert = not self._expert
        self.mode_btn.setText("Staff mode" if self._expert else "User mode")
        self.cmd_log.setVisible(self._expert)
        for wdg in self._staff_widgets:
            wdg.setVisible(self._expert)

    @staticmethod
    def _scan_is_focus(text):
        return "Focus" in text and "OSA" not in text

    @staticmethod
    def _scan_is_line_spectrum(text):
        return "Line Spectrum" in text

    def _is_line_scan(self):
        """True for the single-line scan families (Focus or Line Spectrum): both
        draw one line ROI on the sample image and take the display over with a
        streak, so they share the line-ROI + snapshot/restore machinery."""
        return (getattr(self, "_focus_mode", False)
                or getattr(self, "_ls_mode", False))

    def _is_single_motor(self):
        """A one-motor scan: displayed as a 1-D signal-vs-position curve rather
        than a 2-D image."""
        return (getattr(self, "_motor_scan_mode", False)
                and getattr(self, "_motor_axes", 0) == 1)

    def _takes_over_image(self):
        """True for every scan family that replaces the SampleX/SampleY image +
        ROI boxes with its own display (Focus / Line Spectrum streaks, or a
        motor scan in its own coordinate space) — the set that snapshots the
        sample display on entry and restores it on the way back to Image."""
        return self._is_line_scan() or getattr(self, "_motor_scan_mode", False)

    def _scan_cfg(self, text):
        """The scan.json entry for ``text`` from the connected client, or None
        (offline, or unknown scan type)."""
        client = getattr(self.controller, "client", None) if self.controller else None
        return (getattr(client, "scanConfig", None) or {}).get(text)

    def _scan_is_motor(self, text):
        """True when ``text`` is driven by a motor-scan driver (config-driven;
        falls back to the well-known names when offline)."""
        sc = self._scan_cfg(text)
        if sc is not None:
            return sc.get("driver") in self._MOTOR_DRIVERS
        return text in ("Single Motor", "Double Motor", "OSA Image")

    def _motor_axis_count(self, text):
        """1 for a single-motor scan, 2 for a double-motor scan."""
        sc = self._scan_cfg(text)
        if sc is not None:
            return 1 if sc.get("driver") in self._SINGLE_MOTOR_DRIVERS else 2
        return 1 if text == "Single Motor" else 2

    def _on_motor_selected(self, axis):
        """A motor dropdown changed: centre that axis on the motor's current
        position (a sensible default, like the Loop sequence widget) and refresh."""
        if not getattr(self, "_motor_axis_widgets", None):
            return
        ax = self._motor_axis_widgets[axis]
        name = ax["combo"].currentText()
        if name:
            ax["center"].setText(f"{self._current_motor_pos(name):.3f}")
        self._on_motor_edit()

    def _on_motor_edit(self, *_):
        """A motor Range/Points field changed: re-derive Step and refresh stats."""
        for ax in getattr(self, "_motor_axis_widgets", []):
            self._recompute_step(ax["range"], ax["npts"], ax["step"])
        self._refresh_scan_stats()

    def _on_scan_type(self, text):
        ptycho = "Ptycho" in text
        focus = self._scan_is_focus(text)
        ls = self._scan_is_line_spectrum(text)
        motor = self._scan_is_motor(text)
        # Mode readout: prefer the scan config's mode (point vs continuousLine),
        # falling back to the ptychography/continuous default when offline.
        sc = self._scan_cfg(text)
        self.mode_field.setText((sc or {}).get("mode")
                                or ("ptychography" if ptycho else "continuousLine"))
        was_takeover = self._takes_over_image()
        self._focus_mode = focus
        self._ls_mode = ls
        self._motor_scan_mode = motor
        self._motor_axes = self._motor_axis_count(text) if motor else 0
        line = self._is_line_scan()
        takeover = self._takes_over_image()
        # Per-family control groups: Focus Z (focus), Line (line scans), Motor
        # scan (motor scans).
        if getattr(self, "_focus_group", None):
            self._focus_group.setVisible(focus)
        if getattr(self, "_line_group", None):
            self._line_group.setVisible(line)
        if getattr(self, "_motor_group", None):
            self._motor_group.setVisible(motor)
        # Single-line / motor scans are one region — no multi-region add/remove.
        if getattr(self, "_add_region_btn", None):
            self._add_region_btn.setEnabled(not takeover)
        # Preview (first region, single energy) is meaningless for these.
        if getattr(self, "preview_btn", None):
            self.preview_btn.setEnabled(not takeover and not self._scanning)
        # Streak-display cursor axes: Focus draws Z up the y-axis; Line Spectrum
        # draws energy along the x-axis (position-along-line stays the y-axis);
        # motor scans keep plain X/Y (their own motor coordinates).
        if getattr(self, "_cursor_readout_keys", None):
            self._cursor_readout_keys["Y"].setText("Z" if focus else "Y")
            self._cursor_readout_keys["X"].setText("E" if ls else "X")
        # Focus-to-cursor is re-enabled by a click on the streak (see _on_cursor).
        fbtn = getattr(self, "_cursor_action_btns", {}).get("Focus to cursor")
        if fbtn is not None:
            fbtn.setEnabled(False)
        if takeover:
            # Switching directly between two take-over modes after one has run
            # leaves its frame in the viewer — put the sample image back first
            # (the held snapshot is the sample image).
            if (was_takeover and hasattr(self, "image_area")
                    and (self.image_area._focus_display
                         or self.image_area._plot_mode)):
                self.image_area.set_plot_mode(False)
                self.image_area.set_focus_display(False)
                if self._pre_focus_snapshot is not None:
                    self.image_area.restore(self._pre_focus_snapshot)
                    self._image_seeded = True
            # Entering a take-over mode: snapshot the sample image + region model
            # so leaving can restore it exactly.  Skip when already in one.
            if not was_takeover and hasattr(self, "image_area"):
                self._pre_focus_snapshot = self.image_area.snapshot()
                self._pre_focus_regions = (
                    [dict(r) for r in self._scan_regions],
                    self._active_region,
                    dict(self._spectrum_region) if self._spectrum_region else None)
            if line:
                self._ensure_focus_region()
                if focus:
                    # Live-refresh the Z centre to the current ZonePlateZ on entry.
                    self._focus_region['zCenter'] = self._current_motor_pos('ZonePlateZ')
                self._write_focus_fields()
            if motor:
                self._prefill_motor_axes(text)
            if hasattr(self, "image_area"):
                self.image_area.set_focus_display(False)  # neutral sample view
        else:
            self._last_image_scan_type = text
            self._restore_pre_focus_display()
        self._refresh_spatial_image(fit=True)
        self._refresh_image_meta()
        self._refresh_scan_stats()

    def _prefill_motor_axes(self, text):
        """Show the right number of motor axes and pre-select each from the scan
        config's x_motor / y_motor, centring each on its motor's live position.

        Lock rule (per axis): a motor named in the config (e.g. OSA Image's
        OSA_X/OSA_Y) pins that dropdown — the scan is *defined* on those motors;
        a null/empty config motor leaves the dropdown user-selectable (Single /
        Double Motor).  Only the motor selector locks — the center/range/points
        fields stay editable."""
        if not getattr(self, "_motor_axis_widgets", None):
            return
        sc = self._scan_cfg(text) or {}
        axes = self._motor_axis_count(text)
        defaults = [sc.get("x_motor"), sc.get("y_motor")]
        for i, ax in enumerate(self._motor_axis_widgets):
            ax["block"].setVisible(i < axes)
            if i >= axes:
                continue
            combo = ax["combo"]
            d = defaults[i]
            # A listed motor pins the dropdown, but only if it actually exists in
            # the motor list — otherwise (null/'' or an unknown name) stay editable.
            locked = bool(d) and combo.findText(d) >= 0
            if locked:
                combo.blockSignals(True)
                combo.setCurrentText(d)
                combo.blockSignals(False)
            combo.setEnabled(not locked)
            name = combo.currentText()
            if name:
                ax["center"].setText(f"{self._current_motor_pos(name):.3f}")
            self._recompute_step(ax["range"], ax["npts"], ax["step"])

    def _restore_pre_focus_display(self):
        """Leave focus: remove the ZonePlateZ streak and restore the sample image
        (re-centred) + the pre-focus region model.  Safe to call when there is
        nothing to restore."""
        if hasattr(self, "image_area"):
            had_takeover = (self.image_area._focus_display
                            or self.image_area._plot_mode)
            self.image_area.set_plot_mode(False)   # back to the image ViewBox
            self.image_area.set_focus_display(False)
            self.image_area.clear_line()
            if had_takeover and self._pre_focus_snapshot is not None:
                self.image_area.restore(self._pre_focus_snapshot)
                self._image_seeded = True
        # Undo any line-drag edits to the region model.
        if self._pre_focus_regions is not None:
            regs, active, spec = self._pre_focus_regions
            self._scan_regions = regs
            self._spectrum_region = spec
            if active == 'spectrum' and spec is not None:
                self._active_region = 'spectrum'
            elif isinstance(active, int) and 0 <= active < len(regs):
                self._active_region = active
            else:
                self._active_region = 0
            if isinstance(self._active_region, int):
                self._load_spatial_region(self._active_region)
            elif self._active_region == 'spectrum':
                self._load_spatial_region('spectrum')
            self._pre_focus_regions = None
        self._pre_focus_snapshot = None

    def _set_cmap(self, name):
        """Colormap pills load a gradient preset into the HistogramLUTWidget,
        which owns the LUT once bound to the ImageItem."""
        preset = {"gray": "grey", "viridis": "viridis", "inferno": "inferno"}[name]
        self.hist_lut.gradient.loadPreset(preset)
        self.image_area.set_roi_cmap(name)

    def _tick(self):
        self._t += 0.02
        # pulse the live detector dot
        op = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(self._t * 3))
        self.live_dot.setStyleSheet(
            f"color:{C['alert']};background:transparent;font-size:10px;"
            f"opacity:{op:.2f};")
        # scroll the DUMMY trace of the active point detector only in placeholder
        # mode; when connected, real monitor data drives it via _on_monitor_data.
        if self.controller is None:
            p = self._det_pages.get(self._active_det_key())
            if p and p.get("type") == "point" and p.get("trace") is not None:
                p["trace"] = np.roll(p["trace"], -1)
                p["trace"][-1] = 1 + (np.random.random() - .5) * .004
                p["curve"].setData(p["trace"])
                p["value"].setText(f"{p['trace'][-1]:.4f}")

    # ── controller slots (read-only live data) ──────────────────────────
    def _on_motor_position(self, name, pos):
        self._motor_info.setdefault(name, {})["last value"] = pos
        wd = self._motor_widgets.get(name)
        if wd:
            wd["value"].setText(f"{pos:.2f}")
            wd["bar"].set_state(self._frac(pos, wd["lo"], wd["hi"]), wd["bar"]._moving)
        if name == "Energy":
            self.energy_val.setText(f"{pos:.1f} eV")
            self._refresh_image_meta()

    def _on_motor_status(self, name, moving):
        wd = self._motor_widgets.get(name)
        if not wd:
            return
        color = C["motion"] if moving else C["text"]
        wd["value"].setStyleSheet(f"color:{color};background:transparent;")
        val = self._motor_info.get(name, {}).get("last value")
        wd["bar"].set_state(self._frac(val, wd["lo"], wd["hi"]), moving)

    def _place_line_spectrum_frame(self, image, im):
        """Draw a live line-spectrum frame as a streak: energy on the horizontal
        axis, position-along-line (the fast axis) on the vertical.  The server
        sends the frame as (n_energies, xPoints) with rows filled as each energy
        completes; we transpose it to (xPoints, n_energies) — row-major pyqtgraph
        maps rows→y (line position) and cols→x (energy).  Returns True on success.
        """
        frame = np.asarray(image, dtype=float)
        if frame.ndim != 2:
            return False
        disp = np.ascontiguousarray(frame.T)     # (position, energy)
        e_lo, e_hi, _ = self._ls_energy_span()
        e_center = (e_lo + e_hi) / 2.0
        e_span = max(abs(e_hi - e_lo), 1e-6)
        L = max(self._ensure_focus_region()['length'], 1e-6)
        key = str(im.get('scan_region_index', 'Region1'))
        # Position axis runs 0 → L (distance from the first endpoint).
        self.image_area.set_region_frame(key, disp, e_center, L / 2.0, e_span, L)
        if not getattr(self, '_focus_view_fitted', False):
            self.image_area.set_view(e_center, L / 2.0,
                                     e_span / 0.85, L / 0.85)
            self._focus_view_fitted = True
        return True

    def _place_single_motor_curve(self, image, im):
        """Draw a live single-motor frame as a 1-D signal-vs-position curve.  The
        server sends the frame as (1, xPoints); the x axis is the motor's position
        over the scan range.  Returns True on success."""
        frame = np.asarray(image, dtype=float)
        y = frame.ravel() if frame.ndim == 1 else \
            (frame[0] if frame.ndim == 2 and frame.shape[0] else None)
        if y is None or not y.size:
            return False
        xc, xr = im.get('x_center'), im.get('x_range')
        n = y.size
        if xc is not None and xr:
            x = np.linspace(xc - xr / 2.0, xc + xr / 2.0, n)
        else:
            x = np.arange(n, dtype=float)
        motor = (self._motor_axis_widgets[0]['combo'].currentText()
                 if getattr(self, "_motor_axis_widgets", None) else "")
        unit = self._motor_info.get(motor, {}).get("unit", "")
        x_label = f"{motor} ({unit})" if unit else (motor or "position")
        self.image_area.set_curve(x, y, x_label=x_label, y_label="signal")
        return True

    def _place_motor_frame(self, image, im):
        """Draw a live motor-scan frame in the two motors' coordinate space.  A
        double-motor scan is a normal 2-D image (yPoints × xPoints); a single-
        motor scan is a 1×N strip with no y extent, so give it a nominal height
        so the row is visible.  Returns True on success."""
        frame = np.asarray(image, dtype=float)
        if frame.ndim != 2:
            return False
        xc, yc = im.get('x_center'), im.get('y_center')
        xr, yr = im.get('x_range'), im.get('y_range')
        if xc is None or not xr:
            return False
        if not yr:                              # single-motor: no y extent
            yc = yc or 0.0
            yr = abs(xr) * 0.1 or 1.0
        key = str(im.get('scan_region_index', 'Region1'))
        self.image_area.set_region_frame(key, frame, xc, yc, xr, yr)
        if not getattr(self, '_focus_view_fitted', False):
            self.image_area.set_view(xc, yc, max(abs(xr), 1e-6) / 0.85,
                                     max(abs(yr), 1e-6) / 0.85)
            self._focus_view_fitted = True
        return True

    def _on_image(self, image):
        try:
            # The server tags each frame's region + physical geometry on the
            # image model (the image_updated payload is only the bare array);
            # route each region's frame to its own physical extent so multi-
            # region scans mosaic instead of stacking in Region1.
            placed = False
            if self.controller is not None:
                im = self.controller.get_image_model()
                if self._ls_mode:
                    # Line Spectrum: the frame is (n_energies, xPoints).  The image
                    # model geometry describes the SPATIAL line, not the streak we
                    # want, so place it ourselves: transpose to (position, energy)
                    # so the fast line axis is vertical and energy horizontal.
                    placed = self._place_line_spectrum_frame(image, im)
                elif self._is_single_motor():
                    # Single motor: 1-D signal-vs-position curve, not an image.
                    placed = self._place_single_motor_curve(image, im)
                elif getattr(self, "_motor_scan_mode", False):
                    # Double motor: a normal 2-D image in the two motors' space.
                    placed = self._place_motor_frame(image, im)
            if not placed and self.controller is not None \
                    and not self._ls_mode and not getattr(self, "_motor_scan_mode", False):
                xc, yc = im.get('x_center'), im.get('y_center')
                xr, yr = im.get('x_range'), im.get('y_range')
                if xr and yr and xc is not None and yc is not None:
                    key = str(im.get('scan_region_index', 'Region1'))
                    self.image_area.set_region_frame(key, image, xc, yc, xr, yr)
                    placed = True
                    # Focus places its streak in ZonePlateZ space, far from the
                    # sample view — fit the view to that extent once.
                    if self._focus_mode and not getattr(self, '_focus_view_fitted', False):
                        self.image_area.set_view(xc, yc, max(abs(xr), 1e-6) / 0.85,
                                                 max(abs(yr), 1e-6) / 0.85)
                        self._focus_view_fitted = True
            if not placed:
                self.image_area.set_primary_frame(image)
            self._image_seeded = True
            # During a scan the beamline energy is stepped by the server and no
            # motorPositions message is sent, so drive the header energy readout
            # from the current frame's energy instead.
            if self.controller is not None:
                e = self.controller.get_image_model().get('current_energy')
                if isinstance(e, (int, float)):
                    self.energy_val.setText(f"{float(e):.1f} eV")
        except Exception:
            pass
        # Each frame also refreshes the live-detector CCD panel from the per-detector
        # frames the controller stored on the image model.
        self._refresh_ccd()
        # …and advances the per-image line counter (line_index just updated).
        if self._scanning:
            self._refresh_scan_progress()

    def _ccd_channel_key(self):
        """DAQ channel whose data is a 2-D frame (the area detector / CCD), from
        daqConfig; cached.  None when no image-type DAQ is configured."""
        if hasattr(self, "_ccd_key"):
            return self._ccd_key
        self._ccd_key = None
        client = getattr(self.controller, "client", None)
        for k, val in (getattr(client, "daqConfig", {}) or {}).items():
            if isinstance(val, dict) and val.get("type") == "image":
                self._ccd_key = k
                break
        return self._ccd_key

    def _refresh_ccd(self):
        """Update every image-type detector page with its latest area-detector
        frame.

        Idle: the controller stashes each idle-monitor frame under
        'latest_monitor_frames' (the trace only keeps the scalar sum).
        Scanning: the per-detector frames live under 'all_detector_images'.
        """
        if self.controller is None or not getattr(self, "_det_pages", None):
            return
        try:
            im = self.controller.get_image_model()
            mon = im.get("latest_monitor_frames") or {}
            allimg = im.get("all_detector_images") or {}
        except Exception:
            return
        for key, p in self._det_pages.items():
            if p.get("type") != "image":
                continue
            frame = mon.get(key)
            if not (isinstance(frame, np.ndarray) and frame.ndim >= 2):
                frame = allimg.get(key)
            if not (isinstance(frame, np.ndarray) and frame.ndim >= 2):
                continue
            # Log-scale for display (diffraction has huge dynamic range), as the
            # classic viewer does; autorange levels on the first real frame.
            disp = np.log1p(np.clip(frame.astype(float), 0, None))
            p["img"].setImage(disp, autoLevels=not p["seeded"])
            p["seeded"] = True
            # Caption reflects the real frame: dimensions + total counts.
            h, w = frame.shape[:2]
            p["dims_lbl"].setText(f"{h}² · log" if h == w else f"{h}×{w} · log")
            p["sum_lbl"].setText(f"Σ {float(np.sum(frame)):.1e}")

    def _on_shutter(self, mode):
        """Server reported a gate mode → sync the shutter selector to it without
        re-issuing a command (blockSignals)."""
        idx = self._SHUTTER_MODE_TO_INDEX.get(str(mode).lower())
        if idx is None or not hasattr(self, "shutter_combo"):
            return
        if self.shutter_combo.currentIndex() != idx:
            self.shutter_combo.blockSignals(True)
            self.shutter_combo.setCurrentIndex(idx)
            self.shutter_combo.blockSignals(False)
        self._set_shutter_led(idx)

    def _on_daq_value(self, value):
        """Selected-channel scalar → the active (point/spectrum) detector's
        current-value readout."""
        p = self._det_pages.get(self._active_det_key()) if getattr(
            self, "_det_pages", None) else None
        if p and p.get("type") != "image" and p.get("value") is not None:
            p["value"].setText(f"{value:.4f}")

    def _on_monitor_data(self):
        """Refresh every point/spectrum detector trace from the image model's
        monitor buffer (keyed by DAQ config key, with a name fallback)."""
        try:
            data = self.controller.get_image_model().get("monitor_data") or {}
        except Exception:
            data = {}
        for key, p in (getattr(self, "_det_pages", {}) or {}).items():
            if p.get("type") == "image":
                continue
            series = data.get(key)
            if series is None:
                series = data.get(p.get("name"))
            if series is None:
                continue
            try:
                arr = np.asarray(series, dtype=float).ravel()
            except Exception:
                continue
            if not arr.size:
                continue
            p["curve"].setData(arr)
            if p.get("type") != "spectrum" and p.get("value") is not None:
                p["value"].setText(f"{arr[-1]:.4f}")
        # Idle CCD frames also arrive on this signal (the trace keeps only the sum).
        self._refresh_ccd()

    def _on_progress_text(self, text):
        if hasattr(self, "progress_caption"):
            self.progress_caption.setText(text)

    def _on_est_time(self, seconds):
        # The controller emits *remaining* time; total = elapsed + remaining.
        self._remaining_seconds = float(seconds)
        self._refresh_scan_progress()

    def _on_elapsed_time(self, seconds):
        self._elapsed_seconds = float(seconds)
        self._refresh_scan_progress()

    @staticmethod
    def _fmt_mmss(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60:d}:{seconds % 60:02d}"

    def _refresh_scan_progress(self):
        """Update the whole-scan progress from elapsed/remaining time (the server
        derives remaining from completed/total lines, so elapsed/total equals the
        overall line fraction across every energy and region) plus per-image line
        progress from the image model."""
        elapsed = getattr(self, "_elapsed_seconds", 0.0)
        remaining = getattr(self, "_remaining_seconds", 0.0)
        total = elapsed + remaining
        frac = elapsed / total if total > 0 else 0.0
        if hasattr(self, "progress"):
            self.progress.set_frac(frac)
        if hasattr(self, "pct_lbl"):
            self.pct_lbl.setText(f"{round(frac * 100)}%")
        if hasattr(self, "progress_time_lbl"):
            self.progress_time_lbl.setText(
                f"{self._fmt_mmss(elapsed)} / {self._fmt_mmss(total)}")
        stats = getattr(self, "_progress_stats", {})
        if "Estimated time" in stats:
            stats["Estimated time"].setText(
                self._fmt_mmss(total) if total > 0 else "—")
        if "Elapsed time" in stats:
            stats["Elapsed time"].setText(
                self._fmt_mmss(elapsed) if elapsed > 0 else "—")
        # Per-image line progress (resets each image/energy on the server).
        if "Lines done" in stats and self.controller is not None:
            try:
                im = self.controller.get_image_model()
                li = im.get("line_index")
                ny = im.get("y_points")
                if not ny:
                    arr = getattr(self.image_area.img, "image", None)
                    ny = (arr.shape[0] if isinstance(arr, np.ndarray)
                          and arr.ndim >= 2 else None)
                if li is not None and ny:
                    stats["Lines done"].setText(f"{int(li) + 1} / {int(ny)}")
            except Exception:
                pass

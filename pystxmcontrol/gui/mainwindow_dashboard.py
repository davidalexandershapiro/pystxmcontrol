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
)
from PySide6.QtGui import QPixmap, QImage, QColor, QFont
from PySide6.QtCore import Qt, QTimer, QRectF, Signal

import pyqtgraph as pg

from pystxmcontrol.gui.dashboard_theme import (
    C, MONO_FAMILY, SANS_FAMILY, build_stylesheet, make_lut, roi_colors,
    mono_font, sans_font, TravelBar, ProgressBar, EnergyRegionStrip,
    HistColorBar,
)

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")

pg.setConfigOptions(antialias=True, imageAxisOrder="row-major", background=C["plot_ground"])


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
        self.field = _absorption_field()
        self.img = pg.ImageItem()
        self.img.setImage((1 - self.field))          # absorption → display
        self.img.setLookupTable(make_lut(self._cmap))
        self.img.setZValue(0)
        self.vb.addItem(self.img)
        # The image data occupies a physical µm extent (the scanned region);
        # the *view* is a wider field-of-view around it.  Both default to a
        # placeholder and are set once regions exist.
        self.img.setRect(QRectF(-6.0, -6.0, 12.0, 12.0))
        self.vb.autoRange(padding=0)

        # Live scan data is a spatial mosaic: one ImageItem per scan region,
        # each positioned at its own physical extent (mirrors the classic GUI).
        # The first region reuses self.img (the histogram-bound primary); the
        # rest are secondary tiles kept in LUT/levels sync with it.
        self._region_images = {}      # region key -> ImageItem
        self._seeded_regions = set()  # regions that have auto-levelled once
        self._primary_seeded = False

        # Region ROI boxes, keyed by caller string.  _suppress guards against
        # our own programmatic geometry writes re-emitting change signals;
        # _dragging holds the key of a box under active interactive drag.
        self._roi_items = {}          # key -> {'roi': RectROI, 'label': TextItem}
        self._suppress = False
        self._dragging = None

        # scan line (tracks current row) — repositioned by set_view
        self.scan_line = pg.InfiniteLine(pos=0.0, angle=0, movable=False,
                                         pen=pg.mkPen(C["accent"], width=2))
        self.scan_line.setZValue(5)
        self.vb.addItem(self.scan_line)

        # overlay labels (children of self, positioned in resizeEvent)
        self.scalebar = QFrame(self)
        self.scalebar.setStyleSheet("background:#ffffff;border:none;")
        self.scalebar.setFixedSize(120, 3)
        self.scalebar_lbl = QLabel("2 µm", self)
        self.scalebar_lbl.setFont(mono_font(9))
        self.scalebar_lbl.setStyleSheet("color:#fff;background:transparent;")
        self.meta = QLabel(
            "Spiral Image · channel default\n"
            "pixel 0.100 µm · dwell 2.0 ms\n"
            "705.0 eV · circ. polarization", self)
        self.meta.setFont(mono_font(8))
        self.meta.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.meta.setStyleSheet("color:rgba(255,255,255,.72);background:transparent;")

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
        scanned over — so pixels land under the ROI box that defines them."""
        self.img.setRect(QRectF(xc - width / 2.0, yc - height / 2.0,
                                width, height))

    def set_view(self, xc, yc, width, height):
        """Set the visible field-of-view (µm) centred at (xc, yc)."""
        pad = 0.08
        self.vb.setRange(
            QRectF(xc - width / 2.0 * (1 + pad), yc - height / 2.0 * (1 + pad),
                   width * (1 + pad), height * (1 + pad)),
            padding=0)
        self.scan_line.setValue(yc)

    # ── live scan data (per-region mosaic) ───────────────────────────────
    def set_primary_frame(self, data):
        """Fallback for frames with no region geometry — draw on the primary
        item at its current rect (auto-levels only the first time)."""
        self.img.setImage(data, autoLevels=not self._primary_seeded)
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
        item.setRect(QRectF(xc - xr / 2.0, yc - yr / 2.0, xr, yr))
        if item is not self.img:
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

    def resizeEvent(self, e):
        self.glw.setGeometry(0, 0, self.width(), self.height())
        m = 16
        self.scalebar.move(m, self.height() - m - 20)
        self.scalebar_lbl.move(m, self.height() - m - 16)
        self.meta.adjustSize()
        self.meta.move(self.width() - self.meta.width() - m, m)
        for w in (self.scalebar, self.scalebar_lbl, self.meta):
            w.raise_()
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
        self._motor_group_index = 0     # 0 = Microscope, 1 = Beamline
        self._expert = True
        self._staff_widgets = []          # widgets shown only in Staff mode
        self._motor_widgets = {}          # name -> {value,bar,lo,hi} for live updates
        self._image_seeded = False
        self._ccd_seeded = False

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

        # light "live" animation.  When connected, the counter trace is driven by
        # real monitor data, so only the live-detector dot keeps pulsing.
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(66)

        self.resize(2000, 1200)

    def closeEvent(self, event):
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

    # Scan drivers whose configuration the dashboard's Spatial(SampleX/SampleY) +
    # Energy tabs can compile.  Other scan types (focus, line, single/double motor,
    # OSA, spiral) report "not yet supported" until their panels are wired.
    _SUPPORTED_SCAN_DRIVERS = {"linear_image", "derived_ptychography_image"}

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

    def _maybe_connect_controller(self, live):
        """Return a connected MainController, or None (placeholder mode).

        We probe the command port with a short socket timeout first: the client
        blocks in its constructor on get_config, so building it against an absent
        server would hang the GUI.  Only build it when a server answers."""
        if not live:
            return None
        try:
            with open(os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json")) as f:
                srv = json.load(f).get("server", {})
            addr = srv.get("stxm_address", "127.0.0.1")
            if addr in ("*", "0.0.0.0", "::"):
                addr = "127.0.0.1"
            port = int(srv.get("command_port"))
        except Exception:
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

    def _connect_controller_signals(self):
        c = self.controller
        c.motor_position_updated.connect(self._on_motor_position)
        c.motor_status_updated.connect(self._on_motor_status)
        c.image_updated.connect(self._on_image)
        c.scan_state_changed.connect(self._set_scanning)
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

    def _panel_of(self, d):
        """Group a motor.  Prefer the explicit `panel` field; fall back to a
        driver rule so the panel still works before the server config carries it."""
        p = d.get("panel")
        if p in ("microscope", "beamline", "hidden"):
            return p
        return "beamline" if d.get("driver") in ("bcsMotor", "derivedEnergy") \
            else "microscope"

    def _motors_sorted(self):
        return sorted(self._motor_info.items(), key=lambda kv: kv[1].get("index", 999))

    def _motor_rows(self, panel):
        """Return row tuples (name, kind, pos, unit, frac, moving) for a panel,
        sourced from motor.json (`panel`/`unit` fields), sorted by index."""
        rows = []
        for name, d in self._motors_sorted():
            if self._panel_of(d) != panel:
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
        sh, self.shutter_val = readout("Shutter", "OPEN · auto", role="ok")
        hl.addWidget(self._vline()); hl.addWidget(sh)

        # server status
        hl.addWidget(self._vline())
        srv = QWidget()
        sv = QHBoxLayout(srv)
        sv.setContentsMargins(20, 0, 20, 0)
        sv.setSpacing(9)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{C['ok']};background:transparent;font-size:11px;")
        sv.addWidget(dot)
        sbox = QVBoxLayout()
        sbox.setSpacing(1)
        sbox.addWidget(self._label("stxmserver", font=sans_font(10, QFont.Medium)))
        sbox.addWidget(self._label("131.243.191.90:9999", role="monoFaint"))
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

    # ── acquisition view (3-column body) ─────────────────────────────────
    def _build_acquisition_view(self):
        body = QWidget()
        body.setStyleSheet(f"background:{C['canvas']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(10)
        col1 = self._build_col1(); col1.setFixedWidth(430)
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
                                     "Line Spectrum", "Tomography", "Focus", "OSA Image"])
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
        grid, _ = self._grid4([("Center", "-118.400", False), ("Range", "40.000", False),
                               ("Points", "41", False), ("Step µm", "1.000", True)])
        gv.addLayout(grid)
        r = QHBoxLayout()
        b = QPushButton("Set center to current"); b.setProperty("role", "small")
        r.addWidget(b)
        cb = QCheckBox("move to best focus"); cb.setChecked(True)
        r.addWidget(cb); r.addStretch(1)
        gv.addLayout(r)
        # Zone-plate focus calibration (from the Energy motor's A0/A1). A0 sets the
        # focus offset (shown to all); A1 is the slope coefficient (staff-only).
        energy = self._motor_info.get("Energy", {})
        zp = QGridLayout()
        zp.setHorizontalSpacing(6)
        zp.setVerticalSpacing(4)
        zp.addWidget(self._label("Zone Plate A0", role="microLabel"), 0, 0)
        zp.addWidget(self._field(f"{float(energy.get('A0', 0.0)):.4f}"), 1, 0)
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
        grid, _ = self._grid4([("Length µm", "10.000", False), ("Angle °", "0.0", False),
                               ("Points", "100", False), ("Step µm", "0.100", True)])
        gv.addLayout(grid)
        r = QHBoxLayout()
        b = QPushButton("Draw line on image"); b.setProperty("role", "small")
        r.addWidget(b)
        r.addWidget(self._label("from (-320.0, 166.0) → (-310.0, 166.0)", role="monoFaint"))
        r.addStretch(1)
        gv.addLayout(r)
        iv.addWidget(w)

        # Loop sequence
        w, gv = self._group_box("Loop sequence", "outer motor loop")
        lbl = self._label("MOTOR", role="microLabel")
        gv.addWidget(lbl)
        combo = QComboBox()
        combo.addItems([name for name, _ in self._motors_sorted()])
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
        for lbl, val in (("X", "-312.4"), ("Y", "168.1"), ("I", "4218"), ("OD", "0.34")):
            cur = QHBoxLayout()
            cur.setSpacing(6)
            k = self._label(lbl, font=mono_font(11), color=C["text_dim"])
            val_l = self._label(val, font=mono_font(11), color=C["text"])
            cur.addWidget(k); cur.addWidget(val_l)
            fv.addLayout(cur)
        fv.addStretch(1)
        for name in ("Set cursor to 0", "Move to cursor", "Focus to cursor"):
            b = QPushButton(name); b.setProperty("role", "small")
            fv.addWidget(b)
        cl.addWidget(footer)
        return card

    def _build_bottom_strip(self):
        strip = QWidget()
        strip.setFixedHeight(214)
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(10)

        # spectrum
        spec_card, spec_body = self._card("Spectrum · ROI 1", "Fe L3 · OD vs eV")
        self._note_lbl.setProperty("role", "accent")
        pw = pg.PlotWidget()
        pw.setBackground(C["plot_ground"])
        pw.showGrid(x=True, y=True, alpha=0.15)
        pw.getAxis("bottom").setPen(C["border"])
        pw.getAxis("left").setPen(C["border"])
        pw.getAxis("bottom").setTextPen(C["text_faint"])
        pw.getAxis("left").setTextPen(C["text_faint"])
        e, od = _spectrum()
        pw.plot(e[:82], od[:82], pen=pg.mkPen(C["accent"], width=2))
        cursor = pg.InfiniteLine(pos=e[81], angle=90,
                                 pen=pg.mkPen(QColor(95, 212, 214, 90), width=1))
        pw.addItem(cursor)
        spec_body.addWidget(pw, 1)
        sl.addWidget(spec_card, 135)

        # scan progress
        prog_card, prog_body = self._card("Scan progress", "12:47 / 18:24")
        self.progress_time_lbl = self._note_lbl      # header "elapsed / est"
        content = QWidget()
        pv = QVBoxLayout(content)
        pv.setContentsMargins(14, 14, 14, 14)
        pv.setSpacing(12)
        top = QHBoxLayout()
        self.progress_caption = self._label("Energy point 82 / 121",
                                             font=sans_font(10), color=C["text_dim"])
        top.addWidget(self.progress_caption)
        top.addStretch(1)
        self.pct_lbl = self._label("68%", role="value")
        top.addWidget(self.pct_lbl)
        pv.addLayout(top)
        self.progress = ProgressBar(0.68)
        pv.addWidget(self.progress)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        stats = [("Lines done", "82 / 120", "value"), ("Frames written", "9 840", "value"),
                 ("Missed triggers", "0", "ok"), ("Data rate", "412 MB/s", "value")]
        for i, (lbl, val, role) in enumerate(stats):
            r, c = divmod(i, 2)
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(self._label(lbl.upper(), role="fieldLabel"))
            v_ = self._label(val, role=role)
            v_.setFont(mono_font(14))
            box.addWidget(v_)
            grid.addLayout(box, r, c)
        pv.addLayout(grid)
        prog_body.addWidget(content, 1)
        sl.addWidget(prog_card, 100)
        return strip

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
        # add pill group + live status into the header
        det_well, self.det_btns = self._segmented(["fCCD", "Counter1"], 0)
        card._header_layout.insertWidget(1, det_well)
        card._header_layout.insertSpacing(2, 12)
        self.live_dot = QLabel("●")
        self.live_dot.setStyleSheet(f"color:{C['alert']};background:transparent;font-size:10px;")
        card._header_layout.addWidget(self.live_dot)
        self.det_status = self._label("48 fps · fCCD 1k", role="mono")
        self.det_status.setFont(mono_font(10))
        card._header_layout.addWidget(self.det_status)

        wrap = QWidget()
        wrap.setFixedHeight(268)
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(14, 14, 14, 14)
        self.det_stack = QStackedWidget()
        self.det_stack.addWidget(self._ccd_page())
        self.det_stack.addWidget(self._counter_page())
        wl.addWidget(self.det_stack)
        body.addWidget(wrap)

        def switch(i):
            self.det_stack.setCurrentIndex(i)
            self.det_status.setText("48 fps · fCCD 1k" if i == 0 else "500 Hz · Counter1")
        det_well._group.idClicked.connect(switch)
        return card

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

    def _ccd_page(self):
        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(6)
        glw = pg.GraphicsLayoutWidget()
        glw.setBackground("#000000")
        vb = glw.addViewBox()
        vb.setAspectLocked(True)
        vb.invertY(True)
        # Seeded with a placeholder frame; replaced by live area-detector frames
        # (see _refresh_ccd) once a scan with an image-type DAQ is running.
        self.ccd_img = pg.ImageItem(_diffraction())
        self.ccd_img.setLookupTable(make_lut("inferno"))
        vb.addItem(self.ccd_img)
        self.ccd_vb = vb
        vb.autoRange(padding=0)
        left.addWidget(glw, 1)
        cap = QHBoxLayout()
        self.ccd_dims_lbl = self._label("256² · log", role="monoFaint")
        self.ccd_sum_lbl = self._label("Σ 1.9e6", role="monoFaint")
        cap.addWidget(self.ccd_dims_lbl)
        cap.addStretch(1)
        cap.addWidget(self.ccd_sum_lbl)
        left.addLayout(cap)
        h.addLayout(left, 1)

        chips = QVBoxLayout()
        chips.setSpacing(8)
        chips.addWidget(self._chip("Exposure", "20.0 ms · 1:8"))
        chips.addWidget(self._chip("Max pixel", "6 214 adu"))
        chips.addWidget(self._chip("Sat. pixels", "0.02 %"))
        chips.addWidget(self._chip("Dropped", "0 frames", ok=True))
        chips.addStretch(1)
        cw = QWidget(); cw.setFixedWidth(178); cw.setLayout(chips)
        h.addWidget(cw)
        return page

    def _counter_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(9)
        top = QHBoxLayout()
        top.addWidget(self._label("Counter1 monitor · 53230A", role="fieldLabel"))
        top.addStretch(1)
        self.counts_lbl = self._label("1.0002", role="ok")
        self.counts_lbl.setFont(mono_font(11))
        top.addWidget(self.counts_lbl)
        v.addLayout(top)

        # Exponent shown once above the plot (SciAxis reports it) so the y tick
        # labels stay a compact one-decimal mantissa instead of full magnitudes.
        exp_row = QHBoxLayout()
        exp_row.setContentsMargins(0, 0, 0, 0)
        self.trace_exp_lbl = self._label("", role="monoFaint")
        exp_row.addWidget(self.trace_exp_lbl)
        exp_row.addStretch(1)
        v.addLayout(exp_row)

        left_axis = SciAxis(orientation="left")
        left_axis.on_exp_changed = lambda e: self.trace_exp_lbl.setText(_exp_str(e))
        self.trace_plot = pg.PlotWidget(axisItems={"left": left_axis})
        self.trace_plot.setBackground(C["plot_ground"])
        self.trace_plot.showGrid(x=False, y=True, alpha=0.2)
        self.trace_plot.enableAutoRange("y", True)
        pi = self.trace_plot.getPlotItem()
        # Full bounding box: draw all four axes; only left/bottom carry tick values.
        pi.showAxis("top"); pi.showAxis("right")
        pi.getAxis("top").setStyle(showValues=False)
        pi.getAxis("right").setStyle(showValues=False)
        for ax in ("left", "bottom", "top", "right"):
            pi.getAxis(ax).setPen(C["border"])
            pi.getAxis(ax).setTextPen(C["text_faint"])
        # Let the left axis auto-size to its labels — a fixed narrow width cropped
        # multi-decimal near-1.0 labels (e.g. "0.9987"); the exponent factoring
        # already keeps large-magnitude labels short.
        self._trace = 1 + (np.random.default_rng(4).random(220) - .5) * .004
        self.trace_curve = self.trace_plot.plot(
            self._trace, pen=pg.mkPen(C["ok"], width=1.4))
        v.addWidget(self.trace_plot, 1)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        for lbl, val in (("I₀ norm", "0.9987"), ("σ / mean", "0.11 %"),
                         ("Window", "10 s"), ("Gate", "2.0 ms")):
            chips.addWidget(self._chip(lbl, val))
        v.addLayout(chips)
        return page

    def _build_motors(self):
        card, body = self._card("Motors")
        grp_well, _ = self._segmented(["Microscope", "Beamline"], 0)
        card._header_layout.addWidget(grp_well)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.motor_inner = QWidget()
        self.motor_layout = QVBoxLayout(self.motor_inner)
        self.motor_layout.setContentsMargins(0, 0, 0, 0)
        self.motor_layout.setSpacing(0)

        self._micro = self._motor_rows("microscope")
        self._beam = self._motor_rows("beamline")
        self.motor_layout.addStretch(1)
        self._populate_motors(self._micro)
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
        jm = self.jogmove_btn; mp = QPushButton("Motor panel")
        stop = QPushButton("Stop all"); stop.setObjectName("stopAll")
        # Inactive until a server-side motor-stop command exists (none in the
        # current protocol).  Kept visible for layout; wired later.
        stop.setEnabled(False)
        stop.setToolTip("Motor stop not yet implemented (pending a server-side "
                        "stop command).")
        self.stop_all_btn = stop
        btns.addWidget(jm, 1); btns.addWidget(mp, 1); btns.addWidget(stop)
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
            # Per-row action cell, driven by _move_mode (toggled by "Jog / Move"):
            #  - Move mode: field holds an ABSOLUTE destination (pre-filled with the
            #    current position); a "Move" button (or Enter) commits move_motor().
            #  - Jog mode: field holds a RELATIVE step (pre-filled with a small default);
            #    − / + jog by that amount via jog_motor().
            fill = pos if self._move_mode else f"{self._jog_step(name):g}"
            tgt = self._field(fill, align_right=True)
            tgt.setFixedWidth(84)
            tgt.setStyleSheet("font-size:11px;padding:5px 7px;")
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
        panel = "microscope" if self._motor_group_index == 0 else "beamline"
        self._populate_motors(self._motor_rows(panel))

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
    #  Agent view
    # ════════════════════════════════════════════════════════════════════
    _LOG_FILTERS = ["All", "Scans", "Comments", "Errors", "Attachments"]
    _LOG_ENTRIES = [
        ("14:04", "Scans", "SCAN", "#5fd4d6", "NS_260809056.stxm",
         "Spiral Image · 20 × 20 µm · 100 nm · 705.5 eV · dwell 1.0 ms. "
         "Completed in 03:12.",
         "ZonePlateZ 1204.85 µm · ring 499.6 mA · queued by task agent", 56, "Spiral Image"),
        ("13:58", "Errors", "ANOMALY", "#ffc45e", "fCCD column dropout",
         "Intelligence agent flagged lines 46–49 of frame 3184. Values "
         "interpolated in preview, raw frames preserved.",
         "detector.fccd · severity warn · auto-logged", None, None),
        ("13:51", "Comments", "OPERATOR", "#8ee06a", "Sample NiFe_ox_04",
         "Particle field looks cleaner after the nitrogen purge. Using the "
         "lower-left quadrant for the rest of the shift.", "j.chen", None, None),
        ("13:44", "Attachments", "FIGURE", "#b79bf0",
         "Fe L₃ OD spectrum, ROI 1 vs ROI 2",
         "Attached from Analysis. Pre-edge subtracted, aligned stack, 12 energies.",
         "analysis/od_roi_compare.png · 121 pts · 700.0–705.5 eV", 12, "Spiral Stack"),
        ("13:30", "Scans", "SCAN", "#5fd4d6", "NS_260809053.stxm",
         "Focus · ZonePlateZ 1198–1212 µm · 41 points. Best focus 1204.85 µm.",
         "applied to microscope · Δ +1.35 µm", None, None),
        ("13:22", "Errors", "INTERLOCK", "#e08b8b", "Shutter interlock trip",
         "Endstation shutter closed on vacuum transient. Scan NS_260809052 "
         "aborted at line 88 of 120.", "cleared 13:24 · partial file kept", None, None),
        ("13:15", "Comments", "OPERATOR", "#8ee06a", "Shift start",
         "Beamline handed over from morning group. Grating 1200 l/mm, "
         "exit slit 30 µm.", "j.chen", None, None),
        ("13:12", "Scans", "SCAN", "#5fd4d6", "NS_260809051.stxm",
         "Focus · coarse pass to find the zone plate. 61 points, 2.0 ms dwell.",
         "ZonePlateZ 1190–1220 µm", 51, "Focus"),
    ]

    def _build_agent_view(self):
        self._plan_state = "pending"
        self._log_filter = "All"

        body = QWidget()
        body.setStyleSheet(f"background:{C['canvas']};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(10, 10, 10, 10)
        bl.setSpacing(10)
        left = self._agent_left_col()
        right = self._agent_logbook_col(); right.setFixedWidth(880)
        bl.addWidget(left, 1)
        bl.addWidget(right)

        self._render_logbook()
        return body

    def _agent_left_col(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(self._agent_status_strip())
        v.addWidget(self._agent_conversation(), 1)
        return col

    def _agent_status_strip(self):
        card = QFrame()
        card.setObjectName("card")
        h = QHBoxLayout(card)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        def half(dot_color, pulse, name, name_color, subline, status, status_role):
            w = QWidget()
            g = QHBoxLayout(w)
            g.setContentsMargins(16, 13, 16, 13)
            g.setSpacing(10)
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{dot_color};background:transparent;font-size:11px;")
            g.addWidget(dot, 0, Qt.AlignTop)
            box = QVBoxLayout(); box.setSpacing(2)
            nm = self._label(name, font=sans_font(12, QFont.DemiBold),
                             color=name_color)
            box.addWidget(nm)
            box.addWidget(self._label(subline, role="monoFaint"))
            bw = QWidget(); bw.setLayout(box)
            g.addWidget(bw, 1)
            chip = self._label(status, role=status_role)
            chip.setFont(mono_font(10))
            if status_role == "approvalChip":
                chip.setStyleSheet(
                    f"color:{C['accent']};background:#0f2a2b;"
                    f"border:1px solid #1f4b4c;border-radius:4px;padding:3px 8px;")
            else:
                chip.setStyleSheet(f"color:{C['motion']};background:transparent;")
            g.addWidget(chip, 0, Qt.AlignTop)
            return w, dot

        left, self._ta_dot = half(
            C["ok"], True, "Task agent", C["text"],
            "operator-facing · proposes, you approve",
            "APPROVAL REQUIRED", "approvalChip")
        h.addWidget(left, 1)
        h.addWidget(self._vline())
        right, _ = half(
            C["motion"], False, "Intelligence agent", C["text_2"],
            "hardware-side · advises the task agent",
            "1 anomaly · 14 ms latency", "warnChip")
        h.addWidget(right, 1)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        return card

    def _agent_conversation(self):
        card, cbody = self._card("Conversation")
        sess = self._label("session 042 · NiFe_ox_04", role="monoFaint")
        card._header_layout.insertWidget(1, sess)
        card._header_layout.insertSpacing(2, 10)
        for name in ("Transcript", "Clear"):
            b = QPushButton(name); b.setProperty("role", "small")
            card._header_layout.addWidget(b)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self._conv_layout = QVBoxLayout(inner)
        self._conv_layout.setContentsMargins(20, 18, 20, 18)
        self._conv_layout.setSpacing(16)

        # session-start divider
        div = QHBoxLayout()
        div.addStretch(1)
        chip = self._label("14:02 · session started", role="monoFaint")
        chip.setStyleSheet(
            f"color:{C['text_faint']};background:{C['panel_footer']};"
            f"border:1px solid {C['border']};border-radius:20px;padding:3px 12px;")
        div.addWidget(chip)
        div.addStretch(1)
        self._conv_layout.addLayout(div)

        self._conv_layout.addWidget(self._msg_bubble(
            "OP",
            "Find the iron-rich particles in the current field of view and take "
            "a Fe L₃ stack on the two strongest ones.",
            "14:03:11"))
        self._conv_layout.addWidget(self._msg_bubble(
            "TA",
            "I ran a two-point absorption contrast pass over "
            "<b>NS_260809056.stxm</b> at 705.5 eV and 700.0 eV. Six candidate "
            "particles above threshold; two are well separated and outside the "
            "drift region flagged by the intelligence agent.<br><br>"
            "<span style='color:#7c8894'>ROI 1 · (−1.42, 3.08) µm · ΔOD 0.61"
            "&nbsp;&nbsp;&nbsp; ROI 2 · (2.10, −0.94) µm · ΔOD 0.48</span>",
            "14:03:26 · 4.1 s · 2 tool calls"))
        self._conv_layout.addWidget(self._msg_bubble(
            "IA",
            "fCCD frame 3184 shows a column dropout on lines 46–49 of the last "
            "spiral. Interpolated in the preview, flagged in the file. Recommend "
            "re-taking the region if quantitative OD is needed below 0.05.",
            "14:03:29 · not addressable from GUI"))
        self._conv_layout.addWidget(self._msg_bubble(
            "TA",
            "Proposed plan below. Nothing has moved yet — the scan queue is "
            "untouched until you approve.",
            "14:03:34", extra=self._proposal_card()))

        self._conv_layout.addStretch(1)
        scroll.setWidget(inner)
        cbody.addWidget(scroll, 1)
        cbody.addWidget(self._agent_composer())
        return card

    def _msg_bubble(self, speaker, html, meta, extra=None):
        avatar_style = {
            "OP": ("#1d2833", "#8b97a3"),
            "TA": ("#0f2a2b", "#5fd4d6"),
            "IA": ("#2a2113", "#ffc45e"),
        }[speaker]
        bubble_style = {
            "OP": ("#161b21", "#2c3a48", "#e6ebef"),
            "TA": ("#101820", "#22303c", "#cbd5dd"),
            "IA": ("#171410", "#3a2f1a", "#d8cbb3"),
        }[speaker]
        max_w = {"OP": 620, "TA": 700, "IA": 700}[speaker]

        w = QWidget()
        g = QHBoxLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(12)
        av = QLabel(speaker)
        av.setFixedSize(26, 26)
        av.setAlignment(Qt.AlignCenter)
        av.setFont(mono_font(10, QFont.DemiBold))
        av.setStyleSheet(
            f"background:{avatar_style[0]};color:{avatar_style[1]};"
            "border-radius:5px;")
        g.addWidget(av, 0, Qt.AlignTop)

        col = QVBoxLayout(); col.setSpacing(5); col.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
        bubble.setObjectName("convBubble")
        bubble.setMaximumWidth(max_w)
        # objectName-scoped so the border can't leak onto child labels
        # (QLabel subclasses QFrame, so bare-property borders would apply to it).
        bubble.setStyleSheet(
            f"QFrame#convBubble {{background:{bubble_style[0]};"
            f"border:1px solid {bubble_style[1]};border-radius:8px;}}")
        bv = QVBoxLayout(bubble)
        bv.setContentsMargins(14, 12, 14, 12)
        bv.setSpacing(8)
        if speaker == "IA":
            adv = self._label("ADVISORY → TASK AGENT", role="monoFaint")
            adv.setStyleSheet(f"color:{C['motion']};background:transparent;"
                              "font-size:10px;letter-spacing:1px;")
            bv.addWidget(adv)
        text = QLabel(html)
        text.setTextFormat(Qt.RichText)
        text.setWordWrap(True)
        text.setMaximumWidth(max_w - 28)      # force wrap within the bubble
        text.setStyleSheet(f"color:{bubble_style[2]};background:transparent;"
                           "font-size:13px;")
        bv.addWidget(text)
        if extra is not None:
            bv.addWidget(extra)
        # Bubble in an HBox with a trailing stretch: the bubble hugs its content
        # width (capped at max_w) and word-wraps within it.  A trailing AlignTop
        # on the content column would suppress QLabel heightForWidth (→ no wrap).
        brow = QHBoxLayout(); brow.setContentsMargins(0, 0, 0, 0)
        brow.addWidget(bubble)
        brow.addStretch(1)
        col.addLayout(brow)
        col.addWidget(self._label(meta, role="monoFaint"))
        cw = QWidget(); cw.setLayout(col)
        g.addWidget(cw, 1)
        return w

    def _proposal_card(self):
        card = QFrame()
        card.setObjectName("proposalCard")
        card.setStyleSheet(f"QFrame#proposalCard {{background:#0b1116;"
                           f"border:1px solid {C['border_strong']};"
                           "border-radius:7px;}")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        head = QFrame()
        head.setObjectName("proposalHead")
        head.setStyleSheet(f"QFrame#proposalHead {{background:{C['panel_footer']};"
                           f"border:none;border-bottom:1px solid {C['border']};}}")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(13, 9, 13, 9)
        h = self._label("PROPOSED ACTION")
        h.setObjectName("panelHeading")
        hl.addWidget(h)
        hl.addStretch(1)
        self._proposal_state = self._label("AWAITING APPROVAL", role="monoFaint")
        self._proposal_state.setStyleSheet(
            f"color:{C['motion']};background:transparent;font-size:11px;")
        hl.addWidget(self._proposal_state)
        cv.addWidget(head)

        bodyw = QWidget()
        bv = QVBoxLayout(bodyw)
        bv.setContentsMargins(13, 12, 13, 12)
        bv.setSpacing(9)
        steps = [
            ("1", "Coarse image at ROI 1 to confirm registration",
             "10 × 10 µm · 100 nm · 1.0 ms"),
            ("2", "Fe L₃ image stack, ROI 1", "4 × 4 µm · 40 nm · 121 pts"),
            ("3", "Fe L₃ image stack, ROI 2", "4 × 4 µm · 40 nm · 121 pts"),
            ("4", "Re-take lines 46–49 flagged by intelligence agent",
             "optional · +02:10"),
        ]
        for n, what, detail in steps:
            row = QHBoxLayout(); row.setSpacing(10)
            idx = self._label(n, role="monoFaint"); idx.setFixedWidth(18)
            row.addWidget(idx, 0, Qt.AlignTop)
            row.addWidget(self._label(what, font=sans_font(11.5), color=C["text_2"]), 1)
            d = self._label(detail, role="monoFaint")
            row.addWidget(d, 0, Qt.AlignTop)
            bv.addLayout(row)
        rule = QFrame(); rule.setFixedHeight(1)
        rule.setStyleSheet(f"background:{C['separator']};border:none;")
        bv.addWidget(rule)
        cost = self._label("total 00:19:40      242 energy points      "
                           "2 files      dose 1.4× nominal", role="monoFaint")
        bv.addWidget(cost)
        cv.addWidget(bodyw)

        actions = QFrame()
        actions.setObjectName("proposalActions")
        actions.setStyleSheet(f"QFrame#proposalActions {{background:{C['panel_footer']};"
                              f"border:none;border-top:1px solid {C['border']};}}")
        al = QHBoxLayout(actions)
        al.setContentsMargins(13, 11, 13, 11)
        al.setSpacing(8)
        approve = QPushButton("Approve && queue")
        approve.setObjectName("beginScan")
        approve.setCursor(Qt.PointingHandCursor)
        approve.clicked.connect(self._approve_plan)
        al.addWidget(approve)
        for name in ("Edit in Acquisition", "Dry run"):
            b = QPushButton(name); b.setProperty("role", "small")
            al.addWidget(b)
        al.addStretch(1)
        reject = QPushButton("Reject")
        reject.setObjectName("rejectBtn")
        reject.setCursor(Qt.PointingHandCursor)
        reject.clicked.connect(self._reject_plan)
        al.addWidget(reject)
        cv.addWidget(actions)
        return card

    def _approve_plan(self):
        if self._plan_state != "pending":
            return
        self._plan_state = "approved"
        self._proposal_state.setText("APPROVED 14:04:02")
        self._proposal_state.setStyleSheet(
            f"color:{C['ok']};background:transparent;font-size:11px;")
        # append a confirmation turn before the trailing stretch
        conf = self._msg_bubble(
            "TA",
            "Queued as items 4–5. Step 1 running now: coarse image at ROI 1, "
            "10 × 10 µm. I will report the OD contrast when the first stack "
            "finishes and log both files.",
            "14:04:02 · queue updated")
        self._conv_layout.insertWidget(self._conv_layout.count() - 1, conf)

    def _reject_plan(self):
        if self._plan_state != "pending":
            return
        self._plan_state = "rejected"
        self._proposal_state.setText("REJECTED")
        self._proposal_state.setStyleSheet(
            f"color:#e08b8b;background:transparent;font-size:11px;")

    def _agent_composer(self):
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(16, 12, 16, 12)
        fv.setSpacing(9)
        presets = QHBoxLayout(); presets.setSpacing(7)
        for name in ("Optimise focus", "Find features", "Explain last anomaly",
                     "Summarise this session"):
            b = QPushButton(name); b.setProperty("role", "small")
            presets.addWidget(b)
        presets.addStretch(1)
        fv.addLayout(presets)
        row = QHBoxLayout(); row.setSpacing(9)
        inp = QLineEdit()
        inp.setPlaceholderText("Ask the task agent…")
        inp.setFont(sans_font(11.5))
        row.addWidget(inp, 1)
        send = QPushButton("Send")
        send.setObjectName("beginScan")
        send.setCursor(Qt.PointingHandCursor)
        row.addWidget(send)
        fv.addLayout(row)
        return footer

    def _agent_logbook_col(self):
        card, cbody = self._card("Logbook")
        meta = self._label(f"2026-08-09 · {len(self._LOG_ENTRIES)} entries",
                           role="monoFaint")
        card._header_layout.insertWidget(1, meta)
        card._header_layout.insertSpacing(2, 10)
        exp = QPushButton("Export MD"); exp.setProperty("role", "small")
        card._header_layout.addWidget(exp)

        frow = QFrame()
        frow.setObjectName("filterRow")
        frow.setStyleSheet(f"QFrame#filterRow {{background:{C['panel_footer']};"
                           f"border:none;border-bottom:1px solid {C['border']};}}")
        fl = QHBoxLayout(frow)
        fl.setContentsMargins(14, 10, 14, 10)
        fl.setSpacing(6)
        self._log_filter_grp, fbtns = self._filter_pills(self._LOG_FILTERS)
        for i, b in enumerate(fbtns):
            fl.addWidget(b)
            b.clicked.connect(
                lambda _=False, k=self._LOG_FILTERS[i]: self._set_log_filter(k))
        fl.addStretch(1)
        cbody.addWidget(frow)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self._log_layout = QVBoxLayout(inner)
        self._log_layout.setContentsMargins(0, 0, 0, 0)
        self._log_layout.setSpacing(0)
        self._log_layout.addStretch(1)
        scroll.setWidget(inner)
        cbody.addWidget(scroll, 1)

        # composer
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fl2 = QHBoxLayout(footer)
        fl2.setContentsMargins(14, 11, 14, 11)
        fl2.setSpacing(8)
        note = QLineEdit()
        note.setPlaceholderText("Add a note to the logbook…")
        note.setFont(sans_font(11))
        fl2.addWidget(note, 1)
        attach = QPushButton("Attach view"); attach.setProperty("role", "small")
        addb = QPushButton("Add"); addb.setProperty("role", "small")
        fl2.addWidget(attach)
        fl2.addWidget(addb)
        cbody.addWidget(footer)
        return card

    def _set_log_filter(self, kind):
        self._log_filter = kind
        self._render_logbook()

    def _render_logbook(self):
        while self._log_layout.count() > 1:      # keep trailing stretch
            item = self._log_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for entry in self._LOG_ENTRIES:
            if self._log_filter != "All" and entry[1] != self._log_filter:
                continue
            self._log_layout.insertWidget(
                self._log_layout.count() - 1, self._log_row(entry))

    def _log_row(self, entry):
        time, kind, tag, color, title, body_txt, meta, seed, fkind = entry
        row = QFrame()
        row.setObjectName("rowSep")
        g = QHBoxLayout(row)
        g.setContentsMargins(14, 13, 14, 13)
        g.setSpacing(12)
        t = self._label(time, role="monoFaint")
        t.setFixedWidth(46)
        g.addWidget(t, 0, Qt.AlignTop)
        spine = QFrame(); spine.setFixedWidth(3)
        spine.setStyleSheet(f"background:{color};border-radius:2px;")
        g.addWidget(spine)
        box = QVBoxLayout(); box.setSpacing(4)
        titlerow = QHBoxLayout(); titlerow.setSpacing(9)
        titlerow.addWidget(self._label(title, font=sans_font(12.5, QFont.DemiBold),
                                       color=C["text"]))
        chip = self._label(tag)
        chip.setFont(mono_font(9))
        chip.setStyleSheet(
            f"color:{color};background:transparent;border:1px solid {color}44;"
            "border-radius:3px;padding:1px 6px;letter-spacing:1px;")
        titlerow.addWidget(chip)
        titlerow.addStretch(1)
        box.addLayout(titlerow)
        b = self._label(body_txt, font=sans_font(12), color=C["text_muted"])
        b.setWordWrap(True)
        box.addWidget(b)
        if seed is not None:
            mrow = QHBoxLayout(); mrow.setSpacing(8)
            thumb = QLabel()
            thumb.setFixedSize(74, 74)
            thumb.setScaledContents(True)
            thumb.setStyleSheet(f"background:#000;border:1px solid {C['border']};"
                                "border-radius:4px;")
            thumb.setPixmap(_field_pixmap(_thumb_field(seed, fkind, 74), "gray", 74))
            mrow.addWidget(thumb, 0, Qt.AlignTop)
            mrow.addWidget(self._label(meta, role="monoFaint"), 1, Qt.AlignTop)
            box.addLayout(mrow)
        else:
            box.addWidget(self._label(meta, role="monoFaint"))
        bw = QWidget(); bw.setLayout(box)
        g.addWidget(bw, 1)
        return row

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
            pos = float(wd["target"].text())
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
            step = float(wd["target"].text())
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
            c.start_scan()
        # start_scan / cancel_scan emit scan_state_changed → _set_scanning keeps
        # the Begin/Cancel button in sync with the controller's real state.

    def _compile_scan(self):
        """Populate the controller's scan_model from the dashboard widgets,
        mirroring MainController.compile_scan_from_view but reading THIS view's
        widgets.  Returns True on success.

        Scoped to Image-family scans (SampleX/SampleY spatial grid + energy
        regions); other scan types report an error until their panels are wired.
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
            sm.set('comment', '')
            sm.set('driver', driver)
            sm.set('mode', sc.get('mode', 'continuousLine'))
            sm.set('loop_scan', False)   # loop sequence not yet wired in dashboard
            sm.set('daq_list', self._resolve_daq_list(client, sc))

            # Spatial regions — flush the grid into the active region, then emit
            # every image region (plus the spectrum region, if enabled).
            if isinstance(self._active_region, int):
                self._scan_regions[self._active_region].update(
                    self._read_spatial_fields())
            elif self._spectrum_region is not None:
                self._spectrum_region.update(self._read_spatial_fields())
            region = self._region_scan_dict(self._scan_regions[0])
            for i, r in enumerate(self._scan_regions):
                sm.add_scan_region(f'Region{i + 1}', self._region_scan_dict(r))
            if self._spectrum_region is not None:
                spec = self._region_scan_dict(self._spectrum_region)
                spec['spectrum'] = True
                sm.add_scan_region('SpectrumRegion', spec)

            # Energy regions — flush the field row into the active region first.
            self._sync_active_energy_region()
            total_n = 0
            for i, r in enumerate(self._energy_regions):
                total_n += r['n']
                sm.add_energy_region(f'EnergyRegion{i + 1}', {
                    'start': r['start'], 'stop': r['stop'], 'step': r['step'],
                    'dwell': r['dwell'], 'n_energies': r['n']})
            sm.set('single_energy', total_n <= 1)
            sm.set('energy_list', None)

            est = sm.calculate_estimated_time()
            self._update_scan_stats(est, region)
            c.status_updated.emit(f"Scan compiled — est. {self._fmt_mmss(est)}")
            return True
        except ValueError as e:
            c.error_occurred.emit(f"Invalid scan value: {e}")
            return False
        except Exception as e:
            c.error_occurred.emit(f"Failed to compile scan: {e}")
            return False

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

    def _update_scan_stats(self, est_seconds, region):
        lbls = getattr(self, "_stat_labels", {})
        if 'Est. time' in lbls:
            lbls['Est. time'].setText(self._fmt_mmss(est_seconds))
        if 'Points' in lbls:
            pts = int(region['xPoints']) * int(region['yPoints'])
            lbls['Points'].setText(f"{pts:,}".replace(',', ' '))

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
        """Place the image data at the primary scan region (Region1) so pixels
        land under its ROI, and auto-fit the *view* to hold all regions."""
        regs = list(self._scan_regions)
        if self._spectrum_region is not None:
            regs.append(self._spectrum_region)
        if not regs:
            return
        # Image data extent = the region being scanned/displayed (Region1).
        primary = self._scan_regions[0]
        self.image_area.set_image_extent(
            primary['xCenter'], primary['yCenter'],
            primary['xRange'], primary['yRange'])
        # View = bounding box of all regions, padded (min 20 µm).
        x0 = min(r['xCenter'] - r['xRange'] / 2 for r in regs)
        x1 = max(r['xCenter'] + r['xRange'] / 2 for r in regs)
        y0 = min(r['yCenter'] - r['yRange'] / 2 for r in regs)
        y1 = max(r['yCenter'] + r['yRange'] / 2 for r in regs)
        xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
        span = max(x1 - x0, y1 - y0)
        w = max(span * 1.5, 20.0)
        self.image_area.set_view(xc, yc, w, w)

    def _refresh_spatial_image(self, fit=False):
        """Redraw the ROI boxes (and optionally refit the FOV) from the model."""
        if self._syncing_spatial or not hasattr(self, 'image_area'):
            return
        if getattr(self, '_del_region_btn', None):
            self._del_region_btn.setEnabled(
                self._active_region == 'spectrum' or len(self._scan_regions) > 1)
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

    def _select_energy_region(self, idx):
        self._load_energy_region(idx)

    def _sync_active_energy_region(self):
        """Write the current field row back into the active region, then redraw."""
        if not getattr(self, '_energy_regions', None):
            return
        self._energy_regions[self._active_energy_region] = self._read_energy_fields()
        self._refresh_energy_strip()

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
        self._scanning = bool(scanning)
        if self._scanning:
            self.begin_btn.setText("Cancel scan")
            self.begin_btn.setObjectName("cancelScan")
        else:
            self.begin_btn.setText("Begin scan")
            self.begin_btn.setObjectName("beginScan")
        # re-polish so the objectName-based style applies
        self.begin_btn.style().unpolish(self.begin_btn)
        self.begin_btn.style().polish(self.begin_btn)

    def _toggle_expert(self):
        self._expert = not self._expert
        self.mode_btn.setText("Staff mode" if self._expert else "User mode")
        self.cmd_log.setVisible(self._expert)
        for wdg in self._staff_widgets:
            wdg.setVisible(self._expert)

    def _on_scan_type(self, text):
        ptycho = "Ptycho" in text
        self.mode_field.setText("ptychography" if ptycho else "continuousLine")

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
        # scroll the DUMMY counter trace only in placeholder mode; when connected,
        # real monitor data drives it via _on_monitor_data.
        if (self.controller is None and hasattr(self, "trace_curve")
                and self.det_stack.currentIndex() == 1):
            self._trace = np.roll(self._trace, -1)
            self._trace[-1] = 1 + (np.random.random() - .5) * .004
            self.trace_curve.setData(self._trace)
            self.counts_lbl.setText(f"{self._trace[-1]:.4f}")

    # ── controller slots (read-only live data) ──────────────────────────
    def _on_motor_position(self, name, pos):
        self._motor_info.setdefault(name, {})["last value"] = pos
        wd = self._motor_widgets.get(name)
        if wd:
            wd["value"].setText(f"{pos:.2f}")
            wd["bar"].set_state(self._frac(pos, wd["lo"], wd["hi"]), wd["bar"]._moving)
        if name == "Energy":
            self.energy_val.setText(f"{pos:.1f} eV")

    def _on_motor_status(self, name, moving):
        wd = self._motor_widgets.get(name)
        if not wd:
            return
        color = C["motion"] if moving else C["text"]
        wd["value"].setStyleSheet(f"color:{color};background:transparent;")
        val = self._motor_info.get(name, {}).get("last value")
        wd["bar"].set_state(self._frac(val, wd["lo"], wd["hi"]), moving)

    def _on_image(self, image):
        try:
            # The server tags each frame's region + physical geometry on the
            # image model (the image_updated payload is only the bare array);
            # route each region's frame to its own physical extent so multi-
            # region scans mosaic instead of stacking in Region1.
            placed = False
            if self.controller is not None:
                im = self.controller.get_image_model()
                xc, yc = im.get('x_center'), im.get('y_center')
                xr, yr = im.get('x_range'), im.get('y_range')
                if xr and yr and xc is not None and yc is not None:
                    key = str(im.get('scan_region_index', 'Region1'))
                    self.image_area.set_region_frame(key, image, xc, yc, xr, yr)
                    placed = True
            if not placed:
                self.image_area.set_primary_frame(image)
            self._image_seeded = True
        except Exception:
            pass
        # Each frame also refreshes the live-detector CCD panel from the per-detector
        # frames the controller stored on the image model.
        self._refresh_ccd()

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
        """Update the live-detector CCD panel with the latest area-detector frame.

        Idle: the controller stashes each idle-monitor frame under
        'latest_monitor_frames' (the trace only keeps the scalar sum).
        Scanning: the per-detector frames live under 'all_detector_images'.
        """
        if self.controller is None or not hasattr(self, "ccd_img"):
            return
        key = self._ccd_channel_key()
        if key is None:
            return
        try:
            im = self.controller.get_image_model()
            frame = (im.get("latest_monitor_frames") or {}).get(key)
            if not (isinstance(frame, np.ndarray) and frame.ndim >= 2):
                frame = (im.get("all_detector_images") or {}).get(key)
            if isinstance(frame, np.ndarray) and frame.ndim >= 2:
                # Log-scale for display (diffraction has huge dynamic range), as the
                # classic viewer does; autorange levels on the first real frame.
                disp = np.log1p(np.clip(frame.astype(float), 0, None))
                self.ccd_img.setImage(disp, autoLevels=not self._ccd_seeded)
                self._ccd_seeded = True
                # Caption reflects the real frame: dimensions + total counts.
                h, w = frame.shape[:2]
                dims = f"{h}² · log" if h == w else f"{h}×{w} · log"
                self.ccd_dims_lbl.setText(dims)
                self.ccd_sum_lbl.setText(f"Σ {float(np.sum(frame)):.1e}")
        except Exception:
            pass

    def _on_shutter(self, mode):
        text = {"open": "OPEN", "close": "CLOSED", "auto": "AUTO"}.get(mode, str(mode).upper())
        color = C["alert_text"] if mode == "close" else C["ok"]
        self.shutter_val.setText(text)
        self.shutter_val.setStyleSheet(f"color:{color};background:transparent;")

    def _on_daq_value(self, value):
        if hasattr(self, "counts_lbl"):
            self.counts_lbl.setText(f"{value:.4f}")

    def _on_monitor_data(self):
        """Refresh the Counter1 trace from the image model's monitor buffer."""
        if not hasattr(self, "trace_curve"):
            return
        try:
            data = self.controller.get_image_model().get("monitor_data") or {}
            series = None
            for key in ("Counter1", "default"):
                if key in data:
                    series = data[key]; break
            if series is None and data:
                series = next(iter(data.values()))
            arr = np.asarray(series, dtype=float).ravel()
            if arr.size:
                self.trace_curve.setData(arr)
                self.counts_lbl.setText(f"{arr[-1]:.4f}")
        except Exception:
            pass
        # Idle CCD frames also arrive on this signal (the trace keeps only the sum).
        self._refresh_ccd()

    def _on_progress_text(self, text):
        if hasattr(self, "progress_caption"):
            self.progress_caption.setText(text)

    def _on_est_time(self, seconds):
        self._est_seconds = float(seconds)
        self._refresh_progress_time()

    def _on_elapsed_time(self, seconds):
        self._elapsed_seconds = float(seconds)
        self._refresh_progress_time()

    @staticmethod
    def _fmt_mmss(seconds):
        seconds = max(0, int(seconds))
        return f"{seconds // 60:d}:{seconds % 60:02d}"

    def _refresh_progress_time(self):
        if not hasattr(self, "progress_time_lbl"):
            return
        est = getattr(self, "_est_seconds", 0.0)
        elapsed = getattr(self, "_elapsed_seconds", 0.0)
        self.progress_time_lbl.setText(
            f"{self._fmt_mmss(elapsed)} / {self._fmt_mmss(est)}")
        if est > 0:
            self.progress.set_frac(elapsed / est)

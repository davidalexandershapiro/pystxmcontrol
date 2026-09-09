"""The acquisition dashboard's main image viewer and its scientific axis.

Split out of ``mainwindow``.  ``ImageArea`` owns the pyqtgraph
ViewBox/ImageItem, the interactive scan-region and focus-line ROIs, the overlay
metadata bar and scale bar, and the plot mode used by 1-D scans.  It reports
user interaction through signals and holds no scan-definition state of its own,
so the window remains the only place scan regions are decided.
"""

import os

import numpy as np
import pyqtgraph as pg

from PySide6.QtWidgets import (
    QWidget, QLabel, QFrame, QHBoxLayout, QVBoxLayout,
)
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtCore import Qt, QRectF, Signal

from pystxmcontrol.gui.dashboard.theme import C, make_lut, mono_font, roi_colors

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "..", "icons")

# The dashboard image display convention is row-major (matches
# mainwindow, which sets this at import).  Set it here too so the
# widget renders identically standalone.
pg.setConfigOptions(antialias=True, imageAxisOrder="row-major",
                    background=C["plot_ground"])


_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def exp_str(exp):
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

    def set_rois_visible(self, visible):
        """Show/hide every scan-region ROI box (+ its label) and the scan line —
        used to omit them from an exported PNG so only the image and its metadata
        overlay are saved."""
        for it in self._roi_items.values():
            it["roi"].setVisible(visible)
            it["label"].setVisible(visible)
        if self._line_roi is not None:
            self._line_roi.setVisible(visible)

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
            # ROI boxes sit above the image tiles (z 0).  The spectrum box goes
            # above everything else — including the crosshair (12) — so live scan
            # data streaming into the tiles can never bury the one ROI the
            # operator adjusts while a scan is running.
            spectrum = kind == "spectrum"
            roi.setZValue(20 if spectrum else 10)
            roi.sigRegionChangeStarted.connect(lambda _, k=key: self._on_start(k))
            roi.sigRegionChanged.connect(lambda _, k=key: self._on_changed(k))
            roi.sigRegionChangeFinished.connect(lambda _, k=key: self._on_finished(k))
            roi.sigClicked.connect(lambda _, __, k=key: self.roi_selected.emit(k))
            self.vb.addItem(roi)
            label = pg.TextItem("", color=color, anchor=(0, 1))
            label.setFont(mono_font(8))
            label.setZValue(21 if spectrum else 11)
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

"""
Browser App (dashboard style) — a standalone data-file browser for the
dashboard's Browser tab.

Ports the working data browser from ``data_browser_widget.py`` onto the
dashboard's bespoke dark theme (``dashboard_theme``): the three-column
"Session files / Viewer / Details" layout the acquisition dashboard mock uses,
wired to real ``.stxm`` files instead of the mock's procedural placeholder
fields.

The heavy lifting — HDF5 preview reading, the background thumbnail thread and
its SQLite cache, and the metadata-overlay item — is *reused* from
``data_browser_widget`` rather than reimplemented; only the chrome (cards,
pills, viewer rail, footer readouts) is rebuilt on the dashboard palette.

Two classes:

``DashboardImageViewer``
    The centre viewer: a ``pg.ImageView`` with its own UI chrome hidden and the
    dashboard palette applied, driven by the colormap pills and the footer's
    energy/stack navigation.  A reused ``_MetadataOverlay`` draws the scale bar
    + facility logo + two metadata rows; a scene mouse hook reports the cursor's
    sample X/Y and pixel value.

``BrowserApp``
    The whole tab: Session files (folder / date navigation, scan-type filter
    pills, a scrolling grid of themed thumbnail tiles), the viewer, and a
    details column (scan Parameters + Actions).  Works standalone (carries its
    own stylesheet) and embedded in ``mainwindow_dashboard`` alike, and — like
    ``DataBrowserWidget`` — emits ``file_selected`` / ``send_to_analysis`` /
    ``send_to_acquisition`` and accepts a ``logbook_model`` for "Add to log".
"""

import os
import sys
import json
import glob

import numpy as np
import h5py
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QComboBox, QDateEdit,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QButtonGroup,
    QFileDialog, QProgressBar, QSizePolicy, QSlider,
)
from PySide6.QtCore import Qt, Signal, QDate, QTimer, QRectF
from PySide6.QtGui import QFont, QImage, QPixmap

from pystxmcontrol.gui.dashboard_theme import (
    C, build_stylesheet, mono_font, sans_font, make_lut,
)
# Reuse the proven data path from the classic browser: the background thumbnail
# thread (and its HDF5 preview reader / SQLite cache) plus the metadata-overlay
# item and the h5py-string helper.  Rebuilding these would only invite drift.
from pystxmcontrol.gui.data_browser_widget import (
    ThumbnailLoader, _MetadataOverlay, _h5str,
)
from pystxmcontrol.utils.thumbnail_cache import ThumbnailCache

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")
_ALS_LOGO = os.path.join(_ICONS_DIR, "als-logo.png")

# The dashboard image display convention is row-major (matches
# mainwindow_dashboard, which sets this at import).  Set it here too so the
# widget renders identically standalone.  _oriented() below keeps us correct
# even if some other importer flipped it.
pg.setConfigOptions(imageAxisOrder="row-major")


def _oriented(arr2d):
    """Return a 2-D image array oriented so pyqtgraph shows it as (y rows, x
    cols) regardless of the global ``imageAxisOrder``.  HDF5 image data is
    stored (y, x)."""
    if pg.getConfigOption("imageAxisOrder") == "row-major":
        return arr2d
    return arr2d.T


def _default_data_dir():
    """The server's ``data_dir`` from the runtime main.json (sys.prefix copy
    first, repo copy as a fallback), or ``~`` if unavailable — the same file the
    server and mainwindow_dashboard read."""
    for path in (os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json"),
                 os.path.join(os.path.dirname(__file__), "..", "..", "config",
                              "main.json")):
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            d = (cfg.get("server") or {}).get("data_dir")
            if d and os.path.isdir(d):
                return d
        except Exception:
            continue
    return os.path.expanduser("~")


# ── dashboard chrome helpers (module-level twins of the mainwindow methods) ──
def _mk_label(text, role=None, font=None, color=None):
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if font:
        lbl.setFont(font)
    if color:
        lbl.setStyleSheet(f"color:{color};background:transparent;")
    return lbl


def _mk_card(title):
    """Return (card QFrame, body QVBoxLayout) — the dashboard's titled card.
    ``card._header_layout`` is exposed for extra header controls."""
    card = QFrame()
    card.setObjectName("card")
    cl = QVBoxLayout(card)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(0)
    header = QFrame()
    header.setObjectName("cardHeader")
    hl = QHBoxLayout(header)
    hl.setContentsMargins(14, 11, 14, 11)
    h = _mk_label(title.upper())
    h.setObjectName("panelHeading")
    hl.addWidget(h)
    hl.addStretch(1)
    cl.addWidget(header)
    card._header_layout = hl
    return card, cl


def _small_btn(text, tip=""):
    b = QPushButton(text)
    b.setProperty("role", "small")
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def _cmap_control(on_change, checked=0):
    """gray/viridis/inferno segmented pill control wired to ``on_change(name)``.
    Returns the well QFrame."""
    names = ("gray", "viridis", "inferno")
    well = QFrame()
    well.setProperty("role", "pillWell")
    wl = QHBoxLayout(well)
    wl.setContentsMargins(2, 2, 2, 2)
    wl.setSpacing(2)
    grp = QButtonGroup(well)
    grp.setExclusive(True)
    for i, name in enumerate(names):
        b = QPushButton(name)
        b.setProperty("role", "pill")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        if i == checked:
            b.setChecked(True)
        grp.addButton(b, i)
        b.clicked.connect(lambda _=False, n=name: on_change(n))
        wl.addWidget(b)
    well._group = grp
    return well


# ════════════════════════════════════════════════════════════════════════════
#  Thumbnail tile (dashboard style)
# ════════════════════════════════════════════════════════════════════════════
class BrowserTile(QFrame):
    """A clickable thumbnail card on the dashboard palette: a colour-mapped
    preview canvas over the filename and scan type.  Emits ``clicked`` with its
    filepath."""

    clicked = Signal(str)

    CANVAS = 188            # square image-area side (px)

    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.setObjectName("browserTile")
        self.filepath = filepath
        self.scan_type = ""
        self._raw = None                # cached thumbnail array (for cmap swaps)
        self._cmap = "gray"
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)

        # The image area is a fixed SQUARE (the Session-files column is a fixed
        # width, so the cell width is stable).  The thumbnail is drawn inside it
        # with its true aspect ratio (KeepAspectRatio + AlignCenter → black
        # letterbox bars).  Name/type labels use an Ignored horizontal policy so
        # a long filename can't grow the tile and collapse the column grid.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(5)
        self.canvas = QLabel("loading…")
        self.canvas.setFixedSize(self.CANVAS, self.CANVAS)
        self.canvas.setAlignment(Qt.AlignCenter)
        self.canvas.setStyleSheet(
            f"background:#000;border:none;color:{C['text_faint']};font-size:11px;")
        v.addWidget(self.canvas, alignment=Qt.AlignHCenter)
        cap = QVBoxLayout()
        cap.setSpacing(1)
        self.name_lbl = _mk_label(os.path.basename(filepath), role="mono")
        self.name_lbl.setFont(mono_font(10.5))
        self.name_lbl.setWordWrap(False)
        self.name_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        cap.addWidget(self.name_lbl)
        self.type_lbl = _mk_label("", role="microLabel")
        self.type_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        cap.addWidget(self.type_lbl)
        v.addLayout(cap)
        self._apply_style()

    def set_thumbnail(self, arr, scan_type):
        self.scan_type = scan_type or ""
        self._raw = arr
        self.type_lbl.setText(self.scan_type.upper())
        self._repaint_canvas()

    def set_cmap(self, name):
        self._cmap = name
        self._repaint_canvas()

    def _repaint_canvas(self):
        if self._raw is None:
            self.canvas.setText("N/A")
            self.canvas.setPixmap(QPixmap())
            return
        arr = np.asarray(self._raw, dtype=float)
        if arr.size == 0:
            self.canvas.setText("N/A")
            return
        mn, mx = np.nanmin(arr), np.nanmax(arr)
        norm = (arr - mn) / (mx - mn) if mx > mn else np.zeros_like(arr)
        idx = (np.clip(norm, 0, 1) * 255).astype(np.uint8)
        rgb = np.ascontiguousarray(make_lut(self._cmap)[idx])
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        # Fit the thumbnail into the square canvas at its true aspect ratio;
        # AlignCenter + the black canvas background give the letterbox bars.
        pm = QPixmap.fromImage(qimg).scaled(
            self.CANVAS, self.CANVAS, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.canvas.setText("")
        self.canvas.setPixmap(pm)

    def set_selected(self, selected):
        self._selected = selected
        self._apply_style()

    def _apply_style(self):
        sel = self._selected
        self.setStyleSheet(
            f"QFrame#browserTile {{background:"
            f"{'#131a20' if sel else C['panel_footer']};"
            f"border:1px solid {C['accent'] if sel else C['border']};"
            "border-radius:6px;}")
        self.name_lbl.setStyleSheet(
            f"color:{C['text'] if sel else C['text_2']};background:transparent;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.filepath)
        super().mousePressEvent(event)


# ════════════════════════════════════════════════════════════════════════════
#  Image viewer (dashboard style)
# ════════════════════════════════════════════════════════════════════════════
class DashboardImageViewer(QWidget):
    """A ``pg.ImageView`` reskinned for the dashboard: its histogram / ROI /
    menu chrome is hidden (the dashboard supplies its own colormap pills and
    rail), the background is the plot-ground colour, and a reused
    ``_MetadataOverlay`` draws the scale bar + logo + metadata rows.

    Frames are fed one at a time for stacks (the Browser footer drives the
    energy index); tiled multi-region scans get one ``ImageItem`` per tile.
    ``cursor_changed(x_um, y_um, value_str)`` fires as the pointer moves over
    the image."""

    # gray → pyqtgraph's 'grey' gradient preset; others match by name.
    _PRESET = {"gray": "grey", "viridis": "viridis", "inferno": "inferno"}

    cursor_changed = Signal(float, float, str)

    def __init__(self, cmap="gray", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C['plot_ground']};")
        self._cmap = cmap
        self._tile_items = []           # bare ImageItems for tiled displays

        self.iv = pg.ImageView(parent=self)
        self.iv.ui.roiBtn.hide()
        self.iv.ui.menuBtn.hide()
        # Kill the built-in time/ROI plot for good: ImageView.setImage re-shows it
        # for stacks, so hiding alone is not enough — pin it to zero height (this
        # also removes its timeline vertical line).  The Browser footer navigates
        # energy planes instead.
        self.iv.ui.roiPlot.hide()
        self.iv.ui.roiPlot.setFixedHeight(0)
        self.iv.getView().setBackgroundColor(C["plot_ground"])

        # Keep pyqtgraph's histogram / contrast slider on the right — it IS the
        # interactive levels + colormap control.  Restyle it for the dashboard
        # and seed its gradient from the colormap pills.
        self.hist = self.iv.ui.histogram
        self.hist.setBackground(C["plot_ground"])
        self.hist.axis.setPen(C["border"])
        self.hist.axis.setTextPen(C["text_faint"])
        self.hist.gradient.loadPreset(self._PRESET.get(cmap, "grey"))

        self.overlay = _MetadataOverlay(self.iv, logo_path=_ALS_LOGO)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.iv)

        # Cursor readout — throttled scene mouse hook (same pattern as the
        # classic browser's detail view).
        self._proxy = pg.SignalProxy(
            self.iv.getView().scene().sigMouseMoved, rateLimit=40,
            slot=self._on_mouse_moved)

    # ── display ──────────────────────────────────────────────────────────────
    def clear(self):
        self._clear_tiles()
        self.iv.clear()
        self.overlay.set_visible(False)

    def _clear_tiles(self):
        for it in self._tile_items:
            self.iv.getView().removeItem(it)
        self._tile_items = []

    def show_frame(self, data2d, pos=(0.0, 0.0), scale=(1.0, 1.0),
                   aspect_locked=True):
        """Show a single 2-D frame positioned in physical (µm) coordinates."""
        self._clear_tiles()
        self.iv.getView().setAspectLocked(aspect_locked)
        self.iv.setImage(_oriented(np.asarray(data2d, dtype=float)),
                         pos=pos, scale=scale, autoLevels=True)

    def show_stack(self, data3d, pos=(0.0, 0.0), scale=(1.0, 1.0),
                   aspect_locked=True):
        """Show a 3-D stack (n_frames, y, x); the ImageView index selects the
        frame.  Returns the number of frames."""
        self._clear_tiles()
        arr = np.asarray(data3d, dtype=float)
        self.iv.getView().setAspectLocked(aspect_locked)
        if pg.getConfigOption("imageAxisOrder") == "row-major":
            oriented, axes = arr, {"t": 0, "y": 1, "x": 2}
        else:
            oriented, axes = np.transpose(arr, (0, 2, 1)), {"t": 0, "x": 1, "y": 2}
        self.iv.setImage(oriented, axes=axes, pos=pos, scale=scale,
                         autoLevels=True)
        return arr.shape[0]

    def show_tiles(self, tile_list):
        """Show a tiled multi-region composite.  ``tile_list`` items are
        ``(img_2d, x_scale, y_scale, (x0, y0), x_range)`` — the classic
        browser's tiled representation."""
        self._clear_tiles()
        self.iv.clear()
        self.iv.getView().setAspectLocked(True)
        for img_2d, x_scale, y_scale, pos_i, _xr in tile_list:
            it = pg.ImageItem()
            arr = _oriented(np.asarray(img_2d, dtype=float))
            it.setImage(arr, autoLevels=True)
            ny, nx = np.asarray(img_2d).shape[:2]
            it.setRect(QRectF(pos_i[0], pos_i[1], nx * x_scale, ny * y_scale))
            it.setLookupTable(make_lut(self._cmap))
            self.iv.getView().addItem(it)
            self._tile_items.append(it)
        self.iv.getView().autoRange()

    def set_index(self, i):
        """Select frame ``i`` of a stack."""
        self.iv.setCurrentIndex(i)

    def set_cmap(self, name):
        """Switch the colormap: the histogram gradient drives the main image's
        LUT; tiled composites (bare ImageItems the histogram can't reach) get
        the LUT applied directly."""
        self._cmap = name
        self.hist.gradient.loadPreset(self._PRESET.get(name, "grey"))
        if self._tile_items:
            lut = make_lut(name)
            for it in self._tile_items:
                it.setLookupTable(lut)

    def update_overlay(self, x_range_um, rows):
        self.overlay.update(x_range_um, rows)

    # ── cursor ───────────────────────────────────────────────────────────────
    def _on_mouse_moved(self, args):
        pos = args[0]
        view = self.iv.getView()
        if not view.sceneBoundingRect().contains(pos):
            return
        pt = view.mapSceneToView(pos)
        x_um, y_um = pt.x(), pt.y()
        value_str = ""
        img_item = self.iv.getImageItem()
        if self._tile_items:
            for it in self._tile_items:
                dp = it.mapFromScene(pos)
                arr = it.image
                if arr is None:
                    continue
                ix, iy = int(dp.x()), int(dp.y())
                if 0 <= ix < arr.shape[0] and 0 <= iy < arr.shape[1]:
                    value_str = f"{arr[ix, iy]:.2f}"
                    break
        elif img_item.image is not None:
            dp = img_item.mapFromScene(pos)
            arr = img_item.image
            ix, iy = int(dp.x()), int(dp.y())
            if arr.ndim == 2 and 0 <= ix < arr.shape[0] and 0 <= iy < arr.shape[1]:
                value_str = f"{arr[ix, iy]:.2f}"
        self.cursor_changed.emit(x_um, y_um, value_str)


# ════════════════════════════════════════════════════════════════════════════
#  Browser App (files + viewer + details)
# ════════════════════════════════════════════════════════════════════════════
class BrowserApp(QWidget):
    """Standalone data-file browser styled for the dashboard.

    Parameters
    ----------
    controller : MainController or None
        Optional; only used to gate "Send to Acquisition" while a scan runs
        (via ``set_scanning``).  The browser itself reads files straight from
        disk and needs no server.
    logbook_model : LogbookModel or None
        Shared logbook model for "Add to log".  Falls back to
        ``controller.logbook_model`` when present.
    start_dir : str or None
        Root data directory (``…/YYYY/MM/YYMMDD`` hierarchy).  Defaults to the
        server's configured ``data_dir``.
    """

    file_selected = Signal(str)
    send_to_analysis = Signal(str)
    send_to_acquisition = Signal(str)

    THUMB_COLS = 3

    def __init__(self, controller=None, logbook_model=None, start_dir=None,
                 parent=None):
        super().__init__(parent)
        self.controller = controller
        self.logbook_model = logbook_model or getattr(
            controller, "logbook_model", None)
        self.setStyleSheet(build_stylesheet())

        self._cmap = "gray"
        self._cache = ThumbnailCache()
        self._loader = None
        self._tiles = {}                # filepath -> BrowserTile
        self._root_dir = start_dir or _default_data_dir()
        self._direct_day_dir = None
        self._filter = ""               # lowercase scan-type substring ("" = all)
        self._current_filepath = None
        self._scanning = False

        # detail state
        self._det_data = {}             # detector -> (data, x_scale, y_scale, x_range)
        self._is_tiled = False
        self._is_spectrum = False
        self._detail_origin = (0.0, 0.0)
        self._export_meta = {}
        self._n_frames = 1
        self._frame_idx = 0
        self._ptycho_arrays = []        # [obj_amp, obj_phase, probe_amp]
        self._ptycho_px = []            # pixel size (µm) per ptycho view

        self._build_ui()
        # Auto-load today's folder if the default hierarchy has one.
        QTimer.singleShot(0, self._load_for_date)

    # ── construction ─────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        col1 = self._files_col()
        col1.setFixedWidth(660)
        col2 = self._viewer_col()
        col3 = self._details_col()
        col3.setFixedWidth(460)
        root.addWidget(col1)
        root.addWidget(col2, 1)
        root.addWidget(col3)

    # ---- Session files column -------------------------------------------------
    def _files_col(self):
        card, body = _mk_card("Session files")
        self._path_lbl = _mk_label(self._short_path(self._root_dir),
                                   role="monoFaint")
        self._path_lbl.setToolTip(self._root_dir)
        card._header_layout.insertWidget(1, self._path_lbl)
        card._header_layout.insertSpacing(2, 10)
        browse = _small_btn("Browse…", "Choose the data root or a day folder")
        browse.clicked.connect(self._browse_folder)
        card._header_layout.addWidget(browse)
        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDisplayFormat("yyyy-MM-dd")
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.setFixedWidth(120)
        card._header_layout.addWidget(self._date_edit)
        load = _small_btn("Load", "Load scans for the selected date")
        load.clicked.connect(self._load_for_date)
        card._header_layout.addWidget(load)
        refresh = _small_btn("Refresh", "Re-scan the current folder")
        refresh.clicked.connect(self._load_for_date)
        card._header_layout.addWidget(refresh)

        # filter row — a free-text scan-type filter (there are too many scan
        # types for a row of pills), plus a live shown/total count.
        frow = QFrame()
        frow.setObjectName("filterRow")
        frow.setStyleSheet(f"QFrame#filterRow {{background:{C['panel_footer']};"
                           f"border:none;border-bottom:1px solid {C['border']};}}")
        fl = QHBoxLayout(frow)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(8)
        fl.addWidget(_mk_label("Filter", role="fieldLabel"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("scan type…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.setFont(sans_font(11))
        self._filter_edit.textChanged.connect(self._set_filter)
        fl.addWidget(self._filter_edit, 1)
        self._count_lbl = _mk_label("no folder loaded", role="monoFaint")
        fl.addWidget(self._count_lbl)
        body.addWidget(frow)

        # thumbnail grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self._grid = QGridLayout(inner)
        self._grid.setContentsMargins(12, 12, 12, 12)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(10)
        self._grid.setAlignment(Qt.AlignTop)
        for c in range(self.THUMB_COLS):
            self._grid.setColumnStretch(c, 1)
        scroll.setWidget(inner)
        body.addWidget(scroll, 1)

        self._status_lbl = _mk_label("", role="monoFaint")
        body.addWidget(self._status_lbl)
        return card

    # ---- Viewer column --------------------------------------------------------
    def _viewer_col(self):
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # toolbar: filename + subline + detector combo + cmap pills + buttons
        tb = QFrame()
        tb.setObjectName("cardHeader")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(14)
        self._fn_lbl = _mk_label("—", role="value")
        self._fn_lbl.setFont(mono_font(16, QFont.DemiBold))
        tl.addWidget(self._fn_lbl)
        self._sub_lbl = _mk_label("", font=sans_font(10), color=C["text_dim"])
        tl.addWidget(self._sub_lbl)
        tl.addStretch(1)
        self._det_combo = QComboBox()
        self._det_combo.setCursor(Qt.PointingHandCursor)
        self._det_combo.setVisible(False)
        self._det_combo.currentIndexChanged.connect(self._on_detector_changed)
        tl.addWidget(self._det_combo)
        self._ptycho_combo = QComboBox()
        self._ptycho_combo.setCursor(Qt.PointingHandCursor)
        self._ptycho_combo.addItems(
            ["Object |amplitude|", "Object phase", "Probe |amplitude|"])
        self._ptycho_combo.setVisible(False)
        self._ptycho_combo.currentIndexChanged.connect(self._show_ptycho_view)
        tl.addWidget(self._ptycho_combo)
        tl.addWidget(_cmap_control(self._set_cmap))
        # Thumbnail-load progress lives here (where Levels/Unzoom used to be), so
        # a big directory shows a moving bar instead of freezing.  Hidden idle.
        self._progress = QProgressBar()
        self._progress.setFixedWidth(170)
        self._progress.setTextVisible(True)
        self._progress.setFormat("loading %v/%m")
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{C['well']};border:1px solid {C['border_strong']};"
            f"border-radius:4px;color:{C['text_2']};font-size:11px;"
            f"text-align:center;height:22px;}}"
            f"QProgressBar::chunk{{background:{C['accent_fill']};border-radius:3px;}}")
        tl.addWidget(self._progress)
        savepng = _small_btn("Save PNG", "Export the current view to PNG")
        savepng.clicked.connect(self._save_png)
        tl.addWidget(savepng)
        cl.addWidget(tb)

        # viewer body — pyqtgraph's own histogram / contrast slider is docked on
        # the right inside the ImageView (no separate rail).
        self.viewer = DashboardImageViewer(cmap=self._cmap)
        self.viewer.cursor_changed.connect(self._on_cursor)
        cl.addWidget(self.viewer, 1)

        # footer: energy/frame slider + cursor readout
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QHBoxLayout(footer)
        fv.setContentsMargins(14, 10, 14, 10)
        fv.setSpacing(10)
        self._frame_slider = QSlider(Qt.Horizontal)
        self._frame_slider.setMinimum(0)
        self._frame_slider.setMaximum(0)
        self._frame_slider.setPageStep(1)
        self._frame_slider.setFixedWidth(240)
        self._frame_slider.setCursor(Qt.PointingHandCursor)
        self._frame_slider.setStyleSheet(
            f"QSlider::groove:horizontal{{height:4px;background:{C['well']};"
            f"border:1px solid {C['border']};border-radius:2px;}}"
            f"QSlider::sub-page:horizontal{{background:{C['accent_fill']};"
            f"border:1px solid {C['accent_brdr']};border-radius:2px;}}"
            f"QSlider::handle:horizontal{{background:{C['accent']};width:12px;"
            f"margin:-6px 0;border-radius:6px;}}"
            f"QSlider::handle:horizontal:disabled{{background:{C['border_strong']};}}")
        self._frame_slider.valueChanged.connect(self._on_slider)
        fv.addWidget(self._frame_slider)
        self._frame_lbl = _mk_label("—", role="monoFaint")
        fv.addWidget(self._frame_lbl)
        fv.addStretch(1)
        self._xyi = {}
        for key in ("X", "Y", "I"):
            fv.addWidget(_mk_label(key, font=mono_font(11), color=C["text_dim"]))
            val = _mk_label("—", font=mono_font(11), color=C["text"])
            fv.addWidget(val)
            self._xyi[key] = val
        cl.addWidget(footer)
        return card

    # ---- Details column -------------------------------------------------------
    def _details_col(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        pcard, pbody = _mk_card("Parameters")
        pscroll = QScrollArea()
        pscroll.setWidgetResizable(True)
        pscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pinner = QWidget()
        self._params = QVBoxLayout(pinner)
        self._params.setContentsMargins(14, 4, 14, 4)
        self._params.setSpacing(0)
        self._params.addStretch(1)
        pscroll.setWidget(pinner)
        pbody.addWidget(pscroll, 1)
        v.addWidget(pcard, 1)

        acard, abody = _mk_card("Actions")
        acontent = QWidget()
        av = QVBoxLayout(acontent)
        av.setContentsMargins(14, 14, 14, 14)
        av.setSpacing(10)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self._send_acq_btn = QPushButton("Send to Acquisition")
        self._send_acq_btn.setObjectName("beginScan")
        self._send_acq_btn.setCursor(Qt.PointingHandCursor)
        self._send_acq_btn.setEnabled(False)
        self._send_acq_btn.clicked.connect(self._on_send_acq)
        self._send_ana_btn = QPushButton("Send to Analysis")
        self._send_ana_btn.setCursor(Qt.PointingHandCursor)
        self._send_ana_btn.setEnabled(False)
        self._send_ana_btn.clicked.connect(self._on_send_ana)
        btns.addWidget(self._send_acq_btn, 1)
        btns.addWidget(self._send_ana_btn, 1)
        av.addLayout(btns)
        note = _mk_label(
            "Send to Acquisition loads the scan's region, energy and dwell into "
            "the scan definition; Send to Analysis opens the stack.",
            font=sans_font(10.5), color=C["text_faint"])
        note.setWordWrap(True)
        av.addWidget(note)
        crow = QHBoxLayout()
        crow.setSpacing(8)
        self._comment = QLineEdit()
        self._comment.setPlaceholderText("Comment for logbook…")
        self._comment.setFont(sans_font(11))
        self._comment.returnPressed.connect(self._on_add_log)
        crow.addWidget(self._comment, 1)
        addb = _small_btn("Add to log", "Add this scan (with comment) to the logbook")
        addb.clicked.connect(self._on_add_log)
        crow.addWidget(addb)
        av.addLayout(crow)
        abody.addWidget(acontent)
        v.addWidget(acard)
        return col

    # ── file listing ─────────────────────────────────────────────────────────
    @staticmethod
    def _short_path(path):
        return path if len(path) <= 52 else "…" + path[-49:]

    def set_root(self, path):
        self._root_dir = path
        self._path_lbl.setText(self._short_path(path))
        self._path_lbl.setToolTip(path)

    def _browse_folder(self):
        start = self._root_dir or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(
            self, "Select data root or day folder", start)
        if not folder:
            return
        # A folder that directly holds .stxm files is a day directory; parse its
        # YYMMDD name into the date picker and, if it sits in a
        # root/YYYY/MM/YYMMDD tree, recover the true root — else use it directly.
        try:
            has_stxm = any(f.endswith(".stxm") and "ccdframes" not in f
                           for f in os.listdir(folder))
        except OSError:
            has_stxm = False
        if has_stxm:
            day = os.path.basename(folder)
            if len(day) == 6 and day.isdigit():
                qd = QDate(2000 + int(day[:2]), int(day[2:4]), int(day[4:6]))
                if qd.isValid():
                    self._date_edit.setDate(qd)
            parent = os.path.basename(os.path.dirname(folder))
            gp = os.path.basename(os.path.dirname(os.path.dirname(folder)))
            in_tree = (len(parent) == 2 and parent.isdigit()
                       and len(gp) == 4 and gp.isdigit())
            if in_tree:
                self._direct_day_dir = None
                self.set_root(os.path.dirname(os.path.dirname(os.path.dirname(folder))))
            else:
                self._direct_day_dir = folder
                self.set_root(folder)
        else:
            self._direct_day_dir = None
            self.set_root(folder)
        self._load_for_date()

    def _day_dir(self):
        if self._direct_day_dir and os.path.isdir(self._direct_day_dir):
            return self._direct_day_dir
        d = self._date_edit.date()
        yr, mo, dy = str(d.year()), str(d.month()).zfill(2), str(d.day()).zfill(2)
        return os.path.join(self._root_dir, yr, mo, yr[-2:] + mo + dy)

    def current_day_dir(self):
        """Best-effort current day directory (default base for logbooks)."""
        try:
            return self._day_dir()
        except Exception:
            return self._root_dir or ""

    def _load_for_date(self):
        if not self._root_dir:
            self._status_lbl.setText("Select a folder first")
            return
        if self._loader is not None and self._loader.isRunning():
            self._loader.abort()
            self._loader.wait()
        # clear grid
        for t in self._tiles.values():
            self._grid.removeWidget(t)
            t.deleteLater()
        self._tiles.clear()

        day_dir = self._day_dir()
        self._direct_day_dir = None      # consumed; next Load uses the hierarchy
        if not os.path.isdir(day_dir):
            self._status_lbl.setText(f"Not found: {day_dir}")
            self._count_lbl.setText("0 files")
            return
        filepaths = sorted(
            os.path.join(day_dir, f) for f in os.listdir(day_dir)
            if f.endswith(".stxm") and "ccdframes" not in f)
        self._status_lbl.setText(f"{os.path.basename(day_dir)} · {len(filepaths)} file(s)")

        # Build the tiles and lay them out ONCE.  Thumbnails then stream in on a
        # background thread and update tiles in place — the grid is not re-laid
        # out per file (that O(n²) rebuild is what froze large directories).
        for fp in filepaths:
            tile = BrowserTile(fp)
            tile.set_cmap(self._cmap)
            tile.clicked.connect(self._on_select)
            self._tiles[fp] = tile
        self._render_grid()

        if filepaths:
            self._progress.setMaximum(len(filepaths))
            self._progress.setValue(0)
            self._progress.setVisible(True)
            self._loader = ThumbnailLoader(filepaths, cache=self._cache)
            self._loader.thumbnail_ready.connect(self._on_thumbnail_ready)
            self._loader.progress.connect(self._on_load_progress)
            self._loader.finished.connect(self._on_load_finished)
            self._loader.start()

    def _tile_matches(self, tile):
        return self._filter == "" or self._filter in tile.scan_type.lower()

    def _render_grid(self):
        """Lay the (filtered) tiles into the grid and update the count.  Called
        at load and on filter change — NOT per thumbnail."""
        for i in reversed(range(self._grid.count())):
            self._grid.itemAt(i).widget().setParent(None)
        shown = [fp for fp, t in self._tiles.items() if self._tile_matches(t)]
        for pos, fp in enumerate(shown):
            r, c = divmod(pos, self.THUMB_COLS)
            self._grid.addWidget(self._tiles[fp], r, c)
        self._count_lbl.setText(f"{len(shown)} of {len(self._tiles)} shown")

    def _on_thumbnail_ready(self, filepath, arr, scan_type, start_time, x_range_um):
        tile = self._tiles.get(filepath)
        if tile is None:
            return
        tile.set_thumbnail(arr, scan_type)
        # On the default (empty) filter the tile is already placed; only re-lay
        # out the grid when a filter is active and this tile's match matters.
        if self._filter:
            self._render_grid()

    def _on_load_progress(self, done, total):
        self._progress.setMaximum(total)
        self._progress.setValue(done)

    def _on_load_finished(self):
        self._progress.setVisible(False)
        if self._filter:
            self._render_grid()

    def _set_filter(self, text):
        self._filter = text.strip().lower()
        self._render_grid()

    # ── colormap ─────────────────────────────────────────────────────────────
    def _set_cmap(self, name):
        self._cmap = name
        self.viewer.set_cmap(name)
        for t in self._tiles.values():
            t.set_cmap(name)

    # ── selection / detail ───────────────────────────────────────────────────
    def _on_select(self, filepath):
        self._current_filepath = filepath
        for fp, t in self._tiles.items():
            t.set_selected(fp == filepath)
        self._send_acq_btn.setEnabled(not self._scanning)
        self._send_ana_btn.setEnabled(True)
        self.file_selected.emit(filepath)
        self._show_detail(filepath)

    def _show_detail(self, filepath):
        self._clear_params()
        self.viewer.clear()
        self._fn_lbl.setText(os.path.basename(filepath))
        self._sub_lbl.setText("")
        self._det_data = {}
        self._is_tiled = False
        self._is_spectrum = False
        self._n_frames = 1
        self._frame_idx = 0
        self._ptycho_combo.setVisible(False)

        # Ptychography: show the reconstruction (object amp/phase, probe amp).
        recon = self._find_recon_file(filepath)
        if recon:
            self._show_ptycho(filepath, recon)
            return

        try:
            from pystxmcontrol.utils.writeNX import stxm as stxm_reader
            nx = stxm_reader(stxm_file=filepath)
        except Exception as e:
            self._add_param("Error", str(e))
            return

        meta = nx.meta
        scan_type = meta.get("scan_type", "")
        self._is_spectrum = "Spectrum" in scan_type
        try:
            n_regions = int(getattr(nx, "nRegions", 1) or 1)
        except Exception:
            n_regions = 1
        self._is_tiled = (n_regions > 1 and "Image" in scan_type
                          and not self._is_spectrum)

        start = meta.get("start_time", "")
        self._sub_lbl.setText(f"{scan_type} · {start[:19]}" if start else scan_type)

        energies = np.atleast_1d(nx.data["entry0"].get("energy", np.array([])))
        energy_str = ""
        if energies.size == 1:
            energy_str = f"{float(energies[0]):.1f} eV"
        elif energies.size > 1:
            energy_str = f"{float(energies[0]):.1f}–{float(energies[-1]):.1f} eV"
        dwell_ms = None
        ct = np.atleast_1d(nx.data["entry0"].get("count_time", np.array([])))
        if ct.size:
            dwell_ms = float(ct.flat[0])       # already ms
        source_name = ""
        try:
            with h5py.File(filepath, "r") as _f:
                source_name = _h5str(_f["entry0/instrument/source/name"][()])
        except Exception:
            pass
        self._export_meta = {
            "filename": os.path.basename(filepath),
            "proposal": meta.get("proposal", ""),
            "scan_type": scan_type,
            "sample": meta.get("sample_description", ""),
            "energy": energy_str,
            "dwell_ms": dwell_ms,
            "source": source_name,
        }

        self._load_detector_data(filepath, energies)
        if not self._det_data:
            self._add_param("Note", "No photon detector data found.")
        else:
            self._det_combo.blockSignals(True)
            self._det_combo.clear()
            self._det_combo.addItems(list(self._det_data))
            self._det_combo.blockSignals(False)
            self._det_combo.setVisible(len(self._det_data) > 1)
            self._on_detector_changed(0)

        self._populate_params(filepath, nx)

    def _load_detector_data(self, filepath, energies):
        """Populate ``self._det_data`` from the HDF5 photon detectors, mirroring
        the classic browser's per-detector representation."""
        with h5py.File(filepath, "r") as hf:
            instr = hf.get("entry0/instrument", {})
            if self._is_tiled:
                for det in instr.keys():
                    g = hf[f"entry0/instrument/{det}"]
                    if _h5str(g.attrs.get("type", b"")) != "photon":
                        continue
                    tiles = []
                    ri = 0
                    while f"entry{ri}/{det}/data" in hf:
                        data = hf[f"entry{ri}/{det}/data"][()]
                        img = data[0] if data.ndim == 3 else data
                        xp = np.atleast_1d(hf.get(f"entry{ri}/default/sample_x",
                                                  np.array([]))[()]) \
                            if f"entry{ri}/default/sample_x" in hf else np.array([])
                        yp = np.atleast_1d(hf.get(f"entry{ri}/default/sample_y",
                                                  np.array([]))[()]) \
                            if f"entry{ri}/default/sample_y" in hf else np.array([])
                        xr = float(xp.max() - xp.min()) if xp.size > 1 else 0.0
                        yr = float(yp.max() - yp.min()) if yp.size > 1 else 0.0
                        ny, nx_ = (img.shape if img.ndim == 2 else (1, 1))
                        xs = xr / nx_ if nx_ and xr > 0 else 1.0
                        ys = yr / ny if ny and yr > 0 else 1.0
                        pos = (float(xp.min()) if xp.size else 0.0,
                               float(yp.min()) if yp.size else 0.0)
                        tiles.append((img, xs, ys, pos, xr))
                        ri += 1
                    if tiles:
                        self._det_data[det] = tiles
                return

            xp = np.atleast_1d(hf["entry0/default/sample_x"][()]) \
                if "entry0/default/sample_x" in hf else np.array([])
            yp = np.atleast_1d(hf["entry0/default/sample_y"][()]) \
                if "entry0/default/sample_y" in hf else np.array([])
            x_range = float(xp.max() - xp.min()) if xp.size > 1 else 0.0
            y_range = float(yp.max() - yp.min()) if yp.size > 1 else 0.0
            self._detail_origin = (0.0, 0.0) if self._is_spectrum else (
                float(xp.min()) if xp.size else 0.0,
                float(yp.min()) if yp.size else 0.0)

            for det in instr.keys():
                g = hf[f"entry0/instrument/{det}"]
                if _h5str(g.attrs.get("type", b"")) != "photon":
                    continue
                path = f"entry0/{det}/data"
                if path not in hf:
                    continue
                data = hf[path][()]
                if self._is_spectrum:
                    if data.ndim == 3:
                        d2 = data[:, 0, :]
                    elif data.ndim == 2:
                        d2 = data
                    else:
                        d2 = data.reshape(1, -1)
                    n_e, x_pts = d2.shape
                    e_range = (float(energies.max() - energies.min())
                               if energies.size > 1 else 1.0)
                    xs = e_range / n_e if n_e else 1.0
                    ys = x_range / x_pts if x_pts and x_range > 0 else 1.0
                    self._det_data[det] = (d2.T, xs, ys, x_range)
                else:
                    if data.ndim == 3:
                        _, ny, nx_ = data.shape
                    elif data.ndim == 2:
                        ny, nx_ = data.shape
                    else:
                        ny = nx_ = 1
                    xs = x_range / nx_ if nx_ and x_range > 0 else 1.0
                    ys = y_range / ny if ny and y_range > 0 else 1.0
                    self._det_data[det] = (data, xs, ys, x_range)

    def _on_detector_changed(self, index):
        if index < 0:
            return
        det = self._det_combo.itemText(index) if self._det_combo.count() \
            else next(iter(self._det_data), "")
        if det not in self._det_data:
            return
        aspect = not self._is_spectrum

        if self._is_tiled:
            tiles = self._det_data[det]
            self.viewer.show_tiles(tiles)
            x_range_um = max((t[4] for t in tiles), default=0.0)
            self._set_frame_nav(1, 0)
        else:
            data, xs, ys, x_range_um = self._det_data[det]
            if data.ndim == 3:
                n = self.viewer.show_stack(data, pos=self._detail_origin,
                                           scale=(xs, ys), aspect_locked=aspect)
                self._set_frame_nav(n, min(self._frame_idx, n - 1))
                self.viewer.set_index(self._frame_idx)
            elif data.ndim == 2:
                self.viewer.show_frame(data, pos=self._detail_origin,
                                       scale=(xs, ys), aspect_locked=aspect)
                self._set_frame_nav(1, 0)
            else:
                self.viewer.clear()
                self._set_frame_nav(1, 0)

        # overlay
        m = self._export_meta
        row1 = "   ".join(p for p in [
            m.get("proposal", ""), m.get("scan_type", ""), m.get("sample", ""),
            f"Channel: {det}" if det else ""] if p)
        row2_parts = []
        if not self._is_tiled:
            _, xs, _ys, _xr = self._det_data[det]
            if xs and xs > 0 and not self._is_spectrum:
                row2_parts.append(f"Pixel Size: {xs:.3f} µm")
        if m.get("dwell_ms") is not None:
            row2_parts.append(f"Dwell: {m['dwell_ms']:.3f} ms")
        if m.get("energy"):
            row2_parts.append(f"Energy: {m['energy']}")
        self.viewer.update_overlay(x_range_um, [row1, "   ".join(row2_parts)])

    def _set_frame_nav(self, n_frames, idx):
        self._n_frames = max(1, n_frames)
        self._frame_idx = max(0, min(idx, self._n_frames - 1))
        multi = self._n_frames > 1
        # Sync the slider without re-triggering _on_slider.
        self._frame_slider.blockSignals(True)
        self._frame_slider.setMaximum(self._n_frames - 1)
        self._frame_slider.setValue(self._frame_idx)
        self._frame_slider.blockSignals(False)
        self._frame_slider.setEnabled(multi)
        self._update_frame_label()

    def _update_frame_label(self):
        unit = "position" if self._is_spectrum else "energy"
        if self._n_frames > 1:
            self._frame_lbl.setText(
                f"{unit} {self._frame_idx + 1} of {self._n_frames}")
        else:
            self._frame_lbl.setText(f"1 {unit}" if not self._is_tiled else "tiled")

    def _on_slider(self, value):
        if value == self._frame_idx or self._n_frames <= 1:
            return
        self._frame_idx = value
        self.viewer.set_index(value)
        self._update_frame_label()

    # ── ptychography ──────────────────────────────────────────────────────────
    @staticmethod
    def _find_recon_file(stxm_path):
        base = os.path.splitext(stxm_path)[0]
        matches = glob.glob(base + "_ccdframes_*.h5")
        return matches[0] if matches else None

    def _show_ptycho(self, stxm_path, recon_path):
        """Show a ptychography reconstruction: object |amplitude|, object phase
        (unwrapped) and probe |amplitude|, selectable via the toolbar combo.
        Ports ``DataBrowserWidget._show_ptycho_detail`` onto this viewer."""
        CROP = 400
        try:
            with h5py.File(recon_path, "r") as f:
                obj = f["obj"][()]                          # complex (ny, nx)
                probe = f["probe"][()]                      # complex (modes, H, W)
                obj_basis = f["obj_basis"][()] if "obj_basis" in f else None
                probe_basis = f["probe_basis"][()] if "probe_basis" in f else None
                try:
                    wl_m = float(np.atleast_1d(f["wavelength"][()])[0])
                    energy_str = f"{(1239.8 / wl_m) * 1e-9:.1f} eV"
                except Exception:
                    energy_str = ""
        except Exception as e:
            self._add_param("Error", f"Could not read reconstruction: {e}")
            return

        # Pixel size = length of one basis column (per-axis step), in µm.
        obj_px = float(np.linalg.norm(obj_basis[:, 0]) * 1e6) if obj_basis is not None else 0.0
        probe_px = float(np.linalg.norm(probe_basis[:, 0]) * 1e6) if probe_basis is not None else 0.0

        # Crop object border artefacts when the array is large enough.
        if obj.ndim == 2 and obj.shape[0] > 2 * CROP and obj.shape[1] > 2 * CROP:
            obj_c = obj[CROP:-CROP, CROP:-CROP]
        else:
            obj_c = obj
        obj_amp = np.abs(obj_c)
        obj_phase = np.angle(obj_c)
        try:
            from skimage.restoration import unwrap_phase
            obj_phase = unwrap_phase(obj_phase)
        except Exception:
            pass                                            # wrapped phase fallback
        if probe.ndim == 2:
            probe = probe[None]
        probe_amp = np.sqrt(np.sum(np.abs(probe) ** 2, axis=0))   # incoherent sum

        # Arrays are (y, x); the viewer's _oriented() handles axis order.
        self._ptycho_arrays = [obj_amp, obj_phase, probe_amp]
        self._ptycho_px = [obj_px, obj_px, probe_px]

        self._is_tiled = False
        self._is_spectrum = False
        self._det_combo.setVisible(False)
        self._export_meta = {
            "filename": os.path.basename(stxm_path),
            "scan_type": "Ptychography",
            "proposal": "", "sample": "", "energy": energy_str, "dwell_ms": None,
        }
        self._sub_lbl.setText("Ptychography (reconstruction)")

        self._ptycho_combo.blockSignals(True)
        self._ptycho_combo.setCurrentIndex(0)
        self._ptycho_combo.blockSignals(False)
        self._ptycho_combo.setVisible(True)
        self._show_ptycho_view(0)

        self._add_param("File", os.path.basename(stxm_path))
        self._add_param("Reconstruction", os.path.basename(recon_path))
        if energy_str:
            self._add_param("Energy", energy_str)
        self._add_param("Object shape",
                        f"{obj.shape[0]} × {obj.shape[1]} px  "
                        f"(cropped {obj_c.shape[0]} × {obj_c.shape[1]})")
        self._add_param("Probe modes", str(probe.shape[0]))
        self._add_param("Probe shape", f"{probe.shape[1]} × {probe.shape[2]} px")
        if obj_px:
            self._add_param("Object pixel", f"{obj_px:.4f} µm")
        if probe_px:
            self._add_param("Probe pixel", f"{probe_px:.4f} µm")

    def _show_ptycho_view(self, index):
        """Display the selected ptychography view (object amp/phase, probe amp)."""
        if not self._ptycho_arrays or index < 0:
            return
        arr = self._ptycho_arrays[index]
        px = self._ptycho_px[index] if self._ptycho_px else 0.0
        scale = (px, px) if px > 0 else (1.0, 1.0)
        self.viewer.show_frame(arr, pos=(0.0, 0.0), scale=scale, aspect_locked=True)
        self._set_frame_nav(1, 0)
        label = self._ptycho_combo.itemText(index)
        x_range = px * arr.shape[1] if px > 0 else 0.0   # arr is (y, x)
        row2 = "   ".join(p for p in [
            f"Pixel Size: {px:.4f} µm" if px > 0 else "",
            f"Energy: {self._export_meta.get('energy', '')}"
            if self._export_meta.get("energy") else ""] if p)
        self.viewer.update_overlay(x_range, [f"Ptychography · {label}", row2])

    # ── parameters panel ──────────────────────────────────────────────────────
    def _clear_params(self):
        while self._params.count():
            item = self._params.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)      # remove from view now; deleteLater is async
                w.deleteLater()
        self._params.addStretch(1)

    def _add_param(self, key, value):
        row = QFrame()
        row.setObjectName("rowSep")
        g = QHBoxLayout(row)
        g.setContentsMargins(0, 7, 0, 7)
        g.setSpacing(10)
        k = _mk_label(key, font=sans_font(10.5), color=C["text_dim"])
        k.setFixedWidth(110)
        k.setAlignment(Qt.AlignTop)
        g.addWidget(k)
        v = _mk_label(str(value), role="mono")
        v.setWordWrap(True)
        g.addWidget(v, 1)
        self._params.insertWidget(self._params.count() - 1, row)

    def _populate_params(self, filepath, nx):
        meta = nx.meta
        self._add_param("File", os.path.basename(filepath))
        for label, key in (("Scan type", "scan_type"), ("Start", "start_time"),
                           ("End", "end_time"), ("Experimenters", "experimenters"),
                           ("Sample", "sample_description"), ("Proposal", "proposal")):
            val = meta.get(key, "")
            if val:
                self._add_param(label, val)
        try:
            with h5py.File(filepath, "r") as hf:
                grp = hf["entry0/default"]
                xp = np.atleast_1d(grp["sample_x"][()]) if "sample_x" in grp else np.array([])
                yp = np.atleast_1d(grp["sample_y"][()]) if "sample_y" in grp else np.array([])
                en = np.atleast_1d(grp["energy"][()]) if "energy" in grp else np.array([])
                try:
                    dwell = float(np.atleast_1d(grp["count_time"][()])[0])
                except Exception:
                    dwell = None
                x_motor = _h5str(hf["entry0/default/motor_name_x"][()]) \
                    if "entry0/default/motor_name_x" in hf else meta.get("x_motor", "")
                y_motor = _h5str(hf["entry0/default/motor_name_y"][()]) \
                    if "entry0/default/motor_name_y" in hf else meta.get("y_motor", "")
                motors = []
                if "entry0/instrument/motors" in hf:
                    mgrp = hf["entry0/instrument/motors"]
                    for mname in mgrp.keys():
                        try:
                            motors.append((mname, float(np.atleast_1d(mgrp[mname][()]).flat[0])))
                        except Exception:
                            pass
            if xp.size > 1:
                dx = float(xp[1] - xp[0])
                self._add_param("X range", f"{xp.min():.3f} – {xp.max():.3f} µm  "
                                           f"({xp.size} pts, {dx:.4f} µm/pt)")
            if yp.size > 1:
                dy = float(yp[1] - yp[0])
                self._add_param("Y range", f"{yp.min():.3f} – {yp.max():.3f} µm  "
                                           f"({yp.size} pts, {dy:.4f} µm/pt)")
            if en.size > 0:
                unit = "energy" if en.size == 1 else "energies"
                self._add_param("Energies",
                                f"{en.size} {unit}  {en.min():.2f}–{en.max():.2f} eV")
            if dwell is not None:
                self._add_param("Dwell", f"{dwell:.3f} ms")
            if x_motor:
                self._add_param("X motor", x_motor)
            if y_motor:
                self._add_param("Y motor", y_motor)
            self._add_param("Size", self._human_size(filepath))
            if motors:
                self._add_param("Motor positions",
                                "\n".join(f"{n}: {v:.3f}" for n, v in motors))
        except Exception:
            pass

    @staticmethod
    def _human_size(filepath):
        try:
            b = os.path.getsize(filepath)
        except OSError:
            return ""
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024 or unit == "GB":
                return f"{b:.1f} {unit}" if unit != "B" else f"{int(b)} B"
            b /= 1024

    # ── cursor readout ────────────────────────────────────────────────────────
    def _on_cursor(self, x_um, y_um, value_str):
        self._xyi["X"].setText(f"{x_um:.2f}")
        self._xyi["Y"].setText(f"{y_um:.2f}")
        self._xyi["I"].setText(value_str or "—")

    # ── actions ───────────────────────────────────────────────────────────────
    def set_scanning(self, scanning: bool):
        """Gate the Send-to-Acquisition button while a scan runs."""
        self._scanning = scanning
        self._send_acq_btn.setEnabled(bool(self._current_filepath) and not scanning)

    def _on_send_ana(self):
        if self._current_filepath:
            self.send_to_analysis.emit(self._current_filepath)

    def _on_send_acq(self):
        if self._current_filepath:
            self.send_to_acquisition.emit(self._current_filepath)

    def _save_png(self):
        if self._current_filepath is None:
            return
        base = os.path.splitext(os.path.basename(self._current_filepath))[0]
        default = os.path.join(os.path.dirname(self._current_filepath), base + ".png")
        path, _ = QFileDialog.getSaveFileName(self, "Save PNG", default,
                                              "PNG image (*.png)")
        if not path:
            return
        try:
            from pyqtgraph.exporters import ImageExporter
            exporter = ImageExporter(self.viewer.iv.getView())
            exporter.export(path)
            self._status_lbl.setText(f"Saved {os.path.basename(path)}")
        except Exception as e:
            self._status_lbl.setText(f"PNG export failed: {e}")

    def _on_add_log(self):
        if self._current_filepath is None:
            self._status_lbl.setText("Select a scan first")
            return
        comment = self._comment.text().strip()
        img = self._grab_view_image()
        meta = dict(self._export_meta)
        meta["filename"] = os.path.basename(self._current_filepath)
        try:
            if self.logbook_model is not None and getattr(self.logbook_model, "folder", None):
                self.logbook_model.add(img, meta=meta, comment=comment,
                                       author="human")
            else:
                from pystxmcontrol.utils.logbook import add_entry
                add_entry(self.current_day_dir(), img, meta, comment=comment)
            self._comment.clear()
            self._status_lbl.setText("Added to logbook")
        except Exception as e:
            self._status_lbl.setText(f"Logbook add failed: {e}")

    def _grab_view_image(self):
        """Grab the current viewer render as a QImage for the logbook."""
        try:
            return self.viewer.iv.getView().grab().toImage()
        except Exception:
            return self.viewer.grab().toImage()

    def closeEvent(self, event):
        if self._loader is not None and self._loader.isRunning():
            self._loader.abort()
            self._loader.wait(2000)
        super().closeEvent(event)


# ════════════════════════════════════════════════════════════════════════════
#  Standalone launcher
# ════════════════════════════════════════════════════════════════════════════
def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    app = QApplication(sys.argv)
    icon = os.path.join(_ICONS_DIR, "pystxmcontrol_icon.png")
    if os.path.isfile(icon):
        app.setWindowIcon(QIcon(icon))
    app.setApplicationName("STXM Control — Browser")
    w = BrowserApp()
    w.setWindowTitle("STXM Browser")
    w.resize(1900, 1100)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

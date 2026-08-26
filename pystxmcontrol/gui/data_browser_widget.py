import os
import numpy as np
import h5py
from PySide6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from pystxmcontrol.utils.thumbnail_cache import ThumbnailCache, make_thumbnail_array


# ─────────────────────────── helpers ──────────────────────────────────────────

class _MetadataOverlay:
    """Bottom-anchored metadata bar overlaid on a pyqtgraph ImageView.

    Mirrors the acquisition tab's mainImage overlay: a semi-transparent black background
    bar holding a facility logo, two rows of metadata text, and a white scale bar, all
    pinned to the bottom of the visible view and re-pinned on zoom/pan.
    """
    _NICE = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]

    def __init__(self, image_view, logo_path=None):
        self._vb = image_view.getView()
        self._visible = False

        self._bg = QtWidgets.QGraphicsRectItem()
        self._bg.setBrush(pg.mkBrush(0, 0, 0, 180))
        self._bg.setPen(pg.mkPen(None))
        self._bg.setZValue(5)
        self._vb.addItem(self._bg, ignoreBounds=True)

        # White scale bar (pyqtgraph rescales its pixel width automatically on zoom).
        self._scale = pg.ScaleBar(size=10, suffix='µm', offset=(-20, -20),
                                  brush=pg.mkBrush('w'), pen=pg.mkPen('w'))
        self._scale.text.setColor('w')
        self._scale.setParentItem(self._vb)
        self._scale.setZValue(10)

        # Facility logo (optional).
        self._logo = None
        self._logo_w = 0
        if logo_path:
            pix = QtGui.QPixmap(logo_path)
            if not pix.isNull():
                pix = pix.scaledToHeight(30, QtCore.Qt.SmoothTransformation)
                self._logo = QtWidgets.QGraphicsPixmapItem(pix)
                self._logo.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations, True)
                self._logo.setZValue(10)
                self._vb.addItem(self._logo, ignoreBounds=True)
                self._logo_w = pix.width()

        self._text = pg.TextItem(text='', anchor=(0, 1), color=(220, 220, 220))
        self._text.setFont(QtGui.QFont("Monospace", 8))
        self._text.setZValue(10)
        self._vb.addItem(self._text, ignoreBounds=True)

        self.set_visible(False)
        self._vb.sigRangeChanged.connect(self._reposition)

    @property
    def scale_size(self) -> float:
        """Current scale-bar length in µm (used by the export renderer)."""
        return self._scale.size

    def set_visible(self, visible: bool):
        self._visible = visible
        self._bg.setVisible(visible)
        self._scale.setVisible(visible)
        self._text.setVisible(visible)
        if self._logo is not None:
            self._logo.setVisible(visible)

    def update(self, x_range_um, rows):
        """Set the scale-bar size from the field of view and the metadata text rows."""
        rows = [r for r in rows if r]
        if x_range_um and x_range_um > 0:
            target = x_range_um / 5.0
            bar_um = min(self._NICE, key=lambda v: abs(v - target))
            self._scale.size = bar_um
            self._scale.updateBar()
            self._scale.text.setText(f"{bar_um * 1000:g} nm" if bar_um < 1.0
                                     else f"{bar_um:g} µm")
        self._text.setText('\n'.join(rows))
        self.set_visible(bool(rows))
        self._reposition()

    def _reposition(self, *args):
        if not self._visible:
            return
        r = self._vb.viewRange()
        px_w, px_h = self._vb.viewPixelSize()
        bar_h_data = 48 * abs(px_h)
        x0, x1 = r[0][0], r[0][1]
        y_bottom = r[1][1]                       # visual bottom (views use invertY)
        x_pad = (x1 - x0) * 0.01
        y_pad = (r[1][1] - r[1][0]) * 0.01

        self._bg.setRect(x0, y_bottom - bar_h_data, x1 - x0, bar_h_data)
        if self._logo is not None and self._logo_w > 0:
            logo_h_data = 30 * abs(px_h)
            self._logo.setPos(x0 + x_pad, y_bottom - logo_h_data - 1.5 * y_pad)
            logo_gap_data = (self._logo_w + 6) * abs(px_w)
        else:
            logo_gap_data = 0
        self._text.setPos(x0 + logo_gap_data + x_pad, y_bottom - y_pad)


def _array_to_pixmap(arr, width=128, height=128):
    """Convert a 2-D numpy array to a scaled grayscale QPixmap."""
    if arr is None or arr.size == 0:
        return None
    arr = arr.astype(float)
    mn, mx = arr.min(), arr.max()
    if mx > mn:
        arr = ((arr - mn) / (mx - mn) * 255).astype(np.uint8)
    else:
        arr = np.zeros_like(arr, dtype=np.uint8)
    h_px, w_px = arr.shape
    rgb = np.ascontiguousarray(np.stack([arr, arr, arr], axis=-1))
    qimage = QtGui.QImage(
        rgb.tobytes(), w_px, h_px, 3 * w_px, QtGui.QImage.Format_RGB888
    )
    pixmap = QtGui.QPixmap.fromImage(qimage)
    return pixmap.scaled(
        width, height, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
    )


def _h5str(val) -> str:
    """Return a plain str from an h5py scalar that may be bytes or str.

    h5py 2.x returns bytes for string datasets; h5py 3.x returns str.
    Both cases are handled here so callers don't need .decode().
    """
    if isinstance(val, (list, np.ndarray)):
        val = val[0]
    if isinstance(val, (bytes, np.bytes_)):
        return val.decode()
    return str(val)


def _read_scan_footprint(filepath):
    """Read a scan's sample-XY footprint in motor µm.

    Returns ``(x_min, x_max, y_min, y_max, x_motor, y_motor)`` unioned across all
    ``entry*`` regions, or ``None`` if the file has no usable sample-XY extent.
    """
    x_lo = y_lo = float("inf")
    x_hi = y_hi = float("-inf")
    x_motor = y_motor = ""
    try:
        with h5py.File(filepath, "r") as hf:
            for ekey in (k for k in hf.keys() if k.startswith("entry")):
                grp = hf.get(f"{ekey}/default")
                if grp is None or "sample_x" not in grp or "sample_y" not in grp:
                    continue
                xp = np.atleast_1d(grp["sample_x"][()])
                yp = np.atleast_1d(grp["sample_y"][()])
                if xp.size == 0 or yp.size == 0:
                    continue
                x_lo, x_hi = min(x_lo, float(xp.min())), max(x_hi, float(xp.max()))
                y_lo, y_hi = min(y_lo, float(yp.min())), max(y_hi, float(yp.max()))
                if not x_motor and "motor_name_x" in grp:
                    x_motor = _h5str(grp["motor_name_x"][()])
                if not y_motor and "motor_name_y" in grp:
                    y_motor = _h5str(grp["motor_name_y"][()])
    except Exception:
        return None
    if x_hi <= x_lo or y_hi <= y_lo:
        return None
    return (x_lo, x_hi, y_lo, y_hi, x_motor, y_motor)


def _get_version(f):
    """Return the numeric nexus version from an open h5py.File."""
    try:
        definition = f["entry0/definition"][()]
        if isinstance(definition, (list, np.ndarray)):
            definition = definition[0]
        if isinstance(definition, bytes):
            definition = definition.decode()
        if definition == "NXstxm":
            try:
                return float(f["entry0/version"][()])
            except Exception:
                return 3.0
        else:
            try:
                return float(definition)
            except Exception:
                return 0.0
    except Exception:
        return 0.0


def _load_preview(filepath):
    """
    Open a .stxm file and return (arr_2d, scan_type, start_time, x_range_um).
    arr_2d may be None if image data cannot be read.
    x_range_um is 0.0 if the physical scale cannot be determined.
    """
    with h5py.File(filepath, "r") as f:
        version = _get_version(f)
        scan_type = ""
        start_time = ""
        arr = None
        x_range_um = 0.0
        n_frames = 1

        if version >= 3.0:
            try:
                scan_type = _h5str(f["entry0/default/stxm_scan_type"][0])
            except Exception:
                pass
            try:
                start_time = _h5str(f["entry0/start_time"][()])
            except Exception:
                pass
            # find first photon detector and use its interpolated data
            try:
                for key in f["entry0/instrument"].keys():
                    grp = f[f"entry0/instrument/{key}"]
                    if (
                        "type" in grp.attrs
                        and _h5str(grp.attrs["type"]) == "photon"
                    ):
                        data_path = f"entry0/{key}/data"
                        if data_path in f:
                            data = f[data_path][()]
                            if data.ndim == 3:
                                n_frames = data.shape[0]
                                if "Spectrum" in scan_type and data.shape[1] == 1:
                                    # (n_energies, 1, x_pts) → transpose to
                                    # (x_pts, n_energies): spatial rows, energy cols
                                    arr = data[:, 0, :].T
                                else:
                                    arr = data[0]
                            elif data.ndim == 2:
                                if "Spectrum" in scan_type:
                                    arr = data.T  # (n_energies, x_pts) → (x_pts, n_energies)
                                else:
                                    arr = data
                            break
            except Exception:
                pass
            try:
                xpos = f["entry0/default/sample_x"][()]
                x_range_um = float(xpos.max() - xpos.min())
            except Exception:
                pass

        else:
            try:
                scan_type = _h5str(f["entry0/counter0/stxm_scan_type"][()][0])
            except Exception:
                pass
            try:
                start_time = _h5str(f["entry0/start_time"][()])
            except Exception:
                pass
            try:
                data = f["entry0/counter0/data"][()]
                if data.ndim == 3:
                    n_frames = data.shape[0]
                    if "Spectrum" in scan_type and data.shape[1] == 1:
                        arr = data[:, 0, :].T
                    else:
                        arr = data[0]
                elif data.ndim == 2:
                    arr = data.T if "Spectrum" in scan_type else data
            except Exception:
                pass
            try:
                xpos = f["entry0/counter0/sample_x"][()]
                x_range_um = float(xpos.max() - xpos.min())
            except Exception:
                pass

    if n_frames > 1:
        if scan_type == "Image":
            scan_type = "Stack"
        else:
            scan_type = scan_type.replace(" Image", " Stack")

    # For ptychography files, replace the stxm thumbnail with the cropped
    # object amplitude from the companion reconstruction .h5 file.
    if "ptycho" in scan_type.lower():
        import glob as _glob
        base = os.path.splitext(filepath)[0]
        recon_matches = _glob.glob(base + "_ccdframes_*.h5")
        if recon_matches:
            try:
                CROP = 400
                with h5py.File(recon_matches[0], "r") as rf:
                    obj = rf["obj"][()]
                obj_cropped = obj[CROP:-CROP, CROP:-CROP]
                arr = np.abs(obj_cropped)
            except Exception:
                pass  # fall back to stxm image if recon can't be read

    return arr, scan_type, start_time, x_range_um


# ───────────────────────── ThumbnailLoader ────────────────────────────────────

class ThumbnailLoader(QtCore.QThread):
    """Background thread: reads preview data from .stxm files one by one.

    Checks the ThumbnailCache first; only opens the HDF5 file on a cache miss,
    then writes the result back to the cache so subsequent loads are instant.
    """

    # filepath, arr (may be None), scan_type, start_time, x_range_um
    thumbnail_ready = QtCore.Signal(str, object, str, str, float)
    # (n_done, n_total)
    progress = QtCore.Signal(int, int)

    def __init__(self, filepaths, cache=None, parent=None):
        super().__init__(parent)
        self.filepaths = filepaths
        self.cache = cache
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        total = len(self.filepaths)
        for i, fp in enumerate(self.filepaths):
            if self._abort:
                break

            # ── cache hit ────────────────────────────────────────────────────
            if self.cache is not None:
                hit = self.cache.get(fp)
                if hit is not None:
                    arr, scan_type, start_time, x_range_um = hit
                    self.thumbnail_ready.emit(fp, arr, scan_type, start_time, x_range_um)
                    self.progress.emit(i + 1, total)
                    continue

            # ── cache miss: read from HDF5 ────────────────────────────────
            arr, scan_type, start_time, x_range_um = None, "", "", 0.0
            try:
                arr, scan_type, start_time, x_range_um = _load_preview(fp)
            except Exception:
                pass

            if self.cache is not None:
                self.cache.put(fp, arr, scan_type, start_time, x_range_um)

            thumb = make_thumbnail_array(arr) if arr is not None else None
            self.thumbnail_ready.emit(fp, thumb, scan_type, start_time, x_range_um)
            self.progress.emit(i + 1, total)


# ───────────────────────── ThumbnailCard ──────────────────────────────────────

class ThumbnailCard(QtWidgets.QWidget):
    """A clickable card showing a small preview image and scan metadata.

    Two independent visual states:
    - ``selected`` (left-click): the card whose scan is currently displayed in the
      detail view — blue border + tint.
    - ``marked`` (right-click): the card is in the ROI-mapping set — green border and a
      numbered badge giving its map order. A card can be both selected and marked.
    """

    clicked = QtCore.Signal(str)        # left-click: emits filepath (show in detail view)
    right_clicked = QtCore.Signal(str)  # right-click: emits filepath (toggle ROI mapping)

    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.setObjectName("ThumbnailCard")
        self.filepath = filepath
        self.setFixedSize(152, 188)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self._selected = False
        self._marked = False
        self._build_ui()
        self._refresh_style()

    def _build_ui(self):
        self.scan_type = ""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(2)
        layout.setContentsMargins(5, 5, 5, 5)

        self.image_label = QtWidgets.QLabel("loading…")
        self.image_label.setFixedSize(128, 128)
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid #333; background-color: #222;")

        # Numbered badge shown at the top-left when the card is marked for ROI mapping.
        # A child of the card (not in the layout) so it floats over the thumbnail corner.
        self.badge = QtWidgets.QLabel("", self)
        self.badge.setAlignment(QtCore.Qt.AlignCenter)
        self.badge.setFixedSize(20, 20)
        self.badge.move(9, 9)
        self.badge.setStyleSheet(
            "background-color: #2e7d32; color: white; border-radius: 10px;"
            " font-weight: bold; font-size: 11px;"
        )
        self.badge.hide()

        fname = os.path.basename(self.filepath)
        self.name_label = QtWidgets.QLabel(fname)
        self.name_label.setAlignment(QtCore.Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        small = self.name_label.font()
        small.setPointSize(7)
        self.name_label.setFont(small)

        self.type_label = QtWidgets.QLabel()
        self.type_label.setAlignment(QtCore.Qt.AlignCenter)
        italic = QtGui.QFont(small)
        italic.setItalic(True)
        self.type_label.setFont(italic)

        layout.addWidget(self.image_label, alignment=QtCore.Qt.AlignCenter)
        layout.addWidget(self.name_label)
        layout.addWidget(self.type_label)

    def set_thumbnail(self, arr, scan_type, start_time, x_range_um=0.0):
        self.scan_type = scan_type
        if arr is not None:
            pixmap = _array_to_pixmap(arr, 128, 128)
            if pixmap:
                self.image_label.setPixmap(pixmap)
                self.image_label.setText("")
            else:
                self.image_label.setText("N/A")
        else:
            self.image_label.setText("N/A")
        self.type_label.setText(scan_type)
        if start_time:
            self.setToolTip(f"{os.path.basename(self.filepath)}\n{start_time}")

    def set_selected(self, selected):
        self._selected = selected
        self._refresh_style()

    def set_marked(self, marked, number=None):
        """Mark/unmark this card for ROI mapping; ``number`` sets the badge label."""
        self._marked = marked
        if marked and number is not None:
            self.badge.setText(str(number))
            self.badge.show()
            self.badge.raise_()
        else:
            self.badge.hide()
        self._refresh_style()

    def _refresh_style(self):
        # Marked (green) takes border precedence over selected (blue); selected adds a
        # background tint so a card that is both reads as "displayed and mapped".
        border = "#2e7d32" if self._marked else ("#4a9fd5" if self._selected else "#555")
        width = "2px" if (self._marked or self._selected) else "1px"
        bg = "  background-color: rgba(74,159,213,30);" if self._selected else ""
        self.setStyleSheet(
            f"QWidget#ThumbnailCard {{ border: {width} solid {border};"
            f" border-radius: 4px;{bg} }}"
        )

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(self.filepath)
        elif event.button() == QtCore.Qt.RightButton:
            self.right_clicked.emit(self.filepath)
        super().mousePressEvent(event)


# ───────────────────────── DataBrowserWidget ─────────────────────────────────

class DataBrowserWidget(QtWidgets.QWidget):
    """
    Browser panel for the main window's Browser tab.

    Shows a scrollable grid of thumbnail cards for all .stxm files in the
    selected day's directory.  Clicking a card loads a larger image view
    and a metadata/parameters summary in the right panel.
    """

    THUMB_COLS = 3

    # Emitted when the user clicks a thumbnail card — carries the file path.
    file_selected = QtCore.Signal(str)
    # Emitted when the user clicks "Send to Analysis" — carries the file path.
    send_to_analysis = QtCore.Signal(str)
    # Emitted when the user clicks "Send to Acquisition" — carries the file path.
    send_to_acquisition = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_dir = ""
        self._direct_day_dir = None   # set when user browses to a flat YYMMDD folder
        self._cards = {}      # filepath -> ThumbnailCard
        self._loader = None
        self._cache = ThumbnailCache()
        self._detail_overlay = None   # _MetadataOverlay on detail_image
        self._ptycho_overlay = None   # _MetadataOverlay on ptycho_image
        self._ptycho_pixel_um = []   # pixel size in µm per dropdown index
        self._current_filepath = ""
        self._export_meta = {}
        self._scanning = False   # gates "Send to Acquisition" while a scan is running
        self._is_tiled_detail = False
        self._detail_origin = (0.0, 0.0)  # (x_min, y_min) motor position of non-tiled detail image
        self._browser_tile_items = []   # pg.ImageItems added for tiled composite display
        self._map_selection = []        # filepaths right-click-marked for ROI mapping, in order
        self._map_overlay_items = []    # rect/label items drawn on the overview for "Map Selected"
        self._setup_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        # ── top bar ───────────────────────────────────────────────────────────
        top_bar = QtWidgets.QHBoxLayout()
        top_bar.setSpacing(6)

        browse_btn = QtWidgets.QPushButton("Browse folder")
        browse_btn.clicked.connect(self._browse_folder)
        top_bar.addWidget(browse_btn)

        self.root_label = QtWidgets.QLabel("(no folder selected)")
        self.root_label.setStyleSheet("color: #888;")
        top_bar.addWidget(self.root_label, stretch=1)

        top_bar.addWidget(QtWidgets.QLabel("Date:"))
        self.date_edit = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setFixedWidth(110)
        top_bar.addWidget(self.date_edit)

        load_btn = QtWidgets.QPushButton("Load")
        load_btn.setFixedWidth(55)
        load_btn.clicked.connect(self._load_for_date)
        top_bar.addWidget(load_btn)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setMinimumWidth(90)
        top_bar.addWidget(self.status_label)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setMinimumWidth(120)
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        top_bar.addWidget(self.progress_bar)

        main_layout.addLayout(top_bar)

        # ── splitter ──────────────────────────────────────────────────────────
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)

        # Left: scrollable thumbnail grid + filter bar
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setMinimumWidth(180)

        self._thumb_container = QtWidgets.QWidget()
        self._thumb_grid = QtWidgets.QGridLayout(self._thumb_container)
        self._thumb_grid.setSpacing(8)
        self._thumb_grid.setContentsMargins(8, 8, 8, 8)
        self._thumb_grid.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self._scroll.setWidget(self._thumb_container)
        left_layout.addWidget(self._scroll, stretch=1)

        filter_bar = QtWidgets.QHBoxLayout()
        filter_bar.addWidget(QtWidgets.QLabel("Filter:"))
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("scan type…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self.filter_edit)
        left_layout.addLayout(filter_bar)

        splitter.addWidget(left_panel)

        # Right: detail panel
        detail_panel = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(4)

        # Stacked widget: page 0 = normal scan, page 1 = ptychography reconstruction
        self.detail_stack = QtWidgets.QStackedWidget()

        # ── page 0: normal scan view with optional detector selector ─────────
        normal_page = QtWidgets.QWidget()
        normal_layout = QtWidgets.QVBoxLayout(normal_page)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.setSpacing(4)

        self._detector_bar = QtWidgets.QHBoxLayout()
        self._detector_bar.addWidget(QtWidgets.QLabel("Detector:"))
        self.detector_combo = QtWidgets.QComboBox()
        self.detector_combo.currentIndexChanged.connect(self._on_detector_changed)
        self._detector_bar.addWidget(self.detector_combo)
        self._detector_bar.addStretch()
        self._detector_bar_widget = QtWidgets.QWidget()
        self._detector_bar_widget.setLayout(self._detector_bar)
        normal_layout.addWidget(self._detector_bar_widget)

        self.detail_image = pg.ImageView()
        normal_layout.addWidget(self.detail_image, stretch=1)
        _logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'icons', 'als-logo.png')
        self._detail_overlay = _MetadataOverlay(self.detail_image, logo_path=_logo_path)

        self.detail_stack.addWidget(normal_page)
        self._stxm_detector_data = {}  # {detector_name: (data_array, x_scale, y_scale, x_range_um)}

        # ── page 1: single ptychography view with dropdown selector ──────────
        ptycho_page = QtWidgets.QWidget()
        ptycho_layout = QtWidgets.QVBoxLayout(ptycho_page)
        ptycho_layout.setContentsMargins(0, 0, 0, 0)
        ptycho_layout.setSpacing(4)

        ptycho_bar = QtWidgets.QHBoxLayout()
        ptycho_bar.addWidget(QtWidgets.QLabel("Show:"))
        self.ptycho_selector = QtWidgets.QComboBox()
        self.ptycho_selector.addItems(["Object |amplitude|", "Object phase", "Probe |amplitude|"])
        self.ptycho_selector.currentIndexChanged.connect(self._on_ptycho_selection_changed)
        ptycho_bar.addWidget(self.ptycho_selector)
        ptycho_bar.addStretch()
        ptycho_layout.addLayout(ptycho_bar)

        self.ptycho_image = pg.ImageView()
        ptycho_layout.addWidget(self.ptycho_image, stretch=1)
        self._ptycho_overlay = _MetadataOverlay(self.ptycho_image, logo_path=_logo_path)

        self.detail_stack.addWidget(ptycho_page)
        self._ptycho_arrays = []   # [obj_amp, obj_phase, probe_amp]

        detail_layout.addWidget(self.detail_stack, stretch=1)

        export_bar = QtWidgets.QHBoxLayout()

        export_btn = QtWidgets.QPushButton("Export PNG")
        export_btn.setFixedWidth(100)
        export_btn.clicked.connect(self._export_png)
        export_bar.addWidget(export_btn)

        add_log_btn = QtWidgets.QPushButton("Add to log")
        add_log_btn.setFixedWidth(90)
        add_log_btn.clicked.connect(self._add_to_log)
        export_bar.addWidget(add_log_btn)

        # ROI mapping: right-click thumbnails to mark them, then overlay their scan
        # footprints on the currently displayed overview image.
        self.map_btn = QtWidgets.QPushButton("Map Selected")
        self.map_btn.setFixedWidth(110)
        self.map_btn.setToolTip(
            "Overlay the scan regions of right-click-marked thumbnails as labelled "
            "boxes on the displayed overview image."
        )
        self.map_btn.setEnabled(False)
        self.map_btn.clicked.connect(self._map_selected)
        export_bar.addWidget(self.map_btn)

        self.clear_map_btn = QtWidgets.QPushButton("Clear Map")
        self.clear_map_btn.setFixedWidth(85)
        self.clear_map_btn.setEnabled(False)
        self.clear_map_btn.clicked.connect(self._clear_map)
        export_bar.addWidget(self.clear_map_btn)

        self.log_comment_edit = QtWidgets.QLineEdit()
        self.log_comment_edit.setPlaceholderText("Comment for logbook…")
        export_bar.addWidget(self.log_comment_edit, stretch=1)

        self.send_analysis_btn = QtWidgets.QPushButton("Send to Analysis")
        self.send_analysis_btn.setFixedWidth(130)
        self.send_analysis_btn.setEnabled(False)
        self.send_analysis_btn.clicked.connect(self._on_send_to_analysis)
        export_bar.addWidget(self.send_analysis_btn)

        self.send_acquisition_btn = QtWidgets.QPushButton("Send to Acquisition")
        self.send_acquisition_btn.setFixedWidth(150)
        self.send_acquisition_btn.setEnabled(False)
        self.send_acquisition_btn.clicked.connect(self._on_send_to_acquisition)
        export_bar.addWidget(self.send_acquisition_btn)

        detail_layout.addLayout(export_bar)

        self.cursor_label = QtWidgets.QLabel("")
        self.cursor_label.setStyleSheet("font-family: monospace; color: #aaaaff;")
        detail_layout.addWidget(self.cursor_label)

        self.detail_text = QtWidgets.QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(230)
        self.detail_text.setFontFamily("Monospace")
        detail_layout.addWidget(self.detail_text)

        self._mouse_proxy = pg.SignalProxy(
            self.detail_image.scene.sigMouseMoved,
            rateLimit=30, slot=self._on_detail_mouse_moved
        )

        splitter.addWidget(detail_panel)
        splitter.setSizes([490, 900])
        main_layout.addWidget(splitter, stretch=1)

    # ── public API ────────────────────────────────────────────────────────────

    def set_root(self, path):
        """Set the root data directory (contains YYYY/MM/YYMMDD sub-dirs)."""
        self._root_dir = path
        short = path if len(path) <= 60 else "…" + path[-57:]
        self.root_label.setText(short)
        self.root_label.setToolTip(path)
        self.root_label.setStyleSheet("")

    # ── folder / date helpers ─────────────────────────────────────────────────

    def _browse_folder(self):
        start = self._root_dir or os.path.expanduser("~")
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select data root folder", start
        )
        if not folder:
            return

        # If the selected folder directly contains .stxm files it is a day
        # directory (YYMMDD).  Walk up three levels to get the true root and
        # parse the date so the date picker stays consistent.
        try:
            has_stxm = any(
                f.endswith(".stxm") and "ccdframes" not in f
                for f in os.listdir(folder)
            )
        except OSError:
            has_stxm = False

        if has_stxm:
            day_name = os.path.basename(folder)   # e.g. "260327"
            # try to parse YYMMDD → set the date picker
            if len(day_name) == 6 and day_name.isdigit():
                yy, mm, dd = int(day_name[0:2]), int(day_name[2:4]), int(day_name[4:6])
                yyyy = 2000 + yy
                qdate = QtCore.QDate(yyyy, mm, dd)
                if qdate.isValid():
                    self.date_edit.setDate(qdate)
            # Check whether folder sits in the expected root/YYYY/MM/YYMMDD hierarchy.
            # If not (e.g. ~/Downloads/251106), store the path directly rather than
            # walking 3 levels up and computing a wrong root.
            parent_name = os.path.basename(os.path.dirname(folder))
            grandparent_name = os.path.basename(os.path.dirname(os.path.dirname(folder)))
            in_hierarchy = (
                len(parent_name) == 2 and parent_name.isdigit() and
                len(grandparent_name) == 4 and grandparent_name.isdigit()
            )
            if in_hierarchy:
                self._direct_day_dir = None
                true_root = os.path.dirname(os.path.dirname(os.path.dirname(folder)))
                self.set_root(true_root)
            else:
                self._direct_day_dir = folder
                self.set_root(folder)
        else:
            self._direct_day_dir = None
            self.set_root(folder)

        self._load_for_date()

    def _get_day_dir(self, date):
        yr = str(date.year())
        mo = str(date.month()).zfill(2)
        dy = str(date.day()).zfill(2)
        day_str = yr[-2:] + mo + dy          # e.g. "260327"
        return os.path.join(self._root_dir, yr, mo, day_str)

    def current_day_dir(self) -> str:
        """Best-effort current day directory (used as a default base for logbooks).
        May not exist yet; returns "" if no root is set."""
        if self._direct_day_dir and os.path.isdir(self._direct_day_dir):
            return self._direct_day_dir
        if self._root_dir:
            try:
                return self._get_day_dir(self.date_edit.date())
            except Exception:
                return self._root_dir
        return ""

    def _load_for_date(self):
        if not self._root_dir:
            self.status_label.setText("Select a folder first")
            return

        # abort any in-flight loader
        if self._loader is not None and self._loader.isRunning():
            self._loader.abort()
            self._loader.wait()

        # clear existing thumbnails and any ROI-mapping selection (cards are recreated)
        self._clear_map()
        for card in self._cards.values():
            self._thumb_grid.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        date = self.date_edit.date()
        if self._direct_day_dir and os.path.isdir(self._direct_day_dir):
            day_dir = self._direct_day_dir
            self._direct_day_dir = None   # consumed; next Load uses normal hierarchy
        else:
            day_dir = self._get_day_dir(date)

        if not os.path.isdir(day_dir):
            self.status_label.setText("Not found")
            self.status_label.setToolTip(f"Looked for:\n{day_dir}")
            return

        self.status_label.setToolTip("")

        filepaths = sorted(
            os.path.join(day_dir, f)
            for f in os.listdir(day_dir)
            if f.endswith(".stxm") and "ccdframes" not in f
        )

        self.status_label.setText(f"{len(filepaths)} file(s)")

        for i, fp in enumerate(filepaths):
            card = ThumbnailCard(fp)
            card.clicked.connect(self._on_card_clicked)
            card.right_clicked.connect(self._on_card_right_clicked)
            self._thumb_grid.addWidget(
                card, i // self.THUMB_COLS, i % self.THUMB_COLS
            )
            self._cards[fp] = card

        # start background thumbnail loading
        self.progress_bar.setMaximum(len(filepaths))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(len(filepaths) > 0)

        self._loader = ThumbnailLoader(filepaths, cache=self._cache)
        self._loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._loader.progress.connect(self._on_load_progress)
        self._loader.finished.connect(self._on_load_finished)
        self._loader.start()

    # ── slots ─────────────────────────────────────────────────────────────────

    def _apply_filter(self, text=""):
        ftext = self.filter_edit.text().strip().lower()
        for card in self._cards.values():
            card.setVisible(not ftext or ftext in card.scan_type.lower())

    def _on_thumbnail_ready(self, filepath, arr, scan_type, start_time, x_range_um):
        card = self._cards.get(filepath)
        if card:
            card.set_thumbnail(arr, scan_type, start_time, x_range_um)
            ftext = self.filter_edit.text().strip().lower()
            if ftext:
                card.setVisible(ftext in card.scan_type.lower())

    def _on_load_progress(self, done, total):
        self.progress_bar.setValue(done)

    def _on_load_finished(self):
        self.progress_bar.setVisible(False)

    def _on_card_clicked(self, filepath):
        for fp, card in self._cards.items():
            card.set_selected(fp == filepath)
        self._show_detail(filepath)
        self.send_analysis_btn.setEnabled(True)
        # Don't re-enable "Send to Acquisition" while a scan is running.
        self.send_acquisition_btn.setEnabled(not self._scanning)
        self.file_selected.emit(filepath)

    # ── ROI mapping ─────────────────────────────────────────────────────────────

    def _on_card_right_clicked(self, filepath):
        """Toggle a thumbnail in the ROI-mapping set and renumber the badges."""
        if filepath in self._map_selection:
            self._map_selection.remove(filepath)
        else:
            self._map_selection.append(filepath)
        self._refresh_map_badges()
        self._update_map_buttons()

    def _refresh_map_badges(self):
        """Sync each card's marked state and badge number to the selection order."""
        order = {fp: i + 1 for i, fp in enumerate(self._map_selection)}
        for fp, card in self._cards.items():
            card.set_marked(fp in order, order.get(fp))

    def _update_map_buttons(self):
        n = len(self._map_selection)
        self.map_btn.setText(f"Map Selected ({n})" if n else "Map Selected")
        self.map_btn.setEnabled(n > 0 and bool(self._current_filepath))
        self.clear_map_btn.setEnabled(n > 0 or bool(self._map_overlay_items))

    def _clear_map_overlay(self):
        """Remove the drawn ROI boxes/labels from the overview, keeping the selection."""
        view = self.detail_image.getView()
        for item in self._map_overlay_items:
            try:
                view.removeItem(item)
            except Exception:
                pass
        self._map_overlay_items = []
        if hasattr(self, "clear_map_btn"):
            self._update_map_buttons()

    def _clear_map(self):
        """Full reset: remove drawn boxes, unmark all thumbnails, empty the selection."""
        self._clear_map_overlay()
        self._map_selection = []
        for card in self._cards.values():
            card.set_marked(False)
        self._update_map_buttons()

    @staticmethod
    def _read_scan_footprint(filepath):
        """Scan footprint in motor µm — see the module-level helper of the same
        name, shared with the dashboard browser."""
        return _read_scan_footprint(filepath)

    def _map_selected(self):
        """Overlay each marked scan's footprint as a labelled box on the overview image."""
        if not self._current_filepath or not self._map_selection:
            return
        # Boxes are drawn on the normal STXM view (page 0). A ptychography reconstruction
        # is shown on a different view, so mapping there would draw onto a hidden widget.
        if self.detail_stack.currentIndex() != 0:
            QtWidgets.QMessageBox.information(
                self, "Map Selected",
                "Display a normal STXM scan as the overview before mapping regions."
            )
            return

        self._clear_map_overlay()
        overview = self._read_scan_footprint(self._current_filepath)
        ov_xmot, ov_ymot = (overview[4], overview[5]) if overview else ("", "")

        view = self.detail_image.getView()
        # Distinct colours cycled per box; cosmetic pens keep a constant on-screen width.
        colors = ["#ff5252", "#ffd740", "#69f0ae", "#40c4ff", "#e040fb",
                  "#ffab40", "#b2ff59", "#64ffda"]
        mismatched = []
        drawn = 0
        for i, fp in enumerate(self._map_selection):
            fprint = self._read_scan_footprint(fp)
            if fprint is None:
                continue
            x_lo, x_hi, y_lo, y_hi, x_mot, y_mot = fprint
            # Flag scans taken on different motors than the overview — their µm
            # coordinates may not correspond, so the box position is unreliable.
            if overview and ((ov_xmot and x_mot and x_mot != ov_xmot) or
                             (ov_ymot and y_mot and y_mot != ov_ymot)):
                mismatched.append(os.path.basename(fp))

            color = QtGui.QColor(colors[i % len(colors)])
            pen = pg.mkPen(color, width=2)
            pen.setCosmetic(True)
            rect = QtWidgets.QGraphicsRectItem(x_lo, y_lo, x_hi - x_lo, y_hi - y_lo)
            rect.setPen(pen)
            view.addItem(rect, ignoreBounds=True)
            self._map_overlay_items.append(rect)

            label = pg.TextItem(str(i + 1), color="w", anchor=(0, 0),
                                fill=pg.mkBrush(color))
            label.setPos(x_lo, y_hi)   # top-left corner in data coords (y increases upward)
            view.addItem(label, ignoreBounds=True)
            self._map_overlay_items.append(label)
            drawn += 1

        self._update_map_buttons()
        if mismatched:
            QtWidgets.QMessageBox.warning(
                self, "Motor mismatch",
                "These scans use different X/Y motors than the overview, so their box "
                "positions may be wrong:\n\n  " + "\n  ".join(mismatched)
            )

    def set_scanning(self, scanning: bool):
        """Enable/disable 'Send to Acquisition' based on whether a scan is running.

        Pushing a stored scan's configuration into the Acquisition tab mid-scan could clobber
        the running scan's setup, so the button is disabled while scanning. The state is kept
        so selecting a file card does not re-enable it during a scan; it is restored when the
        scan finishes if a file is currently selected.
        """
        self._scanning = scanning
        self.send_acquisition_btn.setEnabled(not scanning and bool(self._current_filepath))

    def _on_send_to_analysis(self):
        if self._current_filepath:
            self.send_to_analysis.emit(self._current_filepath)

    def _on_send_to_acquisition(self):
        if self._scanning:
            return
        if self._current_filepath:
            self.send_to_acquisition.emit(self._current_filepath)

    @staticmethod
    def _find_recon_file(stxm_path):
        """Return path to a ptychography reconstruction .h5 alongside stxm_path, or None."""
        import glob
        base = os.path.splitext(stxm_path)[0]   # strip .stxm
        pattern = base + "_ccdframes_*.h5"
        matches = glob.glob(pattern)
        return matches[0] if matches else None

    def _clear_browser_tile_items(self):
        for item in self._browser_tile_items:
            try:
                self.detail_image.getView().removeItem(item)
            except Exception:
                pass
        self._browser_tile_items = []
        self._is_tiled_detail = False
        self._detail_origin = (0.0, 0.0)

    def _show_detail(self, filepath):
        self._current_filepath = filepath
        self._clear_browser_tile_items()
        # Drawn ROI boxes belong to the previously displayed overview; drop them but keep
        # the marked-thumbnail selection so the same set can be re-mapped onto this image.
        self._clear_map_overlay()
        try:
            recon = self._find_recon_file(filepath)
            if recon:
                self._show_ptycho_detail(filepath, recon)
                return

            from pystxmcontrol.utils.writeNX import stxm as stxm_reader

            nx = stxm_reader(stxm_file=filepath)

            # ── collect export metadata ───────────────────────────────────────
            start = nx.meta.get("start_time", "")
            date_str, time_str = (start[:10], start[11:19]) if len(start) >= 19 else (start, "")
            source_name = ""
            energy_str  = ""
            try:
                with h5py.File(filepath, "r") as _f:
                    source_name = _h5str(_f["entry0/instrument/source/name"][()])
            except Exception:
                pass
            dwell_ms = None
            try:
                energies = np.atleast_1d(nx.data["entry0"].get("energy", np.array([])))
                if energies.size == 1:
                    energy_str = f"{float(energies[0]):.1f} eV"
                elif energies.size > 1:
                    energy_str = f"{float(energies[0]):.1f}–{float(energies[-1]):.1f} eV"
                ct = np.atleast_1d(nx.data["entry0"].get("count_time", np.array([])))
                if ct.size:
                    # count_time is already stored in milliseconds — do NOT rescale.
                    dwell_ms = float(ct.flat[0])
            except Exception:
                pass
            self._export_meta = {
                "filename":    os.path.basename(filepath),
                "date":        date_str,
                "time":        time_str,
                "proposal":    nx.meta.get("proposal", ""),
                "source":      source_name,
                "energy":      energy_str,
                "scan_type":   nx.meta.get("scan_type", ""),
                "sample":      nx.meta.get("sample_description", ""),
                "dwell_ms":    dwell_ms,
            }

            # ── discover detectors directly from HDF5 ────────────────────────
            scan_type_str = self._export_meta.get("scan_type", "")
            is_spectrum = "Spectrum" in scan_type_str
            self._is_tiled_detail = (nx.nRegions > 1 and "Image" in scan_type_str
                                     and not is_spectrum)
            self._stxm_detector_data = {}
            with h5py.File(filepath, "r") as hf:
                if self._is_tiled_detail:
                    # Tiled: collect per-entry (tile) data for each detector.
                    # _stxm_detector_data[det] = list of (data_2d, x_scale, y_scale, pos, x_range_um)
                    for det_name in hf.get("entry0/instrument", {}).keys():
                        instr_grp = hf[f"entry0/instrument/{det_name}"]
                        if _h5str(instr_grp.attrs.get("type", b"")) != "photon":
                            continue
                        tile_list = []
                        for ri in range(nx.nRegions):
                            data_path = f"entry{ri}/{det_name}/data"
                            if data_path not in hf:
                                continue
                            data = hf[data_path][()]          # (ne, y, x) or (y, x)
                            img_2d = data[0] if data.ndim == 3 else data
                            try:
                                xp = np.atleast_1d(hf[f"entry{ri}/default/sample_x"][()])
                            except Exception:
                                xp = np.array([])
                            try:
                                yp = np.atleast_1d(hf[f"entry{ri}/default/sample_y"][()])
                            except Exception:
                                yp = np.array([])
                            x_range_i = float(xp.max() - xp.min()) if xp.size > 1 else 0.0
                            y_range_i = float(yp.max() - yp.min()) if yp.size > 1 else 0.0
                            n_ypx, n_xpx = img_2d.shape if img_2d.ndim == 2 else (1, 1)
                            x_scale_i = x_range_i / n_xpx if n_xpx > 0 and x_range_i > 0 else 1.0
                            y_scale_i = y_range_i / n_ypx if n_ypx > 0 and y_range_i > 0 else 1.0
                            pos_i = (float(xp.min()) if xp.size > 0 else 0.0,
                                     float(yp.min()) if yp.size > 0 else 0.0)
                            tile_list.append((img_2d, x_scale_i, y_scale_i, pos_i, x_range_i))
                        if tile_list:
                            self._stxm_detector_data[det_name] = tile_list
                else:
                    # Single region: existing per-detector load from entry0
                    try:
                        xp = np.atleast_1d(hf["entry0/default/sample_x"][()])
                    except Exception:
                        xp = np.array([])
                    try:
                        yp = np.atleast_1d(hf["entry0/default/sample_y"][()])
                    except Exception:
                        yp = np.array([])
                    x_range_um = float(xp.max() - xp.min()) if xp.size > 1 else 0.0
                    y_range_um = float(yp.max() - yp.min()) if yp.size > 1 else 0.0

                    # Origin so the detail image is drawn in real motor coordinates
                    # (cursor returns scan X/Y positions, not 0-based pixel coords).
                    # Spectrum scans keep a 0 origin: their axes are energy/position,
                    # not sample X/Y.
                    if is_spectrum:
                        self._detail_origin = (0.0, 0.0)
                    else:
                        self._detail_origin = (
                            float(xp.min()) if xp.size else 0.0,
                            float(yp.min()) if yp.size else 0.0,
                        )

                    for det_name in hf.get("entry0/instrument", {}).keys():
                        instr_grp = hf[f"entry0/instrument/{det_name}"]
                        is_photon = _h5str(instr_grp.attrs.get("type", b"")) == "photon"
                        data_path = f"entry0/{det_name}/data"
                        if is_photon and data_path in hf:
                            data = hf[data_path][()]
                            if is_spectrum:
                                if data.ndim == 3:
                                    data_2d = data[:, 0, :]
                                elif data.ndim == 2:
                                    data_2d = data
                                else:
                                    data_2d = data.reshape(1, -1)
                                n_energies, x_pts = data_2d.shape
                                e_range = (float(energies.max() - energies.min())
                                           if energies.size > 1 else 1.0)
                                x_scale = e_range / n_energies if n_energies > 0 else 1.0
                                y_scale = x_range_um / x_pts if x_pts > 0 and x_range_um > 0 else 1.0
                                self._stxm_detector_data[det_name] = (
                                    data_2d.T, x_scale, y_scale, x_range_um
                                )
                            else:
                                if data.ndim == 3:
                                    _, n_ypx, n_xpx = data.shape
                                elif data.ndim == 2:
                                    n_ypx, n_xpx = data.shape
                                else:
                                    n_ypx = n_xpx = 1
                                x_scale = x_range_um / n_xpx if n_xpx > 0 and x_range_um > 0 else 1.0
                                y_scale = y_range_um / n_ypx if n_ypx > 0 and y_range_um > 0 else 1.0
                                self._stxm_detector_data[det_name] = (data, x_scale, y_scale, x_range_um)

            if not self._stxm_detector_data:
                self.detail_text.setPlainText("No photon detector data found.")
                return

            # ── populate detector combo ───────────────────────────────────────
            self.detector_combo.blockSignals(True)
            self.detector_combo.clear()
            for name in self._stxm_detector_data:
                self.detector_combo.addItem(name)
            self.detector_combo.blockSignals(False)
            multi = len(self._stxm_detector_data) > 1
            self._detector_bar_widget.setVisible(multi)

            self.detail_stack.setCurrentIndex(0)
            self._on_detector_changed(0)

            # ── metadata text (read scan params directly from HDF5) ───────────
            w = 17
            lines = [
                f"{'File:':<{w}}{os.path.basename(filepath)}",
                f"{'Scan type:':<{w}}{nx.meta.get('scan_type', '')}",
                f"{'Start time:':<{w}}{nx.meta.get('start_time', '')}",
                f"{'End time:':<{w}}{nx.meta.get('end_time', '')}",
                f"{'Experimenters:':<{w}}{nx.meta.get('experimenters', '')}",
                f"{'Sample:':<{w}}{nx.meta.get('sample_description', '')}",
                f"{'Proposal:':<{w}}{nx.meta.get('proposal', '')}",
                "",
            ]
            try:
                with h5py.File(filepath, "r") as hf:
                    grp = hf["entry0/default"]
                    xp_arr = np.atleast_1d(grp["sample_x"][()] if "sample_x" in grp else np.array([]))
                    yp_arr = np.atleast_1d(grp["sample_y"][()] if "sample_y" in grp else np.array([]))
                    en_arr = np.atleast_1d(grp["energy"][()]   if "energy"   in grp else np.array([]))
                    try:
                        # count_time is already stored in milliseconds — do NOT rescale.
                        dwell_val = float(np.atleast_1d(grp["count_time"][()])[0])
                    except Exception:
                        dwell_val = None
                    try:
                        x_motor = _h5str(hf["entry0/default/motor_name_x"][()])
                    except Exception:
                        x_motor = nx.meta.get("x_motor", "")
                    try:
                        y_motor = _h5str(hf["entry0/default/motor_name_y"][()])
                    except Exception:
                        y_motor = nx.meta.get("y_motor", "")
                    # Motor positions at scan time (entry0/instrument/motors): one scalar per motor.
                    motor_items = []
                    try:
                        mgrp = hf["entry0/instrument/motors"]
                        for mname in mgrp.keys():
                            try:
                                motor_items.append(
                                    (mname, float(np.atleast_1d(mgrp[mname][()]).flat[0]))
                                )
                            except Exception:
                                pass
                    except Exception:
                        motor_items = []

                if xp_arr.size > 1:
                    dx = float(xp_arr[1] - xp_arr[0]) if xp_arr.size > 1 else 0.0
                    lines.append(
                        f"{'X range:':<{w}}"
                        f"{float(xp_arr.min()):.3f} – {float(xp_arr.max()):.3f} µm"
                        f"  ({xp_arr.size} pts, {dx:.4f} µm/pt)"
                    )
                if yp_arr.size > 1:
                    dy = float(yp_arr[1] - yp_arr[0]) if yp_arr.size > 1 else 0.0
                    lines.append(
                        f"{'Y range:':<{w}}"
                        f"{float(yp_arr.min()):.3f} – {float(yp_arr.max()):.3f} µm"
                        f"  ({yp_arr.size} pts, {dy:.4f} µm/pt)"
                    )
                if en_arr.size > 0:
                    lines.append(
                        f"{'Energies:':<{w}}"
                        f"{en_arr.size} {'energy' if en_arr.size == 1 else 'energies'}  "
                        f"{float(en_arr.min()):.2f}–{float(en_arr.max()):.2f} eV"
                    )
                if dwell_val is not None:
                    lines.append(f"{'Dwell:':<{w}}{dwell_val:.3f} ms")
                if x_motor:
                    lines.append(f"{'X motor:':<{w}}{x_motor}")
                if y_motor:
                    lines.append(f"{'Y motor:':<{w}}{y_motor}")
                if motor_items:
                    lines.append("")
                    lines.append("Motor positions:")
                    for mname, mval in motor_items:
                        lines.append(f"  {mname:<{w}}{mval:.3f}")
            except Exception:
                pass

            self.detail_text.setPlainText("\n".join(lines))

        except Exception as e:
            import traceback
            self.detail_text.setPlainText(
                f"Error loading file:\n{e}\n\n{traceback.format_exc()}"
            )

    def _on_detail_mouse_moved(self, args):
        pos = args[0]
        view = self.detail_image.getView()
        if not view.sceneBoundingRect().contains(pos):
            return
        mouse_pt = view.mapSceneToView(pos)
        x_um = mouse_pt.x()
        y_um = mouse_pt.y()

        value_str = ""
        if self._is_tiled_detail:
            for item in self._browser_tile_items:
                data_pt = item.mapFromScene(pos)
                arr = item.image
                if arr is None:
                    continue
                ix = int(data_pt.x())
                iy = int(data_pt.y())
                if 0 <= ix < arr.shape[0] and 0 <= iy < arr.shape[1]:
                    value_str = f"  val: {arr[ix, iy]:.2f}"
                    break
        else:
            img_item = self.detail_image.getImageItem()
            arr = img_item.image if img_item is not None else None
            if arr is not None:
                data_pt = img_item.mapFromScene(pos)
                ix = int(data_pt.x())
                iy = int(data_pt.y())
                if arr.ndim == 3:
                    t = self.detail_image.currentIndex
                    if 0 <= ix < arr.shape[1] and 0 <= iy < arr.shape[2] and 0 <= t < arr.shape[0]:
                        value_str = f"  val: {arr[t, ix, iy]:.2f}"
                elif arr.ndim == 2:
                    if 0 <= ix < arr.shape[0] and 0 <= iy < arr.shape[1]:
                        value_str = f"  val: {arr[ix, iy]:.2f}"

        self.cursor_label.setText(f"x: {x_um:.3f} µm   y: {y_um:.3f} µm{value_str}")

    def _on_detector_changed(self, index):
        """Display the image for the selected detector."""
        det_name = self.detector_combo.itemText(index)
        if not det_name or det_name not in self._stxm_detector_data:
            return

        is_spectrum = "Spectrum" in self._export_meta.get("scan_type", "")
        self.detail_image.getView().setAspectLocked(not is_spectrum)

        if self._is_tiled_detail:
            # Clear previous tile items and the internal image
            self._clear_browser_tile_items()
            self.detail_image.clear()
            tile_list = self._stxm_detector_data[det_name]
            total_x_range = 0.0
            for (img_2d, x_scale_i, y_scale_i, pos_i, x_range_i) in tile_list:
                img_item = pg.ImageItem()
                tr = QtGui.QTransform()
                tr.scale(x_scale_i, y_scale_i)
                tr.translate(pos_i[0] / x_scale_i, pos_i[1] / y_scale_i)
                img_item.setTransform(tr)
                img_item.setImage(img_2d.T, autoLevels=True)
                self.detail_image.getView().addItem(img_item)
                self._browser_tile_items.append(img_item)
                total_x_range = max(total_x_range, x_range_i)
            self.detail_image.getView().autoRange()
            x_range_um = total_x_range
        else:
            data, x_scale, y_scale, x_range_um = self._stxm_detector_data[det_name]
            if data.ndim == 3:
                self.detail_image.setImage(
                    np.transpose(data, (0, 2, 1)),
                    axes={"t": 0, "x": 1, "y": 2},
                    pos=self._detail_origin,
                    scale=(x_scale, y_scale),
                )
            elif data.ndim == 2:
                self.detail_image.setImage(
                    data.T, pos=self._detail_origin, scale=(x_scale, y_scale)
                )
            else:
                self.detail_image.clear()

        # ── metadata overlay (scale bar + logo + two text rows) ───────────────
        m = self._export_meta
        scan_type = m.get("scan_type", "")
        row1 = '   '.join(p for p in [
            m.get("proposal", ""),
            scan_type,
            m.get("sample", ""),
            f"Channel: {det_name}" if det_name else "",
        ] if p)
        row2_parts = []
        if not self._is_tiled_detail:
            data, x_scale, y_scale, _xr = self._stxm_detector_data[det_name]
            if x_scale and x_scale > 0:
                row2_parts.append(f"Pixel Size: {x_scale:.3f} µm")
        if m.get("dwell_ms") is not None:
            row2_parts.append(f"Dwell: {m['dwell_ms']:.3f} ms")
        if m.get("energy"):
            row2_parts.append(f"Energy: {m['energy']}")
        row2 = '   '.join(row2_parts)
        self._detail_overlay.update(x_range_um, [row1, row2])

    def _show_ptycho_detail(self, stxm_path, recon_path):
        """Display obj |amp|, obj phase, and probe |amp| from a reconstruction .h5."""
        CROP = 400
        try:
            with h5py.File(recon_path, "r") as f:
                obj         = f["obj"][()]         # complex64 (ny, nx)
                probe       = f["probe"][()]       # complex64 (n_modes, 512, 512)
                obj_basis   = f["obj_basis"][()]   # float32 (3, 2)
                probe_basis = f["probe_basis"][()]
                try:
                    wavelength_m = float(np.atleast_1d(f["wavelength"][()])[0])
                    energy_ev = (1239.8 / wavelength_m) * 1e-9
                    energy_str = f"{energy_ev:.1f} eV"
                except Exception:
                    energy_str = ""

            # pixel sizes, converted to µm. Each basis is a matrix whose columns
            # are the two per-axis real-space step vectors, so the pixel size is the
            # length of one column — NOT the Frobenius norm of the whole matrix, which
            # combines both axes and overstates the size by ~√2 for a square grid.
            obj_px_um   = float(np.linalg.norm(obj_basis[:, 0])) * 1e6
            probe_px_um = float(np.linalg.norm(probe_basis[:, 0])) * 1e6

            # crop border artefacts from the object
            obj_cropped = obj[CROP:-CROP, CROP:-CROP]

            obj_amp   = np.abs(obj_cropped).T
            obj_phase = np.angle(obj_cropped)
            # unwrap 2-D phase to remove ±π discontinuities before display
            try:
                from skimage.restoration import unwrap_phase
                obj_phase = unwrap_phase(obj_phase)
            except Exception:
                pass  # fall back to wrapped phase if skimage is unavailable
            obj_phase = obj_phase.T
            # incoherent sum over probe modes: sqrt(sum |mode|^2)
            probe_amp = np.sqrt(np.sum(np.abs(probe) ** 2, axis=0)).T

            self._ptycho_arrays = [obj_amp, obj_phase, probe_amp]
            # pixel size per dropdown index: obj amp, obj phase, probe amp
            self._ptycho_pixel_um = [obj_px_um, obj_px_um, probe_px_um]

            # load image data before making the page visible so pyqtgraph renders it
            self._on_ptycho_selection_changed(self.ptycho_selector.currentIndex())
            self.detail_stack.setCurrentIndex(1)

            # ── collect export metadata from the stxm file ────────────────────
            try:
                with h5py.File(stxm_path, "r") as _sf:
                    start = _h5str(_sf["entry0/start_time"][()])
                    date_str = start[:10] if len(start) >= 10 else start
                    time_str = start[11:19] if len(start) >= 19 else ""
                    try:
                        source_name = _h5str(_sf["entry0/instrument/source/name"][()])
                    except Exception:
                        source_name = ""
                    try:
                        proposal = _h5str(_sf["entry0/title"][()])
                    except Exception:
                        proposal = ""
                    try:
                        scan_type = _h5str(_sf["entry0/default/stxm_scan_type"][0])
                    except Exception:
                        scan_type = "Ptychography Image"
                self._export_meta = {
                    "filename":  os.path.basename(stxm_path),
                    "date":      date_str,
                    "time":      time_str,
                    "proposal":  proposal,
                    "source":    source_name,
                    "energy":    energy_str,
                    "scan_type": scan_type,
                }
            except Exception:
                self._export_meta = {"filename": os.path.basename(stxm_path)}

            # ── metadata text ─────────────────────────────────────────────────
            w = 17
            lines = [
                f"{'STXM file:':<{w}}{os.path.basename(stxm_path)}",
                f"{'Recon file:':<{w}}{os.path.basename(recon_path)}",
            ]
            if energy_str:
                lines.append(f"{'Energy:':<{w}}{energy_str}")
            lines += [
                "",
                f"{'Object shape:':<{w}}{obj.shape[0]} × {obj.shape[1]} px  "
                f"(cropped to {obj_cropped.shape[0]} × {obj_cropped.shape[1]})",
                f"{'Probe modes:':<{w}}{probe.shape[0]}",
                f"{'Probe shape:':<{w}}{probe.shape[1]} × {probe.shape[2]} px",
            ]
            self.detail_text.setPlainText("\n".join(lines))

        except Exception as e:
            import traceback
            self.detail_stack.setCurrentIndex(0)
            self.detail_text.setPlainText(
                f"Error loading reconstruction:\n{e}\n\n{traceback.format_exc()}"
            )

    def _on_ptycho_selection_changed(self, index):
        if not self._ptycho_arrays:
            return
        px_um = self._ptycho_pixel_um[index] if self._ptycho_pixel_um else 0.0
        scale = (px_um, px_um) if px_um > 0 else (1.0, 1.0)
        self.ptycho_image.setImage(
            self._ptycho_arrays[index], autoRange=True, autoLevels=True,
            scale=scale,
        )

        # ── metadata overlay (scale bar + logo + two text rows) ───────────────
        x_range_um = px_um * self._ptycho_arrays[index].shape[0] if px_um > 0 else 0.0
        m = self._export_meta
        label = self.ptycho_selector.currentText()
        scan_type = m.get("scan_type", "")
        row1 = '   '.join(p for p in [
            m.get("proposal", ""),
            f"{scan_type} ({label})" if scan_type else label,
            m.get("sample", ""),
        ] if p)
        row2_parts = []
        if px_um > 0:
            row2_parts.append(f"Pixel Size: {px_um:.4f} µm")
        if m.get("energy"):
            row2_parts.append(f"Energy: {m['energy']}")
        row2 = '   '.join(row2_parts)
        self._ptycho_overlay.update(x_range_um, [row1, row2])

    def _render_composite_image(self):
        """
        Render the currently displayed image plus its metadata bar into a
        ``QImage`` (the same output that Export PNG saves to disk).

        Returns ``(QImage, default_filename_stem)`` or ``(None, "")`` if there
        is nothing to render.
        """
        if not self._current_filepath:
            return None, ""

        base = os.path.splitext(self._current_filepath)[0]
        page = self.detail_stack.currentIndex()

        if page == 1:
            label = self.ptycho_selector.currentText()
            suffix_map = {
                "Object |amplitude|": "amplitude",
                "Object phase":       "phase",
                "Probe |amplitude|":  "probe",
            }
            suffix = suffix_map.get(label, label.lower().replace(" ", "_"))
            stem       = f"{base}_{suffix}"
            image_view = self.ptycho_image
            overlay    = self._ptycho_overlay
        else:
            stem       = base
            image_view = self.detail_image
            overlay    = self._detail_overlay

        # ── hide the on-screen overlay, zoom to fit, render ───────────────────
        # The export draws its own metadata bar below the image, so the in-view overlay
        # (bar/logo/text) is hidden here to avoid duplicating it inside the rendered image.
        overlay_was_visible = overlay is not None and overlay._visible
        if overlay is not None:
            overlay.set_visible(False)

        view = image_view.getView()
        prev_state = view.getState()
        view.autoRange(padding=0)

        from pyqtgraph.exporters import ImageExporter
        exporter = ImageExporter(view)
        img_qimage = exporter.export(toBytes=True)

        export_view_rect = view.viewRect()

        view.setState(prev_state)
        if overlay is not None and overlay_was_visible:
            overlay.set_visible(True)

        img_w = img_qimage.width()
        img_h = img_qimage.height()

        # ── ALS logo ──────────────────────────────────────────────────────────
        _here     = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(_here, 'icons', 'als-logo.png')
        logo      = QtGui.QImage(logo_path)
        logo_w    = logo.width()  if not logo.isNull() else 0
        logo_h    = logo.height() if not logo.isNull() else 0

        # ── metadata bar ──────────────────────────────────────────────────────
        font   = QtGui.QFont("Monospace", 11)
        fm     = QtGui.QFontMetrics(font)
        line_h = fm.height()
        pad    = 12

        m = self._export_meta
        scan_type_str = m.get("scan_type", "")
        if page == 0:
            det = self.detector_combo.currentText()
            if det and self.detector_combo.count() > 1:
                scan_type_str = f"{scan_type_str} ({det})"
        elif page == 1 and scan_type_str:
            display_label_map = {
                "Object |amplitude|": "amplitude",
                "Object phase":       "phase",
                "Probe |amplitude|":  "probe",
            }
            display_label = display_label_map.get(
                self.ptycho_selector.currentText(),
                self.ptycho_selector.currentText()
            )
            scan_type_str = f"{scan_type_str.replace(' Image', '')} ({display_label})"

        # scan_type moved to the end of row 1 to avoid overlapping the scale bar
        row1_parts = [v for v in [
            m.get("filename", ""),
            m.get("date", ""),
            m.get("time", ""),
            scan_type_str,
        ] if v]
        row2_parts = [v for v in [
            m.get("proposal", ""),
            m.get("source", ""),
            m.get("energy", ""),
        ] if v]
        meta_rows = []
        if row1_parts:
            meta_rows.append("   ".join(row1_parts))
        if row2_parts:
            meta_rows.append("   ".join(row2_parts))

        text_h = pad + len(meta_rows) * line_h + pad
        bar_h  = max(text_h, logo_h + 2 * pad) if logo_h else text_h

        # ── composite ─────────────────────────────────────────────────────────
        out = QtGui.QImage(img_w, img_h + bar_h, QtGui.QImage.Format_RGB32)
        out.fill(QtGui.QColor(0, 0, 0))
        painter = QtGui.QPainter(out)
        painter.drawImage(0, 0, img_qimage)

        # Logo — vertically centred in the metadata bar
        text_x = pad
        if not logo.isNull():
            logo_y = img_h + (bar_h - logo_h) // 2
            painter.drawImage(pad, logo_y, logo)
            text_x = pad + logo_w + pad

        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.setFont(font)
        for i, row in enumerate(meta_rows):
            y = img_h + pad + i * line_h + fm.ascent()
            painter.drawText(text_x, y, row)

        if overlay is not None:
            bar_size_um = overlay.scale_size
            bar_label   = f"{bar_size_um:g} µm"
            px_per_unit = img_w / export_view_rect.width() if export_view_rect.width() > 0 else 1.0
            bar_px      = max(10, round(abs(bar_size_um * px_per_unit)))
            bar_thick   = 5
            bar_x       = img_w - bar_px - pad
            total_h     = bar_thick + fm.ascent() + 2
            bar_y       = img_h + (bar_h - total_h) // 2 + fm.ascent() + 2

            painter.setBrush(QtGui.QColor(255, 255, 255))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRect(bar_x, bar_y, bar_px, bar_thick)

            painter.setPen(QtGui.QColor(255, 255, 255))
            painter.setFont(font)
            label_w = fm.horizontalAdvance(bar_label)
            painter.drawText(bar_x + (bar_px - label_w) // 2, bar_y - 2, bar_label)

        painter.end()
        return out, stem

    def _export_png(self):
        out, stem = self._render_composite_image()
        if out is None:
            return
        save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export PNG", f"{stem}.png", "PNG Images (*.png)"
        )
        if save_path:
            out.save(save_path, "PNG")

    def _add_to_log(self):
        """Append the current image + metadata + comment to the day's logbook."""
        if not self._current_filepath:
            return

        out, _ = self._render_composite_image()
        if out is None:
            return

        comment = self.log_comment_edit.text()
        detail_text = self.detail_text.toPlainText()

        try:
            # Route to the active logbook (shared model) when one is open, so the entry
            # lands in the user's chosen logbook and the live view refreshes. Fall back to
            # the source file's day folder when no logbook is active.
            model = getattr(self, "logbook_model", None)
            if model is not None and model.folder:
                model.add(out, self._export_meta, comment, detail_text, author="human")
                folder = model.folder
            else:
                from pystxmcontrol.utils.logbook import add_entry
                folder = os.path.dirname(self._current_filepath)
                add_entry(folder, out, self._export_meta, comment, detail_text)
            self.log_comment_edit.clear()
            QtWidgets.QMessageBox.information(
                self,
                "Logbook updated",
                f"Entry added.\n\nLogbook PDF: {os.path.join(folder, 'logbook.pdf')}",
            )
        except Exception as e:
            import traceback
            QtWidgets.QMessageBox.critical(
                self,
                "Logbook error",
                f"Could not add to logbook:\n{e}\n\n{traceback.format_exc()}",
            )

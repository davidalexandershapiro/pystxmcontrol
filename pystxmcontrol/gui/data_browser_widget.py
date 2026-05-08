import os
import numpy as np
import h5py
from PySide6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from pystxmcontrol.utils.thumbnail_cache import ThumbnailCache


# ─────────────────────────── helpers ──────────────────────────────────────────

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
                scan_type = f["entry0/default/stxm_scan_type"][0].decode()
            except Exception:
                pass
            try:
                start_time = f["entry0/start_time"][()].decode()
            except Exception:
                pass
            # find first photon detector and use its interpolated data
            try:
                for key in f["entry0/instrument"].keys():
                    grp = f[f"entry0/instrument/{key}"]
                    if (
                        "type" in grp.attrs
                        and grp.attrs["type"].decode() == "photon"
                    ):
                        data_path = f"entry0/{key}/data"
                        if data_path in f:
                            data = f[data_path][()]
                            if data.ndim == 3:
                                n_frames = data.shape[0]
                                arr = data[0]
                            elif data.ndim == 2:
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
                scan_type = f["entry0/counter0/stxm_scan_type"][()][0].decode()
            except Exception:
                pass
            try:
                st = f["entry0/start_time"][()]
                if isinstance(st, (list, np.ndarray)):
                    start_time = (
                        st[0].decode() if isinstance(st[0], bytes) else str(st[0])
                    )
                else:
                    start_time = (
                        st.decode() if isinstance(st, bytes) else str(st)
                    )
            except Exception:
                pass
            try:
                data = f["entry0/counter0/data"][()]
                if data.ndim == 3:
                    n_frames = data.shape[0]
                    arr = data[0]
                elif data.ndim == 2:
                    arr = data
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
                arr = np.abs(obj_cropped).T
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

            self.thumbnail_ready.emit(fp, arr, scan_type, start_time, x_range_um)
            self.progress.emit(i + 1, total)


# ───────────────────────── ThumbnailCard ──────────────────────────────────────

class ThumbnailCard(QtWidgets.QWidget):
    """A clickable card showing a small preview image and scan metadata."""

    clicked = QtCore.Signal(str)  # emits filepath

    _NORMAL = (
        "QWidget#ThumbnailCard {"
        "  border: 1px solid #555;"
        "  border-radius: 4px;"
        "}"
    )
    _SELECTED = (
        "QWidget#ThumbnailCard {"
        "  border: 2px solid #4a9fd5;"
        "  border-radius: 4px;"
        "  background-color: rgba(74,159,213,30);"
        "}"
    )

    def __init__(self, filepath, parent=None):
        super().__init__(parent)
        self.setObjectName("ThumbnailCard")
        self.filepath = filepath
        self.setFixedSize(152, 188)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setStyleSheet(self._NORMAL)
        self._build_ui()

    def _build_ui(self):
        self.scan_type = ""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(2)
        layout.setContentsMargins(5, 5, 5, 5)

        self.image_label = QtWidgets.QLabel("loading…")
        self.image_label.setFixedSize(128, 128)
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setStyleSheet("border: 1px solid #333; background-color: #222;")

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
        self.setStyleSheet(self._SELECTED if selected else self._NORMAL)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(self.filepath)
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_dir = ""
        self._direct_day_dir = None   # set when user browses to a flat YYMMDD folder
        self._cards = {}      # filepath -> ThumbnailCard
        self._loader = None
        self._cache = ThumbnailCache()
        self._detail_scale_bar = None
        self._ptycho_scale_bar = None
        self._ptycho_pixel_um = []   # pixel size in µm per dropdown index
        self._current_filepath = ""
        self._export_meta = {}
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

        self.log_comment_edit = QtWidgets.QLineEdit()
        self.log_comment_edit.setPlaceholderText("Comment for logbook…")
        export_bar.addWidget(self.log_comment_edit, stretch=1)

        detail_layout.addLayout(export_bar)

        self.detail_text = QtWidgets.QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(230)
        self.detail_text.setFontFamily("Monospace")
        detail_layout.addWidget(self.detail_text)

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

    def _load_for_date(self):
        if not self._root_dir:
            self.status_label.setText("Select a folder first")
            return

        # abort any in-flight loader
        if self._loader is not None and self._loader.isRunning():
            self._loader.abort()
            self._loader.wait()

        # clear existing thumbnails
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

    @staticmethod
    def _find_recon_file(stxm_path):
        """Return path to a ptychography reconstruction .h5 alongside stxm_path, or None."""
        import glob
        base = os.path.splitext(stxm_path)[0]   # strip .stxm
        pattern = base + "_ccdframes_*.h5"
        matches = glob.glob(pattern)
        return matches[0] if matches else None

    def _show_detail(self, filepath):
        self._current_filepath = filepath
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
                    source_name = _f["entry0/instrument/source/name"][()].decode()
            except Exception:
                pass
            try:
                energies = np.atleast_1d(nx.data["entry0"].get("energy", np.array([])))
                if energies.size == 1:
                    energy_str = f"{float(energies[0]):.1f} eV"
                elif energies.size > 1:
                    energy_str = f"{float(energies[0]):.1f}–{float(energies[-1]):.1f} eV"
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
            }

            # ── discover detectors directly from HDF5 ────────────────────────
            self._stxm_detector_data = {}
            with h5py.File(filepath, "r") as hf:
                # physical scale from the default group (same for all detectors)
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

                # find all photon detectors: instrument groups with type='photon'
                # that also have a matching NXdata group at entry0 level
                for det_name in hf.get("entry0/instrument", {}).keys():
                    instr_grp = hf[f"entry0/instrument/{det_name}"]
                    is_photon = instr_grp.attrs.get("type", b"").decode() == "photon"
                    data_path = f"entry0/{det_name}/data"
                    if is_photon and data_path in hf:
                        data = hf[data_path][()]
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
                        dwell_val = float(np.atleast_1d(grp["count_time"][()])[0]) * 1000
                    except Exception:
                        dwell_val = None
                    try:
                        x_motor = hf["entry0/default/motor_name_x"][()].decode()
                    except Exception:
                        x_motor = nx.meta.get("x_motor", "")
                    try:
                        y_motor = hf["entry0/default/motor_name_y"][()].decode()
                    except Exception:
                        y_motor = nx.meta.get("y_motor", "")

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
                    lines.append(f"{'Dwell:':<{w}}{dwell_val:.1f} ms")
                if x_motor:
                    lines.append(f"{'X motor:':<{w}}{x_motor}")
                if y_motor:
                    lines.append(f"{'Y motor:':<{w}}{y_motor}")
            except Exception:
                pass

            self.detail_text.setPlainText("\n".join(lines))

        except Exception as e:
            import traceback
            self.detail_text.setPlainText(
                f"Error loading file:\n{e}\n\n{traceback.format_exc()}"
            )

    def _on_detector_changed(self, index):
        """Display the image for the selected detector."""
        det_name = self.detector_combo.itemText(index)
        if not det_name or det_name not in self._stxm_detector_data:
            return
        data, x_scale, y_scale, x_range_um = self._stxm_detector_data[det_name]

        if data.ndim == 3:
            self.detail_image.setImage(
                np.transpose(data, (0, 2, 1)),
                axes={"t": 0, "x": 1, "y": 2},
                scale=(x_scale, y_scale),
            )
        elif data.ndim == 2:
            self.detail_image.setImage(data.T, scale=(x_scale, y_scale))
        else:
            self.detail_image.clear()

        # ── scale bar ────────────────────────────────────────────────────────
        if x_range_um > 0:
            bar_um = round(max(1.0, x_range_um / 5.0), 1)
            if self._detail_scale_bar is None:
                self._detail_scale_bar = pg.ScaleBar(
                    size=bar_um, suffix='µm', offset=(-20, -20),
                    brush=pg.mkBrush('r'), pen=pg.mkPen('r'),
                )
                self._detail_scale_bar.text.setColor('r')
                self._detail_scale_bar.setParentItem(self.detail_image.getView())
            else:
                self._detail_scale_bar.size = bar_um
                self._detail_scale_bar.updateBar()
            self._detail_scale_bar.text.setText(f"{bar_um:g} µm")
            self._detail_scale_bar.setVisible(True)
        elif self._detail_scale_bar is not None:
            self._detail_scale_bar.setVisible(False)

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

            # pixel sizes: norm of basis matrix, converted to µm
            obj_px_um   = float(np.linalg.norm(obj_basis)) * 1e6
            probe_px_um = float(np.linalg.norm(probe_basis)) * 1e6

            # crop border artefacts from the object
            obj_cropped = obj[CROP:-CROP, CROP:-CROP]

            obj_amp   = np.abs(obj_cropped).T
            obj_phase = np.angle(obj_cropped).T
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
                    start = _sf["entry0/start_time"][()].decode()
                    date_str = start[:10] if len(start) >= 10 else start
                    time_str = start[11:19] if len(start) >= 19 else ""
                    try:
                        source_name = _sf["entry0/instrument/source/name"][()].decode()
                    except Exception:
                        source_name = ""
                    try:
                        proposal = _sf["entry0/title"][()].decode()
                    except Exception:
                        proposal = ""
                    try:
                        scan_type = _sf["entry0/default/stxm_scan_type"][0].decode()
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
            self._ptycho_arrays[index].T, autoRange=True, autoLevels=True,
            scale=scale,
        )

        # ── scale bar ─────────────────────────────────────────────────────────
        if px_um > 0:
            n_xpx = self._ptycho_arrays[index].shape[0]
            x_range_um = px_um * n_xpx
            bar_um = max(1.0, x_range_um / 5.0)
            if self._ptycho_scale_bar is None:
                self._ptycho_scale_bar = pg.ScaleBar(
                    size=bar_um, suffix='µm', offset=(-20, -20),
                    brush=pg.mkBrush('r'), pen=pg.mkPen('r'),
                )
                self._ptycho_scale_bar.text.setColor('r')
                self._ptycho_scale_bar.setParentItem(self.ptycho_image.getView())
            else:
                self._ptycho_scale_bar.size = bar_um
                self._ptycho_scale_bar.updateBar()
            self._ptycho_scale_bar.text.setText(f"{bar_um:g} µm")
            self._ptycho_scale_bar.setVisible(True)
        elif self._ptycho_scale_bar is not None:
            self._ptycho_scale_bar.setVisible(False)

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
            scale_bar  = self._ptycho_scale_bar
        else:
            stem       = base
            image_view = self.detail_image
            scale_bar  = self._detail_scale_bar

        # ── hide scale bar, zoom to fit, render ───────────────────────────────
        if scale_bar is not None:
            scale_bar.setVisible(False)

        view = image_view.getView()
        prev_state = view.getState()
        view.autoRange(padding=0)

        from pyqtgraph.exporters import ImageExporter
        exporter = ImageExporter(view)
        img_qimage = exporter.export(toBytes=True)

        export_view_rect = view.viewRect()

        view.setState(prev_state)
        if scale_bar is not None:
            scale_bar.setVisible(True)

        img_w = img_qimage.width()
        img_h = img_qimage.height()

        # ── ALS logo ──────────────────────────────────────────────────────────
        _here     = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(_here, '..', '..', 'icons', 'als-logo.png')
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

        if scale_bar is not None:
            bar_size_um = scale_bar.size
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

        folder = os.path.dirname(self._current_filepath)
        comment = self.log_comment_edit.text()
        detail_text = self.detail_text.toPlainText()

        try:
            from pystxmcontrol.utils.logbook import add_entry
            index = add_entry(folder, out, self._export_meta, comment, detail_text)
            self.log_comment_edit.clear()
            QtWidgets.QMessageBox.information(
                self,
                "Logbook updated",
                f"Entry {index} added.\n\nLogbook PDF: {os.path.join(folder, 'logbook.pdf')}",
            )
        except Exception as e:
            import traceback
            QtWidgets.QMessageBox.critical(
                self,
                "Logbook error",
                f"Could not add to logbook:\n{e}\n\n{traceback.format_exc()}",
            )

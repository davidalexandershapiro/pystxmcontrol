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
from PySide6.QtGui import QPixmap, QColor, QFont
from PySide6.QtCore import Qt, QTimer

import pyqtgraph as pg

from pystxmcontrol.gui.dashboard_theme import (
    C, MONO_FAMILY, SANS_FAMILY, build_stylesheet, make_lut,
    mono_font, sans_font, TravelBar, ProgressBar, EnergyRegionStrip,
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


class ImageArea(QWidget):
    """The main image viewer: a pyqtgraph ViewBox+ImageItem with absolutely
    positioned overlay labels (scale bar, metadata) repositioned on resize."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{C['plot_ground']};")
        self.glw = pg.GraphicsLayoutWidget(parent=self)
        self.glw.setBackground(C["plot_ground"])
        self.vb = self.glw.addViewBox()
        self.vb.setAspectLocked(True)
        self.vb.invertY(True)
        self.vb.setMouseEnabled(True, True)

        self.field = _absorption_field()
        self.img = pg.ImageItem()
        self.img.setImage((1 - self.field))          # absorption → display
        self.img.setLookupTable(make_lut("gray"))
        self.vb.addItem(self.img)
        self.vb.autoRange(padding=0)

        # ROI overlay (1px accent rect with scale handles)
        n = self.field.shape[0]
        self.roi = pg.RectROI([n * .38, n * .31], [n * .26, n * .24],
                              pen=pg.mkPen(C["accent"], width=1),
                              handlePen=pg.mkPen(C["accent"]),
                              hoverPen=pg.mkPen(C["accent"], width=2))
        self.vb.addItem(self.roi)
        self.roi_label = pg.TextItem("ROI 1 · 3.1 × 2.9 µm", color=C["accent"],
                                     anchor=(0, 1))
        self.roi_label.setFont(mono_font(8))
        self.roi_label.setPos(n * .38, n * .31)
        self.vb.addItem(self.roi_label)

        # scan line (tracks current row)
        self.scan_line = pg.InfiniteLine(pos=n * 0.68, angle=0, movable=False,
                                         pen=pg.mkPen(C["accent"], width=2))
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
        self.img.setLookupTable(make_lut(name))

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


class MainWindowDashboard(QMainWindow):
    def __init__(self, parent=None, live=True):
        super().__init__(parent)
        self.setWindowTitle("STXM Control — Acquisition")
        self.setStyleSheet(build_stylesheet())
        self._scanning = False
        self._expert = True
        self._staff_widgets = []          # widgets shown only in Staff mode
        self._motor_widgets = {}          # name -> {value,bar,lo,hi} for live updates
        self._image_seeded = False

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
        outer.addWidget(body, 1)

        # Subscribe to controller signals (read-only live data).
        if self.controller is not None:
            self._connect_controller_signals()
            self._seed_from_controller()

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
        grp = QButtonGroup(nav)
        grp.setExclusive(True)
        for i, name in enumerate(("Acquisition", "Browser", "Analysis", "Agent")):
            b = QPushButton(name)
            b.setProperty("role", "navtab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if i == 0:
                b.setChecked(True)
            grp.addButton(b)
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
        for lbl, val in (("Est. time", "18:24"), ("Velocity", "0.500 mm/s"),
                         ("Points", "14 400")):
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(self._label(lbl.upper(), role="fieldLabel"))
            v_ = self._label(val, role="valueBig")
            box.addWidget(v_)
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
        for r, (name, c, rng, n, step) in enumerate(rows, start=1):
            g.addWidget(self._label(name, role="mono"), r, 0)
            g.addWidget(self._field(c), r, 1)
            g.addWidget(self._field(rng), r, 2)
            g.addWidget(self._field(n), r, 3)
            g.addWidget(self._field(step, derived=True), r, 4)
        g.setColumnStretch(0, 0)
        for col in range(1, 5):
            g.setColumnStretch(col, 1)
        v.addLayout(g)

        checks = QHBoxLayout()
        checks.setSpacing(7)
        add = QPushButton("+ Region")
        add.setProperty("role", "small")
        checks.addWidget(add)
        for name, on in (("autofocus", True), ("show ROI", True),
                         ("tiled", False), ("defocus", False)):
            cb = QCheckBox(name)
            cb.setChecked(on)
            cb.setCursor(Qt.PointingHandCursor)
            checks.addWidget(cb)
        checks.addStretch(1)
        v.addLayout(checks)
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
                 ("Step", "0.25", False), ("N", "121", True),
                 ("Dwell ms", "2.0", False)]
        for col, (lbl, val, derived) in enumerate(specs):
            g.addWidget(self._label(lbl, role="microLabel"), 0, col)
            g.addWidget(self._field(val, derived=derived), 1, col)
            g.setColumnStretch(col, 1)
        v.addLayout(g)

        well = QFrame()
        well.setStyleSheet(f"background:{C['well']};border:1px solid {C['border']};"
                           "border-radius:6px;")
        wv = QVBoxLayout(well)
        wv.setContentsMargins(12, 10, 12, 6)
        wv.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(self._label("ENERGY REGIONS · Fe L3", role="fieldLabel"))
        top.addStretch(1)
        top.addWidget(self._label("3 regions · 121 pts", role="accent"))
        wv.addLayout(top)
        strip = EnergyRegionStrip([
            {"start": 700, "stop": 706, "n": 13, "active": False},
            {"start": 706, "stop": 714, "n": 81, "active": True},
            {"start": 714, "stop": 730, "n": 27, "active": False},
        ])
        wv.addWidget(strip)
        axis = QHBoxLayout()
        for i, t in enumerate(("700", "710", "720", "730 eV")):
            axis.addWidget(self._label(t, role="monoFaint"))
            if i < 3:
                axis.addStretch(1)
        wv.addLayout(axis)
        v.addWidget(well)

        btns = QHBoxLayout()
        btns.setSpacing(7)
        for name in ("+ Energy region", "Load edge preset"):
            b = QPushButton(name)
            b.setProperty("role", "small")
            btns.addWidget(b)
        btns.addStretch(1)
        v.addLayout(btns)
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
        for i, (lbl, val, role, editable) in enumerate(fields):
            r, c = divmod(i, 2)
            box = QVBoxLayout()
            box.setSpacing(4)
            box.addWidget(self._label(lbl, role="microLabel"))
            if editable:
                box.addWidget(self._field(val))
            else:
                ro = QLineEdit(val)
                ro.setReadOnly(True)
                ro.setProperty("derived", "true")
                if role == "ok":
                    ro.setStyleSheet(f"color:{C['ok']};")
                ro.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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
        pbox.addWidget(self._label("ALS-14872 · Shapiro", role="mono"))
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
        bl.addWidget(self.image_area, 1)

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
        item = pg.ImageItem(_diffraction())
        item.setLookupTable(make_lut("inferno"))
        vb.addItem(item)
        vb.autoRange(padding=0)
        left.addWidget(glw, 1)
        cap = QHBoxLayout()
        cap.addWidget(self._label("256² · log", role="monoFaint"))
        cap.addStretch(1)
        cap.addWidget(self._label("Σ 1.9e6", role="monoFaint"))
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

        self.trace_plot = pg.PlotWidget()
        self.trace_plot.setBackground(C["plot_ground"])
        self.trace_plot.showGrid(x=False, y=True, alpha=0.2)
        self.trace_plot.setYRange(0.994, 1.006)
        self.trace_plot.getAxis("left").setTextPen(C["text_faint"])
        self.trace_plot.getAxis("bottom").setTextPen(C["text_faint"])
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
            self._populate_motors(self._micro if i == 0 else self._beam)
        grp_well._group.idClicked.connect(show_group)

        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QVBoxLayout(footer)
        fv.setContentsMargins(14, 11, 14, 11)
        fv.setSpacing(8)
        btns = QHBoxLayout()
        btns.setSpacing(7)
        jm = QPushButton("Jog / Move"); mp = QPushButton("Motor panel")
        stop = QPushButton("Stop all"); stop.setObjectName("stopAll")
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
            self._motor_widgets[name] = {
                "value": val, "bar": bar, "unit": unit,
                "lo": info.get("minValue"), "hi": info.get("maxValue"),
            }
            # target + jog
            tgt = self._field(pos, align_right=True)
            tgt.setFixedWidth(84)
            tgt.setStyleSheet("font-size:11px;padding:5px 7px;")
            g.addWidget(tgt, 0, 2)
            minus = QPushButton("−"); minus.setProperty("role", "jog"); minus.setFixedWidth(26)
            plus = QPushButton("+"); plus.setProperty("role", "jog"); plus.setFixedWidth(26)
            g.addWidget(minus, 0, 3)
            g.addWidget(plus, 0, 4)
            g.setColumnStretch(1, 1)
            self.motor_layout.insertWidget(self.motor_layout.count() - 1, row)

    # ── interactions ─────────────────────────────────────────────────────
    def _toggle_scan(self):
        # Phase 1 is read-only; Begin/Cancel actions arrive in Phase 2.  Locally
        # reflect the toggle; when live, scan_state_changed keeps us in sync.
        self._set_scanning(not self._scanning)

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
            self.image_area.img.setImage(image, autoLevels=not self._image_seeded)
            self._image_seeded = True
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

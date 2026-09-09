"""Acquisition dashboard main window — a single-window STXM/ptychography
acquisition interface, transcribed from the design handoff in
``design_handoff_stxm_main_window/``.

STATUS: static skeleton (Phase 0).  Layout, styling, and representative
placeholder content only — no controller/hardware wiring yet.  All numbers and
plots are dummy data so the layout can be evaluated in real Qt.  Later phases
subscribe this view to ``MainController`` signals (see the reuse map / README).

Run standalone via ``main.py``.
"""

import os
import sys
import json
from collections import deque
from datetime import datetime
import numpy as np

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QFrame, QLabel, QPushButton, QComboBox, QLineEdit,
    QCheckBox, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QStackedWidget, QButtonGroup, QSizePolicy,
    QMessageBox, QFileDialog, QInputDialog, QMenu,
)
from PySide6.QtGui import QPixmap, QFont, QIntValidator, QCursor
from PySide6.QtCore import Qt, QTimer

import pyqtgraph as pg

from pystxmcontrol.gui.dashboard.theme import (
    C, build_stylesheet,
    mono_font, sans_font, TravelBar, ProgressBar, EnergyRegionStrip,
)
from pystxmcontrol.gui.dashboard import widgets as dw
from pystxmcontrol.gui.dashboard import motor_info as mi
from pystxmcontrol.gui.dashboard import scan_stats as stats
from pystxmcontrol.gui.dashboard import staff_auth as auth
from pystxmcontrol.gui.dashboard.scan_definition import (
    ScanDefinition, energy_n, motor_scan_region, region_scan_dict,
    resolve_daq_list,
)
from pystxmcontrol.gui.dashboard.detector_panel import DetectorPanel
from pystxmcontrol.gui.dashboard.heartbeat import ServerHeartbeat
from pystxmcontrol.gui.dashboard.image_area import ImageArea
from pystxmcontrol.gui.dashboard.favorites_bar import EnergyFavoritesBar
from pystxmcontrol.gui.dashboard.scan_files import (
    instrument_identity, window_title, find_last_scan_file, load_last_scan,
    read_scan_file, runtime_main_config,
)
# Saved energy definitions: one definition of the preset format and of where presets
# live, shared with the task agent and the MCP server so all three agree.
from pystxmcontrol.controller import energy_presets

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "..", "icons")

pg.setConfigOptions(antialias=True, imageAxisOrder="row-major", background=C["plot_ground"])


class MainWindowDashboard(QMainWindow):
    def __init__(self, parent=None, live=True):
        super().__init__(parent)
        self.setWindowTitle(window_title())
        self.setStyleSheet(build_stylesheet())
        self.statusBar().setStyleSheet(
            f"QStatusBar{{background:{C['panel_footer']};color:{C['text_dim']};"
            f"border-top:1px solid {C['border']};}}")
        # The scan geometry the panels edit.  Built before any view, because the
        # region/energy properties below read through it from build time on.
        self.scan_def = ScanDefinition()
        # Recent activity shown in the motor rail's footer.  Filled before
        # the rail exists (startup), so it is created here.
        self._cmd_log_entries = deque(maxlen=self._CMD_LOG_LINES)
        self._scanning = False
        self._move_mode = True          # True = absolute Move, False = relative Jog
        self._motor_group_index = 0     # index into the data-driven motor groups
        self._expert = False              # start in User mode (Staff needs a password)
        self._staff_widgets = []          # widgets shown only in Staff mode
        self._motor_widgets = {}          # name -> {value,bar,lo,hi} for live updates
        self._image_seeded = False
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
        # Seed the activity log with something true rather than leaving the
        # footer blank: whether we actually reached a server.
        self._log_activity(
            "connected to server" if self.controller is not None
            else "no server — placeholder mode",
            level="ok" if self.controller is not None else "info")

        # Motor config: prefer the server's (authoritative, live positions),
        # fall back to the on-disk file for placeholder mode.
        self._motor_info = {}
        if self.controller is not None:
            self._motor_info = dict(
                self.controller.get_motor_model().get("motor_info", {}) or {})
        if not self._motor_info:
            self._motor_info = mi.load_motor_info()

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

        # Apply the initial (User) mode: hide staff-only widgets, filter the motor
        # list, gate the Begin button on proposal selection.
        self._apply_mode()

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

    # ── scan definition ─────────────────────────────────────────────────
    # The editable scan geometry lives in self.scan_def (see
    # scan_definition); these properties keep the window's existing
    # attribute names pointing at it, so the panels that edit regions read and
    # write one shared model rather than several parallel lists.
    @property
    def _scan_regions(self):
        return self.scan_def.scan_regions

    @_scan_regions.setter
    def _scan_regions(self, value):
        self.scan_def.scan_regions = value

    @property
    def _active_region(self):
        return self.scan_def.active_region

    @_active_region.setter
    def _active_region(self, value):
        self.scan_def.active_region = value

    @property
    def _spectrum_region(self):
        return self.scan_def.spectrum_region

    @_spectrum_region.setter
    def _spectrum_region(self, value):
        self.scan_def.spectrum_region = value

    @property
    def _energy_regions(self):
        return self.scan_def.energy_regions

    @_energy_regions.setter
    def _energy_regions(self, value):
        self.scan_def.energy_regions = value

    @property
    def _active_energy_region(self):
        return self.scan_def.active_energy_region

    @_active_energy_region.setter
    def _active_energy_region(self, value):
        self.scan_def.active_energy_region = value

    @property
    def _focus_region(self):
        return self.scan_def.focus_region

    @_focus_region.setter
    def _focus_region(self, value):
        self.scan_def.focus_region = value

    # ── motor config ────────────────────────────────────────────────────
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

    def _load_daq_info(self):
        """Load DAQ (detector) config from the runtime file the server also reads
        (sys.prefix/pystxmcontrol_cfg/daq.json), falling back to the repo copy.
        When connected the live client.daqConfig is preferred instead."""
        candidates = [
            os.path.join(sys.prefix, "pystxmcontrol_cfg", "daq.json"),
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "daq.json"),
        ]
        for path in candidates:
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                continue
        return {}

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

        self._log_activity("server appeared — live mode", level="ok")
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
        c.scan_region_geometry_updated.connect(self._on_external_scan_geometry)
        c.shutter_state_changed.connect(self._on_shutter)
        c.daq_value_updated.connect(self._on_daq_value)
        c.monitor_data_updated.connect(self._on_monitor_data)
        c.scan_progress_updated.connect(self._on_progress_text)
        c.scan_file_updated.connect(self._on_scan_file)
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

    def _visible_motors(self):
        return mi.visible_motors(self._motor_info)

    @staticmethod
    def _target_text(widget):
        """Read the move/jog target — a dropdown (enumerated motor) or line edit."""
        return (widget.currentText() if isinstance(widget, QComboBox)
                else widget.text())

    def _motor_groups(self):
        return mi.motor_groups(self._motor_info)

    def _motor_rows(self, group):
        return mi.motor_rows(self._motor_info, group, expert=self._expert)

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
        t = dw.label("STXM Control")
        t.setFont(sans_font(11, QFont.DemiBold))
        title_box.addWidget(t)
        # The beamline, from main.json. Only added when configured: an empty line here
        # leaves a gap, and the placeholder this replaces named a specific beamline
        # that any other instrument running this GUI is not on.
        _, beamline = instrument_identity()
        if beamline:
            title_box.addWidget(dw.label(beamline, role="monoFaint"))
        bl.addLayout(title_box)
        hl.addWidget(brand)
        hl.addWidget(dw.vline())

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
            lab = dw.label(label.upper(), role="fieldLabel")
            val = dw.label(value, role=role)
            val.setFont(mono_font(12, QFont.Medium))
            v.addWidget(lab)
            v.addWidget(val)
            v.addStretch(1)
            return w, val

        rc, self.beam_val = readout("Beam current", "499.6 mA")
        hl.addWidget(dw.vline()); hl.addWidget(rc)
        pe, self.energy_val = readout("Photon energy", "705.0 eV", role="accent")
        hl.addWidget(dw.vline()); hl.addWidget(pe)
        hl.addWidget(dw.vline()); hl.addWidget(self._build_shutter_control())

        # server status
        hl.addWidget(dw.vline())
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
        sbox.addWidget(dw.label("stxmserver", font=sans_font(10, QFont.Medium)))
        sbox.addWidget(dw.label(endpoint, role="monoFaint"))
        sv.addLayout(sbox)
        hl.addWidget(srv)

        # mode toggle
        hl.addWidget(dw.vline())
        modew = QWidget()
        mv = QHBoxLayout(modew)
        mv.setContentsMargins(20, 0, 20, 0)
        self.mode_btn = QPushButton("User mode")
        self.mode_btn.setObjectName("modeToggle")
        self.mode_btn.setCursor(Qt.PointingHandCursor)
        self.mode_btn.clicked.connect(self._toggle_expert)
        # Right-click to set/change the staff password (mirrors the classic
        # window's "Set Staff Password…" File-menu action).
        self.mode_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mode_btn.customContextMenuRequested.connect(self._mode_btn_menu)
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
        h.addWidget(dw.label("SHUTTER", role="fieldLabel"))
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
        """Header tab → body view."""
        self.view_stack.setCurrentIndex(index)

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
        card, body = dw.card("Scan definition", "scan.json")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(14, 14, 14, 14)
        cv.setSpacing(12)

        # scan type + mode
        row = QGridLayout()
        row.setHorizontalSpacing(10)
        row.setVerticalSpacing(5)
        row.addWidget(dw.label("SCAN TYPE", role="fieldLabel"), 0, 0)
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
        row.addWidget(dw.label("MODE", role="fieldLabel"), 0, 1)
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
            box.addWidget(dw.label(lbl.upper(), role="fieldLabel"))
            v_ = dw.label(val, role="valueBig")
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
            lbl = dw.label(h, role="microLabel")
            lbl.setAlignment(Qt.AlignCenter)
            g.addWidget(lbl, 0, col)
        rows = [("SampleX", "-315.000", "12.000", "120", "0.100"),
                ("SampleY", "166.000", "12.000", "120", "0.100")]
        # Field refs keyed by motor, used by _compile_scan to build the region.
        self._spatial_fields = {}
        for r, (name, c, rng, n, step) in enumerate(rows, start=1):
            g.addWidget(dw.label(name, role="mono"), r, 0)
            e_c = dw.field(c); e_rng = dw.field(rng)
            e_n = dw.field(n); e_step = dw.field(step, derived=True)
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
        # The spectrum ROI is no longer a checkbox here — it is driven by the
        # Profile panel's Spectrum tab (see _switch_profile), which shows the ROI
        # while Spectrum is selected and hides it on Line-outs.
        for name, on in (("autofocus", True),
                         ("show ROI", True), ("tiled", False), ("defocus", False)):
            cb = QCheckBox(name)
            cb.setChecked(on)
            cb.setCursor(Qt.PointingHandCursor)
            checks.addWidget(cb)
            self._scan_checks[name] = cb
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
            g.addWidget(dw.label(lbl, role="microLabel"), 0, col)
            e = dw.field(val, derived=derived)
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
        top.addWidget(dw.label("ENERGY REGIONS", role="fieldLabel"))
        top.addStretch(1)
        self._energy_summary_lbl = dw.label("", role="accent")
        top.addWidget(self._energy_summary_lbl)
        wv.addLayout(top)
        self._energy_strip = EnergyRegionStrip([])
        self._energy_strip.region_clicked.connect(self._select_energy_region)
        wv.addWidget(self._energy_strip)
        self._energy_axis = QHBoxLayout()
        self._energy_axis_lbls = []
        for i in range(4):
            lbl = dw.label("", role="monoFaint")
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
        preset_btn = QPushButton("Load Preset")
        preset_btn.setProperty("role", "small")
        preset_btn.clicked.connect(self._load_energy_preset)
        btns.addWidget(preset_btn)
        save_preset_btn = QPushButton("Save Preset")
        save_preset_btn.setProperty("role", "small")
        save_preset_btn.clicked.connect(self._save_energy_preset)
        btns.addWidget(save_preset_btn)
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
            box.addWidget(dw.label(lbl, role="microLabel"))
            if editable:
                e = dw.field(val)
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
        card, body = dw.card("Acquisition controls", "continuousLine")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(0)

        # Focus Z
        w, gv = dw.group_box("Focus Z", "ZonePlateZ · Focus, Image Stack")
        self._focus_group = w
        grid, fz_edits = dw.grid4([("Center", "0.000", False), ("Range", "100.000", False),
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
        zp.addWidget(dw.label("Zone Plate A0", role="microLabel"), 0, 0)
        self._a0_field = dw.field(f"{float(energy.get('A0', 0.0)):.4f}")
        zp.addWidget(self._a0_field, 1, 0)
        a1_lbl = dw.label("Zone Plate A1 · staff", role="microLabel")
        a1_edit = dw.field(f"{float(energy.get('A1', 0.0)):.4f}")
        zp.addWidget(a1_lbl, 0, 1)
        zp.addWidget(a1_edit, 1, 1)
        zp.setColumnStretch(0, 1)
        zp.setColumnStretch(1, 1)
        gv.addLayout(zp)
        self._staff_widgets += [a1_lbl, a1_edit]
        iv.addWidget(w)

        # Line
        w, gv = dw.group_box("Line", "Focus, Line Spectrum")
        self._line_group = w
        grid, ln_edits = dw.grid4([("Length µm", "10.000", False), ("Angle °", "0.0", False),
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
        self._line_endpoints_lbl = dw.label("", role="monoFaint")
        r.addWidget(self._line_endpoints_lbl)
        r.addStretch(1)
        gv.addLayout(r)
        iv.addWidget(w)

        # Motor scan — one axis (Single Motor) or two (Double Motor / OSA Image /
        # any double_motor_scan family).  Each axis is a motor dropdown + a
        # Center / Range / Points / Step grid (mirrors the Loop sequence widget).
        # The dropdowns pre-select from the scan config's x_motor / y_motor.
        w, gv = dw.group_box("Motor scan", "Single / Double Motor")
        self._motor_group = w
        self._motor_axis_widgets = []
        for axis in range(2):
            block = QWidget()
            bl = QVBoxLayout(block)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            lbl = dw.label("X MOTOR" if axis == 0 else "Y MOTOR",
                              role="microLabel")
            bl.addWidget(lbl)
            combo = QComboBox()
            combo.addItems([name for name, _ in self._visible_motors()])
            combo.setCursor(Qt.PointingHandCursor)
            combo.currentIndexChanged.connect(
                lambda _i, a=axis: self._on_motor_selected(a))
            bl.addWidget(combo)
            grid, edits = dw.grid4([("Center", "0.000", False),
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
        w, gv = dw.group_box("Loop sequence", "outer motor loop")
        lbl = dw.label("MOTOR", role="microLabel")
        gv.addWidget(lbl)
        combo = QComboBox()
        combo.addItems([name for name, _ in self._visible_motors()])
        combo.setCursor(Qt.PointingHandCursor)
        gv.addWidget(combo)
        self._loop_motor_combo = combo
        grid, loop_edits = dw.grid4(
            [("Center", "-118.400", False), ("Range", "20.000", False),
             ("Points", "11", False), ("Step", "2.000", True)])
        gv.addLayout(grid)
        self._loop_fields = {"center": loop_edits[0], "range": loop_edits[1],
                             "points": loop_edits[2], "step": loop_edits[3]}
        r = QHBoxLayout()
        cb = QCheckBox("Execute Loop Scan")
        r.addWidget(cb); r.addStretch(1)
        gv.addLayout(r)
        self._loop_scan_check = cb
        iv.addWidget(w)

        # Favorites — energy presets, added by dropping a .json here (see
        # _on_favorite_dropped) and applied with a left-click.
        w, gv = dw.group_box("Favorites", "energy presets · drag .json here")
        self._favorites_bar = EnergyFavoritesBar()
        self._favorites_bar.file_dropped.connect(self._on_favorite_dropped)
        gv.addWidget(self._favorites_bar)
        iv.addWidget(w)
        self._favorites = self._read_favorites_file()
        self._rebuild_favorites_bar()

        # Output — Sample and Comment are stored in the scan file (see the
        # sm.set('sample'/'comment') calls in the scan compiler).
        w, gv = dw.group_box("Output", sep=False)
        gv.addWidget(dw.label("Sample", role="microLabel"))
        sample = QLineEdit("particle collection, Fe screening")
        sample.setFont(sans_font(10))
        self._sample_field = sample
        gv.addWidget(sample)
        gv.addWidget(dw.label("Comment", role="microLabel"))
        comment = QLineEdit("")
        comment.setFont(sans_font(10))
        self._comment_field = comment
        gv.addWidget(comment)
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
        pbox.addWidget(dw.label("Proposal", font=sans_font(10), color=C["text_dim"]))
        combo = QComboBox()
        combo.setCursor(Qt.PointingHandCursor)
        combo.setMinimumWidth(200)
        self._proposal_combo = combo
        self._esaf_participants = {}   # proposal id -> [participant names]
        combo.currentIndexChanged.connect(self._on_proposal_changed)
        pbox.addWidget(combo)
        fv.addLayout(pbox)
        self._populate_proposal_combo()
        fv.addStretch(1)
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
        fn = dw.label("NS_260806042.stxm", role="value")
        fn.setFont(mono_font(16, QFont.DemiBold))
        self._image_title_lbl = fn
        tl.addWidget(fn)
        self._image_subline_lbl = dw.label("—",
                                              font=sans_font(10), color=C["text_dim"])
        tl.addWidget(self._image_subline_lbl)
        tl.addStretch(1)
        cmap_well, self.cmap_btns = dw.segmented(["gray", "viridis", "inferno"], 0)
        for i, b in enumerate(self.cmap_btns):
            b.clicked.connect(lambda _=False, n=("gray", "viridis", "inferno")[i]:
                              self._set_cmap(n))
        tl.addWidget(cmap_well)
        load_btn = QPushButton("Load scan"); load_btn.setProperty("role", "small")
        load_btn.clicked.connect(self._on_load_scan)
        tl.addWidget(load_btn)
        save_btn = QPushButton("Save"); save_btn.setProperty("role", "small")
        save_btn.clicked.connect(self._save_image_png)
        tl.addWidget(save_btn)
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
            k = dw.label(lbl, font=mono_font(11), color=C["text_dim"])
            val_l = dw.label(val, font=mono_font(11), color=C["text"])
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
        prof_card, prof_body = dw.card("Profile")
        prof_well, _ = dw.segmented(["Spectrum", "Line-outs"], 1)
        prof_card.header_layout.insertWidget(1, prof_well)
        prof_card.header_layout.insertSpacing(2, 10)
        # Right side of the header: the spectrum note OR the X/Y line-cut pill,
        # whichever the active tab needs (they share the slot; only one shows).
        self._profile_note = dw.label("mean signal · ROI vs eV", role="accent")
        prof_card.header_layout.addWidget(self._profile_note)
        self._lineout_axis_well, _ = dw.segmented(["X", "Y"], 0)
        prof_card.header_layout.addWidget(self._lineout_axis_well)

        self._profile_stack = QStackedWidget()
        self._profile_stack.addWidget(self._spectrum_panel())
        self._profile_stack.addWidget(self._lineout_panel())
        prof_body.addWidget(self._profile_stack, 1)
        self._profile_grp = prof_well.group
        prof_well.group.idClicked.connect(self._switch_profile)
        self._lineout_axis_well.group.idClicked.connect(self._set_lineout_axis)
        # Default to the Line-outs tab (matches the checked pill above).
        self._switch_profile(1)
        sl.addWidget(prof_card, 135)

        # scan progress
        prog_card, prog_body = dw.card("Scan progress", "12:47 / 18:24")
        # This card's own note is the header "elapsed / est" readout.  It used to
        # be picked up from a self._note_lbl that every card with a note
        # overwrote, so it was only ever correct because of build order.
        self.progress_time_lbl = prog_card.note_label
        content = QWidget()
        pv = QVBoxLayout(content)
        pv.setContentsMargins(14, 14, 14, 14)
        pv.setSpacing(12)
        top = QHBoxLayout()
        self.progress_caption = dw.label("—",
                                             font=sans_font(10), color=C["text_dim"])
        top.addWidget(self.progress_caption)
        top.addStretch(1)
        self.pct_lbl = dw.label("0%", role="value")
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
            box.addWidget(dw.label(lbl.upper(), role="fieldLabel"))
            v_ = dw.label(val, role=role)
            v_.setFont(mono_font(14))
            box.addWidget(v_)
            grid.addLayout(box, r, c)
            self._progress_stats[lbl] = v_
        pv.addLayout(grid)
        prog_body.addWidget(content, 1)
        sl.addWidget(prog_card, 100)
        return strip

    def _spectrum_panel(self):
        """ROI spectrum: the mean signal inside the Spectrum ROI as a function of
        energy, computed live from the scan's energy stack (see
        _update_roi_spectrum).  Empty for single-energy scans — there is no
        spectrum to show — and until at least one energy has finished imaging."""
        pw = dw.style_plot(pg.PlotWidget())
        # No units= here: pyqtgraph's auto SI-prefix would rescale hundreds of eV
        # to "0.7 k" — show the raw eV value on the axis instead.
        pw.setLabel("bottom", "energy (eV)")
        pw.getAxis("bottom").enableAutoSIPrefix(False)
        pw.setLabel("left", "mean signal")
        self._spectrum_plot = pw
        self._spectrum_curve = pw.plot(
            [], [], pen=pg.mkPen(C["accent"], width=2),
            symbol='o', symbolSize=5, symbolBrush=C["accent"], symbolPen=None)
        return pw

    def _update_roi_spectrum(self):
        """Request a redraw of the ROI spectrum from the live energy stack.

        Coalesced onto a single-shot timer: this is called both from every
        ``sigRegionChanged`` of an ROI drag (one per mouse-move) and from every
        incoming frame, and re-averaging the whole energy stack + redrawing the
        curve on each of those starves the event loop — which is what makes the
        ROI feel like it is fighting the incoming data.  One redraw per interval
        is indistinguishable on screen."""
        if getattr(self, "_spectrum_curve", None) is None:
            return
        t = getattr(self, "_spectrum_redraw_timer", None)
        if t is None:
            t = self._spectrum_redraw_timer = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(120)
            t.timeout.connect(self._redraw_roi_spectrum)
        if not t.isActive():
            t.start()

    def _redraw_roi_spectrum(self):
        """Recompute and draw the ROI spectrum (see _update_roi_spectrum)."""
        curve = getattr(self, "_spectrum_curve", None)
        if curve is None:
            return
        xs, ys = self._roi_spectrum_points()
        curve.setData(xs, ys)

    def _roi_spectrum_points(self):
        """Return (energies, ROI-mean-signal) for every COMPLETED energy, or
        ([], []) when a spectrum does not apply.

        The in-progress energy is skipped so its partially-imaged (zero-filled)
        frame never drags the trace down, which also keeps the horizontal axis
        limited to energies that have actually been measured.  Nothing is
        returned for single-energy scans, non-image scans, or before the live
        energy stack exists."""
        if (self._spectrum_region is None or self.controller is None
                or getattr(self, "_ls_mode", False)
                or getattr(self, "_focus_mode", False)
                or getattr(self, "_motor_scan_mode", False)
                or self._is_single_motor()):
            return [], []
        try:
            live = getattr(self.controller, "_live_stxm", None)
            im = self.controller.get_image_model()
            energies = list(np.asarray(
                im.get('energy_list') or [], dtype=float).ravel())
            if live is None or len(energies) <= 1:
                return [], []

            channel = im.get('channel_key', 'default') or 'default'
            region_key = str(im.get('scan_region_index', 'Region1'))
            try:
                region_num = int(region_key.split('Region')[-1]) - 1
            except (ValueError, AttributeError):
                region_num = 0

            interp = getattr(live, 'interp_counts', None)
            cube = interp.get(channel) if isinstance(interp, dict) else None
            if cube is None or region_num >= len(cube):
                return [], []
            frames = cube[region_num]
            rect = self.image_area._region_rects.get(region_key)
            if rect is None:
                return [], []
            x0, y0, xr, yr = rect.x(), rect.y(), rect.width(), rect.height()
            if not (xr and yr):
                return [], []

            # Completed energies only: everything before the in-progress index
            # while scanning; the whole stack once the scan has finished.
            eidx = im.get('energy_index')
            n = min(len(frames), len(energies))
            last = min(eidx, n) if (self._scanning and isinstance(eidx, int)) else n

            r = self._spectrum_region
            rx0, rx1 = r['xCenter'] - r['xRange'] / 2.0, r['xCenter'] + r['xRange'] / 2.0
            ry0, ry1 = r['yCenter'] - r['yRange'] / 2.0, r['yCenter'] + r['yRange'] / 2.0
            # The ROI only analyses pixels that were actually scanned: dragged
            # off the imaged region entirely, it has nothing to average (clamping
            # would otherwise report a spurious one-pixel edge strip).
            if rx1 <= x0 or rx0 >= x0 + xr or ry1 <= y0 or ry0 >= y0 + yr:
                return [], []
            xs, ys = [], []
            for i in range(last):
                frame = frames[i]
                if not (isinstance(frame, np.ndarray) and frame.ndim >= 2):
                    continue
                ny, nx = frame.shape[:2]        # row-major frames: [y, x]
                cx0, cx1 = sorted((int(round((rx0 - x0) / xr * nx)),
                                   int(round((rx1 - x0) / xr * nx))))
                cy0, cy1 = sorted((int(round((ry0 - y0) / yr * ny)),
                                   int(round((ry1 - y0) / yr * ny))))
                cx0, cx1 = max(0, min(nx, cx0)), max(0, min(nx, cx1))
                cy0, cy1 = max(0, min(ny, cy0)), max(0, min(ny, cy1))
                sub = frame[cy0:max(cy0 + 1, cy1), cx0:max(cx0 + 1, cx1)]
                if sub.size == 0:
                    continue
                xs.append(energies[i])
                ys.append(float(np.nanmean(sub)))
            return xs, ys
        except Exception:
            return [], []

    def _lineout_panel(self):
        """A single cursor line-cut through the image, in physical µm — the
        horizontal (X, red) or vertical (Y, cyan) cut, toggled by the X/Y pill in
        the card header.  The two cuts live on very different position axes, so
        only one shows at a time.  Fed live by ImageArea.cursor_changed."""
        pw = dw.style_plot(pg.PlotWidget())
        pw.setLabel("bottom", "x", units="µm")
        self._lineout_plot = pw
        self._lineout_h = pw.plot([], [], pen=pg.mkPen("#ff3b30", width=1.6))
        self._lineout_v = pw.plot([], [], pen=pg.mkPen("#37d7ff", width=1.6))
        self._lineout_axis = 0          # 0 = X (horizontal cut), 1 = Y (vertical)
        self._last_cursor = None
        return pw

    def _switch_profile(self, index):
        """Swap the header's right-hand control with the tab: the spectrum note
        for Spectrum, the X/Y line-cut pill for Line-outs.

        The Spectrum tab also owns the spectrum ROI (replacing the old spatial-tab
        checkbox): selecting Spectrum shows the ROI, Line-outs hides it.  Guarded
        so the init call (before the spatial machinery exists) is a safe no-op."""
        self._profile_stack.setCurrentIndex(index)
        lineout = index == 1
        self._profile_note.setVisible(not lineout)
        self._lineout_axis_well.setVisible(lineout)
        if hasattr(self, "image_area") and hasattr(self, "_scan_regions"):
            self._toggle_spectrum(index == 0)
        if not lineout:
            self._update_roi_spectrum()      # entering Spectrum tab → draw it

    def _set_profile_tab(self, index):
        """Programmatically select a profile tab (Spectrum=0, Line-outs=1), keeping
        the pill group's checked state in sync — idClicked only fires on real
        clicks, so setting the button checked alone would not run _switch_profile."""
        grp = getattr(self, "_profile_grp", None)
        if grp is not None:
            b = grp.button(index)
            if b is not None:
                b.setChecked(True)
        self._switch_profile(index)

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
        self.detector_panel = DetectorPanel(self._daq_info, self.controller)
        v.addWidget(self.detector_panel)
        v.addWidget(self._build_motors(), 1)
        return col

    def _build_motors(self):
        card, body = dw.card("Motors")
        # Tabs are data-driven: one per distinct motor `group` in motor.json.
        self._motor_group_names = self._motor_groups()
        labels = [g.title() for g in self._motor_group_names] or ["Motors"]
        if self._motor_group_index >= len(self._motor_group_names):
            self._motor_group_index = 0
        grp_well, _ = dw.segmented(labels, self._motor_group_index)
        card.header_layout.addWidget(grp_well)

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
        grp_well.group.idClicked.connect(show_group)

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
        # Recent activity: what this window last asked the instrument to do, and
        # what came back.  A fixed number of rows so the footer never resizes;
        # the oldest line is the dimmest.
        self.cmd_log = QFrame()
        self.cmd_log.setStyleSheet(f"border-top:1px solid {C['border']};")
        lv = QVBoxLayout(self.cmd_log)
        lv.setContentsMargins(0, 8, 0, 0)
        lv.setSpacing(3)
        self._cmd_log_labels = []
        for _ in range(self._CMD_LOG_LINES):
            lbl = dw.label("", font=mono_font(9), color=C["text_faint"])
            lv.addWidget(lbl)
            self._cmd_log_labels.append(lbl)
        self._render_cmd_log()
        fv.addWidget(self.cmd_log)
        body.addWidget(footer)
        return card

    # Rows in the motor-rail activity log.  Fixed, so the footer never resizes.
    _CMD_LOG_LINES = 2

    def _log_activity(self, text, level="info"):
        """Add a line to the motor rail's activity log.

        ``level`` is "info" for something we asked for, "ok" for a confirmed
        result and "error" for a failure — it only picks the colour.  Safe to
        call before the rail exists (startup, placeholder mode): the entry is
        kept and painted once the widget is built.
        """
        entry = (datetime.now().strftime("%H:%M:%S"), text, level)
        self._cmd_log_entries.append(entry)
        self._render_cmd_log()

    def _render_cmd_log(self):
        """Paint the newest entries into the fixed rows, oldest at the top and
        dimmest.  Rows with no entry yet are blank rather than absent, so the
        footer keeps its height from the first paint."""
        labels = getattr(self, "_cmd_log_labels", None)
        if not labels:
            return
        entries = list(self._cmd_log_entries)[-len(labels):]
        pad = [None] * (len(labels) - len(entries))
        for lbl, entry in zip(labels, pad + entries):
            if entry is None:
                lbl.setText("")
                continue
            stamp, text, level = entry
            colour = {"error": C["alert"], "ok": C["ok"]}.get(level, C["text_dim"])
            # Older lines are dimmer: only the last row gets the full colour.
            if entry is not entries[-1]:
                colour = C["text_faint"]
            lbl.setText(f"{stamp}  {text}")
            lbl.setStyleSheet(f"color:{colour};background:transparent;")

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
            nb.addWidget(dw.label(name, role="mono"))
            nb.addWidget(dw.label(kind, role="microLabel"))
            # Wider name column (motor names were truncating); the value column is
            # the flexible one (columnStretch below), so this space comes straight
            # out of it — shrinking the value column by roughly a third.
            nw = QWidget(); nw.setFixedWidth(150); nw.setLayout(nb)
            g.addWidget(nw, 0, 0)
            # value + travel bar
            vb = QVBoxLayout()
            vb.setSpacing(3)
            vrow = QHBoxLayout()
            vrow.setSpacing(6)
            val = dw.label(pos, role="motion" if moving else "value")
            val.setFont(mono_font(13, QFont.Medium))
            vrow.addWidget(val)
            if unit:
                vrow.addWidget(dw.label(unit, role="monoFaint"))
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
                tgt.addItems([mi.format_enum(v) for v in enum_values])
                cur = mi.format_enum(info.get("last value"))
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
                tgt = dw.field(fill, align_right=True)
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
            from pystxmcontrol.gui.dashboard.motor_panel import MotorPanelWindow
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
            from pystxmcontrol.gui.dashboard.beamline_panel import BeamlinePanelWindow
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
    def _go_view(self, index):
        """Programmatically switch the top-level view and sync its nav tab."""
        b = self.nav_grp.button(index)
        if b is not None:
            b.setChecked(True)
        self._switch_view(index)

    # ════════════════════════════════════════════════════════════════════
    #  Browser view
    # ════════════════════════════════════════════════════════════════════
    def _build_browser_view(self):
        """The Browser tab: the standalone ``BrowserApp`` data browser, wired so
        Send to Analysis / Acquisition drive this window's views (see
        ``browser_app``)."""
        from pystxmcontrol.gui.dashboard.browser_app import BrowserApp
        self.browser_app = BrowserApp(
            controller=self.controller,
            logbook_model=getattr(self.controller, "logbook_model", None),
            parent=self)
        self.browser_app.send_to_analysis.connect(self._browser_to_analysis)
        self.browser_app.send_to_acquisition.connect(self._browser_to_acquisition)
        self.browser_app.set_scanning(self._scanning)
        return self.browser_app

    def _browser_to_acquisition(self, path):
        """Send to Acquisition: load the scan into the acquisition definition
        (if its driver is loadable) and switch to that view."""
        self._load_scan_file(path)
        self._go_view(0)

    def _browser_to_analysis(self, path):
        """Send to Analysis: load the stack into the Analysis tab and show it."""
        if getattr(self, "analysis_app", None) is not None:
            self.analysis_app.load_file(path)
        self._go_view(2)


    # ════════════════════════════════════════════════════════════════════
    #  Analysis view — the standalone dashboard-styled stack-analysis widget
    # ════════════════════════════════════════════════════════════════════
    def _build_analysis_view(self):
        """The Analysis tab: the standalone ``AnalysisApp`` stack-analysis
        widget, wired to the live controller (live data) and sharing the
        window's logbook.  See ``analysis_app``."""
        from pystxmcontrol.gui.dashboard.analysis_app import AnalysisApp
        self.analysis_app = AnalysisApp(
            controller=self.controller,
            logbook_model=getattr(self.controller, "logbook_model", None),
            parent=self)
        return self.analysis_app

    # ════════════════════════════════════════════════════════════════════
    #  Agent view — the standalone dashboard-styled task-agent console
    # ════════════════════════════════════════════════════════════════════
    def _build_agent_view(self):
        """The Agent tab: the standalone ``AgentApp`` console (conversation +
        logbook), wired to the live controller when connected and degrading to a
        read-only placeholder otherwise.  See ``agent_app``."""
        from pystxmcontrol.gui.dashboard.agent_app import AgentApp
        self._agent_app = AgentApp(
            controller=self.controller,
            logbook_model=getattr(self.controller, "logbook_model", None),
            default_dir_provider=self._logbook_default_dir,
            parent=self)
        return self._agent_app

    def _logbook_default_dir(self):
        """Base directory for New/Open logbook dialogs — the server's data
        directory when configured, else the user's home."""
        data_dir = (runtime_main_config().get("server") or {}).get("data_dir")
        if data_dir and os.path.isdir(data_dir):
            return data_dir
        return os.path.expanduser("~")

    # ── motor actions ────────────────────────────────────────────────────
    def _jog_step(self, name):
        return mi.jog_step(self._motor_info.get(name, {}))

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
        unit = self._motor_info.get(name, {}).get("unit", "")
        self._log_activity(f"move {name} → {pos:g}{(' ' + unit) if unit else ''}")
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
        unit = self._motor_info.get(name, {}).get("unit", "")
        sign = "+" if direction >= 0 else "−"
        self._log_activity(
            f"jog {name} {sign}{abs(step):g}{(' ' + unit) if unit else ''}")
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
        # Clear the last error so _show_scan_error only surfaces one raised by
        # THIS compile/start attempt.
        self._last_error = None
        if not self._compile_scan():
            self._show_scan_error("The scan could not be compiled — check the "
                                  "scan definition.")
            return
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
        if not c.start_scan():
            self._show_scan_error("The scan could not be started — check the "
                                  "scan definition.")
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
        self._last_error = None
        if not self._compile_scan(preview=True):
            self._show_scan_error("The preview could not be compiled — check the "
                                  "scan definition.")
            return
        # A preview is a single-image sanity check: force the outer loop off at
        # the point of execution so an "Execute Loop Scan" checkbox can never
        # turn a preview into the full looped sequence, regardless of how the
        # scan model was compiled.
        sm = c.get_scan_model()
        sm.set('loop_scan', False)
        sm.set('loop_points', 1)
        self.image_area.clear_region_frames()
        if not c.start_scan(preview=True):
            self._show_scan_error("The preview could not be started — check the "
                                  "scan definition.")

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
            user_comment = (self._comment_field.text()
                            if getattr(self, "_comment_field", None) else "")
            sm.set('comment', 'preview' if preview else user_comment)
            sm.set('driver', driver)
            sm.set('mode', sc.get('mode', 'continuousLine'))
            self._compile_loop_scan(sm, preview=preview)
            sm.set('daq_list', resolve_daq_list(getattr(client, 'daqConfig', {}), sc))

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

    def _compile_loop_scan(self, sm, preview=False):
        """Set the outer-loop-scan keys on the scan model from the Loop sequence
        group's "Execute Loop Scan" checkbox and fields.  When enabled the server
        (controller.runScan) repeats the whole scan at each loop-motor position,
        so ``loop_scan``/``loop_motor``/``loop_center``/``loop_range``/
        ``loop_points``/``loop_step`` must all be present in the scan dict.

        Previews (single region, single energy) never loop — the ``preview`` flag
        forces the loop off regardless of the checkbox so a Preview always runs a
        single image even while "Execute Loop Scan" is checked."""
        cb = getattr(self, "_loop_scan_check", None)
        enabled = bool(cb is not None and cb.isChecked() and not preview)
        if not enabled:
            # Fully neutralise the loop so no stale loop_points/motor from an
            # earlier full-scan compile can survive into this scan dict.
            sm.set('loop_scan', False)
            sm.set('loop_points', 1)
            return
        f = self._loop_fields
        center = float(f["center"].text())
        rng = float(f["range"].text())
        points = max(1, int(float(f["points"].text())))
        step = rng / (points - 1) if points > 1 else 0.0
        sm.set('loop_scan', True)
        sm.set('loop_motor', self._loop_motor_combo.currentText())
        sm.set('loop_center', center)
        sm.set('loop_range', rng)
        sm.set('loop_points', points)
        sm.set('loop_step', step)

    def _compile_image_regions(self, sm, preview=False):
        """Populate ``sm`` with the image-family spatial + energy regions and
        return the primary region dict (for the stats readout).

        ``preview=True`` emits only the first spatial region at a single energy
        (the start of the first energy region) — an abridged sanity check.  The
        view's region/energy lists are only read, never reassigned."""
        # Flush the live field rows into the active regions.  The spectrum ROI is
        # display-only (it selects the pixels the Profile spectrum averages), so
        # the Spatial fields never write to it and it is never emitted.
        if isinstance(self._active_region, int):
            self.scan_def.update_active_region(self._read_spatial_fields())
        self._sync_active_energy_region()

        self.scan_def.validate_image_grid(preview=preview)
        region = self.scan_def.emit_image_regions(sm, preview=preview)
        if preview:
            self.scan_def.emit_single_energy(sm)
        else:
            self.scan_def.emit_energy_regions(sm)
        return region

    def _compile_focus(self, sm, sc):
        """Populate ``sm`` for a single-line focus scan: one scan region (angled
        line × ZonePlateZ sweep) at a single energy.  Returns the region dict."""
        # Flush live edits from the fields into the focus model + R1 centre.
        self._on_focus_edit()
        self._on_line_edit()
        if isinstance(self._active_region, int):
            self.scan_def.update_active_region(self._read_spatial_fields())
        sm.set('z_motor', sc.get('z_motor', 'ZonePlateZ'))
        sm.set('tiled', False)          # focus is a single line, never tiled
        sm.set('autofocus', bool(getattr(self, '_focus_move_to_best', None)
                                 and self._focus_move_to_best.isChecked()))
        region = self._focus_region_scan_dict()
        sm.add_scan_region('Region1', region)

        # Single energy: the first energy region's start, at its dwell.
        self._sync_active_energy_region()
        e0 = self.scan_def.emit_single_energy(sm)
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
            self.scan_def.update_active_region(self._read_spatial_fields())
        sm.set('tiled', False)          # a single line is never tiled
        region = self._line_spectrum_region_scan_dict()
        sm.add_scan_region('Region1', region)
        # Energy regions — identical to the Image path (multi-region, multi-energy).
        self._emit_energy_regions(sm)
        return region

    def _emit_energy_regions(self, sm):
        """Flush the active energy row, then emit the full multi-region energy
        axis (as an Image scan uses)."""
        self._sync_active_energy_region()
        self.scan_def.emit_energy_regions(sm)

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
        """Read the Motor-scan group's center/range/points fields into a scan
        region.  A single-motor scan has one row."""
        def read(ax):
            try:
                c = float(ax['center'].text() or 0)
                r = abs(float(ax['range'].text() or 0))
                n = max(1, int(float(ax['npts'].text() or 1)))
            except ValueError:
                c, r, n = 0.0, 0.0, 1
            return c, r, n
        x_axis = read(self._motor_axis_widgets[0])
        y_axis = read(self._motor_axis_widgets[1]) if axes >= 2 else None
        return motor_scan_region(x_axis, y_axis)

    def _line_spectrum_region_scan_dict(self):
        return self.scan_def.line_spectrum_scan_region()

    def _ls_energy_span(self):
        return self.scan_def.energy_span()

    def _show_last_scan_image(self):
        """Paint the most recently recorded ``.stxm`` scan at its *own* fixed
        physical extent (the region it was scanned over), independent of the
        editable scan-region ROIs.  Region1 is aligned to that extent so a new
        scan starts as "the whole displayed image", ready to be shrunk to a
        sub-region.  No-op — black canvas + ROI boxes — when no file is readable."""
        if not hasattr(self, "image_area"):
            return
        try:
            path = find_last_scan_file()
            if not path:
                return
            loaded = load_last_scan(path)
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
            self._set_image_header(
                filename=os.path.basename(path),
                subline=f"{int(arr.shape[1])} × {int(arr.shape[0])} px")
        except Exception as e:
            print(f"[dashboard] could not display last scan: {e}")

    # Only these drivers produce a plain 2-D raster that maps cleanly onto the
    # Acquisition view's image + spatial/energy region fields.  Focus/line/spiral/
    # ptychography files have other geometries and are refused by Load scan.
    _LOADABLE_DRIVERS = ("linear_image", "double_motor_scan")

    def _on_load_scan(self):
        """Load scan button: pick a ``.stxm`` file and, if its driver is loadable,
        display it and seed the spatial + energy regions from the file — the same
        setup an externally launched scan performs."""
        cfg = runtime_main_config()
        start_dir = (cfg.get("server") or {}).get("data_dir") or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Load scan", start_dir, "STXM data (*.stxm);;All files (*)")
        if path:
            self._load_scan_file(path)

    def _load_scan_file(self, path):
        """Read *path*, refuse it unless its scan driver is in _LOADABLE_DRIVERS,
        then paint the frame at its physical extent and populate the spatial +
        energy region widgets (mirroring _on_external_scan_geometry / the energy
        prefill so a loaded scan sets up exactly like an external one)."""
        name = os.path.basename(path)
        info = read_scan_file(path)
        if info is None:
            QMessageBox.warning(self, "Load scan",
                                f"Could not read a scan image from:\n{name}")
            return
        scan_type = info.get("scan_type")
        driver = (self._scan_cfg(scan_type) or {}).get("driver") if scan_type else None
        if driver not in self._LOADABLE_DRIVERS:
            QMessageBox.information(
                self, "Load scan",
                f"'{name}' is a '{scan_type or 'unknown'}' scan "
                f"(driver: {driver or 'unknown'}).\n\n"
                f"Load scan only supports {', '.join(self._LOADABLE_DRIVERS)} "
                f"(e.g. Image, TEY/XRF Image, Double Motor, OSA Image).")
            return
        if not hasattr(self, "image_area"):
            return

        # Spatial region + image extent, exactly as _on_external_scan_geometry does.
        frame = info["frame"]
        extent = info.get("extent")
        if extent is not None:
            xc, yc, xr, yr = extent
            self.image_area.set_image_extent(xc, yc, xr, yr)
            r = {'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr,
                 'xPoints': int(info.get("xPoints", frame.shape[1])),
                 'yPoints': int(info.get("yPoints", frame.shape[0]))}
            self._scan_regions = [r]
            self._active_region = 0
            self._keep_spectrum_region(r)
            self._write_spatial_fields(r)
        # Force a fresh auto-level: set_primary_frame only levels the first frame,
        # but a loaded file replaces whatever was shown and needs its own contrast.
        self.image_area._primary_seeded = False
        self.image_area.set_primary_frame(frame)
        self._image_seeded = True
        self._refresh_spatial_image(fit=True)

        # Energy region(s) from the file's energy list, as the energy prefill does.
        n_energies = 1
        energies = info.get("energies")
        if energies is not None and len(energies):
            start = float(energies[0]); stop = float(energies[-1])
            n = int(len(energies))
            step = abs(stop - start) / (n - 1) if n > 1 else 0.0
            self._energy_regions = [{'start': start, 'stop': stop, 'step': step,
                                     'dwell': float(info.get("dwell", 1.0)), 'n': n}]
            self._active_energy_region = 0
            self._load_energy_region(0)
            n_energies = n

        n_regions = len(self._scan_regions)
        e_word = "energy" if n_energies == 1 else "energies"
        self._set_image_header(
            filename=name,
            subline=f"Region 1 of {n_regions} · {n_energies} {e_word}")
        self._refresh_image_meta()
        self._on_status(f"Loaded {name} ({scan_type})")

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

    def _set_image_header(self, filename=None, subline=None):
        """Update the toolbar labels above the main image: the filename and the
        region/energy subline.  Either argument may be None to leave that label
        unchanged."""
        if filename is not None and hasattr(self, "_image_title_lbl"):
            self._image_title_lbl.setText(filename)
        if subline is not None and hasattr(self, "_image_subline_lbl"):
            self._image_subline_lbl.setText(subline)

    def _save_image_png(self):
        """Export the current main-image view to a PNG (the same rendered scene the
        operator sees, including ROIs/overlays), mirroring the Browser's Export PNG.
        The default filename is taken from the current image title."""
        if not hasattr(self, "image_area"):
            return
        stem = os.path.splitext(self._image_title_lbl.text().strip())[0] \
            if getattr(self, "_image_title_lbl", None) else "image"
        if not stem or stem == "—":
            stem = "image"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PNG", f"{stem}.png", "PNG Images (*.png)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".png"
        # Grab the whole ImageArea widget (image + the bottom metadata overlay +
        # scale bar, which are Qt overlay widgets a pyqtgraph scene export would
        # miss) with the ROI boxes hidden so the saved PNG shows only the data.
        try:
            self.image_area.set_rois_visible(False)
            pixmap = self.image_area.grab()
            self.image_area.set_rois_visible(True)
            if not pixmap.save(path, "PNG"):
                raise IOError("QPixmap.save returned False")
            self._on_status(f"Saved PNG: {os.path.basename(path)}")
        except Exception as e:
            self.image_area.set_rois_visible(True)
            QMessageBox.warning(self, "Save PNG", f"Could not save PNG:\n{e}")

    def _prefill_from_last_scan(self, scan_type='Image', spatial=True, energy=True):
        """Pre-fill the spatial and/or energy regions from the last executed scan of
        ``scan_type``, which the server ships in
        ``client.main_config['lastScan'][scan_type]`` (on connect, and now also at
        scan start — see dataHandler.startScanProcess).  Called at startup/reconnect
        for the last Image scan (both), and by ``_on_external_scan_started`` with
        ``spatial=False`` (energy only — the spatial region is driven live from the
        data stream in ``_on_external_scan_geometry``, which is authoritative and
        server-version-independent, so we must not overwrite it from the cache).
        No-op if unavailable."""
        client = getattr(self.controller, 'client', None)
        main_cfg = getattr(client, 'main_config', None) or {}
        last = (main_cfg.get('lastScan') or {}).get(scan_type)
        if not last:
            return
        try:
            if spatial:
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
                    self._keep_spectrum_region(regs[0])
                    self._write_spatial_fields(regs[0])
                    self._refresh_spatial_image(fit=True)

            if not energy:
                return
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

            comment = last.get('comment')
            if (comment and comment != 'preview'
                    and getattr(self, '_comment_field', None)):
                self._comment_field.setText(str(comment))
        except (ValueError, TypeError, KeyError) as ex:
            self._on_error(f"Could not pre-fill last scan: {ex}")

    # Shown when no proposals come back from the ALS API (offline, or none
    # currently active for this beamline) — the combobox always has this entry.
    # Placeholder shown as the default combobox entry — nothing is selected until
    # the user picks a real proposal (which activates Begin scan in User mode).
    _SELECT_PROPOSAL = "Select a proposal…"

    def _populate_proposal_combo(self):
        """Fill the Proposal combobox from the ALS API's current ESAF list for
        this beamline.  Always starts on a "Select a proposal…" placeholder so
        no proposal is pre-selected; the list is empty behind it when the API
        can't be reached (dev / offline)."""
        combo = getattr(self, "_proposal_combo", None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        self._esaf_participants = {}
        combo.addItem(self._SELECT_PROPOSAL)      # index 0: nothing selected
        try:
            client = getattr(self.controller, "client", None)
            beamline = ((getattr(client, "main_config", None) or {})
                        .get("source", {}).get("beamline"))
            if not beamline:
                raise RuntimeError("no beamline configured")
            from pystxmcontrol.utils.alsapi import getCurrentEsafList
            esaf_list, participants_list = getCurrentEsafList(beamline=beamline)
            for esaf, participants in zip(esaf_list, participants_list):
                combo.addItem(esaf)
                self._esaf_participants[esaf] = participants
        except Exception as e:
            print(f"Could not fetch ESAF list: {e}")
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _on_proposal_changed(self, _idx=0):
        """Selecting a proposal is the sole source of the experimenter list
        (resolved lazily in _proposal_parts()) and, in User mode, the gate that
        activates the Begin-scan button."""
        self._update_begin_enabled()

    def _proposal_parts(self):
        """Return (proposal, experimenters) for the selected proposal.  The
        experimenter list comes from that proposal's ALS-API participants."""
        combo = getattr(self, "_proposal_combo", None)
        if combo is None:
            return "", ""
        proposal = combo.currentText().strip()
        if not proposal or proposal == self._SELECT_PROPOSAL:
            return "", ""
        experimenters = ", ".join(self._esaf_participants.get(proposal, []))
        return proposal, experimenters

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
        """Total acquisition points in a compiled scan model."""
        return stats.total_scan_points(sm.get('scan_regions', {}) or {},
                                       sm.get('energy_regions', {}) or {},
                                       is_focus=self._focus_mode)

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
            # Image regions only — the spectrum ROI is not scanned, so it adds
            # neither points nor time.
            regions = [region_scan_dict(r) for r in self._scan_regions]

        # Energy regions.  Focus is always a single energy (compile forces it),
        # so use only the first region's dwell there.
        eregs = list(getattr(self, "_energy_regions", None) or [])
        if is_focus:
            d0 = eregs[0]["dwell"] if eregs else 2.0
            eff = [{"dwell": d0, "n": 1}]
        else:
            eff = eregs

        est, pts, _n_energies = stats.estimate(
            regions, eff, is_focus=is_focus, is_ptycho=is_ptycho)

        # Point-mode scans step to each point rather than sweeping the stage.
        point_mode = bool(
            is_motor and (self._scan_cfg(scan_type) or {}).get("mode") == "point")
        vel = stats.scan_velocity(regions, eff[0]["dwell"] if eff else 1.0,
                                  point_mode=point_mode)
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
        return self.scan_def.active_region_dict()

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
            # The spectrum ROI is owned by the Profile panel's Spectrum tab; drop
            # it by switching back to Line-outs (which clears it and re-selects R1).
            self._set_profile_tab(1)
            return
        elif len(self._scan_regions) > 1:
            del self._scan_regions[self._active_region]
            self._load_spatial_region(min(self._active_region,
                                          len(self._scan_regions) - 1))
        self._refresh_spatial_image(fit=True)

    def _toggle_spectrum(self, on):
        """Show/hide the spectrum ROI (a distinct-coloured box).

        The spectrum ROI is a VISUALIZATION region only: it selects the pixels
        averaged into the Profile spectrum and is never compiled into the scan
        (see _compile_image_regions) nor counted in the time estimate.  It floats
        independently of the spatial scan regions — never the active region,
        never edits the Spatial tab fields — so toggling or dragging it leaves
        the scan definition untouched.  Its point counts merely mirror the base
        region so the dict has the same shape as a spatial region."""
        if on:
            # Re-selecting the Spectrum tab keeps the box the operator already
            # placed; it is only created the first time.
            if self._spectrum_region is None:
                self._spectrum_region = self._default_spectrum_region()
        else:
            self._spectrum_region = None
        self._refresh_spatial_image(fit=True)
        self._update_roi_spectrum()

    def _default_spectrum_region(self):
        """A fresh spectrum ROI: a box 40% the size of the region being defined,
        centred on it."""
        base = self._active_region_dict() or self._read_spatial_fields()
        return {'xCenter': base['xCenter'], 'yCenter': base['yCenter'],
                'xRange': max(base['xRange'] * 0.4, 1.0),
                'yRange': max(base['yRange'] * 0.4, 1.0),
                'xPoints': max(2, int(base.get('xPoints', 2))),
                'yPoints': max(2, int(base.get('yPoints', 2)))}

    def _keep_spectrum_region(self, region):
        """Carry the spectrum ROI over to a new spatial geometry (a scan starting,
        a file loaded, a config prefill).

        The ROI is display-only, so a new scan must never silently delete it —
        the Profile panel would still show the Spectrum tab with no box to drag.
        It lives in absolute µm, so it is left exactly where the operator put it
        whenever it still overlaps the new region; only a box that has fallen
        completely outside is re-centred (its size preserved, capped to fit)."""
        r = self._spectrum_region
        if r is None or not region:
            return
        try:
            overlaps = (
                abs(r['xCenter'] - region['xCenter'])
                < (r['xRange'] + region['xRange']) / 2.0
                and abs(r['yCenter'] - region['yCenter'])
                < (r['yRange'] + region['yRange']) / 2.0)
        except (KeyError, TypeError):
            return
        if overlaps:
            return
        r['xCenter'], r['yCenter'] = region['xCenter'], region['yCenter']
        r['xRange'] = min(r['xRange'], region['xRange'])
        r['yRange'] = min(r['yRange'], region['yRange'])

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
            # Always "active" for styling only: the spectrum ROI is not a scan
            # region, but keeping its resize handles visible lets it be edited
            # without ever becoming the selected spatial region.
            out.append({'key': 'spectrum', 'label': "Spec", 'kind': 'spectrum',
                        'active': True,
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
                and len(self._scan_regions) > 1)
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
        # The spectrum ROI floats independently of the spatial regions: selecting
        # it must NOT make it the active region or touch the Spatial fields.
        if key == 'spectrum':
            return
        target = self._key_to_target(key)
        if target != self._active_region:
            self._load_spatial_region(target)

    def _on_roi_moving(self, key, xc, yc, xr, yr):
        """Live geometry during a drag: update the target's model, no FOV refit.

        The spectrum ROI is decoupled from the spatial regions — dragging it only
        updates its own geometry and the spectrum trace, never a scan region or
        the shared Spatial fields."""
        if key == 'spectrum':
            if self._spectrum_region is not None:
                self._spectrum_region.update(
                    {'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr})
                self._update_roi_spectrum()
            return
        target = self._key_to_target(key)
        reg = self._scan_regions[target]
        reg.update({'xCenter': xc, 'yCenter': yc, 'xRange': xr, 'yRange': yr})
        if target == self._active_region:
            self._syncing_spatial = True
            try:
                self._write_spatial_fields(reg)
            finally:
                self._syncing_spatial = False

    def _on_roi_moved(self, key, xc, yc, xr, yr):
        """Drag finished: commit geometry."""
        self._on_roi_moving(key, xc, yc, xr, yr)
        if key == 'spectrum':
            # A spectrum-ROI drag changes neither the scan definition nor the FOV.
            self._refresh_spatial_image()
            return
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
        """The focus-scan model, created on first use centred on the zone
        plate's current position."""
        return self.scan_def.ensure_focus_region(
            self._current_motor_pos('ZonePlateZ'))

    def _line_center(self):
        return self.scan_def.line_center()

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
        self._ensure_focus_region()          # seed Z from the live position
        return self.scan_def.focus_scan_region()

    def _recompute_energy_n(self):
        """N = round(|stop-start| / |step|) + 1, from the current Start/Stop/Step."""
        try:
            s = float(self._energy_fields['start'].text())
            e = float(self._energy_fields['stop'].text())
            st = float(self._energy_fields['step'].text() or 0)
            self._energy_fields['n'].setText(str(energy_n(s, e, st)))
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
                'n': energy_n(start, stop, step)}

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
            'dwell': last['dwell'], 'n': energy_n(start, stop, step)})
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

    def _save_energy_preset(self):
        """Save the current energy regions to a JSON preset file, in the same
        ``{"energy_regions": {"EnergyRegion1": {...}}}`` format the MVC window reads
        (see mainwindow_mvc.open_energy_definition), so presets are interchangeable.

        The dialog opens on the shared presets directory: a preset saved there is
        discoverable BY NAME (its filename) to the task agent and the MCP server as well
        as to Load Preset, so the operator defines an edge once and can then just ask for
        it. Saving elsewhere still works — it is only the starting directory."""
        self._sync_active_energy_region()   # flush the active field row into the model
        regs = getattr(self, '_energy_regions', None) or []
        if not regs:
            return
        energy_regions = energy_presets.regions_to_dict(
            [{'start': r['start'], 'stop': r['stop'], 'step': r['step'],
              'n_energies': r['n'], 'dwell': r['dwell']} for r in regs])
        start_dir = energy_presets.presets_dir()
        try:
            os.makedirs(start_dir, exist_ok=True)
        except OSError:
            start_dir = ''      # fall back to the dialog's default location
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Energy Preset", start_dir, "JSON Files (*.json);;All Files (*)")
        if not filename:
            return
        if not os.path.splitext(filename)[1]:
            filename += '.json'
        try:
            with open(filename, 'w') as f:
                json.dump({'energy_regions': energy_regions}, f, indent=2)
            self._on_status(f"Saved energy preset: {os.path.basename(filename)}")
        except OSError as e:
            QMessageBox.warning(self, "Save Energy Preset",
                                f"Could not save preset:\n{e}")

    @staticmethod
    def _read_energy_regions_json(path):
        """Read an energy-preset JSON file.  Accepts either
        ``{"energy_regions": {...}}`` or a raw ``{EnergyRegionN: {...}}`` dict
        (matching mainwindow_mvc.open_energy_definition).  Returns the regions dict
        or None if unreadable / empty.

        Delegates to the shared reader so the GUI and the agents agree on what a saved
        energy definition is, rather than agreeing by luck."""
        return energy_presets.read_energy_regions_json(path)

    def _apply_energy_regions_dict(self, regions):
        """Populate the energy fields from an ``{EnergyRegionN: {...}}`` dict.
        Returns True on success (shared by the file loader and Favorites)."""
        # The shared normaliser orders regions by their EnergyRegionN index and derives a
        # missing 'step', so hand-written presets load the same way here as for an agent.
        normalized = energy_presets.normalize_regions(regions)
        if normalized is None:
            return False
        eregs = [{'start': r['start'], 'stop': r['stop'], 'step': r['step'],
                  'dwell': r['dwell'], 'n': r['n_energies']} for r in normalized]
        self._energy_regions = eregs
        self._active_energy_region = 0
        self._load_energy_region(0)
        self._refresh_image_meta()
        return True

    def _load_energy_preset(self):
        """Load energy regions from a JSON preset file and populate the fields."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Energy Preset", "", "JSON Files (*.json);;All Files (*)")
        if not filename:
            return
        regions = self._read_energy_regions_json(filename)
        if regions is None:
            QMessageBox.warning(self, "Load Energy Preset",
                                f"No readable energy regions in:\n"
                                f"{os.path.basename(filename)}")
            return
        if not self._apply_energy_regions_dict(regions):
            QMessageBox.warning(self, "Load Energy Preset",
                                f"Malformed energy preset:\n{os.path.basename(filename)}")
            return
        self._on_status(f"Loaded energy preset: {os.path.basename(filename)}")

    # ── energy favorites (drag-drop presets pinned to the Favorites bar) ──────
    @staticmethod
    def _favorites_file_path():
        """Where energy favorites are persisted: alongside the runtime config
        (pystxmcontrol_cfg), falling back to the repo config dir, then home.

        Resolved by the shared module, which is also where the agents look for presets by
        name — so a pinned favorite is agent-visible without any export step."""
        return energy_presets.favorites_file_path()

    def _read_favorites_file(self):
        """Load the persisted favorites list, keeping only well-formed entries."""
        try:
            with open(self._favorites_file_path(), 'r') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        favs = data.get('favorites', []) if isinstance(data, dict) else []
        out = []
        for fav in favs:
            if isinstance(fav, dict) and isinstance(fav.get('energy_regions'), dict):
                out.append({'alias': str(fav.get('alias', 'Preset')),
                            'energy_regions': fav['energy_regions']})
        return out

    def _write_favorites_file(self):
        try:
            with open(self._favorites_file_path(), 'w') as f:
                json.dump({'favorites': self._favorites}, f, indent=2)
        except OSError as e:
            self._on_error(f"Could not save favorites: {e}")

    @staticmethod
    def _favorite_tooltip(fav):
        lines = []
        for r in (fav.get('energy_regions') or {}).values():
            lines.append(f"{r.get('start')}–{r.get('stop')} eV · "
                         f"{r.get('n_energies')} pts · {r.get('dwell')} ms")
        return "\n".join(lines) or "energy preset"

    def _rebuild_favorites_bar(self):
        """Redraw the Favorites bar from ``self._favorites``: one button each
        (left-click applies, right-click removes), or a hint when empty."""
        row = self._favorites_bar.layout_row()
        while row.count():
            item = row.takeAt(0)
            wdg = item.widget()
            if wdg is not None:
                wdg.deleteLater()
        if not self._favorites:
            row.addWidget(dw.label("Drag an energy preset (.json) here",
                                      role="monoFaint"))
            return
        for i, fav in enumerate(self._favorites):
            b = QPushButton(fav.get('alias', f'Preset {i + 1}'))
            b.setProperty("role", "preset")
            b.setToolTip(self._favorite_tooltip(fav))
            b.clicked.connect(lambda _=False, idx=i: self._apply_favorite(idx))
            b.setContextMenuPolicy(Qt.CustomContextMenu)
            b.customContextMenuRequested.connect(
                lambda _pos, idx=i: self._favorite_context_menu(idx))
            row.addWidget(b)

    def _on_favorite_dropped(self, path):
        """A .json was dropped on the Favorites bar: read its energy regions, ask
        for an alias, then pin it as a new favorite button."""
        regions = self._read_energy_regions_json(path)
        if regions is None:
            QMessageBox.warning(self, "Add favorite",
                                f"No readable energy regions in:\n"
                                f"{os.path.basename(path)}")
            return
        default_alias = os.path.splitext(os.path.basename(path))[0]
        alias, ok = QInputDialog.getText(
            self, "Add favorite", "Favorite name:", text=default_alias)
        if not ok:
            return
        alias = alias.strip() or default_alias
        self._favorites.append({'alias': alias, 'energy_regions': regions})
        self._write_favorites_file()
        self._rebuild_favorites_bar()
        self._on_status(f"Added favorite: {alias}")

    def _apply_favorite(self, idx):
        """Left-click: apply a favorite's energy regions (like Load Preset)."""
        if not (0 <= idx < len(self._favorites)):
            return
        fav = self._favorites[idx]
        if self._apply_energy_regions_dict(fav.get('energy_regions')):
            self._on_status(f"Applied favorite: {fav.get('alias')}")
        else:
            self._on_error(f"Favorite '{fav.get('alias')}' has no valid energy regions")

    def _favorite_context_menu(self, idx):
        """Right-click: offer to remove the favorite."""
        menu = QMenu(self)
        remove_act = menu.addAction("Remove favorite")
        if menu.exec(QCursor.pos()) is remove_act:
            self._remove_favorite(idx)

    def _remove_favorite(self, idx):
        if not (0 <= idx < len(self._favorites)):
            return
        alias = self._favorites[idx].get('alias', 'this favorite')
        reply = QMessageBox.question(
            self, "Remove favorite", f"Remove energy favorite '{alias}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        del self._favorites[idx]
        self._write_favorites_file()
        self._rebuild_favorites_bar()

    def _on_error(self, msg):
        # Remember the most recent error so a failed scan compile/start can pop it
        # up (see _show_scan_error) — the controller and _compile_scan both report
        # scan-definition problems through error_occurred.
        self._last_error = msg
        self._log_activity(msg, level="error")
        print(f"[dashboard] ERROR: {msg}")
        self.statusBar().showMessage(f"⚠  {msg}", 8000)

    def _show_scan_error(self, fallback="The scan could not be run."):
        """Pop up a modal warning for a failed scan compile/start.  Uses the last
        error message reported through ``error_occurred`` (set by ``_on_error``),
        falling back to a generic message if none was captured."""
        msg = getattr(self, "_last_error", None) or fallback
        QMessageBox.warning(self, "Scan error", msg)

    def _on_status(self, msg):
        self.statusBar().showMessage(msg, 5000)

    # ── interactions ─────────────────────────────────────────────────────

    def _set_scanning(self, scanning):
        was_scanning = self._scanning
        self._scanning = bool(scanning)
        if self._scanning != was_scanning:
            self._log_activity(
                f"scan {self.scan_type.currentText()} started" if self._scanning
                else "scan finished",
                level="info" if self._scanning else "ok")
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
        # Enabled state: always active as Cancel while scanning; when idle it is
        # gated by mode + proposal (User mode needs a proposal selected).
        self._update_begin_enabled()
        # A finished scan releases its final energy into the ROI spectrum (during
        # the scan the last energy is the in-progress one and so is held back).
        if was_scanning and not self._scanning:
            self._update_roi_spectrum()
        # Gate the Browser's Send-to-Acquisition on scan state.
        if getattr(self, "browser_app", None) is not None:
            self.browser_app.set_scanning(self._scanning)

    def _on_external_scan_started(self, scan_type):
        """A scan was started outside the Begin button — by the task agent, a
        remote script, or already running when the GUI attached.  The controller
        has already flipped its own ``scanning`` flag and is streaming data into
        the view; put the button into Cancel mode so the operator can still stop
        the scan (scan completion emits scan_state_changed(False), which restores
        the button via _set_scanning).  The scan-type combo is intentionally left
        untouched: retargeting it mid-scan would run _on_scan_type and tear down
        the region widgets / display while data is arriving.

        The spatial + energy region fields ARE refreshed to match the running scan
        (its parameters otherwise go stale the moment the agent launches something
        different from what the operator last set up).  The server pushes the scan's
        config over the SUB stream at scan start, refreshing the client's cached
        main_config['lastScan'][scan_type] before the first frame arrives, so
        _prefill_from_last_scan reads the just-launched parameters.  Limited to
        image-like scans (a spatial grid over energy regions): the line-scan (Focus /
        Line Spectrum) and motor-scan views carry their own field layouts and are
        left alone."""
        self._set_scanning(True)
        if not (self._scan_is_focus(scan_type)
                or self._scan_is_line_spectrum(scan_type)
                or self._scan_is_motor(scan_type)):
            # Spatial region is driven live from the data stream
            # (_on_external_scan_geometry); take only the energy regions from the
            # cached config here so we don't overwrite the live spatial geometry.
            self._prefill_from_last_scan(scan_type, spatial=False)

    def _on_external_scan_geometry(self, config, scan_type):
        """Live scan geometry from the data stream (MainController derives
        xCenter/xRange/xPoints… from the first broadcast frame of an externally
        launched scan in ``scan_region_geometry_updated``).  Unlike
        ``_prefill_from_last_scan`` — which reads the client's cached
        ``main_config['lastScan']`` and so needs the updated server build to be
        fresh — this rides the SAME data that already positions the image, so the
        spatial region + ROI track the running scan against ANY server.

        The controller emits this exactly once per external scan, inside its
        ``not self.scanning`` block and BEFORE it flips ``scanning`` true / emits
        ``external_scan_started`` (main_controller.py) — so there is deliberately
        NO ``self._scanning`` guard here (that flag is still false at this point),
        and the energy prefill in ``_on_external_scan_started`` is energy-only so it
        cannot clobber the spatial values applied here.

        Only spatial geometry is broadcast — the energy-region list is not — so
        energy comes from the config prefill.  The signal always keys a single
        'Region1', so only the currently scanning region is reflected."""
        if (self._scan_is_focus(scan_type)
                or self._scan_is_line_spectrum(scan_type)
                or self._scan_is_motor(scan_type)):
            return
        regs = (config or {}).get('scan_regions') or {}
        if not regs:
            return
        region = next(iter(regs.values()))
        try:
            r = {'xCenter': float(region['xCenter']),
                 'yCenter': float(region['yCenter']),
                 'xRange':  float(region['xRange']),
                 'yRange':  float(region['yRange']),
                 'xPoints': max(1, int(region['xPoints'])),
                 'yPoints': max(1, int(region['yPoints']))}
        except (KeyError, ValueError, TypeError):
            return
        self._scan_regions = [r]
        self._active_region = 0
        # The spectrum ROI is display-only and survives the new geometry.
        self._keep_spectrum_region(r)
        self._write_spatial_fields(r)
        self._refresh_spatial_image(fit=True)

    def _toggle_expert(self):
        """Toggle Staff/User mode.  Entering Staff mode requires the staff
        password; dropping back to User mode is unrestricted."""
        if not self._expert:
            if not self._check_staff_password():
                return
            self._expert = True
        else:
            self._expert = False
        self._apply_mode()

    def _apply_mode(self):
        """Apply the current Staff/User mode across the UI: the mode-button
        label, staff-only widgets, the command log, the motor list (Staff sees
        ``display:false`` motors too), and the Begin-scan proposal gate."""
        staff = self._expert
        # Button shows the currently active mode.
        self.mode_btn.setText("Staff mode" if staff else "User mode")
        if getattr(self, "cmd_log", None) is not None:
            self.cmd_log.setVisible(staff)
        for wdg in self._staff_widgets:
            wdg.setVisible(staff)
        # Refilter the motor panel: User mode hides display:false motors.
        if hasattr(self, "motor_layout"):
            self._repopulate_motors()
        self._update_begin_enabled()

    def _mode_btn_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Set staff password…", self.set_staff_password)
        menu.exec(self.mode_btn.mapToGlobal(pos))

    # ── staff password (mirrors mainwindow_mvc: PBKDF2 hash in main.json) ──────
    @staticmethod
    def _check_staff_password(self):
        """Prompt for the staff password.  Returns True if authenticated.  When
        no password has been set yet, offer to create one (matching the classic
        window)."""
        cfg = auth.read_config()
        if not auth.has_password(cfg):
            reply = QMessageBox.question(
                self, "Staff Password",
                "No staff password is set. Set one now?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return False
            self.set_staff_password()
            cfg = auth.read_config()
            if not auth.has_password(cfg):
                return False
        password, ok = QInputDialog.getText(
            self, "Staff Access", "Enter staff password:", QLineEdit.Password)
        if not ok:
            return False
        return auth.verify_password(password, cfg)

    def set_staff_password(self):
        """Prompt for and store a new staff password (PBKDF2 hash + salt) in
        main.json."""
        password, ok = QInputDialog.getText(
            self, "Set Staff Password", "Enter new staff password:",
            QLineEdit.Password)
        if not ok or not password:
            return
        confirm, ok = QInputDialog.getText(
            self, "Set Staff Password", "Confirm new staff password:",
            QLineEdit.Password)
        if not ok or confirm != password:
            QMessageBox.warning(self, "Staff Password", "Passwords do not match.")
            return
        try:
            auth.write_config(auth.set_password(auth.read_config(), password))
        except Exception as e:
            self._on_error(f"Could not save config: {e}")
            return
        QMessageBox.information(self, "Staff Password", "Staff password updated.")

    def _proposal_selected(self):
        """True when a real proposal is chosen (not the empty placeholder)."""
        try:
            return bool(self._proposal_parts()[0])
        except Exception:
            return False

    def _update_begin_enabled(self):
        """Gate the Begin-scan button: User mode requires a selected proposal;
        Staff mode does not.  While scanning the button is Cancel and stays
        enabled.  The agent Send button shares the same gate."""
        allowed = self._expert or self._proposal_selected()
        # Agent console Send button follows the same Staff/proposal gate.
        agent_app = getattr(self, "_agent_app", None)
        if agent_app is not None and hasattr(agent_app, "set_gate_allowed"):
            agent_app.set_gate_allowed(allowed)
        btn = getattr(self, "begin_btn", None)
        if btn is None:
            return
        if self._scanning:
            btn.setEnabled(True)
            return
        btn.setEnabled(allowed)

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
        """The window owns the one animation timer and drives the panels from
        it, so no panel keeps a timer of its own."""
        self._t += 0.02
        self.detector_panel.pulse(self._t)
        # Only in placeholder mode; when connected, real monitor data drives the
        # trace via _on_monitor_data.
        if self.controller is None:
            self.detector_panel.scroll_placeholder_trace()

    # ── controller slots (read-only live data) ──────────────────────────
    def _on_motor_position(self, name, pos):
        self._motor_info.setdefault(name, {})["last value"] = pos
        wd = self._motor_widgets.get(name)
        if wd:
            wd["value"].setText(f"{pos:.2f}")
            wd["bar"].set_state(mi.frac(pos, wd["lo"], wd["hi"]), wd["bar"]._moving)
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
        wd["bar"].set_state(mi.frac(val, wd["lo"], wd["hi"]), moving)

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
        # …the ROI spectrum (mean signal in the Spectrum ROI vs energy)…
        self._update_roi_spectrum()
        # …and advances the per-image line counter (line_index just updated).
        if self._scanning:
            self._refresh_scan_progress()

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
        self.detector_panel.on_daq_value(value)

    def _on_monitor_data(self):
        self.detector_panel.on_monitor_data()

    def _on_progress_text(self, text):
        if hasattr(self, "progress_caption"):
            self.progress_caption.setText(text)
        # The same region/energy progress drives the image header subline (the
        # controller emits it as "Region X of N | Energy Y of M"; use the mock's
        # middot separator for the header).
        if text:
            self._set_image_header(subline=text.replace(" | ", " · "))

    def _on_scan_file(self, name):
        """The controller reports the current scan's data file name at scan start
        (and per loop iteration); reflect it in the image header title."""
        if name:
            self._set_image_header(filename=os.path.basename(name))
            self._log_activity(f"writing {os.path.basename(name)}")

    def _on_est_time(self, seconds):
        # The controller emits *remaining* time; total = elapsed + remaining.
        self._remaining_seconds = float(seconds)
        self._refresh_scan_progress()

    def _on_elapsed_time(self, seconds):
        self._elapsed_seconds = float(seconds)
        self._refresh_scan_progress()

    @staticmethod
    def _fmt_mmss(seconds):
        return stats.format_mmss(seconds)

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

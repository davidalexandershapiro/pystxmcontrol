"""
Motor Panel (dashboard style) — a floating utility window for inspecting and
jogging any motor, styled to match ``mainwindow_dashboard``.

Ports the feature set of ``motor_panel.MotorPanelWindow`` (motor selector,
move-to-position, jog, Live/History plots, read-only config) onto the dashboard's
bespoke dark theme (``dashboard_theme``): card frames, segmented pill controls,
mono/sans type tokens, and pyqtgraph plots on the dashboard plot ground.

Works both connected (full move/jog/history via ``MainController``) and in
placeholder mode (controller is ``None`` — the selector/config still populate
from the supplied ``motor_info`` dict, but the actions are disabled).
"""

import time
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QDialog, QWidget, QPushButton, QComboBox,
    QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPlainTextEdit, QDateEdit, QMessageBox, QApplication,
)
from PySide6.QtCore import Qt, QDate

import pyqtgraph as pg

from pystxmcontrol.gui.dashboard_theme import C, build_stylesheet, mono_font
from pystxmcontrol.gui import dashboard_widgets as dw

pg.setConfigOptions(antialias=True, background=C["plot_ground"])

_MAX_LIVE_HISTORY = 200   # maximum samples kept in the live rolling plot


class MotorPanelWindow(QDialog):
    """Non-modal, always-on-top motor inspection/control window in dashboard style.

    Parameters
    ----------
    controller : MainController or None
        When present, drives move/jog/history and live position updates.  When
        ``None`` (placeholder mode) the actions are disabled but the window still
        populates from ``motor_info``.
    motor_info : dict
        The ``{name: config}`` motor map (the dashboard's ``_motor_info``); used
        for the selector order, units, config display, and placeholder readback.
    """

    def __init__(self, controller=None, motor_info=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._motor_info = dict(motor_info or {})
        self.setWindowTitle("Motor Panel")
        self.setMinimumSize(560, 720)
        self.setStyleSheet(build_stylesheet())
        # Float above the main window without blocking it.
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        # Rolling history for the Live tab.
        self._live_times = []
        self._live_positions = []
        self._t0 = time.monotonic()

        self._build_ui()
        self._populate_motors()
        self._connect_signals()

    @staticmethod
    def _style_plot(pw):
        pw.setBackground(C["plot_ground"])
        pw.showGrid(x=True, y=True, alpha=0.18)
        pi = pw.getPlotItem()
        pi.showAxis("top")
        pi.showAxis("right")
        pi.getAxis("top").setStyle(showValues=False)
        pi.getAxis("right").setStyle(showValues=False)
        for ax in ("left", "bottom", "top", "right"):
            pi.getAxis(ax).setPen(C["border"])
            pi.getAxis(ax).setTextPen(C["text_faint"])
        return pw

    # ── UI construction ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Motor selector + readback ──────────────────────────────────────
        sel_card, sel_body = dw.card("Motor", padded=True)
        sel_row = QHBoxLayout()
        sel_row.setSpacing(10)
        self.motorCombo = QComboBox()
        self.motorCombo.setCursor(Qt.PointingHandCursor)
        sel_row.addWidget(self.motorCombo, 1)
        sel_row.addWidget(dw.label("POSITION", role="fieldLabel"))
        self.posReadback = dw.field(derived=True)
        self.posReadback.setFixedWidth(120)
        sel_row.addWidget(self.posReadback)
        self.posUnit = dw.label("", role="monoFaint")
        sel_row.addWidget(self.posUnit)
        sel_body.addLayout(sel_row)
        root.addWidget(sel_card)

        # ── Move / Jog controls ────────────────────────────────────────────
        ctl_card, ctl_body = dw.card("Control", padded=True)
        # Move-to-position row
        move_row = QHBoxLayout()
        move_row.setSpacing(8)
        move_row.addWidget(dw.label("MOVE TO", role="fieldLabel"))
        self.positionEdit = dw.field()
        self.positionEdit.setPlaceholderText("target")
        move_row.addWidget(self.positionEdit, 1)
        self.moveButton = QPushButton("Move")
        self.moveButton.setProperty("role", "jog")
        self.moveButton.setCursor(Qt.PointingHandCursor)
        self.moveButton.setFixedWidth(80)
        move_row.addWidget(self.moveButton)
        ctl_body.addLayout(move_row)
        # Jog row
        jog_row = QHBoxLayout()
        jog_row.setSpacing(8)
        jog_row.addWidget(dw.label("JOG STEP", role="fieldLabel"))
        self.stepEdit = dw.field("1.0")
        jog_row.addWidget(self.stepEdit, 1)
        self.minusButton = QPushButton("−")
        self.plusButton = QPushButton("+")
        for b in (self.minusButton, self.plusButton):
            b.setProperty("role", "jog")
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedWidth(38)
        jog_row.addWidget(self.minusButton)
        jog_row.addWidget(self.plusButton)
        ctl_body.addLayout(jog_row)
        root.addWidget(ctl_card)

        # ── Plots (Live / History) ─────────────────────────────────────────
        plot_card, plot_body = dw.card("Trace", padded=True)
        tab_well, _ = dw.segmented(["Live", "History"], 0)
        self._tab_grp = tab_well.group
        plot_card.header_layout.insertWidget(1, tab_well)
        plot_card.header_layout.insertSpacing(2, 10)

        self.plotStack = QStackedWidget()
        self.plotStack.addWidget(self._build_live_tab())
        self.plotStack.addWidget(self._build_history_tab())
        plot_body.addWidget(self.plotStack, 1)
        self._tab_grp.idClicked.connect(self.plotStack.setCurrentIndex)
        root.addWidget(plot_card, 1)

        # ── Read-only config ───────────────────────────────────────────────
        cfg_card, cfg_body = dw.card("Motor config", padded=True)
        self.configText = QPlainTextEdit()
        self.configText.setReadOnly(True)
        self.configText.setFixedHeight(150)
        self.configText.setFont(mono_font(10))
        self.configText.setStyleSheet(
            f"QPlainTextEdit{{background:{C['well']};border:1px solid "
            f"{C['border']};border-radius:4px;color:{C['text_2']};}}")
        cfg_body.addWidget(self.configText)
        root.addWidget(cfg_card)

    def _build_live_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.livePlot = self._style_plot(pg.PlotWidget())
        self.livePlot.setLabel("bottom", "Elapsed time", units="s")
        self.liveCurve = self.livePlot.plot(
            pen=pg.mkPen(C["accent"], width=2))
        v.addWidget(self.livePlot, 1)
        v.addLayout(self._zoom_controls(self.livePlot))
        return w

    def _build_history_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        date_row.addWidget(dw.label("DATE", role="fieldLabel"))
        self.datePicker = QDateEdit()
        self.datePicker.setDate(QDate.currentDate())
        self.datePicker.setCalendarPopup(True)
        self.datePicker.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.datePicker)
        self.loadHistButton = QPushButton("Load")
        self.loadHistButton.setProperty("role", "small")
        self.loadHistButton.setCursor(Qt.PointingHandCursor)
        date_row.addWidget(self.loadHistButton)
        date_row.addStretch(1)
        self.histStatus = dw.label("", role="monoFaint")
        date_row.addWidget(self.histStatus)
        v.addLayout(date_row)

        self.histPlot = self._style_plot(
            pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()}))
        self.histPlot.setLabel("bottom", "Time of day")
        self.histCurve = self.histPlot.plot(
            pen=pg.mkPen(C["motion"], width=1),
            symbol="o", symbolSize=4,
            symbolBrush=pg.mkBrush(255, 196, 94, 180), symbolPen=None)

        # Right-axis ViewBox for the motor offset series.
        self._offsetVB = pg.ViewBox()
        self.histPlot.scene().addItem(self._offsetVB)
        self._offsetAxis = pg.AxisItem("right")
        self._offsetAxis.setLabel("Offset", color=C["ok"])
        self._offsetAxis.setPen(C["border"])
        self._offsetAxis.setTextPen(C["text_faint"])
        self.histPlot.plotItem.layout.addItem(self._offsetAxis, 2, 3)
        self._offsetAxis.linkToView(self._offsetVB)
        self._offsetVB.setXLink(self.histPlot.plotItem)
        self._offsetCurve = pg.PlotDataItem(
            pen=pg.mkPen(C["ok"], width=1),
            symbol="t", symbolSize=5,
            symbolBrush=pg.mkBrush(142, 224, 106, 180), symbolPen=None)
        self._offsetVB.addItem(self._offsetCurve)
        self.histPlot.plotItem.vb.sigResized.connect(self._sync_offset_vb)
        self._offsetAxis.setVisible(False)

        v.addWidget(self.histPlot, 1)
        v.addLayout(self._zoom_controls(self.histPlot))
        return w

    def _sync_offset_vb(self):
        self._offsetVB.setGeometry(self.histPlot.plotItem.vb.sceneBoundingRect())

    def _zoom_controls(self, plot_widget):
        """A 'Zoom: XY / X / Y' segmented row controlling wheel-zoom axes."""
        vb = plot_widget.getViewBox()
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(dw.label("ZOOM", role="fieldLabel"))
        well, btns = dw.segmented(["XY", "X", "Y"], 0)
        grp = well.group
        modes = ((True, True), (True, False), (False, True))
        for i, b in enumerate(btns):
            b.clicked.connect(lambda _=False, m=modes[i]: vb.setMouseEnabled(*m))
        # Keep the group alive alongside the plot.
        plot_widget._zoom_btn_group = grp
        row.addWidget(well)
        row.addStretch(1)
        return row

    # ── population / wiring ─────────────────────────────────────────────────
    def _motors_sorted(self):
        return sorted(self._motor_info.items(),
                      key=lambda kv: kv[1].get("index", 999))

    def _populate_motors(self):
        names = [name for name, _ in self._motors_sorted()]
        # Fall back to the controller's display list if no motor_info was passed.
        if not names and self.controller is not None:
            names = self.controller.get_available_motors()
        self.motorCombo.blockSignals(True)
        self.motorCombo.clear()
        self.motorCombo.addItems(names)
        self.motorCombo.blockSignals(False)
        if names:
            self._on_motor_changed(names[0])

    def _connect_signals(self):
        self.motorCombo.currentTextChanged.connect(self._on_motor_changed)
        self.moveButton.clicked.connect(self._on_move)
        self.positionEdit.returnPressed.connect(self._on_move)
        self.plusButton.clicked.connect(lambda: self._jog(+1))
        self.minusButton.clicked.connect(lambda: self._jog(-1))
        self.stepEdit.returnPressed.connect(lambda: self._jog(+1))
        self.loadHistButton.clicked.connect(self._load_history)
        if self.controller is not None:
            self.controller.motor_position_updated.connect(self._on_position_update)
        else:
            # Placeholder mode: the actions have no server to talk to.
            for wdg in (self.moveButton, self.positionEdit, self.stepEdit,
                        self.plusButton, self.minusButton,
                        self.loadHistButton, self.datePicker):
                wdg.setEnabled(False)

    def _unit(self, motor_name):
        return self._motor_info.get(motor_name, {}).get("unit", "") or ""

    def _position_of(self, motor_name):
        """Current position: from the live motor model when connected, else the
        config's last recorded value in placeholder mode."""
        if self.controller is not None:
            pos = self.controller.get_motor_model().get_position(motor_name)
            if isinstance(pos, (int, float)):
                return float(pos)
        val = self._motor_info.get(motor_name, {}).get("last value")
        return float(val) if isinstance(val, (int, float)) else None

    # ── slots ───────────────────────────────────────────────────────────────
    def _on_motor_changed(self, motor_name):
        if not motor_name:
            return
        self._live_times.clear()
        self._live_positions.clear()
        self._t0 = time.monotonic()
        self.liveCurve.setData([], [])
        unit = self._unit(motor_name)
        left = f"{motor_name} ({unit})" if unit else motor_name
        self.livePlot.setLabel("left", left)
        self.histPlot.setLabel("left", left)
        self.histCurve.setData([], [])
        self._offsetCurve.setData([], [])
        self._offsetAxis.setLabel(f"{motor_name} offset", color=C["ok"])
        self.histStatus.setText("")
        self.posUnit.setText(unit)

        pos = self._position_of(motor_name)
        if pos is not None:
            self.posReadback.setText(f"{pos:.4g}")
            self.positionEdit.setText(f"{pos:.4g}")
        else:
            self.posReadback.clear()

        # Prefill the jog step from the motor's last step if it looks usable.
        step = self._motor_info.get(motor_name, {}).get("last step:")
        if isinstance(step, (int, float)) and step > 0:
            self.stepEdit.setText(f"{step:g}")

        cfg = self._motor_info.get(motor_name, {})
        if not cfg and self.controller is not None:
            cfg = self.controller.get_motor_model().get(
                "motor_info", {}).get(motor_name, {})
        if cfg:
            self.configText.setPlainText(
                "\n".join(f"{k}: {v}" for k, v in sorted(cfg.items())))
        else:
            self.configText.setPlainText("(no config available)")

    def _on_position_update(self, motor_name, position):
        if motor_name != self.motorCombo.currentText():
            return
        self.posReadback.setText(f"{position:.4g}")
        t = time.monotonic() - self._t0
        self._live_times.append(t)
        self._live_positions.append(position)
        if len(self._live_times) > _MAX_LIVE_HISTORY:
            self._live_times.pop(0)
            self._live_positions.pop(0)
        self.liveCurve.setData(self._live_times, self._live_positions)

    def _load_history(self):
        if self.controller is None:
            return
        motor_name = self.motorCombo.currentText()
        if not motor_name:
            return
        qdate = self.datePicker.date()
        day_start = datetime(qdate.year(), qdate.month(), qdate.day())
        start_ts = day_start.timestamp()
        end_ts = (day_start + timedelta(days=1)).timestamp()
        self.histStatus.setText("Loading…")
        QApplication.processEvents()

        records = self.controller.query_motor_history(motor_name, start_ts, end_ts)
        if not records:
            self.histStatus.setText(
                f"No data for {motor_name} on {qdate.toString('yyyy-MM-dd')}")
            self.histCurve.setData([], [])
            self._offsetCurve.setData([], [])
            self._offsetAxis.setVisible(False)
            return
        self.histCurve.setData([r["timestamp"] for r in records],
                               [r["actual_position"] for r in records])
        off_ts = [r["timestamp"] for r in records
                  if r.get("motor_offset") is not None]
        off_val = [r["motor_offset"] for r in records
                   if r.get("motor_offset") is not None]
        self._offsetCurve.setData(off_ts, off_val)
        self._offsetAxis.setVisible(bool(off_ts))
        self.histStatus.setText(
            f"{len(records)} records"
            + (f" · {len(off_ts)} offset" if off_ts else ""))

    def _on_move(self):
        if self.controller is None:
            return
        motor_name = self.motorCombo.currentText()
        try:
            position = float(self.positionEdit.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid input", "Position must be a number.")
            return
        self.controller.move_motor(motor_name, position)

    def _jog(self, direction):
        if self.controller is None:
            return
        motor_name = self.motorCombo.currentText()
        try:
            step = float(self.stepEdit.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid input", "Step size must be a number.")
            return
        self.controller.jog_motor(motor_name, step, direction)

    def closeEvent(self, event):
        if self.controller is not None:
            try:
                self.controller.motor_position_updated.disconnect(
                    self._on_position_update)
            except (RuntimeError, TypeError):
                pass
        super().closeEvent(event)

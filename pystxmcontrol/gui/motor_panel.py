"""
Motor Panel — floating utility window for inspecting and jogging any motor.

Features:
  • Motor selector combo box (all motors known to the controller)
  • Move-to-position controls
  • Jog (step) controls with +/- buttons
  • Tabbed plots:
      – Live   : rolling position vs. elapsed time (updated from motor_position_updated signal)
      – History: position vs. time-of-day for a chosen date, loaded from the server's
                 operation logger via the query_motor_history command
  • Read-only motor config display
"""

import time
from datetime import datetime, timedelta
from PySide6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg


_MAX_LIVE_HISTORY = 200   # maximum samples kept in the live rolling plot


class MotorPanelWindow(QtWidgets.QDialog):
    """
    Non-modal dialog that provides motor inspection and control.

    Pass the MainController instance so the panel can call move_motor /
    jog_motor, subscribe to motor_position_updated, and request historical
    data from the server.
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Motor Panel")
        self.setMinimumWidth(520)
        self.setMinimumHeight(700)
        # Stays on top of the main window but does not block it
        self.setWindowFlags(
            QtCore.Qt.Window |
            QtCore.Qt.WindowStaysOnTopHint
        )

        # Rolling history for the live tab
        self._live_times: list = []
        self._live_positions: list = []
        self._t0: float = time.monotonic()

        self._build_ui()
        self._populate_motors()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(10, 10, 10, 10)

        # ── Motor selector ──────────────────────────────────────────────
        sel_row = QtWidgets.QHBoxLayout()
        sel_row.addWidget(QtWidgets.QLabel("Motor:"))
        self.motorCombo = QtWidgets.QComboBox()
        sel_row.addWidget(self.motorCombo, stretch=1)
        sel_row.addWidget(QtWidgets.QLabel("Pos:"))
        self.posReadback = QtWidgets.QLineEdit()
        self.posReadback.setReadOnly(True)
        self.posReadback.setMaximumWidth(110)
        self.posReadback.setAlignment(QtCore.Qt.AlignRight)
        sel_row.addWidget(self.posReadback)
        root.addLayout(sel_row)

        # ── Move to position ────────────────────────────────────────────
        move_group = QtWidgets.QGroupBox("Move to Position")
        move_layout = QtWidgets.QHBoxLayout(move_group)
        move_layout.addWidget(QtWidgets.QLabel("Target:"))
        self.positionEdit = QtWidgets.QLineEdit()
        self.positionEdit.setPlaceholderText("enter position")
        move_layout.addWidget(self.positionEdit, stretch=1)
        self.moveButton = QtWidgets.QPushButton("Move")
        self.moveButton.setMinimumWidth(70)
        move_layout.addWidget(self.moveButton)
        root.addWidget(move_group)

        # ── Jog controls ────────────────────────────────────────────────
        jog_group = QtWidgets.QGroupBox("Jog")
        jog_layout = QtWidgets.QHBoxLayout(jog_group)
        jog_layout.addWidget(QtWidgets.QLabel("Step:"))
        self.stepEdit = QtWidgets.QLineEdit("1.0")
        self.stepEdit.setMaximumWidth(100)
        jog_layout.addWidget(self.stepEdit)
        jog_layout.addStretch()
        self.minusButton = QtWidgets.QPushButton("−")
        self.minusButton.setFixedWidth(50)
        self.minusButton.setFixedHeight(32)
        self.plusButton = QtWidgets.QPushButton("+")
        self.plusButton.setFixedWidth(50)
        self.plusButton.setFixedHeight(32)
        jog_layout.addWidget(self.minusButton)
        jog_layout.addWidget(self.plusButton)
        root.addWidget(jog_group)

        # ── Tabbed plots ────────────────────────────────────────────────
        self.plotTabs = QtWidgets.QTabWidget()
        self.plotTabs.setMinimumHeight(240)

        # Tab 1: Live rolling plot
        live_widget = QtWidgets.QWidget()
        live_layout = QtWidgets.QVBoxLayout(live_widget)
        live_layout.setContentsMargins(4, 4, 4, 4)
        self.livePlot = pg.PlotWidget()
        self.livePlot.setLabel("bottom", "Elapsed Time (s)")
        self.livePlot.showGrid(x=True, y=True, alpha=0.3)
        self.liveCurve = self.livePlot.plot(
            pen=pg.mkPen(color=(100, 200, 255), width=2)
        )
        live_layout.addWidget(self.livePlot)
        live_layout.addLayout(self._make_zoom_controls(self.livePlot))
        self.plotTabs.addTab(live_widget, "Live")

        # Tab 2: Historical plot
        hist_widget = QtWidgets.QWidget()
        hist_layout = QtWidgets.QVBoxLayout(hist_widget)
        hist_layout.setContentsMargins(4, 4, 4, 4)

        date_row = QtWidgets.QHBoxLayout()
        date_row.addWidget(QtWidgets.QLabel("Date:"))
        self.datePicker = QtWidgets.QDateEdit()
        self.datePicker.setDate(QtCore.QDate.currentDate())
        self.datePicker.setCalendarPopup(True)
        self.datePicker.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.datePicker)
        self.loadHistButton = QtWidgets.QPushButton("Load")
        self.loadHistButton.setMinimumWidth(60)
        date_row.addWidget(self.loadHistButton)
        date_row.addStretch()
        hist_layout.addLayout(date_row)

        self.histPlot = pg.PlotWidget(
            axisItems={"bottom": pg.DateAxisItem()}
        )
        self.histPlot.setLabel("bottom", "Time of Day")
        self.histPlot.showGrid(x=True, y=True, alpha=0.3)
        self.histCurve = self.histPlot.plot(
            pen=pg.mkPen(color=(255, 180, 80), width=1),
            symbol='o', symbolSize=4,
            symbolBrush=pg.mkBrush(255, 180, 80, 180),
            symbolPen=None,
        )

        # ── Right-axis ViewBox for motor offset ─────────────────────────
        self._offsetVB = pg.ViewBox()
        self.histPlot.scene().addItem(self._offsetVB)

        self._offsetAxis = pg.AxisItem("right")
        self._offsetAxis.setLabel("Offset", color="#80ff80")
        self.histPlot.plotItem.layout.addItem(self._offsetAxis, 2, 3)
        self._offsetAxis.linkToView(self._offsetVB)
        self._offsetVB.setXLink(self.histPlot.plotItem)

        self._offsetCurve = pg.PlotDataItem(
            pen=pg.mkPen(color=(128, 255, 128), width=1),
            symbol='t', symbolSize=5,
            symbolBrush=pg.mkBrush(128, 255, 128, 180),
            symbolPen=None,
        )
        self._offsetVB.addItem(self._offsetCurve)

        # Keep the offset ViewBox geometry in sync with the main plot
        self.histPlot.plotItem.vb.sigResized.connect(self._sync_offset_vb)

        hist_layout.addWidget(self.histPlot)
        hist_layout.addLayout(self._make_zoom_controls(self.histPlot))

        self.histStatus = QtWidgets.QLabel("")
        self.histStatus.setAlignment(QtCore.Qt.AlignCenter)
        hist_layout.addWidget(self.histStatus)

        self.plotTabs.addTab(hist_widget, "History")

        root.addWidget(self.plotTabs)

        # ── Motor config (read-only) ────────────────────────────────────
        cfg_group = QtWidgets.QGroupBox("Motor Config")
        cfg_layout = QtWidgets.QVBoxLayout(cfg_group)
        self.configText = QtWidgets.QPlainTextEdit()
        self.configText.setReadOnly(True)
        self.configText.setMaximumHeight(150)
        mono = QtGui.QFont("Monospace", 9)
        mono.setStyleHint(QtGui.QFont.TypeWriter)
        self.configText.setFont(mono)
        cfg_layout.addWidget(self.configText)
        root.addWidget(cfg_group)

    def _sync_offset_vb(self):
        """Keep the offset ViewBox geometry locked to the main plot ViewBox."""
        self._offsetVB.setGeometry(self.histPlot.plotItem.vb.sceneBoundingRect())

    @staticmethod
    def _make_zoom_controls(plot_widget: pg.PlotWidget) -> QtWidgets.QHBoxLayout:
        """
        Build a row of exclusive toggle buttons (XY / X / Y) that control
        which axes respond to scroll-wheel zoom for *plot_widget*.
        """
        vb = plot_widget.getViewBox()

        btn_xy = QtWidgets.QPushButton("XY")
        btn_x  = QtWidgets.QPushButton("X")
        btn_y  = QtWidgets.QPushButton("Y")

        for btn in (btn_xy, btn_x, btn_y):
            btn.setCheckable(True)
            btn.setFixedHeight(22)
            btn.setFixedWidth(36)

        btn_xy.setChecked(True)   # default: both axes

        group = QtWidgets.QButtonGroup()
        group.setExclusive(True)
        for btn in (btn_xy, btn_x, btn_y):
            group.addButton(btn)

        def set_zoom(x_on, y_on):
            vb.setMouseEnabled(x=x_on, y=y_on)

        btn_xy.clicked.connect(lambda: set_zoom(True,  True))
        btn_x.clicked.connect( lambda: set_zoom(True,  False))
        btn_y.clicked.connect( lambda: set_zoom(False, True))

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Zoom:"))
        row.addWidget(btn_xy)
        row.addWidget(btn_x)
        row.addWidget(btn_y)
        row.addStretch()

        # Keep the button group alive (it has no parent widget yet)
        plot_widget._zoom_btn_group = group

        return row

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _populate_motors(self):
        motors = self.controller.get_available_motors()
        self.motorCombo.blockSignals(True)
        self.motorCombo.clear()
        for m in motors:
            self.motorCombo.addItem(m)
        self.motorCombo.blockSignals(False)
        if motors:
            self._on_motor_changed(motors[0])

    def _connect_signals(self):
        self.motorCombo.currentTextChanged.connect(self._on_motor_changed)
        self.moveButton.clicked.connect(self._on_move)
        self.positionEdit.returnPressed.connect(self._on_move)
        self.plusButton.clicked.connect(self._on_jog_plus)
        self.minusButton.clicked.connect(self._on_jog_minus)
        self.loadHistButton.clicked.connect(self._load_history)
        self.controller.motor_position_updated.connect(self._on_position_update)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_motor_changed(self, motor_name: str):
        """Reset live history and refresh config/readback when the selected motor changes."""
        self._live_times.clear()
        self._live_positions.clear()
        self._t0 = time.monotonic()
        self.liveCurve.setData([], [])
        self.livePlot.setLabel("left", motor_name)
        self.histPlot.setLabel("left", motor_name)
        self.histCurve.setData([], [])
        self._offsetCurve.setData([], [])
        self._offsetAxis.setLabel(f"{motor_name} Offset", color="#80ff80")
        self.histStatus.setText("")

        motor_model = self.controller.get_motor_model()
        pos = motor_model.get_position(motor_name)
        if pos is not None:
            self.posReadback.setText(f"{pos:.4g}")
            self.positionEdit.setText(f"{pos:.4g}")
        else:
            self.posReadback.clear()

        motor_info = motor_model.get('motor_info', {})
        cfg = motor_info.get(motor_name, {})
        if cfg:
            lines = [f"{k}: {v}" for k, v in sorted(cfg.items())]
            self.configText.setPlainText("\n".join(lines))
        else:
            self.configText.setPlainText("(no config available)")

    def _on_position_update(self, motor_name: str, position: float):
        """Receive live position updates and append to the rolling plot."""
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
        """Query the server for historical motor positions and plot them."""
        motor_name = self.motorCombo.currentText()
        if not motor_name:
            return

        qdate = self.datePicker.date()
        day_start = datetime(qdate.year(), qdate.month(), qdate.day())
        start_ts = day_start.timestamp()
        end_ts = (day_start + timedelta(days=1)).timestamp()

        self.histStatus.setText("Loading…")
        QtWidgets.QApplication.processEvents()

        records = self.controller.query_motor_history(
            motor_name, start_ts, end_ts
        )

        if not records:
            self.histStatus.setText(
                f"No data for {motor_name} on {qdate.toString('yyyy-MM-dd')}"
            )
            self.histCurve.setData([], [])
            return

        timestamps = [r["timestamp"] for r in records]
        positions  = [r["actual_position"] for r in records]
        self.histCurve.setData(timestamps, positions)

        # Plot offsets on the right axis (skip records where offset is None)
        off_ts  = [r["timestamp"]    for r in records if r.get("motor_offset") is not None]
        off_val = [r["motor_offset"] for r in records if r.get("motor_offset") is not None]
        self._offsetCurve.setData(off_ts, off_val)
        self._offsetAxis.setVisible(bool(off_ts))

        self.histStatus.setText(
            f"{len(records)} records"
            + (f" · {len(off_ts)} offset readings" if off_ts else "")
        )

    def _on_move(self):
        motor_name = self.motorCombo.currentText()
        try:
            position = float(self.positionEdit.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid input",
                                          "Position must be a number.")
            return
        self.controller.move_motor(motor_name, position)

    def _on_jog_plus(self):
        self._jog(+1)

    def _on_jog_minus(self):
        self._jog(-1)

    def _jog(self, direction: int):
        motor_name = self.motorCombo.currentText()
        try:
            step = float(self.stepEdit.text())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid input",
                                          "Step size must be a number.")
            return
        self.controller.jog_motor(motor_name, step, direction)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        """Disconnect signals on close to avoid dangling connections."""
        try:
            self.controller.motor_position_updated.disconnect(self._on_position_update)
        except RuntimeError:
            pass
        super().closeEvent(event)

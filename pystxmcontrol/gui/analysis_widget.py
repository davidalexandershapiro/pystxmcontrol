from PySide6 import QtWidgets, QtCore, QtGui
import json
import os
import sys
import pyqtgraph as pg
import numpy as np
import qdarktheme

from pystxmcontrol.gui.analysis_widget_UI import Ui_Analysis2Widget
from pystxmcontrol.utils.script_recorder import ScriptRecorder, records


class Analysis2Widget(QtWidgets.QWidget):
    """Standalone STXM stack analysis widget.

    Can be embedded as a tab (pass controller via connect_controller) or
    run as an independent application.
    """

    _BUTTON_STYLE_LIGHT = """
        QPushButton {
            border: 1px solid #a0a0a0;
            border-radius: 3px;
            background-color: #ebebeb;
            padding: 2px 8px;
        }
        QPushButton:hover {
            border-color: #707070;
            background-color: #dcdcdc;
        }
        QPushButton:pressed {
            background-color: #c8c8c8;
        }
        QPushButton:disabled {
            border-color: #c8c8c8;
            color: #a0a0a0;
        }
    """
    _BUTTON_STYLE_DARK = """
        QPushButton {
            border: 1px solid #606060;
            border-radius: 3px;
            background-color: #3a3a3a;
            padding: 2px 8px;
        }
        QPushButton:hover {
            border-color: #909090;
            background-color: #484848;
        }
        QPushButton:pressed {
            background-color: #2a2a2a;
        }
        QPushButton:disabled {
            border-color: #404040;
            color: #606060;
        }
    """

    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.ui = Ui_Analysis2Widget()
        self.ui.setupUi(self)
        self._setup_connections()
        self._setup_scale_bar()
        self._initialize_analysis2()
        if controller is not None:
            self.connect_controller(controller)
        # Apply theme last so plots are already initialised.
        # When embedded in a parent window the parent's stylesheet cascades
        # automatically; only apply the full qdarktheme sheet when standalone.
        dark = self._load_gui_theme() == 'dark'
        if parent is None:
            if dark:
                self.set_dark_theme()
            else:
                self.set_light_theme()
        else:
            # Just update plot colours to match the parent's theme
            self._apply_a2_spectrum_theme(light=not dark)

    def connect_controller(self, controller):
        """Wire controller signals — call after __init__ when embedding in main window."""
        controller.live_data_ready.connect(self.ui.a2_stack_viewer.recv_live_data)

    def load_file(self, filepath: str):
        """Load a .stxm file directly — called by the browser when a file is selected."""
        self.ui.a2_stack_viewer.receiveStack(filepath)

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _load_gui_theme(self):
        try:
            cfg_path = os.path.join(sys.prefix, 'pystxmcontrol_cfg/main.json')
            with open(cfg_path) as f:
                cfg = json.load(f)
            return cfg.get("gui", {}).get("theme", "light")
        except Exception:
            return "light"

    def set_light_theme(self):
        if self.parent() is None:
            self.setStyleSheet(qdarktheme.load_stylesheet("light") + self._BUTTON_STYLE_LIGHT)
        self._apply_a2_spectrum_theme(light=True)

    def set_dark_theme(self):
        if self.parent() is None:
            self.setStyleSheet(qdarktheme.load_stylesheet() + self._BUTTON_STYLE_DARK)
        self._apply_a2_spectrum_theme(light=False)

    def _apply_a2_spectrum_theme(self, light: bool):
        plot = self.ui.a2_spectrumPlot
        pi = plot.getPlotItem()
        bg  = 'w'           if light else 'k'
        pen = pg.mkPen('k') if light else pg.mkPen('w')
        plot.setBackground(bg)
        for axis in ('left', 'bottom', 'top', 'right'):
            pi.getAxis(axis).setPen(pen)
            pi.getAxis(axis).setTextPen(pen)
        if hasattr(self, '_a2_spec_curve'):
            self._a2_spec_curve.setPen(pen)

    def _setup_scale_bar(self):
        self._a2_scale_bar = pg.ScaleBar(
            size=100,
            width=6,
            brush=pg.mkBrush(255, 255, 255, 220),
            pen=pg.mkPen(color=(0, 0, 0, 160), width=1),
            offset=(-15, -15),
        )
        self._a2_scale_bar.text.setText('')
        self._a2_scale_bar.setParentItem(self.ui.a2_imageView.getView())
        self._a2_scale_bar.hide()

    def _setup_connections(self):
        ui = self.ui
        ui.a2_openStackButton.clicked.connect(ui.a2_stack_viewer.getFileName)
        ui.a2_regionCombo.currentIndexChanged.connect(self._on_a2_region_changed)
        ui.a2_saveDataButton.clicked.connect(self._on_a2_save_data)
        ui.a2_addToLogButton.clicked.connect(self._on_a2_add_to_log)
        ui.a2_savePngButton.clicked.connect(self._on_a2_save_png)
        ui.a2_recordButton.clicked.connect(self._on_a2_record_toggle)
        ui.a2_exportScriptButton.clicked.connect(self._on_a2_export_script)
        ui.a2_autoProcessButton.clicked.connect(self._on_a2_auto_process)
        ui.a2_mapButton.clicked.connect(self._on_a2_map)
        ui.a2_resetButton.clicked.connect(self._on_a2_reset)
        ui.a2_drawRoiCheckbox.stateChanged.connect(self._on_a2_draw_roi_toggled)
        ui.a2_deleteRoiButton.clicked.connect(self._on_a2_delete_roi)
        ui.a2_deleteFrameButton.clicked.connect(self._on_a2_delete_frame)
        ui.a2_cropButton.clicked.connect(self._on_a2_crop)
        ui.a2_roiTypeCombo.currentIndexChanged.connect(self._on_a2_roi_type_changed)
        ui.a2_odCheckbox.stateChanged.connect(self._on_a2_od_toggled)
        ui.a2_trackMouseCheckbox.stateChanged.connect(
            lambda state: self._a2_spec_curve.setData([], []) if not state else None
        )
        ui.a2_liveDisplayCheckbox.stateChanged.connect(
            lambda state: ui.a2_stack_viewer.ui.live_display.setChecked(bool(state))
        )
        ui.a2_preEdgeCheckbox.stateChanged.connect(self._on_a2_pre_edge_checkbox)
        ui.a2_subtractPreEdgeButton.clicked.connect(self._on_a2_subtract_pre_edge)
        ui.a2_detrendButton.clicked.connect(self._on_a2_detrend)
        ui.a2_selectI0FromHistogramCheckbox.stateChanged.connect(
            self._on_a2_select_i0_from_histogram)

        ui.a2_calcPCAButton.clicked.connect(self._on_a2_calc_pca)
        ui.a2_clusterImageCombo.currentTextChanged.connect(self._on_a2_cluster_image_changed)
        ui.a2_clusterPlotCombo.currentTextChanged.connect(self._on_a2_cluster_plot_changed)
        ui.a2_calcRGBMapButton.clicked.connect(self._on_a2_calc_rgb_map)
        ui.a2_calcNMFButton.clicked.connect(self._on_a2_calc_nmf)
        ui.a2_nmfDisplayCombo.currentTextChanged.connect(self._on_a2_nmf_display_changed)
        ui.a2_nmfPlotCombo.currentTextChanged.connect(self._on_a2_nmf_plot_changed)
        ui.a2_nmfCalcRGBMapButton.clicked.connect(self._on_a2_nmf_calc_rgb_map)
        ui.a2_workflowTabs.currentChanged.connect(self._on_a2_workflow_tab_changed)

        ui.a2_regStartButton.clicked.connect(self._on_a2_reg_start)
        ui.a2_regUndoButton.clicked.connect(self._on_a2_reg_undo)
        ui.a2_stack_viewer.progress_updated.connect(ui.a2_regProgressBar.setValue)

        ui.a2_subtractDarkButton.clicked.connect(self._on_a2_subtract_dark)
        ui.a2_filterUndoButton.clicked.connect(self._on_a2_filter_undo)
        ui.a2_medianFilterButton.clicked.connect(self._on_a2_median_filter)
        ui.a2_despikeButton.clicked.connect(self._on_a2_despike)

        ui.a2_stack_viewer.stack_loaded.connect(self._on_a2_stack_loaded)
        ui.a2_stack_viewer.auto_process_done.connect(self._on_a2_auto_process_done)
        ui.a2_stack_viewer.progress_updated.connect(ui.a2_progressBar.setValue)
        ui.a2_imageView.scene.sigMouseMoved.connect(self._on_a2_mouse_moved)
        ui.a2_imageView.sigTimeChanged.connect(self._on_a2_frame_changed)
        ui.a2_spectrumPlot.scene().sigMouseMoved.connect(self._on_a2_spectrum_mouse_moved)

    def _initialize_analysis2(self):
        """Configure the Analysis2 tab spectrum plot."""
        pi = self.ui.a2_spectrumPlot.getPlotItem()

        # Show all four axes as a bounding frame
        pi.showAxis('top')
        pi.showAxis('right')
        pi.showAxis('left')
        pi.showAxis('bottom')
        pi.getAxis('top').setStyle(showValues=False)
        pi.getAxis('right').setStyle(showValues=False)
        pi.getAxis('top').setHeight(10)
        pi.getAxis('right').setWidth(10)

        # Major-tick grid on both axes
        pi.showGrid(x=True, y=True, alpha=0.25)

        # Axis labels
        pi.setLabel('bottom', 'Energy', units='eV')
        pi.setLabel('left', 'Counts')

        # Persistent curve for hover spectrum (created once, updated in place)
        self._a2_spec_curve = pi.plot([], [], pen=pg.mkPen('k', width=1))

        # ROI state
        self._a2_rois = []               # list of {roi, type, color, curve}
        self._a2_spectrum_color_idx = 0  # cycles through non-blue colors
        self._a2_drawing = False
        self._a2_draw_points = []        # freehand path collected during drag
        self._a2_rubber_band = None      # live PlotCurveItem shown while drawing
        self._a2_pending_color = None
        self._a2_pending_roi = None      # kept for toggle-cleanup only
        self._a2_cluster_curves = []     # PlotDataItems for cluster/eigenvalue plot
        self._a2_pre_edge_region = None  # pg.LinearRegionItem for pre-edge selection
        self._a2_cursor_text = ""        # live cursor readout shown above energy line
        self._a2_histogram_mode = False      # True when histogram I0 selection is active
        self._a2_i0_hist_region = None       # pg.LinearRegionItem on spectrum plot
        self._a2_hist_curve = None           # step-mode PlotDataItem for histogram
        self._a2_i0_mask_overlay = None      # pg.ImageItem blue mask on imageView
        self._a2_i0_hist_spectrum = None     # (n_e,) I0 spectrum from histogram mask
        self._a2_i0_mask = None              # (ny, nx) bool mask from histogram I0 selection
        self._a2_crop_roi = None             # pg.RectROI used for the Crop tool
        self._recorder = ScriptRecorder()
        self._initialize_ls_tab()

    # ── Single source of truth for OD frames ─────────────────────────────────

    @property
    def _a2_od_frames(self):
        """Delegates directly to sv.stack.odFrames — one array, no copies."""
        sv = self.ui.a2_stack_viewer
        return sv.stack.odFrames if sv.haveStack else None

    @_a2_od_frames.setter
    def _a2_od_frames(self, value):
        sv = self.ui.a2_stack_viewer
        if sv.haveStack:
            sv.stack.odFrames = value

    def _on_a2_stack_loaded(self):
        """Display the full stack in a2_imageView when a stack is loaded."""
        if not hasattr(self.ui, 'a2_imageView'):
            return
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        frames = sv.stack.processedFrames  # (n_e, ny, nx)
        # Reset histogram I0 mode for the new stack
        if self._a2_histogram_mode:
            self._a2_exit_histogram_mode()
            if hasattr(self.ui, 'a2_selectI0FromHistogramCheckbox'):
                self.ui.a2_selectI0FromHistogramCheckbox.blockSignals(True)
                self.ui.a2_selectI0FromHistogramCheckbox.setChecked(False)
                self.ui.a2_selectI0FromHistogramCheckbox.blockSignals(False)
        # Sync OD checkbox with sv.stack.odFrames — do NOT clear sv.stack.odFrames here,
        # because stack_loaded is also emitted after operations that just computed OD
        # (e.g. autoProcess).  For a fresh file load sv.stack.odFrames is already None
        # (reset() sets it to None), so the checkbox will be disabled correctly.
        has_od = sv.stack.odFrames is not None
        self._a2_i0_mask = None
        self._a2_update_mask_checkbox_state()
        if hasattr(self.ui, 'a2_odCheckbox'):
            self.ui.a2_odCheckbox.blockSignals(True)
            self.ui.a2_odCheckbox.setEnabled(has_od)
            if not has_od:
                self.ui.a2_odCheckbox.setChecked(False)
            self.ui.a2_odCheckbox.blockSignals(False)
        # Reset clustering/decomposition combos only when results no longer exist.
        # stack_loaded fires both on new file load AND after operations (applyPCA, align,
        # etc.).  For a new load the stack's arrays are None; for a post-op signal they
        # may still be valid and should not be cleared from the UI.
        stack = sv.stack
        has_pca = getattr(stack, 'pcaImages', None) is not None
        has_nmf = getattr(stack, 'nmfMaps', None) is not None
        if hasattr(self.ui, 'a2_clusterImageCombo'):
            if not has_pca:
                self.ui.a2_clusterImageCombo.setEnabled(False)
                self.ui.a2_clusterImageCombo.setCurrentIndex(0)
        if hasattr(self.ui, 'a2_clusterPlotCombo'):
            if not has_pca:
                self.ui.a2_clusterPlotCombo.setEnabled(False)
                self.ui.a2_clusterPlotCombo.setCurrentIndex(0)
        if hasattr(self.ui, 'a2_nmfDisplayCombo'):
            if not has_nmf:
                self.ui.a2_nmfDisplayCombo.setEnabled(False)
                self.ui.a2_nmfDisplayCombo.setCurrentIndex(0)
        if hasattr(self.ui, 'a2_nmfPlotCombo'):
            if not has_nmf:
                self.ui.a2_nmfPlotCombo.setEnabled(False)
                self.ui.a2_nmfPlotCombo.setCurrentIndex(0)
        if hasattr(self.ui, 'a2_nmfProgressBar'):
            if not has_nmf:
                self.ui.a2_nmfProgressBar.setValue(0)
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        for curve in self._a2_cluster_curves:
            pi.removeItem(curve)
        self._a2_cluster_curves.clear()
        if pi.legend is not None:
            pi.legend.scene().removeItem(pi.legend)
            pi.legend = None
        self._a2_clear_all_rois()   # also calls _a2_update_map_button_state via _a2_update_od_checkbox_state
        self._a2_remove_crop_roi()
        self.ui.a2_drawRoiCheckbox.blockSignals(True)
        self.ui.a2_drawRoiCheckbox.setChecked(False)
        self.ui.a2_drawRoiCheckbox.blockSignals(False)
        combo = self.ui.a2_regionCombo
        combo.blockSignals(True)
        combo.clear()
        n = getattr(sv, 'nRegion', 1) or 1
        for i in range(n):
            combo.addItem(f"Region {i + 1}")
        # Use regionSelect.currentIndex() rather than sv.iRegion: when stack_loaded is
        # emitted from inside reset() (called by changeRegion()), sv.iRegion is still the
        # old value but regionSelect is already at the new index.
        combo.setCurrentIndex(sv.ui.regionSelect.currentIndex())
        combo.setEnabled(n > 1)
        combo.blockSignals(False)
        self.ui.a2_imageView.setImage(np.ascontiguousarray(frames.transpose(0, 2, 1)))  # → (n_e, nx, ny) for pg slider
        # Seek to the energy index that the stack viewer already has (e.g. from live data)
        energy_idx = sv.ui.verticalSlider.value()
        if energy_idx > 0:
            self.ui.a2_imageView.setCurrentIndex(energy_idx)
        self._update_a2_info_panel(energy_idx)
        self._update_a2_scale_bar()
        self._on_a2_roi_changed()
        if hasattr(self.ui, 'a2_selectI0FromHistogramCheckbox'):
            self.ui.a2_selectI0FromHistogramCheckbox.setEnabled(True)

    def _update_a2_info_panel(self, index=0):
        """Populate a2_metadataText with file metadata and the current energy line."""
        if not hasattr(self.ui, 'a2_metadataText'):
            return
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return

        energies = sv.stack.energies
        n = len(energies)
        idx = max(0, min(int(index), n - 1))
        energy_line = f"Energy {idx + 1} of {n}: {energies[idx]:.2f} eV"

        # Build file/scan metadata block
        lines = [self._a2_cursor_text, energy_line, "\u2500" * 44]
        nx = getattr(sv.stack, 'nx', None)
        meta = getattr(nx, 'meta', {}) if nx is not None else {}

        def m(key):
            return meta.get(key, '')

        if sv.stack_file:
            lines.append(f"File:          {os.path.basename(sv.stack_file)}")
        if m('scan_type'):
            lines.append(f"Scan type:     {m('scan_type')}")
        if m('start_time'):
            lines.append(f"Start time:    {m('start_time')}")
        if m('end_time'):
            lines.append(f"End time:      {m('end_time')}")
        if m('experimenters'):
            lines.append(f"Experimenters: {m('experimenters')}")
        if m('sample_description'):
            lines.append(f"Sample:        {m('sample_description')}")
        if m('proposal'):
            lines.append(f"Proposal:      {m('proposal')}")

        if nx is not None:
            try:
                iReg = sv.iRegion
                ne, ny_pts, nx_pts = nx.interp_counts["default"][iReg].shape
                dx = nx.xstepsize[iReg]
                dy = nx.ystepsize[iReg]
                lines.append(f"X range:       {nx_pts * dx:.3f} \u00b5m  ({nx_pts} pts, {dx:.4f} \u00b5m/pt)")
                lines.append(f"Y range:       {ny_pts * dy:.3f} \u00b5m  ({ny_pts} pts, {dy:.4f} \u00b5m/pt)")
            except Exception:
                pass
            try:
                if n:
                    lines.append(f"Energies:      {n}  ({energies[0]:.2f} \u2013 {energies[-1]:.2f} eV)")
            except Exception:
                pass
            try:
                dwells = nx.dwells
                if dwells is not None and len(dwells):
                    lines.append(f"Dwell:         {dwells[0]:.1f} ms")
            except Exception:
                pass
            if m('x_motor'):
                lines.append(f"X motor:       {m('x_motor')}")
            if m('y_motor'):
                lines.append(f"Y motor:       {m('y_motor')}")

        self.ui.a2_metadataText.setPlainText("\n".join(lines))

    def _on_a2_frame_changed(self, index, time):
        """Called when the a2_imageView slider moves to a new frame."""
        self._update_a2_info_panel(index)

    def _on_a2_spectrum_mouse_moved(self, pos):
        """Hover on spectrum plot → seek imageView to the nearest energy frame."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        if not pi.sceneBoundingRect().contains(pos):
            return
        mouse_energy = pi.vb.mapSceneToView(pos).x()
        energies = np.asarray(sv.stack.energies)
        idx = int(np.argmin(np.abs(energies - mouse_energy)))
        try:
            self.ui.a2_imageView.setCurrentIndex(idx)
        except AttributeError:
            pass  # tVals not set when a 2D image (diff/RGB) is displayed
        self._update_a2_info_panel(idx)

    def _on_a2_mouse_moved(self, pos):
        """Update a2_spectrumPlot with the spectrum at the mouse pixel position."""
        if not hasattr(self.ui, 'a2_imageView'):
            return
        if hasattr(self.ui, 'a2_trackMouseCheckbox') and not self.ui.a2_trackMouseCheckbox.isChecked():
            return
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        frames = self._a2_get_display_frames()  # raw or OD depending on checkbox
        energies = sv.stack.energies

        img_item = self.ui.a2_imageView.getImageItem()
        scene_pos = img_item.mapFromScene(pos)
        col = int(scene_pos.x())
        row = int(scene_pos.y())
        n_e, ny, nx = frames.shape
        if 0 <= col < nx and 0 <= row < ny:
            spectrum = frames[:, row, col]
            self._a2_spec_curve.setData(energies, spectrum)

        _cursor_tabs = {
            getattr(self.ui, 'a2_tab_main', None),
            getattr(self.ui, 'a2_tab_filtering', None),
            getattr(self.ui, 'a2_tab_registration', None),
        }
        if (hasattr(self.ui, 'a2_workflowTabs')
                and self.ui.a2_workflowTabs.currentWidget() in _cursor_tabs
                and 0 <= col < nx and 0 <= row < ny):
            frame_idx = max(0, min(self.ui.a2_imageView.currentIndex, n_e - 1))
            val = frames[frame_idx, row, col]
            self._a2_cursor_text = f"x={col:4d}  y={row:4d}  val={val:.4f}"
            self._update_cursor_metadata_line()

    def _update_cursor_metadata_line(self):
        """Replace the first line of a2_metadataText with the current cursor readout."""
        if not hasattr(self.ui, 'a2_metadataText'):
            return
        cursor = self.ui.a2_metadataText.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfLine,
                            QtGui.QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(self._a2_cursor_text)

    def _update_a2_scale_bar(self):
        """Resize the scale bar to a nice round µm length based on the loaded stack."""
        if self._a2_scale_bar is None:
            return
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            self._a2_scale_bar.hide()
            return
        dx = getattr(sv.stack, 'xpixelsize', None)
        if not dx:
            self._a2_scale_bar.hide()
            return
        _, _, nx_pts = sv.stack.processedFrames.shape
        nice_um = self._a2_nice_scale_um(nx_pts * dx)
        self._a2_scale_bar.size = nice_um / dx
        label = (f"{nice_um * 1000:.4g} nm" if nice_um < 1
                 else f"{nice_um:.4g} µm")
        self._a2_scale_bar.text.setText(label)
        self._a2_scale_bar.updateBar()
        self._a2_scale_bar.show()

    @staticmethod
    def _a2_nice_scale_um(total_um):
        """Return a round µm value suitable for a scale bar (~20% of image width)."""
        target = total_um * 0.2
        nice = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
        return min(nice, key=lambda v: abs(v - target))

    # ── Analysis2 ROI drawing ─────────────────────────────────────────────────

    _A2_I0_COLOR = (30, 100, 255)          # blue – reserved for I0
    _A2_SPECTRUM_COLORS = [                 # cycles for Spectrum ROIs
        (220,  50,  50),   # red
        ( 50, 180,  50),   # green
        (220, 120,   0),   # orange
        (180,  50, 180),   # purple
        (  0, 180, 180),   # cyan
        (200, 200,   0),   # yellow
    ]

    def _a2_next_spectrum_color(self):
        color = self._A2_SPECTRUM_COLORS[
            self._a2_spectrum_color_idx % len(self._A2_SPECTRUM_COLORS)
        ]
        self._a2_spectrum_color_idx += 1
        return color

    def _on_a2_draw_roi_toggled(self, state):
        roi_type = self.ui.a2_roiTypeCombo.currentText()
        viewport = self.ui.a2_imageView.ui.graphicsView.viewport()

        if roi_type == 'Crop':
            # Ensure the freehand event filter is never active in Crop mode
            viewport.removeEventFilter(self)
            self._a2_drawing = False
            self._a2_draw_points = []
            if self._a2_rubber_band is not None:
                self.ui.a2_imageView.removeItem(self._a2_rubber_band)
                self._a2_rubber_band = None
            if bool(state):
                self._a2_add_crop_roi()
            else:
                self._a2_remove_crop_roi()
            return

        if bool(state):
            self._a2_drawing = False
            self._a2_draw_points = []
            self._a2_rubber_band = None
            self._a2_pending_color = None
            viewport.installEventFilter(self)
        else:
            viewport.removeEventFilter(self)
            # Clean up any half-drawn rubber band
            if self._a2_rubber_band is not None:
                self.ui.a2_imageView.removeItem(self._a2_rubber_band)
                self._a2_rubber_band = None
            self._a2_drawing = False
            self._a2_draw_points = []

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent, Qt
        if not hasattr(self.ui, 'a2_imageView'):
            return super().eventFilter(obj, event)

        viewport = self.ui.a2_imageView.ui.graphicsView.viewport()
        if obj is not viewport:
            return super().eventFilter(obj, event)

        et = event.type()
        gv       = self.ui.a2_imageView.ui.graphicsView
        img_item = self.ui.a2_imageView.getImageItem()

        def to_img(qpoint):
            return img_item.mapFromScene(gv.mapToScene(qpoint))

        if et == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            pt = to_img(event.pos())
            self._a2_draw_points = [(pt.x(), pt.y())]
            roi_type = self.ui.a2_roiTypeCombo.currentText()
            self._a2_pending_color = (self._A2_I0_COLOR if roi_type == 'I0'
                                      else self._a2_next_spectrum_color())
            self._a2_drawing = True
            return True

        elif et == QEvent.Type.MouseMove and self._a2_drawing:
            pt = to_img(event.pos())
            self._a2_draw_points.append((pt.x(), pt.y()))
            xs = [p[0] for p in self._a2_draw_points]
            ys = [p[1] for p in self._a2_draw_points]
            if self._a2_rubber_band is None:
                self._a2_rubber_band = pg.PlotCurveItem(
                    xs, ys,
                    pen=pg.mkPen(self._a2_pending_color, width=2)
                )
                self.ui.a2_imageView.addItem(self._a2_rubber_band)
            else:
                self._a2_rubber_band.setData(xs, ys)
            return True

        elif et == QEvent.Type.MouseButtonRelease and self._a2_drawing:
            self._a2_drawing = False
            if self._a2_rubber_band is not None:
                self.ui.a2_imageView.removeItem(self._a2_rubber_band)
                self._a2_rubber_band = None
            points = self._a2_draw_points
            self._a2_draw_points = []
            if len(points) >= 3:
                self._finalize_a2_roi(points, self._a2_pending_color)
            return True

        return super().eventFilter(obj, event)

    def _finalize_a2_roi(self, points, color):
        """Create a permanent PolyLineROI from the freehand path and plot its spectrum."""
        roi_type = self.ui.a2_roiTypeCombo.currentText()

        # Enforce single I0 ROI
        if roi_type == 'I0':
            for entry in [e for e in self._a2_rois if e['type'] == 'I0']:
                self.ui.a2_imageView.removeItem(entry['roi'])
                self.ui.a2_spectrumPlot.getPlotItem().removeItem(entry['curve'])
                self._a2_rois.remove(entry)

        # Downsample to ~40 vertices so handles are manageable
        step = max(1, len(points) // 40)
        simplified = points[::step]

        roi = pg.PolyLineROI(simplified, closed=True,
                             pen=pg.mkPen(color, width=2))
        for handle in roi.getHandles():
            handle.hide()
        self.ui.a2_imageView.addItem(roi)

        curve = self.ui.a2_spectrumPlot.getPlotItem().plot(
            [], [], pen=pg.mkPen(color, width=1.5)
        )

        entry = {'roi': roi, 'type': roi_type, 'color': color, 'curve': curve}
        self._a2_rois.append(entry)
        roi.sigRegionChanged.connect(self._on_a2_roi_changed)
        self._a2_update_od_checkbox_state()
        self._on_a2_roi_changed()

    def _a2_clear_all_rois(self):
        """Remove every ROI from the image view and spectrum plot."""
        for entry in self._a2_rois:
            self.ui.a2_imageView.removeItem(entry['roi'])
            self.ui.a2_spectrumPlot.getPlotItem().removeItem(entry['curve'])
        self._a2_rois.clear()
        self._a2_update_od_checkbox_state()

    def _on_a2_delete_roi(self):
        """Remove the most recently added ROI (or the crop ROI) from the image."""
        if self._a2_crop_roi is not None:
            self._a2_remove_crop_roi()
            self.ui.a2_drawRoiCheckbox.blockSignals(True)
            self.ui.a2_drawRoiCheckbox.setChecked(False)
            self.ui.a2_drawRoiCheckbox.blockSignals(False)
            return
        if not self._a2_rois:
            return
        entry = self._a2_rois.pop()
        self.ui.a2_imageView.removeItem(entry['roi'])
        self.ui.a2_spectrumPlot.getPlotItem().removeItem(entry['curve'])
        self._a2_update_od_checkbox_state()
        self._on_a2_roi_changed()

    @records("delete_frame")
    def _on_a2_delete_frame(self):
        """Delete the currently displayed energy frame without a full stack reset."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        n_e = sv.stack.processedFrames.shape[0]
        if n_e <= 2:
            return
        idx = max(0, min(self.ui.a2_imageView.currentIndex, n_e - 1))
        energy = float(sv.stack.energies[idx])

        sv.stack.deleteFrameInPlace(energy)

        # Sync stack viewer slider
        new_n = sv.stack.processedFrames.shape[0]
        sv.ui.verticalSlider.setMaximum(new_n - 1)
        sv.ui.verticalSlider.setValue(min(sv.ui.verticalSlider.value(), new_n - 1))

        new_idx = min(idx, new_n - 1)
        self._a2_refresh_image_view()
        self.ui.a2_imageView.setCurrentIndex(new_idx)
        self._a2_update_roi_curves()
        return {"energy": energy}
        self._a2_update_od_checkbox_state()

    # ── Crop ROI ──────────────────────────────────────────────────────────────

    def _on_a2_roi_type_changed(self):
        """Sync event filter and crop ROI whenever the ROI type combo changes."""
        roi_type = self.ui.a2_roiTypeCombo.currentText()
        viewport = self.ui.a2_imageView.ui.graphicsView.viewport()
        is_checked = self.ui.a2_drawRoiCheckbox.isChecked()

        if roi_type == 'Crop':
            # Remove freehand event filter — it must not intercept RectROI mouse events
            viewport.removeEventFilter(self)
            self._a2_drawing = False
            self._a2_draw_points = []
            if self._a2_rubber_band is not None:
                self.ui.a2_imageView.removeItem(self._a2_rubber_band)
                self._a2_rubber_band = None
            # Add crop ROI if the checkbox was already checked
            if is_checked:
                self._a2_add_crop_roi()
        else:
            # Switching away from Crop — tear down the crop ROI
            if self._a2_crop_roi is not None:
                self._a2_remove_crop_roi()
                self.ui.a2_drawRoiCheckbox.blockSignals(True)
                self.ui.a2_drawRoiCheckbox.setChecked(False)
                self.ui.a2_drawRoiCheckbox.blockSignals(False)

    def _a2_add_crop_roi(self):
        """Place a resizable RectROI over the image for crop selection."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            self.ui.a2_drawRoiCheckbox.blockSignals(True)
            self.ui.a2_drawRoiCheckbox.setChecked(False)
            self.ui.a2_drawRoiCheckbox.blockSignals(False)
            return
        if self._a2_crop_roi is not None:
            return
        _, h, w = sv.stack.processedFrames.shape
        mx, my = w * 0.1, h * 0.1
        self._a2_crop_roi = pg.RectROI(
            [mx, my], [w * 0.8, h * 0.8],
            pen=pg.mkPen('y', width=2), handlePen=pg.mkPen('y', width=1)
        )
        self.ui.a2_imageView.addItem(self._a2_crop_roi)
        self._a2_update_crop_button_state()

    def _a2_remove_crop_roi(self):
        """Remove the crop RectROI from the image."""
        if self._a2_crop_roi is not None:
            self.ui.a2_imageView.removeItem(self._a2_crop_roi)
            self._a2_crop_roi = None
        self._a2_update_crop_button_state()

    def _a2_update_crop_button_state(self):
        self.ui.a2_cropButton.setEnabled(self._a2_crop_roi is not None)

    @records("crop_frames")
    def _on_a2_crop(self):
        """Crop all frames and OD data to the bounds of the Crop RectROI."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or self._a2_crop_roi is None:
            return
        frames = sv.stack.processedFrames  # (n_e, ny, nx)
        n_e, ny, nx = frames.shape
        img_item = self.ui.a2_imageView.getImageItem()
        try:
            # imageView shows frames transposed as (nx, ny); slices[0]=x/col, slices[1]=y/row
            slices, _ = self._a2_crop_roi.getArraySlice(frames[0].T, img_item)
            col_sl, row_sl = slices
        except Exception:
            return
        # Validate that the crop region is non-empty
        def _valid(sl, size):
            start = sl.start if sl.start is not None else 0
            stop  = sl.stop  if sl.stop  is not None else size
            return stop > start
        if not (_valid(col_sl, nx) and _valid(row_sl, ny)):
            return
        r0 = row_sl.start if row_sl.start is not None else 0
        r1 = row_sl.stop  if row_sl.stop  is not None else ny
        c0 = col_sl.start if col_sl.start is not None else 0
        c1 = col_sl.stop  if col_sl.stop  is not None else nx
        xstep = getattr(sv.stack, 'xpixelsize', 1.0)
        ystep = getattr(sv.stack, 'ypixelsize', 1.0)
        comment = (f"crop: x={c0*xstep:.2f}–{c1*xstep:.2f} µm, "
                   f"y={r0*ystep:.2f}–{r1*ystep:.2f} µm")
        sv.stack.cropFrames(row_sl, col_sl)
        # Clean up
        self._a2_remove_crop_roi()
        self.ui.a2_drawRoiCheckbox.blockSignals(True)
        self.ui.a2_drawRoiCheckbox.setChecked(False)
        self.ui.a2_drawRoiCheckbox.blockSignals(False)
        sv.stack_loaded.emit()
        return {"row_start": r0, "row_stop": r1, "col_start": c0, "col_stop": c1,
                "comment": comment}


    def _a2_update_mask_checkbox_state(self):
        """Enable Mask I0 Region checkboxes when a histogram mask exists."""
        has_mask = self._a2_i0_mask is not None
        for cb_name in ('a2_pcaMaskI0Checkbox', 'a2_nmfMaskI0Checkbox'):
            cb = getattr(self.ui, cb_name, None)
            if cb is not None:
                cb.setEnabled(has_mask)

    def _a2_update_od_checkbox_state(self):
        """Enable OD checkbox when an I0 ROI exists, histogram I0 is set, or stack-level OD is loaded."""
        if not hasattr(self.ui, 'a2_odCheckbox'):
            return
        has_i0 = (any(e['type'] == 'I0' for e in self._a2_rois)
                  or self._a2_i0_hist_spectrum is not None)
        # Keep enabled if stack.odFrames was loaded by autoProcess (_a2_od_frames populated)
        has_od = has_i0 or self._a2_od_frames is not None
        self.ui.a2_odCheckbox.setEnabled(has_od)
        if not has_od:
            self.ui.a2_odCheckbox.setChecked(False)  # triggers _on_a2_od_toggled → revert display
        self._a2_update_map_button_state()
        self._a2_update_norm_button_state()

    def _a2_update_norm_button_state(self):
        """Enable pre-edge controls and registration image-type combo when OD is available."""
        has_od = self._a2_od_frames is not None
        if hasattr(self.ui, 'a2_subtractPreEdgeButton'):
            self.ui.a2_preEdgeCheckbox.setEnabled(has_od)
            self.ui.a2_subtractPreEdgeButton.setEnabled(has_od)
        if hasattr(self.ui, 'a2_detrendButton'):
            self.ui.a2_detrendButton.setEnabled(has_od)
        if hasattr(self.ui, 'a2_regImageTypeCombo'):
            self.ui.a2_regImageTypeCombo.setEnabled(has_od)
            if not has_od:
                self.ui.a2_regImageTypeCombo.setCurrentIndex(0)

    def _a2_update_map_button_state(self):
        """Enable Map button based on energy count and Spectrum ROI count."""
        if not hasattr(self.ui, 'a2_mapButton'):
            return
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            self.ui.a2_mapButton.setEnabled(False)
            return
        n_energies = len(sv.stack.energies)
        if n_energies == 2:
            self.ui.a2_mapButton.setEnabled(True)
        else:
            n_spectrum_rois = sum(1 for e in self._a2_rois if e['type'] == 'Spectrum')
            self.ui.a2_mapButton.setEnabled(2 <= n_spectrum_rois <= 3)

    def _a2_get_display_frames(self):
        """Return OD frames when the OD checkbox is active, otherwise raw frames."""
        sv = self.ui.a2_stack_viewer
        if (hasattr(self.ui, 'a2_odCheckbox')
                and self.ui.a2_odCheckbox.isChecked()
                and self._a2_od_frames is not None):
            return self._a2_od_frames
        return sv.stack.processedFrames

    def _a2_compute_od(self):
        """Compute OD = -log(I / I0) using the mean spectrum of the I0 ROI.
        If no I0 ROI exists but stack.odFrames was set by Auto Process, use that."""
        sv = self.ui.a2_stack_viewer
        i0_entries = [e for e in self._a2_rois if e['type'] == 'I0']
        if not sv.haveStack:
            self._a2_od_frames = None
            return
        raw = sv.stack.processedFrames          # (n_e, ny, nx)

        if not i0_entries:
            if self._a2_i0_hist_spectrum is not None:
                i0 = self._a2_i0_hist_spectrum
            else:
                return
        else:
            try:
                i0 = self._a2_roi_mean_spectrum(i0_entries[0]['roi'], raw)  # (n_e,)
            except Exception:
                self._a2_od_frames = None
                return
            if i0 is None:
                self._a2_od_frames = None
                return

        try:
            sv.stack.computeODFromSpectrum(i0)
        except Exception:
            self._a2_od_frames = None

    def _on_a2_od_toggled(self, state):
        """Switch the image view and spectrum curves between raw and OD.
        Hide the I0 ROI and its curve while OD is active."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        od_on = bool(state)
        hist_bounds = None
        if od_on:
            if self._a2_histogram_mode:
                # Capture histogram bounds before _a2_exit_histogram_mode destroys the region
                hist_bounds = (self._a2_i0_hist_region.getRegion()
                               if self._a2_i0_hist_region is not None else None)
                # Compute OD while _a2_i0_hist_spectrum is still alive, THEN dismiss
                # histogram mode.  Dismissing first would clear the spectrum and make OD
                # unavailable, causing _a2_update_od_checkbox_state to disable the checkbox.
                self._a2_compute_od()
                if hasattr(self.ui, 'a2_selectI0FromHistogramCheckbox'):
                    cb = self.ui.a2_selectI0FromHistogramCheckbox
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
                self._a2_exit_histogram_mode()
                # _a2_od_frames is now set, so _a2_update_od_checkbox_state (called
                # inside _a2_exit_histogram_mode) will keep the OD checkbox enabled.
            else:
                self._a2_compute_od()
            # Switch ROI type combo to Spectrum so new ROIs are analysis ROIs
            if hasattr(self.ui, 'a2_roiTypeCombo'):
                idx = self.ui.a2_roiTypeCombo.findText('Spectrum')
                if idx >= 0:
                    self.ui.a2_roiTypeCombo.setCurrentIndex(idx)
        # Show/hide the I0 ROI and its spectrum curve
        for entry in self._a2_rois:
            if entry['type'] == 'I0':
                entry['roi'].setVisible(not od_on)
                entry['curve'].setVisible(not od_on)
        # Update y-axis label and disable SI prefix multiplier for OD (values 0–5)
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        if od_on:
            pi.setLabel('left', 'Optical Density')
            pi.getAxis('left').enableAutoSIPrefix(False)
        else:
            pi.setLabel('left', 'Counts')
            pi.getAxis('left').enableAutoSIPrefix(True)
        self._a2_refresh_image_view()
        self._on_a2_roi_changed()
        self._a2_update_norm_button_state()
        # Record only when turning OD on — turning it off is not a scripted action
        if od_on and sv.stack.I0 is not None:
            if hist_bounds is not None:
                self._recorder.record("compute_od_histogram",
                                      intensity_lo=float(hist_bounds[0]),
                                      intensity_hi=float(hist_bounds[1]))
            else:
                self._recorder.record("compute_od",
                                      i0_spectrum=list(np.asarray(sv.stack.I0.ravel(),
                                                                   dtype=float)))

    def _a2_refresh_image_view(self):
        """Push the current display frames (raw or OD) into a2_imageView."""
        frames = self._a2_get_display_frames()
        current_idx = self.ui.a2_imageView.currentIndex
        self.ui.a2_imageView.setImage(np.ascontiguousarray(frames.transpose(0, 2, 1)))
        self.ui.a2_imageView.setCurrentIndex(current_idx)

    def _a2_roi_mean_spectrum(self, roi, frames):
        """Return the mean spectrum (n_e,) over the ROI polygon via direct pixel masking.

        Vertices are taken from the ROI's free handles, mapped to integer image-pixel
        coordinates, and rasterised with skimage.draw.polygon.  This avoids the
        zoom-dependent interpolation that pg.PolyLineROI.getArrayRegion applies.
        """
        from skimage.draw import polygon as sk_polygon
        img_item = self.ui.a2_imageView.getImageItem()
        n_e, ny, nx = frames.shape

        xs, ys = [], []
        for h in roi.handles:
            if h['type'] == 'f':           # 'f' = free/vertex handle
                img_pos = img_item.mapFromScene(roi.mapToScene(h['pos']))
                xs.append(img_pos.x())
                ys.append(img_pos.y())

        if len(xs) < 3:
            return None

        rr, cc = sk_polygon(ys, xs, shape=(ny, nx))   # rr=row(ny), cc=col(nx)
        if rr.size == 0:
            return None

        return frames[:, rr, cc].mean(axis=1)          # (n_e,)

    def _a2_update_roi_curves(self):
        """Redraw spectrum curves for all ROIs from the current display frames.
        Does NOT recompute OD — use this after in-place OD modifications."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        frames   = self._a2_get_display_frames()
        energies = sv.stack.energies
        for entry in self._a2_rois:
            try:
                spectrum = self._a2_roi_mean_spectrum(entry['roi'], frames)
                if spectrum is not None:
                    entry['curve'].setData(energies, spectrum)
            except Exception:
                pass

    def _on_a2_roi_changed(self):
        """Recompute spectra for all ROIs using current display frames (raw or OD).
        If OD is active and the I0 ROI moved, recompute OD first."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return

        # If OD is on, I0 ROI movement requires recomputing OD first
        if (hasattr(self.ui, 'a2_odCheckbox')
                and self.ui.a2_odCheckbox.isChecked()):
            self._a2_compute_od()
            self._a2_refresh_image_view()

        self._a2_update_roi_curves()

    # ── Analysis2 Registration tab ────────────────────────────────────────────

    # Maps combobox display text → internal mode string used by alignFrames
    _A2_REG_MODE_MAP = {
        'Circular Image': 'manualtranslation',
        'Translation':    'translation',
        'Affine':         'affine',
        'Rigid':          'rigid',
        'Homographic':    'homographic',
    }

    def _on_a2_reg_start(self):
        display_mode = self.ui.a2_regModeCombo.currentText()
        mode = self._A2_REG_MODE_MAP.get(display_mode, 'manualtranslation')
        sobel = self.ui.a2_regSobelCheckbox.isChecked()
        autocrop = self.ui.a2_regAutocropCheckbox.isChecked()
        sv = self.ui.a2_stack_viewer

        use_od = (hasattr(self.ui, 'a2_regImageTypeCombo')
                  and self.ui.a2_regImageTypeCombo.currentText() == 'Optical Density'
                  and self._a2_od_frames is not None)

        # New options — only relevant for translation/manualtranslation modes
        use_custom = mode in ('translation', 'manualtranslation')
        align_method = 'sequential'
        if hasattr(self.ui, 'a2_regAlignMethodCombo'):
            align_method = ('reference'
                            if self.ui.a2_regAlignMethodCombo.currentText() == 'Reference Image'
                            else 'sequential')
        thresholded = (hasattr(self.ui, 'a2_regThresholdCheckbox')
                       and self.ui.a2_regThresholdCheckbox.isChecked())
        threshold = 0.0
        if thresholded and hasattr(self.ui, 'a2_regThresholdEdit'):
            try:
                threshold = float(self.ui.a2_regThresholdEdit.text())
            except ValueError:
                pass
        reference_idx = self.ui.a2_imageView.currentIndex if align_method == 'reference' else 0

        sv.progress_updated.emit(0)
        if use_od:
            sv.stack.alignODFrames(sobelFilter=sobel, mode=mode, autocrop=autocrop)
        elif use_custom:
            sv.stack.alignFramesCustom(
                mode=mode,
                align_method=align_method,
                reference_idx=reference_idx,
                thresholded=thresholded,
                threshold=threshold,
                sobelFilter=sobel,
                autocrop=autocrop,
                progress_callback=lambda pct: sv.progress_updated.emit(pct),
            )
            has_i0 = (any(e['type'] == 'I0' for e in self._a2_rois)
                      or self._a2_i0_hist_spectrum is not None)
            if has_i0:
                if self._a2_histogram_mode and self._a2_i0_hist_region is not None:
                    self._a2_update_i0_mask_overlay()
                else:
                    self._a2_compute_od()
        else:
            # Affine / Rigid / Homographic — use existing path (no new options apply)
            sv.stack.alignFrames(
                mode=mode, sobelFilter=sobel, autocrop=autocrop,
                progress_callback=lambda pct: sv.progress_updated.emit(pct),
            )
            has_i0 = (any(e['type'] == 'I0' for e in self._a2_rois)
                      or self._a2_i0_hist_spectrum is not None)
            if has_i0:
                self._a2_compute_od()

        sv.progress_updated.emit(100)
        self._update_a2_scale_bar()
        energy_idx = sv.ui.verticalSlider.value()
        self._update_a2_info_panel(energy_idx)
        self._a2_refresh_image_view()
        self._on_a2_roi_changed()
        if use_od:
            self._recorder.record("align_od_frames",
                                  mode=mode, sobel=sobel, autocrop=autocrop)
        elif use_custom:
            self._recorder.record("align_frames_custom",
                                  mode=mode, align_method=align_method,
                                  reference_idx=reference_idx, thresholded=thresholded,
                                  threshold=threshold, sobel=sobel, autocrop=autocrop)
        else:
            self._recorder.record("align_frames",
                                  mode=mode, sobel=sobel, autocrop=autocrop)

    def _on_a2_reg_undo(self):
        self.ui.a2_stack_viewer.undoFilter()

    # ── Analysis2 Filtering tab ───────────────────────────────────────────────

    def _on_a2_subtract_dark(self):
        """Subtract user-specified dark level from processedFrames; disable button until undo."""
        try:
            value = float(self.ui.a2_darkLevelEdit.text())
        except ValueError:
            return
        self.ui.a2_stack_viewer.subtractDarkLevel(value)
        self.ui.a2_subtractDarkButton.setEnabled(False)

    def _on_a2_filter_undo(self):
        """Undo last filter operation and re-enable the Subtract Dark button."""
        self.ui.a2_stack_viewer.undoFilter()
        if hasattr(self.ui, 'a2_subtractDarkButton'):
            self.ui.a2_subtractDarkButton.setEnabled(True)

    @records("median_filter")
    def _on_a2_median_filter(self):
        """Apply median filter with kernel size from text edit."""
        try:
            size = int(self.ui.a2_medianKernelEdit.text())
        except ValueError:
            return
        self.ui.a2_stack_viewer.applyMedianFilter(size)
        return {"size": size, "axis": 2}

    @records("despike")
    def _on_a2_despike(self):
        """Apply despike with kernel size and N sigma from text edits."""
        try:
            kernel_size = int(self.ui.a2_despikeKernelEdit.text())
            n_sigma = float(self.ui.a2_despikeNSigmaEdit.text())
        except ValueError:
            return
        self.ui.a2_stack_viewer.applyDespike(kernel_size, n_sigma)
        return {"kernel_size": kernel_size, "n_sigma": n_sigma}

    # ── Analysis2 Map button ─────────────────────────────────────────────────

    def _on_a2_region_changed(self, index: int):
        """Switch the active scan region and sync a2_imageView with the new data.

        changeRegion() calls reset() first, and reset() emits stack_loaded before the new
        region's data is loaded.  We block sv's own signals so that premature emission
        doesn't update a2_imageView with stale data.  sv.blockSignals() only affects sv
        itself — sv.ui.regionSelect.currentIndexChanged still fires, so changeRegion()
        runs fully.  Once it returns, sv.stack has the correct region data and we sync
        manually.
        """
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or index < 0:
            return
        sv.blockSignals(True)
        sv.ui.regionSelect.setCurrentIndex(index)  # triggers changeRegion() internally
        sv.blockSignals(False)
        self._on_a2_stack_loaded()  # sync a2_imageView now that sv.stack is correct

    def _on_a2_map(self):
        """Dispatch to dual-energy or ROI-RGB map depending on energy count."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        if len(sv.stack.energies) == 2:
            self._a2_dual_energy_map()
        else:
            self._a2_roi_rgb_map()

    def _a2_dual_energy_map(self):
        """Align two frames, compute OD, display the difference (frame[1] - frame[0])."""
        sv = self.ui.a2_stack_viewer
        sv.progress_updated.emit(0)
        sv.stack.update()
        sv.stack.alignFrames(
            mode='manualtranslation',
            progress_callback=lambda pct: sv.progress_updated.emit(pct)
        )
        sv.stack.calcOD()
        sv.progress_updated.emit(100)
        diff = sv.stack.odFrames[1] - sv.stack.odFrames[0]
        self.ui.a2_imageView.setImage(np.ascontiguousarray(diff.T))

    def _a2_roi_rgb_map(self):
        """Compute an RGB map from 2-3 Spectrum ROI mean spectra."""
        sv = self.ui.a2_stack_viewer
        frames = self._a2_get_display_frames()
        spectrum_entries = [e for e in self._a2_rois if e['type'] == 'Spectrum']
        spectra = []
        for entry in spectrum_entries:
            spec = self._a2_roi_mean_spectrum(entry['roi'], frames)
            if spec is not None:
                spectra.append(spec)
        n = len(spectra)
        if n < 2:
            return
        rgb = [1] * n + [0] * (3 - n)
        # rgbMap always fits against stack.filteredImages; if PCA hasn't been run
        # use the current display frames (OD or transmission) directly.
        if sv.stack.filteredImages is None:
            sv.stack.filteredImages = frames
            sv.stack.nEnergies, sv.stack.nY, sv.stack.nX = frames.shape
        sv.stack.rgbMap(spectra, rgb)
        if sv.stack.rgbImage is not None:
            self.ui.a2_imageView.setImage(
                np.ascontiguousarray(sv.stack.rgbImage.transpose(1, 0, 2)))

    def _on_a2_auto_process_done(self):
        """After Auto Process, switch imageView to OD and enable the OD checkbox."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or sv.stack.odFrames is None:
            return
        # Enable and check the OD checkbox without triggering _on_a2_od_toggled
        if hasattr(self.ui, 'a2_odCheckbox'):
            self.ui.a2_odCheckbox.blockSignals(True)
            self.ui.a2_odCheckbox.setEnabled(True)
            self.ui.a2_odCheckbox.setChecked(True)
            self.ui.a2_odCheckbox.blockSignals(False)
        # Update spectrum plot axis label to match OD display
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        pi.setLabel('left', 'Optical Density')
        pi.getAxis('left').enableAutoSIPrefix(False)
        # Display OD frames in imageView
        frames = sv.stack.odFrames
        self.ui.a2_imageView.setImage(np.ascontiguousarray(frames.transpose(0, 2, 1)))
        energy_idx = sv.ui.verticalSlider.value()
        if energy_idx > 0:
            self.ui.a2_imageView.setCurrentIndex(energy_idx)

    def _on_a2_auto_process(self):
        """Dispatch Auto Process: special pipeline for 2/4/6-energy map scans, else default."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        if len(sv.stack.energies) in (2, 4, 6):
            self._on_a2_map_scan_process()
        else:
            sv.autoProcess()

    def _on_a2_map_scan_process(self):
        """Despike → Circular Image align → OD → difference map display for 2/4/6-energy stacks."""
        sv = self.ui.a2_stack_viewer
        stack = sv.stack
        n = len(stack.energies)
        pb = self.ui.a2_progressBar

        # ── Step 1: Despike ───────────────────────────────────────────────────
        pb.setValue(0)
        QtWidgets.QApplication.processEvents()
        try:
            kernel_size = int(self.ui.a2_despikeKernelEdit.text())
            n_sigma = float(self.ui.a2_despikeNSigmaEdit.text())
        except ValueError:
            kernel_size, n_sigma = 3, 5
        sv.applyDespike(kernel_size, n_sigma)
        pb.setValue(20)
        QtWidgets.QApplication.processEvents()

        # ── Step 2: Circular Image alignment ─────────────────────────────────
        stack.alignFrames(
            mode='manualtranslation',
            progress_callback=lambda pct: (
                pb.setValue(20 + int(pct * 0.4)),
                QtWidgets.QApplication.processEvents(),
            )
        )
        pb.setValue(60)
        QtWidgets.QApplication.processEvents()

        # ── Step 3: Optical density ───────────────────────────────────────────
        stack.calcOD()
        self.ui.a2_odCheckbox.blockSignals(True)
        self.ui.a2_odCheckbox.setEnabled(True)
        self.ui.a2_odCheckbox.setChecked(True)
        self.ui.a2_odCheckbox.blockSignals(False)
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        pi.setLabel('left', 'Optical Density')
        pi.getAxis('left').enableAutoSIPrefix(False)
        pb.setValue(80)
        QtWidgets.QApplication.processEvents()

        # ── Step 4: Difference maps ───────────────────────────────────────────
        # Pairs: (0,1), (2,3), (4,5) — second minus first of each pair
        od = stack.odFrames
        diffs = [od[i + 1] - od[i] for i in range(0, n, 2)]

        if n == 2:
            self.ui.a2_imageView.setImage(np.ascontiguousarray(diffs[0].T))

        elif n == 4:
            # Pair 0 → green channel, pair 1 → red channel
            nY, nX = diffs[0].shape
            rgb = np.zeros((nY, nX, 3), dtype='uint8')
            for diff, ch in zip(diffs, [1, 0]):   # green=1, red=0
                clipped = np.clip(diff, 0, None)
                ch_max = clipped.max()
                if ch_max > 0:
                    rgb[:, :, ch] = (255 * clipped / ch_max).astype('uint8')
            self.ui.a2_imageView.setImage(np.ascontiguousarray(rgb.transpose(1, 0, 2)))

        else:  # n == 6
            # Pairs → R, G, B channels
            nY, nX = diffs[0].shape
            rgb = np.zeros((nY, nX, 3), dtype='uint8')
            for diff, ch in zip(diffs, [0, 1, 2]):
                clipped = np.clip(diff, 0, None)
                ch_max = clipped.max()
                if ch_max > 0:
                    rgb[:, :, ch] = (255 * clipped / ch_max).astype('uint8')
            self.ui.a2_imageView.setImage(np.ascontiguousarray(rgb.transpose(1, 0, 2)))

        pb.setValue(100)

    # ── Analysis2 Save ───────────────────────────────────────────────────────

    def _on_a2_save_data(self):
        """Save all available analysis results to a user-chosen directory."""
        import os, csv
        from tifffile import imwrite as tif_imsave
        from PIL import Image as PILImage

        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            QtWidgets.QMessageBox.warning(self, "No Data", "Load a stack before saving.")
            return

        # Ask user for a directory
        save_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose save directory", os.path.dirname(sv.stack.fileName)
        )
        if not save_dir:
            return

        stack = sv.stack
        saved = []
        errors = []

        def _try_save(label, func):
            try:
                func()
                saved.append(label)
            except Exception as exc:
                errors.append(f"{label}: {exc}")

        # ── Processed (aligned) intensity frames ─────────────────────────────
        if stack.processedFrames is not None:
            path = os.path.join(save_dir, "processedFrames.tif")
            _try_save("processedFrames.tif",
                      lambda: tif_imsave(path, stack.processedFrames.astype('float32')))

        # ── OD frames ────────────────────────────────────────────────────────
        od = self._a2_od_frames
        if od is not None:
            path = os.path.join(save_dir, "odFrames.tif")
            _try_save("odFrames.tif",
                      lambda p=path, d=od: tif_imsave(p, d.astype('float32')))

        # ── I0 histogram mask ─────────────────────────────────────────────────
        if self._a2_i0_mask is not None:
            path = os.path.join(save_dir, "i0Mask.tif")
            _try_save("i0Mask.tif",
                      lambda p=path, m=self._a2_i0_mask: tif_imsave(p, m.astype('uint8')))

        # ── ROI spectra (Spectrum ROIs drawn on the image) ───────────────────
        spectrum_entries = [e for e in self._a2_rois if e['type'] == 'Spectrum']
        if spectrum_entries and stack.processedFrames is not None:
            frames = self._a2_get_display_frames()
            energies = stack.energies
            spectra = []
            for i, entry in enumerate(spectrum_entries):
                spec = self._a2_roi_mean_spectrum(entry['roi'], frames)
                if spec is not None:
                    spectra.append((f"ROI_{i+1}", spec))
            if spectra:
                path = os.path.join(save_dir, "roiSpectra.csv")
                def _write_roi_spectra(p=path, e=energies, s=spectra):
                    with open(p, 'w', newline='') as f:
                        w = csv.writer(f)
                        w.writerow(["Energy"] + [name for name, _ in s])
                        for j, en in enumerate(e):
                            w.writerow([en] + [sp[j] for _, sp in s])
                _try_save("roiSpectra.csv", _write_roi_spectra)

        # ── PCA components ────────────────────────────────────────────────────
        if stack.pcaImages is not None:
            path = os.path.join(save_dir, "pcaComponents.tif")
            _try_save("pcaComponents.tif",
                      lambda: tif_imsave(path, stack.pcaImages.astype('float32')))

        # ── PCA eigenvalues ───────────────────────────────────────────────────
        if hasattr(stack, 'eigenVals') and stack.eigenVals is not None:
            path = os.path.join(save_dir, "eigenvalues.csv")
            def _write_eigenvals(p=path, ev=stack.eigenVals):
                with open(p, 'w', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(["Component", "Eigenvalue"])
                    for i, v in enumerate(ev):
                        w.writerow([i + 1, float(v)])
            _try_save("eigenvalues.csv", _write_eigenvals)

        # ── NMF component maps and spectra ───────────────────────────────────
        if hasattr(stack, 'nmfMaps') and stack.nmfMaps is not None:
            path = os.path.join(save_dir, "nmfMaps.tif")
            _try_save("nmfMaps.tif",
                      lambda p=path, m=stack.nmfMaps: tif_imsave(p, m.astype('float32')))

        if hasattr(stack, 'nmfComponents') and stack.nmfComponents is not None:
            path = os.path.join(save_dir, "nmfSpectra.csv")
            energies = stack.energies
            comps = stack.nmfComponents
            def _write_nmf_spectra(p=path, e=energies, c=comps):
                with open(p, 'w', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(["Energy"] + [f"Component_{i+1}" for i in range(len(c))])
                    for j, en in enumerate(e):
                        w.writerow([en] + [c[i][j] for i in range(len(c))])
            _try_save("nmfSpectra.csv", _write_nmf_spectra)

        # ── Cluster label map ─────────────────────────────────────────────────
        if hasattr(stack, 'clusters') and stack.clusters is not None:
            path = os.path.join(save_dir, "clusterMap.tif")
            _try_save("clusterMap.tif",
                      lambda: tif_imsave(path, stack.clusters.astype('int32')))

        # ── Cluster spectra ───────────────────────────────────────────────────
        if hasattr(stack, 'clusterSpectra') and stack.clusterSpectra:
            path = os.path.join(save_dir, "clusterSpectra.csv")
            energies = stack.energies
            cs = stack.clusterSpectra
            def _write_cluster_spectra(p=path, e=energies, c=cs):
                with open(p, 'w', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(["Energy"] + [f"Cluster_{i+1}" for i in range(len(c))])
                    for j, en in enumerate(e):
                        w.writerow([en] + [c[i][j] for i in range(len(c))])
            _try_save("clusterSpectra.csv", _write_cluster_spectra)

        # ── RGB cluster map ───────────────────────────────────────────────────
        if hasattr(stack, 'clusters') and stack.clusters is not None:
            path = os.path.join(save_dir, "rgbClusterMap.png")
            def _write_rgb_cluster(p=path):
                rgb = stack.rgbClusterMap()
                PILImage.fromarray(rgb.astype('uint8')).save(p)
            _try_save("rgbClusterMap.png", _write_rgb_cluster)

        # ── RGB component map (from Map button) ───────────────────────────────
        if stack.rgbImage is not None:
            path = os.path.join(save_dir, "rgbMap.png")
            _try_save("rgbMap.png",
                      lambda: PILImage.fromarray(stack.rgbImage.astype('uint8')).save(path))

        # ── Report ────────────────────────────────────────────────────────────
        msg = f"Saved {len(saved)} file(s) to:\n{save_dir}"
        if saved:
            msg += "\n\n  " + "\n  ".join(saved)
        if errors:
            msg += f"\n\n{len(errors)} error(s):\n  " + "\n  ".join(errors)
        QtWidgets.QMessageBox.information(self, "Save Complete", msg)

    def _a2_render_image_png(self):
        """Render the current imageView frame with a metadata bar (browser style)."""
        from pyqtgraph.exporters import ImageExporter
        sv = self.ui.a2_stack_viewer

        view = self.ui.a2_imageView.getView()
        prev_state = view.getState()
        view.autoRange(padding=0)

        # Hide the in-view scale bar while exporting; the metadata bar below carries it.
        sb_was_visible = (self._a2_scale_bar is not None and self._a2_scale_bar.isVisible())
        if sb_was_visible:
            self._a2_scale_bar.hide()

        exporter = ImageExporter(view)
        img_qimage = exporter.export(toBytes=True)
        export_view_rect = view.viewRect()
        view.setState(prev_state)

        if sb_was_visible:
            self._a2_scale_bar.show()

        img_w = img_qimage.width()
        img_h = img_qimage.height()

        # ALS logo
        _here     = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(_here, '..', '..', 'icons', 'als-logo.png')
        logo      = QtGui.QImage(logo_path)
        logo_w    = logo.width()  if not logo.isNull() else 0
        logo_h    = logo.height() if not logo.isNull() else 0

        font   = QtGui.QFont("Monospace", 11)
        fm     = QtGui.QFontMetrics(font)
        line_h = fm.height()
        pad    = 12

        stack     = sv.stack
        energies  = stack.energies
        energy_idx = min(self.ui.a2_imageView.currentIndex, len(energies) - 1)
        current_e  = f"{energies[energy_idx]:.2f} eV" if energies is not None and len(energies) else ""
        e_range    = (f"{energies[0]:.1f}–{energies[-1]:.1f} eV  ({len(energies)} pts)"
                      if energies is not None and len(energies) else "")
        od_str     = ("Optical Density"
                      if hasattr(self.ui, 'a2_odCheckbox') and self.ui.a2_odCheckbox.isChecked()
                      else "Transmission")

        row1_parts = [v for v in [os.path.basename(stack.fileName), current_e, od_str] if v]
        row2_parts = [v for v in [e_range] if v]
        meta_rows  = []
        if row1_parts:
            meta_rows.append("   ".join(row1_parts))
        if row2_parts:
            meta_rows.append("   ".join(row2_parts))

        text_h = pad + len(meta_rows) * line_h + pad
        bar_h  = max(text_h, logo_h + 2 * pad) if logo_h else text_h

        out = QtGui.QImage(img_w, img_h + bar_h, QtGui.QImage.Format_RGB32)
        out.fill(QtGui.QColor(0, 0, 0))
        painter = QtGui.QPainter(out)
        painter.drawImage(0, 0, img_qimage)

        text_x = pad
        if not logo.isNull():
            painter.drawImage(pad, img_h + (bar_h - logo_h) // 2, logo)
            text_x = pad + logo_w + pad

        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.setFont(font)
        for i, row in enumerate(meta_rows):
            painter.drawText(text_x, img_h + pad + i * line_h + fm.ascent(), row)

        # Scale bar
        if self._a2_scale_bar is not None and self._a2_scale_bar.isVisible():
            dx = getattr(stack, 'xpixelsize', None)
            if dx:
                bar_size_data = self._a2_scale_bar.size   # image pixels
                nice_um = bar_size_data * dx
                bar_label = (f"{nice_um * 1000:.4g} nm" if nice_um < 1
                             else f"{nice_um:.4g} µm")
                if export_view_rect.width() > 0:
                    bar_px = max(10, round(abs(bar_size_data * img_w / export_view_rect.width())))
                else:
                    bar_px = 50
                bar_thick = 5
                bar_x     = img_w - bar_px - pad
                bar_y     = img_h + (bar_h - bar_thick - fm.ascent() - 2) // 2 + fm.ascent() + 2
                painter.setBrush(QtGui.QColor(255, 255, 255))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawRect(bar_x, bar_y, bar_px, bar_thick)
                painter.setPen(QtGui.QColor(255, 255, 255))
                painter.setFont(font)
                lw = fm.horizontalAdvance(bar_label)
                painter.drawText(bar_x + (bar_px - lw) // 2, bar_y - 2, bar_label)

        painter.end()
        return out

    def _on_a2_record_toggle(self):
        """Start or stop recording analysis actions."""
        if self._recorder.recording:
            self._recorder.stop()
            self.ui.a2_recordButton.setText("Record")
            self.ui.a2_recordButton.setStyleSheet("")
            self.ui.a2_exportScriptButton.setEnabled(self._recorder.has_actions)
        else:
            sv = self.ui.a2_stack_viewer
            self._recorder.start()
            # Auto-prepend load_stack so the exported script is self-contained
            if sv.haveStack:
                filepath = getattr(sv.stack, 'fileName', None) or getattr(sv.stack, 'nxFile', '')
                region   = getattr(sv.stack, 'iRegion', 0)
                self._recorder.record("load_stack", filepath=filepath, region=region)
            self.ui.a2_recordButton.setText("Stop")
            self.ui.a2_recordButton.setStyleSheet("color: red; font-weight: bold;")

    def _on_a2_export_script(self):
        """Show a save dialog and write the recorded script to disk."""
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Analysis Script", "", "Python Script (*.py)"
        )
        if not path:
            return
        if not path.endswith(".py"):
            path += ".py"
        self._recorder.export_script(path)
        QtWidgets.QMessageBox.information(self, "Script Exported", f"Saved to:\n{path}")

    def _on_a2_save_png(self):
        """Save the current image and/or spectrum plot as a PNG file."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            QtWidgets.QMessageBox.warning(self, "No Data", "Load a stack before saving.")
            return

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Save PNG")
        dlg.setMinimumWidth(240)
        layout = QtWidgets.QVBoxLayout(dlg)
        combo = QtWidgets.QComboBox()
        combo.addItems(["Image", "Spectrum"])
        layout.addWidget(combo)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        from pyqtgraph.exporters import ImageExporter

        if combo.currentText() == "Image":
            out = self._a2_render_image_png()
        else:
            exp = ImageExporter(self.ui.a2_spectrumPlot.getPlotItem())
            exp.parameters()['width'] = 1200
            out = exp.export(toBytes=True)

        stem = os.path.splitext(sv.stack.fileName)[0]
        save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save PNG", f"{stem}.png", "PNG Images (*.png)"
        )
        if save_path:
            out.save(save_path, "PNG")

    def _on_a2_add_to_log(self):
        """Show the Add-to-Log dialog and append the chosen items to the logbook."""
        import os
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            QtWidgets.QMessageBox.warning(self, "No Data", "Load a stack before logging.")
            return

        # ── Dialog ────────────────────────────────────────────────────────────
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Add to Log")
        dlg.setMinimumWidth(320)
        layout = QtWidgets.QVBoxLayout(dlg)

        cb_image    = QtWidgets.QCheckBox("Image Data",    checked=True)
        cb_spectrum = QtWidgets.QCheckBox("Spectrum Plot", checked=True)
        cb_meta     = QtWidgets.QCheckBox("Metadata",      checked=True)
        for cb in (cb_image, cb_spectrum, cb_meta):
            layout.addWidget(cb)

        layout.addWidget(QtWidgets.QLabel("Comment:"))
        comment_edit = QtWidgets.QLineEdit()
        layout.addWidget(comment_edit)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        want_image    = cb_image.isChecked()
        want_spectrum = cb_spectrum.isChecked()
        want_meta     = cb_meta.isChecked()
        comment       = comment_edit.text()

        if not want_image and not want_spectrum:
            QtWidgets.QMessageBox.warning(
                self, "Nothing to log", "Select at least Image Data or Spectrum Plot."
            )
            return

        # ── Render image view ─────────────────────────────────────────────────
        from pyqtgraph.exporters import ImageExporter

        def _render_widget(view_item, target_width):
            exp = ImageExporter(view_item)
            exp.parameters()['width'] = target_width
            return exp.export(toBytes=True)   # returns QImage

        img_qimage  = _render_widget(self.ui.a2_imageView.getView(),       800) if want_image    else None
        spec_qimage = _render_widget(self.ui.a2_spectrumPlot.getPlotItem(), 1200) if want_spectrum else None

        # ── Composite side-by-side ────────────────────────────────────────────
        parts = [q for q in (img_qimage, spec_qimage) if q is not None]
        total_w = sum(p.width()  for p in parts)
        total_h = max(p.height() for p in parts)

        composite = QtGui.QImage(total_w, total_h, QtGui.QImage.Format_RGB32)
        composite.fill(QtGui.QColor("white"))
        painter = QtGui.QPainter(composite)
        x = 0
        for p in parts:
            painter.drawImage(x, 0, p)
            x += p.width()
        painter.end()

        # ── Metadata text ─────────────────────────────────────────────────────
        detail_text = ""
        if want_meta:
            stack = sv.stack
            lines = []
            lines.append(f"File: {os.path.basename(stack.fileName)}")
            if stack.energies is not None and len(stack.energies) > 0:
                e = stack.energies
                lines.append(f"Energies: {len(e)}  ({e[0]:.2f} – {e[-1]:.2f} eV)")
            if stack.odFrames is not None:
                lines.append("OD: computed")
            if hasattr(stack, 'clusters') and stack.clusters is not None:
                n_clusters = int(stack.clusters.max()) + 1
                lines.append(f"Clusters: {n_clusters}")
            if stack.pcaImages is not None:
                lines.append(f"PCA components: {stack.pcaImages.shape[0]}")
            # ROI summary
            spectrum_rois = [e for e in self._a2_rois if e['type'] == 'Spectrum']
            if spectrum_rois:
                lines.append(f"Spectrum ROIs: {len(spectrum_rois)}")
            detail_text = "\n".join(lines)

        meta = {
            "filename":  os.path.basename(sv.stack.fileName),
            "scan_type": "STXM Stack",
        }

        folder = os.path.dirname(sv.stack.fileName)
        try:
            from pystxmcontrol.utils.logbook import add_entry
            index = add_entry(folder, composite, meta, comment, detail_text)
            QtWidgets.QMessageBox.information(
                self, "Logbook updated",
                f"Entry {index} added.\n\nLogbook: {os.path.join(folder, 'logbook.pdf')}",
            )
        except Exception as exc:
            import traceback
            QtWidgets.QMessageBox.critical(
                self, "Logbook error",
                f"Could not add to logbook:\n{exc}\n\n{traceback.format_exc()}",
            )

    # ── Analysis2 Clustering tab ─────────────────────────────────────────────

    @records("calc_pca")
    def _on_a2_calc_pca(self):
        """Run PCA + clustering, then enable the display/plot combos."""
        sv = self.ui.a2_stack_viewer
        od = self._a2_od_frames
        if not sv.haveStack or od is None:
            QtWidgets.QMessageBox.warning(
                self, "Optical Density Required",
                "Calculate optical density before clustering."
            )
            return
        # Ensure stack.odFrames is populated so applyPCA can use it.
        # Apply inverse I0 mask if requested (zeros out the I0 region).
        use_mask = (self.ui.a2_pcaMaskI0Checkbox.isChecked()
                    and self._a2_i0_mask is not None)
        sv.stack.odFrames = od * (~self._a2_i0_mask)[np.newaxis] if use_mask else od
        try:
            n_components = int(self.ui.a2_nComponentsEdit.text())
            n_clusters   = int(self.ui.a2_nClustersEdit.text())
        except ValueError:
            return
        reduce_mass  = self.ui.a2_reduceMassCheckbox.isChecked()
        remove_pre   = self.ui.a2_removePreEdgeCheckbox.isChecked()

        # applyPCA emits stack_loaded which wipes _a2_od_frames and disables the OD
        # checkbox.  Save state now and restore it afterwards.
        saved_od       = self._a2_od_frames
        saved_i0_hist  = self._a2_i0_hist_spectrum
        od_was_checked = (hasattr(self.ui, 'a2_odCheckbox')
                          and self.ui.a2_odCheckbox.isChecked())

        sv.applyPCA(n_components, n_clusters, reduce_mass, remove_pre)

        # Restore OD state so the Main tab remains functional
        self._a2_od_frames        = saved_od
        self._a2_i0_hist_spectrum = saved_i0_hist
        self._a2_update_od_checkbox_state()
        if od_was_checked and hasattr(self.ui, 'a2_odCheckbox'):
            self.ui.a2_odCheckbox.setChecked(True)

        # Enable combos now that PCA results exist
        self.ui.a2_clusterImageCombo.setEnabled(True)
        self.ui.a2_clusterPlotCombo.setEnabled(True)
        return {"n_components": n_components, "n_clusters": n_clusters}

    def _on_a2_cluster_image_changed(self, text):
        """Switch the image view to show the selected data type."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        stack = sv.stack
        if text == 'Transmission':
            frames = stack.processedFrames
            self.ui.a2_imageView.setImage(np.ascontiguousarray(frames.transpose(0, 2, 1)))
        elif text == 'Optical Density':
            if stack.odFrames is None:
                return
            frames = stack.odFrames
            self.ui.a2_imageView.setImage(np.ascontiguousarray(frames.transpose(0, 2, 1)))
        elif text == 'Principal Components':
            if stack.pcaImages is None:
                return
            frames = stack.pcaImages
            self.ui.a2_imageView.setImage(np.ascontiguousarray(frames.transpose(0, 2, 1)))
        elif text == 'Clusters':
            if not hasattr(stack, 'rgbClusterImage') or stack.rgbClusterImage is None:
                return
            # RGB image: (ny, nx, 3) → transpose to (nx, ny, 3) for pyqtgraph
            self.ui.a2_imageView.setImage(np.ascontiguousarray(
                stack.rgbClusterImage.transpose(1, 0, 2)))
        elif text == 'RGB Map':
            if stack.rgbImage is None:
                return
            # rgbImage is (ny, nx, 3) → transpose to (nx, ny, 3) for pyqtgraph
            self.ui.a2_imageView.setImage(np.ascontiguousarray(
                stack.rgbImage.transpose(1, 0, 2)))

    def _on_a2_cluster_plot_changed(self, text):
        """Switch the spectrum plot between ROI spectra, cluster spectra, and eigenvalues."""
        sv = self.ui.a2_stack_viewer
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        self._a2_clear_cluster_curves()

        if text == 'ROI Spectra':
            self._a2_set_roi_curves_visible(True)
            pi.setLabel('bottom', 'Energy', units='eV')
            pi.setLabel('left', 'Counts' if not (
                hasattr(self.ui, 'a2_odCheckbox') and self.ui.a2_odCheckbox.isChecked()
            ) else 'Optical Density')
            self._on_a2_roi_changed()

        elif text == 'Cluster Spectra':
            self._a2_set_roi_curves_visible(False)
            if not sv.haveStack or not sv.stack.clusterSpectra:
                return
            energies = sv.stack.energies
            pen_colors = sv.stack.penColors
            pi.addLegend(offset=(10, 10))
            for i, spectrum in enumerate(sv.stack.clusterSpectra):
                r, g, b = pen_colors[i % len(pen_colors)]
                color = (int(r * 255), int(g * 255), int(b * 255))
                curve = pi.plot(energies, spectrum,
                                pen=pg.mkPen(color, width=1.5),
                                name=f'Cluster {i + 1}')
                self._a2_cluster_curves.append(curve)
            pi.setLabel('bottom', 'Energy', units='eV')
            pi.setLabel('left', 'Optical Density')

        elif text == 'PCA Eigenvalues':
            self._a2_set_roi_curves_visible(False)
            if not sv.haveStack or not hasattr(sv.stack, 'eigenVals') or sv.stack.eigenVals is None:
                return
            eigen_vals = sv.stack.eigenVals
            log_vals = np.log(eigen_vals[eigen_vals > 0])
            x = np.arange(1, len(log_vals) + 1)
            curve = pi.plot(x, log_vals,
                            pen=None, symbol='o', symbolSize=7,
                            symbolBrush=pg.mkBrush('c'))
            self._a2_cluster_curves.append(curve)
            pi.setLabel('bottom', 'Principal Component')
            pi.setLabel('left', 'log(Explained Variance)')
            pi.setYRange(0, log_vals.max())

    def _on_a2_calc_rgb_map(self):
        """Parse target spectra indices and compute the RGB map."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or not sv.stack.clusterSpectra:
            QtWidgets.QMessageBox.warning(
                self, "Clustering Required",
                "Calculate PCA and clustering before computing the RGB map."
            )
            return
        try:
            indices = [int(s.strip()) for s in self.ui.a2_targetSpectraEdit.text().split(',') if s.strip()]
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Input",
                                          "Target Spectra must be a comma-separated list of integers.")
            return
        if len(indices) < 2:
            QtWidgets.QMessageBox.warning(self, "Invalid Input",
                                          "At least 2 target spectra are required for an RGB map.")
            return
        sv.applyRGBMap(indices)
        # applyRGBMap emits stack_loaded which disables the combos — re-enable them
        self.ui.a2_clusterImageCombo.setEnabled(True)
        self.ui.a2_clusterPlotCombo.setEnabled(True)
        # Switch display to RGB Map automatically
        if hasattr(self.ui, 'a2_clusterImageCombo'):
            idx = self.ui.a2_clusterImageCombo.findText('RGB Map')
            if idx >= 0:
                self.ui.a2_clusterImageCombo.setCurrentIndex(idx)

    # ── Analysis2 normalization (pre/post edge) ───────────────────────────────

    def _a2_remove_edge_region(self, which):
        """Remove a LinearRegionItem ('pre' or 'post') from the spectrum plot."""
        attr = f'_a2_{which}_edge_region'
        region = getattr(self, attr)
        if region is not None:
            self.ui.a2_spectrumPlot.getPlotItem().removeItem(region)
            setattr(self, attr, None)

    def _a2_add_edge_region(self, which):
        """Add a LinearRegionItem for 'pre' or 'post' edge to the spectrum plot."""
        sv = self.ui.a2_stack_viewer
        energies = sv.stack.energies if sv.haveStack else [0, 1]
        e_min, e_max = min(energies), max(energies)
        span = e_max - e_min

        if which == 'pre':
            bounds = (e_min, e_min + span * 0.15)
            color = (100, 150, 255, 60)   # blue-ish, translucent
        else:
            bounds = (e_max - span * 0.15, e_max)
            color = (255, 120, 50, 60)    # orange-ish, translucent

        region = pg.LinearRegionItem(
            values=bounds,
            brush=pg.mkBrush(*color),
            pen=pg.mkPen(color[:3], width=1),
        )
        self.ui.a2_spectrumPlot.getPlotItem().addItem(region)
        setattr(self, f'_a2_{which}_edge_region', region)

    def _on_a2_pre_edge_checkbox(self, state):
        if state:
            self._a2_add_edge_region('pre')
        else:
            self._a2_remove_edge_region('pre')

    def _a2_frames_in_region(self, region):
        """Return indices of energies that fall within the LinearRegionItem bounds."""
        sv = self.ui.a2_stack_viewer
        lo, hi = region.getRegion()
        energies = np.asarray(sv.stack.energies)
        return np.where((energies >= lo) & (energies <= hi))[0]

    @records("subtract_pre_edge")
    def _on_a2_subtract_pre_edge(self):
        """Average odFrames over the pre-edge region and subtract from all OD frames."""
        if self._a2_pre_edge_region is None:
            QtWidgets.QMessageBox.warning(
                self, "No Pre-Edge Selected",
                "Check 'Select Pre-Edge' and drag the region to the pre-edge energies first."
            )
            return
        sv = self.ui.a2_stack_viewer
        if len(self._a2_frames_in_region(self._a2_pre_edge_region)) == 0:
            QtWidgets.QMessageBox.warning(self, "Empty Region",
                                          "No energy frames fall within the pre-edge region.")
            return
        energy_lo, energy_hi = self._a2_pre_edge_region.getRegion()
        sv.stack.subtractPreEdgeBackground(energy_lo, energy_hi)
        self._a2_refresh_image_view()
        self._a2_update_roi_curves()
        return {"energy_lo": float(energy_lo), "energy_hi": float(energy_hi)}

    @records("detrend_pre_edge")
    def _on_a2_detrend(self):
        """Fit a per-pixel linear trend to the pre-edge OD region and remove it from the stack."""
        if self._a2_pre_edge_region is None:
            QtWidgets.QMessageBox.warning(
                self, "No Pre-Edge Selected",
                "Check 'Select Pre-Edge' and drag the region to the pre-edge energies first."
            )
            return
        sv = self.ui.a2_stack_viewer
        if len(self._a2_frames_in_region(self._a2_pre_edge_region)) == 0:
            QtWidgets.QMessageBox.warning(self, "Empty Region",
                                          "No energy frames fall within the pre-edge region.")
            return
        energy_lo, energy_hi = self._a2_pre_edge_region.getRegion()
        sv.stack.detrendPreEdge(energy_lo, energy_hi)
        self._a2_refresh_image_view()
        self._a2_update_roi_curves()
        return {"energy_lo": float(energy_lo), "energy_hi": float(energy_hi)}

    def _on_a2_reset(self):
        """Uncheck pre-edge selection then delegate to the stack viewer reset."""
        if hasattr(self.ui, 'a2_preEdgeCheckbox') and self.ui.a2_preEdgeCheckbox.isChecked():
            self.ui.a2_preEdgeCheckbox.setChecked(False)
        self._a2_i0_mask = None
        self._a2_update_mask_checkbox_state()
        self._a2_remove_crop_roi()
        self.ui.a2_drawRoiCheckbox.blockSignals(True)
        self.ui.a2_drawRoiCheckbox.setChecked(False)
        self.ui.a2_drawRoiCheckbox.blockSignals(False)
        self.ui.a2_stack_viewer.reset()

    # ── Analysis2 histogram I0 selection ─────────────────────────────────────

    def _on_a2_select_i0_from_histogram(self, state):
        """Toggle histogram-based I0 selection mode."""
        if bool(state):
            self._a2_enter_histogram_mode()
        else:
            self._a2_exit_histogram_mode()

    def _a2_enter_histogram_mode(self):
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        self._a2_histogram_mode = True
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        pi.setLabel('bottom', 'Pixel Value')
        pi.setLabel('left', 'Count')
        pi.getAxis('bottom').enableAutoSIPrefix(False)
        pi.getAxis('left').enableAutoSIPrefix(False)
        self._a2_set_roi_curves_visible(False)
        if self._a2_pre_edge_region is not None:
            self._a2_pre_edge_region.setVisible(False)
        self._a2_update_i0_histogram()

    def _a2_exit_histogram_mode(self):
        self._a2_histogram_mode = False
        # _a2_i0_hist_spectrum is intentionally kept so that OD can be computed
        # after the histogram UI is dismissed without re-entering histogram mode.
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        if self._a2_hist_curve is not None:
            pi.removeItem(self._a2_hist_curve)
            self._a2_hist_curve = None
        if self._a2_i0_hist_region is not None:
            pi.removeItem(self._a2_i0_hist_region)
            self._a2_i0_hist_region = None
        if self._a2_i0_mask_overlay is not None:
            self.ui.a2_imageView.getView().removeItem(self._a2_i0_mask_overlay)
            self._a2_i0_mask_overlay = None
        pi.setLabel('bottom', 'Energy', units='eV')
        pi.setLabel('left', 'Counts')
        pi.getAxis('bottom').enableAutoSIPrefix(True)
        pi.getAxis('left').enableAutoSIPrefix(True)
        self._a2_set_roi_curves_visible(True)
        if self._a2_pre_edge_region is not None:
            self._a2_pre_edge_region.setVisible(True)
        pi.vb.enableAutoRange(axis=pi.vb.XYAxes)
        self._a2_update_od_checkbox_state()

    def _a2_update_i0_histogram(self):
        """Rebuild the histogram from processedFrames and add the region selector."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack:
            return
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        mean_frame = sv.stack.processedFrames.mean(axis=0).ravel()
        counts, bin_edges = np.histogram(mean_frame, bins=256)
        # Step-mode histogram plot
        if self._a2_hist_curve is not None:
            pi.removeItem(self._a2_hist_curve)
        self._a2_hist_curve = pi.plot(
            bin_edges, np.append(counts, 0),
            stepMode='left',
            fillLevel=0,
            brush=pg.mkBrush(150, 150, 150, 200),
            pen=pg.mkPen('k', width=1),
        )
        v_lo, v_hi = float(bin_edges[0]), float(bin_edges[-1])
        span = v_hi - v_lo
        if self._a2_i0_hist_region is None:
            lo = v_lo + 0.02 * span
            hi = v_lo + 0.30 * span
            self._a2_i0_hist_region = pg.LinearRegionItem(
                values=(lo, hi),
                brush=pg.mkBrush(30, 100, 255, 60),
                pen=pg.mkPen(30, 100, 255, 200, width=2),
            )
            self._a2_i0_hist_region.sigRegionChanged.connect(self._a2_update_i0_mask_overlay)
        pi.addItem(self._a2_i0_hist_region)
        pi.autoRange()
        self._a2_update_i0_mask_overlay()

    def _a2_update_i0_mask_overlay(self):
        """Recompute the blue pixel mask from the current histogram region,
        derive the I0 spectrum from the selected pixels, and enable OD."""
        if not self._a2_histogram_mode:
            return
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or self._a2_i0_hist_region is None:
            return
        frames = sv.stack.processedFrames              # (n_e, ny, nx)
        mean_frame = frames.mean(axis=0)               # (ny, nx)
        lo, hi = self._a2_i0_hist_region.getRegion()
        mask = (mean_frame >= lo) & (mean_frame <= hi) # (ny, nx) bool

        # Compute I0 spectrum: mean of selected pixels across each energy
        n_selected = mask.sum()
        if n_selected > 0:
            i0 = frames[:, mask].mean(axis=1)          # (n_e,)
            self._a2_i0_hist_spectrum = i0
            self._a2_i0_mask = mask                    # (ny, nx) bool — persisted for saving
            sv.stack.I0 = np.reshape(i0, (len(i0), 1, 1))
            sv.stack.i0Mask = mask
        else:
            self._a2_i0_hist_spectrum = None
            self._a2_i0_mask = None
            sv.stack.I0 = None
            sv.stack.i0Mask = None
        self._a2_update_mask_checkbox_state()

        # Update OD checkbox state and recompute OD if it is currently active
        self._a2_update_od_checkbox_state()
        if (hasattr(self.ui, 'a2_odCheckbox') and self.ui.a2_odCheckbox.isChecked()):
            self._a2_compute_od()
            self._a2_refresh_image_view()
            self._on_a2_roi_changed()

        # Blue mask overlay on the imageView
        mask_T = mask.T                                # (nx, ny) to match imageView transpose
        nx_, ny_ = mask_T.shape
        rgba = np.zeros((nx_, ny_, 4), dtype=np.uint8)
        rgba[mask_T, 0] = 30
        rgba[mask_T, 1] = 100
        rgba[mask_T, 2] = 255
        rgba[mask_T, 3] = 160
        if self._a2_i0_mask_overlay is None:
            self._a2_i0_mask_overlay = pg.ImageItem()
            self._a2_i0_mask_overlay.setZValue(5)
            self.ui.a2_imageView.getView().addItem(self._a2_i0_mask_overlay)
        self._a2_i0_mask_overlay.setImage(rgba)

    # ── Analysis2 workflow tab switching ─────────────────────────────────────

    def _a2_clear_cluster_curves(self):
        """Remove all cluster/component curves and legend from the spectrum plot."""
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        for c in self._a2_cluster_curves:
            pi.removeItem(c)
        self._a2_cluster_curves.clear()
        if pi.legend is not None:
            pi.legend.scene().removeItem(pi.legend)
            pi.legend = None

    def _a2_set_roi_curves_visible(self, visible: bool):
        """Show or hide all ROI spectrum curves."""
        for entry in self._a2_rois:
            entry['curve'].setVisible(visible)
        self._a2_spec_curve.setVisible(visible)

    def _a2_set_roi_overlays_visible(self, visible: bool):
        """Show or hide freehand ROI overlays on the image view."""
        for entry in self._a2_rois:
            entry['roi'].setVisible(visible)

    def _a2_deactivate_edge_selection(self):
        """Uncheck the pre-edge checkbox and remove any region from the plot."""
        if hasattr(self.ui, 'a2_preEdgeCheckbox') and self.ui.a2_preEdgeCheckbox.isChecked():
            self.ui.a2_preEdgeCheckbox.setChecked(False)   # triggers handler → removes region

    def _on_a2_workflow_tab_changed(self, index):
        """Redraw the spectrum plot to match the newly selected workflow tab."""
        tab = self.ui.a2_workflowTabs.widget(index)
        if tab is None:
            return
        name = tab.objectName()

        # Always deactivate edge selection when leaving the Main tab
        if name != 'a2_tab_main':
            self._a2_deactivate_edge_selection()

        # Hide the line-spectrum ROI whenever we leave the LS tab
        if name != 'a2_tab_metadata':
            self._ls_hide()

        if name == 'a2_tab_main':
            # Clear analysis curves, restore ROI/hover curves and overlays
            self._a2_clear_cluster_curves()
            self._a2_set_roi_curves_visible(True)
            self._a2_set_roi_overlays_visible(True)
            # Refresh display from existing _a2_od_frames without recomputing OD,
            # so post-OD modifications (e.g. pre-edge subtraction) are preserved.
            self._a2_refresh_image_view()
            self._a2_update_roi_curves()
            # Restore axis labels to match the current OD/Transmission state
            pi = self.ui.a2_spectrumPlot.getPlotItem()
            od_on = (hasattr(self.ui, 'a2_odCheckbox')
                     and self.ui.a2_odCheckbox.isChecked())
            if od_on:
                pi.setLabel('left', 'Optical Density')
                pi.getAxis('left').enableAutoSIPrefix(False)
            else:
                pi.setLabel('left', 'Counts')
                pi.getAxis('left').enableAutoSIPrefix(True)
            pi.setLabel('bottom', 'Energy', units='eV')

        elif name == 'a2_tab_clustering':
            # Hide ROI/hover curves and overlays, replot clustering results
            self._a2_set_roi_curves_visible(False)
            self._a2_set_roi_overlays_visible(False)
            self._a2_clear_cluster_curves()
            sv = self.ui.a2_stack_viewer
            if sv.haveStack and self.ui.a2_clusterPlotCombo.isEnabled():
                self._on_a2_cluster_plot_changed(self.ui.a2_clusterPlotCombo.currentText())

        elif name == 'a2_tab_nnmf':
            # Hide ROI/hover curves and overlays, replot NMF results
            self._a2_set_roi_curves_visible(False)
            self._a2_set_roi_overlays_visible(False)
            self._a2_clear_cluster_curves()
            sv = self.ui.a2_stack_viewer
            if sv.haveStack and self.ui.a2_nmfPlotCombo.isEnabled():
                self._on_a2_nmf_plot_changed(self.ui.a2_nmfPlotCombo.currentText())

        elif name == 'a2_tab_metadata':
            # Line Spectrum tab — hide stack ROIs, show LS data and ROI
            self._a2_set_roi_curves_visible(False)
            self._a2_set_roi_overlays_visible(False)
            self._a2_clear_cluster_curves()
            self._ls_show()

        else:
            # Filtering, Registration — leave plot as-is but hide analysis curves and overlays
            self._a2_clear_cluster_curves()
            self._a2_set_roi_curves_visible(True)
            self._a2_set_roi_overlays_visible(False)

    # ── Analysis2 NMF tab ─────────────────────────────────────────────────────

    _NMF_INIT_MAP = {'NNDSVDA': 'nndsvda', 'Random': 'random'}

    @records("calc_nmf")
    def _on_a2_calc_nmf(self):
        """Run NMF decomposition, then enable the display/plot combos."""
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or sv.stack.odFrames is None:
            QtWidgets.QMessageBox.warning(
                self, "Optical Density Required",
                "Calculate optical density before running NMF."
            )
            return
        try:
            n_components = int(self.ui.a2_nmfNComponentsEdit.text())
            n_clusters   = int(self.ui.a2_nmfNClustersEdit.text())
            max_iter     = int(self.ui.a2_nmfMaxIterEdit.text())
        except ValueError:
            return

        init_label = self.ui.a2_nmfInitCombo.currentText()
        init = self._NMF_INIT_MAP.get(init_label, 'nndsvda')

        pb = self.ui.a2_nmfProgressBar
        pb.setValue(0)

        def _progress(pct):
            pb.setValue(pct)
            QtWidgets.QApplication.processEvents()

        # Apply inverse I0 mask if requested (zeros out the I0 region).
        use_mask = (self.ui.a2_nmfMaskI0Checkbox.isChecked()
                    and self._a2_i0_mask is not None)
        if use_mask:
            sv.stack.odFrames = sv.stack.odFrames * (~self._a2_i0_mask)[np.newaxis]

        try:
            sv.stack.calcNMF(
                n_components=n_components,
                n_clusters=n_clusters,
                max_iter=max_iter,
                init=init,
                progress_callback=_progress,
            )
        except Exception as exc:
            import traceback
            QtWidgets.QMessageBox.critical(
                self, "NMF Error",
                f"NMF failed:\n{exc}\n\n{traceback.format_exc()}"
            )
            return

        # Enable display/plot combos and show component maps by default
        self.ui.a2_nmfDisplayCombo.setEnabled(True)
        self.ui.a2_nmfDisplayCombo.setCurrentIndex(0)
        self.ui.a2_nmfPlotCombo.setEnabled(True)
        self.ui.a2_nmfPlotCombo.setCurrentIndex(0)
        self._show_nmf_components()
        self._plot_nmf_component_spectra()
        return {"n_components": n_components, "n_clusters": n_clusters,
                "max_iter": max_iter, "init": init}

    def _show_nmf_components(self):
        """Display the NMF spatial weight maps in the image view."""
        sv = self.ui.a2_stack_viewer
        maps = sv.stack.nmfMaps   # (n_components, nY, nX)
        self.ui.a2_imageView.setImage(np.ascontiguousarray(maps.transpose(0, 2, 1)))

    def _show_nmf_cluster_map(self):
        """Display the kmeans cluster map derived from NMF weights."""
        sv = self.ui.a2_stack_viewer
        cluster_img = sv.stack.rgbClusterMap()
        self.ui.a2_imageView.setImage(np.ascontiguousarray(cluster_img.transpose(1, 0, 2)))

    def _show_nmf_rgb_map(self):
        """Display first 3 NMF component maps composited as RGB."""
        sv = self.ui.a2_stack_viewer
        maps = sv.stack.nmfMaps   # (n_components, nY, nX)
        n = min(3, maps.shape[0])
        rgb = np.zeros((maps.shape[1], maps.shape[2], 3), dtype='uint8')
        for i in range(n):
            ch = maps[i]
            ch_max = ch.max()
            if ch_max > 0:
                rgb[:, :, i] = (255 * ch / ch_max).astype('uint8')
        self.ui.a2_imageView.setImage(np.ascontiguousarray(rgb.transpose(1, 0, 2)))

    def _plot_nmf_component_spectra(self):
        """Plot NMF spectral components (H matrix rows) with matching colors."""
        sv = self.ui.a2_stack_viewer
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        self._a2_clear_cluster_curves()
        self._a2_set_roi_curves_visible(False)
        energies = sv.stack.energies
        components = sv.stack.nmfComponents
        pi.addLegend(offset=(10, 10))
        for i, spec in enumerate(components):
            raw_color = sv.stack.penColors[i % len(sv.stack.penColors)]
            color = tuple(int(c * 255) for c in raw_color)
            curve = pi.plot(energies, spec, pen=pg.mkPen(color, width=1.5), name=f"Comp {i+1}")
            self._a2_cluster_curves.append(curve)
        pi.setLabel('left', 'NMF Component Weight')
        pi.getAxis('left').enableAutoSIPrefix(False)

    def _plot_nmf_cluster_spectra(self):
        """Plot cluster mean spectra from the NMF clustering result."""
        sv = self.ui.a2_stack_viewer
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        self._a2_clear_cluster_curves()
        self._a2_set_roi_curves_visible(False)
        energies = sv.stack.energies
        pi.addLegend(offset=(10, 10))
        for i, spec in enumerate(sv.stack.clusterSpectra):
            raw_color = sv.stack.penColors[i % len(sv.stack.penColors)]
            color = tuple(int(c * 255) for c in raw_color)
            curve = pi.plot(energies, spec, pen=pg.mkPen(color, width=1.5), name=f"Cluster {i+1}")
            self._a2_cluster_curves.append(curve)
        pi.setLabel('left', 'Optical Density')
        pi.getAxis('left').enableAutoSIPrefix(False)

    def _on_a2_nmf_calc_rgb_map(self):
        """Compute an NMF RGB map using the selected target spectra.

        Cluster Spectra mode: runs NNLS fitting of the OD stack against the selected
        cluster mean spectra.  Each RGB channel is the NNLS coefficient map — "how much
        of this cluster's spectral signature is at each pixel."  This is identical to
        the PCA-based RGB Map workflow (stack.nnls).

        Component Spectra mode: uses the NMF spatial weight maps directly as channels.
        """
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or not hasattr(sv.stack, 'nmfComponents') or sv.stack.nmfComponents is None:
            QtWidgets.QMessageBox.warning(
                self, "NMF Required", "Calculate NMF before computing the RGB map."
            )
            return
        try:
            indices = [int(s.strip()) for s in self.ui.a2_nmfTargetSpectraEdit.text().split(',') if s.strip()]
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Input",
                                          "Target Spectra must be a comma-separated list of integers.")
            return
        if len(indices) < 2:
            QtWidgets.QMessageBox.warning(self, "Invalid Input",
                                          "At least 2 target spectra are required for an RGB map.")
            return
        indices = indices[:3]

        plot_mode = self.ui.a2_nmfPlotCombo.currentText()

        if plot_mode == 'Cluster Spectra' and sv.stack.clusterSpectra:
            # Build list of selected cluster mean spectra and fit each pixel's OD
            # spectrum against them using NNLS.  Produces continuous coefficient maps.
            cluster_spectra = sv.stack.clusterSpectra
            targets = []
            for idx in indices:
                i = idx - 1   # 1-based → 0-based
                if 0 <= i < len(cluster_spectra):
                    targets.append(cluster_spectra[i])
            if not targets:
                QtWidgets.QMessageBox.warning(self, "Invalid Indices",
                                              "None of the entered indices match available clusters.")
                return
            sv.stack.nnls(sv.stack.odFrames, targets)
            raw_maps = sv.stack.targetSVDmaps   # (n_targets, nY, nX)
        else:
            # Component Spectra mode: index directly into NMF spatial weight maps
            nmf_maps = sv.stack.nmfMaps   # (n_components, nY, nX)
            selected = []
            for idx in indices:
                i = idx - 1   # 1-based → 0-based
                if 0 <= i < nmf_maps.shape[0]:
                    selected.append(nmf_maps[i])
            if not selected:
                return
            raw_maps = np.array(selected)   # (n_selected, nY, nX)

        nY, nX = raw_maps.shape[1], raw_maps.shape[2]
        rgb = np.zeros((nY, nX, 3), dtype='uint8')
        for ch in range(min(raw_maps.shape[0], 3)):
            ch_map = raw_maps[ch]
            ch_max = ch_map.max()
            if ch_max > 0:
                rgb[:, :, ch] = (255 * ch_map / ch_max).astype('uint8')

        sv.stack.rgbImage = rgb
        self.ui.a2_imageView.setImage(np.ascontiguousarray(rgb.transpose(1, 0, 2)))
        # Switch display combo to RGB Map
        if hasattr(self.ui, 'a2_nmfDisplayCombo'):
            idx = self.ui.a2_nmfDisplayCombo.findText('RGB Map')
            if idx >= 0:
                self.ui.a2_nmfDisplayCombo.blockSignals(True)
                self.ui.a2_nmfDisplayCombo.setCurrentIndex(idx)
                self.ui.a2_nmfDisplayCombo.blockSignals(False)

    def _on_a2_nmf_display_changed(self, text):
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or not hasattr(sv.stack, 'nmfMaps') or sv.stack.nmfMaps is None:
            return
        if text == 'NMF Components':
            self._show_nmf_components()
        elif text == 'Cluster Map':
            self._show_nmf_cluster_map()
        elif text == 'RGB Map':
            self._show_nmf_rgb_map()

    def _on_a2_nmf_plot_changed(self, text):
        sv = self.ui.a2_stack_viewer
        if not sv.haveStack or not hasattr(sv.stack, 'nmfComponents') or sv.stack.nmfComponents is None:
            return
        if text == 'Component Spectra':
            self._plot_nmf_component_spectra()
        elif text == 'Cluster Spectra':
            self._plot_nmf_cluster_spectra()

    # ── end Analysis2 ROI drawing ─────────────────────────────────────────────

    # ── Line Spectrum tab ─────────────────────────────────────────────────────

    def _initialize_ls_tab(self):
        """Build the Line Spectrum tab toolbar programmatically and init state."""
        layout = self.ui.a2_tab_metadata_layout

        bar = QtWidgets.QHBoxLayout()

        self._ls_load_btn = QtWidgets.QPushButton("Load Scan")
        self._ls_load_btn.setFixedWidth(100)
        bar.addWidget(self._ls_load_btn)

        bar.addSpacing(16)

        self._ls_i0_cb = QtWidgets.QCheckBox("Select I0")
        self._ls_i0_cb.setEnabled(False)
        bar.addWidget(self._ls_i0_cb)

        bar.addSpacing(8)

        self._ls_od_cb = QtWidgets.QCheckBox("Optical Density")
        self._ls_od_cb.setEnabled(False)
        bar.addWidget(self._ls_od_cb)

        bar.addStretch(1)

        self._ls_save_btn = QtWidgets.QPushButton("Save Spectra")
        self._ls_save_btn.setEnabled(False)
        bar.addWidget(self._ls_save_btn)

        layout.addLayout(bar)
        layout.addStretch(1)

        # state
        self._ls_data     = None   # (n_spatial, n_energies) raw counts
        self._ls_energies = None   # (n_energies,)
        self._ls_i0       = None   # (n_energies,) I0 spectrum
        self._ls_roi      = None   # pg.LinearRegionItem added to imageView when tab active

        # dedicated spectrum curve (hidden until LS tab active)
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        self._ls_curve = pi.plot([], [], pen=pg.mkPen('c', width=1.5))
        self._ls_curve.setVisible(False)

        self._ls_load_btn.clicked.connect(self._on_ls_load)
        self._ls_i0_cb.stateChanged.connect(self._on_ls_i0_toggled)
        self._ls_od_cb.stateChanged.connect(self._on_ls_od_toggled)
        self._ls_save_btn.clicked.connect(self._on_ls_save)

    def _on_ls_load(self):
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Line Spectrum Scan", "", "STXM files (*.stxm);;All files (*)"
        )
        if not filepath:
            return
        try:
            data, energies, scan_type = self._ls_read_stxm(filepath)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Load Error", f"Could not read file:\n{exc}")
            return
        if "spectrum" not in scan_type.lower():
            QtWidgets.QMessageBox.warning(
                self, "Wrong Scan Type",
                f"Expected a Line Spectrum scan but got: '{scan_type}'\n\nFile not loaded."
            )
            return
        self._ls_data     = data
        self._ls_energies = energies
        self._ls_i0       = None
        self._ls_od_cb.blockSignals(True)
        self._ls_od_cb.setChecked(False)
        self._ls_od_cb.setEnabled(False)
        self._ls_od_cb.blockSignals(False)
        self._ls_i0_cb.blockSignals(True)
        self._ls_i0_cb.setChecked(False)
        self._ls_i0_cb.setEnabled(True)
        self._ls_i0_cb.blockSignals(False)
        self._ls_save_btn.setEnabled(True)
        # Refresh immediately if the LS tab is already visible
        current = self.ui.a2_workflowTabs.currentWidget()
        if current and current.objectName() == 'a2_tab_metadata':
            self._ls_show()

    def _ls_read_stxm(self, filepath):
        """Read a .stxm file; return (data, energies, scan_type).

        data      — (n_spatial, n_energies) float64
        energies  — (n_energies,) float64 (index-based if not found in file)
        scan_type — string from file metadata
        """
        import h5py

        def _s(val):
            if isinstance(val, (list, np.ndarray)):
                val = val[0]
            return val.decode() if isinstance(val, (bytes, np.bytes_)) else str(val)

        with h5py.File(filepath, 'r') as f:
            try:
                defn    = _s(f["entry0/definition"][()])
                version = float(f["entry0/version"][()]) if defn == "NXstxm" else float(defn)
            except Exception:
                version = 0.0

            if version >= 3.0:
                scan_type = ""
                data      = None
                energies  = None
                try:
                    scan_type = _s(f["entry0/default/stxm_scan_type"][0])
                except Exception:
                    pass
                try:
                    for key in f["entry0/instrument"].keys():
                        grp = f[f"entry0/instrument/{key}"]
                        if "type" in grp.attrs and _s(grp.attrs["type"]) == "photon":
                            path = f"entry0/{key}/data"
                            if path in f:
                                data = f[path][()].astype(float)
                                break
                except Exception:
                    pass
                for epath in ("entry0/default/energy", "entry0/energy",
                              "entry0/instrument/mono/energy"):
                    try:
                        e = np.asarray(f[epath][()], dtype=float).ravel()
                        if e.size > 1:
                            energies = e
                            break
                    except Exception:
                        pass
            else:
                scan_type = ""
                data      = None
                energies  = None
                try:
                    scan_type = _s(f["entry0/counter0/stxm_scan_type"][()][0])
                except Exception:
                    pass
                try:
                    data = f["entry0/counter0/data"][()].astype(float)
                except Exception:
                    pass
                for epath in ("entry0/counter0/energy", "entry0/energy"):
                    try:
                        e = np.asarray(f[epath][()], dtype=float).ravel()
                        if e.size > 1:
                            energies = e
                            break
                    except Exception:
                        pass

        if data is None:
            raise ValueError("No detector data found in file.")
        if data.ndim == 3:
            data = data[:, 0, :]     # (n_energies, 1, n_spatial) → (n_energies, n_spatial)
        if data.ndim != 2:
            raise ValueError(f"Unexpected data shape {data.shape}.")
        data = data.T                # → (n_spatial, n_energies)

        n_energies = data.shape[1]
        if energies is None or energies.size == 0:
            energies = np.arange(n_energies, dtype=float)
        elif energies.size != n_energies:
            energies = np.linspace(energies[0], energies[-1], n_energies)

        return data, energies, scan_type

    def _ls_show(self):
        """Display LS data in the shared imageView and add the selection ROI."""
        if self._ls_data is None:
            return
        n_spatial, _ = self._ls_data.shape
        self._ls_update_image_view()
        # (Re-)create the ROI
        self._ls_remove_roi()
        lo = n_spatial / 3.0
        hi = 2.0 * n_spatial / 3.0
        self._ls_roi = pg.LinearRegionItem(orientation='horizontal', values=[lo, hi])
        self._ls_roi.sigRegionChanged.connect(self._on_ls_roi_changed)
        self.ui.a2_imageView.getView().addItem(self._ls_roi)
        # Set spectrum plot axes
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        pi.setLabel('bottom', 'Energy', units='eV')
        if self._ls_od_cb.isChecked():
            pi.setLabel('left', 'Optical Density')
            pi.getAxis('left').enableAutoSIPrefix(False)
        else:
            pi.setLabel('left', 'Counts')
            pi.getAxis('left').enableAutoSIPrefix(True)
        self._ls_curve.setVisible(True)
        self._ls_update_spectrum()

    def _ls_hide(self):
        """Remove the LS ROI and hide the LS spectrum curve."""
        self._ls_remove_roi()
        if self._ls_curve is not None:
            self._ls_curve.setVisible(False)

    def _ls_remove_roi(self):
        if self._ls_roi is not None:
            try:
                self.ui.a2_imageView.getView().removeItem(self._ls_roi)
            except Exception:
                pass
            self._ls_roi = None

    def _ls_update_image_view(self):
        """Display raw counts or OD image depending on checkbox state."""
        if self._ls_data is None:
            return
        if self._ls_od_cb.isChecked() and self._ls_i0 is not None:
            i0 = self._ls_i0.copy()
            i0[i0 <= 0] = np.nan
            od = -np.log(self._ls_data / i0[np.newaxis, :])
            od = np.nan_to_num(od, nan=0.0, posinf=0.0, neginf=0.0)
            display = np.ascontiguousarray(od.T)       # (n_energies, n_spatial)
        else:
            display = np.ascontiguousarray(self._ls_data.T)
        self.ui.a2_imageView.setImage(display)

    def _on_ls_roi_changed(self):
        self._ls_update_spectrum()

    def _ls_get_roi_slice(self):
        """Return (idx0, idx1) for the selected spatial rows, or None."""
        if self._ls_roi is None or self._ls_data is None:
            return None
        n_spatial = self._ls_data.shape[0]
        y0, y1 = self._ls_roi.getRegion()
        idx0 = max(0, int(np.floor(y0)))
        idx1 = min(n_spatial, int(np.ceil(y1)))
        return (idx0, idx1) if idx0 < idx1 else None

    def _ls_update_spectrum(self):
        """Recompute the spectrum for the current ROI and display mode."""
        if self._ls_data is None or self._ls_energies is None or self._ls_curve is None:
            return
        sl = self._ls_get_roi_slice()
        if sl is None:
            self._ls_curve.setData([], [])
            return
        idx0, idx1 = sl

        if self._ls_od_cb.isChecked() and self._ls_i0 is not None:
            i0 = self._ls_i0.copy()
            i0[i0 <= 0] = np.nan
            od = -np.log(self._ls_data / i0[np.newaxis, :])
            od = np.nan_to_num(od, nan=0.0, posinf=0.0, neginf=0.0)
            spectrum = od[idx0:idx1, :].mean(axis=0)
        else:
            spectrum = self._ls_data[idx0:idx1, :].mean(axis=0)
            # Live-update I0 while Select I0 is active
            if self._ls_i0_cb.isChecked():
                self._ls_i0 = spectrum.copy()
                self._ls_od_cb.setEnabled(True)

        self._ls_curve.setData(self._ls_energies, spectrum)

    def _on_ls_i0_toggled(self, state):
        if not state:
            return
        self._ls_od_cb.blockSignals(True)
        self._ls_od_cb.setChecked(False)
        self._ls_od_cb.blockSignals(False)
        self._ls_update_image_view()
        pi = self.ui.a2_spectrumPlot.getPlotItem()
        pi.setLabel('left', 'Counts')
        pi.getAxis('left').enableAutoSIPrefix(True)
        self._ls_update_spectrum()

    def _on_ls_od_toggled(self, state):
        if state:
            if self._ls_i0 is None:
                self._ls_od_cb.blockSignals(True)
                self._ls_od_cb.setChecked(False)
                self._ls_od_cb.blockSignals(False)
                return
            self._ls_i0_cb.blockSignals(True)
            self._ls_i0_cb.setChecked(False)
            self._ls_i0_cb.blockSignals(False)
            pi = self.ui.a2_spectrumPlot.getPlotItem()
            pi.setLabel('left', 'Optical Density')
            pi.getAxis('left').enableAutoSIPrefix(False)
        else:
            pi = self.ui.a2_spectrumPlot.getPlotItem()
            pi.setLabel('left', 'Counts')
            pi.getAxis('left').enableAutoSIPrefix(True)
        self._ls_update_image_view()
        self._ls_update_spectrum()

    def _on_ls_save(self):
        if self._ls_data is None or self._ls_energies is None:
            return
        sl = self._ls_get_roi_slice()
        if sl is None:
            QtWidgets.QMessageBox.warning(
                self, "No Selection", "Adjust the ROI to select a region first."
            )
            return
        idx0, idx1 = sl
        if self._ls_od_cb.isChecked() and self._ls_i0 is not None:
            i0 = self._ls_i0.copy()
            i0[i0 <= 0] = np.nan
            od = -np.log(self._ls_data / i0[np.newaxis, :])
            od = np.nan_to_num(od, nan=0.0, posinf=0.0, neginf=0.0)
            spectrum = od[idx0:idx1, :].mean(axis=0)
            col_label = "OD"
        else:
            spectrum = self._ls_data[idx0:idx1, :].mean(axis=0)
            col_label = "Counts"
        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Spectrum", "", "CSV files (*.csv);;All files (*)"
        )
        if not filepath:
            return
        if not filepath.lower().endswith(".csv"):
            filepath += ".csv"
        try:
            np.savetxt(
                filepath,
                np.column_stack([self._ls_energies, spectrum]),
                delimiter=",",
                header=f"Energy_eV,{col_label}",
                comments="",
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save Error", f"Could not save:\n{exc}")

    # ── end Line Spectrum tab ─────────────────────────────────────────────────


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = Analysis2Widget()
    w.setWindowTitle("STXM Analysis")
    w.resize(1400, 900)
    w.show()
    sys.exit(app.exec())

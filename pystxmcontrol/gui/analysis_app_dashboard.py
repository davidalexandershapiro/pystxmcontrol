"""
Analysis App (dashboard style) — the standalone stack-analysis widget for the
dashboard's Analysis tab.

Like ``browser_app_dashboard`` reskins the classic browser, this reskins the
proven ``Analysis2Widget`` onto the dashboard's dark palette
(``dashboard_theme``): the mock's three-column "Tools / Viewer / Info" layout,
driven by the *same* analysis engine instead of a mock's procedural fields.

The heavy lifting — stack loading/processing (``stackViewerWidget``), ROI
drawing, optical density, filtering, registration, PCA/NMF clustering, the
line-spectrum tool, save/export/logbook — is **reused verbatim** from
``Analysis2Widget``; only the chrome (cards, pills, dashboard viewer) is
rebuilt.  ``AnalysisApp`` subclasses ``Analysis2Widget`` and swaps the generated
``Ui_Analysis2Widget`` for ``_DashboardAnalysisUI``, which builds the dashboard
layout while exposing the identical ``a2_*`` widget names the ~2900 lines of
logic reference.  Because the contract is name-for-name, no logic changes.

Two pieces:

``_DashboardAnalysisUI``
    A drop-in replacement for the generated UI object.  Its ``setupUi`` builds
    the dashboard chrome and creates every ``a2_*`` widget (buttons, combos,
    edits, checkboxes, the spectrum ``PlotWidget``, the ``ImageView``, the six
    workflow-tab pages with their exact object names, the ``a2_calc_pca_layout``
    / ``a2_nmf_calc_layout`` insertion points, and the ``a2_tab_metadata_layout``
    the base fills with the Line-Spectrum toolbar).

``AnalysisApp``
    The whole tab.  Works standalone (carries its own stylesheet) and embedded
    in ``mainwindow_dashboard`` alike, accepts a ``controller`` (for live data)
    and a ``logbook_model`` (for Add-to-Log), and exposes ``load_file`` so the
    Browser's "Send to Analysis" can open a stack here.
"""

import os
import sys

import numpy as np
import pyqtgraph as pg
from PySide6 import QtWidgets
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QComboBox, QLineEdit, QCheckBox,
    QProgressBar, QPlainTextEdit, QTabWidget, QButtonGroup, QScrollArea,
    QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from pyqtgraph import PlotWidget, ImageView

from pystxmcontrol.gui.analysis_widget import Analysis2Widget
from pystxmcontrol.gui.stackviewerwidget import stackViewerWidget
from pystxmcontrol.gui.dashboard_theme import (
    C, build_stylesheet, mono_font, sans_font,
)

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")

# The classic analysis logic was written against pyqtgraph's *default*
# (col-major) image axis order — it hands the ImageView arrays already
# transposed to (n_energies, nx, ny).  ``mainwindow_dashboard`` flips the global
# order to row-major (the acquisition/browser views need it), which would
# transpose every analysis frame when embedded.  We fix this *locally* by
# pinning the analysis ImageView's ImageItem to col-major (see
# ``_ColMajorImageView``) — never by touching the global option, so the
# acquisition view keeps its row-major setting.
_COL_MAJOR = "col-major"

_PRESET = {"gray": "grey", "viridis": "viridis", "inferno": "inferno"}


# ── chrome helpers (module-level twins of the mainwindow/browser helpers) ────
def _mk_label(text="", role=None, font=None, color=None):
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if font:
        lbl.setFont(font)
    if color:
        lbl.setStyleSheet(f"color:{color};background:transparent;")
    return lbl


def _mk_card(title):
    """The dashboard's titled card → (card QFrame, body QVBoxLayout).
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


def _small_btn(text, obj=None):
    b = QPushButton(text)
    b.setProperty("role", "small")
    b.setCursor(Qt.PointingHandCursor)
    if obj:
        b.setObjectName(obj)
    return b


def _primary_btn(text):
    b = QPushButton(text)
    b.setObjectName("beginScan")
    b.setCursor(Qt.PointingHandCursor)
    return b


def _edit(default="", width=None):
    e = QLineEdit(default)
    e.setFont(mono_font(12))
    if width:
        e.setFixedWidth(width)
    return e


def _combo(items):
    cb = QComboBox()
    cb.addItems(items)
    cb.setCursor(Qt.PointingHandCursor)
    return cb


def _field(label, widget):
    """A micro-labelled field → QWidget wrapping (label over widget)."""
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    v.addWidget(_mk_label(label, role="microLabel"))
    v.addWidget(widget)
    return w


def _row(*widgets, spacing=8, stretch_last=False, pad=False, valign=None):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(spacing)
    for i, x in enumerate(widgets):
        stretch = 1 if (stretch_last and i == len(widgets) - 1) else 0
        if isinstance(x, QtWidgets.QLayout):
            h.addLayout(x, stretch)
        elif valign is not None and stretch == 0:
            # valign (e.g. Qt.AlignBottom) lines bare buttons up with the input
            # inside a _field wrapper, whose micro-label would otherwise push
            # the input below the button's centre.
            h.addWidget(x, stretch, valign)
        else:
            h.addWidget(x, stretch)
    # pad=True packs the widgets to the left, sending all slack to the right
    # instead of spreading it between them.
    if pad:
        h.addStretch(1)
    return w


def _hline():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    # C['border'] (#22282f) is nearly black on the dark ground and disappears;
    # use the near-white text color so the divider is clearly visible.
    line.setStyleSheet(f"color: {C['text']}; background: {C['text']};")
    line.setFixedHeight(1)
    return line


def _cmap_control(on_change, checked=0):
    """gray/viridis/inferno segmented pill control wired to ``on_change(name)``."""
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
#  Col-major-pinned image view
# ════════════════════════════════════════════════════════════════════════════
class _ColMajorImageView(ImageView):
    """A ``pg.ImageView`` whose ImageItem is pinned to col-major axis order so
    the analysis logic's already-transposed frames display upright regardless of
    the process-wide ``imageAxisOrder`` (row-major under the dashboard).  The
    built-in time slider (roiPlot) is kept — the analysis logic uses it for
    energy navigation — while the ROI/menu buttons are hidden and the palette is
    darkened to match the dashboard."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.getImageItem().setOpts(axisOrder=_COL_MAJOR)
        self.ui.roiBtn.hide()
        self.ui.menuBtn.hide()
        self.getView().setBackgroundColor(C["plot_ground"])
        hist = self.ui.histogram
        hist.setBackground(C["plot_ground"])
        hist.axis.setPen(C["border"])
        hist.axis.setTextPen(C["text_faint"])
        # Style the built-in energy (time) slider row and label its axis with
        # the real photon energy (values supplied via setImage(xvals=...)).
        self.ui.roiPlot.setBackground(C["plot_ground"])
        _slider_axis = self.ui.roiPlot.getPlotItem().getAxis("bottom")
        _slider_axis.setPen(C["border"])
        _slider_axis.setTextPen(C["text_faint"])
        _slider_axis.setLabel("Energy", units="eV")

    def timeIndex(self, slider):
        """Map the slider position to a frame index by nearest tVal.

        pyqtgraph's default assumes ascending time values (``argwhere(xv <= t)``),
        which freezes the slider on energy stacks scanned high→low (descending
        energies): every drag snaps to the last frame.  Nearest-value search is
        correct for ascending, descending, and non-monotonic energy axes alike.
        """
        if not self.hasTimeAxis():
            return 0, 0.0
        t = slider.value()
        xv = self.tVals
        if xv is None or len(xv) == 0:
            return int(t), t
        ind = int(np.argmin(np.abs(np.asarray(xv, dtype=float) - t)))
        return ind, t


# ════════════════════════════════════════════════════════════════════════════
#  Dashboard UI builder (drop-in for Ui_Analysis2Widget)
# ════════════════════════════════════════════════════════════════════════════
class _DashboardAnalysisUI:
    """Builds the dashboard analysis chrome and exposes the identical ``a2_*``
    widget attributes the ``Analysis2Widget`` logic references by name."""

    def setupUi(self, w):
        # ── compute engine: the classic stack viewer, kept hidden ────────────
        # It owns ``.stack`` and does all loading/processing; display is driven
        # through our own ``a2_imageView``.  Its internal ``ui.verticalSlider`` /
        # ``ui.regionSelect`` / ``ui.live_display`` are used headlessly.
        self.a2_stack_viewer = stackViewerWidget(w)
        self.a2_stack_viewer.hide()

        root = QHBoxLayout(w)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        col1 = self._tools_col()
        col1.setFixedWidth(660)
        col2 = self._viewer_col()
        col3 = self._info_col()
        col3.setFixedWidth(420)
        root.addWidget(col1)
        root.addWidget(col2, 1)
        root.addWidget(col3)

        # Registration and NNMF report through the single footer progress bar
        # (built in col2) rather than their own per-tab bars.
        self.a2_regProgressBar = self.a2_progressBar
        self.a2_nmfProgressBar = self.a2_progressBar

    # ── column 1: spectrum + tools ───────────────────────────────────────────
    def _tools_col(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # OD-vs-energy spectrum plot
        scard, sbody = _mk_card("OD vs energy")
        self.a2_spectrumPlot = PlotWidget()
        self.a2_spectrumPlot.setFixedHeight(280)
        self.a2_spectrumPlot.setBackground(C["plot_ground"])
        sbody.addWidget(self.a2_spectrumPlot)
        v.addWidget(scard)

        # Tools card: Open Stack + Region in the header, workflow tabs, footer.
        tcard, tbody = _mk_card("Tools")
        self.a2_openStackButton = _small_btn("Open Stack")
        tcard._header_layout.addWidget(self.a2_openStackButton)
        tcard._header_layout.addWidget(_mk_label("Region", role="fieldLabel"))
        self.a2_regionCombo = _combo(["Region 1"])
        self.a2_regionCombo.setFixedWidth(110)
        self.a2_regionCombo.setEnabled(False)
        tcard._header_layout.addWidget(self.a2_regionCombo)

        self.a2_workflowTabs = QTabWidget()
        self.a2_workflowTabs.setObjectName("a2_workflowTabs")
        self.a2_workflowTabs.addTab(self._tab_main(), "Main")
        self.a2_workflowTabs.addTab(self._tab_filtering(), "Filtering")
        self.a2_workflowTabs.addTab(self._tab_registration(), "Registration")
        self.a2_workflowTabs.addTab(self._tab_pca(), "PCA")
        self.a2_workflowTabs.addTab(self._tab_nmf(), "NNMF")
        self.a2_workflowTabs.addTab(self._tab_line(), "Line Spectrum")
        tbody.addWidget(self.a2_workflowTabs, 1)

        # Shared footer: global save/record/log actions.
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QHBoxLayout(footer)
        fv.setContentsMargins(14, 10, 14, 10)
        fv.setSpacing(8)
        self.a2_saveDataButton = _small_btn("Save Data")
        self.a2_savePngButton = _small_btn("Save PNG")
        self.a2_recordButton = _small_btn("Record")
        self.a2_exportScriptButton = _small_btn("Export Script")
        self.a2_exportScriptButton.setEnabled(False)
        self.a2_addToLogButton = _small_btn("Add to Log")
        for b in (self.a2_saveDataButton, self.a2_savePngButton,
                  self.a2_recordButton, self.a2_exportScriptButton):
            fv.addWidget(b)
        fv.addStretch(1)
        fv.addWidget(self.a2_addToLogButton)
        tbody.addWidget(footer)

        v.addWidget(tcard, 1)
        return col

    def _page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(14, 14, 14, 14)
        v.setSpacing(10)
        return page, v

    def _tab_main(self):
        page, v = self._page()
        page.setObjectName("a2_tab_main")
        self.a2_tab_main = page

        # process actions (on top)
        self.a2_autoProcessButton = _primary_btn("Auto Process")
        self.a2_mapButton = _small_btn("Map")
        self.a2_mapButton.setEnabled(False)
        self.a2_resetButton = _small_btn("Reset")
        v.addWidget(_row(self.a2_autoProcessButton, self.a2_mapButton,
                         self.a2_resetButton, stretch_last=False))

        v.addWidget(_hline())

        # ROI tools.  Delete Frame lives below the image (see _viewer_col).
        self.a2_roiTypeCombo = _combo(["I0", "Spectrum", "Crop"])
        self.a2_drawRoiCheckbox = QCheckBox("Draw ROI")
        self.a2_deleteRoiButton = _small_btn("Delete ROI")
        self.a2_deleteFrameButton = _small_btn("Delete Frame")
        self.a2_cropButton = _small_btn("Crop")
        self.a2_cropButton.setEnabled(False)
        v.addWidget(_row(_field("ROI type", self.a2_roiTypeCombo),
                         self.a2_drawRoiCheckbox, self.a2_deleteRoiButton,
                         self.a2_cropButton))

        self.a2_odCheckbox = QCheckBox("Optical Density")
        self.a2_odCheckbox.setEnabled(False)
        self.a2_selectI0FromHistogramCheckbox = QCheckBox("Select I0 From Histogram")
        v.addWidget(_row(self.a2_odCheckbox, self.a2_selectI0FromHistogramCheckbox))

        # pre-edge normalization
        self.a2_preEdgeCheckbox = QCheckBox("Select Pre-Edge")
        self.a2_preEdgeCheckbox.setEnabled(False)
        self.a2_subtractPreEdgeButton = _small_btn("Subtract Pre-Edge")
        self.a2_subtractPreEdgeButton.setEnabled(False)
        self.a2_detrendButton = _small_btn("Detrend")
        self.a2_detrendButton.setEnabled(False)
        v.addWidget(_row(self.a2_preEdgeCheckbox, self.a2_subtractPreEdgeButton,
                         self.a2_detrendButton))

        v.addWidget(_hline())

        self.a2_trackMouseCheckbox = QCheckBox("Track Mouse")
        # Default ON (matches the classic UI): hovering the image plots the pixel
        # spectrum, which also auto-ranges the spectrum plot to the real energy
        # domain so hovering the plot seeks the image to the nearest energy.
        self.a2_trackMouseCheckbox.setChecked(True)
        self.a2_liveDisplayCheckbox = QCheckBox("Live Display")
        v.addWidget(_row(self.a2_trackMouseCheckbox, self.a2_liveDisplayCheckbox))

        v.addStretch(1)
        return page

    def _tab_filtering(self):
        page, v = self._page()
        page.setObjectName("a2_tab_filtering")
        self.a2_tab_filtering = page

        self.a2_darkLevelEdit = _edit("0", width=90)
        self.a2_subtractDarkButton = _small_btn("Subtract Dark Level")
        self.a2_filterUndoButton = _small_btn("Undo")
        v.addWidget(_row(_field("Dark level", self.a2_darkLevelEdit),
                         self.a2_subtractDarkButton, self.a2_filterUndoButton,
                         pad=True, valign=Qt.AlignBottom))

        self.a2_medianKernelEdit = _edit("5", width=90)
        self.a2_medianFilterButton = _small_btn("Median Filter")
        v.addWidget(_row(_field("Median kernel", self.a2_medianKernelEdit),
                         self.a2_medianFilterButton, pad=True,
                         valign=Qt.AlignBottom))

        self.a2_despikeKernelEdit = _edit("3", width=90)
        self.a2_despikeNSigmaEdit = _edit("5", width=90)
        self.a2_despikeButton = _small_btn("Despike")
        v.addWidget(_row(_field("Despike kernel", self.a2_despikeKernelEdit),
                         _field("N sigma", self.a2_despikeNSigmaEdit),
                         self.a2_despikeButton, pad=True, valign=Qt.AlignBottom))
        v.addStretch(1)
        return page

    def _tab_registration(self):
        page, v = self._page()
        page.setObjectName("a2_tab_registration")
        self.a2_tab_registration = page

        self.a2_regImageTypeCombo = _combo(["Transmission", "Optical Density"])
        self.a2_regImageTypeCombo.setEnabled(False)
        self.a2_regModeCombo = _combo(
            ["Translation", "Circular Image", "Affine", "Rigid", "Homographic"])
        self.a2_regAlignMethodCombo = _combo(["Sequential", "Reference Image"])
        v.addWidget(_row(_field("Image type", self.a2_regImageTypeCombo),
                         _field("Mode", self.a2_regModeCombo),
                         _field("Align to", self.a2_regAlignMethodCombo)))

        self.a2_regThresholdCheckbox = QCheckBox("Thresholded")
        self.a2_regThresholdEdit = _edit("0", width=90)
        v.addWidget(_row(self.a2_regThresholdCheckbox,
                         _field("Threshold", self.a2_regThresholdEdit),
                         pad=True, valign=Qt.AlignBottom))

        self.a2_regSobelCheckbox = QCheckBox("Sobel Filter")
        self.a2_regAutocropCheckbox = QCheckBox("Autocrop")
        v.addWidget(_row(self.a2_regSobelCheckbox, self.a2_regAutocropCheckbox))

        self.a2_regStartButton = _primary_btn("Start")
        self.a2_regUndoButton = _small_btn("Undo")
        v.addWidget(_row(self.a2_regStartButton, self.a2_regUndoButton,
                         stretch_last=False))

        # Progress reports through the shared footer bar (aliased in setupUi).
        v.addStretch(1)
        return page

    def _tab_pca(self):
        page, v = self._page()
        page.setObjectName("a2_tab_clustering")
        self.a2_tab_clustering = page

        self.a2_nComponentsEdit = _edit("4", width=90)
        self.a2_nClustersEdit = _edit("4", width=90)
        v.addWidget(_row(_field("N components", self.a2_nComponentsEdit),
                         _field("N clusters", self.a2_nClustersEdit)))

        self.a2_reduceMassCheckbox = QCheckBox("Reduce Mass Effects")
        self.a2_removePreEdgeCheckbox = QCheckBox("Remove Pre-Edge")
        self.a2_pcaMaskI0Checkbox = QCheckBox("Mask I0 Region")
        self.a2_pcaMaskI0Checkbox.setEnabled(False)
        v.addWidget(_row(self.a2_reduceMassCheckbox, self.a2_removePreEdgeCheckbox))
        v.addWidget(self.a2_pcaMaskI0Checkbox)

        # a2_calc_pca_layout: base inserts the "Add to Log" button at index 1,
        # so a2_calcPCAButton must sit at index 0.
        self.a2_calcPCAButton = _primary_btn("Calculate PCA")
        self.a2_calc_pca_layout = QHBoxLayout()
        self.a2_calc_pca_layout.setContentsMargins(0, 0, 0, 0)
        self.a2_calc_pca_layout.setSpacing(8)
        self.a2_calc_pca_layout.addWidget(self.a2_calcPCAButton)
        v.addLayout(self.a2_calc_pca_layout)

        self.a2_clusterImageCombo = _combo(
            ["Transmission", "Optical Density", "Principal Components",
             "Clusters", "RGB Map"])
        self.a2_clusterImageCombo.setEnabled(False)
        self.a2_clusterPlotCombo = _combo(
            ["ROI Spectra", "Cluster Spectra", "PCA Eigenvalues"])
        self.a2_clusterPlotCombo.setEnabled(False)
        v.addWidget(_row(_field("Display", self.a2_clusterImageCombo),
                         _field("Plot", self.a2_clusterPlotCombo)))

        self.a2_targetSpectraEdit = _edit("1,2,3", width=120)
        self.a2_calcRGBMapButton = _small_btn("RGB Map")
        v.addWidget(_row(_field("Target spectra", self.a2_targetSpectraEdit),
                         self.a2_calcRGBMapButton))
        v.addStretch(1)
        return page

    def _tab_nmf(self):
        page, v = self._page()
        page.setObjectName("a2_tab_nnmf")
        self.a2_tab_nnmf = page

        self.a2_nmfNComponentsEdit = _edit("4", width=90)
        self.a2_nmfNClustersEdit = _edit("4", width=90)
        self.a2_nmfMaxIterEdit = _edit("500", width=90)
        v.addWidget(_row(_field("N components", self.a2_nmfNComponentsEdit),
                         _field("N clusters", self.a2_nmfNClustersEdit),
                         _field("Max iter", self.a2_nmfMaxIterEdit)))

        self.a2_nmfInitCombo = _combo(["NNDSVDA", "Random"])
        self.a2_nmfMaskI0Checkbox = QCheckBox("Mask I0 Region")
        self.a2_nmfMaskI0Checkbox.setEnabled(False)
        v.addWidget(_row(_field("Init", self.a2_nmfInitCombo),
                         self.a2_nmfMaskI0Checkbox))

        self.a2_calcNMFButton = _primary_btn("Calculate NMF")
        self.a2_nmf_calc_layout = QHBoxLayout()
        self.a2_nmf_calc_layout.setContentsMargins(0, 0, 0, 0)
        self.a2_nmf_calc_layout.setSpacing(8)
        self.a2_nmf_calc_layout.addWidget(self.a2_calcNMFButton)
        v.addLayout(self.a2_nmf_calc_layout)

        self.a2_nmfDisplayCombo = _combo(["NMF Components", "Cluster Map", "RGB Map"])
        self.a2_nmfDisplayCombo.setEnabled(False)
        self.a2_nmfPlotCombo = _combo(["Component Spectra", "Cluster Spectra"])
        self.a2_nmfPlotCombo.setEnabled(False)
        v.addWidget(_row(_field("Display", self.a2_nmfDisplayCombo),
                         _field("Plot", self.a2_nmfPlotCombo)))

        self.a2_nmfTargetSpectraEdit = _edit("1,2,3", width=120)
        self.a2_nmfCalcRGBMapButton = _small_btn("RGB Map")
        v.addWidget(_row(_field("Target spectra", self.a2_nmfTargetSpectraEdit),
                         self.a2_nmfCalcRGBMapButton))

        # Progress reports through the shared footer bar (aliased in setupUi).
        v.addStretch(1)
        return page

    def _tab_line(self):
        # The base's ``_initialize_ls_tab`` builds the Line-Spectrum toolbar into
        # ``a2_tab_metadata_layout`` and adds a stretch; we just provide the page
        # (objectName ``a2_tab_metadata``) and its layout.
        page = QWidget()
        page.setObjectName("a2_tab_metadata")
        self.a2_tab_metadata = page
        self.a2_tab_metadata_layout = QVBoxLayout(page)
        self.a2_tab_metadata_layout.setContentsMargins(14, 14, 14, 14)
        self.a2_tab_metadata_layout.setSpacing(10)
        return page

    # ── column 2: viewer ─────────────────────────────────────────────────────
    def _viewer_col(self):
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # toolbar: filename + subline + colormap pills
        tb = QFrame()
        tb.setObjectName("cardHeader")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(14)
        self.a2_fnLabel = _mk_label("—", role="value")
        self.a2_fnLabel.setFont(mono_font(15, QFont.DemiBold))
        tl.addWidget(self.a2_fnLabel)
        self.a2_subLabel = _mk_label("", font=sans_font(10), color=C["text_dim"])
        tl.addWidget(self.a2_subLabel)
        tl.addStretch(1)
        tl.addWidget(_cmap_control(self._apply_cmap))
        cl.addWidget(tb)

        # image view (col-major pinned)
        self.a2_imageView = _ColMajorImageView()
        cl.addWidget(self.a2_imageView, 1)

        # footer: progress + cursor toggles
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fv = QHBoxLayout(footer)
        fv.setContentsMargins(14, 10, 14, 10)
        fv.setSpacing(12)
        self.a2_progressBar = QProgressBar()
        self.a2_progressBar.setTextVisible(False)
        self.a2_progressBar.setFixedWidth(200)
        fv.addWidget(self.a2_progressBar)
        self.a2_progressPct = _mk_label("0%", role="monoFaint")
        self.a2_progressPct.setFixedWidth(40)
        self.a2_progressBar.valueChanged.connect(
            lambda v: self.a2_progressPct.setText(f"{int(v)}%"))
        fv.addWidget(self.a2_progressPct)
        fv.addStretch(1)
        # Delete Frame sits below the image, next to the progress readout.
        fv.addWidget(self.a2_deleteFrameButton)
        cl.addWidget(footer)
        return card

    def _apply_cmap(self, name):
        """Colormap pills → the ImageView histogram gradient LUT."""
        try:
            self.a2_imageView.ui.histogram.gradient.loadPreset(
                _PRESET.get(name, "grey"))
        except Exception:
            pass

    # ── column 3: info ───────────────────────────────────────────────────────
    def _info_col(self):
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        mcard, mbody = _mk_card("Info")
        self.a2_metadataText = QPlainTextEdit()
        self.a2_metadataText.setReadOnly(True)
        self.a2_metadataText.setPlaceholderText(
            "File and process metadata will appear here…")
        self.a2_metadataText.setFont(mono_font(11))
        self.a2_metadataText.setStyleSheet(
            f"QPlainTextEdit{{background:{C['well']};border:none;"
            f"color:{C['text_2']};padding:10px;}}")
        mbody.addWidget(self.a2_metadataText, 1)
        v.addWidget(mcard, 1)
        return col


# ════════════════════════════════════════════════════════════════════════════
#  Analysis App
# ════════════════════════════════════════════════════════════════════════════
class AnalysisApp(Analysis2Widget):
    """Standalone stack-analysis widget styled for the dashboard.

    Reuses every bit of ``Analysis2Widget`` logic; only the ``ui`` and the theme
    are dashboard-specific.

    Parameters
    ----------
    controller : MainController or None
        Optional; wired for live scan data (``live_data_ready``) when present.
    logbook_model : LogbookModel or None
        Shared logbook model for the various Add-to-Log actions.  Falls back to
        ``controller.logbook_model``.
    """

    # Local QSS for the workflow QTabWidget (the dashboard sheet doesn't cover
    # tabs) plus progress bars.
    _EXTRA_QSS = f"""
    QTabWidget::pane {{
        border: 1px solid {C['border']};
        border-radius: 6px;
        top: -1px;
        background: {C['panel']};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {C['text_muted']};
        border: none;
        border-bottom: 2px solid transparent;
        padding: 7px 12px;
        font-size: 12px;
        margin-right: 2px;
    }}
    QTabBar::tab:hover {{ color: {C['text']}; }}
    QTabBar::tab:selected {{
        color: #ffffff;
        border-bottom: 2px solid {C['accent']};
    }}
    QProgressBar {{
        background: {C['well']};
        border: 1px solid {C['border']};
        border-radius: 3px;
        height: 8px;
    }}
    QProgressBar::chunk {{ background: {C['accent']}; border-radius: 2px; }}
    """

    def __init__(self, controller=None, logbook_model=None, parent=None):
        # Deliberately bypass Analysis2Widget.__init__ (which builds the
        # generated UI + qdarktheme); reproduce its wiring with our dashboard UI.
        QtWidgets.QWidget.__init__(self, parent)
        self.controller = controller
        self.logbook_model = logbook_model or getattr(
            controller, "logbook_model", None)

        self.ui = _DashboardAnalysisUI()
        self.ui.setupUi(self)
        self._setup_connections()
        self._setup_scale_bar()
        self._initialize_analysis2()

        if controller is not None and hasattr(controller, "live_data_ready"):
            self.connect_controller(controller)

        self.setStyleSheet(build_stylesheet() + self._EXTRA_QSS)
        # Recolour the spectrum plot for the dark dashboard palette.
        self._apply_a2_spectrum_theme(light=False)

    # ── theme overrides (dashboard palette, not qdarktheme) ──────────────────
    def set_light_theme(self):
        self._apply_a2_spectrum_theme(light=False)

    def set_dark_theme(self):
        self._apply_a2_spectrum_theme(light=False)

    def _apply_a2_spectrum_theme(self, light: bool):
        """Style the spectrum plot with the dashboard palette (always dark)."""
        plot = self.ui.a2_spectrumPlot
        pi = plot.getPlotItem()
        plot.setBackground(C["plot_ground"])
        axis_pen = pg.mkPen(C["border"])
        text_pen = pg.mkPen(C["text_faint"])
        for axis in ("left", "bottom", "top", "right"):
            pi.getAxis(axis).setPen(axis_pen)
            pi.getAxis(axis).setTextPen(text_pen)
        # The hover-spectrum curve is created black by the base; make it visible
        # on the dark ground.
        if hasattr(self, "_a2_spec_curve"):
            self._a2_spec_curve.setPen(pg.mkPen(C["text_2"], width=1))

    # ── overrides for embed-time axis-order safety ───────────────────────────
    def _a2_update_i0_mask_overlay(self):
        """The histogram-I0 mask overlay is a bare ImageItem created inside the
        base method; it reads the *global* axis order at construction.  Force
        col-major around the call so the overlay aligns with our col-major main
        image even when embedded under the dashboard's global row-major."""
        prev = pg.getConfigOption("imageAxisOrder")
        pg.setConfigOption("imageAxisOrder", _COL_MAJOR)
        try:
            super()._a2_update_i0_mask_overlay()
        finally:
            pg.setConfigOption("imageAxisOrder", prev)

    # ── viewer toolbar labels (mirror the file/energy readout) ───────────────
    def _on_a2_stack_loaded(self):
        super()._on_a2_stack_loaded()
        self._update_viewer_header()

    def _on_a2_frame_changed(self, index, time):
        super()._on_a2_frame_changed(index, time)
        self._update_viewer_header(index)

    def _update_viewer_header(self, index=None):
        sv = self.ui.a2_stack_viewer
        if not getattr(sv, "haveStack", False):
            return
        try:
            energies = sv.stack.energies
            n = len(energies)
            idx = self.ui.a2_imageView.currentIndex if index is None else index
            idx = max(0, min(int(idx), n - 1))
            fname = os.path.basename(sv.stack_file or getattr(sv.stack, "fileName", "") or "—")
            self.ui.a2_fnLabel.setText(fname)
            self.ui.a2_subLabel.setText(
                f"Energy {idx + 1} of {n} · {energies[idx]:.2f} eV")
        except Exception:
            pass


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
    app.setApplicationName("STXM Control — Analysis")
    w = AnalysisApp()
    w.setWindowTitle("STXM Analysis")
    w.resize(1900, 1100)
    w.show()
    # Optional: open a file passed on the command line.
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        w.load_file(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

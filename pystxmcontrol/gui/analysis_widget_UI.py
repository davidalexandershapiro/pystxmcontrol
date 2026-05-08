# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'analysis_widget.ui'
##
## Created by: Qt User Interface Compiler version 6.8.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QSizePolicy, QSpacerItem, QSplitter,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from pyqtgraph import (ImageView, PlotWidget)
from pystxmcontrol.gui.stackviewerwidget import stackViewerWidget

class Ui_Analysis2Widget(object):
    def setupUi(self, Analysis2Widget):
        if not Analysis2Widget.objectName():
            Analysis2Widget.setObjectName(u"Analysis2Widget")
        self.a2_layout = QVBoxLayout(Analysis2Widget)
        self.a2_layout.setSpacing(2)
        self.a2_layout.setObjectName(u"a2_layout")
        self.a2_layout.setContentsMargins(0, 0, 0, 0)
        self.a2_stack_viewer = stackViewerWidget(Analysis2Widget)
        self.a2_stack_viewer.setObjectName(u"a2_stack_viewer")
        self.a2_stack_viewer.setVisible(False)

        self.a2_layout.addWidget(self.a2_stack_viewer)

        self.a2_topSplitter = QSplitter(Analysis2Widget)
        self.a2_topSplitter.setObjectName(u"a2_topSplitter")
        self.a2_topSplitter.setOrientation(Qt.Horizontal)
        self.a2_rightPane = QWidget(self.a2_topSplitter)
        self.a2_rightPane.setObjectName(u"a2_rightPane")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.a2_rightPane.sizePolicy().hasHeightForWidth())
        self.a2_rightPane.setSizePolicy(sizePolicy)
        self.a2_rightPane_layout = QVBoxLayout(self.a2_rightPane)
        self.a2_rightPane_layout.setSpacing(4)
        self.a2_rightPane_layout.setObjectName(u"a2_rightPane_layout")
        self.a2_rightPane_layout.setContentsMargins(0, 0, 0, 0)
        self.a2_spectrumPlot = PlotWidget(self.a2_rightPane)
        self.a2_spectrumPlot.setObjectName(u"a2_spectrumPlot")

        self.a2_rightPane_layout.addWidget(self.a2_spectrumPlot)

        self.a2_workflowTabs = QTabWidget(self.a2_rightPane)
        self.a2_workflowTabs.setObjectName(u"a2_workflowTabs")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.a2_workflowTabs.sizePolicy().hasHeightForWidth())
        self.a2_workflowTabs.setSizePolicy(sizePolicy1)
        self.a2_workflowTabs.setMinimumSize(QSize(0, 600))
        self.a2_tab_main = QWidget()
        self.a2_tab_main.setObjectName(u"a2_tab_main")
        self.a2_tab_main_layout = QVBoxLayout(self.a2_tab_main)
        self.a2_tab_main_layout.setSpacing(6)
        self.a2_tab_main_layout.setObjectName(u"a2_tab_main_layout")
        self.a2_tab_main_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_main_buttons_layout = QHBoxLayout()
        self.a2_main_buttons_layout.setObjectName(u"a2_main_buttons_layout")
        self.a2_openStackButton = QPushButton(self.a2_tab_main)
        self.a2_openStackButton.setObjectName(u"a2_openStackButton")

        self.a2_main_buttons_layout.addWidget(self.a2_openStackButton)

        self.a2_saveDataButton = QPushButton(self.a2_tab_main)
        self.a2_saveDataButton.setObjectName(u"a2_saveDataButton")

        self.a2_main_buttons_layout.addWidget(self.a2_saveDataButton)

        self.a2_addToLogButton = QPushButton(self.a2_tab_main)
        self.a2_addToLogButton.setObjectName(u"a2_addToLogButton")

        self.a2_main_buttons_layout.addWidget(self.a2_addToLogButton)

        self.a2_savePngButton = QPushButton(self.a2_tab_main)
        self.a2_savePngButton.setObjectName(u"a2_savePngButton")

        self.a2_main_buttons_layout.addWidget(self.a2_savePngButton)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_main_buttons_layout.addItem(self.horizontalSpacer_2)


        self.a2_tab_main_layout.addLayout(self.a2_main_buttons_layout)

        self.a2_roi_separator = QFrame(self.a2_tab_main)
        self.a2_roi_separator.setObjectName(u"a2_roi_separator")
        self.a2_roi_separator.setFrameShape(QFrame.HLine)
        self.a2_roi_separator.setFrameShadow(QFrame.Sunken)

        self.a2_tab_main_layout.addWidget(self.a2_roi_separator)

        self.a2_roi_type_layout = QHBoxLayout()
        self.a2_roi_type_layout.setObjectName(u"a2_roi_type_layout")
        self.a2_roiTypeLabel = QLabel(self.a2_tab_main)
        self.a2_roiTypeLabel.setObjectName(u"a2_roiTypeLabel")

        self.a2_roi_type_layout.addWidget(self.a2_roiTypeLabel)

        self.a2_roiTypeCombo = QComboBox(self.a2_tab_main)
        self.a2_roiTypeCombo.addItem("")
        self.a2_roiTypeCombo.addItem("")
        self.a2_roiTypeCombo.addItem("")
        self.a2_roiTypeCombo.setObjectName(u"a2_roiTypeCombo")

        self.a2_roi_type_layout.addWidget(self.a2_roiTypeCombo)

        self.a2_drawRoiCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_drawRoiCheckbox.setObjectName(u"a2_drawRoiCheckbox")

        self.a2_roi_type_layout.addWidget(self.a2_drawRoiCheckbox)

        self.a2_deleteRoiButton = QPushButton(self.a2_tab_main)
        self.a2_deleteRoiButton.setObjectName(u"a2_deleteRoiButton")

        self.a2_roi_type_layout.addWidget(self.a2_deleteRoiButton)

        self.a2_deleteFrameButton = QPushButton(self.a2_tab_main)
        self.a2_deleteFrameButton.setObjectName(u"a2_deleteFrameButton")

        self.a2_roi_type_layout.addWidget(self.a2_deleteFrameButton)

        self.a2_cropButton = QPushButton(self.a2_tab_main)
        self.a2_cropButton.setObjectName(u"a2_cropButton")
        self.a2_cropButton.setEnabled(False)

        self.a2_roi_type_layout.addWidget(self.a2_cropButton)

        self.a2_roi_type_hSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_roi_type_layout.addItem(self.a2_roi_type_hSpacer)


        self.a2_tab_main_layout.addLayout(self.a2_roi_type_layout)

        self.a2_roi_draw_layout = QHBoxLayout()
        self.a2_roi_draw_layout.setObjectName(u"a2_roi_draw_layout")
        self.a2_odCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_odCheckbox.setObjectName(u"a2_odCheckbox")
        self.a2_odCheckbox.setEnabled(False)

        self.a2_roi_draw_layout.addWidget(self.a2_odCheckbox)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_roi_draw_layout.addItem(self.horizontalSpacer)


        self.a2_tab_main_layout.addLayout(self.a2_roi_draw_layout)

        self.a2_norm_separator = QFrame(self.a2_tab_main)
        self.a2_norm_separator.setObjectName(u"a2_norm_separator")
        self.a2_norm_separator.setFrameShape(QFrame.HLine)
        self.a2_norm_separator.setFrameShadow(QFrame.Sunken)

        self.a2_tab_main_layout.addWidget(self.a2_norm_separator)

        self.a2_edge_select_layout = QHBoxLayout()
        self.a2_edge_select_layout.setObjectName(u"a2_edge_select_layout")
        self.a2_autoProcessButton = QPushButton(self.a2_tab_main)
        self.a2_autoProcessButton.setObjectName(u"a2_autoProcessButton")

        self.a2_edge_select_layout.addWidget(self.a2_autoProcessButton)

        self.a2_mapButton = QPushButton(self.a2_tab_main)
        self.a2_mapButton.setObjectName(u"a2_mapButton")
        self.a2_mapButton.setEnabled(False)

        self.a2_edge_select_layout.addWidget(self.a2_mapButton)

        self.a2_resetButton = QPushButton(self.a2_tab_main)
        self.a2_resetButton.setObjectName(u"a2_resetButton")

        self.a2_edge_select_layout.addWidget(self.a2_resetButton)


        self.a2_tab_main_layout.addLayout(self.a2_edge_select_layout)

        self.a2_norm_buttons_layout = QHBoxLayout()
        self.a2_norm_buttons_layout.setObjectName(u"a2_norm_buttons_layout")
        self.a2_norm_buttons_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_norm_buttons_layout.addItem(self.a2_norm_buttons_spacer)


        self.a2_tab_main_layout.addLayout(self.a2_norm_buttons_layout)

        self.a2_process_buttons_layout = QHBoxLayout()
        self.a2_process_buttons_layout.setObjectName(u"a2_process_buttons_layout")
        self.a2_preEdgeCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_preEdgeCheckbox.setObjectName(u"a2_preEdgeCheckbox")

        self.a2_process_buttons_layout.addWidget(self.a2_preEdgeCheckbox)

        self.a2_subtractPreEdgeButton = QPushButton(self.a2_tab_main)
        self.a2_subtractPreEdgeButton.setObjectName(u"a2_subtractPreEdgeButton")
        self.a2_subtractPreEdgeButton.setEnabled(False)

        self.a2_process_buttons_layout.addWidget(self.a2_subtractPreEdgeButton)

        self.a2_detrendButton = QPushButton(self.a2_tab_main)
        self.a2_detrendButton.setObjectName(u"a2_detrendButton")
        self.a2_detrendButton.setEnabled(False)

        self.a2_process_buttons_layout.addWidget(self.a2_detrendButton)

        self.a2_selectI0FromHistogramCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_selectI0FromHistogramCheckbox.setObjectName(u"a2_selectI0FromHistogramCheckbox")
        self.a2_selectI0FromHistogramCheckbox.setEnabled(False)

        self.a2_process_buttons_layout.addWidget(self.a2_selectI0FromHistogramCheckbox)


        self.a2_tab_main_layout.addLayout(self.a2_process_buttons_layout)

        self.a2_progressBar = QProgressBar(self.a2_tab_main)
        self.a2_progressBar.setObjectName(u"a2_progressBar")
        self.a2_progressBar.setValue(0)
        self.a2_progressBar.setTextVisible(True)

        self.a2_tab_main_layout.addWidget(self.a2_progressBar)

        self.a2_trackMouseCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_trackMouseCheckbox.setObjectName(u"a2_trackMouseCheckbox")
        self.a2_trackMouseCheckbox.setChecked(True)

        self.a2_tab_main_layout.addWidget(self.a2_trackMouseCheckbox)

        self.a2_liveDisplayCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_liveDisplayCheckbox.setObjectName(u"a2_liveDisplayCheckbox")

        self.a2_tab_main_layout.addWidget(self.a2_liveDisplayCheckbox)

        self.a2_main_vSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_main_layout.addItem(self.a2_main_vSpacer)

        self.a2_workflowTabs.addTab(self.a2_tab_main, "")
        self.a2_tab_filtering = QWidget()
        self.a2_tab_filtering.setObjectName(u"a2_tab_filtering")
        self.a2_tab_filtering_layout = QVBoxLayout(self.a2_tab_filtering)
        self.a2_tab_filtering_layout.setSpacing(6)
        self.a2_tab_filtering_layout.setObjectName(u"a2_tab_filtering_layout")
        self.a2_tab_filtering_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_subtract_dark_layout = QHBoxLayout()
        self.a2_subtract_dark_layout.setObjectName(u"a2_subtract_dark_layout")
        self.a2_darkLevelLabel = QLabel(self.a2_tab_filtering)
        self.a2_darkLevelLabel.setObjectName(u"a2_darkLevelLabel")

        self.a2_subtract_dark_layout.addWidget(self.a2_darkLevelLabel)

        self.a2_darkLevelEdit = QLineEdit(self.a2_tab_filtering)
        self.a2_darkLevelEdit.setObjectName(u"a2_darkLevelEdit")

        self.a2_subtract_dark_layout.addWidget(self.a2_darkLevelEdit)

        self.a2_subtractDarkButton = QPushButton(self.a2_tab_filtering)
        self.a2_subtractDarkButton.setObjectName(u"a2_subtractDarkButton")

        self.a2_subtract_dark_layout.addWidget(self.a2_subtractDarkButton)


        self.a2_tab_filtering_layout.addLayout(self.a2_subtract_dark_layout)

        self.a2_undo_row_layout = QHBoxLayout()
        self.a2_undo_row_layout.setObjectName(u"a2_undo_row_layout")
        self.a2_undo_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_undo_row_layout.addItem(self.a2_undo_spacer)

        self.a2_filterUndoButton = QPushButton(self.a2_tab_filtering)
        self.a2_filterUndoButton.setObjectName(u"a2_filterUndoButton")

        self.a2_undo_row_layout.addWidget(self.a2_filterUndoButton)


        self.a2_tab_filtering_layout.addLayout(self.a2_undo_row_layout)

        self.a2_filter_line1 = QFrame(self.a2_tab_filtering)
        self.a2_filter_line1.setObjectName(u"a2_filter_line1")
        self.a2_filter_line1.setFrameShape(QFrame.Shape.HLine)
        self.a2_filter_line1.setFrameShadow(QFrame.Shadow.Sunken)

        self.a2_tab_filtering_layout.addWidget(self.a2_filter_line1)

        self.a2_median_filter_layout = QHBoxLayout()
        self.a2_median_filter_layout.setObjectName(u"a2_median_filter_layout")
        self.a2_medianKernelLabel = QLabel(self.a2_tab_filtering)
        self.a2_medianKernelLabel.setObjectName(u"a2_medianKernelLabel")

        self.a2_median_filter_layout.addWidget(self.a2_medianKernelLabel)

        self.a2_medianKernelEdit = QLineEdit(self.a2_tab_filtering)
        self.a2_medianKernelEdit.setObjectName(u"a2_medianKernelEdit")

        self.a2_median_filter_layout.addWidget(self.a2_medianKernelEdit)

        self.a2_medianFilterButton = QPushButton(self.a2_tab_filtering)
        self.a2_medianFilterButton.setObjectName(u"a2_medianFilterButton")

        self.a2_median_filter_layout.addWidget(self.a2_medianFilterButton)


        self.a2_tab_filtering_layout.addLayout(self.a2_median_filter_layout)

        self.a2_filter_line2 = QFrame(self.a2_tab_filtering)
        self.a2_filter_line2.setObjectName(u"a2_filter_line2")
        self.a2_filter_line2.setFrameShape(QFrame.Shape.HLine)
        self.a2_filter_line2.setFrameShadow(QFrame.Shadow.Sunken)

        self.a2_tab_filtering_layout.addWidget(self.a2_filter_line2)

        self.a2_despike_layout = QHBoxLayout()
        self.a2_despike_layout.setObjectName(u"a2_despike_layout")
        self.a2_despikeKernelLabel = QLabel(self.a2_tab_filtering)
        self.a2_despikeKernelLabel.setObjectName(u"a2_despikeKernelLabel")

        self.a2_despike_layout.addWidget(self.a2_despikeKernelLabel)

        self.a2_despikeKernelEdit = QLineEdit(self.a2_tab_filtering)
        self.a2_despikeKernelEdit.setObjectName(u"a2_despikeKernelEdit")

        self.a2_despike_layout.addWidget(self.a2_despikeKernelEdit)

        self.a2_despikeNSigmaLabel = QLabel(self.a2_tab_filtering)
        self.a2_despikeNSigmaLabel.setObjectName(u"a2_despikeNSigmaLabel")

        self.a2_despike_layout.addWidget(self.a2_despikeNSigmaLabel)

        self.a2_despikeNSigmaEdit = QLineEdit(self.a2_tab_filtering)
        self.a2_despikeNSigmaEdit.setObjectName(u"a2_despikeNSigmaEdit")

        self.a2_despike_layout.addWidget(self.a2_despikeNSigmaEdit)

        self.a2_despikeButton = QPushButton(self.a2_tab_filtering)
        self.a2_despikeButton.setObjectName(u"a2_despikeButton")

        self.a2_despike_layout.addWidget(self.a2_despikeButton)


        self.a2_tab_filtering_layout.addLayout(self.a2_despike_layout)

        self.a2_filter_vspacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_filtering_layout.addItem(self.a2_filter_vspacer)

        self.a2_workflowTabs.addTab(self.a2_tab_filtering, "")
        self.a2_tab_registration = QWidget()
        self.a2_tab_registration.setObjectName(u"a2_tab_registration")
        self.a2_tab_registration_layout = QVBoxLayout(self.a2_tab_registration)
        self.a2_tab_registration_layout.setSpacing(6)
        self.a2_tab_registration_layout.setObjectName(u"a2_tab_registration_layout")
        self.a2_tab_registration_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_reg_image_type_layout = QHBoxLayout()
        self.a2_reg_image_type_layout.setObjectName(u"a2_reg_image_type_layout")
        self.a2_regImageTypeLabel = QLabel(self.a2_tab_registration)
        self.a2_regImageTypeLabel.setObjectName(u"a2_regImageTypeLabel")

        self.a2_reg_image_type_layout.addWidget(self.a2_regImageTypeLabel)

        self.a2_regImageTypeCombo = QComboBox(self.a2_tab_registration)
        self.a2_regImageTypeCombo.addItem("")
        self.a2_regImageTypeCombo.addItem("")
        self.a2_regImageTypeCombo.setObjectName(u"a2_regImageTypeCombo")
        self.a2_regImageTypeCombo.setEnabled(False)

        self.a2_reg_image_type_layout.addWidget(self.a2_regImageTypeCombo)

        self.a2_reg_image_type_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_image_type_layout.addItem(self.a2_reg_image_type_spacer)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_image_type_layout)

        self.a2_reg_mode_layout = QHBoxLayout()
        self.a2_reg_mode_layout.setObjectName(u"a2_reg_mode_layout")
        self.a2_regModeLabel = QLabel(self.a2_tab_registration)
        self.a2_regModeLabel.setObjectName(u"a2_regModeLabel")

        self.a2_reg_mode_layout.addWidget(self.a2_regModeLabel)

        self.a2_regModeCombo = QComboBox(self.a2_tab_registration)
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.setObjectName(u"a2_regModeCombo")

        self.a2_reg_mode_layout.addWidget(self.a2_regModeCombo)

        self.horizontalSpacer_3 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_mode_layout.addItem(self.horizontalSpacer_3)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_mode_layout)

        self.a2_reg_align_method_layout = QHBoxLayout()
        self.a2_reg_align_method_layout.setObjectName(u"a2_reg_align_method_layout")
        self.a2_regAlignMethodLabel = QLabel(self.a2_tab_registration)
        self.a2_regAlignMethodLabel.setObjectName(u"a2_regAlignMethodLabel")

        self.a2_reg_align_method_layout.addWidget(self.a2_regAlignMethodLabel)

        self.a2_regAlignMethodCombo = QComboBox(self.a2_tab_registration)
        self.a2_regAlignMethodCombo.addItem("")
        self.a2_regAlignMethodCombo.addItem("")
        self.a2_regAlignMethodCombo.setObjectName(u"a2_regAlignMethodCombo")

        self.a2_reg_align_method_layout.addWidget(self.a2_regAlignMethodCombo)

        self.a2_reg_align_method_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_align_method_layout.addItem(self.a2_reg_align_method_spacer)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_align_method_layout)

        self.a2_reg_threshold_layout = QHBoxLayout()
        self.a2_reg_threshold_layout.setObjectName(u"a2_reg_threshold_layout")
        self.a2_regThresholdCheckbox = QCheckBox(self.a2_tab_registration)
        self.a2_regThresholdCheckbox.setObjectName(u"a2_regThresholdCheckbox")

        self.a2_reg_threshold_layout.addWidget(self.a2_regThresholdCheckbox)

        self.a2_regThresholdLabel = QLabel(self.a2_tab_registration)
        self.a2_regThresholdLabel.setObjectName(u"a2_regThresholdLabel")

        self.a2_reg_threshold_layout.addWidget(self.a2_regThresholdLabel)

        self.a2_regThresholdEdit = QLineEdit(self.a2_tab_registration)
        self.a2_regThresholdEdit.setObjectName(u"a2_regThresholdEdit")
        self.a2_regThresholdEdit.setMaximumWidth(70)

        self.a2_reg_threshold_layout.addWidget(self.a2_regThresholdEdit)

        self.a2_reg_threshold_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_threshold_layout.addItem(self.a2_reg_threshold_spacer)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_threshold_layout)

        self.a2_reg_options_layout = QHBoxLayout()
        self.a2_reg_options_layout.setObjectName(u"a2_reg_options_layout")
        self.a2_regSobelCheckbox = QCheckBox(self.a2_tab_registration)
        self.a2_regSobelCheckbox.setObjectName(u"a2_regSobelCheckbox")

        self.a2_reg_options_layout.addWidget(self.a2_regSobelCheckbox)

        self.a2_regAutocropCheckbox = QCheckBox(self.a2_tab_registration)
        self.a2_regAutocropCheckbox.setObjectName(u"a2_regAutocropCheckbox")
        self.a2_regAutocropCheckbox.setChecked(True)

        self.a2_reg_options_layout.addWidget(self.a2_regAutocropCheckbox)

        self.a2_reg_options_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_options_layout.addItem(self.a2_reg_options_spacer)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_options_layout)

        self.a2_reg_buttons_layout = QHBoxLayout()
        self.a2_reg_buttons_layout.setObjectName(u"a2_reg_buttons_layout")
        self.a2_regStartButton = QPushButton(self.a2_tab_registration)
        self.a2_regStartButton.setObjectName(u"a2_regStartButton")

        self.a2_reg_buttons_layout.addWidget(self.a2_regStartButton)

        self.a2_regUndoButton = QPushButton(self.a2_tab_registration)
        self.a2_regUndoButton.setObjectName(u"a2_regUndoButton")

        self.a2_reg_buttons_layout.addWidget(self.a2_regUndoButton)

        self.a2_reg_buttons_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_buttons_layout.addItem(self.a2_reg_buttons_spacer)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_buttons_layout)

        self.a2_regProgressBar = QProgressBar(self.a2_tab_registration)
        self.a2_regProgressBar.setObjectName(u"a2_regProgressBar")
        self.a2_regProgressBar.setValue(0)
        self.a2_regProgressBar.setTextVisible(True)

        self.a2_tab_registration_layout.addWidget(self.a2_regProgressBar)

        self.a2_reg_vspacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_registration_layout.addItem(self.a2_reg_vspacer)

        self.a2_workflowTabs.addTab(self.a2_tab_registration, "")
        self.a2_tab_clustering = QWidget()
        self.a2_tab_clustering.setObjectName(u"a2_tab_clustering")
        self.a2_tab_clustering_layout = QVBoxLayout(self.a2_tab_clustering)
        self.a2_tab_clustering_layout.setSpacing(6)
        self.a2_tab_clustering_layout.setObjectName(u"a2_tab_clustering_layout")
        self.a2_tab_clustering_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_pca_params_layout = QHBoxLayout()
        self.a2_pca_params_layout.setObjectName(u"a2_pca_params_layout")
        self.a2_nComponentsLabel = QLabel(self.a2_tab_clustering)
        self.a2_nComponentsLabel.setObjectName(u"a2_nComponentsLabel")

        self.a2_pca_params_layout.addWidget(self.a2_nComponentsLabel)

        self.a2_nComponentsEdit = QLineEdit(self.a2_tab_clustering)
        self.a2_nComponentsEdit.setObjectName(u"a2_nComponentsEdit")

        self.a2_pca_params_layout.addWidget(self.a2_nComponentsEdit)

        self.a2_nClustersLabel = QLabel(self.a2_tab_clustering)
        self.a2_nClustersLabel.setObjectName(u"a2_nClustersLabel")

        self.a2_pca_params_layout.addWidget(self.a2_nClustersLabel)

        self.a2_nClustersEdit = QLineEdit(self.a2_tab_clustering)
        self.a2_nClustersEdit.setObjectName(u"a2_nClustersEdit")

        self.a2_pca_params_layout.addWidget(self.a2_nClustersEdit)

        self.a2_pca_params_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_pca_params_layout.addItem(self.a2_pca_params_spacer)


        self.a2_tab_clustering_layout.addLayout(self.a2_pca_params_layout)

        self.a2_pca_options_layout = QHBoxLayout()
        self.a2_pca_options_layout.setObjectName(u"a2_pca_options_layout")
        self.a2_reduceMassCheckbox = QCheckBox(self.a2_tab_clustering)
        self.a2_reduceMassCheckbox.setObjectName(u"a2_reduceMassCheckbox")

        self.a2_pca_options_layout.addWidget(self.a2_reduceMassCheckbox)

        self.a2_removePreEdgeCheckbox = QCheckBox(self.a2_tab_clustering)
        self.a2_removePreEdgeCheckbox.setObjectName(u"a2_removePreEdgeCheckbox")

        self.a2_pca_options_layout.addWidget(self.a2_removePreEdgeCheckbox)

        self.a2_pca_options_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_pca_options_layout.addItem(self.a2_pca_options_spacer)


        self.a2_tab_clustering_layout.addLayout(self.a2_pca_options_layout)

        self.a2_pcaMaskI0Checkbox = QCheckBox(self.a2_tab_clustering)
        self.a2_pcaMaskI0Checkbox.setObjectName(u"a2_pcaMaskI0Checkbox")
        self.a2_pcaMaskI0Checkbox.setEnabled(False)

        self.a2_tab_clustering_layout.addWidget(self.a2_pcaMaskI0Checkbox)

        self.a2_calc_pca_layout = QHBoxLayout()
        self.a2_calc_pca_layout.setObjectName(u"a2_calc_pca_layout")
        self.a2_calcPCAButton = QPushButton(self.a2_tab_clustering)
        self.a2_calcPCAButton.setObjectName(u"a2_calcPCAButton")

        self.a2_calc_pca_layout.addWidget(self.a2_calcPCAButton)

        self.a2_calc_pca_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_calc_pca_layout.addItem(self.a2_calc_pca_spacer)


        self.a2_tab_clustering_layout.addLayout(self.a2_calc_pca_layout)

        self.a2_cluster_line1 = QFrame(self.a2_tab_clustering)
        self.a2_cluster_line1.setObjectName(u"a2_cluster_line1")
        self.a2_cluster_line1.setFrameShape(QFrame.Shape.HLine)
        self.a2_cluster_line1.setFrameShadow(QFrame.Shadow.Sunken)

        self.a2_tab_clustering_layout.addWidget(self.a2_cluster_line1)

        self.a2_cluster_image_layout = QHBoxLayout()
        self.a2_cluster_image_layout.setObjectName(u"a2_cluster_image_layout")
        self.a2_clusterImageLabel = QLabel(self.a2_tab_clustering)
        self.a2_clusterImageLabel.setObjectName(u"a2_clusterImageLabel")

        self.a2_cluster_image_layout.addWidget(self.a2_clusterImageLabel)

        self.a2_clusterImageCombo = QComboBox(self.a2_tab_clustering)
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.setObjectName(u"a2_clusterImageCombo")
        self.a2_clusterImageCombo.setEnabled(False)

        self.a2_cluster_image_layout.addWidget(self.a2_clusterImageCombo)


        self.a2_tab_clustering_layout.addLayout(self.a2_cluster_image_layout)

        self.a2_cluster_plot_layout = QHBoxLayout()
        self.a2_cluster_plot_layout.setObjectName(u"a2_cluster_plot_layout")
        self.a2_clusterPlotLabel = QLabel(self.a2_tab_clustering)
        self.a2_clusterPlotLabel.setObjectName(u"a2_clusterPlotLabel")

        self.a2_cluster_plot_layout.addWidget(self.a2_clusterPlotLabel)

        self.a2_clusterPlotCombo = QComboBox(self.a2_tab_clustering)
        self.a2_clusterPlotCombo.addItem("")
        self.a2_clusterPlotCombo.addItem("")
        self.a2_clusterPlotCombo.addItem("")
        self.a2_clusterPlotCombo.setObjectName(u"a2_clusterPlotCombo")
        self.a2_clusterPlotCombo.setEnabled(False)

        self.a2_cluster_plot_layout.addWidget(self.a2_clusterPlotCombo)


        self.a2_tab_clustering_layout.addLayout(self.a2_cluster_plot_layout)

        self.a2_rgb_map_layout = QHBoxLayout()
        self.a2_rgb_map_layout.setObjectName(u"a2_rgb_map_layout")
        self.a2_targetSpectraLabel = QLabel(self.a2_tab_clustering)
        self.a2_targetSpectraLabel.setObjectName(u"a2_targetSpectraLabel")

        self.a2_rgb_map_layout.addWidget(self.a2_targetSpectraLabel)

        self.a2_targetSpectraEdit = QLineEdit(self.a2_tab_clustering)
        self.a2_targetSpectraEdit.setObjectName(u"a2_targetSpectraEdit")

        self.a2_rgb_map_layout.addWidget(self.a2_targetSpectraEdit)

        self.a2_calcRGBMapButton = QPushButton(self.a2_tab_clustering)
        self.a2_calcRGBMapButton.setObjectName(u"a2_calcRGBMapButton")

        self.a2_rgb_map_layout.addWidget(self.a2_calcRGBMapButton)


        self.a2_tab_clustering_layout.addLayout(self.a2_rgb_map_layout)

        self.a2_cluster_vspacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_clustering_layout.addItem(self.a2_cluster_vspacer)

        self.a2_workflowTabs.addTab(self.a2_tab_clustering, "")
        self.a2_tab_nnmf = QWidget()
        self.a2_tab_nnmf.setObjectName(u"a2_tab_nnmf")
        self.a2_tab_nnmf_layout = QVBoxLayout(self.a2_tab_nnmf)
        self.a2_tab_nnmf_layout.setSpacing(6)
        self.a2_tab_nnmf_layout.setObjectName(u"a2_tab_nnmf_layout")
        self.a2_tab_nnmf_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_nmf_params1_layout = QHBoxLayout()
        self.a2_nmf_params1_layout.setObjectName(u"a2_nmf_params1_layout")
        self.a2_nmfNComponentsLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfNComponentsLabel.setObjectName(u"a2_nmfNComponentsLabel")

        self.a2_nmf_params1_layout.addWidget(self.a2_nmfNComponentsLabel)

        self.a2_nmfNComponentsEdit = QLineEdit(self.a2_tab_nnmf)
        self.a2_nmfNComponentsEdit.setObjectName(u"a2_nmfNComponentsEdit")

        self.a2_nmf_params1_layout.addWidget(self.a2_nmfNComponentsEdit)

        self.a2_nmfNClustersLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfNClustersLabel.setObjectName(u"a2_nmfNClustersLabel")

        self.a2_nmf_params1_layout.addWidget(self.a2_nmfNClustersLabel)

        self.a2_nmfNClustersEdit = QLineEdit(self.a2_tab_nnmf)
        self.a2_nmfNClustersEdit.setObjectName(u"a2_nmfNClustersEdit")

        self.a2_nmf_params1_layout.addWidget(self.a2_nmfNClustersEdit)

        self.a2_nmf_params1_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_nmf_params1_layout.addItem(self.a2_nmf_params1_spacer)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_params1_layout)

        self.a2_nmf_params2_layout = QHBoxLayout()
        self.a2_nmf_params2_layout.setObjectName(u"a2_nmf_params2_layout")
        self.a2_nmfMaxIterLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfMaxIterLabel.setObjectName(u"a2_nmfMaxIterLabel")

        self.a2_nmf_params2_layout.addWidget(self.a2_nmfMaxIterLabel)

        self.a2_nmfMaxIterEdit = QLineEdit(self.a2_tab_nnmf)
        self.a2_nmfMaxIterEdit.setObjectName(u"a2_nmfMaxIterEdit")

        self.a2_nmf_params2_layout.addWidget(self.a2_nmfMaxIterEdit)

        self.a2_nmfInitLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfInitLabel.setObjectName(u"a2_nmfInitLabel")

        self.a2_nmf_params2_layout.addWidget(self.a2_nmfInitLabel)

        self.a2_nmfInitCombo = QComboBox(self.a2_tab_nnmf)
        self.a2_nmfInitCombo.addItem("")
        self.a2_nmfInitCombo.addItem("")
        self.a2_nmfInitCombo.setObjectName(u"a2_nmfInitCombo")

        self.a2_nmf_params2_layout.addWidget(self.a2_nmfInitCombo)

        self.a2_nmf_params2_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_nmf_params2_layout.addItem(self.a2_nmf_params2_spacer)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_params2_layout)

        self.a2_nmfMaskI0Checkbox = QCheckBox(self.a2_tab_nnmf)
        self.a2_nmfMaskI0Checkbox.setObjectName(u"a2_nmfMaskI0Checkbox")
        self.a2_nmfMaskI0Checkbox.setEnabled(False)

        self.a2_tab_nnmf_layout.addWidget(self.a2_nmfMaskI0Checkbox)

        self.a2_nmf_calc_layout = QHBoxLayout()
        self.a2_nmf_calc_layout.setObjectName(u"a2_nmf_calc_layout")
        self.a2_calcNMFButton = QPushButton(self.a2_tab_nnmf)
        self.a2_calcNMFButton.setObjectName(u"a2_calcNMFButton")

        self.a2_nmf_calc_layout.addWidget(self.a2_calcNMFButton)

        self.a2_nmf_calc_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_nmf_calc_layout.addItem(self.a2_nmf_calc_spacer)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_calc_layout)

        self.a2_nmfProgressBar = QProgressBar(self.a2_tab_nnmf)
        self.a2_nmfProgressBar.setObjectName(u"a2_nmfProgressBar")
        self.a2_nmfProgressBar.setValue(0)

        self.a2_tab_nnmf_layout.addWidget(self.a2_nmfProgressBar)

        self.a2_nmf_line1 = QFrame(self.a2_tab_nnmf)
        self.a2_nmf_line1.setObjectName(u"a2_nmf_line1")
        self.a2_nmf_line1.setFrameShape(QFrame.Shape.HLine)
        self.a2_nmf_line1.setFrameShadow(QFrame.Shadow.Sunken)

        self.a2_tab_nnmf_layout.addWidget(self.a2_nmf_line1)

        self.a2_nmf_display_layout = QHBoxLayout()
        self.a2_nmf_display_layout.setObjectName(u"a2_nmf_display_layout")
        self.a2_nmfDisplayLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfDisplayLabel.setObjectName(u"a2_nmfDisplayLabel")

        self.a2_nmf_display_layout.addWidget(self.a2_nmfDisplayLabel)

        self.a2_nmfDisplayCombo = QComboBox(self.a2_tab_nnmf)
        self.a2_nmfDisplayCombo.addItem("")
        self.a2_nmfDisplayCombo.addItem("")
        self.a2_nmfDisplayCombo.addItem("")
        self.a2_nmfDisplayCombo.setObjectName(u"a2_nmfDisplayCombo")
        self.a2_nmfDisplayCombo.setEnabled(False)

        self.a2_nmf_display_layout.addWidget(self.a2_nmfDisplayCombo)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_display_layout)

        self.a2_nmf_plot_layout = QHBoxLayout()
        self.a2_nmf_plot_layout.setObjectName(u"a2_nmf_plot_layout")
        self.a2_nmfPlotLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfPlotLabel.setObjectName(u"a2_nmfPlotLabel")

        self.a2_nmf_plot_layout.addWidget(self.a2_nmfPlotLabel)

        self.a2_nmfPlotCombo = QComboBox(self.a2_tab_nnmf)
        self.a2_nmfPlotCombo.addItem("")
        self.a2_nmfPlotCombo.addItem("")
        self.a2_nmfPlotCombo.setObjectName(u"a2_nmfPlotCombo")
        self.a2_nmfPlotCombo.setEnabled(False)

        self.a2_nmf_plot_layout.addWidget(self.a2_nmfPlotCombo)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_plot_layout)

        self.a2_nmf_rgb_map_layout = QHBoxLayout()
        self.a2_nmf_rgb_map_layout.setObjectName(u"a2_nmf_rgb_map_layout")
        self.a2_nmfTargetSpectraLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfTargetSpectraLabel.setObjectName(u"a2_nmfTargetSpectraLabel")

        self.a2_nmf_rgb_map_layout.addWidget(self.a2_nmfTargetSpectraLabel)

        self.a2_nmfTargetSpectraEdit = QLineEdit(self.a2_tab_nnmf)
        self.a2_nmfTargetSpectraEdit.setObjectName(u"a2_nmfTargetSpectraEdit")

        self.a2_nmf_rgb_map_layout.addWidget(self.a2_nmfTargetSpectraEdit)

        self.a2_nmfCalcRGBMapButton = QPushButton(self.a2_tab_nnmf)
        self.a2_nmfCalcRGBMapButton.setObjectName(u"a2_nmfCalcRGBMapButton")

        self.a2_nmf_rgb_map_layout.addWidget(self.a2_nmfCalcRGBMapButton)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_rgb_map_layout)

        self.a2_nmf_vspacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_nnmf_layout.addItem(self.a2_nmf_vspacer)

        self.a2_workflowTabs.addTab(self.a2_tab_nnmf, "")
        self.a2_tab_metadata = QWidget()
        self.a2_tab_metadata.setObjectName(u"a2_tab_metadata")
        self.a2_tab_metadata_layout = QVBoxLayout(self.a2_tab_metadata)
        self.a2_tab_metadata_layout.setSpacing(0)
        self.a2_tab_metadata_layout.setObjectName(u"a2_tab_metadata_layout")
        self.a2_tab_metadata_layout.setContentsMargins(4, 4, 4, 4)
        self.a2_workflowTabs.addTab(self.a2_tab_metadata, "")

        self.a2_rightPane_layout.addWidget(self.a2_workflowTabs)

        self.a2_topSplitter.addWidget(self.a2_rightPane)
        self.a2_imagePane = QWidget(self.a2_topSplitter)
        self.a2_imagePane.setObjectName(u"a2_imagePane")
        self.a2_imagePane_layout = QVBoxLayout(self.a2_imagePane)
        self.a2_imagePane_layout.setObjectName(u"a2_imagePane_layout")
        self.a2_imagePane_layout.setContentsMargins(0, 0, 0, 0)
        self.a2_imageView = ImageView(self.a2_imagePane)
        self.a2_imageView.setObjectName(u"a2_imageView")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.a2_imageView.sizePolicy().hasHeightForWidth())
        self.a2_imageView.setSizePolicy(sizePolicy2)
        self.a2_imageView.setMinimumSize(QSize(800, 700))

        self.a2_imagePane_layout.addWidget(self.a2_imageView)

        self.a2_metadataText = QTextEdit(self.a2_imagePane)
        self.a2_metadataText.setObjectName(u"a2_metadataText")
        self.a2_metadataText.setReadOnly(True)

        self.a2_imagePane_layout.addWidget(self.a2_metadataText)

        self.a2_topSplitter.addWidget(self.a2_imagePane)

        self.a2_layout.addWidget(self.a2_topSplitter)


        self.retranslateUi(Analysis2Widget)

        self.a2_workflowTabs.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(Analysis2Widget)
    # setupUi

    def retranslateUi(self, Analysis2Widget):
        self.a2_openStackButton.setText(QCoreApplication.translate("Analysis2Widget", u"Open Stack", None))
        self.a2_saveDataButton.setText(QCoreApplication.translate("Analysis2Widget", u"Save Data", None))
        self.a2_addToLogButton.setText(QCoreApplication.translate("Analysis2Widget", u"Add to Log", None))
        self.a2_savePngButton.setText(QCoreApplication.translate("Analysis2Widget", u"Save PNG", None))
        self.a2_roiTypeLabel.setText(QCoreApplication.translate("Analysis2Widget", u"ROI Type:", None))
        self.a2_roiTypeCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"I0", None))
        self.a2_roiTypeCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Spectrum", None))
        self.a2_roiTypeCombo.setItemText(2, QCoreApplication.translate("Analysis2Widget", u"Crop", None))

        self.a2_drawRoiCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Draw ROI", None))
        self.a2_deleteRoiButton.setText(QCoreApplication.translate("Analysis2Widget", u"Delete ROI", None))
        self.a2_deleteFrameButton.setText(QCoreApplication.translate("Analysis2Widget", u"Delete Frame", None))
        self.a2_cropButton.setText(QCoreApplication.translate("Analysis2Widget", u"Crop", None))
        self.a2_odCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Optical Density", None))
        self.a2_autoProcessButton.setText(QCoreApplication.translate("Analysis2Widget", u"Auto Process", None))
        self.a2_mapButton.setText(QCoreApplication.translate("Analysis2Widget", u"Map", None))
        self.a2_resetButton.setText(QCoreApplication.translate("Analysis2Widget", u"Reset", None))
        self.a2_preEdgeCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Select Pre-Edge", None))
        self.a2_subtractPreEdgeButton.setText(QCoreApplication.translate("Analysis2Widget", u"Subtract Pre-Edge", None))
        self.a2_detrendButton.setText(QCoreApplication.translate("Analysis2Widget", u"Detrend", None))
        self.a2_selectI0FromHistogramCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Select I0 From Histogram", None))
        self.a2_trackMouseCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Track Mouse", None))
        self.a2_liveDisplayCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Live Display", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_main), QCoreApplication.translate("Analysis2Widget", u"Main", None))
        self.a2_darkLevelLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Dark Level:", None))
        self.a2_darkLevelEdit.setText(QCoreApplication.translate("Analysis2Widget", u"0", None))
        self.a2_subtractDarkButton.setText(QCoreApplication.translate("Analysis2Widget", u"Subtract Dark Level", None))
        self.a2_filterUndoButton.setText(QCoreApplication.translate("Analysis2Widget", u"Undo", None))
        self.a2_medianKernelLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Kernel Size:", None))
        self.a2_medianKernelEdit.setText(QCoreApplication.translate("Analysis2Widget", u"5", None))
        self.a2_medianFilterButton.setText(QCoreApplication.translate("Analysis2Widget", u"Median Filter", None))
        self.a2_despikeKernelLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Kernel Size:", None))
        self.a2_despikeKernelEdit.setText(QCoreApplication.translate("Analysis2Widget", u"3", None))
        self.a2_despikeNSigmaLabel.setText(QCoreApplication.translate("Analysis2Widget", u"N Sigma:", None))
        self.a2_despikeNSigmaEdit.setText(QCoreApplication.translate("Analysis2Widget", u"5", None))
        self.a2_despikeButton.setText(QCoreApplication.translate("Analysis2Widget", u"Despike", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_filtering), QCoreApplication.translate("Analysis2Widget", u"Filtering", None))
        self.a2_regImageTypeLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Image Type:", None))
        self.a2_regImageTypeCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"Transmission", None))
        self.a2_regImageTypeCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Optical Density", None))

        self.a2_regModeLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Mode:", None))
        self.a2_regModeCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"Translation", None))
        self.a2_regModeCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Circular Image", None))
        self.a2_regModeCombo.setItemText(2, QCoreApplication.translate("Analysis2Widget", u"Affine", None))
        self.a2_regModeCombo.setItemText(3, QCoreApplication.translate("Analysis2Widget", u"Rigid", None))
        self.a2_regModeCombo.setItemText(4, QCoreApplication.translate("Analysis2Widget", u"Homographic", None))

        self.a2_regAlignMethodLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Align To:", None))
        self.a2_regAlignMethodCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"Sequential", None))
        self.a2_regAlignMethodCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Reference Image", None))

        self.a2_regThresholdCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Thresholded", None))
        self.a2_regThresholdLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Threshold:", None))
        self.a2_regThresholdEdit.setText(QCoreApplication.translate("Analysis2Widget", u"0", None))
        self.a2_regSobelCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Sobel Filter", None))
        self.a2_regAutocropCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Autocrop", None))
        self.a2_regStartButton.setText(QCoreApplication.translate("Analysis2Widget", u"Start", None))
        self.a2_regUndoButton.setText(QCoreApplication.translate("Analysis2Widget", u"Undo", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_registration), QCoreApplication.translate("Analysis2Widget", u"Registration", None))
        self.a2_nComponentsLabel.setText(QCoreApplication.translate("Analysis2Widget", u"N Components:", None))
        self.a2_nComponentsEdit.setText(QCoreApplication.translate("Analysis2Widget", u"4", None))
        self.a2_nClustersLabel.setText(QCoreApplication.translate("Analysis2Widget", u"N Clusters:", None))
        self.a2_nClustersEdit.setText(QCoreApplication.translate("Analysis2Widget", u"4", None))
        self.a2_reduceMassCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Reduce Mass Effects", None))
        self.a2_removePreEdgeCheckbox.setText(QCoreApplication.translate("Analysis2Widget", u"Remove Pre-Edge", None))
        self.a2_pcaMaskI0Checkbox.setText(QCoreApplication.translate("Analysis2Widget", u"Mask I0 Region", None))
        self.a2_calcPCAButton.setText(QCoreApplication.translate("Analysis2Widget", u"Calculate PCA", None))
        self.a2_clusterImageLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Display:", None))
        self.a2_clusterImageCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"Transmission", None))
        self.a2_clusterImageCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Optical Density", None))
        self.a2_clusterImageCombo.setItemText(2, QCoreApplication.translate("Analysis2Widget", u"Principal Components", None))
        self.a2_clusterImageCombo.setItemText(3, QCoreApplication.translate("Analysis2Widget", u"Clusters", None))
        self.a2_clusterImageCombo.setItemText(4, QCoreApplication.translate("Analysis2Widget", u"RGB Map", None))

        self.a2_clusterPlotLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Plot:", None))
        self.a2_clusterPlotCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"ROI Spectra", None))
        self.a2_clusterPlotCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Cluster Spectra", None))
        self.a2_clusterPlotCombo.setItemText(2, QCoreApplication.translate("Analysis2Widget", u"PCA Eigenvalues", None))

        self.a2_targetSpectraLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Target Spectra:", None))
        self.a2_targetSpectraEdit.setText(QCoreApplication.translate("Analysis2Widget", u"1,2,3", None))
        self.a2_calcRGBMapButton.setText(QCoreApplication.translate("Analysis2Widget", u"RGB Map", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_clustering), QCoreApplication.translate("Analysis2Widget", u"PCA", None))
        self.a2_nmfNComponentsLabel.setText(QCoreApplication.translate("Analysis2Widget", u"N Components:", None))
        self.a2_nmfNComponentsEdit.setText(QCoreApplication.translate("Analysis2Widget", u"4", None))
        self.a2_nmfNClustersLabel.setText(QCoreApplication.translate("Analysis2Widget", u"N Clusters:", None))
        self.a2_nmfNClustersEdit.setText(QCoreApplication.translate("Analysis2Widget", u"4", None))
        self.a2_nmfMaxIterLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Max Iterations:", None))
        self.a2_nmfMaxIterEdit.setText(QCoreApplication.translate("Analysis2Widget", u"500", None))
        self.a2_nmfInitLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Init:", None))
        self.a2_nmfInitCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"NNDSVDA", None))
        self.a2_nmfInitCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Random", None))

        self.a2_nmfMaskI0Checkbox.setText(QCoreApplication.translate("Analysis2Widget", u"Mask I0 Region", None))
        self.a2_calcNMFButton.setText(QCoreApplication.translate("Analysis2Widget", u"Calculate NMF", None))
        self.a2_nmfDisplayLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Display:", None))
        self.a2_nmfDisplayCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"NMF Components", None))
        self.a2_nmfDisplayCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Cluster Map", None))
        self.a2_nmfDisplayCombo.setItemText(2, QCoreApplication.translate("Analysis2Widget", u"RGB Map", None))

        self.a2_nmfPlotLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Plot:", None))
        self.a2_nmfPlotCombo.setItemText(0, QCoreApplication.translate("Analysis2Widget", u"Component Spectra", None))
        self.a2_nmfPlotCombo.setItemText(1, QCoreApplication.translate("Analysis2Widget", u"Cluster Spectra", None))

        self.a2_nmfTargetSpectraLabel.setText(QCoreApplication.translate("Analysis2Widget", u"Target Spectra:", None))
        self.a2_nmfTargetSpectraEdit.setText(QCoreApplication.translate("Analysis2Widget", u"1,2,3", None))
        self.a2_nmfCalcRGBMapButton.setText(QCoreApplication.translate("Analysis2Widget", u"RGB Map", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_nnmf), QCoreApplication.translate("Analysis2Widget", u"NNMF", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_metadata), QCoreApplication.translate("Analysis2Widget", u"Line Spectrum", None))
        self.a2_metadataText.setPlaceholderText(QCoreApplication.translate("Analysis2Widget", u"File and process metadata will appear here\u2026", None))
        pass
    # retranslateUi


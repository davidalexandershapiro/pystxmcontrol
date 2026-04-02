# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'stack_mainwindow.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QSlider, QSpacerItem, QVBoxLayout,
    QWidget)

from pyqtgraph import (ImageView, PlotWidget)

class Ui_stackViewer(object):
    def setupUi(self, stackViewer):
        if not stackViewer.objectName():
            stackViewer.setObjectName(u"stackViewer")
        stackViewer.resize(1057, 600)
        self.verticalLayout_outer = QVBoxLayout(stackViewer)
        self.verticalLayout_outer.setSpacing(4)
        self.verticalLayout_outer.setObjectName(u"verticalLayout_outer")
        self.verticalLayout_outer.setContentsMargins(4, 4, 4, 4)
        self.live_display = QCheckBox(stackViewer)
        self.live_display.setObjectName(u"live_display")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.live_display.sizePolicy().hasHeightForWidth())
        self.live_display.setSizePolicy(sizePolicy)

        self.verticalLayout_outer.addWidget(self.live_display)

        self.horizontalLayout_main = QHBoxLayout()
        self.horizontalLayout_main.setSpacing(4)
        self.horizontalLayout_main.setObjectName(u"horizontalLayout_main")
        self.mainImage = ImageView(stackViewer)
        self.mainImage.setObjectName(u"mainImage")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(3)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.mainImage.sizePolicy().hasHeightForWidth())
        self.mainImage.setSizePolicy(sizePolicy1)

        self.horizontalLayout_main.addWidget(self.mainImage)

        self.verticalLayout_right = QVBoxLayout()
        self.verticalLayout_right.setSpacing(4)
        self.verticalLayout_right.setObjectName(u"verticalLayout_right")
        self.horizontalLayout_plot = QHBoxLayout()
        self.horizontalLayout_plot.setSpacing(2)
        self.horizontalLayout_plot.setObjectName(u"horizontalLayout_plot")
        self.verticalSlider = QSlider(stackViewer)
        self.verticalSlider.setObjectName(u"verticalSlider")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.verticalSlider.sizePolicy().hasHeightForWidth())
        self.verticalSlider.setSizePolicy(sizePolicy2)
        self.verticalSlider.setOrientation(Qt.Vertical)

        self.horizontalLayout_plot.addWidget(self.verticalSlider)

        self.specPlot = PlotWidget(stackViewer)
        self.specPlot.setObjectName(u"specPlot")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.specPlot.sizePolicy().hasHeightForWidth())
        self.specPlot.setSizePolicy(sizePolicy3)
        self.specPlot.setMaximumHeight(560)

        self.horizontalLayout_plot.addWidget(self.specPlot)


        self.verticalLayout_right.addLayout(self.horizontalLayout_plot)

        self.gridLayout_controls = QGridLayout()
        self.gridLayout_controls.setSpacing(4)
        self.gridLayout_controls.setObjectName(u"gridLayout_controls")
        self.regionSelect = QComboBox(stackViewer)
        self.regionSelect.addItem("")
        self.regionSelect.setObjectName(u"regionSelect")

        self.gridLayout_controls.addWidget(self.regionSelect, 0, 0, 1, 1)

        self.spectraComboBox = QComboBox(stackViewer)
        self.spectraComboBox.addItem("")
        self.spectraComboBox.addItem("")
        self.spectraComboBox.addItem("")
        self.spectraComboBox.setObjectName(u"spectraComboBox")
        self.spectraComboBox.setLayoutDirection(Qt.LeftToRight)

        self.gridLayout_controls.addWidget(self.spectraComboBox, 0, 1, 1, 1)

        self.addROIButton = QPushButton(stackViewer)
        self.addROIButton.setObjectName(u"addROIButton")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.addROIButton.sizePolicy().hasHeightForWidth())
        self.addROIButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.addROIButton, 0, 2, 1, 1)

        self.clearROIButton = QPushButton(stackViewer)
        self.clearROIButton.setObjectName(u"clearROIButton")
        sizePolicy4.setHeightForWidth(self.clearROIButton.sizePolicy().hasHeightForWidth())
        self.clearROIButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.clearROIButton, 0, 3, 1, 1)

        self.pcaButton = QPushButton(stackViewer)
        self.pcaButton.setObjectName(u"pcaButton")
        sizePolicy4.setHeightForWidth(self.pcaButton.sizePolicy().hasHeightForWidth())
        self.pcaButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.pcaButton, 0, 4, 1, 1)

        self.frameEnergy = QLabel(stackViewer)
        self.frameEnergy.setObjectName(u"frameEnergy")

        self.gridLayout_controls.addWidget(self.frameEnergy, 0, 5, 1, 1)

        self.autoButton = QPushButton(stackViewer)
        self.autoButton.setObjectName(u"autoButton")
        sizePolicy4.setHeightForWidth(self.autoButton.sizePolicy().hasHeightForWidth())
        self.autoButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.autoButton, 1, 0, 1, 1)

        self.filterButton = QPushButton(stackViewer)
        self.filterButton.setObjectName(u"filterButton")
        sizePolicy4.setHeightForWidth(self.filterButton.sizePolicy().hasHeightForWidth())
        self.filterButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.filterButton, 1, 1, 1, 1)

        self.toggleOD = QCheckBox(stackViewer)
        self.toggleOD.setObjectName(u"toggleOD")
        sizePolicy4.setHeightForWidth(self.toggleOD.sizePolicy().hasHeightForWidth())
        self.toggleOD.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.toggleOD, 1, 2, 1, 1)

        self.label = QLabel(stackViewer)
        self.label.setObjectName(u"label")

        self.gridLayout_controls.addWidget(self.label, 1, 3, 1, 1, Qt.AlignRight)

        self.darkLineEdit = QLineEdit(stackViewer)
        self.darkLineEdit.setObjectName(u"darkLineEdit")
        sizePolicy.setHeightForWidth(self.darkLineEdit.sizePolicy().hasHeightForWidth())
        self.darkLineEdit.setSizePolicy(sizePolicy)

        self.gridLayout_controls.addWidget(self.darkLineEdit, 1, 4, 1, 1)

        self.mapButton = QPushButton(stackViewer)
        self.mapButton.setObjectName(u"mapButton")
        sizePolicy4.setHeightForWidth(self.mapButton.sizePolicy().hasHeightForWidth())
        self.mapButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.mapButton, 1, 5, 1, 1)

        self.resetButton = QPushButton(stackViewer)
        self.resetButton.setObjectName(u"resetButton")

        self.gridLayout_controls.addWidget(self.resetButton, 2, 0, 1, 1)

        self.registerButton = QPushButton(stackViewer)
        self.registerButton.setObjectName(u"registerButton")
        sizePolicy4.setHeightForWidth(self.registerButton.sizePolicy().hasHeightForWidth())
        self.registerButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.registerButton, 2, 1, 1, 1)

        self.preEdgeBox = QCheckBox(stackViewer)
        self.preEdgeBox.setObjectName(u"preEdgeBox")
        sizePolicy4.setHeightForWidth(self.preEdgeBox.sizePolicy().hasHeightForWidth())
        self.preEdgeBox.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.preEdgeBox, 2, 2, 1, 1)

        self.scaleBox = QCheckBox(stackViewer)
        self.scaleBox.setObjectName(u"scaleBox")
        sizePolicy4.setHeightForWidth(self.scaleBox.sizePolicy().hasHeightForWidth())
        self.scaleBox.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.scaleBox, 2, 3, 1, 1)

        self.trackMouseBox = QCheckBox(stackViewer)
        self.trackMouseBox.setObjectName(u"trackMouseBox")
        sizePolicy4.setHeightForWidth(self.trackMouseBox.sizePolicy().hasHeightForWidth())
        self.trackMouseBox.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.trackMouseBox, 2, 4, 1, 1)

        self.bkgRemovalButton = QPushButton(stackViewer)
        self.bkgRemovalButton.setObjectName(u"bkgRemovalButton")
        sizePolicy4.setHeightForWidth(self.bkgRemovalButton.sizePolicy().hasHeightForWidth())
        self.bkgRemovalButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.bkgRemovalButton, 2, 5, 1, 1)

        self.fileName = QLabel(stackViewer)
        self.fileName.setObjectName(u"fileName")

        self.gridLayout_controls.addWidget(self.fileName, 3, 0, 1, 3)

        self.deleteButton = QPushButton(stackViewer)
        self.deleteButton.setObjectName(u"deleteButton")

        self.gridLayout_controls.addWidget(self.deleteButton, 3, 3, 1, 1)

        self.stackLoadButton = QPushButton(stackViewer)
        self.stackLoadButton.setObjectName(u"stackLoadButton")
        sizePolicy4.setHeightForWidth(self.stackLoadButton.sizePolicy().hasHeightForWidth())
        self.stackLoadButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.stackLoadButton, 3, 4, 1, 1)

        self.saveButton = QPushButton(stackViewer)
        self.saveButton.setObjectName(u"saveButton")
        sizePolicy4.setHeightForWidth(self.saveButton.sizePolicy().hasHeightForWidth())
        self.saveButton.setSizePolicy(sizePolicy4)

        self.gridLayout_controls.addWidget(self.saveButton, 3, 5, 1, 1)


        self.verticalLayout_right.addLayout(self.gridLayout_controls)

        self.importButton = QPushButton(stackViewer)
        self.importButton.setObjectName(u"importButton")

        self.verticalLayout_right.addWidget(self.importButton)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout_right.addItem(self.verticalSpacer)


        self.horizontalLayout_main.addLayout(self.verticalLayout_right)


        self.verticalLayout_outer.addLayout(self.horizontalLayout_main)


        self.retranslateUi(stackViewer)

        QMetaObject.connectSlotsByName(stackViewer)
    # setupUi

    def retranslateUi(self, stackViewer):
        stackViewer.setWindowTitle(QCoreApplication.translate("stackViewer", u"Stack Viewer", None))
        self.live_display.setText(QCoreApplication.translate("stackViewer", u"Live Display", None))
        self.regionSelect.setItemText(0, QCoreApplication.translate("stackViewer", u"Region 1", None))

        self.spectraComboBox.setItemText(0, QCoreApplication.translate("stackViewer", u"ROI", None))
        self.spectraComboBox.setItemText(1, QCoreApplication.translate("stackViewer", u"Point", None))
        self.spectraComboBox.setItemText(2, QCoreApplication.translate("stackViewer", u"I0", None))

        self.addROIButton.setText(QCoreApplication.translate("stackViewer", u"Add", None))
        self.clearROIButton.setText(QCoreApplication.translate("stackViewer", u"Remove", None))
        self.pcaButton.setText(QCoreApplication.translate("stackViewer", u"PCA / Clustering", None))
        self.frameEnergy.setText(QCoreApplication.translate("stackViewer", u"Current Frame Energy", None))
        self.autoButton.setText(QCoreApplication.translate("stackViewer", u"Auto", None))
        self.filterButton.setText(QCoreApplication.translate("stackViewer", u"Filter", None))
        self.toggleOD.setText(QCoreApplication.translate("stackViewer", u"Optical Density", None))
        self.label.setText(QCoreApplication.translate("stackViewer", u"Dark Signal", None))
        self.darkLineEdit.setText(QCoreApplication.translate("stackViewer", u"0", None))
        self.mapButton.setText(QCoreApplication.translate("stackViewer", u"Map", None))
        self.resetButton.setText(QCoreApplication.translate("stackViewer", u"Reset", None))
        self.registerButton.setText(QCoreApplication.translate("stackViewer", u"Register", None))
        self.preEdgeBox.setText(QCoreApplication.translate("stackViewer", u"Subtract Pre-edge", None))
        self.scaleBox.setText(QCoreApplication.translate("stackViewer", u"Scale", None))
        self.trackMouseBox.setText(QCoreApplication.translate("stackViewer", u"Track Mouse", None))
        self.bkgRemovalButton.setText(QCoreApplication.translate("stackViewer", u"BKG Removal", None))
        self.fileName.setText(QCoreApplication.translate("stackViewer", u"Current File Name", None))
        self.deleteButton.setText(QCoreApplication.translate("stackViewer", u"Delete Frame", None))
        self.stackLoadButton.setText(QCoreApplication.translate("stackViewer", u"Load Stack", None))
        self.saveButton.setText(QCoreApplication.translate("stackViewer", u"Save Data", None))
        self.importButton.setText(QCoreApplication.translate("stackViewer", u"Import", None))
    # retranslateUi


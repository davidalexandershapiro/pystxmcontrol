# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'stack_mainwindow.ui'
##
## Created by: Qt User Interface Compiler version 6.7.2
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
    QSizePolicy, QSlider, QWidget)

from pyqtgraph import (ImageView, PlotWidget)

class Ui_stackViewer(object):
    def setupUi(self, stackViewer):
        if not stackViewer.objectName():
            stackViewer.setObjectName(u"stackViewer")
        stackViewer.resize(1057, 600)
        self.gridLayout = QGridLayout(stackViewer)
        self.gridLayout.setObjectName(u"gridLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")

        self.gridLayout.addLayout(self.horizontalLayout, 0, 0, 1, 1)

        self.gridLayout_2 = QGridLayout()
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.saveButton = QPushButton(stackViewer)
        self.saveButton.setObjectName(u"saveButton")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.saveButton.sizePolicy().hasHeightForWidth())
        self.saveButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.saveButton, 5, 10, 1, 1)

        self.trackMouseBox = QCheckBox(stackViewer)
        self.trackMouseBox.setObjectName(u"trackMouseBox")
        sizePolicy.setHeightForWidth(self.trackMouseBox.sizePolicy().hasHeightForWidth())
        self.trackMouseBox.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.trackMouseBox, 5, 4, 1, 1)

        self.scaleBox = QCheckBox(stackViewer)
        self.scaleBox.setObjectName(u"scaleBox")
        sizePolicy.setHeightForWidth(self.scaleBox.sizePolicy().hasHeightForWidth())
        self.scaleBox.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.scaleBox, 5, 3, 1, 1)

        self.stackLoadButton = QPushButton(stackViewer)
        self.stackLoadButton.setObjectName(u"stackLoadButton")
        sizePolicy.setHeightForWidth(self.stackLoadButton.sizePolicy().hasHeightForWidth())
        self.stackLoadButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.stackLoadButton, 5, 9, 1, 1)

        self.fileName = QLabel(stackViewer)
        self.fileName.setObjectName(u"fileName")

        self.gridLayout_2.addWidget(self.fileName, 3, 9, 1, 2)

        self.verticalSlider = QSlider(stackViewer)
        self.verticalSlider.setObjectName(u"verticalSlider")
        self.verticalSlider.setOrientation(Qt.Vertical)

        self.gridLayout_2.addWidget(self.verticalSlider, 0, 8, 1, 1)

        self.clearROIButton = QPushButton(stackViewer)
        self.clearROIButton.setObjectName(u"clearROIButton")
        sizePolicy.setHeightForWidth(self.clearROIButton.sizePolicy().hasHeightForWidth())
        self.clearROIButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.clearROIButton, 2, 3, 1, 1)

        self.mainImage = ImageView(stackViewer)
        self.mainImage.setObjectName(u"mainImage")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.mainImage.sizePolicy().hasHeightForWidth())
        self.mainImage.setSizePolicy(sizePolicy1)
        self.mainImage.setMinimumSize(QSize(0, 0))

        self.gridLayout_2.addWidget(self.mainImage, 0, 0, 1, 5)

        self.frameEnergy = QLabel(stackViewer)
        self.frameEnergy.setObjectName(u"frameEnergy")

        self.gridLayout_2.addWidget(self.frameEnergy, 2, 9, 1, 1)

        self.toggleOD = QCheckBox(stackViewer)
        self.toggleOD.setObjectName(u"toggleOD")
        sizePolicy.setHeightForWidth(self.toggleOD.sizePolicy().hasHeightForWidth())
        self.toggleOD.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.toggleOD, 3, 2, 1, 1)

        self.resetButton = QPushButton(stackViewer)
        self.resetButton.setObjectName(u"resetButton")

        self.gridLayout_2.addWidget(self.resetButton, 5, 0, 1, 1)

        self.autoButton = QPushButton(stackViewer)
        self.autoButton.setObjectName(u"autoButton")
        sizePolicy.setHeightForWidth(self.autoButton.sizePolicy().hasHeightForWidth())
        self.autoButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.autoButton, 3, 0, 1, 1)

        self.regionSelect = QComboBox(stackViewer)
        self.regionSelect.addItem("")
        self.regionSelect.setObjectName(u"regionSelect")

        self.gridLayout_2.addWidget(self.regionSelect, 2, 0, 1, 1)

        self.addROIButton = QPushButton(stackViewer)
        self.addROIButton.setObjectName(u"addROIButton")
        sizePolicy.setHeightForWidth(self.addROIButton.sizePolicy().hasHeightForWidth())
        self.addROIButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.addROIButton, 2, 2, 1, 1)

        self.filterButton = QPushButton(stackViewer)
        self.filterButton.setObjectName(u"filterButton")
        sizePolicy.setHeightForWidth(self.filterButton.sizePolicy().hasHeightForWidth())
        self.filterButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.filterButton, 3, 1, 1, 1)

        self.mapButton = QPushButton(stackViewer)
        self.mapButton.setObjectName(u"mapButton")
        sizePolicy.setHeightForWidth(self.mapButton.sizePolicy().hasHeightForWidth())
        self.mapButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.mapButton, 2, 10, 1, 1)

        self.spectraComboBox = QComboBox(stackViewer)
        self.spectraComboBox.addItem("")
        self.spectraComboBox.addItem("")
        self.spectraComboBox.addItem("")
        self.spectraComboBox.setObjectName(u"spectraComboBox")
        self.spectraComboBox.setLayoutDirection(Qt.LeftToRight)

        self.gridLayout_2.addWidget(self.spectraComboBox, 2, 1, 1, 1)

        self.registerButton = QPushButton(stackViewer)
        self.registerButton.setObjectName(u"registerButton")
        sizePolicy.setHeightForWidth(self.registerButton.sizePolicy().hasHeightForWidth())
        self.registerButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.registerButton, 5, 1, 1, 1)

        self.specPlot = PlotWidget(stackViewer)
        self.specPlot.setObjectName(u"specPlot")
        sizePolicy1.setHeightForWidth(self.specPlot.sizePolicy().hasHeightForWidth())
        self.specPlot.setSizePolicy(sizePolicy1)
        self.specPlot.setMinimumSize(QSize(0, 0))

        self.gridLayout_2.addWidget(self.specPlot, 0, 9, 1, 3)

        self.preEdgeBox = QCheckBox(stackViewer)
        self.preEdgeBox.setObjectName(u"preEdgeBox")
        sizePolicy.setHeightForWidth(self.preEdgeBox.sizePolicy().hasHeightForWidth())
        self.preEdgeBox.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.preEdgeBox, 5, 2, 1, 1)

        self.pcaButton = QPushButton(stackViewer)
        self.pcaButton.setObjectName(u"pcaButton")
        sizePolicy.setHeightForWidth(self.pcaButton.sizePolicy().hasHeightForWidth())
        self.pcaButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.pcaButton, 2, 4, 1, 1)

        self.bkgRemovalButton = QPushButton(stackViewer)
        self.bkgRemovalButton.setObjectName(u"bkgRemovalButton")
        sizePolicy.setHeightForWidth(self.bkgRemovalButton.sizePolicy().hasHeightForWidth())
        self.bkgRemovalButton.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.bkgRemovalButton, 2, 11, 1, 1)

        self.importButton = QPushButton(stackViewer)
        self.importButton.setObjectName(u"importButton")

        self.gridLayout_2.addWidget(self.importButton, 5, 11, 1, 1)

        self.deleteButton = QPushButton(stackViewer)
        self.deleteButton.setObjectName(u"deleteButton")

        self.gridLayout_2.addWidget(self.deleteButton, 3, 11, 1, 1)

        self.label = QLabel(stackViewer)
        self.label.setObjectName(u"label")

        self.gridLayout_2.addWidget(self.label, 3, 3, 1, 1, Qt.AlignRight)

        self.darkLineEdit = QLineEdit(stackViewer)
        self.darkLineEdit.setObjectName(u"darkLineEdit")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.darkLineEdit.sizePolicy().hasHeightForWidth())
        self.darkLineEdit.setSizePolicy(sizePolicy2)

        self.gridLayout_2.addWidget(self.darkLineEdit, 3, 4, 1, 1)


        self.gridLayout.addLayout(self.gridLayout_2, 2, 0, 1, 1)

        self.live_display = QCheckBox(stackViewer)
        self.live_display.setObjectName(u"live_display")

        self.gridLayout.addWidget(self.live_display, 1, 0, 1, 1)


        self.retranslateUi(stackViewer)

        QMetaObject.connectSlotsByName(stackViewer)
    # setupUi

    def retranslateUi(self, stackViewer):
        stackViewer.setWindowTitle(QCoreApplication.translate("stackViewer", u"Stack Viewer", None))
        self.saveButton.setText(QCoreApplication.translate("stackViewer", u"Save Data", None))
        self.trackMouseBox.setText(QCoreApplication.translate("stackViewer", u"Track Mouse", None))
        self.scaleBox.setText(QCoreApplication.translate("stackViewer", u"Scale", None))
        self.stackLoadButton.setText(QCoreApplication.translate("stackViewer", u"Load Stack", None))
        self.fileName.setText(QCoreApplication.translate("stackViewer", u"Current File Name", None))
        self.clearROIButton.setText(QCoreApplication.translate("stackViewer", u"Remove", None))
        self.frameEnergy.setText(QCoreApplication.translate("stackViewer", u"Current Frame Energy", None))
        self.toggleOD.setText(QCoreApplication.translate("stackViewer", u"Optical Density", None))
        self.resetButton.setText(QCoreApplication.translate("stackViewer", u"Reset", None))
        self.autoButton.setText(QCoreApplication.translate("stackViewer", u"Auto", None))
        self.regionSelect.setItemText(0, QCoreApplication.translate("stackViewer", u"Region 1", None))

        self.addROIButton.setText(QCoreApplication.translate("stackViewer", u"Add", None))
        self.filterButton.setText(QCoreApplication.translate("stackViewer", u"Filter", None))
        self.mapButton.setText(QCoreApplication.translate("stackViewer", u"Map", None))
        self.spectraComboBox.setItemText(0, QCoreApplication.translate("stackViewer", u"ROI", None))
        self.spectraComboBox.setItemText(1, QCoreApplication.translate("stackViewer", u"Point", None))
        self.spectraComboBox.setItemText(2, QCoreApplication.translate("stackViewer", u"I0", None))

        self.registerButton.setText(QCoreApplication.translate("stackViewer", u"Register", None))
        self.preEdgeBox.setText(QCoreApplication.translate("stackViewer", u"Subtract Pre-edge", None))
        self.pcaButton.setText(QCoreApplication.translate("stackViewer", u"PCA / Clustering", None))
        self.bkgRemovalButton.setText(QCoreApplication.translate("stackViewer", u"BKG Removal", None))
        self.importButton.setText(QCoreApplication.translate("stackViewer", u"Import", None))
        self.deleteButton.setText(QCoreApplication.translate("stackViewer", u"Delete Frame", None))
        self.label.setText(QCoreApplication.translate("stackViewer", u"Dark Signal", None))
        self.darkLineEdit.setText(QCoreApplication.translate("stackViewer", u"0", None))
        self.live_display.setText(QCoreApplication.translate("stackViewer", u"Live Display", None))
    # retranslateUi


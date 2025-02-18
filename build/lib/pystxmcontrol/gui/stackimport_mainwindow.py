# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'stackimport_mainwindow.ui'
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
from PySide6.QtWidgets import (QApplication, QComboBox, QGridLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QSizePolicy,
    QSlider, QWidget)

from pyqtgraph import (ImageView, PlotWidget)

class Ui_Import(object):
    def setupUi(self, Import):
        if not Import.objectName():
            Import.setObjectName(u"Import")
        Import.resize(1037, 855)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(Import.sizePolicy().hasHeightForWidth())
        Import.setSizePolicy(sizePolicy)
        self.baseStack = ImageView(Import)
        self.baseStack.setObjectName(u"baseStack")
        self.baseStack.setGeometry(QRect(0, 20, 500, 400))
        self.plotWindow = PlotWidget(Import)
        self.plotWindow.setObjectName(u"plotWindow")
        self.plotWindow.setGeometry(QRect(530, 20, 500, 400))
        self.importStack = ImageView(Import)
        self.importStack.setObjectName(u"importStack")
        self.importStack.setGeometry(QRect(0, 450, 500, 400))
        self.acceptButton = QPushButton(Import)
        self.acceptButton.setObjectName(u"acceptButton")
        self.acceptButton.setGeometry(QRect(940, 790, 89, 25))
        self.cancelButton = QPushButton(Import)
        self.cancelButton.setObjectName(u"cancelButton")
        self.cancelButton.setGeometry(QRect(940, 820, 89, 25))
        self.label = QLabel(Import)
        self.label.setObjectName(u"label")
        self.label.setGeometry(QRect(0, 0, 141, 17))
        self.label_2 = QLabel(Import)
        self.label_2.setObjectName(u"label_2")
        self.label_2.setGeometry(QRect(0, 430, 141, 17))
        self.addFrameButton = QPushButton(Import)
        self.addFrameButton.setObjectName(u"addFrameButton")
        self.addFrameButton.setGeometry(QRect(520, 790, 89, 25))
        self.interpRadio = QRadioButton(Import)
        self.interpRadio.setObjectName(u"interpRadio")
        self.interpRadio.setGeometry(QRect(520, 450, 181, 23))
        self.interpRadio.setChecked(True)
        self.roiRadio = QRadioButton(Import)
        self.roiRadio.setObjectName(u"roiRadio")
        self.roiRadio.setGeometry(QRect(520, 670, 112, 23))
        self.odRadio = QRadioButton(Import)
        self.odRadio.setObjectName(u"odRadio")
        self.odRadio.setGeometry(QRect(520, 640, 131, 23))
        self.baseSlider = QSlider(Import)
        self.baseSlider.setObjectName(u"baseSlider")
        self.baseSlider.setGeometry(QRect(500, 20, 20, 401))
        self.baseSlider.setOrientation(Qt.Vertical)
        self.importSlider = QSlider(Import)
        self.importSlider.setObjectName(u"importSlider")
        self.importSlider.setGeometry(QRect(500, 450, 16, 401))
        self.importSlider.setOrientation(Qt.Vertical)
        self.pushButton_2 = QPushButton(Import)
        self.pushButton_2.setObjectName(u"pushButton_2")
        self.pushButton_2.setGeometry(QRect(520, 820, 89, 25))
        self.widget = QWidget(Import)
        self.widget.setObjectName(u"widget")
        self.widget.setGeometry(QRect(520, 480, 235, 151))
        self.gridLayout = QGridLayout(self.widget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.pushButton = QPushButton(self.widget)
        self.pushButton.setObjectName(u"pushButton")

        self.gridLayout.addWidget(self.pushButton, 0, 0, 1, 1)

        self.comboBox = QComboBox(self.widget)
        self.comboBox.addItem("")
        self.comboBox.addItem("")
        self.comboBox.setObjectName(u"comboBox")

        self.gridLayout.addWidget(self.comboBox, 0, 1, 1, 1)

        self.cropButton = QPushButton(self.widget)
        self.cropButton.setObjectName(u"cropButton")

        self.gridLayout.addWidget(self.cropButton, 1, 0, 1, 1)

        self.fillCombo = QComboBox(self.widget)
        self.fillCombo.addItem("")
        self.fillCombo.addItem("")
        self.fillCombo.setObjectName(u"fillCombo")

        self.gridLayout.addWidget(self.fillCombo, 1, 1, 1, 1)

        self.registerButton = QPushButton(self.widget)
        self.registerButton.setObjectName(u"registerButton")

        self.gridLayout.addWidget(self.registerButton, 2, 0, 1, 1)

        self.registerCombo = QComboBox(self.widget)
        self.registerCombo.addItem("")
        self.registerCombo.addItem("")
        self.registerCombo.addItem("")
        self.registerCombo.addItem("")
        self.registerCombo.addItem("")
        self.registerCombo.setObjectName(u"registerCombo")

        self.gridLayout.addWidget(self.registerCombo, 2, 1, 1, 1)

        self.label_3 = QLabel(self.widget)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout.addWidget(self.label_3, 3, 0, 1, 1)

        self.darkEdit = QLineEdit(self.widget)
        self.darkEdit.setObjectName(u"darkEdit")

        self.gridLayout.addWidget(self.darkEdit, 3, 1, 1, 1)

        self.scaleButton = QPushButton(self.widget)
        self.scaleButton.setObjectName(u"scaleButton")

        self.gridLayout.addWidget(self.scaleButton, 4, 0, 1, 1)

        self.scaleEdit = QLineEdit(self.widget)
        self.scaleEdit.setObjectName(u"scaleEdit")

        self.gridLayout.addWidget(self.scaleEdit, 4, 1, 1, 1)


        self.retranslateUi(Import)

        QMetaObject.connectSlotsByName(Import)
    # setupUi

    def retranslateUi(self, Import):
        Import.setWindowTitle(QCoreApplication.translate("Import", u"Form", None))
        self.acceptButton.setText(QCoreApplication.translate("Import", u"Accept", None))
        self.cancelButton.setText(QCoreApplication.translate("Import", u"Cancel", None))
        self.label.setText(QCoreApplication.translate("Import", u"Base Stack", None))
        self.label_2.setText(QCoreApplication.translate("Import", u"Import Stack", None))
        self.addFrameButton.setText(QCoreApplication.translate("Import", u"Add Frame", None))
        self.interpRadio.setText(QCoreApplication.translate("Import", u"Interpolate Base Stack", None))
        self.roiRadio.setText(QCoreApplication.translate("Import", u"ROI", None))
        self.odRadio.setText(QCoreApplication.translate("Import", u"Optical Density", None))
        self.pushButton_2.setText(QCoreApplication.translate("Import", u"Save Stack", None))
        self.pushButton.setText(QCoreApplication.translate("Import", u"Interpolate", None))
        self.comboBox.setItemText(0, QCoreApplication.translate("Import", u"Nearest", None))
        self.comboBox.setItemText(1, QCoreApplication.translate("Import", u"Spline", None))

        self.cropButton.setText(QCoreApplication.translate("Import", u"Crop", None))
        self.fillCombo.setItemText(0, QCoreApplication.translate("Import", u"Fill Mean", None))
        self.fillCombo.setItemText(1, QCoreApplication.translate("Import", u"Fill Zeroes", None))

        self.registerButton.setText(QCoreApplication.translate("Import", u"Register", None))
        self.registerCombo.setItemText(0, QCoreApplication.translate("Import", u"Translation", None))
        self.registerCombo.setItemText(1, QCoreApplication.translate("Import", u"Rigid", None))
        self.registerCombo.setItemText(2, QCoreApplication.translate("Import", u"Affine", None))
        self.registerCombo.setItemText(3, QCoreApplication.translate("Import", u"Homography", None))
        self.registerCombo.setItemText(4, QCoreApplication.translate("Import", u"All", None))

        self.label_3.setText(QCoreApplication.translate("Import", u"Dark Signal", None))
        self.darkEdit.setText(QCoreApplication.translate("Import", u"0.0", None))
        self.scaleButton.setText(QCoreApplication.translate("Import", u"Scale OD", None))
        self.scaleEdit.setText(QCoreApplication.translate("Import", u"1.0", None))
    # retranslateUi


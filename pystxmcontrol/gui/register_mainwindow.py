# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'register_mainwindow.ui'
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
    QLabel, QProgressBar, QPushButton, QSizePolicy,
    QSlider, QWidget)

from pyqtgraph import ImageView

class Ui_registerWindow(object):
    def setupUi(self, registerWindow):
        if not registerWindow.objectName():
            registerWindow.setObjectName(u"registerWindow")
        registerWindow.resize(2000, 1350)
        self.gridLayout = QGridLayout(registerWindow)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout_2 = QGridLayout()
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.sequentialBox = QCheckBox(registerWindow)
        self.sequentialBox.setObjectName(u"sequentialBox")

        self.gridLayout_2.addWidget(self.sequentialBox, 2, 1, 1, 1)

        self.energyLabel = QLabel(registerWindow)
        self.energyLabel.setObjectName(u"energyLabel")

        self.gridLayout_2.addWidget(self.energyLabel, 19, 2, 1, 1)

        self.referenceBox = QCheckBox(registerWindow)
        self.referenceBox.setObjectName(u"referenceBox")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.referenceBox.sizePolicy().hasHeightForWidth())
        self.referenceBox.setSizePolicy(sizePolicy)

        self.gridLayout_2.addWidget(self.referenceBox, 3, 1, 1, 1)

        self.autoCropCheckbox = QCheckBox(registerWindow)
        self.autoCropCheckbox.setObjectName(u"autoCropCheckbox")
        self.autoCropCheckbox.setChecked(True)

        self.gridLayout_2.addWidget(self.autoCropCheckbox, 8, 1, 1, 1)

        self.applyButton = QPushButton(registerWindow)
        self.applyButton.setObjectName(u"applyButton")

        self.gridLayout_2.addWidget(self.applyButton, 18, 1, 1, 1)

        self.despikeBox = QCheckBox(registerWindow)
        self.despikeBox.setObjectName(u"despikeBox")

        self.gridLayout_2.addWidget(self.despikeBox, 4, 1, 1, 1)

        self.optionsLabel = QLabel(registerWindow)
        self.optionsLabel.setObjectName(u"optionsLabel")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.optionsLabel.sizePolicy().hasHeightForWidth())
        self.optionsLabel.setSizePolicy(sizePolicy1)
        self.optionsLabel.setMaximumSize(QSize(16777215, 50))

        self.gridLayout_2.addWidget(self.optionsLabel, 0, 1, 1, 1, Qt.AlignVCenter)

        self.filterBox = QCheckBox(registerWindow)
        self.filterBox.setObjectName(u"filterBox")

        self.gridLayout_2.addWidget(self.filterBox, 5, 1, 1, 1)

        self.loadButton = QPushButton(registerWindow)
        self.loadButton.setObjectName(u"loadButton")

        self.gridLayout_2.addWidget(self.loadButton, 17, 1, 1, 1)

        self.saveButton = QPushButton(registerWindow)
        self.saveButton.setObjectName(u"saveButton")

        self.gridLayout_2.addWidget(self.saveButton, 16, 1, 1, 1)

        self.progressBar = QProgressBar(registerWindow)
        self.progressBar.setObjectName(u"progressBar")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.progressBar.sizePolicy().hasHeightForWidth())
        self.progressBar.setSizePolicy(sizePolicy2)
        self.progressBar.setValue(24)

        self.gridLayout_2.addWidget(self.progressBar, 15, 1, 1, 1)

        self.mainImage = ImageView(registerWindow)
        self.mainImage.setObjectName(u"mainImage")

        self.gridLayout_2.addWidget(self.mainImage, 0, 2, 19, 3)

        self.posLabel = QLabel(registerWindow)
        self.posLabel.setObjectName(u"posLabel")

        self.gridLayout_2.addWidget(self.posLabel, 19, 3, 1, 1)

        self.typeBox = QComboBox(registerWindow)
        self.typeBox.addItem("")
        self.typeBox.addItem("")
        self.typeBox.addItem("")
        self.typeBox.addItem("")
        self.typeBox.setObjectName(u"typeBox")

        self.gridLayout_2.addWidget(self.typeBox, 6, 1, 1, 1)

        self.manualBox = QCheckBox(registerWindow)
        self.manualBox.setObjectName(u"manualBox")

        self.gridLayout_2.addWidget(self.manualBox, 1, 1, 1, 1)

        self.undoButton = QPushButton(registerWindow)
        self.undoButton.setObjectName(u"undoButton")

        self.gridLayout_2.addWidget(self.undoButton, 19, 1, 1, 1)

        self.verticalSlider = QSlider(registerWindow)
        self.verticalSlider.setObjectName(u"verticalSlider")
        self.verticalSlider.setOrientation(Qt.Vertical)

        self.gridLayout_2.addWidget(self.verticalSlider, 0, 5, 19, 1)

        self.intensityLabel = QLabel(registerWindow)
        self.intensityLabel.setObjectName(u"intensityLabel")

        self.gridLayout_2.addWidget(self.intensityLabel, 19, 4, 1, 1)

        self.roiCheckbox = QCheckBox(registerWindow)
        self.roiCheckbox.setObjectName(u"roiCheckbox")

        self.gridLayout_2.addWidget(self.roiCheckbox, 9, 1, 1, 1)


        self.gridLayout.addLayout(self.gridLayout_2, 0, 0, 1, 1)


        self.retranslateUi(registerWindow)

        QMetaObject.connectSlotsByName(registerWindow)
    # setupUi

    def retranslateUi(self, registerWindow):
        registerWindow.setWindowTitle(QCoreApplication.translate("registerWindow", u"Register Images", None))
        self.sequentialBox.setText(QCoreApplication.translate("registerWindow", u"Sequential", None))
        self.energyLabel.setText(QCoreApplication.translate("registerWindow", u"Energy = ", None))
        self.referenceBox.setText(QCoreApplication.translate("registerWindow", u"Reference Image", None))
        self.autoCropCheckbox.setText(QCoreApplication.translate("registerWindow", u"Auto Crop", None))
        self.applyButton.setText(QCoreApplication.translate("registerWindow", u"Apply", None))
        self.despikeBox.setText(QCoreApplication.translate("registerWindow", u"Despike", None))
        self.optionsLabel.setText(QCoreApplication.translate("registerWindow", u"Alignment Options", None))
        self.filterBox.setText(QCoreApplication.translate("registerWindow", u"Edge Filter", None))
        self.loadButton.setText(QCoreApplication.translate("registerWindow", u"Load Shifts", None))
        self.saveButton.setText(QCoreApplication.translate("registerWindow", u"Save Shifts", None))
        self.posLabel.setText(QCoreApplication.translate("registerWindow", u"X,Y = ", None))
        self.typeBox.setItemText(0, QCoreApplication.translate("registerWindow", u"Translation", None))
        self.typeBox.setItemText(1, QCoreApplication.translate("registerWindow", u"Rigid", None))
        self.typeBox.setItemText(2, QCoreApplication.translate("registerWindow", u"Affine", None))
        self.typeBox.setItemText(3, QCoreApplication.translate("registerWindow", u"Homographic", None))

        self.manualBox.setText(QCoreApplication.translate("registerWindow", u"Manual", None))
        self.undoButton.setText(QCoreApplication.translate("registerWindow", u"Undo", None))
        self.intensityLabel.setText(QCoreApplication.translate("registerWindow", u"Intensity = ", None))
        self.roiCheckbox.setText(QCoreApplication.translate("registerWindow", u"Crop to ROI", None))
    # retranslateUi


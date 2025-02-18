# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'bkg_mainwindow.ui'
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
from PySide6.QtWidgets import (QApplication, QGridLayout, QLabel, QPushButton,
    QScrollBar, QSizePolicy, QWidget)

from pyqtgraph import (ImageView, PlotWidget)

class Ui_bkgWindow(object):
    def setupUi(self, bkgWindow):
        if not bkgWindow.objectName():
            bkgWindow.setObjectName(u"bkgWindow")
        bkgWindow.resize(1092, 540)
        self.gridLayout_4 = QGridLayout(bkgWindow)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.gridLayout_3 = QGridLayout()
        self.gridLayout_3.setObjectName(u"gridLayout_3")
        self.rawMaps = ImageView(bkgWindow)
        self.rawMaps.setObjectName(u"rawMaps")

        self.gridLayout_3.addWidget(self.rawMaps, 0, 0, 1, 1)

        self.rawSlider = QScrollBar(bkgWindow)
        self.rawSlider.setObjectName(u"rawSlider")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.rawSlider.sizePolicy().hasHeightForWidth())
        self.rawSlider.setSizePolicy(sizePolicy)
        self.rawSlider.setOrientation(Qt.Vertical)

        self.gridLayout_3.addWidget(self.rawSlider, 0, 1, 1, 1)

        self.label = QLabel(bkgWindow)
        self.label.setObjectName(u"label")

        self.gridLayout_3.addWidget(self.label, 1, 0, 1, 1)


        self.gridLayout_4.addLayout(self.gridLayout_3, 0, 0, 1, 1)

        self.gridLayout_5 = QGridLayout()
        self.gridLayout_5.setObjectName(u"gridLayout_5")
        self.bkgSubtractMaps = ImageView(bkgWindow)
        self.bkgSubtractMaps.setObjectName(u"bkgSubtractMaps")

        self.gridLayout_5.addWidget(self.bkgSubtractMaps, 0, 0, 1, 1)

        self.bkgSubtractSlider = QScrollBar(bkgWindow)
        self.bkgSubtractSlider.setObjectName(u"bkgSubtractSlider")
        sizePolicy.setHeightForWidth(self.bkgSubtractSlider.sizePolicy().hasHeightForWidth())
        self.bkgSubtractSlider.setSizePolicy(sizePolicy)
        self.bkgSubtractSlider.setOrientation(Qt.Vertical)

        self.gridLayout_5.addWidget(self.bkgSubtractSlider, 0, 1, 1, 1)

        self.label_4 = QLabel(bkgWindow)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_5.addWidget(self.label_4, 1, 0, 1, 1)


        self.gridLayout_4.addLayout(self.gridLayout_5, 0, 1, 1, 1)

        self.gridLayout = QGridLayout()
        self.gridLayout.setObjectName(u"gridLayout")
        self.bkgMaps = ImageView(bkgWindow)
        self.bkgMaps.setObjectName(u"bkgMaps")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.bkgMaps.sizePolicy().hasHeightForWidth())
        self.bkgMaps.setSizePolicy(sizePolicy1)

        self.gridLayout.addWidget(self.bkgMaps, 0, 0, 1, 4)

        self.bkgSlider = QScrollBar(bkgWindow)
        self.bkgSlider.setObjectName(u"bkgSlider")
        sizePolicy.setHeightForWidth(self.bkgSlider.sizePolicy().hasHeightForWidth())
        self.bkgSlider.setSizePolicy(sizePolicy)
        self.bkgSlider.setOrientation(Qt.Vertical)

        self.gridLayout.addWidget(self.bkgSlider, 0, 4, 1, 1)

        self.label_3 = QLabel(bkgWindow)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout.addWidget(self.label_3, 1, 0, 1, 1)

        self.setROIButton = QPushButton(bkgWindow)
        self.setROIButton.setObjectName(u"setROIButton")
        palette = QPalette()
        brush = QBrush(QColor(85, 0, 255, 255))
        brush.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.ButtonText, brush)
        palette.setBrush(QPalette.Inactive, QPalette.ButtonText, brush)
        brush1 = QBrush(QColor(120, 120, 120, 255))
        brush1.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Disabled, QPalette.ButtonText, brush1)
        self.setROIButton.setPalette(palette)

        self.gridLayout.addWidget(self.setROIButton, 1, 1, 1, 1)

        self.getbkgFromROIButton = QPushButton(bkgWindow)
        self.getbkgFromROIButton.setObjectName(u"getbkgFromROIButton")
        palette1 = QPalette()
        brush2 = QBrush(QColor(0, 170, 0, 255))
        brush2.setStyle(Qt.SolidPattern)
        palette1.setBrush(QPalette.Active, QPalette.ButtonText, brush2)
        palette1.setBrush(QPalette.Inactive, QPalette.ButtonText, brush2)
        palette1.setBrush(QPalette.Disabled, QPalette.ButtonText, brush1)
        self.getbkgFromROIButton.setPalette(palette1)

        self.gridLayout.addWidget(self.getbkgFromROIButton, 1, 2, 1, 1)

        self.countRate = QLabel(bkgWindow)
        self.countRate.setObjectName(u"countRate")

        self.gridLayout.addWidget(self.countRate, 1, 3, 1, 1)


        self.gridLayout_4.addLayout(self.gridLayout, 1, 0, 1, 1)

        self.gridLayout_2 = QGridLayout()
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.bkgSpectra = PlotWidget(bkgWindow)
        self.bkgSpectra.setObjectName(u"bkgSpectra")
        sizePolicy1.setHeightForWidth(self.bkgSpectra.sizePolicy().hasHeightForWidth())
        self.bkgSpectra.setSizePolicy(sizePolicy1)

        self.gridLayout_2.addWidget(self.bkgSpectra, 0, 0, 1, 4)

        self.LoadBKGFrameButton = QPushButton(bkgWindow)
        self.LoadBKGFrameButton.setObjectName(u"LoadBKGFrameButton")
        palette2 = QPalette()
        brush3 = QBrush(QColor(255, 0, 255, 255))
        brush3.setStyle(Qt.SolidPattern)
        palette2.setBrush(QPalette.Active, QPalette.ButtonText, brush3)
        palette2.setBrush(QPalette.Inactive, QPalette.ButtonText, brush3)
        palette2.setBrush(QPalette.Disabled, QPalette.ButtonText, brush1)
        self.LoadBKGFrameButton.setPalette(palette2)

        self.gridLayout_2.addWidget(self.LoadBKGFrameButton, 1, 0, 1, 1)

        self.bkgRemovalButton = QPushButton(bkgWindow)
        self.bkgRemovalButton.setObjectName(u"bkgRemovalButton")
        palette3 = QPalette()
        brush4 = QBrush(QColor(0, 0, 255, 255))
        brush4.setStyle(Qt.SolidPattern)
        palette3.setBrush(QPalette.Active, QPalette.ButtonText, brush4)
        palette3.setBrush(QPalette.Inactive, QPalette.ButtonText, brush4)
        palette3.setBrush(QPalette.Disabled, QPalette.ButtonText, brush1)
        self.bkgRemovalButton.setPalette(palette3)

        self.gridLayout_2.addWidget(self.bkgRemovalButton, 1, 1, 1, 1)

        self.bkgUndoButton = QPushButton(bkgWindow)
        self.bkgUndoButton.setObjectName(u"bkgUndoButton")
        palette4 = QPalette()
        brush5 = QBrush(QColor(255, 0, 0, 255))
        brush5.setStyle(Qt.SolidPattern)
        palette4.setBrush(QPalette.Active, QPalette.ButtonText, brush5)
        palette4.setBrush(QPalette.Inactive, QPalette.ButtonText, brush5)
        palette4.setBrush(QPalette.Disabled, QPalette.ButtonText, brush1)
        self.bkgUndoButton.setPalette(palette4)

        self.gridLayout_2.addWidget(self.bkgUndoButton, 1, 2, 1, 1)

        self.bkgApplyButton = QPushButton(bkgWindow)
        self.bkgApplyButton.setObjectName(u"bkgApplyButton")
        palette5 = QPalette()
        brush6 = QBrush(QColor(170, 0, 0, 255))
        brush6.setStyle(Qt.SolidPattern)
        palette5.setBrush(QPalette.Active, QPalette.ButtonText, brush6)
        palette5.setBrush(QPalette.Inactive, QPalette.ButtonText, brush6)
        palette5.setBrush(QPalette.Disabled, QPalette.ButtonText, brush1)
        self.bkgApplyButton.setPalette(palette5)

        self.gridLayout_2.addWidget(self.bkgApplyButton, 1, 3, 1, 1)


        self.gridLayout_4.addLayout(self.gridLayout_2, 1, 1, 1, 1)


        self.retranslateUi(bkgWindow)

        QMetaObject.connectSlotsByName(bkgWindow)
    # setupUi

    def retranslateUi(self, bkgWindow):
        bkgWindow.setWindowTitle(QCoreApplication.translate("bkgWindow", u"bkg Viewer", None))
        self.label.setText(QCoreApplication.translate("bkgWindow", u"Raw Frames", None))
        self.label_4.setText(QCoreApplication.translate("bkgWindow", u"BKG Subtracted Frames", None))
        self.label_3.setText(QCoreApplication.translate("bkgWindow", u"BKG Frame", None))
        self.setROIButton.setText(QCoreApplication.translate("bkgWindow", u"Set ROI", None))
        self.getbkgFromROIButton.setText(QCoreApplication.translate("bkgWindow", u"Get count_rate from ROI", None))
        self.countRate.setText(QCoreApplication.translate("bkgWindow", u"count_rate:", None))
        self.LoadBKGFrameButton.setText(QCoreApplication.translate("bkgWindow", u"Load bkg Frame", None))
        self.bkgRemovalButton.setText(QCoreApplication.translate("bkgWindow", u"BKG Removal", None))
        self.bkgUndoButton.setText(QCoreApplication.translate("bkgWindow", u"Undo", None))
        self.bkgApplyButton.setText(QCoreApplication.translate("bkgWindow", u"Apply", None))
    # retranslateUi


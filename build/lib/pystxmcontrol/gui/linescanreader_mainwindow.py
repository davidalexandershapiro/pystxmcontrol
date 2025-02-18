# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'linescanreader_mainwindow.ui'
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
from PySide6.QtWidgets import (QApplication, QCheckBox, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QWidget)

from pyqtgraph import (ImageView, PlotWidget)

class Ui_CustomWidget(object):
    def setupUi(self, CustomWidget):
        if not CustomWidget.objectName():
            CustomWidget.setObjectName(u"CustomWidget")
        CustomWidget.resize(1127, 685)
        self.gridLayout = QGridLayout(CustomWidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.linearRegionCheckBox = QCheckBox(CustomWidget)
        self.linearRegionCheckBox.setObjectName(u"linearRegionCheckBox")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.linearRegionCheckBox.sizePolicy().hasHeightForWidth())
        self.linearRegionCheckBox.setSizePolicy(sizePolicy)

        self.horizontalLayout.addWidget(self.linearRegionCheckBox)

        self.backgroundCheckBox = QCheckBox(CustomWidget)
        self.backgroundCheckBox.setObjectName(u"backgroundCheckBox")
        sizePolicy.setHeightForWidth(self.backgroundCheckBox.sizePolicy().hasHeightForWidth())
        self.backgroundCheckBox.setSizePolicy(sizePolicy)

        self.horizontalLayout.addWidget(self.backgroundCheckBox)

        self.displayOD = QCheckBox(CustomWidget)
        self.displayOD.setObjectName(u"displayOD")

        self.horizontalLayout.addWidget(self.displayOD)

        self.offsetLabel = QLabel(CustomWidget)
        self.offsetLabel.setObjectName(u"offsetLabel")
        self.offsetLabel.setMaximumSize(QSize(50, 16777215))

        self.horizontalLayout.addWidget(self.offsetLabel)

        self.dataOffset = QLineEdit(CustomWidget)
        self.dataOffset.setObjectName(u"dataOffset")
        self.dataOffset.setMaximumSize(QSize(100, 16777215))

        self.horizontalLayout.addWidget(self.dataOffset)


        self.gridLayout.addLayout(self.horizontalLayout, 4, 0, 2, 1)

        self.horizontalLayout_3 = QHBoxLayout()
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.energyLabel = QLabel(CustomWidget)
        self.energyLabel.setObjectName(u"energyLabel")

        self.horizontalLayout_3.addWidget(self.energyLabel)

        self.dataLabel = QLabel(CustomWidget)
        self.dataLabel.setObjectName(u"dataLabel")

        self.horizontalLayout_3.addWidget(self.dataLabel)

        self.fileLoadButton = QPushButton(CustomWidget)
        self.fileLoadButton.setObjectName(u"fileLoadButton")

        self.horizontalLayout_3.addWidget(self.fileLoadButton)

        self.fileSaveButton = QPushButton(CustomWidget)
        self.fileSaveButton.setObjectName(u"fileSaveButton")

        self.horizontalLayout_3.addWidget(self.fileSaveButton)


        self.gridLayout.addLayout(self.horizontalLayout_3, 4, 1, 2, 1)

        self.label = QLabel(CustomWidget)
        self.label.setObjectName(u"label")

        self.gridLayout.addWidget(self.label, 0, 1, 1, 1)

        self.bgPlotWidget = PlotWidget(CustomWidget)
        self.bgPlotWidget.setObjectName(u"bgPlotWidget")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.bgPlotWidget.sizePolicy().hasHeightForWidth())
        self.bgPlotWidget.setSizePolicy(sizePolicy1)
        self.bgPlotWidget.setMinimumSize(QSize(200, 0))
        self.bgPlotWidget.setMaximumSize(QSize(100000, 300))

        self.gridLayout.addWidget(self.bgPlotWidget, 1, 1, 1, 1)

        self.label_2 = QLabel(CustomWidget)
        self.label_2.setObjectName(u"label_2")

        self.gridLayout.addWidget(self.label_2, 2, 1, 1, 1)

        self.mainImage = ImageView(CustomWidget)
        self.mainImage.setObjectName(u"mainImage")
        sizePolicy1.setHeightForWidth(self.mainImage.sizePolicy().hasHeightForWidth())
        self.mainImage.setSizePolicy(sizePolicy1)
        self.mainImage.setMinimumSize(QSize(400, 0))

        self.gridLayout.addWidget(self.mainImage, 1, 0, 3, 1)

        self.label_3 = QLabel(CustomWidget)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout.addWidget(self.label_3, 0, 0, 1, 1)

        self.specPlotWidget = PlotWidget(CustomWidget)
        self.specPlotWidget.setObjectName(u"specPlotWidget")
        self.specPlotWidget.setMinimumSize(QSize(200, 0))

        self.gridLayout.addWidget(self.specPlotWidget, 3, 1, 1, 1)


        self.retranslateUi(CustomWidget)

        QMetaObject.connectSlotsByName(CustomWidget)
    # setupUi

    def retranslateUi(self, CustomWidget):
        CustomWidget.setWindowTitle(QCoreApplication.translate("CustomWidget", u"LineScanReader", None))
        self.linearRegionCheckBox.setText(QCoreApplication.translate("CustomWidget", u"ROI", None))
        self.backgroundCheckBox.setText(QCoreApplication.translate("CustomWidget", u"Background", None))
        self.displayOD.setText(QCoreApplication.translate("CustomWidget", u"Optical Density", None))
        self.offsetLabel.setText(QCoreApplication.translate("CustomWidget", u"Offset", None))
        self.energyLabel.setText("")
        self.dataLabel.setText("")
        self.fileLoadButton.setText(QCoreApplication.translate("CustomWidget", u"Load Data", None))
        self.fileSaveButton.setText(QCoreApplication.translate("CustomWidget", u"Save", None))
        self.label.setText(QCoreApplication.translate("CustomWidget", u"Background Spectrum", None))
        self.label_2.setText(QCoreApplication.translate("CustomWidget", u"Sample Spectrum", None))
        self.label_3.setText(QCoreApplication.translate("CustomWidget", u"Linescan Data", None))
    # retranslateUi


# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'regionDef.ui'
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
from PySide6.QtWidgets import (QApplication, QGridLayout, QLabel, QLineEdit,
    QSizePolicy, QWidget)

class Ui_regionDef(object):
    def setupUi(self, regionDef):
        if not regionDef.objectName():
            regionDef.setObjectName(u"regionDef")
        regionDef.resize(816, 105)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(regionDef.sizePolicy().hasHeightForWidth())
        regionDef.setSizePolicy(sizePolicy)
        regionDef.setMinimumSize(QSize(0, 105))
        regionDef.setMaximumSize(QSize(16777215, 105))
        self.scanRegionDef = QWidget(regionDef)
        self.scanRegionDef.setObjectName(u"scanRegionDef")
        self.scanRegionDef.setGeometry(QRect(0, 0, 600, 102))
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Maximum)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.scanRegionDef.sizePolicy().hasHeightForWidth())
        self.scanRegionDef.setSizePolicy(sizePolicy1)
        self.scanRegionDef.setMinimumSize(QSize(600, 100))
        self.scanRegionDef.setMaximumSize(QSize(600, 16777215))
        self.gridLayout = QGridLayout(self.scanRegionDef)
        self.gridLayout.setObjectName(u"gridLayout")
        self.xNPoints = QLineEdit(self.scanRegionDef)
        self.xNPoints.setObjectName(u"xNPoints")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.xNPoints.sizePolicy().hasHeightForWidth())
        self.xNPoints.setSizePolicy(sizePolicy2)
        self.xNPoints.setMinimumSize(QSize(120, 0))
        self.xNPoints.setAlignment(Qt.AlignCenter)

        self.gridLayout.addWidget(self.xNPoints, 1, 5, 1, 1, Qt.AlignHCenter)

        self.yCenter = QLineEdit(self.scanRegionDef)
        self.yCenter.setObjectName(u"yCenter")
        sizePolicy2.setHeightForWidth(self.yCenter.sizePolicy().hasHeightForWidth())
        self.yCenter.setSizePolicy(sizePolicy2)
        self.yCenter.setMinimumSize(QSize(120, 0))
        self.yCenter.setAlignment(Qt.AlignCenter)

        self.gridLayout.addWidget(self.yCenter, 2, 3, 1, 1, Qt.AlignHCenter)

        self.yStep = QLineEdit(self.scanRegionDef)
        self.yStep.setObjectName(u"yStep")
        sizePolicy2.setHeightForWidth(self.yStep.sizePolicy().hasHeightForWidth())
        self.yStep.setSizePolicy(sizePolicy2)
        self.yStep.setMinimumSize(QSize(120, 0))
        self.yStep.setAlignment(Qt.AlignCenter)

        self.gridLayout.addWidget(self.yStep, 2, 6, 1, 1, Qt.AlignHCenter)

        self.xRange = QLineEdit(self.scanRegionDef)
        self.xRange.setObjectName(u"xRange")
        sizePolicy2.setHeightForWidth(self.xRange.sizePolicy().hasHeightForWidth())
        self.xRange.setSizePolicy(sizePolicy2)
        self.xRange.setMinimumSize(QSize(120, 0))
        self.xRange.setAlignment(Qt.AlignCenter)

        self.gridLayout.addWidget(self.xRange, 1, 4, 1, 1, Qt.AlignHCenter)

        self.xStep = QLineEdit(self.scanRegionDef)
        self.xStep.setObjectName(u"xStep")
        sizePolicy2.setHeightForWidth(self.xStep.sizePolicy().hasHeightForWidth())
        self.xStep.setSizePolicy(sizePolicy2)
        self.xStep.setMinimumSize(QSize(120, 0))
        self.xStep.setAlignment(Qt.AlignCenter)

        self.gridLayout.addWidget(self.xStep, 1, 6, 1, 1, Qt.AlignHCenter)

        self.yNPoints = QLineEdit(self.scanRegionDef)
        self.yNPoints.setObjectName(u"yNPoints")
        sizePolicy2.setHeightForWidth(self.yNPoints.sizePolicy().hasHeightForWidth())
        self.yNPoints.setSizePolicy(sizePolicy2)
        self.yNPoints.setMinimumSize(QSize(120, 0))
        self.yNPoints.setAlignment(Qt.AlignCenter)

        self.gridLayout.addWidget(self.yNPoints, 2, 5, 1, 1, Qt.AlignHCenter)

        self.label_13 = QLabel(self.scanRegionDef)
        self.label_13.setObjectName(u"label_13")

        self.gridLayout.addWidget(self.label_13, 2, 1, 1, 1, Qt.AlignVCenter)

        self.label_12 = QLabel(self.scanRegionDef)
        self.label_12.setObjectName(u"label_12")

        self.gridLayout.addWidget(self.label_12, 1, 1, 1, 1, Qt.AlignVCenter)

        self.yRange = QLineEdit(self.scanRegionDef)
        self.yRange.setObjectName(u"yRange")
        sizePolicy2.setHeightForWidth(self.yRange.sizePolicy().hasHeightForWidth())
        self.yRange.setSizePolicy(sizePolicy2)
        self.yRange.setMinimumSize(QSize(120, 0))
        self.yRange.setAlignment(Qt.AlignCenter)

        self.gridLayout.addWidget(self.yRange, 2, 4, 1, 1, Qt.AlignHCenter)

        self.label_14 = QLabel(self.scanRegionDef)
        self.label_14.setObjectName(u"label_14")

        self.gridLayout.addWidget(self.label_14, 0, 3, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)

        self.label_15 = QLabel(self.scanRegionDef)
        self.label_15.setObjectName(u"label_15")

        self.gridLayout.addWidget(self.label_15, 0, 4, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)

        self.label_16 = QLabel(self.scanRegionDef)
        self.label_16.setObjectName(u"label_16")

        self.gridLayout.addWidget(self.label_16, 0, 5, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)

        self.label_17 = QLabel(self.scanRegionDef)
        self.label_17.setObjectName(u"label_17")

        self.gridLayout.addWidget(self.label_17, 0, 6, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)

        self.xCenter = QLineEdit(self.scanRegionDef)
        self.xCenter.setObjectName(u"xCenter")
        sizePolicy2.setHeightForWidth(self.xCenter.sizePolicy().hasHeightForWidth())
        self.xCenter.setSizePolicy(sizePolicy2)
        self.xCenter.setMinimumSize(QSize(120, 0))
        self.xCenter.setAlignment(Qt.AlignCenter)

        self.gridLayout.addWidget(self.xCenter, 1, 3, 1, 1)

        self.regNum = QLabel(self.scanRegionDef)
        self.regNum.setObjectName(u"regNum")
        font = QFont()
        font.setBold(True)
        self.regNum.setFont(font)

        self.gridLayout.addWidget(self.regNum, 0, 1, 1, 1, Qt.AlignBottom)


        self.retranslateUi(regionDef)

        QMetaObject.connectSlotsByName(regionDef)
    # setupUi

    def retranslateUi(self, regionDef):
        regionDef.setWindowTitle(QCoreApplication.translate("regionDef", u"Form", None))
        self.label_13.setText(QCoreApplication.translate("regionDef", u"<html><head/><body><p>Y Position</p></body></html>", None))
        self.label_12.setText(QCoreApplication.translate("regionDef", u"<html><head/><body><p>X Position</p></body></html>", None))
        self.label_14.setText(QCoreApplication.translate("regionDef", u"<html><head/><body><p>Center</p></body></html>", None))
        self.label_15.setText(QCoreApplication.translate("regionDef", u"<html><head/><body><p>Range</p></body></html>", None))
        self.label_16.setText(QCoreApplication.translate("regionDef", u"<html><head/><body><p>N Points</p></body></html>", None))
        self.label_17.setText(QCoreApplication.translate("regionDef", u"<html><head/><body><p>Step Size</p></body></html>", None))
        self.regNum.setText(QCoreApplication.translate("regionDef", u"TextLabel", None))
    # retranslateUi


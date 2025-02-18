# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'energyDef.ui'
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

class Ui_energyDef(object):
    def setupUi(self, energyDef):
        if not energyDef.objectName():
            energyDef.setObjectName(u"energyDef")
        energyDef.resize(600, 75)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(energyDef.sizePolicy().hasHeightForWidth())
        energyDef.setSizePolicy(sizePolicy)
        energyDef.setMinimumSize(QSize(600, 75))
        energyDef.setMaximumSize(QSize(600, 75))
        self.layoutWidget_2 = QWidget(energyDef)
        self.layoutWidget_2.setObjectName(u"layoutWidget_2")
        self.layoutWidget_2.setGeometry(QRect(0, 0, 571, 51))
        self.gridLayout_2 = QGridLayout(self.layoutWidget_2)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.gridLayout_2.setContentsMargins(0, 0, 0, 0)
        self.label_3 = QLabel(self.layoutWidget_2)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout_2.addWidget(self.label_3, 0, 1, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)

        self.label_4 = QLabel(self.layoutWidget_2)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_2.addWidget(self.label_4, 0, 5, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)

        self.energyStep = QLineEdit(self.layoutWidget_2)
        self.energyStep.setObjectName(u"energyStep")
        self.energyStep.setAlignment(Qt.AlignCenter)

        self.gridLayout_2.addWidget(self.energyStep, 1, 3, 1, 1, Qt.AlignHCenter)

        self.label_18 = QLabel(self.layoutWidget_2)
        self.label_18.setObjectName(u"label_18")

        self.gridLayout_2.addWidget(self.label_18, 0, 2, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)

        self.regNum = QLabel(self.layoutWidget_2)
        self.regNum.setObjectName(u"regNum")
        font = QFont()
        font.setBold(True)
        self.regNum.setFont(font)

        self.gridLayout_2.addWidget(self.regNum, 1, 0, 1, 1)

        self.energyStart = QLineEdit(self.layoutWidget_2)
        self.energyStart.setObjectName(u"energyStart")
        self.energyStart.setAlignment(Qt.AlignCenter)

        self.gridLayout_2.addWidget(self.energyStart, 1, 1, 1, 1)

        self.energyStop = QLineEdit(self.layoutWidget_2)
        self.energyStop.setObjectName(u"energyStop")
        self.energyStop.setAlignment(Qt.AlignCenter)

        self.gridLayout_2.addWidget(self.energyStop, 1, 2, 1, 1, Qt.AlignHCenter)

        self.dwellTime = QLineEdit(self.layoutWidget_2)
        self.dwellTime.setObjectName(u"dwellTime")
        self.dwellTime.setAlignment(Qt.AlignCenter)

        self.gridLayout_2.addWidget(self.dwellTime, 1, 5, 1, 1, Qt.AlignHCenter)

        self.label_19 = QLabel(self.layoutWidget_2)
        self.label_19.setObjectName(u"label_19")

        self.gridLayout_2.addWidget(self.label_19, 0, 3, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)

        self.nEnergies = QLineEdit(self.layoutWidget_2)
        self.nEnergies.setObjectName(u"nEnergies")
        self.nEnergies.setAlignment(Qt.AlignCenter)

        self.gridLayout_2.addWidget(self.nEnergies, 1, 4, 1, 1, Qt.AlignHCenter)

        self.label_21 = QLabel(self.layoutWidget_2)
        self.label_21.setObjectName(u"label_21")

        self.gridLayout_2.addWidget(self.label_21, 0, 4, 1, 1, Qt.AlignHCenter|Qt.AlignBottom)


        self.retranslateUi(energyDef)

        QMetaObject.connectSlotsByName(energyDef)
    # setupUi

    def retranslateUi(self, energyDef):
        energyDef.setWindowTitle(QCoreApplication.translate("energyDef", u"Form", None))
        self.label_3.setText(QCoreApplication.translate("energyDef", u"Start", None))
        self.label_4.setText(QCoreApplication.translate("energyDef", u"Dwell Time", None))
        self.label_18.setText(QCoreApplication.translate("energyDef", u"Stop", None))
        self.regNum.setText(QCoreApplication.translate("energyDef", u"Energy Region 1", None))
        self.label_19.setText(QCoreApplication.translate("energyDef", u"Step", None))
        self.label_21.setText(QCoreApplication.translate("energyDef", u"N Energies", None))
    # retranslateUi


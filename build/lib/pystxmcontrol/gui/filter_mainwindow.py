# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'filter_mainwindow.ui'
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
    QLabel, QLineEdit, QPushButton, QSizePolicy,
    QSlider, QWidget)

from pyqtgraph import ImageView

class Ui_filterWindow(object):
    def setupUi(self, filterWindow):
        if not filterWindow.objectName():
            filterWindow.setObjectName(u"filterWindow")
        filterWindow.resize(2000, 1350)
        self.gridLayout = QGridLayout(filterWindow)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout_2 = QGridLayout()
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.filterWidthLabel = QLabel(filterWindow)
        self.filterWidthLabel.setObjectName(u"filterWidthLabel")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.filterWidthLabel.sizePolicy().hasHeightForWidth())
        self.filterWidthLabel.setSizePolicy(sizePolicy)
        self.filterWidthLabel.setMaximumSize(QSize(16777215, 50))

        self.gridLayout_2.addWidget(self.filterWidthLabel, 0, 1, 1, 1, Qt.AlignBottom)

        self.selectXYBox = QCheckBox(filterWindow)
        self.selectXYBox.setObjectName(u"selectXYBox")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.selectXYBox.sizePolicy().hasHeightForWidth())
        self.selectXYBox.setSizePolicy(sizePolicy1)

        self.gridLayout_2.addWidget(self.selectXYBox, 5, 1, 1, 1)

        self.undoButton = QPushButton(filterWindow)
        self.undoButton.setObjectName(u"undoButton")

        self.gridLayout_2.addWidget(self.undoButton, 13, 1, 1, 1)

        self.selectYBox = QCheckBox(filterWindow)
        self.selectYBox.setObjectName(u"selectYBox")

        self.gridLayout_2.addWidget(self.selectYBox, 3, 1, 1, 1)

        self.intensityLabel = QLabel(filterWindow)
        self.intensityLabel.setObjectName(u"intensityLabel")

        self.gridLayout_2.addWidget(self.intensityLabel, 13, 4, 1, 1)

        self.filterTypeBox = QComboBox(filterWindow)
        self.filterTypeBox.addItem("")
        self.filterTypeBox.addItem("")
        self.filterTypeBox.addItem("")
        self.filterTypeBox.setObjectName(u"filterTypeBox")

        self.gridLayout_2.addWidget(self.filterTypeBox, 2, 1, 1, 1)

        self.verticalSlider = QSlider(filterWindow)
        self.verticalSlider.setObjectName(u"verticalSlider")
        self.verticalSlider.setOrientation(Qt.Vertical)

        self.gridLayout_2.addWidget(self.verticalSlider, 0, 5, 13, 1)

        self.mainImage = ImageView(filterWindow)
        self.mainImage.setObjectName(u"mainImage")

        self.gridLayout_2.addWidget(self.mainImage, 0, 2, 13, 3)

        self.selectXBox = QCheckBox(filterWindow)
        self.selectXBox.setObjectName(u"selectXBox")

        self.gridLayout_2.addWidget(self.selectXBox, 4, 1, 1, 1)

        self.posLabel = QLabel(filterWindow)
        self.posLabel.setObjectName(u"posLabel")

        self.gridLayout_2.addWidget(self.posLabel, 13, 3, 1, 1)

        self.energyLabel = QLabel(filterWindow)
        self.energyLabel.setObjectName(u"energyLabel")

        self.gridLayout_2.addWidget(self.energyLabel, 13, 2, 1, 1)

        self.darkLabel = QLabel(filterWindow)
        self.darkLabel.setObjectName(u"darkLabel")

        self.gridLayout_2.addWidget(self.darkLabel, 8, 1, 1, 1, Qt.AlignBottom)

        self.applyButton = QPushButton(filterWindow)
        self.applyButton.setObjectName(u"applyButton")

        self.gridLayout_2.addWidget(self.applyButton, 12, 1, 1, 1)

        self.jumpBox = QCheckBox(filterWindow)
        self.jumpBox.setObjectName(u"jumpBox")

        self.gridLayout_2.addWidget(self.jumpBox, 6, 1, 1, 1)

        self.despikeBox = QCheckBox(filterWindow)
        self.despikeBox.setObjectName(u"despikeBox")

        self.gridLayout_2.addWidget(self.despikeBox, 7, 1, 1, 1)

        self.kernelEdit = QLineEdit(filterWindow)
        self.kernelEdit.setObjectName(u"kernelEdit")
        sizePolicy1.setHeightForWidth(self.kernelEdit.sizePolicy().hasHeightForWidth())
        self.kernelEdit.setSizePolicy(sizePolicy1)

        self.gridLayout_2.addWidget(self.kernelEdit, 1, 1, 1, 1)

        self.darkValueEdit = QLineEdit(filterWindow)
        self.darkValueEdit.setObjectName(u"darkValueEdit")
        sizePolicy1.setHeightForWidth(self.darkValueEdit.sizePolicy().hasHeightForWidth())
        self.darkValueEdit.setSizePolicy(sizePolicy1)

        self.gridLayout_2.addWidget(self.darkValueEdit, 9, 1, 1, 1)


        self.gridLayout.addLayout(self.gridLayout_2, 1, 0, 1, 1)


        self.retranslateUi(filterWindow)

        QMetaObject.connectSlotsByName(filterWindow)
    # setupUi

    def retranslateUi(self, filterWindow):
        filterWindow.setWindowTitle(QCoreApplication.translate("filterWindow", u"Image Filter", None))
        self.filterWidthLabel.setText(QCoreApplication.translate("filterWindow", u"Filter Kernel Width", None))
        self.selectXYBox.setText(QCoreApplication.translate("filterWindow", u"X and Y", None))
        self.undoButton.setText(QCoreApplication.translate("filterWindow", u"Undo", None))
        self.selectYBox.setText(QCoreApplication.translate("filterWindow", u"Y", None))
        self.intensityLabel.setText(QCoreApplication.translate("filterWindow", u"Intensity = ", None))
        self.filterTypeBox.setItemText(0, QCoreApplication.translate("filterWindow", u"Wiener", None))
        self.filterTypeBox.setItemText(1, QCoreApplication.translate("filterWindow", u"Median", None))
        self.filterTypeBox.setItemText(2, QCoreApplication.translate("filterWindow", u"Non-Local Means", None))

        self.selectXBox.setText(QCoreApplication.translate("filterWindow", u"X", None))
        self.posLabel.setText(QCoreApplication.translate("filterWindow", u"X,Y = ", None))
        self.energyLabel.setText(QCoreApplication.translate("filterWindow", u"Energy = ", None))
        self.darkLabel.setText(QCoreApplication.translate("filterWindow", u"Subtract Dark Field", None))
        self.applyButton.setText(QCoreApplication.translate("filterWindow", u"Apply", None))
        self.jumpBox.setText(QCoreApplication.translate("filterWindow", u"Edge Jumps", None))
        self.despikeBox.setText(QCoreApplication.translate("filterWindow", u"Despike", None))
    # retranslateUi


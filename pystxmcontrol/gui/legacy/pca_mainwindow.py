# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'pca_mainwindow.ui'
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
    QLabel, QPushButton, QScrollBar, QSizePolicy,
    QWidget)

from pyqtgraph import (ImageView, PlotWidget)

class Ui_pcaViewer(object):
    def setupUi(self, pcaViewer):
        if not pcaViewer.objectName():
            pcaViewer.setObjectName(u"pcaViewer")
        pcaViewer.resize(1061, 900)
        self.gridLayout = QGridLayout(pcaViewer)
        self.gridLayout.setObjectName(u"gridLayout")
        self.stackSlider = QScrollBar(pcaViewer)
        self.stackSlider.setObjectName(u"stackSlider")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.stackSlider.sizePolicy().hasHeightForWidth())
        self.stackSlider.setSizePolicy(sizePolicy)
        self.stackSlider.setOrientation(Qt.Vertical)

        self.gridLayout.addWidget(self.stackSlider, 1, 3, 1, 1)

        self.pcaCombo = QComboBox(pcaViewer)
        self.pcaCombo.addItem("")
        self.pcaCombo.addItem("")
        self.pcaCombo.setObjectName(u"pcaCombo")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.pcaCombo.sizePolicy().hasHeightForWidth())
        self.pcaCombo.setSizePolicy(sizePolicy1)

        self.gridLayout.addWidget(self.pcaCombo, 2, 0, 1, 1)

        self.pcaMaps = ImageView(pcaViewer)
        self.pcaMaps.setObjectName(u"pcaMaps")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.pcaMaps.sizePolicy().hasHeightForWidth())
        self.pcaMaps.setSizePolicy(sizePolicy2)

        self.gridLayout.addWidget(self.pcaMaps, 1, 0, 1, 1)

        self.stackCombo = QComboBox(pcaViewer)
        self.stackCombo.addItem("")
        self.stackCombo.addItem("")
        self.stackCombo.addItem("")
        self.stackCombo.addItem("")
        self.stackCombo.addItem("")
        self.stackCombo.setObjectName(u"stackCombo")
        sizePolicy1.setHeightForWidth(self.stackCombo.sizePolicy().hasHeightForWidth())
        self.stackCombo.setSizePolicy(sizePolicy1)

        self.gridLayout.addWidget(self.stackCombo, 2, 2, 1, 1)

        self.stackMaps = ImageView(pcaViewer)
        self.stackMaps.setObjectName(u"stackMaps")
        sizePolicy2.setHeightForWidth(self.stackMaps.sizePolicy().hasHeightForWidth())
        self.stackMaps.setSizePolicy(sizePolicy2)

        self.gridLayout.addWidget(self.stackMaps, 1, 2, 1, 1)

        self.spectraPlot = PlotWidget(pcaViewer)
        self.spectraPlot.setObjectName(u"spectraPlot")
        sizePolicy2.setHeightForWidth(self.spectraPlot.sizePolicy().hasHeightForWidth())
        self.spectraPlot.setSizePolicy(sizePolicy2)

        self.gridLayout.addWidget(self.spectraPlot, 3, 2, 1, 2)

        self.pcaSlider = QScrollBar(pcaViewer)
        self.pcaSlider.setObjectName(u"pcaSlider")
        sizePolicy.setHeightForWidth(self.pcaSlider.sizePolicy().hasHeightForWidth())
        self.pcaSlider.setSizePolicy(sizePolicy)
        self.pcaSlider.setOrientation(Qt.Vertical)

        self.gridLayout.addWidget(self.pcaSlider, 1, 1, 1, 1)

        self.plotCombo = QComboBox(pcaViewer)
        self.plotCombo.addItem("")
        self.plotCombo.addItem("")
        self.plotCombo.addItem("")
        self.plotCombo.setObjectName(u"plotCombo")

        self.gridLayout.addWidget(self.plotCombo, 4, 2, 1, 1)

        self.gridLayout_2 = QGridLayout()
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.redCombo = QComboBox(pcaViewer)
        self.redCombo.addItem("")
        self.redCombo.setObjectName(u"redCombo")

        self.gridLayout_2.addWidget(self.redCombo, 10, 5, 1, 1)

        self.label_4 = QLabel(pcaViewer)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_2.addWidget(self.label_4, 11, 4, 1, 1, Qt.AlignRight)

        self.label_5 = QLabel(pcaViewer)
        self.label_5.setObjectName(u"label_5")

        self.gridLayout_2.addWidget(self.label_5, 12, 4, 1, 1, Qt.AlignRight)

        self.preEdgeButton = QCheckBox(pcaViewer)
        self.preEdgeButton.setObjectName(u"preEdgeButton")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.preEdgeButton.sizePolicy().hasHeightForWidth())
        self.preEdgeButton.setSizePolicy(sizePolicy3)

        self.gridLayout_2.addWidget(self.preEdgeButton, 14, 4, 1, 1, Qt.AlignLeft)

        self.saveButton = QPushButton(pcaViewer)
        self.saveButton.setObjectName(u"saveButton")
        sizePolicy3.setHeightForWidth(self.saveButton.sizePolicy().hasHeightForWidth())
        self.saveButton.setSizePolicy(sizePolicy3)

        self.gridLayout_2.addWidget(self.saveButton, 16, 4, 1, 1)

        self.greenCombo = QComboBox(pcaViewer)
        self.greenCombo.addItem("")
        self.greenCombo.setObjectName(u"greenCombo")

        self.gridLayout_2.addWidget(self.greenCombo, 11, 5, 1, 1)

        self.mapButton = QPushButton(pcaViewer)
        self.mapButton.setObjectName(u"mapButton")
        sizePolicy3.setHeightForWidth(self.mapButton.sizePolicy().hasHeightForWidth())
        self.mapButton.setSizePolicy(sizePolicy3)

        self.gridLayout_2.addWidget(self.mapButton, 15, 5, 1, 1)

        self.label_3 = QLabel(pcaViewer)
        self.label_3.setObjectName(u"label_3")

        self.gridLayout_2.addWidget(self.label_3, 10, 4, 1, 1, Qt.AlignRight)

        self.nClustersCombo = QComboBox(pcaViewer)
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.addItem("")
        self.nClustersCombo.setObjectName(u"nClustersCombo")

        self.gridLayout_2.addWidget(self.nClustersCombo, 9, 5, 1, 1, Qt.AlignTop)

        self.nPCCombo = QComboBox(pcaViewer)
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.addItem("")
        self.nPCCombo.setObjectName(u"nPCCombo")

        self.gridLayout_2.addWidget(self.nPCCombo, 8, 5, 1, 1, Qt.AlignBottom)

        self.normButton = QCheckBox(pcaViewer)
        self.normButton.setObjectName(u"normButton")

        self.gridLayout_2.addWidget(self.normButton, 15, 4, 1, 1, Qt.AlignLeft)

        self.blueCombo = QComboBox(pcaViewer)
        self.blueCombo.addItem("")
        self.blueCombo.setObjectName(u"blueCombo")

        self.gridLayout_2.addWidget(self.blueCombo, 12, 5, 1, 1)

        self.calcButton = QPushButton(pcaViewer)
        self.calcButton.setObjectName(u"calcButton")
        sizePolicy3.setHeightForWidth(self.calcButton.sizePolicy().hasHeightForWidth())
        self.calcButton.setSizePolicy(sizePolicy3)

        self.gridLayout_2.addWidget(self.calcButton, 16, 5, 1, 1)

        self.label = QLabel(pcaViewer)
        self.label.setObjectName(u"label")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.label.sizePolicy().hasHeightForWidth())
        self.label.setSizePolicy(sizePolicy4)

        self.gridLayout_2.addWidget(self.label, 8, 4, 1, 1, Qt.AlignRight|Qt.AlignBottom)

        self.label_2 = QLabel(pcaViewer)
        self.label_2.setObjectName(u"label_2")
        sizePolicy4.setHeightForWidth(self.label_2.sizePolicy().hasHeightForWidth())
        self.label_2.setSizePolicy(sizePolicy4)

        self.gridLayout_2.addWidget(self.label_2, 9, 4, 1, 1, Qt.AlignRight|Qt.AlignTop)

        self.massCheckBox = QCheckBox(pcaViewer)
        self.massCheckBox.setObjectName(u"massCheckBox")

        self.gridLayout_2.addWidget(self.massCheckBox, 14, 5, 1, 1)


        self.gridLayout.addLayout(self.gridLayout_2, 3, 0, 2, 1)


        self.retranslateUi(pcaViewer)

        QMetaObject.connectSlotsByName(pcaViewer)
    # setupUi

    def retranslateUi(self, pcaViewer):
        pcaViewer.setWindowTitle(QCoreApplication.translate("pcaViewer", u"PCA Viewer", None))
        self.pcaCombo.setItemText(0, QCoreApplication.translate("pcaViewer", u"PCA Images", None))
        self.pcaCombo.setItemText(1, QCoreApplication.translate("pcaViewer", u"Clusters", None))

        self.stackCombo.setItemText(0, QCoreApplication.translate("pcaViewer", u"Stack Frames", None))
        self.stackCombo.setItemText(1, QCoreApplication.translate("pcaViewer", u"PCA Filtered Stack Frames", None))
        self.stackCombo.setItemText(2, QCoreApplication.translate("pcaViewer", u"Component Maps", None))
        self.stackCombo.setItemText(3, QCoreApplication.translate("pcaViewer", u"RGB Map", None))
        self.stackCombo.setItemText(4, QCoreApplication.translate("pcaViewer", u"R-factor Map", None))

        self.plotCombo.setItemText(0, QCoreApplication.translate("pcaViewer", u"Cluster Spectra", None))
        self.plotCombo.setItemText(1, QCoreApplication.translate("pcaViewer", u"Eigen Values", None))
        self.plotCombo.setItemText(2, QCoreApplication.translate("pcaViewer", u"Point Spectrum", None))

        self.redCombo.setItemText(0, QCoreApplication.translate("pcaViewer", u"None", None))

        self.label_4.setText(QCoreApplication.translate("pcaViewer", u"Green", None))
        self.label_5.setText(QCoreApplication.translate("pcaViewer", u"Blue", None))
        self.preEdgeButton.setText(QCoreApplication.translate("pcaViewer", u"Remove Pre-Edge", None))
        self.saveButton.setText(QCoreApplication.translate("pcaViewer", u"Save", None))
        self.greenCombo.setItemText(0, QCoreApplication.translate("pcaViewer", u"None", None))

        self.mapButton.setText(QCoreApplication.translate("pcaViewer", u"Map Spectra", None))
        self.label_3.setText(QCoreApplication.translate("pcaViewer", u"Red", None))
        self.nClustersCombo.setItemText(0, QCoreApplication.translate("pcaViewer", u"1", None))
        self.nClustersCombo.setItemText(1, QCoreApplication.translate("pcaViewer", u"2", None))
        self.nClustersCombo.setItemText(2, QCoreApplication.translate("pcaViewer", u"3", None))
        self.nClustersCombo.setItemText(3, QCoreApplication.translate("pcaViewer", u"4", None))
        self.nClustersCombo.setItemText(4, QCoreApplication.translate("pcaViewer", u"5", None))
        self.nClustersCombo.setItemText(5, QCoreApplication.translate("pcaViewer", u"6", None))
        self.nClustersCombo.setItemText(6, QCoreApplication.translate("pcaViewer", u"7", None))
        self.nClustersCombo.setItemText(7, QCoreApplication.translate("pcaViewer", u"8", None))
        self.nClustersCombo.setItemText(8, QCoreApplication.translate("pcaViewer", u"9", None))
        self.nClustersCombo.setItemText(9, QCoreApplication.translate("pcaViewer", u"10", None))

        self.nPCCombo.setItemText(0, QCoreApplication.translate("pcaViewer", u"1", None))
        self.nPCCombo.setItemText(1, QCoreApplication.translate("pcaViewer", u"2", None))
        self.nPCCombo.setItemText(2, QCoreApplication.translate("pcaViewer", u"3", None))
        self.nPCCombo.setItemText(3, QCoreApplication.translate("pcaViewer", u"4", None))
        self.nPCCombo.setItemText(4, QCoreApplication.translate("pcaViewer", u"5", None))
        self.nPCCombo.setItemText(5, QCoreApplication.translate("pcaViewer", u"6", None))
        self.nPCCombo.setItemText(6, QCoreApplication.translate("pcaViewer", u"7", None))
        self.nPCCombo.setItemText(7, QCoreApplication.translate("pcaViewer", u"8", None))
        self.nPCCombo.setItemText(8, QCoreApplication.translate("pcaViewer", u"9", None))
        self.nPCCombo.setItemText(9, QCoreApplication.translate("pcaViewer", u"10", None))

        self.normButton.setText(QCoreApplication.translate("pcaViewer", u"Normalize Components", None))
        self.blueCombo.setItemText(0, QCoreApplication.translate("pcaViewer", u"None", None))

        self.calcButton.setText(QCoreApplication.translate("pcaViewer", u"Calculate", None))
        self.label.setText(QCoreApplication.translate("pcaViewer", u"Significant Components", None))
        self.label_2.setText(QCoreApplication.translate("pcaViewer", u"Clusters", None))
        self.massCheckBox.setText(QCoreApplication.translate("pcaViewer", u"Reduce mass", None))
    # retranslateUi


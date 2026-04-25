# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'mainwindow.ui'
##
## Created by: Qt User Interface Compiler version 6.8.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMenuBar, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpacerItem,
    QSpinBox, QSplitter, QStatusBar, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget)

from pyqtgraph import (ImageView, PlotWidget)
from pystxmcontrol.gui.customwidget import customWidget
from pystxmcontrol.gui.stackviewerwidget import stackViewerWidget

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.setEnabled(True)
        MainWindow.resize(1550, 1080)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(MainWindow.sizePolicy().hasHeightForWidth())
        MainWindow.setSizePolicy(sizePolicy)
        MainWindow.setMaximumSize(QSize(1550, 1080))
        self.action_Open_Image_Data = QAction(MainWindow)
        self.action_Open_Image_Data.setObjectName(u"action_Open_Image_Data")
        self.action_Save_Image_Data = QAction(MainWindow)
        self.action_Save_Image_Data.setObjectName(u"action_Save_Image_Data")
        self.action_Save_Scan_Definition = QAction(MainWindow)
        self.action_Save_Scan_Definition.setObjectName(u"action_Save_Scan_Definition")
        self.action_Open_Energy_Definition = QAction(MainWindow)
        self.action_Open_Energy_Definition.setObjectName(u"action_Open_Energy_Definition")
        self.action_Open_Scan_Definition = QAction(MainWindow)
        self.action_Open_Scan_Definition.setObjectName(u"action_Open_Scan_Definition")
        self.actionGood_Luck = QAction(MainWindow)
        self.actionGood_Luck.setObjectName(u"actionGood_Luck")
        self.actionPlease_confirm_you_have_a_good_sample = QAction(MainWindow)
        self.actionPlease_confirm_you_have_a_good_sample.setObjectName(u"actionPlease_confirm_you_have_a_good_sample")
        self.actionGood_Luck_2 = QAction(MainWindow)
        self.actionGood_Luck_2.setObjectName(u"actionGood_Luck_2")
        self.actionLight = QAction(MainWindow)
        self.actionLight.setObjectName(u"actionLight")
        self.actionDark = QAction(MainWindow)
        self.actionDark.setObjectName(u"actionDark")
        self.action_light_theme = QAction(MainWindow)
        self.action_light_theme.setObjectName(u"action_light_theme")
        self.action_dark_theme = QAction(MainWindow)
        self.action_dark_theme.setObjectName(u"action_dark_theme")
        self.action_load_config_from_server = QAction(MainWindow)
        self.action_load_config_from_server.setObjectName(u"action_load_config_from_server")
        self.action_init = QAction(MainWindow)
        self.action_init.setObjectName(u"action_init")
        self.action_quit = QAction(MainWindow)
        self.action_quit.setObjectName(u"action_quit")
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.tabWidget_3 = QTabWidget(self.centralwidget)
        self.tabWidget_3.setObjectName(u"tabWidget_3")
        self.tabWidget_3.setGeometry(QRect(0, 0, 1521, 1031))
        self.tabWidget_3.setTabPosition(QTabWidget.North)
        self.tabWidget_3.setTabShape(QTabWidget.Rounded)
        self.tabWidget_3.setDocumentMode(False)
        self.tab_9 = QWidget()
        self.tab_9.setObjectName(u"tab_9")
        self.layoutWidget = QWidget(self.tab_9)
        self.layoutWidget.setObjectName(u"layoutWidget")
        self.layoutWidget.setGeometry(QRect(570, 550, 134, 101))
        self.verticalLayout_4 = QVBoxLayout(self.layoutWidget)
        self.verticalLayout_4.setObjectName(u"verticalLayout_4")
        self.verticalLayout_4.setContentsMargins(0, 0, 0, 0)
        self.setCursor2ZeroButton = QPushButton(self.layoutWidget)
        self.setCursor2ZeroButton.setObjectName(u"setCursor2ZeroButton")

        self.verticalLayout_4.addWidget(self.setCursor2ZeroButton)

        self.focusToCursorButton = QPushButton(self.layoutWidget)
        self.focusToCursorButton.setObjectName(u"focusToCursorButton")

        self.verticalLayout_4.addWidget(self.focusToCursorButton)

        self.motors2CursorButton = QPushButton(self.layoutWidget)
        self.motors2CursorButton.setObjectName(u"motors2CursorButton")

        self.verticalLayout_4.addWidget(self.motors2CursorButton)

        self.layoutWidget1 = QWidget(self.tab_9)
        self.layoutWidget1.setObjectName(u"layoutWidget1")
        self.layoutWidget1.setGeometry(QRect(190, 20, 511, 21))
        self.horizontalLayout_5 = QHBoxLayout(self.layoutWidget1)
        self.horizontalLayout_5.setObjectName(u"horizontalLayout_5")
        self.horizontalLayout_5.setContentsMargins(0, 0, 0, 0)
        self.label_2 = QLabel(self.layoutWidget1)
        self.label_2.setObjectName(u"label_2")
        font = QFont()
        font.setBold(False)
        font.setKerning(False)
        self.label_2.setFont(font)

        self.horizontalLayout_5.addWidget(self.label_2)

        self.serverAddress = QLabel(self.layoutWidget1)
        self.serverAddress.setObjectName(u"serverAddress")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.serverAddress.sizePolicy().hasHeightForWidth())
        self.serverAddress.setSizePolicy(sizePolicy1)
        font1 = QFont()
        font1.setBold(True)
        self.serverAddress.setFont(font1)

        self.horizontalLayout_5.addWidget(self.serverAddress)

        self.tabWidget = QTabWidget(self.tab_9)
        self.tabWidget.setObjectName(u"tabWidget")
        self.tabWidget.setGeometry(QRect(10, 510, 551, 171))
        self.tab_4 = QWidget()
        self.tab_4.setObjectName(u"tab_4")
        self.layoutWidget_3 = QWidget(self.tab_4)
        self.layoutWidget_3.setObjectName(u"layoutWidget_3")
        self.layoutWidget_3.setGeometry(QRect(10, 10, 531, 118))
        self.gridLayout = QGridLayout(self.layoutWidget_3)
        self.gridLayout.setObjectName(u"gridLayout")
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.motorMover1 = QComboBox(self.layoutWidget_3)
        self.motorMover1.setObjectName(u"motorMover1")

        self.gridLayout.addWidget(self.motorMover1, 0, 0, 1, 1)

        self.motorMover2Plus = QPushButton(self.layoutWidget_3)
        self.motorMover2Plus.setObjectName(u"motorMover2Plus")
        self.motorMover2Plus.setMaximumSize(QSize(30, 30))
        font2 = QFont()
        font2.setPointSize(14)
        font2.setBold(True)
        self.motorMover2Plus.setFont(font2)

        self.gridLayout.addWidget(self.motorMover2Plus, 1, 6, 1, 1)

        self.motorMover1Edit = QLineEdit(self.layoutWidget_3)
        self.motorMover1Edit.setObjectName(u"motorMover1Edit")
        self.motorMover1Edit.setMinimumSize(QSize(100, 30))
        self.motorMover1Edit.setMaximumSize(QSize(100, 100))

        self.gridLayout.addWidget(self.motorMover1Edit, 0, 3, 1, 1)

        self.motorMover1Pos = QLabel(self.layoutWidget_3)
        self.motorMover1Pos.setObjectName(u"motorMover1Pos")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.motorMover1Pos.sizePolicy().hasHeightForWidth())
        self.motorMover1Pos.setSizePolicy(sizePolicy2)
        self.motorMover1Pos.setMinimumSize(QSize(80, 0))
        self.motorMover1Pos.setStyleSheet(u"color: rgb(0, 0, 0);")

        self.gridLayout.addWidget(self.motorMover1Pos, 0, 1, 1, 1)

        self.motorMover2 = QComboBox(self.layoutWidget_3)
        self.motorMover2.setObjectName(u"motorMover2")

        self.gridLayout.addWidget(self.motorMover2, 1, 0, 1, 1)

        self.motorMover2Pos = QLabel(self.layoutWidget_3)
        self.motorMover2Pos.setObjectName(u"motorMover2Pos")
        sizePolicy2.setHeightForWidth(self.motorMover2Pos.sizePolicy().hasHeightForWidth())
        self.motorMover2Pos.setSizePolicy(sizePolicy2)
        self.motorMover2Pos.setMinimumSize(QSize(80, 0))
        self.motorMover2Pos.setStyleSheet(u"color: rgb(0, 0, 0);")

        self.gridLayout.addWidget(self.motorMover2Pos, 1, 1, 1, 1)

        self.motorMover1Plus = QPushButton(self.layoutWidget_3)
        self.motorMover1Plus.setObjectName(u"motorMover1Plus")
        self.motorMover1Plus.setMaximumSize(QSize(30, 16777215))
        self.motorMover1Plus.setFont(font2)

        self.gridLayout.addWidget(self.motorMover1Plus, 0, 6, 1, 1)

        self.motorMover1Button = QPushButton(self.layoutWidget_3)
        self.motorMover1Button.setObjectName(u"motorMover1Button")
        self.motorMover1Button.setMinimumSize(QSize(30, 30))
        self.motorMover1Button.setMaximumSize(QSize(30, 16777215))

        self.gridLayout.addWidget(self.motorMover1Button, 0, 4, 1, 1)

        self.motorMover2Button = QPushButton(self.layoutWidget_3)
        self.motorMover2Button.setObjectName(u"motorMover2Button")
        self.motorMover2Button.setMinimumSize(QSize(30, 30))
        self.motorMover2Button.setMaximumSize(QSize(30, 16777215))

        self.gridLayout.addWidget(self.motorMover2Button, 1, 4, 1, 1)

        self.jogToggleButton = QPushButton(self.layoutWidget_3)
        self.jogToggleButton.setObjectName(u"jogToggleButton")
        self.jogToggleButton.setMaximumSize(QSize(16777215, 30))

        self.gridLayout.addWidget(self.jogToggleButton, 2, 0, 1, 1)

        self.motorMover1Minus = QPushButton(self.layoutWidget_3)
        self.motorMover1Minus.setObjectName(u"motorMover1Minus")
        self.motorMover1Minus.setMinimumSize(QSize(30, 0))
        self.motorMover1Minus.setMaximumSize(QSize(30, 16777215))
        self.motorMover1Minus.setFont(font2)

        self.gridLayout.addWidget(self.motorMover1Minus, 0, 5, 1, 1)

        self.motorMover2Minus = QPushButton(self.layoutWidget_3)
        self.motorMover2Minus.setObjectName(u"motorMover2Minus")
        self.motorMover2Minus.setMaximumSize(QSize(30, 16777215))
        self.motorMover2Minus.setFont(font2)

        self.gridLayout.addWidget(self.motorMover2Minus, 1, 5, 1, 1)

        self.motorMover2Edit = QLineEdit(self.layoutWidget_3)
        self.motorMover2Edit.setObjectName(u"motorMover2Edit")
        self.motorMover2Edit.setMinimumSize(QSize(100, 30))
        self.motorMover2Edit.setMaximumSize(QSize(100, 16777215))

        self.gridLayout.addWidget(self.motorMover2Edit, 1, 3, 1, 1)

        self.motorPanelButton = QPushButton(self.layoutWidget_3)
        self.motorPanelButton.setObjectName(u"motorPanelButton")
        sizePolicy3 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy3.setHorizontalStretch(0)
        sizePolicy3.setVerticalStretch(0)
        sizePolicy3.setHeightForWidth(self.motorPanelButton.sizePolicy().hasHeightForWidth())
        self.motorPanelButton.setSizePolicy(sizePolicy3)
        self.motorPanelButton.setMinimumSize(QSize(30, 30))
        self.motorPanelButton.setMaximumSize(QSize(16777215, 16777215))

        self.gridLayout.addWidget(self.motorPanelButton, 2, 4, 1, 3)

        self.tabWidget.addTab(self.tab_4, "")
        self.tab_3 = QWidget()
        self.tab_3.setObjectName(u"tab_3")
        self.gridLayoutWidget = QWidget(self.tab_3)
        self.gridLayoutWidget.setObjectName(u"gridLayoutWidget")
        self.gridLayoutWidget.setGeometry(QRect(10, 10, 401, 52))
        self.gridLayout_2 = QGridLayout(self.gridLayoutWidget)
        self.gridLayout_2.setObjectName(u"gridLayout_2")
        self.gridLayout_2.setContentsMargins(0, 0, 0, 0)
        self.label_27 = QLabel(self.gridLayoutWidget)
        self.label_27.setObjectName(u"label_27")

        self.gridLayout_2.addWidget(self.label_27, 0, 0, 1, 1)

        self.label_29 = QLabel(self.gridLayoutWidget)
        self.label_29.setObjectName(u"label_29")

        self.gridLayout_2.addWidget(self.label_29, 0, 2, 1, 1)

        self.focusRangeEdit = QLineEdit(self.gridLayoutWidget)
        self.focusRangeEdit.setObjectName(u"focusRangeEdit")

        self.gridLayout_2.addWidget(self.focusRangeEdit, 1, 1, 1, 1)

        self.label_30 = QLabel(self.gridLayoutWidget)
        self.label_30.setObjectName(u"label_30")

        self.gridLayout_2.addWidget(self.label_30, 0, 3, 1, 1)

        self.label_28 = QLabel(self.gridLayoutWidget)
        self.label_28.setObjectName(u"label_28")

        self.gridLayout_2.addWidget(self.label_28, 0, 1, 1, 1)

        self.focusStepsEdit = QLineEdit(self.gridLayoutWidget)
        self.focusStepsEdit.setObjectName(u"focusStepsEdit")

        self.gridLayout_2.addWidget(self.focusStepsEdit, 1, 2, 1, 1)

        self.focusStepSizeLabel = QLabel(self.gridLayoutWidget)
        self.focusStepSizeLabel.setObjectName(u"focusStepSizeLabel")

        self.gridLayout_2.addWidget(self.focusStepSizeLabel, 1, 3, 1, 1)

        self.focusCenterEdit = QLineEdit(self.gridLayoutWidget)
        self.focusCenterEdit.setObjectName(u"focusCenterEdit")

        self.gridLayout_2.addWidget(self.focusCenterEdit, 1, 0, 1, 1)

        self.tabWidget.addTab(self.tab_3, "")
        self.tab = QWidget()
        self.tab.setObjectName(u"tab")
        self.gridLayoutWidget_3 = QWidget(self.tab)
        self.gridLayoutWidget_3.setObjectName(u"gridLayoutWidget_3")
        self.gridLayoutWidget_3.setGeometry(QRect(10, 10, 401, 52))
        self.gridLayout_4 = QGridLayout(self.gridLayoutWidget_3)
        self.gridLayout_4.setObjectName(u"gridLayout_4")
        self.gridLayout_4.setContentsMargins(0, 0, 0, 0)
        self.lineStepSizeLabel = QLabel(self.gridLayoutWidget_3)
        self.lineStepSizeLabel.setObjectName(u"lineStepSizeLabel")

        self.gridLayout_4.addWidget(self.lineStepSizeLabel, 1, 3, 1, 1)

        self.lineAngleEdit = QLineEdit(self.gridLayoutWidget_3)
        self.lineAngleEdit.setObjectName(u"lineAngleEdit")

        self.gridLayout_4.addWidget(self.lineAngleEdit, 1, 1, 1, 1)

        self.label_37 = QLabel(self.gridLayoutWidget_3)
        self.label_37.setObjectName(u"label_37")

        self.gridLayout_4.addWidget(self.label_37, 0, 2, 1, 1)

        self.label_36 = QLabel(self.gridLayoutWidget_3)
        self.label_36.setObjectName(u"label_36")

        self.gridLayout_4.addWidget(self.label_36, 0, 1, 1, 1)

        self.label_39 = QLabel(self.gridLayoutWidget_3)
        self.label_39.setObjectName(u"label_39")

        self.gridLayout_4.addWidget(self.label_39, 0, 0, 1, 1)

        self.label_40 = QLabel(self.gridLayoutWidget_3)
        self.label_40.setObjectName(u"label_40")

        self.gridLayout_4.addWidget(self.label_40, 0, 3, 1, 1)

        self.linePointsEdit = QLineEdit(self.gridLayoutWidget_3)
        self.linePointsEdit.setObjectName(u"linePointsEdit")

        self.gridLayout_4.addWidget(self.linePointsEdit, 1, 2, 1, 1)

        self.lineLengthEdit = QLineEdit(self.gridLayoutWidget_3)
        self.lineLengthEdit.setObjectName(u"lineLengthEdit")

        self.gridLayout_4.addWidget(self.lineLengthEdit, 1, 0, 1, 1)

        self.tabWidget.addTab(self.tab, "")
        self.tab_11 = QWidget()
        self.tab_11.setObjectName(u"tab_11")
        self.gridLayoutWidget_8 = QWidget(self.tab_11)
        self.gridLayoutWidget_8.setObjectName(u"gridLayoutWidget_8")
        self.gridLayoutWidget_8.setGeometry(QRect(10, 10, 531, 82))
        self.gridLayout_10 = QGridLayout(self.gridLayoutWidget_8)
        self.gridLayout_10.setObjectName(u"gridLayout_10")
        self.gridLayout_10.setContentsMargins(0, 0, 0, 0)
        self.focusStepSizeLabel_5 = QLabel(self.gridLayoutWidget_8)
        self.focusStepSizeLabel_5.setObjectName(u"focusStepSizeLabel_5")
        sizePolicy4 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy4.setHorizontalStretch(0)
        sizePolicy4.setVerticalStretch(0)
        sizePolicy4.setHeightForWidth(self.focusStepSizeLabel_5.sizePolicy().hasHeightForWidth())
        self.focusStepSizeLabel_5.setSizePolicy(sizePolicy4)

        self.gridLayout_10.addWidget(self.focusStepSizeLabel_5, 0, 3, 1, 1)

        self.focusStepSizeLabel_6 = QLabel(self.gridLayoutWidget_8)
        self.focusStepSizeLabel_6.setObjectName(u"focusStepSizeLabel_6")

        self.gridLayout_10.addWidget(self.focusStepSizeLabel_6, 0, 4, 1, 1)

        self.loopCenter = QLineEdit(self.gridLayoutWidget_8)
        self.loopCenter.setObjectName(u"loopCenter")
        self.loopCenter.setMaximumSize(QSize(80, 16777215))

        self.gridLayout_10.addWidget(self.loopCenter, 1, 1, 1, 1, Qt.AlignVCenter)

        self.loopPoints = QLineEdit(self.gridLayoutWidget_8)
        self.loopPoints.setObjectName(u"loopPoints")
        self.loopPoints.setMaximumSize(QSize(80, 16777215))

        self.gridLayout_10.addWidget(self.loopPoints, 1, 3, 1, 1, Qt.AlignVCenter)

        self.loopMotor = QComboBox(self.gridLayoutWidget_8)
        self.loopMotor.setObjectName(u"loopMotor")
        self.loopMotor.setMinimumSize(QSize(150, 0))
        self.loopMotor.setMaximumSize(QSize(200, 16777215))

        self.gridLayout_10.addWidget(self.loopMotor, 1, 0, 1, 1, Qt.AlignVCenter)

        self.loopRange = QLineEdit(self.gridLayoutWidget_8)
        self.loopRange.setObjectName(u"loopRange")
        self.loopRange.setMaximumSize(QSize(80, 16777215))

        self.gridLayout_10.addWidget(self.loopRange, 1, 2, 1, 1, Qt.AlignVCenter)

        self.focusStepSizeLabel_3 = QLabel(self.gridLayoutWidget_8)
        self.focusStepSizeLabel_3.setObjectName(u"focusStepSizeLabel_3")
        sizePolicy4.setHeightForWidth(self.focusStepSizeLabel_3.sizePolicy().hasHeightForWidth())
        self.focusStepSizeLabel_3.setSizePolicy(sizePolicy4)

        self.gridLayout_10.addWidget(self.focusStepSizeLabel_3, 0, 1, 1, 1)

        self.focusStepSizeLabel_7 = QLabel(self.gridLayoutWidget_8)
        self.focusStepSizeLabel_7.setObjectName(u"focusStepSizeLabel_7")
        sizePolicy4.setHeightForWidth(self.focusStepSizeLabel_7.sizePolicy().hasHeightForWidth())
        self.focusStepSizeLabel_7.setSizePolicy(sizePolicy4)

        self.gridLayout_10.addWidget(self.focusStepSizeLabel_7, 0, 0, 1, 1)

        self.loopStepSize = QLabel(self.gridLayoutWidget_8)
        self.loopStepSize.setObjectName(u"loopStepSize")
        self.loopStepSize.setMaximumSize(QSize(80, 16777215))

        self.gridLayout_10.addWidget(self.loopStepSize, 1, 4, 1, 1, Qt.AlignVCenter)

        self.focusStepSizeLabel_4 = QLabel(self.gridLayoutWidget_8)
        self.focusStepSizeLabel_4.setObjectName(u"focusStepSizeLabel_4")
        sizePolicy4.setHeightForWidth(self.focusStepSizeLabel_4.sizePolicy().hasHeightForWidth())
        self.focusStepSizeLabel_4.setSizePolicy(sizePolicy4)

        self.gridLayout_10.addWidget(self.focusStepSizeLabel_4, 0, 2, 1, 1)

        self.loopCheckbox = QCheckBox(self.gridLayoutWidget_8)
        self.loopCheckbox.setObjectName(u"loopCheckbox")

        self.gridLayout_10.addWidget(self.loopCheckbox, 2, 0, 1, 1)

        self.tabWidget.addTab(self.tab_11, "")
        self.layoutWidget_2 = QWidget(self.tab_9)
        self.layoutWidget_2.setObjectName(u"layoutWidget_2")
        self.layoutWidget_2.setGeometry(QRect(190, 40, 231, 31))
        self.horizontalLayout_3 = QHBoxLayout(self.layoutWidget_2)
        self.horizontalLayout_3.setObjectName(u"horizontalLayout_3")
        self.horizontalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self.layoutWidget_2)
        self.label.setObjectName(u"label")
        font3 = QFont()
        font3.setBold(False)
        self.label.setFont(font3)

        self.horizontalLayout_3.addWidget(self.label)

        self.energyLabel = QLabel(self.layoutWidget_2)
        self.energyLabel.setObjectName(u"energyLabel")
        palette = QPalette()
        brush = QBrush(QColor(0, 0, 0, 255))
        brush.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.WindowText, brush)
        brush1 = QBrush(QColor(115, 210, 22, 255))
        brush1.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.Button, brush1)
        brush2 = QBrush(QColor(170, 255, 87, 255))
        brush2.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.Light, brush2)
        brush3 = QBrush(QColor(142, 232, 54, 255))
        brush3.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.Midlight, brush3)
        brush4 = QBrush(QColor(57, 105, 11, 255))
        brush4.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.Dark, brush4)
        brush5 = QBrush(QColor(76, 140, 14, 255))
        brush5.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.Mid, brush5)
        palette.setBrush(QPalette.Active, QPalette.Text, brush)
        brush6 = QBrush(QColor(255, 255, 255, 255))
        brush6.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.BrightText, brush6)
        palette.setBrush(QPalette.Active, QPalette.ButtonText, brush)
        palette.setBrush(QPalette.Active, QPalette.Base, brush6)
        palette.setBrush(QPalette.Active, QPalette.Window, brush1)
        palette.setBrush(QPalette.Active, QPalette.Shadow, brush)
        brush7 = QBrush(QColor(185, 232, 138, 255))
        brush7.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.AlternateBase, brush7)
        brush8 = QBrush(QColor(255, 255, 220, 255))
        brush8.setStyle(Qt.SolidPattern)
        palette.setBrush(QPalette.Active, QPalette.ToolTipBase, brush8)
        palette.setBrush(QPalette.Active, QPalette.ToolTipText, brush)
        brush9 = QBrush(QColor(0, 0, 0, 128))
        brush9.setStyle(Qt.NoBrush)
#if QT_VERSION >= QT_VERSION_CHECK(5, 12, 0)
        palette.setBrush(QPalette.Active, QPalette.PlaceholderText, brush9)
#endif
        palette.setBrush(QPalette.Inactive, QPalette.WindowText, brush)
        palette.setBrush(QPalette.Inactive, QPalette.Button, brush1)
        palette.setBrush(QPalette.Inactive, QPalette.Light, brush2)
        palette.setBrush(QPalette.Inactive, QPalette.Midlight, brush3)
        palette.setBrush(QPalette.Inactive, QPalette.Dark, brush4)
        palette.setBrush(QPalette.Inactive, QPalette.Mid, brush5)
        palette.setBrush(QPalette.Inactive, QPalette.Text, brush)
        palette.setBrush(QPalette.Inactive, QPalette.BrightText, brush6)
        palette.setBrush(QPalette.Inactive, QPalette.ButtonText, brush)
        palette.setBrush(QPalette.Inactive, QPalette.Base, brush6)
        palette.setBrush(QPalette.Inactive, QPalette.Window, brush1)
        palette.setBrush(QPalette.Inactive, QPalette.Shadow, brush)
        palette.setBrush(QPalette.Inactive, QPalette.AlternateBase, brush7)
        palette.setBrush(QPalette.Inactive, QPalette.ToolTipBase, brush8)
        palette.setBrush(QPalette.Inactive, QPalette.ToolTipText, brush)
        brush10 = QBrush(QColor(0, 0, 0, 128))
        brush10.setStyle(Qt.NoBrush)
#if QT_VERSION >= QT_VERSION_CHECK(5, 12, 0)
        palette.setBrush(QPalette.Inactive, QPalette.PlaceholderText, brush10)
#endif
        palette.setBrush(QPalette.Disabled, QPalette.WindowText, brush4)
        palette.setBrush(QPalette.Disabled, QPalette.Button, brush1)
        palette.setBrush(QPalette.Disabled, QPalette.Light, brush2)
        palette.setBrush(QPalette.Disabled, QPalette.Midlight, brush3)
        palette.setBrush(QPalette.Disabled, QPalette.Dark, brush4)
        palette.setBrush(QPalette.Disabled, QPalette.Mid, brush5)
        palette.setBrush(QPalette.Disabled, QPalette.Text, brush4)
        palette.setBrush(QPalette.Disabled, QPalette.BrightText, brush6)
        palette.setBrush(QPalette.Disabled, QPalette.ButtonText, brush4)
        palette.setBrush(QPalette.Disabled, QPalette.Base, brush1)
        palette.setBrush(QPalette.Disabled, QPalette.Window, brush1)
        palette.setBrush(QPalette.Disabled, QPalette.Shadow, brush)
        palette.setBrush(QPalette.Disabled, QPalette.AlternateBase, brush1)
        palette.setBrush(QPalette.Disabled, QPalette.ToolTipBase, brush8)
        palette.setBrush(QPalette.Disabled, QPalette.ToolTipText, brush)
        brush11 = QBrush(QColor(0, 0, 0, 128))
        brush11.setStyle(Qt.NoBrush)
#if QT_VERSION >= QT_VERSION_CHECK(5, 12, 0)
        palette.setBrush(QPalette.Disabled, QPalette.PlaceholderText, brush11)
#endif
        self.energyLabel.setPalette(palette)
        self.energyLabel.setFont(font1)
        self.energyLabel.setAutoFillBackground(False)

        self.horizontalLayout_3.addWidget(self.energyLabel)

        self.widget = QWidget(self.tab_9)
        self.widget.setObjectName(u"widget")
        self.widget.setGeometry(QRect(10, 70, 691, 71))
        self.layoutWidget2 = QWidget(self.widget)
        self.layoutWidget2.setObjectName(u"layoutWidget2")
        self.layoutWidget2.setGeometry(QRect(180, 0, 511, 21))
        self.horizontalLayout_7 = QHBoxLayout(self.layoutWidget2)
        self.horizontalLayout_7.setObjectName(u"horizontalLayout_7")
        self.horizontalLayout_7.setContentsMargins(0, 0, 0, 0)
        self.label_7 = QLabel(self.layoutWidget2)
        self.label_7.setObjectName(u"label_7")

        self.horizontalLayout_7.addWidget(self.label_7)

        self.scanVelocity = QLabel(self.layoutWidget2)
        self.scanVelocity.setObjectName(u"scanVelocity")
        self.scanVelocity.setFont(font1)

        self.horizontalLayout_7.addWidget(self.scanVelocity)

        self.label_19 = QLabel(self.layoutWidget2)
        self.label_19.setObjectName(u"label_19")

        self.horizontalLayout_7.addWidget(self.label_19)

        self.estimatedTime = QLabel(self.layoutWidget2)
        self.estimatedTime.setObjectName(u"estimatedTime")
        self.estimatedTime.setFont(font1)

        self.horizontalLayout_7.addWidget(self.estimatedTime)

        self.label_21 = QLabel(self.layoutWidget2)
        self.label_21.setObjectName(u"label_21")

        self.horizontalLayout_7.addWidget(self.label_21)

        self.elapsedTime = QLabel(self.layoutWidget2)
        self.elapsedTime.setObjectName(u"elapsedTime")
        self.elapsedTime.setFont(font1)

        self.horizontalLayout_7.addWidget(self.elapsedTime)

        self.warningLabel = QLabel(self.widget)
        self.warningLabel.setObjectName(u"warningLabel")
        self.warningLabel.setGeometry(QRect(0, 30, 691, 31))
        self.warningLabel.setStyleSheet(u"color: rgb(224, 27, 36);\n"
"font: 75 11pt \"Ubuntu\";\n"
"")
        self.warningLabel.setAlignment(Qt.AlignCenter)
        self.label_6 = QLabel(self.tab_9)
        self.label_6.setObjectName(u"label_6")
        self.label_6.setGeometry(QRect(10, 10, 171, 34))
        self.scanType = QComboBox(self.tab_9)
        self.scanType.setObjectName(u"scanType")
        self.scanType.setGeometry(QRect(10, 40, 171, 42))
        self.gridLayoutWidget_6 = QWidget(self.tab_9)
        self.gridLayoutWidget_6.setObjectName(u"gridLayoutWidget_6")
        self.gridLayoutWidget_6.setGeometry(QRect(340, 850, 361, 122))
        self.gridLayout_9 = QGridLayout(self.gridLayoutWidget_6)
        self.gridLayout_9.setObjectName(u"gridLayout_9")
        self.gridLayout_9.setContentsMargins(0, 0, 0, 0)
        self.imageCountText = QLabel(self.gridLayoutWidget_6)
        self.imageCountText.setObjectName(u"imageCountText")
        sizePolicy2.setHeightForWidth(self.imageCountText.sizePolicy().hasHeightForWidth())
        self.imageCountText.setSizePolicy(sizePolicy2)
        self.imageCountText.setMinimumSize(QSize(80, 0))

        self.gridLayout_9.addWidget(self.imageCountText, 1, 1, 1, 1)

        self.scanFileName = QLabel(self.gridLayoutWidget_6)
        self.scanFileName.setObjectName(u"scanFileName")
        sizePolicy1.setHeightForWidth(self.scanFileName.sizePolicy().hasHeightForWidth())
        self.scanFileName.setSizePolicy(sizePolicy1)

        self.gridLayout_9.addWidget(self.scanFileName, 0, 1, 1, 1)

        self.label_25 = QLabel(self.gridLayoutWidget_6)
        self.label_25.setObjectName(u"label_25")

        self.gridLayout_9.addWidget(self.label_25, 0, 0, 1, 1)

        self.label_5 = QLabel(self.gridLayoutWidget_6)
        self.label_5.setObjectName(u"label_5")
        sizePolicy2.setHeightForWidth(self.label_5.sizePolicy().hasHeightForWidth())
        self.label_5.setSizePolicy(sizePolicy2)
        self.label_5.setMinimumSize(QSize(120, 0))

        self.gridLayout_9.addWidget(self.label_5, 1, 0, 1, 1)

        self.xCursorPos = QLabel(self.gridLayoutWidget_6)
        self.xCursorPos.setObjectName(u"xCursorPos")
        sizePolicy3.setHeightForWidth(self.xCursorPos.sizePolicy().hasHeightForWidth())
        self.xCursorPos.setSizePolicy(sizePolicy3)

        self.gridLayout_9.addWidget(self.xCursorPos, 2, 1, 1, 1)

        self.label_23 = QLabel(self.gridLayoutWidget_6)
        self.label_23.setObjectName(u"label_23")

        self.gridLayout_9.addWidget(self.label_23, 3, 0, 1, 1)

        self.yCursorPos = QLabel(self.gridLayoutWidget_6)
        self.yCursorPos.setObjectName(u"yCursorPos")
        sizePolicy3.setHeightForWidth(self.yCursorPos.sizePolicy().hasHeightForWidth())
        self.yCursorPos.setSizePolicy(sizePolicy3)

        self.gridLayout_9.addWidget(self.yCursorPos, 3, 1, 1, 1)

        self.label_20 = QLabel(self.gridLayoutWidget_6)
        self.label_20.setObjectName(u"label_20")

        self.gridLayout_9.addWidget(self.label_20, 2, 0, 1, 1)

        self.label_24 = QLabel(self.gridLayoutWidget_6)
        self.label_24.setObjectName(u"label_24")

        self.gridLayout_9.addWidget(self.label_24, 4, 0, 1, 1)

        self.cursorIntensity = QLabel(self.gridLayoutWidget_6)
        self.cursorIntensity.setObjectName(u"cursorIntensity")
        sizePolicy1.setHeightForWidth(self.cursorIntensity.sizePolicy().hasHeightForWidth())
        self.cursorIntensity.setSizePolicy(sizePolicy1)

        self.gridLayout_9.addWidget(self.cursorIntensity, 4, 1, 1, 1)

        self.line = QFrame(self.tab_9)
        self.line.setObjectName(u"line")
        self.line.setGeometry(QRect(710, 970, 100, 10))
        sizePolicy.setHeightForWidth(self.line.sizePolicy().hasHeightForWidth())
        self.line.setSizePolicy(sizePolicy)
        self.line.setMinimumSize(QSize(100, 10))
        self.line.setSizeIncrement(QSize(0, 10))
        self.line.setBaseSize(QSize(0, 10))
        self.line.setAutoFillBackground(False)
        self.line.setStyleSheet(u"background-color: rgb(246, 211, 45);")
        self.line.setLineWidth(10)
        self.line.setFrameShape(QFrame.Shape.VLine)
        self.line.setFrameShadow(QFrame.Shadow.Sunken)
        self.mainPlot = PlotWidget(self.tab_9)
        self.mainPlot.setObjectName(u"mainPlot")
        self.mainPlot.setGeometry(QRect(710, 60, 771, 281))
        self.daqCurrentValue = QLabel(self.tab_9)
        self.daqCurrentValue.setObjectName(u"daqCurrentValue")
        self.daqCurrentValue.setGeometry(QRect(710, 20, 331, 41))
        sizePolicy5 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        sizePolicy5.setHorizontalStretch(0)
        sizePolicy5.setVerticalStretch(0)
        sizePolicy5.setHeightForWidth(self.daqCurrentValue.sizePolicy().hasHeightForWidth())
        self.daqCurrentValue.setSizePolicy(sizePolicy5)
        font4 = QFont()
        font4.setPointSize(22)
        self.daqCurrentValue.setFont(font4)
        self.daqCurrentValue.setTextFormat(Qt.PlainText)
        self.layoutWidget3 = QWidget(self.tab_9)
        self.layoutWidget3.setObjectName(u"layoutWidget3")
        self.layoutWidget3.setGeometry(QRect(1100, 16, 377, 41))
        self.horizontalLayout_6 = QHBoxLayout(self.layoutWidget3)
        self.horizontalLayout_6.setObjectName(u"horizontalLayout_6")
        self.horizontalLayout_6.setContentsMargins(0, 0, 0, 0)
        self.label_3 = QLabel(self.layoutWidget3)
        self.label_3.setObjectName(u"label_3")

        self.horizontalLayout_6.addWidget(self.label_3)

        self.plotType = QComboBox(self.layoutWidget3)
        self.plotType.addItem("")
        self.plotType.addItem("")
        self.plotType.addItem("")
        self.plotType.addItem("")
        self.plotType.addItem("")
        self.plotType.setObjectName(u"plotType")
        sizePolicy6 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy6.setHorizontalStretch(0)
        sizePolicy6.setVerticalStretch(0)
        sizePolicy6.setHeightForWidth(self.plotType.sizePolicy().hasHeightForWidth())
        self.plotType.setSizePolicy(sizePolicy6)

        self.horizontalLayout_6.addWidget(self.plotType)

        self.label_22 = QLabel(self.layoutWidget3)
        self.label_22.setObjectName(u"label_22")

        self.horizontalLayout_6.addWidget(self.label_22)

        self.channelSelect = QComboBox(self.layoutWidget3)
        self.channelSelect.addItem("")
        self.channelSelect.addItem("")
        self.channelSelect.addItem("")
        self.channelSelect.setObjectName(u"channelSelect")
        sizePolicy6.setHeightForWidth(self.channelSelect.sizePolicy().hasHeightForWidth())
        self.channelSelect.setSizePolicy(sizePolicy6)

        self.horizontalLayout_6.addWidget(self.channelSelect)

        self.plotClearButton = QPushButton(self.layoutWidget3)
        self.plotClearButton.setObjectName(u"plotClearButton")
        sizePolicy.setHeightForWidth(self.plotClearButton.sizePolicy().hasHeightForWidth())
        self.plotClearButton.setSizePolicy(sizePolicy)
        self.plotClearButton.setMaximumSize(QSize(50, 16777215))

        self.horizontalLayout_6.addWidget(self.plotClearButton)

        self.mainImage = ImageView(self.tab_9)
        self.mainImage.setObjectName(u"mainImage")
        self.mainImage.setGeometry(QRect(710, 348, 771, 611))
        self.horizontalLayoutWidget = QWidget(self.tab_9)
        self.horizontalLayoutWidget.setObjectName(u"horizontalLayoutWidget")
        self.horizontalLayoutWidget.setGeometry(QRect(823, 959, 651, 31))
        self.horizontalLayout_8 = QHBoxLayout(self.horizontalLayoutWidget)
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.horizontalLayout_8.setContentsMargins(0, 0, 0, 0)
        self.scaleBarLength = QLabel(self.horizontalLayoutWidget)
        self.scaleBarLength.setObjectName(u"scaleBarLength")
        sizePolicy2.setHeightForWidth(self.scaleBarLength.sizePolicy().hasHeightForWidth())
        self.scaleBarLength.setSizePolicy(sizePolicy2)
        self.scaleBarLength.setMinimumSize(QSize(80, 0))
        self.scaleBarLength.setMaximumSize(QSize(80, 16777215))
        font5 = QFont()
        font5.setPointSize(13)
        self.scaleBarLength.setFont(font5)

        self.horizontalLayout_8.addWidget(self.scaleBarLength)

        self.label_44 = QLabel(self.horizontalLayoutWidget)
        self.label_44.setObjectName(u"label_44")
        sizePolicy2.setHeightForWidth(self.label_44.sizePolicy().hasHeightForWidth())
        self.label_44.setSizePolicy(sizePolicy2)
        self.label_44.setFont(font5)

        self.horizontalLayout_8.addWidget(self.label_44)

        self.pixelSizeLabel = QLabel(self.horizontalLayoutWidget)
        self.pixelSizeLabel.setObjectName(u"pixelSizeLabel")
        sizePolicy2.setHeightForWidth(self.pixelSizeLabel.sizePolicy().hasHeightForWidth())
        self.pixelSizeLabel.setSizePolicy(sizePolicy2)
        self.pixelSizeLabel.setMinimumSize(QSize(60, 0))
        self.pixelSizeLabel.setMaximumSize(QSize(60, 16777215))
        self.pixelSizeLabel.setFont(font5)

        self.horizontalLayout_8.addWidget(self.pixelSizeLabel)

        self.label_38 = QLabel(self.horizontalLayoutWidget)
        self.label_38.setObjectName(u"label_38")
        sizePolicy2.setHeightForWidth(self.label_38.sizePolicy().hasHeightForWidth())
        self.label_38.setSizePolicy(sizePolicy2)
        self.label_38.setMinimumSize(QSize(100, 0))
        self.label_38.setMaximumSize(QSize(100, 16777215))
        self.label_38.setFont(font5)

        self.horizontalLayout_8.addWidget(self.label_38)

        self.dwellTimeLabel = QLabel(self.horizontalLayoutWidget)
        self.dwellTimeLabel.setObjectName(u"dwellTimeLabel")
        sizePolicy2.setHeightForWidth(self.dwellTimeLabel.sizePolicy().hasHeightForWidth())
        self.dwellTimeLabel.setSizePolicy(sizePolicy2)
        self.dwellTimeLabel.setMinimumSize(QSize(60, 0))
        self.dwellTimeLabel.setMaximumSize(QSize(60, 16777215))
        self.dwellTimeLabel.setFont(font5)

        self.horizontalLayout_8.addWidget(self.dwellTimeLabel)

        self.label_9 = QLabel(self.horizontalLayoutWidget)
        self.label_9.setObjectName(u"label_9")
        sizePolicy2.setHeightForWidth(self.label_9.sizePolicy().hasHeightForWidth())
        self.label_9.setSizePolicy(sizePolicy2)
        self.label_9.setFont(font5)

        self.horizontalLayout_8.addWidget(self.label_9)

        self.imageEnergyLabel = QLabel(self.horizontalLayoutWidget)
        self.imageEnergyLabel.setObjectName(u"imageEnergyLabel")
        sizePolicy2.setHeightForWidth(self.imageEnergyLabel.sizePolicy().hasHeightForWidth())
        self.imageEnergyLabel.setSizePolicy(sizePolicy2)
        self.imageEnergyLabel.setMinimumSize(QSize(80, 0))
        self.imageEnergyLabel.setMaximumSize(QSize(80, 16777215))
        self.imageEnergyLabel.setFont(font5)

        self.horizontalLayout_8.addWidget(self.imageEnergyLabel)

        self.tabWidget_5 = QTabWidget(self.tab_9)
        self.tabWidget_5.setObjectName(u"tabWidget_5")
        self.tabWidget_5.setGeometry(QRect(10, 690, 311, 301))
        self.Experiment = QWidget()
        self.Experiment.setObjectName(u"Experiment")
        self.layoutWidget4 = QWidget(self.Experiment)
        self.layoutWidget4.setObjectName(u"layoutWidget4")
        self.layoutWidget4.setGeometry(QRect(10, 10, 291, 101))
        self.gridLayout_3 = QGridLayout(self.layoutWidget4)
        self.gridLayout_3.setObjectName(u"gridLayout_3")
        self.gridLayout_3.setContentsMargins(0, 0, 0, 0)
        self.experimentersLineEdit = QLineEdit(self.layoutWidget4)
        self.experimentersLineEdit.setObjectName(u"experimentersLineEdit")

        self.gridLayout_3.addWidget(self.experimentersLineEdit, 1, 1, 1, 1)

        self.label_32 = QLabel(self.layoutWidget4)
        self.label_32.setObjectName(u"label_32")
        self.label_32.setFont(font1)

        self.gridLayout_3.addWidget(self.label_32, 1, 0, 1, 1)

        self.sampleLineEdit = QLineEdit(self.layoutWidget4)
        self.sampleLineEdit.setObjectName(u"sampleLineEdit")

        self.gridLayout_3.addWidget(self.sampleLineEdit, 2, 1, 1, 1)

        self.label_33 = QLabel(self.layoutWidget4)
        self.label_33.setObjectName(u"label_33")
        self.label_33.setFont(font1)

        self.gridLayout_3.addWidget(self.label_33, 2, 0, 1, 1)

        self.proposalComboBox = QComboBox(self.layoutWidget4)
        self.proposalComboBox.setObjectName(u"proposalComboBox")

        self.gridLayout_3.addWidget(self.proposalComboBox, 0, 1, 1, 1)

        self.label_31 = QLabel(self.layoutWidget4)
        self.label_31.setObjectName(u"label_31")
        self.label_31.setFont(font1)

        self.gridLayout_3.addWidget(self.label_31, 0, 0, 1, 1)

        self.verticalLayoutWidget = QWidget(self.Experiment)
        self.verticalLayoutWidget.setObjectName(u"verticalLayoutWidget")
        self.verticalLayoutWidget.setGeometry(QRect(9, 119, 291, 141))
        self.verticalLayout_3 = QVBoxLayout(self.verticalLayoutWidget)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.verticalLayout_3.setContentsMargins(0, 0, 0, 0)
        self.label_26 = QLabel(self.verticalLayoutWidget)
        self.label_26.setObjectName(u"label_26")
        self.label_26.setFont(font1)

        self.verticalLayout_3.addWidget(self.label_26)

        self.commentEdit = QTextEdit(self.verticalLayoutWidget)
        self.commentEdit.setObjectName(u"commentEdit")

        self.verticalLayout_3.addWidget(self.commentEdit)

        self.tabWidget_5.addTab(self.Experiment, "")
        self.beamlineTab = QWidget()
        self.beamlineTab.setObjectName(u"beamlineTab")
        self.gridLayoutWidget_7 = QWidget(self.beamlineTab)
        self.gridLayoutWidget_7.setObjectName(u"gridLayoutWidget_7")
        self.gridLayoutWidget_7.setGeometry(QRect(10, 10, 291, 141))
        self.gridLayout_8 = QGridLayout(self.gridLayoutWidget_7)
        self.gridLayout_8.setObjectName(u"gridLayout_8")
        self.gridLayout_8.setContentsMargins(0, 0, 0, 0)
        self.ndsLabel = QLabel(self.gridLayoutWidget_7)
        self.ndsLabel.setObjectName(u"ndsLabel")

        self.gridLayout_8.addWidget(self.ndsLabel, 2, 1, 1, 1)

        self.label_34 = QLabel(self.gridLayoutWidget_7)
        self.label_34.setObjectName(u"label_34")

        self.gridLayout_8.addWidget(self.label_34, 3, 0, 1, 1)

        self.A0Edit = QLineEdit(self.gridLayoutWidget_7)
        self.A0Edit.setObjectName(u"A0Edit")

        self.gridLayout_8.addWidget(self.A0Edit, 3, 2, 1, 1)

        self.energyEdit = QLineEdit(self.gridLayoutWidget_7)
        self.energyEdit.setObjectName(u"energyEdit")

        self.gridLayout_8.addWidget(self.energyEdit, 0, 2, 1, 1)

        self.label_13 = QLabel(self.gridLayoutWidget_7)
        self.label_13.setObjectName(u"label_13")

        self.gridLayout_8.addWidget(self.label_13, 1, 0, 1, 1)

        self.A0Label = QLabel(self.gridLayoutWidget_7)
        self.A0Label.setObjectName(u"A0Label")

        self.gridLayout_8.addWidget(self.A0Label, 3, 1, 1, 1)

        self.dsLabel = QLabel(self.gridLayoutWidget_7)
        self.dsLabel.setObjectName(u"dsLabel")

        self.gridLayout_8.addWidget(self.dsLabel, 1, 1, 1, 1)

        self.ndsEdit = QLineEdit(self.gridLayoutWidget_7)
        self.ndsEdit.setObjectName(u"ndsEdit")

        self.gridLayout_8.addWidget(self.ndsEdit, 2, 2, 1, 1)

        self.label_14 = QLabel(self.gridLayoutWidget_7)
        self.label_14.setObjectName(u"label_14")

        self.gridLayout_8.addWidget(self.label_14, 2, 0, 1, 1)

        self.energyLabel_2 = QLabel(self.gridLayoutWidget_7)
        self.energyLabel_2.setObjectName(u"energyLabel_2")

        self.gridLayout_8.addWidget(self.energyLabel_2, 0, 1, 1, 1)

        self.dsEdit = QLineEdit(self.gridLayoutWidget_7)
        self.dsEdit.setObjectName(u"dsEdit")

        self.gridLayout_8.addWidget(self.dsEdit, 1, 2, 1, 1)

        self.label_4 = QLabel(self.gridLayoutWidget_7)
        self.label_4.setObjectName(u"label_4")

        self.gridLayout_8.addWidget(self.label_4, 0, 0, 1, 1)

        self.tabWidget_5.addTab(self.beamlineTab, "")
        self.epuTab = QWidget()
        self.epuTab.setObjectName(u"epuTab")
        self.gridLayoutWidget_5 = QWidget(self.epuTab)
        self.gridLayoutWidget_5.setObjectName(u"gridLayoutWidget_5")
        self.gridLayoutWidget_5.setGeometry(QRect(10, 10, 291, 161))
        self.gridLayout_6 = QGridLayout(self.gridLayoutWidget_5)
        self.gridLayout_6.setObjectName(u"gridLayout_6")
        self.gridLayout_6.setContentsMargins(0, 0, 0, 0)
        self.polEdit = QLineEdit(self.gridLayoutWidget_5)
        self.polEdit.setObjectName(u"polEdit")
        sizePolicy.setHeightForWidth(self.polEdit.sizePolicy().hasHeightForWidth())
        self.polEdit.setSizePolicy(sizePolicy)
        self.polEdit.setMaximumSize(QSize(80, 16777215))

        self.gridLayout_6.addWidget(self.polEdit, 0, 4, 1, 1)

        self.label_12 = QLabel(self.gridLayoutWidget_5)
        self.label_12.setObjectName(u"label_12")

        self.gridLayout_6.addWidget(self.label_12, 1, 2, 1, 1)

        self.label_17 = QLabel(self.gridLayoutWidget_5)
        self.label_17.setObjectName(u"label_17")

        self.gridLayout_6.addWidget(self.label_17, 2, 2, 1, 1)

        self.label_18 = QLabel(self.gridLayoutWidget_5)
        self.label_18.setObjectName(u"label_18")

        self.gridLayout_6.addWidget(self.label_18, 4, 2, 1, 1)

        self.label_16 = QLabel(self.gridLayoutWidget_5)
        self.label_16.setObjectName(u"label_16")

        self.gridLayout_6.addWidget(self.label_16, 3, 2, 1, 1)

        self.m101Edit = QLineEdit(self.gridLayoutWidget_5)
        self.m101Edit.setObjectName(u"m101Edit")
        sizePolicy.setHeightForWidth(self.m101Edit.sizePolicy().hasHeightForWidth())
        self.m101Edit.setSizePolicy(sizePolicy)
        self.m101Edit.setMinimumSize(QSize(0, 20))
        self.m101Edit.setMaximumSize(QSize(80, 16777215))

        self.gridLayout_6.addWidget(self.m101Edit, 1, 4, 1, 1)

        self.epuEdit = QLineEdit(self.gridLayoutWidget_5)
        self.epuEdit.setObjectName(u"epuEdit")
        sizePolicy.setHeightForWidth(self.epuEdit.sizePolicy().hasHeightForWidth())
        self.epuEdit.setSizePolicy(sizePolicy)
        self.epuEdit.setMaximumSize(QSize(80, 16777215))

        self.gridLayout_6.addWidget(self.epuEdit, 4, 4, 1, 1)

        self.label_15 = QLabel(self.gridLayoutWidget_5)
        self.label_15.setObjectName(u"label_15")

        self.gridLayout_6.addWidget(self.label_15, 0, 2, 1, 1)

        self.harSpin = QSpinBox(self.gridLayoutWidget_5)
        self.harSpin.setObjectName(u"harSpin")
        sizePolicy.setHeightForWidth(self.harSpin.sizePolicy().hasHeightForWidth())
        self.harSpin.setSizePolicy(sizePolicy)
        self.harSpin.setMinimumSize(QSize(0, 30))
        self.harSpin.setMaximumSize(QSize(80, 16777215))
        self.harSpin.setMinimum(1)
        self.harSpin.setMaximum(5)
        self.harSpin.setSingleStep(2)

        self.gridLayout_6.addWidget(self.harSpin, 2, 4, 1, 1)

        self.fbkEdit = QLineEdit(self.gridLayoutWidget_5)
        self.fbkEdit.setObjectName(u"fbkEdit")
        sizePolicy.setHeightForWidth(self.fbkEdit.sizePolicy().hasHeightForWidth())
        self.fbkEdit.setSizePolicy(sizePolicy)
        self.fbkEdit.setMaximumSize(QSize(80, 16777215))

        self.gridLayout_6.addWidget(self.fbkEdit, 3, 4, 1, 1)

        self.epuLabel = QLabel(self.gridLayoutWidget_5)
        self.epuLabel.setObjectName(u"epuLabel")

        self.gridLayout_6.addWidget(self.epuLabel, 4, 3, 1, 1)

        self.fbkLabel = QLabel(self.gridLayoutWidget_5)
        self.fbkLabel.setObjectName(u"fbkLabel")

        self.gridLayout_6.addWidget(self.fbkLabel, 3, 3, 1, 1)

        self.m101Label = QLabel(self.gridLayoutWidget_5)
        self.m101Label.setObjectName(u"m101Label")

        self.gridLayout_6.addWidget(self.m101Label, 1, 3, 1, 1)

        self.polLabel = QLabel(self.gridLayoutWidget_5)
        self.polLabel.setObjectName(u"polLabel")

        self.gridLayout_6.addWidget(self.polLabel, 0, 3, 1, 1)

        self.tabWidget_5.addTab(self.epuTab, "")
        self.tab_2 = QWidget()
        self.tab_2.setObjectName(u"tab_2")
        self.gridLayoutWidget_4 = QWidget(self.tab_2)
        self.gridLayoutWidget_4.setObjectName(u"gridLayoutWidget_4")
        self.gridLayoutWidget_4.setGeometry(QRect(9, 9, 291, 101))
        self.gridLayout_5 = QGridLayout(self.gridLayoutWidget_4)
        self.gridLayout_5.setObjectName(u"gridLayout_5")
        self.gridLayout_5.setContentsMargins(0, 0, 0, 0)
        self.serverAddressEdit = QLineEdit(self.gridLayoutWidget_4)
        self.serverAddressEdit.setObjectName(u"serverAddressEdit")
        self.serverAddressEdit.setEnabled(False)

        self.gridLayout_5.addWidget(self.serverAddressEdit, 1, 2, 1, 1)

        self.label_35 = QLabel(self.gridLayoutWidget_4)
        self.label_35.setObjectName(u"label_35")

        self.gridLayout_5.addWidget(self.label_35, 0, 0, 1, 1)

        self.A1Label = QLabel(self.gridLayoutWidget_4)
        self.A1Label.setObjectName(u"A1Label")
        self.A1Label.setFont(font3)

        self.gridLayout_5.addWidget(self.A1Label, 0, 1, 1, 1)

        self.label_41 = QLabel(self.gridLayoutWidget_4)
        self.label_41.setObjectName(u"label_41")
        self.label_41.setFont(font1)

        self.gridLayout_5.addWidget(self.label_41, 1, 0, 1, 1)

        self.A1Edit = QLineEdit(self.gridLayoutWidget_4)
        self.A1Edit.setObjectName(u"A1Edit")

        self.gridLayout_5.addWidget(self.A1Edit, 0, 2, 1, 1)

        self.serverAddressLabel = QLabel(self.gridLayoutWidget_4)
        self.serverAddressLabel.setObjectName(u"serverAddressLabel")

        self.gridLayout_5.addWidget(self.serverAddressLabel, 1, 1, 1, 1)

        self.serverConnectButton = QPushButton(self.gridLayoutWidget_4)
        self.serverConnectButton.setObjectName(u"serverConnectButton")
        self.serverConnectButton.setEnabled(False)

        self.gridLayout_5.addWidget(self.serverConnectButton, 2, 2, 1, 1)

        self.tabWidget_5.addTab(self.tab_2, "")
        self.tabWidget_2 = QTabWidget(self.tab_9)
        self.tabWidget_2.setObjectName(u"tabWidget_2")
        self.tabWidget_2.setGeometry(QRect(10, 140, 691, 361))
        self.tab_5 = QWidget()
        self.tab_5.setObjectName(u"tab_5")
        self.regionDefWidget = customWidget(self.tab_5)
        self.regionDefWidget.setObjectName(u"regionDefWidget")
        self.regionDefWidget.setGeometry(QRect(0, 90, 691, 241))
        self.horizontalLayoutWidget_3 = QWidget(self.tab_5)
        self.horizontalLayoutWidget_3.setObjectName(u"horizontalLayoutWidget_3")
        self.horizontalLayoutWidget_3.setGeometry(QRect(10, 10, 671, 33))
        self.horizontalLayout_10 = QHBoxLayout(self.horizontalLayoutWidget_3)
        self.horizontalLayout_10.setObjectName(u"horizontalLayout_10")
        self.horizontalLayout_10.setContentsMargins(0, 0, 0, 0)
        self.scanRegSpinbox = QSpinBox(self.horizontalLayoutWidget_3)
        self.scanRegSpinbox.setObjectName(u"scanRegSpinbox")
        sizePolicy.setHeightForWidth(self.scanRegSpinbox.sizePolicy().hasHeightForWidth())
        self.scanRegSpinbox.setSizePolicy(sizePolicy)
        self.scanRegSpinbox.setMinimumSize(QSize(80, 0))
        self.scanRegSpinbox.setMaximumSize(QSize(80, 16777215))
        self.scanRegSpinbox.setMinimum(1)
        self.scanRegSpinbox.setMaximum(100)

        self.horizontalLayout_10.addWidget(self.scanRegSpinbox)

        self.autofocusCheckbox = QCheckBox(self.horizontalLayoutWidget_3)
        self.autofocusCheckbox.setObjectName(u"autofocusCheckbox")
        self.autofocusCheckbox.setChecked(True)

        self.horizontalLayout_10.addWidget(self.autofocusCheckbox)

        self.roiCheckbox = QCheckBox(self.horizontalLayoutWidget_3)
        self.roiCheckbox.setObjectName(u"roiCheckbox")

        self.horizontalLayout_10.addWidget(self.roiCheckbox)

        self.defocusCheckbox = QCheckBox(self.horizontalLayoutWidget_3)
        self.defocusCheckbox.setObjectName(u"defocusCheckbox")

        self.horizontalLayout_10.addWidget(self.defocusCheckbox)

        self.tiledCheckbox = QCheckBox(self.horizontalLayoutWidget_3)
        self.tiledCheckbox.setObjectName(u"tiledCheckbox")

        self.horizontalLayout_10.addWidget(self.tiledCheckbox)

        self.beginScanButton = QPushButton(self.horizontalLayoutWidget_3)
        self.beginScanButton.setObjectName(u"beginScanButton")
        self.beginScanButton.setMinimumSize(QSize(0, 30))
        self.beginScanButton.setMaximumSize(QSize(16777215, 30))

        self.horizontalLayout_10.addWidget(self.beginScanButton)

        self.cancelButton = QPushButton(self.horizontalLayoutWidget_3)
        self.cancelButton.setObjectName(u"cancelButton")
        self.cancelButton.setMinimumSize(QSize(0, 30))
        self.cancelButton.setMaximumSize(QSize(16777215, 30))

        self.horizontalLayout_10.addWidget(self.cancelButton)

        self.horizontalLayoutWidget_6 = QWidget(self.tab_5)
        self.horizontalLayoutWidget_6.setObjectName(u"horizontalLayoutWidget_6")
        self.horizontalLayoutWidget_6.setGeometry(QRect(262, 50, 421, 32))
        self.horizontalLayout_13 = QHBoxLayout(self.horizontalLayoutWidget_6)
        self.horizontalLayout_13.setObjectName(u"horizontalLayout_13")
        self.horizontalLayout_13.setContentsMargins(0, 0, 0, 0)
        self.label_8 = QLabel(self.horizontalLayoutWidget_6)
        self.label_8.setObjectName(u"label_8")
        self.label_8.setMaximumSize(QSize(15, 16777215))

        self.horizontalLayout_13.addWidget(self.label_8)

        self.xMotorCombo = QComboBox(self.horizontalLayoutWidget_6)
        self.xMotorCombo.setObjectName(u"xMotorCombo")

        self.horizontalLayout_13.addWidget(self.xMotorCombo)

        self.label_11 = QLabel(self.horizontalLayoutWidget_6)
        self.label_11.setObjectName(u"label_11")
        self.label_11.setMaximumSize(QSize(15, 16777215))

        self.horizontalLayout_13.addWidget(self.label_11)

        self.yMotorCombo = QComboBox(self.horizontalLayoutWidget_6)
        self.yMotorCombo.setObjectName(u"yMotorCombo")

        self.horizontalLayout_13.addWidget(self.yMotorCombo)

        self.shutterComboBox = QComboBox(self.horizontalLayoutWidget_6)
        self.shutterComboBox.addItem("")
        self.shutterComboBox.addItem("")
        self.shutterComboBox.addItem("")
        self.shutterComboBox.setObjectName(u"shutterComboBox")

        self.horizontalLayout_13.addWidget(self.shutterComboBox)

        self.tabWidget_2.addTab(self.tab_5, "")
        self.tab_6 = QWidget()
        self.tab_6.setObjectName(u"tab_6")
        self.energyDefWidget = customWidget(self.tab_6)
        self.energyDefWidget.setObjectName(u"energyDefWidget")
        self.energyDefWidget.setGeometry(QRect(0, 40, 691, 291))
        self.energyListWidget = QWidget(self.energyDefWidget)
        self.energyListWidget.setObjectName(u"energyListWidget")
        self.energyListWidget.setGeometry(QRect(20, 120, 641, 51))
        self.horizontalLayoutWidget_4 = QWidget(self.energyListWidget)
        self.horizontalLayoutWidget_4.setObjectName(u"horizontalLayoutWidget_4")
        self.horizontalLayoutWidget_4.setGeometry(QRect(0, 10, 641, 32))
        self.energyListLayout = QHBoxLayout(self.horizontalLayoutWidget_4)
        self.energyListLayout.setObjectName(u"energyListLayout")
        self.energyListLayout.setContentsMargins(0, 0, 0, 0)
        self.label_10 = QLabel(self.horizontalLayoutWidget_4)
        self.label_10.setObjectName(u"label_10")

        self.energyListLayout.addWidget(self.label_10)

        self.energyListEdit = QTextEdit(self.horizontalLayoutWidget_4)
        self.energyListEdit.setObjectName(u"energyListEdit")
        self.energyListEdit.setMinimumSize(QSize(0, 30))
        self.energyListEdit.setMaximumSize(QSize(570, 30))

        self.energyListLayout.addWidget(self.energyListEdit)

        self.horizontalLayoutWidget_2 = QWidget(self.tab_6)
        self.horizontalLayoutWidget_2.setObjectName(u"horizontalLayoutWidget_2")
        self.horizontalLayoutWidget_2.setGeometry(QRect(10, 10, 676, 33))
        self.horizontalLayout_9 = QHBoxLayout(self.horizontalLayoutWidget_2)
        self.horizontalLayout_9.setObjectName(u"horizontalLayout_9")
        self.horizontalLayout_9.setContentsMargins(0, 0, 0, 0)
        self.energyRegSpinbox = QSpinBox(self.horizontalLayoutWidget_2)
        self.energyRegSpinbox.setObjectName(u"energyRegSpinbox")
        sizePolicy.setHeightForWidth(self.energyRegSpinbox.sizePolicy().hasHeightForWidth())
        self.energyRegSpinbox.setSizePolicy(sizePolicy)
        self.energyRegSpinbox.setMinimumSize(QSize(50, 0))
        self.energyRegSpinbox.setMaximumSize(QSize(50, 16777215))
        self.energyRegSpinbox.setMinimum(1)
        self.energyRegSpinbox.setMaximum(10)

        self.horizontalLayout_9.addWidget(self.energyRegSpinbox)

        self.toggleSingleEnergy = QCheckBox(self.horizontalLayoutWidget_2)
        self.toggleSingleEnergy.setObjectName(u"toggleSingleEnergy")
        sizePolicy.setHeightForWidth(self.toggleSingleEnergy.sizePolicy().hasHeightForWidth())
        self.toggleSingleEnergy.setSizePolicy(sizePolicy)
        self.toggleSingleEnergy.setMinimumSize(QSize(115, 0))
        self.toggleSingleEnergy.setMaximumSize(QSize(115, 16777215))
        self.toggleSingleEnergy.setChecked(True)

        self.horizontalLayout_9.addWidget(self.toggleSingleEnergy)

        self.energyListCheckbox = QCheckBox(self.horizontalLayoutWidget_2)
        self.energyListCheckbox.setObjectName(u"energyListCheckbox")
        self.energyListCheckbox.setCheckable(True)

        self.horizontalLayout_9.addWidget(self.energyListCheckbox)

        self.doubleExposureCheckbox = QCheckBox(self.horizontalLayoutWidget_2)
        self.doubleExposureCheckbox.setObjectName(u"doubleExposureCheckbox")

        self.horizontalLayout_9.addWidget(self.doubleExposureCheckbox)

        self.multiFrameCheckbox = QCheckBox(self.horizontalLayoutWidget_2)
        self.multiFrameCheckbox.setObjectName(u"multiFrameCheckbox")

        self.horizontalLayout_9.addWidget(self.multiFrameCheckbox)

        self.firstEnergyButton = QPushButton(self.horizontalLayoutWidget_2)
        self.firstEnergyButton.setObjectName(u"firstEnergyButton")
        sizePolicy7 = QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        sizePolicy7.setHorizontalStretch(0)
        sizePolicy7.setVerticalStretch(0)
        sizePolicy7.setHeightForWidth(self.firstEnergyButton.sizePolicy().hasHeightForWidth())
        self.firstEnergyButton.setSizePolicy(sizePolicy7)
        self.firstEnergyButton.setMinimumSize(QSize(100, 30))
        self.firstEnergyButton.setMaximumSize(QSize(160, 16777215))

        self.horizontalLayout_9.addWidget(self.firstEnergyButton)

        self.tabWidget_2.addTab(self.tab_6, "")
        self.tab_7 = QWidget()
        self.tab_7.setObjectName(u"tab_7")
        self.gridLayoutWidget_2 = QWidget(self.tab_7)
        self.gridLayoutWidget_2.setObjectName(u"gridLayoutWidget_2")
        self.gridLayoutWidget_2.setGeometry(QRect(9, 9, 671, 305))
        self.gridLayout_7 = QGridLayout(self.gridLayoutWidget_2)
        self.gridLayout_7.setObjectName(u"gridLayout_7")
        self.gridLayout_7.setContentsMargins(0, 0, 0, 0)
        self.horizontalLayout_11 = QHBoxLayout()
        self.horizontalLayout_11.setObjectName(u"horizontalLayout_11")

        self.gridLayout_7.addLayout(self.horizontalLayout_11, 1, 0, 1, 1)

        self.showBeamPosition = QCheckBox(self.gridLayoutWidget_2)
        self.showBeamPosition.setObjectName(u"showBeamPosition")
        self.showBeamPosition.setChecked(False)

        self.gridLayout_7.addWidget(self.showBeamPosition, 6, 0, 1, 1)

        self.autorangeCheckbox = QCheckBox(self.gridLayoutWidget_2)
        self.autorangeCheckbox.setObjectName(u"autorangeCheckbox")
        self.autorangeCheckbox.setChecked(True)

        self.gridLayout_7.addWidget(self.autorangeCheckbox, 4, 0, 1, 1)

        self.showRangeFinder = QCheckBox(self.gridLayoutWidget_2)
        self.showRangeFinder.setObjectName(u"showRangeFinder")
        self.showRangeFinder.setChecked(True)

        self.gridLayout_7.addWidget(self.showRangeFinder, 5, 0, 1, 1)

        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")

        self.gridLayout_7.addLayout(self.verticalLayout, 0, 0, 1, 1)

        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")

        self.gridLayout_7.addLayout(self.verticalLayout_2, 2, 0, 1, 1)

        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.compositeImageCheckbox = QCheckBox(self.gridLayoutWidget_2)
        self.compositeImageCheckbox.setObjectName(u"compositeImageCheckbox")
        self.compositeImageCheckbox.setChecked(True)

        self.horizontalLayout_4.addWidget(self.compositeImageCheckbox)

        self.clearImageButton = QPushButton(self.gridLayoutWidget_2)
        self.clearImageButton.setObjectName(u"clearImageButton")

        self.horizontalLayout_4.addWidget(self.clearImageButton)

        self.removeLastImageButton = QPushButton(self.gridLayoutWidget_2)
        self.removeLastImageButton.setObjectName(u"removeLastImageButton")

        self.horizontalLayout_4.addWidget(self.removeLastImageButton)


        self.gridLayout_7.addLayout(self.horizontalLayout_4, 8, 0, 1, 1)

        self.snapRoiToFovButton = QPushButton(self.gridLayoutWidget_2)
        self.snapRoiToFovButton.setObjectName(u"snapRoiToFovButton")

        self.gridLayout_7.addWidget(self.snapRoiToFovButton, 9, 0, 1, 1)

        self.snapFovToRoiButton = QPushButton(self.gridLayoutWidget_2)
        self.snapFovToRoiButton.setObjectName(u"snapFovToRoiButton")

        self.gridLayout_7.addWidget(self.snapFovToRoiButton, 10, 0, 1, 1)

        self.autoscaleCheckbox = QCheckBox(self.gridLayoutWidget_2)
        self.autoscaleCheckbox.setObjectName(u"autoscaleCheckbox")
        self.autoscaleCheckbox.setChecked(True)

        self.gridLayout_7.addWidget(self.autoscaleCheckbox, 3, 0, 1, 1)

        self.tabWidget_2.addTab(self.tab_7, "")
        self.tab_8 = QWidget()
        self.tab_8.setObjectName(u"tab_8")
        self.scrollArea = QScrollArea(self.tab_8)
        self.scrollArea.setObjectName(u"scrollArea")
        self.scrollArea.setGeometry(QRect(0, 0, 691, 321))
        self.scrollArea.setWidgetResizable(True)
        self.scrollAreaWidgetContents = QWidget()
        self.scrollAreaWidgetContents.setObjectName(u"scrollAreaWidgetContents")
        self.scrollAreaWidgetContents.setGeometry(QRect(0, 0, 689, 319))
        self.horizontalLayout_2 = QHBoxLayout(self.scrollAreaWidgetContents)
        self.horizontalLayout_2.setObjectName(u"horizontalLayout_2")
        self.serverOutput = QTextEdit(self.scrollAreaWidgetContents)
        self.serverOutput.setObjectName(u"serverOutput")

        self.horizontalLayout_2.addWidget(self.serverOutput)

        self.scrollArea.setWidget(self.scrollAreaWidgetContents)
        self.tabWidget_2.addTab(self.tab_8, "")
        self.tabWidget_3.addTab(self.tab_9, "")
        self.tab_analysis2 = QWidget()
        self.tab_analysis2.setObjectName(u"tab_analysis2")
        self.tab_analysis2_layout = QVBoxLayout(self.tab_analysis2)
        self.tab_analysis2_layout.setSpacing(2)
        self.tab_analysis2_layout.setObjectName(u"tab_analysis2_layout")
        self.tab_analysis2_layout.setContentsMargins(0, 0, 0, 0)
        self.a2_stack_viewer = stackViewerWidget(self.tab_analysis2)
        self.a2_stack_viewer.setObjectName(u"a2_stack_viewer")
        self.a2_stack_viewer.setVisible(False)

        self.tab_analysis2_layout.addWidget(self.a2_stack_viewer)

        self.a2_topSplitter = QSplitter(self.tab_analysis2)
        self.a2_topSplitter.setObjectName(u"a2_topSplitter")
        self.a2_topSplitter.setOrientation(Qt.Horizontal)
        self.a2_rightPane = QWidget(self.a2_topSplitter)
        self.a2_rightPane.setObjectName(u"a2_rightPane")
        sizePolicy8 = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy8.setHorizontalStretch(1)
        sizePolicy8.setVerticalStretch(0)
        sizePolicy8.setHeightForWidth(self.a2_rightPane.sizePolicy().hasHeightForWidth())
        self.a2_rightPane.setSizePolicy(sizePolicy8)
        self.a2_rightPane_layout = QVBoxLayout(self.a2_rightPane)
        self.a2_rightPane_layout.setSpacing(4)
        self.a2_rightPane_layout.setObjectName(u"a2_rightPane_layout")
        self.a2_rightPane_layout.setContentsMargins(0, 0, 0, 0)
        self.a2_spectrumPlot = PlotWidget(self.a2_rightPane)
        self.a2_spectrumPlot.setObjectName(u"a2_spectrumPlot")

        self.a2_rightPane_layout.addWidget(self.a2_spectrumPlot)

        self.a2_workflowTabs = QTabWidget(self.a2_rightPane)
        self.a2_workflowTabs.setObjectName(u"a2_workflowTabs")
        sizePolicy6.setHeightForWidth(self.a2_workflowTabs.sizePolicy().hasHeightForWidth())
        self.a2_workflowTabs.setSizePolicy(sizePolicy6)
        self.a2_workflowTabs.setMinimumSize(QSize(0, 600))
        self.a2_tab_main = QWidget()
        self.a2_tab_main.setObjectName(u"a2_tab_main")
        self.a2_tab_main_layout = QVBoxLayout(self.a2_tab_main)
        self.a2_tab_main_layout.setSpacing(6)
        self.a2_tab_main_layout.setObjectName(u"a2_tab_main_layout")
        self.a2_tab_main_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_main_buttons_layout = QHBoxLayout()
        self.a2_main_buttons_layout.setObjectName(u"a2_main_buttons_layout")
        self.a2_openStackButton = QPushButton(self.a2_tab_main)
        self.a2_openStackButton.setObjectName(u"a2_openStackButton")

        self.a2_main_buttons_layout.addWidget(self.a2_openStackButton)

        self.a2_saveDataButton = QPushButton(self.a2_tab_main)
        self.a2_saveDataButton.setObjectName(u"a2_saveDataButton")

        self.a2_main_buttons_layout.addWidget(self.a2_saveDataButton)

        self.a2_addToLogButton = QPushButton(self.a2_tab_main)
        self.a2_addToLogButton.setObjectName(u"a2_addToLogButton")

        self.a2_main_buttons_layout.addWidget(self.a2_addToLogButton)

        self.horizontalSpacer_2 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_main_buttons_layout.addItem(self.horizontalSpacer_2)


        self.a2_tab_main_layout.addLayout(self.a2_main_buttons_layout)

        self.a2_roi_separator = QFrame(self.a2_tab_main)
        self.a2_roi_separator.setObjectName(u"a2_roi_separator")
        self.a2_roi_separator.setFrameShape(QFrame.HLine)
        self.a2_roi_separator.setFrameShadow(QFrame.Sunken)

        self.a2_tab_main_layout.addWidget(self.a2_roi_separator)

        self.a2_roi_type_layout = QHBoxLayout()
        self.a2_roi_type_layout.setObjectName(u"a2_roi_type_layout")
        self.a2_roiTypeLabel = QLabel(self.a2_tab_main)
        self.a2_roiTypeLabel.setObjectName(u"a2_roiTypeLabel")

        self.a2_roi_type_layout.addWidget(self.a2_roiTypeLabel)

        self.a2_roiTypeCombo = QComboBox(self.a2_tab_main)
        self.a2_roiTypeCombo.addItem("")
        self.a2_roiTypeCombo.addItem("")
        self.a2_roiTypeCombo.setObjectName(u"a2_roiTypeCombo")

        self.a2_roi_type_layout.addWidget(self.a2_roiTypeCombo)

        self.a2_drawRoiCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_drawRoiCheckbox.setObjectName(u"a2_drawRoiCheckbox")

        self.a2_roi_type_layout.addWidget(self.a2_drawRoiCheckbox)

        self.a2_deleteRoiButton = QPushButton(self.a2_tab_main)
        self.a2_deleteRoiButton.setObjectName(u"a2_deleteRoiButton")

        self.a2_roi_type_layout.addWidget(self.a2_deleteRoiButton)

        self.a2_deleteFrameButton = QPushButton(self.a2_tab_main)
        self.a2_deleteFrameButton.setObjectName(u"a2_deleteFrameButton")

        self.a2_roi_type_layout.addWidget(self.a2_deleteFrameButton)

        self.a2_roi_type_hSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_roi_type_layout.addItem(self.a2_roi_type_hSpacer)


        self.a2_tab_main_layout.addLayout(self.a2_roi_type_layout)

        self.a2_roi_draw_layout = QHBoxLayout()
        self.a2_roi_draw_layout.setObjectName(u"a2_roi_draw_layout")
        self.a2_odCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_odCheckbox.setObjectName(u"a2_odCheckbox")
        self.a2_odCheckbox.setEnabled(False)

        self.a2_roi_draw_layout.addWidget(self.a2_odCheckbox)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_roi_draw_layout.addItem(self.horizontalSpacer)


        self.a2_tab_main_layout.addLayout(self.a2_roi_draw_layout)

        self.a2_norm_separator = QFrame(self.a2_tab_main)
        self.a2_norm_separator.setObjectName(u"a2_norm_separator")
        self.a2_norm_separator.setFrameShape(QFrame.HLine)
        self.a2_norm_separator.setFrameShadow(QFrame.Sunken)

        self.a2_tab_main_layout.addWidget(self.a2_norm_separator)

        self.a2_edge_select_layout = QHBoxLayout()
        self.a2_edge_select_layout.setObjectName(u"a2_edge_select_layout")
        self.a2_autoProcessButton = QPushButton(self.a2_tab_main)
        self.a2_autoProcessButton.setObjectName(u"a2_autoProcessButton")

        self.a2_edge_select_layout.addWidget(self.a2_autoProcessButton)

        self.a2_mapButton = QPushButton(self.a2_tab_main)
        self.a2_mapButton.setObjectName(u"a2_mapButton")
        self.a2_mapButton.setEnabled(False)

        self.a2_edge_select_layout.addWidget(self.a2_mapButton)

        self.a2_resetButton = QPushButton(self.a2_tab_main)
        self.a2_resetButton.setObjectName(u"a2_resetButton")

        self.a2_edge_select_layout.addWidget(self.a2_resetButton)


        self.a2_tab_main_layout.addLayout(self.a2_edge_select_layout)

        self.a2_norm_buttons_layout = QHBoxLayout()
        self.a2_norm_buttons_layout.setObjectName(u"a2_norm_buttons_layout")
        self.a2_norm_buttons_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_norm_buttons_layout.addItem(self.a2_norm_buttons_spacer)


        self.a2_tab_main_layout.addLayout(self.a2_norm_buttons_layout)

        self.a2_process_buttons_layout = QHBoxLayout()
        self.a2_process_buttons_layout.setObjectName(u"a2_process_buttons_layout")
        self.a2_preEdgeCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_preEdgeCheckbox.setObjectName(u"a2_preEdgeCheckbox")

        self.a2_process_buttons_layout.addWidget(self.a2_preEdgeCheckbox)

        self.a2_subtractPreEdgeButton = QPushButton(self.a2_tab_main)
        self.a2_subtractPreEdgeButton.setObjectName(u"a2_subtractPreEdgeButton")
        self.a2_subtractPreEdgeButton.setEnabled(False)

        self.a2_process_buttons_layout.addWidget(self.a2_subtractPreEdgeButton)

        self.a2_postEdgeCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_postEdgeCheckbox.setObjectName(u"a2_postEdgeCheckbox")
        self.a2_postEdgeCheckbox.setEnabled(False)

        self.a2_process_buttons_layout.addWidget(self.a2_postEdgeCheckbox)

        self.a2_normalizePostEdgeButton = QPushButton(self.a2_tab_main)
        self.a2_normalizePostEdgeButton.setObjectName(u"a2_normalizePostEdgeButton")
        self.a2_normalizePostEdgeButton.setEnabled(False)

        self.a2_process_buttons_layout.addWidget(self.a2_normalizePostEdgeButton)


        self.a2_tab_main_layout.addLayout(self.a2_process_buttons_layout)

        self.a2_progressBar = QProgressBar(self.a2_tab_main)
        self.a2_progressBar.setObjectName(u"a2_progressBar")
        self.a2_progressBar.setValue(0)
        self.a2_progressBar.setTextVisible(True)

        self.a2_tab_main_layout.addWidget(self.a2_progressBar)

        self.a2_trackMouseCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_trackMouseCheckbox.setObjectName(u"a2_trackMouseCheckbox")
        self.a2_trackMouseCheckbox.setChecked(True)

        self.a2_tab_main_layout.addWidget(self.a2_trackMouseCheckbox)

        self.a2_liveDisplayCheckbox = QCheckBox(self.a2_tab_main)
        self.a2_liveDisplayCheckbox.setObjectName(u"a2_liveDisplayCheckbox")

        self.a2_tab_main_layout.addWidget(self.a2_liveDisplayCheckbox)

        self.a2_main_vSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_main_layout.addItem(self.a2_main_vSpacer)

        self.a2_workflowTabs.addTab(self.a2_tab_main, "")
        self.a2_tab_filtering = QWidget()
        self.a2_tab_filtering.setObjectName(u"a2_tab_filtering")
        self.a2_tab_filtering_layout = QVBoxLayout(self.a2_tab_filtering)
        self.a2_tab_filtering_layout.setSpacing(6)
        self.a2_tab_filtering_layout.setObjectName(u"a2_tab_filtering_layout")
        self.a2_tab_filtering_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_subtract_dark_layout = QHBoxLayout()
        self.a2_subtract_dark_layout.setObjectName(u"a2_subtract_dark_layout")
        self.a2_darkLevelLabel = QLabel(self.a2_tab_filtering)
        self.a2_darkLevelLabel.setObjectName(u"a2_darkLevelLabel")

        self.a2_subtract_dark_layout.addWidget(self.a2_darkLevelLabel)

        self.a2_darkLevelEdit = QLineEdit(self.a2_tab_filtering)
        self.a2_darkLevelEdit.setObjectName(u"a2_darkLevelEdit")

        self.a2_subtract_dark_layout.addWidget(self.a2_darkLevelEdit)

        self.a2_subtractDarkButton = QPushButton(self.a2_tab_filtering)
        self.a2_subtractDarkButton.setObjectName(u"a2_subtractDarkButton")

        self.a2_subtract_dark_layout.addWidget(self.a2_subtractDarkButton)


        self.a2_tab_filtering_layout.addLayout(self.a2_subtract_dark_layout)

        self.a2_undo_row_layout = QHBoxLayout()
        self.a2_undo_row_layout.setObjectName(u"a2_undo_row_layout")
        self.a2_undo_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_undo_row_layout.addItem(self.a2_undo_spacer)

        self.a2_filterUndoButton = QPushButton(self.a2_tab_filtering)
        self.a2_filterUndoButton.setObjectName(u"a2_filterUndoButton")

        self.a2_undo_row_layout.addWidget(self.a2_filterUndoButton)


        self.a2_tab_filtering_layout.addLayout(self.a2_undo_row_layout)

        self.a2_filter_line1 = QFrame(self.a2_tab_filtering)
        self.a2_filter_line1.setObjectName(u"a2_filter_line1")
        self.a2_filter_line1.setFrameShape(QFrame.Shape.HLine)
        self.a2_filter_line1.setFrameShadow(QFrame.Shadow.Sunken)

        self.a2_tab_filtering_layout.addWidget(self.a2_filter_line1)

        self.a2_median_filter_layout = QHBoxLayout()
        self.a2_median_filter_layout.setObjectName(u"a2_median_filter_layout")
        self.a2_medianKernelLabel = QLabel(self.a2_tab_filtering)
        self.a2_medianKernelLabel.setObjectName(u"a2_medianKernelLabel")

        self.a2_median_filter_layout.addWidget(self.a2_medianKernelLabel)

        self.a2_medianKernelEdit = QLineEdit(self.a2_tab_filtering)
        self.a2_medianKernelEdit.setObjectName(u"a2_medianKernelEdit")

        self.a2_median_filter_layout.addWidget(self.a2_medianKernelEdit)

        self.a2_medianFilterButton = QPushButton(self.a2_tab_filtering)
        self.a2_medianFilterButton.setObjectName(u"a2_medianFilterButton")

        self.a2_median_filter_layout.addWidget(self.a2_medianFilterButton)


        self.a2_tab_filtering_layout.addLayout(self.a2_median_filter_layout)

        self.a2_filter_line2 = QFrame(self.a2_tab_filtering)
        self.a2_filter_line2.setObjectName(u"a2_filter_line2")
        self.a2_filter_line2.setFrameShape(QFrame.Shape.HLine)
        self.a2_filter_line2.setFrameShadow(QFrame.Shadow.Sunken)

        self.a2_tab_filtering_layout.addWidget(self.a2_filter_line2)

        self.a2_despike_layout = QHBoxLayout()
        self.a2_despike_layout.setObjectName(u"a2_despike_layout")
        self.a2_despikeKernelLabel = QLabel(self.a2_tab_filtering)
        self.a2_despikeKernelLabel.setObjectName(u"a2_despikeKernelLabel")

        self.a2_despike_layout.addWidget(self.a2_despikeKernelLabel)

        self.a2_despikeKernelEdit = QLineEdit(self.a2_tab_filtering)
        self.a2_despikeKernelEdit.setObjectName(u"a2_despikeKernelEdit")

        self.a2_despike_layout.addWidget(self.a2_despikeKernelEdit)

        self.a2_despikeNSigmaLabel = QLabel(self.a2_tab_filtering)
        self.a2_despikeNSigmaLabel.setObjectName(u"a2_despikeNSigmaLabel")

        self.a2_despike_layout.addWidget(self.a2_despikeNSigmaLabel)

        self.a2_despikeNSigmaEdit = QLineEdit(self.a2_tab_filtering)
        self.a2_despikeNSigmaEdit.setObjectName(u"a2_despikeNSigmaEdit")

        self.a2_despike_layout.addWidget(self.a2_despikeNSigmaEdit)

        self.a2_despikeButton = QPushButton(self.a2_tab_filtering)
        self.a2_despikeButton.setObjectName(u"a2_despikeButton")

        self.a2_despike_layout.addWidget(self.a2_despikeButton)


        self.a2_tab_filtering_layout.addLayout(self.a2_despike_layout)

        self.a2_filter_vspacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_filtering_layout.addItem(self.a2_filter_vspacer)

        self.a2_workflowTabs.addTab(self.a2_tab_filtering, "")
        self.a2_tab_registration = QWidget()
        self.a2_tab_registration.setObjectName(u"a2_tab_registration")
        self.a2_tab_registration_layout = QVBoxLayout(self.a2_tab_registration)
        self.a2_tab_registration_layout.setSpacing(6)
        self.a2_tab_registration_layout.setObjectName(u"a2_tab_registration_layout")
        self.a2_tab_registration_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_reg_mode_layout = QHBoxLayout()
        self.a2_reg_mode_layout.setObjectName(u"a2_reg_mode_layout")
        self.a2_regModeLabel = QLabel(self.a2_tab_registration)
        self.a2_regModeLabel.setObjectName(u"a2_regModeLabel")

        self.a2_reg_mode_layout.addWidget(self.a2_regModeLabel)

        self.a2_regModeCombo = QComboBox(self.a2_tab_registration)
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.addItem("")
        self.a2_regModeCombo.setObjectName(u"a2_regModeCombo")

        self.a2_reg_mode_layout.addWidget(self.a2_regModeCombo)

        self.horizontalSpacer_3 = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_mode_layout.addItem(self.horizontalSpacer_3)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_mode_layout)

        self.a2_reg_options_layout = QHBoxLayout()
        self.a2_reg_options_layout.setObjectName(u"a2_reg_options_layout")
        self.a2_regSobelCheckbox = QCheckBox(self.a2_tab_registration)
        self.a2_regSobelCheckbox.setObjectName(u"a2_regSobelCheckbox")

        self.a2_reg_options_layout.addWidget(self.a2_regSobelCheckbox)

        self.a2_regAutocropCheckbox = QCheckBox(self.a2_tab_registration)
        self.a2_regAutocropCheckbox.setObjectName(u"a2_regAutocropCheckbox")
        self.a2_regAutocropCheckbox.setChecked(True)

        self.a2_reg_options_layout.addWidget(self.a2_regAutocropCheckbox)

        self.a2_reg_options_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_options_layout.addItem(self.a2_reg_options_spacer)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_options_layout)

        self.a2_reg_buttons_layout = QHBoxLayout()
        self.a2_reg_buttons_layout.setObjectName(u"a2_reg_buttons_layout")
        self.a2_regStartButton = QPushButton(self.a2_tab_registration)
        self.a2_regStartButton.setObjectName(u"a2_regStartButton")

        self.a2_reg_buttons_layout.addWidget(self.a2_regStartButton)

        self.a2_regUndoButton = QPushButton(self.a2_tab_registration)
        self.a2_regUndoButton.setObjectName(u"a2_regUndoButton")

        self.a2_reg_buttons_layout.addWidget(self.a2_regUndoButton)

        self.a2_reg_buttons_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_reg_buttons_layout.addItem(self.a2_reg_buttons_spacer)


        self.a2_tab_registration_layout.addLayout(self.a2_reg_buttons_layout)

        self.a2_regProgressBar = QProgressBar(self.a2_tab_registration)
        self.a2_regProgressBar.setObjectName(u"a2_regProgressBar")
        self.a2_regProgressBar.setValue(0)
        self.a2_regProgressBar.setTextVisible(True)

        self.a2_tab_registration_layout.addWidget(self.a2_regProgressBar)

        self.a2_reg_vspacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_registration_layout.addItem(self.a2_reg_vspacer)

        self.a2_workflowTabs.addTab(self.a2_tab_registration, "")
        self.a2_tab_clustering = QWidget()
        self.a2_tab_clustering.setObjectName(u"a2_tab_clustering")
        self.a2_tab_clustering_layout = QVBoxLayout(self.a2_tab_clustering)
        self.a2_tab_clustering_layout.setSpacing(6)
        self.a2_tab_clustering_layout.setObjectName(u"a2_tab_clustering_layout")
        self.a2_tab_clustering_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_pca_params_layout = QHBoxLayout()
        self.a2_pca_params_layout.setObjectName(u"a2_pca_params_layout")
        self.a2_nComponentsLabel = QLabel(self.a2_tab_clustering)
        self.a2_nComponentsLabel.setObjectName(u"a2_nComponentsLabel")

        self.a2_pca_params_layout.addWidget(self.a2_nComponentsLabel)

        self.a2_nComponentsEdit = QLineEdit(self.a2_tab_clustering)
        self.a2_nComponentsEdit.setObjectName(u"a2_nComponentsEdit")

        self.a2_pca_params_layout.addWidget(self.a2_nComponentsEdit)

        self.a2_nClustersLabel = QLabel(self.a2_tab_clustering)
        self.a2_nClustersLabel.setObjectName(u"a2_nClustersLabel")

        self.a2_pca_params_layout.addWidget(self.a2_nClustersLabel)

        self.a2_nClustersEdit = QLineEdit(self.a2_tab_clustering)
        self.a2_nClustersEdit.setObjectName(u"a2_nClustersEdit")

        self.a2_pca_params_layout.addWidget(self.a2_nClustersEdit)

        self.a2_pca_params_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_pca_params_layout.addItem(self.a2_pca_params_spacer)


        self.a2_tab_clustering_layout.addLayout(self.a2_pca_params_layout)

        self.a2_pca_options_layout = QHBoxLayout()
        self.a2_pca_options_layout.setObjectName(u"a2_pca_options_layout")
        self.a2_reduceMassCheckbox = QCheckBox(self.a2_tab_clustering)
        self.a2_reduceMassCheckbox.setObjectName(u"a2_reduceMassCheckbox")

        self.a2_pca_options_layout.addWidget(self.a2_reduceMassCheckbox)

        self.a2_removePreEdgeCheckbox = QCheckBox(self.a2_tab_clustering)
        self.a2_removePreEdgeCheckbox.setObjectName(u"a2_removePreEdgeCheckbox")

        self.a2_pca_options_layout.addWidget(self.a2_removePreEdgeCheckbox)

        self.a2_pca_options_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_pca_options_layout.addItem(self.a2_pca_options_spacer)


        self.a2_tab_clustering_layout.addLayout(self.a2_pca_options_layout)

        self.a2_calc_pca_layout = QHBoxLayout()
        self.a2_calc_pca_layout.setObjectName(u"a2_calc_pca_layout")
        self.a2_calcPCAButton = QPushButton(self.a2_tab_clustering)
        self.a2_calcPCAButton.setObjectName(u"a2_calcPCAButton")

        self.a2_calc_pca_layout.addWidget(self.a2_calcPCAButton)

        self.a2_calc_pca_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_calc_pca_layout.addItem(self.a2_calc_pca_spacer)


        self.a2_tab_clustering_layout.addLayout(self.a2_calc_pca_layout)

        self.a2_cluster_line1 = QFrame(self.a2_tab_clustering)
        self.a2_cluster_line1.setObjectName(u"a2_cluster_line1")
        self.a2_cluster_line1.setFrameShape(QFrame.Shape.HLine)
        self.a2_cluster_line1.setFrameShadow(QFrame.Shadow.Sunken)

        self.a2_tab_clustering_layout.addWidget(self.a2_cluster_line1)

        self.a2_cluster_image_layout = QHBoxLayout()
        self.a2_cluster_image_layout.setObjectName(u"a2_cluster_image_layout")
        self.a2_clusterImageLabel = QLabel(self.a2_tab_clustering)
        self.a2_clusterImageLabel.setObjectName(u"a2_clusterImageLabel")

        self.a2_cluster_image_layout.addWidget(self.a2_clusterImageLabel)

        self.a2_clusterImageCombo = QComboBox(self.a2_tab_clustering)
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.addItem("")
        self.a2_clusterImageCombo.setObjectName(u"a2_clusterImageCombo")
        self.a2_clusterImageCombo.setEnabled(False)

        self.a2_cluster_image_layout.addWidget(self.a2_clusterImageCombo)


        self.a2_tab_clustering_layout.addLayout(self.a2_cluster_image_layout)

        self.a2_cluster_plot_layout = QHBoxLayout()
        self.a2_cluster_plot_layout.setObjectName(u"a2_cluster_plot_layout")
        self.a2_clusterPlotLabel = QLabel(self.a2_tab_clustering)
        self.a2_clusterPlotLabel.setObjectName(u"a2_clusterPlotLabel")

        self.a2_cluster_plot_layout.addWidget(self.a2_clusterPlotLabel)

        self.a2_clusterPlotCombo = QComboBox(self.a2_tab_clustering)
        self.a2_clusterPlotCombo.addItem("")
        self.a2_clusterPlotCombo.addItem("")
        self.a2_clusterPlotCombo.addItem("")
        self.a2_clusterPlotCombo.setObjectName(u"a2_clusterPlotCombo")
        self.a2_clusterPlotCombo.setEnabled(False)

        self.a2_cluster_plot_layout.addWidget(self.a2_clusterPlotCombo)


        self.a2_tab_clustering_layout.addLayout(self.a2_cluster_plot_layout)

        self.a2_rgb_map_layout = QHBoxLayout()
        self.a2_rgb_map_layout.setObjectName(u"a2_rgb_map_layout")
        self.a2_targetSpectraLabel = QLabel(self.a2_tab_clustering)
        self.a2_targetSpectraLabel.setObjectName(u"a2_targetSpectraLabel")

        self.a2_rgb_map_layout.addWidget(self.a2_targetSpectraLabel)

        self.a2_targetSpectraEdit = QLineEdit(self.a2_tab_clustering)
        self.a2_targetSpectraEdit.setObjectName(u"a2_targetSpectraEdit")

        self.a2_rgb_map_layout.addWidget(self.a2_targetSpectraEdit)

        self.a2_calcRGBMapButton = QPushButton(self.a2_tab_clustering)
        self.a2_calcRGBMapButton.setObjectName(u"a2_calcRGBMapButton")

        self.a2_rgb_map_layout.addWidget(self.a2_calcRGBMapButton)


        self.a2_tab_clustering_layout.addLayout(self.a2_rgb_map_layout)

        self.a2_cluster_vspacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_clustering_layout.addItem(self.a2_cluster_vspacer)

        self.a2_workflowTabs.addTab(self.a2_tab_clustering, "")
        self.a2_tab_nnmf = QWidget()
        self.a2_tab_nnmf.setObjectName(u"a2_tab_nnmf")
        self.a2_tab_nnmf_layout = QVBoxLayout(self.a2_tab_nnmf)
        self.a2_tab_nnmf_layout.setSpacing(6)
        self.a2_tab_nnmf_layout.setObjectName(u"a2_tab_nnmf_layout")
        self.a2_tab_nnmf_layout.setContentsMargins(6, 6, 6, 6)
        self.a2_nmf_params1_layout = QHBoxLayout()
        self.a2_nmf_params1_layout.setObjectName(u"a2_nmf_params1_layout")
        self.a2_nmfNComponentsLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfNComponentsLabel.setObjectName(u"a2_nmfNComponentsLabel")

        self.a2_nmf_params1_layout.addWidget(self.a2_nmfNComponentsLabel)

        self.a2_nmfNComponentsEdit = QLineEdit(self.a2_tab_nnmf)
        self.a2_nmfNComponentsEdit.setObjectName(u"a2_nmfNComponentsEdit")

        self.a2_nmf_params1_layout.addWidget(self.a2_nmfNComponentsEdit)

        self.a2_nmfNClustersLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfNClustersLabel.setObjectName(u"a2_nmfNClustersLabel")

        self.a2_nmf_params1_layout.addWidget(self.a2_nmfNClustersLabel)

        self.a2_nmfNClustersEdit = QLineEdit(self.a2_tab_nnmf)
        self.a2_nmfNClustersEdit.setObjectName(u"a2_nmfNClustersEdit")

        self.a2_nmf_params1_layout.addWidget(self.a2_nmfNClustersEdit)

        self.a2_nmf_params1_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_nmf_params1_layout.addItem(self.a2_nmf_params1_spacer)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_params1_layout)

        self.a2_nmf_params2_layout = QHBoxLayout()
        self.a2_nmf_params2_layout.setObjectName(u"a2_nmf_params2_layout")
        self.a2_nmfMaxIterLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfMaxIterLabel.setObjectName(u"a2_nmfMaxIterLabel")

        self.a2_nmf_params2_layout.addWidget(self.a2_nmfMaxIterLabel)

        self.a2_nmfMaxIterEdit = QLineEdit(self.a2_tab_nnmf)
        self.a2_nmfMaxIterEdit.setObjectName(u"a2_nmfMaxIterEdit")

        self.a2_nmf_params2_layout.addWidget(self.a2_nmfMaxIterEdit)

        self.a2_nmfInitLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfInitLabel.setObjectName(u"a2_nmfInitLabel")

        self.a2_nmf_params2_layout.addWidget(self.a2_nmfInitLabel)

        self.a2_nmfInitCombo = QComboBox(self.a2_tab_nnmf)
        self.a2_nmfInitCombo.addItem("")
        self.a2_nmfInitCombo.addItem("")
        self.a2_nmfInitCombo.setObjectName(u"a2_nmfInitCombo")

        self.a2_nmf_params2_layout.addWidget(self.a2_nmfInitCombo)

        self.a2_nmf_params2_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_nmf_params2_layout.addItem(self.a2_nmf_params2_spacer)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_params2_layout)

        self.a2_nmf_calc_layout = QHBoxLayout()
        self.a2_nmf_calc_layout.setObjectName(u"a2_nmf_calc_layout")
        self.a2_calcNMFButton = QPushButton(self.a2_tab_nnmf)
        self.a2_calcNMFButton.setObjectName(u"a2_calcNMFButton")

        self.a2_nmf_calc_layout.addWidget(self.a2_calcNMFButton)

        self.a2_nmf_calc_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.a2_nmf_calc_layout.addItem(self.a2_nmf_calc_spacer)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_calc_layout)

        self.a2_nmfProgressBar = QProgressBar(self.a2_tab_nnmf)
        self.a2_nmfProgressBar.setObjectName(u"a2_nmfProgressBar")
        self.a2_nmfProgressBar.setValue(0)

        self.a2_tab_nnmf_layout.addWidget(self.a2_nmfProgressBar)

        self.a2_nmf_line1 = QFrame(self.a2_tab_nnmf)
        self.a2_nmf_line1.setObjectName(u"a2_nmf_line1")
        self.a2_nmf_line1.setFrameShape(QFrame.Shape.HLine)
        self.a2_nmf_line1.setFrameShadow(QFrame.Shadow.Sunken)

        self.a2_tab_nnmf_layout.addWidget(self.a2_nmf_line1)

        self.a2_nmf_display_layout = QHBoxLayout()
        self.a2_nmf_display_layout.setObjectName(u"a2_nmf_display_layout")
        self.a2_nmfDisplayLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfDisplayLabel.setObjectName(u"a2_nmfDisplayLabel")

        self.a2_nmf_display_layout.addWidget(self.a2_nmfDisplayLabel)

        self.a2_nmfDisplayCombo = QComboBox(self.a2_tab_nnmf)
        self.a2_nmfDisplayCombo.addItem("")
        self.a2_nmfDisplayCombo.addItem("")
        self.a2_nmfDisplayCombo.addItem("")
        self.a2_nmfDisplayCombo.setObjectName(u"a2_nmfDisplayCombo")
        self.a2_nmfDisplayCombo.setEnabled(False)

        self.a2_nmf_display_layout.addWidget(self.a2_nmfDisplayCombo)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_display_layout)

        self.a2_nmf_plot_layout = QHBoxLayout()
        self.a2_nmf_plot_layout.setObjectName(u"a2_nmf_plot_layout")
        self.a2_nmfPlotLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfPlotLabel.setObjectName(u"a2_nmfPlotLabel")

        self.a2_nmf_plot_layout.addWidget(self.a2_nmfPlotLabel)

        self.a2_nmfPlotCombo = QComboBox(self.a2_tab_nnmf)
        self.a2_nmfPlotCombo.addItem("")
        self.a2_nmfPlotCombo.addItem("")
        self.a2_nmfPlotCombo.setObjectName(u"a2_nmfPlotCombo")
        self.a2_nmfPlotCombo.setEnabled(False)

        self.a2_nmf_plot_layout.addWidget(self.a2_nmfPlotCombo)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_plot_layout)

        self.a2_nmf_rgb_map_layout = QHBoxLayout()
        self.a2_nmf_rgb_map_layout.setObjectName(u"a2_nmf_rgb_map_layout")
        self.a2_nmfTargetSpectraLabel = QLabel(self.a2_tab_nnmf)
        self.a2_nmfTargetSpectraLabel.setObjectName(u"a2_nmfTargetSpectraLabel")

        self.a2_nmf_rgb_map_layout.addWidget(self.a2_nmfTargetSpectraLabel)

        self.a2_nmfTargetSpectraEdit = QLineEdit(self.a2_tab_nnmf)
        self.a2_nmfTargetSpectraEdit.setObjectName(u"a2_nmfTargetSpectraEdit")

        self.a2_nmf_rgb_map_layout.addWidget(self.a2_nmfTargetSpectraEdit)

        self.a2_nmfCalcRGBMapButton = QPushButton(self.a2_tab_nnmf)
        self.a2_nmfCalcRGBMapButton.setObjectName(u"a2_nmfCalcRGBMapButton")

        self.a2_nmf_rgb_map_layout.addWidget(self.a2_nmfCalcRGBMapButton)


        self.a2_tab_nnmf_layout.addLayout(self.a2_nmf_rgb_map_layout)

        self.a2_nmf_vspacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.a2_tab_nnmf_layout.addItem(self.a2_nmf_vspacer)

        self.a2_workflowTabs.addTab(self.a2_tab_nnmf, "")
        self.a2_tab_metadata = QWidget()
        self.a2_tab_metadata.setObjectName(u"a2_tab_metadata")
        self.a2_tab_metadata_layout = QVBoxLayout(self.a2_tab_metadata)
        self.a2_tab_metadata_layout.setSpacing(0)
        self.a2_tab_metadata_layout.setObjectName(u"a2_tab_metadata_layout")
        self.a2_tab_metadata_layout.setContentsMargins(4, 4, 4, 4)
        self.a2_workflowTabs.addTab(self.a2_tab_metadata, "")

        self.a2_rightPane_layout.addWidget(self.a2_workflowTabs)

        self.a2_topSplitter.addWidget(self.a2_rightPane)
        self.a2_imagePane = QWidget(self.a2_topSplitter)
        self.a2_imagePane.setObjectName(u"a2_imagePane")
        self.a2_imagePane_layout = QVBoxLayout(self.a2_imagePane)
        self.a2_imagePane_layout.setObjectName(u"a2_imagePane_layout")
        self.a2_imagePane_layout.setContentsMargins(0, 0, 0, 0)
        self.a2_imageView = ImageView(self.a2_imagePane)
        self.a2_imageView.setObjectName(u"a2_imageView")
        sizePolicy.setHeightForWidth(self.a2_imageView.sizePolicy().hasHeightForWidth())
        self.a2_imageView.setSizePolicy(sizePolicy)
        self.a2_imageView.setMinimumSize(QSize(800, 700))

        self.a2_imagePane_layout.addWidget(self.a2_imageView)

        self.a2_metadataText = QTextEdit(self.a2_imagePane)
        self.a2_metadataText.setObjectName(u"a2_metadataText")
        self.a2_metadataText.setReadOnly(True)

        self.a2_imagePane_layout.addWidget(self.a2_metadataText)

        self.a2_topSplitter.addWidget(self.a2_imagePane)

        self.tab_analysis2_layout.addWidget(self.a2_topSplitter)

        self.tabWidget_3.addTab(self.tab_analysis2, "")
        self.tab_13 = QWidget()
        self.tab_13.setObjectName(u"tab_13")
        self.tabWidget_3.addTab(self.tab_13, "")
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QMenuBar(MainWindow)
        self.menubar.setObjectName(u"menubar")
        self.menubar.setGeometry(QRect(0, 0, 1550, 23))
        self.menuFile = QMenu(self.menubar)
        self.menuFile.setObjectName(u"menuFile")
        self.menuOpen = QMenu(self.menuFile)
        self.menuOpen.setObjectName(u"menuOpen")
        self.menuSave = QMenu(self.menuFile)
        self.menuSave.setObjectName(u"menuSave")
        self.menuHelp = QMenu(self.menubar)
        self.menuHelp.setObjectName(u"menuHelp")
        self.menuEdit = QMenu(self.menubar)
        self.menuEdit.setObjectName(u"menuEdit")
        self.menuSettings_2 = QMenu(self.menuEdit)
        self.menuSettings_2.setObjectName(u"menuSettings_2")
        self.menuTheme_2 = QMenu(self.menuSettings_2)
        self.menuTheme_2.setObjectName(u"menuTheme_2")
        self.menuMain_Window = QMenu(self.menuEdit)
        self.menuMain_Window.setObjectName(u"menuMain_Window")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)

        self.menubar.addAction(self.menuFile.menuAction())
        self.menubar.addAction(self.menuEdit.menuAction())
        self.menubar.addAction(self.menuHelp.menuAction())
        self.menuFile.addAction(self.menuOpen.menuAction())
        self.menuFile.addAction(self.menuSave.menuAction())
        self.menuFile.addAction(self.action_quit)
        self.menuOpen.addAction(self.action_Open_Image_Data)
        self.menuOpen.addAction(self.action_Open_Energy_Definition)
        self.menuOpen.addAction(self.action_Open_Scan_Definition)
        self.menuSave.addAction(self.action_Save_Image_Data)
        self.menuSave.addAction(self.action_Save_Scan_Definition)
        self.menuEdit.addAction(self.menuSettings_2.menuAction())
        self.menuEdit.addAction(self.menuMain_Window.menuAction())
        self.menuSettings_2.addAction(self.menuTheme_2.menuAction())
        self.menuTheme_2.addAction(self.action_light_theme)
        self.menuTheme_2.addAction(self.action_dark_theme)
        self.menuMain_Window.addAction(self.action_load_config_from_server)
        self.menuMain_Window.addAction(self.action_init)

        self.retranslateUi(MainWindow)

        self.tabWidget_3.setCurrentIndex(0)
        self.tabWidget.setCurrentIndex(0)
        self.tabWidget_5.setCurrentIndex(0)
        self.tabWidget_2.setCurrentIndex(0)
        self.a2_workflowTabs.setCurrentIndex(0)


        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"STXM Control", None))
        self.action_Open_Image_Data.setText(QCoreApplication.translate("MainWindow", u"Scan Data", None))
        self.action_Save_Image_Data.setText(QCoreApplication.translate("MainWindow", u"Image Data", None))
        self.action_Save_Scan_Definition.setText(QCoreApplication.translate("MainWindow", u"Scan Definition", None))
        self.action_Open_Energy_Definition.setText(QCoreApplication.translate("MainWindow", u"Energy Definition", None))
        self.action_Open_Scan_Definition.setText(QCoreApplication.translate("MainWindow", u"Scan Definition", None))
        self.actionGood_Luck.setText(QCoreApplication.translate("MainWindow", u"Good Luck!", None))
        self.actionPlease_confirm_you_have_a_good_sample.setText(QCoreApplication.translate("MainWindow", u"Please confirm you have a good sample", None))
        self.actionGood_Luck_2.setText(QCoreApplication.translate("MainWindow", u"Good Luck!", None))
        self.actionLight.setText(QCoreApplication.translate("MainWindow", u"Light", None))
        self.actionDark.setText(QCoreApplication.translate("MainWindow", u"Dark", None))
        self.action_light_theme.setText(QCoreApplication.translate("MainWindow", u"Light", None))
        self.action_dark_theme.setText(QCoreApplication.translate("MainWindow", u"Dark", None))
        self.action_load_config_from_server.setText(QCoreApplication.translate("MainWindow", u"Reload Config From Server", None))
        self.action_init.setText(QCoreApplication.translate("MainWindow", u"Initialize", None))
        self.action_quit.setText(QCoreApplication.translate("MainWindow", u"Quit", None))
#if QT_CONFIG(shortcut)
        self.action_quit.setShortcut(QCoreApplication.translate("MainWindow", u"Meta+Q", None))
#endif // QT_CONFIG(shortcut)
        self.setCursor2ZeroButton.setText(QCoreApplication.translate("MainWindow", u"Set Cursor to 0", None))
        self.focusToCursorButton.setText(QCoreApplication.translate("MainWindow", u"Focus to Cursor", None))
        self.motors2CursorButton.setText(QCoreApplication.translate("MainWindow", u"Motors to Cursor", None))
        self.label_2.setText(QCoreApplication.translate("MainWindow", u"STXM Server: ", None))
        self.serverAddress.setText(QCoreApplication.translate("MainWindow", u"Address", None))
        self.motorMover2Plus.setText(QCoreApplication.translate("MainWindow", u"+", None))
        self.motorMover1Pos.setText(QCoreApplication.translate("MainWindow", u"TextLabel", None))
        self.motorMover2Pos.setText(QCoreApplication.translate("MainWindow", u"TextLabel", None))
        self.motorMover1Plus.setText(QCoreApplication.translate("MainWindow", u"+", None))
        self.motorMover1Button.setText(QCoreApplication.translate("MainWindow", u"M", None))
        self.motorMover2Button.setText(QCoreApplication.translate("MainWindow", u"M", None))
        self.jogToggleButton.setText(QCoreApplication.translate("MainWindow", u"Jog/Move", None))
        self.motorMover1Minus.setText(QCoreApplication.translate("MainWindow", u"-", None))
        self.motorMover2Minus.setText(QCoreApplication.translate("MainWindow", u"-", None))
#if QT_CONFIG(tooltip)
        self.motorPanelButton.setToolTip(QCoreApplication.translate("MainWindow", u"Open the motor inspection and history panel.", None))
#endif // QT_CONFIG(tooltip)
        self.motorPanelButton.setText(QCoreApplication.translate("MainWindow", u"Motor Panel", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_4), QCoreApplication.translate("MainWindow", u"Move Motors", None))
        self.label_27.setText(QCoreApplication.translate("MainWindow", u"Center", None))
        self.label_29.setText(QCoreApplication.translate("MainWindow", u"Points", None))
        self.label_30.setText(QCoreApplication.translate("MainWindow", u"Step Size", None))
        self.label_28.setText(QCoreApplication.translate("MainWindow", u"Range", None))
        self.focusStepSizeLabel.setText("")
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_3), QCoreApplication.translate("MainWindow", u"Focus", None))
        self.lineStepSizeLabel.setText("")
        self.label_37.setText(QCoreApplication.translate("MainWindow", u"Points", None))
        self.label_36.setText(QCoreApplication.translate("MainWindow", u"Angle", None))
        self.label_39.setText(QCoreApplication.translate("MainWindow", u"Length", None))
        self.label_40.setText(QCoreApplication.translate("MainWindow", u"Step Size", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab), QCoreApplication.translate("MainWindow", u"Line", None))
        self.focusStepSizeLabel_5.setText(QCoreApplication.translate("MainWindow", u"Points", None))
        self.focusStepSizeLabel_6.setText(QCoreApplication.translate("MainWindow", u"Step Size", None))
        self.focusStepSizeLabel_3.setText(QCoreApplication.translate("MainWindow", u"Center", None))
        self.focusStepSizeLabel_7.setText(QCoreApplication.translate("MainWindow", u"Motor", None))
        self.loopStepSize.setText("")
        self.focusStepSizeLabel_4.setText(QCoreApplication.translate("MainWindow", u"Range", None))
        self.loopCheckbox.setText(QCoreApplication.translate("MainWindow", u"Use Loop", None))
        self.tabWidget.setTabText(self.tabWidget.indexOf(self.tab_11), QCoreApplication.translate("MainWindow", u"Scan Loop", None))
        self.label.setText(QCoreApplication.translate("MainWindow", u"Current Energy:", None))
        self.energyLabel.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" color:#73d216;\">Energy</span></p></body></html>", None))
        self.label_7.setText(QCoreApplication.translate("MainWindow", u"Scan Velocity", None))
        self.scanVelocity.setText(QCoreApplication.translate("MainWindow", u"0.0 mm/s", None))
        self.label_19.setText(QCoreApplication.translate("MainWindow", u"Estimated Time:", None))
        self.estimatedTime.setText(QCoreApplication.translate("MainWindow", u"0.0 s", None))
        self.label_21.setText(QCoreApplication.translate("MainWindow", u"Elapsed Time", None))
        self.elapsedTime.setText(QCoreApplication.translate("MainWindow", u"0.0 s", None))
        self.warningLabel.setText("")
        self.label_6.setText(QCoreApplication.translate("MainWindow", u"Scan Type", None))
        self.imageCountText.setText(QCoreApplication.translate("MainWindow", u"Region 1 of 1 | Energy 1 of 1", None))
        self.scanFileName.setText("")
        self.label_25.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Scan:</span></p></body></html>", None))
        self.label_5.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Current Image:</span></p></body></html>", None))
        self.xCursorPos.setText("")
        self.label_23.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Y:</span></p></body></html>", None))
        self.yCursorPos.setText("")
        self.label_20.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">X:</span></p></body></html>", None))
        self.label_24.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Intensity:</span></p></body></html>", None))
        self.cursorIntensity.setText("")
        self.daqCurrentValue.setText("")
        self.label_3.setText(QCoreApplication.translate("MainWindow", u"Plot", None))
        self.plotType.setItemText(0, QCoreApplication.translate("MainWindow", u"Monitor", None))
        self.plotType.setItemText(1, QCoreApplication.translate("MainWindow", u"Motor Scan", None))
        self.plotType.setItemText(2, QCoreApplication.translate("MainWindow", u"Image X", None))
        self.plotType.setItemText(3, QCoreApplication.translate("MainWindow", u"Image Y", None))
        self.plotType.setItemText(4, QCoreApplication.translate("MainWindow", u"Image XY", None))

        self.label_22.setText(QCoreApplication.translate("MainWindow", u"Channel", None))
        self.channelSelect.setItemText(0, QCoreApplication.translate("MainWindow", u"Diode", None))
        self.channelSelect.setItemText(1, QCoreApplication.translate("MainWindow", u"CCD", None))
        self.channelSelect.setItemText(2, QCoreApplication.translate("MainWindow", u"RPI", None))

        self.plotClearButton.setText(QCoreApplication.translate("MainWindow", u"Clear", None))
        self.scaleBarLength.setText("")
        self.label_44.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:600;\">Pixel Size:</span></p></body></html>", None))
        self.pixelSizeLabel.setText("")
        self.label_38.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:600;\">Dwell Time:</span></p></body></html>", None))
        self.dwellTimeLabel.setText("")
        self.label_9.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:600;\">Energy:</span></p></body></html>", None))
        self.imageEnergyLabel.setText("")
        self.experimentersLineEdit.setText("")
        self.label_32.setText(QCoreApplication.translate("MainWindow", u"Experimenters", None))
        self.sampleLineEdit.setText("")
        self.label_33.setText(QCoreApplication.translate("MainWindow", u"Sample", None))
        self.label_31.setText(QCoreApplication.translate("MainWindow", u"Proposal", None))
        self.label_26.setText(QCoreApplication.translate("MainWindow", u"Comment", None))
        self.tabWidget_5.setTabText(self.tabWidget_5.indexOf(self.Experiment), QCoreApplication.translate("MainWindow", u"Experiment", None))
        self.ndsLabel.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.label_34.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Zone Plate A0</span></p></body></html>", None))
        self.label_13.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Dispersive Slit</span></p></body></html>", None))
        self.A0Label.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.dsLabel.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.label_14.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Non-Dispersive Slit</span></p></body></html>", None))
        self.energyLabel_2.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.label_4.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Energy</span></p></body></html>", None))
        self.tabWidget_5.setTabText(self.tabWidget_5.indexOf(self.beamlineTab), QCoreApplication.translate("MainWindow", u"Beamline", None))
        self.label_12.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">M101 Pitch</span></p></body></html>", None))
        self.label_17.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Harmonic</span></p></body></html>", None))
        self.label_18.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">EPU Offset</span></p></body></html>", None))
        self.label_16.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Feedback Offset</span></p></body></html>", None))
        self.label_15.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Polarization</span></p></body></html>", None))
        self.epuLabel.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.fbkLabel.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.m101Label.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.polLabel.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.tabWidget_5.setTabText(self.tabWidget_5.indexOf(self.epuTab), QCoreApplication.translate("MainWindow", u"EPU", None))
        self.label_35.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\">Zone Plate A1</span></p></body></html>", None))
        self.A1Label.setText(QCoreApplication.translate("MainWindow", u"None", None))
        self.label_41.setText(QCoreApplication.translate("MainWindow", u"Server IP", None))
        self.serverAddressLabel.setText(QCoreApplication.translate("MainWindow", u"127.0.0.1", None))
        self.serverConnectButton.setText(QCoreApplication.translate("MainWindow", u"Connect", None))
        self.tabWidget_5.setTabText(self.tabWidget_5.indexOf(self.tab_2), QCoreApplication.translate("MainWindow", u"Staff", None))
        self.autofocusCheckbox.setText(QCoreApplication.translate("MainWindow", u"autofocus", None))
        self.roiCheckbox.setText(QCoreApplication.translate("MainWindow", u"Show ROI", None))
        self.defocusCheckbox.setText(QCoreApplication.translate("MainWindow", u"Defocus", None))
        self.tiledCheckbox.setText(QCoreApplication.translate("MainWindow", u"Tiled Scan", None))
        self.beginScanButton.setText(QCoreApplication.translate("MainWindow", u"Begin Scan", None))
        self.cancelButton.setText(QCoreApplication.translate("MainWindow", u"Cancel", None))
        self.label_8.setText(QCoreApplication.translate("MainWindow", u"X", None))
        self.label_11.setText(QCoreApplication.translate("MainWindow", u"Y", None))
        self.shutterComboBox.setItemText(0, QCoreApplication.translate("MainWindow", u"Shutter Auto", None))
        self.shutterComboBox.setItemText(1, QCoreApplication.translate("MainWindow", u"Shutter Open", None))
        self.shutterComboBox.setItemText(2, QCoreApplication.translate("MainWindow", u"Shutter Closed", None))

        self.tabWidget_2.setTabText(self.tabWidget_2.indexOf(self.tab_5), QCoreApplication.translate("MainWindow", u"Scan Regions", None))
        self.label_10.setText(QCoreApplication.translate("MainWindow", u"<html><head/><body><p><span style=\" font-weight:700;\"> Energy List </span></p></body></html>", None))
        self.toggleSingleEnergy.setText(QCoreApplication.translate("MainWindow", u"Single Energy", None))
        self.energyListCheckbox.setText(QCoreApplication.translate("MainWindow", u"Energy List", None))
        self.doubleExposureCheckbox.setText(QCoreApplication.translate("MainWindow", u"Double Exp.", None))
        self.multiFrameCheckbox.setText(QCoreApplication.translate("MainWindow", u"Multi-Frame", None))
        self.firstEnergyButton.setText(QCoreApplication.translate("MainWindow", u"To First Energy", None))
        self.tabWidget_2.setTabText(self.tabWidget_2.indexOf(self.tab_6), QCoreApplication.translate("MainWindow", u"Energy Regions", None))
        self.showBeamPosition.setText(QCoreApplication.translate("MainWindow", u"Show beam position", None))
        self.autorangeCheckbox.setText(QCoreApplication.translate("MainWindow", u"Autorange Image", None))
        self.showRangeFinder.setText(QCoreApplication.translate("MainWindow", u"Show scan range", None))
        self.compositeImageCheckbox.setText(QCoreApplication.translate("MainWindow", u"Composite Image", None))
        self.clearImageButton.setText(QCoreApplication.translate("MainWindow", u"Clear All", None))
        self.removeLastImageButton.setText(QCoreApplication.translate("MainWindow", u"Remove Last", None))
#if QT_CONFIG(tooltip)
        self.snapRoiToFovButton.setToolTip(QCoreApplication.translate("MainWindow", u"Resize the scan region ROI to fill the current image field of view and update the scan region parameters accordingly.", None))
#endif // QT_CONFIG(tooltip)
        self.snapRoiToFovButton.setText(QCoreApplication.translate("MainWindow", u"Snap ROI to FOV", None))
#if QT_CONFIG(tooltip)
        self.snapFovToRoiButton.setToolTip(QCoreApplication.translate("MainWindow", u"Pan and zoom the image display to match the current scan region ROI.", None))
#endif // QT_CONFIG(tooltip)
        self.snapFovToRoiButton.setText(QCoreApplication.translate("MainWindow", u"Snap FOV to ROI", None))
        self.autoscaleCheckbox.setText(QCoreApplication.translate("MainWindow", u"Autoscale Image", None))
        self.tabWidget_2.setTabText(self.tabWidget_2.indexOf(self.tab_7), QCoreApplication.translate("MainWindow", u"Display", None))
        self.tabWidget_2.setTabText(self.tabWidget_2.indexOf(self.tab_8), QCoreApplication.translate("MainWindow", u"Console", None))
        self.tabWidget_3.setTabText(self.tabWidget_3.indexOf(self.tab_9), QCoreApplication.translate("MainWindow", u"Acquisition", None))
        self.a2_openStackButton.setText(QCoreApplication.translate("MainWindow", u"Open Stack", None))
        self.a2_saveDataButton.setText(QCoreApplication.translate("MainWindow", u"Save Data", None))
        self.a2_addToLogButton.setText(QCoreApplication.translate("MainWindow", u"Add to Log", None))
        self.a2_roiTypeLabel.setText(QCoreApplication.translate("MainWindow", u"ROI Type:", None))
        self.a2_roiTypeCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"I0", None))
        self.a2_roiTypeCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"Spectrum", None))

        self.a2_drawRoiCheckbox.setText(QCoreApplication.translate("MainWindow", u"Draw ROI", None))
        self.a2_deleteRoiButton.setText(QCoreApplication.translate("MainWindow", u"Delete ROI", None))
        self.a2_deleteFrameButton.setText(QCoreApplication.translate("MainWindow", u"Delete Frame", None))
        self.a2_odCheckbox.setText(QCoreApplication.translate("MainWindow", u"Optical Density", None))
        self.a2_autoProcessButton.setText(QCoreApplication.translate("MainWindow", u"Auto Process", None))
        self.a2_mapButton.setText(QCoreApplication.translate("MainWindow", u"Map", None))
        self.a2_resetButton.setText(QCoreApplication.translate("MainWindow", u"Reset", None))
        self.a2_preEdgeCheckbox.setText(QCoreApplication.translate("MainWindow", u"Select Pre-Edge", None))
        self.a2_subtractPreEdgeButton.setText(QCoreApplication.translate("MainWindow", u"Subtract Pre-Edge", None))
        self.a2_postEdgeCheckbox.setText(QCoreApplication.translate("MainWindow", u"Select Post-Edge", None))
        self.a2_normalizePostEdgeButton.setText(QCoreApplication.translate("MainWindow", u"Normalize Post-Edge", None))
        self.a2_trackMouseCheckbox.setText(QCoreApplication.translate("MainWindow", u"Track Mouse", None))
        self.a2_liveDisplayCheckbox.setText(QCoreApplication.translate("MainWindow", u"Live Display", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_main), QCoreApplication.translate("MainWindow", u"Main", None))
        self.a2_darkLevelLabel.setText(QCoreApplication.translate("MainWindow", u"Dark Level:", None))
        self.a2_darkLevelEdit.setText(QCoreApplication.translate("MainWindow", u"0", None))
        self.a2_subtractDarkButton.setText(QCoreApplication.translate("MainWindow", u"Subtract Dark Level", None))
        self.a2_filterUndoButton.setText(QCoreApplication.translate("MainWindow", u"Undo", None))
        self.a2_medianKernelLabel.setText(QCoreApplication.translate("MainWindow", u"Kernel Size:", None))
        self.a2_medianKernelEdit.setText(QCoreApplication.translate("MainWindow", u"5", None))
        self.a2_medianFilterButton.setText(QCoreApplication.translate("MainWindow", u"Median Filter", None))
        self.a2_despikeKernelLabel.setText(QCoreApplication.translate("MainWindow", u"Kernel Size:", None))
        self.a2_despikeKernelEdit.setText(QCoreApplication.translate("MainWindow", u"3", None))
        self.a2_despikeNSigmaLabel.setText(QCoreApplication.translate("MainWindow", u"N Sigma:", None))
        self.a2_despikeNSigmaEdit.setText(QCoreApplication.translate("MainWindow", u"5", None))
        self.a2_despikeButton.setText(QCoreApplication.translate("MainWindow", u"Despike", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_filtering), QCoreApplication.translate("MainWindow", u"Filtering", None))
        self.a2_regModeLabel.setText(QCoreApplication.translate("MainWindow", u"Mode:", None))
        self.a2_regModeCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"Translation", None))
        self.a2_regModeCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"Circular Image", None))
        self.a2_regModeCombo.setItemText(2, QCoreApplication.translate("MainWindow", u"Affine", None))
        self.a2_regModeCombo.setItemText(3, QCoreApplication.translate("MainWindow", u"Rigid", None))
        self.a2_regModeCombo.setItemText(4, QCoreApplication.translate("MainWindow", u"Homographic", None))

        self.a2_regSobelCheckbox.setText(QCoreApplication.translate("MainWindow", u"Sobel Filter", None))
        self.a2_regAutocropCheckbox.setText(QCoreApplication.translate("MainWindow", u"Autocrop", None))
        self.a2_regStartButton.setText(QCoreApplication.translate("MainWindow", u"Start", None))
        self.a2_regUndoButton.setText(QCoreApplication.translate("MainWindow", u"Undo", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_registration), QCoreApplication.translate("MainWindow", u"Registration", None))
        self.a2_nComponentsLabel.setText(QCoreApplication.translate("MainWindow", u"N Components:", None))
        self.a2_nComponentsEdit.setText(QCoreApplication.translate("MainWindow", u"4", None))
        self.a2_nClustersLabel.setText(QCoreApplication.translate("MainWindow", u"N Clusters:", None))
        self.a2_nClustersEdit.setText(QCoreApplication.translate("MainWindow", u"4", None))
        self.a2_reduceMassCheckbox.setText(QCoreApplication.translate("MainWindow", u"Reduce Mass Effects", None))
        self.a2_removePreEdgeCheckbox.setText(QCoreApplication.translate("MainWindow", u"Remove Pre-Edge", None))
        self.a2_calcPCAButton.setText(QCoreApplication.translate("MainWindow", u"Calculate PCA", None))
        self.a2_clusterImageLabel.setText(QCoreApplication.translate("MainWindow", u"Display:", None))
        self.a2_clusterImageCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"Transmission", None))
        self.a2_clusterImageCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"Optical Density", None))
        self.a2_clusterImageCombo.setItemText(2, QCoreApplication.translate("MainWindow", u"Principal Components", None))
        self.a2_clusterImageCombo.setItemText(3, QCoreApplication.translate("MainWindow", u"Clusters", None))
        self.a2_clusterImageCombo.setItemText(4, QCoreApplication.translate("MainWindow", u"RGB Map", None))

        self.a2_clusterPlotLabel.setText(QCoreApplication.translate("MainWindow", u"Plot:", None))
        self.a2_clusterPlotCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"ROI Spectra", None))
        self.a2_clusterPlotCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"Cluster Spectra", None))
        self.a2_clusterPlotCombo.setItemText(2, QCoreApplication.translate("MainWindow", u"PCA Eigenvalues", None))

        self.a2_targetSpectraLabel.setText(QCoreApplication.translate("MainWindow", u"Target Spectra:", None))
        self.a2_targetSpectraEdit.setText(QCoreApplication.translate("MainWindow", u"1,2,3", None))
        self.a2_calcRGBMapButton.setText(QCoreApplication.translate("MainWindow", u"RGB Map", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_clustering), QCoreApplication.translate("MainWindow", u"PCA", None))
        self.a2_nmfNComponentsLabel.setText(QCoreApplication.translate("MainWindow", u"N Components:", None))
        self.a2_nmfNComponentsEdit.setText(QCoreApplication.translate("MainWindow", u"4", None))
        self.a2_nmfNClustersLabel.setText(QCoreApplication.translate("MainWindow", u"N Clusters:", None))
        self.a2_nmfNClustersEdit.setText(QCoreApplication.translate("MainWindow", u"4", None))
        self.a2_nmfMaxIterLabel.setText(QCoreApplication.translate("MainWindow", u"Max Iterations:", None))
        self.a2_nmfMaxIterEdit.setText(QCoreApplication.translate("MainWindow", u"500", None))
        self.a2_nmfInitLabel.setText(QCoreApplication.translate("MainWindow", u"Init:", None))
        self.a2_nmfInitCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"NNDSVDA", None))
        self.a2_nmfInitCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"Random", None))

        self.a2_calcNMFButton.setText(QCoreApplication.translate("MainWindow", u"Calculate NMF", None))
        self.a2_nmfDisplayLabel.setText(QCoreApplication.translate("MainWindow", u"Display:", None))
        self.a2_nmfDisplayCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"NMF Components", None))
        self.a2_nmfDisplayCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"Cluster Map", None))
        self.a2_nmfDisplayCombo.setItemText(2, QCoreApplication.translate("MainWindow", u"RGB Map", None))

        self.a2_nmfPlotLabel.setText(QCoreApplication.translate("MainWindow", u"Plot:", None))
        self.a2_nmfPlotCombo.setItemText(0, QCoreApplication.translate("MainWindow", u"Component Spectra", None))
        self.a2_nmfPlotCombo.setItemText(1, QCoreApplication.translate("MainWindow", u"Cluster Spectra", None))

        self.a2_nmfTargetSpectraLabel.setText(QCoreApplication.translate("MainWindow", u"Target Spectra:", None))
        self.a2_nmfTargetSpectraEdit.setText(QCoreApplication.translate("MainWindow", u"1,2,3", None))
        self.a2_nmfCalcRGBMapButton.setText(QCoreApplication.translate("MainWindow", u"RGB Map", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_nnmf), QCoreApplication.translate("MainWindow", u"NNMF", None))
        self.a2_workflowTabs.setTabText(self.a2_workflowTabs.indexOf(self.a2_tab_metadata), QCoreApplication.translate("MainWindow", u"Line Spectrum", None))
        self.a2_metadataText.setPlaceholderText(QCoreApplication.translate("MainWindow", u"File and process metadata will appear here\u2026", None))
        self.tabWidget_3.setTabText(self.tabWidget_3.indexOf(self.tab_analysis2), QCoreApplication.translate("MainWindow", u"Analysis", None))
        self.tabWidget_3.setTabText(self.tabWidget_3.indexOf(self.tab_13), QCoreApplication.translate("MainWindow", u"Browser", None))
        self.menuFile.setTitle(QCoreApplication.translate("MainWindow", u"File", None))
        self.menuOpen.setTitle(QCoreApplication.translate("MainWindow", u"Open", None))
        self.menuSave.setTitle(QCoreApplication.translate("MainWindow", u"Save", None))
        self.menuHelp.setTitle(QCoreApplication.translate("MainWindow", u"Help", None))
        self.menuEdit.setTitle(QCoreApplication.translate("MainWindow", u"Edit", None))
        self.menuSettings_2.setTitle(QCoreApplication.translate("MainWindow", u"Settings", None))
        self.menuTheme_2.setTitle(QCoreApplication.translate("MainWindow", u"Theme", None))
        self.menuMain_Window.setTitle(QCoreApplication.translate("MainWindow", u"Main Window", None))
    # retranslateUi


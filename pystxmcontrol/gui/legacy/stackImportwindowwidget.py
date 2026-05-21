from PySide6 import QtWidgets, QtCore, QtGui
from pystxmcontrol.gui.stackimport_mainwindow import Ui_Import
import pyqtgraph as pg


class stackImportWindow(QtWidgets.QDialog, Ui_Import):

    def __init__(self,parent=None):
        QtWidgets.QDialog.__init__(self,parent)
        self.setupUi(self)
        self.stack = None

    def updateGUI(self):
        pass
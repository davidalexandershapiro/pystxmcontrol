from PySide6 import QtWidgets, QtCore, QtGui
from pystxmcontrol.gui.register_mainwindow import Ui_registerWindow
import pyqtgraph as pg
from numpy import transpose

class registerWindowWidget(QtWidgets.QDialog, Ui_registerWindow):
    def __init__(self,parent=None):
        QtWidgets.QDialog.__init__(self,parent)
        self.setupUi(self)
        self.stack = None
        self.verticalSlider.valueChanged.connect(self.updateMainImage)
        self.undoButton.clicked.connect(self.undo)
        self.sequentialBox.setCheckState(QtCore.Qt.Checked)
        self.sequentialBox.stateChanged.connect(self.toggleSequential)
        self.referenceBox.stateChanged.connect(self.toggleReference)
        self.manualBox.stateChanged.connect(self.toggleManual)
        self.despikeBox.setCheckState(QtCore.Qt.Checked)
        self.filterBox.setCheckState(QtCore.Qt.Checked)
        self.applyButton.clicked.connect(self.apply)
        self.progressBar.setValue(0)
        self.roiCheckbox.stateChanged.connect(self.setROI)
        self.autoCropCheckbox.stateChanged.connect(self.setAutoCrop)
        roiPen = pg.mkPen([255,0,0], width = 2)
        self.roi = pg.RectROI((20,20),(40,40), pen = roiPen)
        self.resize(800,500)

    def setROI(self):
        if self.roiCheckbox.isChecked():
            self.autoCropCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.mainImage.addItem(self.roi)
        else:
            self.mainImage.removeItem(self.roi)

    def setAutoCrop(self):
        if self.autoCropCheckbox.isChecked():
            self.roiCheckbox.setCheckState(QtCore.Qt.Unchecked)

    def cropToROI(self):
        self.stack.processedFrames = transpose(self.roi.getArrayRegion(transpose(self.stack.processedFrames, axes = (0,2,1)), \
            self.mainImage.getImageItem(), (1,2)), axes = (0,2,1))
        self.roiCheckbox.setCheckState(QtCore.Qt.Unchecked)
        self.updateMainImage()

    def apply(self):
        if self.stack is not None:
            self.progressBar.setValue(0)
            if str(self.typeBox.currentText()).lower() == 'translation': mode = 'translation'
            if str(self.typeBox.currentText()).lower() == 'rigid': mode = 'rigid'
            if str(self.typeBox.currentText()).lower() == 'affine': mode = 'affine'
            if str(self.typeBox.currentText()).lower() == 'homographic': mode = 'homographic'
            print("Registation mode is %s" %mode)

            if self.despikeBox.isChecked():
                self.stack.despike()
            if self.roiCheckbox.isChecked():
                self.cropToROI()
            else:
                self.stack.alignFrames(sobelFilter = self.filterBox.isChecked(), \
                    mode = mode, autocrop = self.autoCropCheckbox.isChecked())
            self.progressBar.setValue(100)
            self.updateMainImage()

    def updateProgressBar(self, value):
        self.progressBar.setValue(float(value) / float(len(self.stack.processedFrames)))

    def toggleManual(self):
        if self.manualBox.isChecked():
            self.manualBox.setCheckState(QtCore.Qt.Unchecked)

    def toggleSequential(self):
        if self.sequentialBox.isChecked():
            self.referenceBox.setCheckState(QtCore.Qt.Unchecked)

    def toggleReference(self):
        if self.referenceBox.isChecked():
            self.sequentialBox.setCheckState(QtCore.Qt.Unchecked)

    def undo(self):
        self.stack.undo()
        self.updateMainImage()

    def updateGUI(self):
        if self.stack is not None:
            self.verticalSlider.setMaximum(len(self.stack.rawFrames) - 1)
            self.updateMainImage()

    def updateMainImage(self):
        if self.stack is not None:
            self.mainImage.setImage(self.stack.processedFrames[self.verticalSlider.value()].T)

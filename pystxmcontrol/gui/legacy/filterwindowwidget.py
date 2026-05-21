from PySide6 import QtWidgets, QtCore, QtGui
from pystxmcontrol.gui.filter_mainwindow import Ui_filterWindow

class filterWindowWidget(QtWidgets.QDialog, Ui_filterWindow):
    def __init__(self,parent=None):
        QtWidgets.QDialog.__init__(self,parent)
        self.setupUi(self)
        self.axis = 0
        self.stack = None
        self.verticalSlider.valueChanged.connect(self.updateMainImage)
        self.applyButton.clicked.connect(self.apply)
        self.selectYBox.stateChanged.connect(self.toggleSelectY)
        self.selectXBox.stateChanged.connect(self.toggleSelectX)
        self.selectXYBox.stateChanged.connect(self.toggleSelectXY)
        self.despikeBox.stateChanged.connect(self.toggleSelectDespike)
        self.undoButton.clicked.connect(self.undo)
        self.kernelEdit.setText(str(3.0))
        self.darkValueEdit.setText(str(0.0))
        self.selectYBox.setCheckState(QtCore.Qt.Checked)
        self.resize(800,500)

    def undo(self):
        self.stack.undo()
        self.updateMainImage()

    def apply(self):
        try: kernelSize = int(float(self.kernelEdit.text()))
        except: kernelSize = 3
        if self.stack is not None:
            self.stack.darkField = float(str(self.darkValueEdit.text()))
            self.stack.subtractDarkField()
            if self.despikeBox.isChecked():
                self.stack.despike()
            if self.selectXBox.isChecked() or self.selectYBox.isChecked() or \
                self.selectXYBox.isChecked():
                if self.filterTypeBox.currentText() == 'Wiener':
                    self.stack.wienerFilter(size = kernelSize, axis = self.axis)
                elif self.filterTypeBox.currentText() == 'Median':
                    self.stack.medianFilter(size = kernelSize, axis = self.axis)
                elif self.filterTypeBox.currentText() == 'Non-Local Means':
                    self.stack.nlMeansFilter(size = kernelSize, axis = self.axis)
            self.updateMainImage()

    def toggleSelectY(self):
        if self.selectYBox.isChecked():
            self.selectXBox.setCheckState(QtCore.Qt.Unchecked)
            self.selectXYBox.setCheckState(QtCore.Qt.Unchecked)
            self.jumpBox.setCheckState(QtCore.Qt.Unchecked)
            self.despikeBox.setCheckState(QtCore.Qt.Unchecked)
        self.axis = 0

    def toggleSelectX(self):
        if self.selectXBox.isChecked():
            self.selectYBox.setCheckState(QtCore.Qt.Unchecked)
            self.selectXYBox.setCheckState(QtCore.Qt.Unchecked)
            self.jumpBox.setCheckState(QtCore.Qt.Unchecked)
            self.despikeBox.setCheckState(QtCore.Qt.Unchecked)
        self.axis = 1

    def toggleSelectXY(self):
        if self.selectXYBox.isChecked():
            self.selectYBox.setCheckState(QtCore.Qt.Unchecked)
            self.selectXBox.setCheckState(QtCore.Qt.Unchecked)
            self.jumpBox.setCheckState(QtCore.Qt.Unchecked)
            self.despikeBox.setCheckState(QtCore.Qt.Unchecked)
        self.axis = 2

    def toggleSelectJump(self):
        if self.jumpBox.isChecked():
            self.selectXBox.setCheckState(QtCore.Qt.Unchecked)
            self.selectXYBox.setCheckState(QtCore.Qt.Unchecked)
            self.selectYBox.setCheckState(QtCore.Qt.Unchecked)
            self.despikeBox.setCheckState(QtCore.Qt.Unchecked)

    def toggleSelectDespike(self):
        if self.despikeBox.isChecked():
            self.selectXBox.setCheckState(QtCore.Qt.Unchecked)
            self.selectXYBox.setCheckState(QtCore.Qt.Unchecked)
            self.selectYBox.setCheckState(QtCore.Qt.Unchecked)
            self.jumpBox.setCheckState(QtCore.Qt.Unchecked)

    def updateGUI(self):
        self.verticalSlider.setMaximum(len(self.stack.rawFrames) - 1)
        self.updateMainImage()

    def updateMainImage(self):
        if self.stack is not None:
            self.mainImage.setImage(self.stack.processedFrames[self.verticalSlider.value()].T)

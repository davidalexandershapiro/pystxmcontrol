from pystxmcontrol.gui.regionDef_UI import Ui_regionDef
from PySide6 import QtWidgets, QtCore, QtGui
import numpy as np


class scanRegionDef(QtCore.QObject):

    regionChanged = QtCore.Signal(np.intc)
    updateTimeEstimate = QtCore.Signal(np.intc)

    def __init__(self):
        super(scanRegionDef, self).__init__()
        self.region = QtWidgets.QWidget()
        self.ui = Ui_regionDef()
        self.ui.setupUi(self.region)
        self.setDefaultScanParams()
        self.ui.xNPoints.returnPressed.connect(self.xNPointsChanged)
        self.ui.xStep.returnPressed.connect(self.xStepChanged)
        self.ui.yNPoints.returnPressed.connect(self.yNPointsChanged)
        self.ui.yStep.returnPressed.connect(self.yStepChanged)
        self.ui.xCenter.returnPressed.connect(self.xCenterChanged)
        self.ui.yCenter.returnPressed.connect(self.yCenterChanged)
        self.ui.xRange.returnPressed.connect(self.xRangeChanged)
        self.ui.yRange.returnPressed.connect(self.yRangeChanged)
        self.blockPoints = False
        self.blockStep = False
        self.noEmit = False

    def setDefaultScanParams(self):
        self.ui.yRange.setText(str(70))
        self.ui.yNPoints.setText(str(50))
        self.ui.xCenter.setText(str(0))
        self.ui.yCenter.setText(str(0))
        self.ui.xRange.setText(str(70))
        self.ui.xNPoints.setText(str(50))
        self.ui.xStep.setText(str(1.0))
        self.ui.yStep.setText(str(1.0))

    def xCenterChanged(self):
        try:
            float(self.ui.xCenter.text())
        except:
            self.ui.xCenter.undo()
        else:
            if not(self.noEmit):
                self.regionChanged.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))

    def yCenterChanged(self):
        try:
            float(self.ui.yCenter.text())
        except:
            self.ui.yCenter.undo()
        else:
            if not (self.noEmit):
                self.regionChanged.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))

    def xRangeChanged(self):
        try:
            if float(self.ui.xRange.text()) < 0.1:
                self.ui.xRange.undo()
                return
        except:
            self.ui.xRange.undo()
        else:
            xStep = float(self.ui.xRange.text()) / (int(self.ui.xNPoints.text())) #xNPoints
            self.ui.xStep.setText(str(np.round(xStep,3)))
            self.updateTimeEstimate.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
            if not (self.noEmit):
                self.regionChanged.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))

    def yRangeChanged(self):
        try:
            if float(self.ui.yRange.text()) < 0.1:
                self.ui.yRange.undo()
                return
        except:
            self.ui.yRange.undo()
        else:
            yStep = float(self.ui.yRange.text()) / (int(self.ui.yNPoints.text())) #yNPoints
            self.ui.yStep.setText(str(np.round(yStep,3)))
            self.updateTimeEstimate.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
            if not (self.noEmit):
                self.regionChanged.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))

    def xNPointsChanged(self):
        try:
            if float(self.ui.xNPoints.text()) < 2.0:
                self.ui.xNPoints.undo()
                return
        except:
            self.ui.xNPoints.undo()
        else:
            if not self.blockPoints:
                self.blockStep = True
                if int(self.ui.xNPoints.text())>4000:
                    self.ui.xNPoints.setText('4000')
                xStep = float(self.ui.xRange.text()) / (float(self.ui.xNPoints.text()))
                self.ui.xStep.setText(str(np.round(xStep,3)))
                self.regionChanged.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
                self.updateTimeEstimate.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
                self.blockStep = False

    def xStepChanged(self):
        try:
            if float(self.ui.xStep.text()) < 0.01:
                self.ui.xStep.undo()
                return
        except:
            self.ui.xStep.undo()
            return
        else:
            if not self.blockStep:
                self.blockPoints = True
                if float(self.ui.xStep.text()) == 0.:
                    xNPoints = 1
                else:
                    xNPoints = float(self.ui.xRange.text()) / float(self.ui.xStep.text())
                self.ui.xNPoints.setText(str(int(np.round(xNPoints))))
                #self.ui.yStep.setText(self.ui.xStep.text())
                self.regionChanged.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
                self.updateTimeEstimate.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
                self.blockPoints = False

    def yNPointsChanged(self):
        try:
            if float(self.ui.yNPoints.text()) < 2.0:
                self.ui.yNPoints.undo()
                return
        except:
            self.ui.yNPoints.undo()
            return
        else:
            if not self.blockPoints:
                self.blockStep = True
                if int(self.ui.yNPoints.text())>4000:
                    self.ui.yNPoints.setText('4000')
                yStep = float(self.ui.yRange.text()) / (float(self.ui.yNPoints.text()))
                self.ui.yStep.setText(str(np.round(yStep,3)))
                self.regionChanged.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
                self.updateTimeEstimate.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
                self.blockStep = False

    def yStepChanged(self):
        try:
            if float(self.ui.yStep.text()) < 0.01:
                self.ui.yStep.undo()
                return
        except:
            self.ui.yStep.undo()
            return
        else:
            if not self.blockStep:
                self.blockPoints = True
                if float(self.ui.yStep.text()) == 0.:
                    yNPoints = 1
                else:
                    yNPoints = float(self.ui.yRange.text()) / float(self.ui.yStep.text())
                self.ui.yNPoints.setText(str(int(np.round(yNPoints))))
                self.regionChanged.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
                self.updateTimeEstimate.emit(np.intc(self.ui.regNum.text().split("Region ")[1]))
                self.blockPoints = False

    def sendChangedSignal(self):
        pass

    def setEnabled(self,value):
        self.ui.yRange.setEnabled(value)
        self.ui.yNPoints.setEnabled(value)
        self.ui.xCenter.setEnabled(value)
        self.ui.yCenter.setEnabled(value)
        self.ui.xRange.setEnabled(value)
        self.ui.xNPoints.setEnabled(value)
        self.ui.xStep.setEnabled(value)
        self.ui.yStep.setEnabled(value)

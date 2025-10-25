from PySide6 import QtCore, QtWidgets
from pystxmcontrol.gui.energyDef_UI import Ui_energyDef
from numpy import round

class energyDefWidget(QtWidgets.QWidget, Ui_energyDef):

    regionChanged = QtCore.Signal()

    def __init__(self, parent= None):
        QtWidgets.QWidget.__init__(self, parent)
        self.widget = QtWidgets.QWidget()
        self.energyDef = Ui_energyDef()
        self.energyDef.setupUi(self.widget)
        self.setDefaultScanParams()
        self.energyDef.energyStart.returnPressed.connect(self.updateEnergyStart)
        self.energyDef.energyStop.returnPressed.connect(self.updateEnergyStop)
        self.energyDef.dwellTime.returnPressed.connect(self.updateDwell)
        self.energyDef.nEnergies.returnPressed.connect(self.nEnergiesChanged)
        self.energyDef.energyStep.returnPressed.connect(self.energyStepChanged)
        # self.energyDef.energyStart.textChanged.connect(self.updateEnergyStart)
        # self.energyDef.energyStop.textChanged.connect(self.updateEnergyStop)
        # self.energyDef.dwellTime.textChanged.connect(self.updateDwell)
        # self.energyDef.nEnergies.textChanged.connect(self.nEnergiesChanged)
        # self.energyDef.energyStep.textChanged.connect(self.energyStepChanged)
        self.energyDef.singleEnergy = True
        self.blockPoints = False
        self.blockStep = False
        self.setSingleEnergy()

    def energyStepChanged(self):
        try:
            float(self.energyDef.energyStep.text())
        except:
            self.energyDef.energyStep.undo()
        if float(self.energyDef.energyStep.text()) < 0:
            self.energyDef.energyStep.undo()
        if float(self.energyDef.energyStep.text()) > (float(self.energyDef.energyStop.text()) - \
            float(self.energyDef.energyStart.text())):
            self.energyDef.energyStep.undo()
        if not self.blockStep:
            self.blockPoints = True
            nPoints = (float(self.energyDef.energyStop.text()) - \
                float(self.energyDef.energyStart.text())) / float(self.energyDef.energyStep.text()) + 1
            self.energyDef.nEnergies.setText(str(int(nPoints)))
            self.blockPoints = False
        self.regionChanged.emit()

    def nEnergiesChanged(self):
        try:
            float(self.energyDef.nEnergies.text())
        except:
            self.energyDef.nEnergies.undo()
        if self.energyDef.singleEnergy and (float(self.energyDef.nEnergies.text()) < 1):
            self.energyDef.nEnergies.undo()
        elif not(self.energyDef.singleEnergy) and (float(self.energyDef.nEnergies.text()) < 2):
            self.energyDef.nEnergies.undo()
        if not self.blockPoints:
            self.blockStep = True
            if int(self.energyDef.nEnergies.text()) > 1:
                step = (float(self.energyDef.energyStop.text()) - \
                    float(self.energyDef.energyStart.text())) / (float(self.energyDef.nEnergies.text()) - 1)
            else:
                step = (float(self.energyDef.energyStop.text()) - \
                    float(self.energyDef.energyStart.text())) / float(self.energyDef.nEnergies.text())
            self.energyDef.energyStep.setText(str(round(step,2)))
            self.blockStep = False
        self.regionChanged.emit()

    def setDefaultScanParams(self):
        self.energyDef.energyStart.setText(str(500))
        self.energyDef.energyStop.setText(str(501))
        self.energyDef.energyStep.setText(str(1))
        self.energyDef.nEnergies.setText(str(2))
        self.energyDef.dwellTime.setText(str(1))

    def sendChangedSignal(self):
        pass

    def updateEnergyStart(self):
        try:
            float(self.energyDef.energyStart.text())
        except:
            self.energyDef.energyStart.undo()
        if not(self.energyDef.singleEnergy):
            try:
                float(self.energyDef.energyStart.text())
            except:
                self.energyDef.energyStart.undo()
            if float(self.energyDef.energyStart.text()) >= float(self.energyDef.energyStop.text()):
                #self.energyDef.energyStart.undo()
                self.energyDef.energyStop.setText(self.energyDef.energyStart.text())
            self.blockStep = True
            try:
                nPoints = (float(self.energyDef.energyStop.text()) - \
                    float(self.energyDef.energyStart.text())) / float(self.energyDef.energyStep.text()) + 1
            except:
                nPoints = 1
            self.energyDef.nEnergies.setText(str(int(nPoints)))
            self.blockStep = False
            self.regionChanged.emit()

    def updateEnergyStop(self):
        try:
            float(self.energyDef.energyStop.text())
        except:
            self.energyDef.energyStop.undo()
        if float(self.energyDef.energyStart.text()) >= float(self.energyDef.energyStop.text()):
            self.energyDef.energyStop.undo()
        self.blockStep = True
        nPoints = (float(self.energyDef.energyStop.text()) - \
            float(self.energyDef.energyStart.text())) / float(self.energyDef.energyStep.text()) + 1
        self.energyDef.nEnergies.setText(str(int(nPoints)))
        self.blockStep = False
        self.regionChanged.emit()

    def updateDwell(self):
        try:
            float(self.energyDef.dwellTime.text())
        except:
            self.energyDef.dwellTime.undo()
        self.regionChanged.emit()

    def setSingleEnergy(self):
        self.energyDef.energyStop.setEnabled(False)
        self.energyDef.energyStep.setEnabled(False)
        self.energyDef.nEnergies.setEnabled(False)
        self.energyDef.singleEnergy = True

    def setMultiEnergy(self):
        self.energyDef.energyStop.setEnabled(True)
        self.energyDef.energyStep.setEnabled(True)
        self.energyDef.nEnergies.setEnabled(True)
        self.energyDef.singleEnergy = False

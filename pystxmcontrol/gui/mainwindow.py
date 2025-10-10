from pystxmcontrol.controller.client import stxm_client
from pystxmcontrol.gui.mainwindow_UI import Ui_MainWindow
from pystxmcontrol.gui.energyDef import energyDefWidget
from pystxmcontrol.gui.scanDef import scanRegionDef
from pystxmcontrol.utils.writeNX import *
from PySide6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np
import time, json, atexit, sys, os
from queue import Queue
import qdarktheme

BASEPATH = sys.prefix

class controlThread(QtCore.QThread):
    '''
    The main App will create a client and queue for passing messages.  Those are handed to this thread and used
    for passing messages to the client in a controlled way.  The client socket connection to the server is protected
    by a Lock object but it should in principle only receive messages from this thread.
    '''
    controlResponse = QtCore.Signal(object)

    def __init__(self, client, messageQueue):
        QtCore.QThread.__init__(self)
        self.messageQueue = messageQueue
        self.client = client
        self.monitor = True

    def run(self):
        while self.monitor:
            message = self.messageQueue.get(True)
            if message != "exit":
                response = self.client.send_message(message)
                if response is None:
                    response = {"command": message["command"],"status":"No response from server"}
                self.controlResponse.emit(response)
            else:
                return
                
class sampleScanWindow(QtWidgets.QMainWindow, Ui_MainWindow):

    new_data_signal = QtCore.Signal(object)

    def __init__(self, parent=None):
        super(sampleScanWindow, self).__init__(parent=parent)

        # set up the form class as a `ui` attribute
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.client = stxm_client()
        self.messageQueue = Queue()
        self.controlThread = controlThread(self.client, self.messageQueue)
        self.controlThread.start()
        self.serverStatus = False
        self.consoleText = []

        self.ui.focusRangeEdit.setText('100')
        self.ui.focusStepsEdit.setText('50')
        self.ui.lineLengthEdit.setText('10')
        self.ui.lineAngleEdit.setText('0')
        self.lineAngle = 0
        self.xLineRange = 70.
        self.yLineRange = 0.
        self.ui.linePointsEdit.setText('50')
        self.imageScale = 1,1
        self.imageCenter = 0,0

        self.ui.scanRegSpinbox.valueChanged.connect(self.updateScanRegDef)
        self.ui.energyRegSpinbox.valueChanged.connect(self.updateEnergyRegDef)
        self.ui.scanType.currentIndexChanged.connect(self.setScanParams)
        self.ui.channelSelect.currentIndexChanged.connect(self.setChannel)
        self.ui.toggleSingleEnergy.stateChanged.connect(self.setSingleEnergy)
        self.ui.action_Open_Image_Data.triggered.connect(self.getScanFile)
        self.ui.action_light_theme.triggered.connect(self.setLightTheme)
        self.ui.action_dark_theme.triggered.connect(self.setDarkTheme)
        self.ui.action_init.triggered.connect(self.re_init)
        self.ui.action_load_config_from_server.triggered.connect(self.load_config)
        self.ui.action_quit.triggered.connect(sys.exit)
        self.ui.beginScanButton.clicked.connect(self.beginScan)
        self.ui.cancelButton.clicked.connect(self.cancelScan)
        self.ui.roiCheckbox.stateChanged.connect(self.setROI)
        self.ui.jogToggleButton.clicked.connect(self.toggleJog)
        self.ui.motorMover1.currentIndexChanged.connect(self.updateMotorMover1)
        self.ui.motorMover2.currentIndexChanged.connect(self.updateMotorMover2)
        self.ui.motorMover1Button.clicked.connect(self.moveMotor1)
        self.ui.motorMover2Button.clicked.connect(self.moveMotor2)
        self.ui.motorMover1Plus.clicked.connect(self.moveMotor1Plus)
        self.ui.motorMover1Minus.clicked.connect(self.moveMotor1Minus)
        self.ui.motorMover2Plus.clicked.connect(self.moveMotor2Plus)
        self.ui.motorMover2Minus.clicked.connect(self.moveMotor2Minus)
        self.ui.energyEdit.returnPressed.connect(self.updateEnergy)
        self.ui.A0Edit.returnPressed.connect(self.updateA0)
        self.ui.A1Edit.returnPressed.connect(self.updateA1)
        self.ui.dsEdit.returnPressed.connect(self.updateDS)
        self.ui.ndsEdit.returnPressed.connect(self.updateNDS)
        self.ui.m101Edit.returnPressed.connect(self.updateM101)
        self.ui.fbkEdit.returnPressed.connect(self.updateFBK)
        self.ui.polEdit.returnPressed.connect(self.updatePOL)
        self.ui.epuEdit.returnPressed.connect(self.updateEPU)
        self.ui.lineLengthEdit.textChanged.connect(self.updateLineStepSize)
        self.ui.focusStepsEdit.returnPressed.connect(self.updateFocus)
        self.ui.focusRangeEdit.returnPressed.connect(self.updateFocus)
        self.ui.linePointsEdit.returnPressed.connect(self.updateLine)
        self.ui.lineLengthEdit.returnPressed.connect(self.updateLine)
        self.ui.lineAngleEdit.returnPressed.connect(self.updateLine)
        self.ui.shutterComboBox.currentIndexChanged.connect(self.updateShutter)
        self.ui.mainImage.scene.sigMouseMoved.connect(self.mouseMoved)
        self.ui.mainImage.scene.sigMouseClicked.connect(self.mouseClicked)
        self.ui.mainPlot.scene().sigMouseMoved.connect(self.plotMouseMoved)
        self.ui.plotClearButton.clicked.connect(self.clearPlot)
        self.ui.action_Save_Scan_Definition.triggered.connect(self.saveScanDef)
        self.ui.action_Open_Energy_Definition.triggered.connect(self.openEnergyDefinition)
        self.ui.action_Open_Scan_Definition.triggered.connect(self.openScanDefinition)
        self.ui.focusToCursorButton.clicked.connect(self.setFocusZ)
        self.ui.mainImage.sigTimeChanged.connect(self.updateTimeIndex)
        self.ui.showRangeFinder.stateChanged.connect(self.showRangeFinder)
        self.ui.doubleExposureCheckbox.stateChanged.connect(self.setDoubleExposure)
        self.ui.multiFrameCheckbox.stateChanged.connect(self.setMultiFrame)
        self.ui.proposalComboBox.currentIndexChanged.connect(self.updateExperimenters)
        self.ui.plotType.currentIndexChanged.connect(self.changePlot)
        self.ui.serverConnectButton.clicked.connect(self.changeServer)

        self.ui.compositeImageCheckbox.setCheckState(QtCore.Qt.Unchecked)
        self.ui.showBeamPosition.setCheckState(QtCore.Qt.Unchecked)
        self.ui.scanRegSpinbox.setEnabled(False)
        self.ui.energyRegSpinbox.setEnabled(False)
        self.ui.beginScanButton.setEnabled(False)
        self.ui.roiCheckbox.setEnabled(False)
        self.ui.motorMover1Minus.setEnabled(False)
        self.ui.motorMover1Plus.setEnabled(False)
        self.ui.motorMover2Minus.setEnabled(False)
        self.ui.motorMover2Plus.setEnabled(False)
        self.setFocusWidgets(False)
        self.setLineWidgets(False)
        self.ui.abortButton.setEnabled(False)
        self.ui.harSpin.setEnabled(False)
        self.ui.firstEnergyButton.clicked.connect(self.moveToFirstEnergy)
        self.ui.focusToCursorButton.setEnabled(False)
        self.ui.setCursor2ZeroButton.setEnabled(False)
        self.ui.setCursor2ZeroButton.clicked.connect(self.setCursor2Zero)
        self.ui.energyListWidget.setVisible(False)
        self.ui.energyListCheckbox.stateChanged.connect(self.setEnergyList)
        self.ui.motors2CursorButton.setEnabled(False)
        self.ui.motors2CursorButton.clicked.connect(self.motors2Cursor)
        self.ui.xMotorCombo.currentIndexChanged.connect(self.setEnergyScan)
        self.ui.A1Edit.setEnabled(False)
        #self.ui.scan_angle.valueChanged.connect(self.updateDial)

        self.tiled_scan = False
        self.maxVelocity = 1.0
        self.velocity = 0.0
        self.imageScanTypes = ["ptychographyGrid", "rasterLine", "continuousLine",'continuousSpiral','point']
        self.currentDataDir = "\home"
        self.pointOverhead = 0.0001
        self.lineOverhead = 0.02
        self.energyOverhead = 5.0
        self.currentEnergy = 500.0
        self.image = None
        self.scanRegList = []
        self.energyRegList = []
        self.scan = {}
        self.scanDefs = {}
        self.energyDefs = {}
        self.images = {}
        self.scan["energy_regions"] = {}
        self.scan["scan_regions"] = {}
        self.nRegion = 0
        self.nEnergyRegion = 0
        self.roiList = []
        self.monitorData = {"default":[]}
        self.monitorDataList = []
        self.monitorNPoints = 500
        self.beamPosition = None
        self.currentPlot = None
        self.exiting = False
        self.scanning = False
        self.crosshair = None
        self.horizontalLine = None
        self.verticalLine = None
        self.daqText = None
        self.xPlot = None
        self.yPlot = None
        self.rangeROI = None
        self.currentImageType = "Image"
        self.nRegDefs = 100
        self.nEnergyDefs = 100
        self.regDefs = []
        self.energyRegDefs = []
        for i in range(self.nRegDefs):
            regDef = [0,0,70,70,50,50,1.0,1.0]
            self.regDefs.append(regDef)
        for i in range(self.nEnergyDefs):
            energyDef = [500,600,1,2,1]
            self.energyRegDefs.append(energyDef)
        self.penColors = []
        totalColors = 0
        while totalColors <= self.nRegDefs:
            color = list(np.random.choice(range(256), size=3))
            if sum(color) / 3. > 80.:
                self.penColors.append(color)
                totalColors = len(self.penColors)
        self.penColors[0] = [255,100,180]
        self.penStyles = [QtCore.Qt.SolidLine, QtCore.Qt.DashLine]
        self.last_scan = self.client.main_config["lastScan"]
        self.ui.roiCheckbox.setCheckState(QtCore.Qt.Checked)
        print("Connecting to Client.")
        self.connectClient()
        print("Done. INitializing gui...")
        self.initGUI()
        self.focusRange = 100
        self.focusSteps = 50
        self.focusStepSize = 2.0
        self.cursorX = None
        self.cursorY = None
        self.metaFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/meta.json')
        self.metaStr = json.loads(open(self.metaFile).read())
        self._movingStyle = """QLabel {color: red;}"""
        self._staticStyle = """QLabel {color: black;}"""
        self.xCenter, self.yCenter = 0.,0.
        self.xRange, self.yRange = 70.,70.
        self.ui.defocusCheckbox.setCheckState(QtCore.Qt.Checked)
        self.ui.clearImageButton.clicked.connect(self.clearImage)
        self.ui.removeLastImageButton.clicked.connect(self.clearLastImage)
        self.ui.compositeImageCheckbox.stateChanged.connect(self.updateCompositeImage)
        self._motorLock = False
        self.singleMotorScanXData = []
        self.singleMotorScanYData = []
        self.consoleStr = ''
        self.setWindowTitle(f"STXM Control: {self.client.main_config['server']['name']}")

    def changeServer(self):
        # address = self.ui.serverAddressEdit.text().split(':')
        # if len(address) > 1:
        #     address,port = address
        # else:
        #     port = self.client.main_config["server"]["command_port"]
        # if self.client.connect_to_server(address, command_port = port):
        #     self.initGUI()
        pass

    def setCursor2Zero(self):
        x = round(self.cursorX,2)
        y = round(self.cursorY,2)
        x_motor = self.scan["x_motor"]
        y_motor = self.scan["y_motor"]
        x_current_offset = self.client.motorInfo[x_motor]["offset"]
        y_current_offset = self.client.motorInfo[y_motor]["offset"]
        result = self.warningPopup(f"Set {x_motor} = {x} and {y_motor} = {y} to 0?")
        if result:
            message = {"time": str(datetime.datetime.now()),"message": f"Setting {x_motor} = {x} and {y_motor} = {y} to 0"}
            self.printToConsole(message)
            message = {"command": "changeMotorConfig"}
            message["data"] = {"motor":x_motor,"config":"offset","value":x_current_offset - x}
            self.messageQueue.put(message)
            message = {"command": "changeMotorConfig"}
            message["data"] = {"motor":y_motor,"config":"offset","value":y_current_offset - y}
            self.messageQueue.put(message)
        else:
            return
        self.client.get_config()
        self.ui.scanType.setCurrentIndex(self.client.scanConfig["scans"][self.last_image_type]["index"])
        self.ui.mainImage.removeItem(self.horizontalLine)
        self.ui.mainImage.removeItem(self.verticalLine)

    def re_init(self):
        self.client.get_config()
        self.initGUI()

    def load_config(self):
        self.client.get_config()

    def setLightTheme(self):
        self.setStyleSheet(qdarktheme.load_stylesheet("light"))
        self._staticStyle = """QLabel {color: black;}"""

    def setDarkTheme(self):
        self.setStyleSheet(qdarktheme.load_stylesheet())
        self._staticStyle = """QLabel {color: white;}"""

    def motors2Cursor(self):
        if not self.scanning:
            message = {"command": "moveMotor"}
            message["axis"] = self.scan["x_motor"]
            message["pos"] = self.cursorX
            self.messageQueue.put(message)
            message = {"command": "moveMotor"}
            message["axis"] = self.scan["y_motor"]
            message["pos"] = self.cursorY
            self.messageQueue.put(message)

    def setEnergyScan(self):
        if self.ui.xMotorCombo.currentText() == "Energy":
            self.ui.defocusCheckbox.setEnabled(False)
            while len(self.scanRegList) > 1:
                self.ui.regionDefWidget.removeWidget(self.scanRegList[-1].region)
                self.scanRegList[-1].region.deleteLater()
                self.scanRegList[-1] = None
                del self.scanRegList[-1]
                self.ui.mainImage.removeItem(self.roiList[-1])
                del self.roiList[-1]
                self.nRegion -= 1
            self.ui.scanRegSpinbox.setValue(1)
            sampleX = self.currentMotorPositions['SampleX']
            sampleY = self.currentMotorPositions['SampleY']
            self.scanRegList[0].ui.xCenter.setText(str(round(sampleX,2)))
            self.scanRegList[0].ui.yCenter.setText(str(round(sampleY,2)))
            self.scanRegList[0].ui.xRange.setText('0.0')
            self.scanRegList[0].ui.yRange.setText('0.0')
            self.scanRegList[0].ui.xNPoints.setText('1')
            self.scanRegList[0].ui.yNPoints.setText('1')
            self.ui.doubleExposureCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.doubleExposureCheckbox.setEnabled(False)
            self.ui.multiFrameCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.multiFrameCheckbox.setEnabled(False)
            if self.scanType == "Single Motor":
                self.ui.roiCheckbox.setEnabled(False)
                for reg in self.scanRegList:
                    reg.setEnabled(False)
            self.ui.toggleSingleEnergy.setCheckState(QtCore.Qt.Unchecked)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(True)
            self.setFocusWidgets(False)
            self.setLineWidgets(False)
        else:
            self.ui.defocusCheckbox.setEnabled(False)
            for reg in self.scanRegList:
                reg.setEnabled(True)
            self.ui.scanRegSpinbox.setValue(1)
            self.ui.xMotorCombo.setEnabled(True)
            self.ui.energyRegSpinbox.setEnabled(False)
            self.ui.scanRegSpinbox.setEnabled(False)
            self.ui.focusToCursorButton.setEnabled(False)
            self.setFocusWidgets(False)
            self.setLineWidgets(False)
            self.ui.toggleSingleEnergy.setCheckState(QtCore.Qt.Checked)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.setSingleEnergy()

    def setEnergyList(self):
        if self.ui.energyListCheckbox.isChecked():
            self.ui.toggleSingleEnergy.setCheckState(QtCore.Qt.Unchecked)
            for i in range(len(self.energyRegList)):
                self.ui.energyDefWidget.removeWidget(self.energyRegList[-1].widget)
                self.energyRegList[-1].widget.deleteLater()
                self.energyRegList[-1] = None
                del self.energyRegList[-1]
                self.nEnergyRegion -= 1
            self.ui.energyListWidget.setVisible(True)
            self.ui.energyRegSpinbox.setEnabled(False)
        else:
            self.ui.energyRegSpinbox.setEnabled(True)
            if self.ui.energyRegSpinbox.value() == 1:
                self.ui.toggleSingleEnergy.setCheckState(QtCore.Qt.Checked)
            self.ui.energyListWidget.setVisible(False)
            self.updateEnergyRegDef()

    def setWarningBanner(self, warning = True):
        if warning != None:
            self.ui.warningLabel.setStyleSheet("color: red; background-color: yellow")
            self.ui.warningLabel.setText(warning)
        else:
            self.ui.warningLabel.setStyleSheet("")
            self.ui.warningLabel.setText("")

    def updateExperimenters(self):
        if self.ui.proposalComboBox.currentText() == "Staff Access":
            self.activateGUI()
            self.activateStaff()
            self.setWarningBanner("Users cannot access this data!")
        elif self.ui.proposalComboBox.currentIndex() > 0:
            plist = self.participants_list[self.ui.proposalComboBox.currentIndex()-1]
            pstring = plist[0]
            for i in range(1,len(plist)):
                pstring += ',' + plist[i]
            self.ui.experimentersLineEdit.setText(pstring)
            self.setWarningBanner(None)
        else:
            self.ui.experimentersLineEdit.setText('')
            self.setWarningBanner("Select a proposal to activate the GUI")
            self.deactivateGUI()
            self.deactivateStaff()

    def activateStaff(self):
        self.ui.A1Edit.setEnabled(True)
        self.ui.serverAddressEdit.setEnabled(True)
        self.ui.serverConnectButton.setEnabled(True)

    def deactivateStaff(self):
        self.ui.A1Edit.setEnabled(False)
        self.ui.serverAddressEdit.setEnabled(False)
        self.ui.serverConnectButton.setEnabled(False)

    def updateCompositeImage(self):
        if self.ui.compositeImageCheckbox.isChecked():
            for key in self.images.keys():
                self.ui.mainImage.removeItem(self.images[key])
            for key in self.images.keys():
                self.ui.mainImage.addItem(self.images[key])
        else:
            lastKey = list(self.images.keys())[-1]
            for key in self.images.keys():
                if key is not lastKey:
                    self.ui.mainImage.removeItem(self.images[key])

    def updateCompositeDisplay(self):
        pass

    def clearImage(self):
        for key in self.images.keys():
            self.images[key].setImage()
            self.ui.mainImage.removeItem(self.images[key])
        self.ui.mainImage.clear()
        self.images = {}

    def clearLastImage(self):
        key = list(self.images.keys())[-1]
        self.images[key].setImage()
        self.ui.mainImage.removeItem(self.images[key])
        del self.images[key]

    def setDoubleExposure(self):
        if self.ui.doubleExposureCheckbox.isChecked():
            self.ui.multiFrameCheckbox.setCheckState(QtCore.Qt.Unchecked)
        self.updateEstimatedTime()

    def setMultiFrame(self):
        if self.ui.multiFrameCheckbox.isChecked():
            self.ui.doubleExposureCheckbox.setCheckState(QtCore.Qt.Unchecked)
        self.updateEstimatedTime()

    def moveToFirstEnergy(self):
        self.updateEnergy(energy = float(self.energyRegList[0].energyDef.energyStart.text()))

    def showRangeFinder(self):
        if self.ui.showRangeFinder.isChecked():
            self.ui.mainImage.addItem(self.rangeROI)
        else:
            self.ui.mainImage.removeItem(self.rangeROI)

    def openEnergyDefinition(self):
        openFileName = str(QtWidgets.QFileDialog.getOpenFileName(QtWidgets.QWidget(), \
            'Open File', '/cosmic-dtn/groups/cosmic/Data/ScanDefinitions', 'JSON (*.json)')[0])
        if openFileName != '':
            try:
                scan = json.loads(open(openFileName).read())
                self.setGUIfromScan(scan, energyOnly = True)
            except IOError:
                print("Failed to open file %s" %openFileName)
            else:
                print("Opened scan definition file %s" %openFileName)

    def openScanDefinition(self):
        openFileName = str(QtWidgets.QFileDialog.getOpenFileName(QtWidgets.QWidget(), \
            'Open File', '/cosmic-dtn/groups/cosmic/Data/ScanDefinitions', 'JSON (*.json)')[0])
        if openFileName != '':
            try:
                scan = json.loads(open(openFileName).read())
                if scan["type"] == "Image":
                    self.ui.scanType.setCurrentIndex(0)
                    self.last_scan["Image"] = self.scan
                    self.setGUIfromScan(scan)
            except IOError:
                print("Failed to open file %s" %openFileName)
            else:
                print("Opened scan definition file %s" %openFileName)

    def saveScanDef(self):
        saveFileName = str(QtWidgets.QFileDialog.getSaveFileName(QtWidgets.QWidget(), \
            'Save File', '/', 'JSON (*.json)')[0])
        if saveFileName != '':
            try:
                if len(saveFileName.split('.json')) == 1:
                    saveFileName += '.json'
                with open(saveFileName, 'w') as fp:
                    json.dump(self.scan, fp, indent=4)
            except IOError:
                print("Failed to save file %s" %saveFileName)
            else:
                print("Saved data to file %s" %saveFileName)

    def clearPlot(self):
        if self.currentPlot is not None:
            self.ui.mainPlot.removeItem(self.currentPlot)
            self.monitorData[self.client.daqConfig["default"]["name"]]["data"] = []

    def plotMouseMoved(self,pos):
        vb = self.ui.mainPlot.getPlotItem().vb
        idx = vb.mapSceneToView(pos).x()
        channel = self.ui.channelSelect.currentText()
        if self.ui.plotType.currentText() == "Motor Scan":
            xdata = idx
            ydata = np.interp(idx,self.singleMotorScanXData,self.singleMotorScanYData[channel])
        elif self.ui.plotType.currentText() == "Monitor":
            xdata = idx
            daq = self.ui.channelSelect.currentText()
            ydata = np.interp(idx,np.arange(len(self.monitorData[daq]["data"])),self.monitorData[daq]["data"])
        self.ui.xCursorPos.setText(str(round(xdata,3)))
        self.ui.cursorIntensity.setText(str(round(ydata,3)))

    def mouseMoved(self, pos):

        self.scaleBarLength = np.round(100. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0], 3)

        if self.scaleBarLength < 1.:
            self.ui.scaleBarLength.setText(str(self.scaleBarLength * 1000.) + " nm")
        else:
            self.ui.scaleBarLength.setText(str(self.scaleBarLength) + " um")

        if (self.beamPosition is not None):
            self.ui.mainImage.removeItem(self.beamPosition)
        if self.ui.showBeamPosition.isChecked():
            size = 10. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0]
            if self.image is None:
                size = size / 8. * self.imageScale[0]
            self.beamPosition.setSize(size)
            self.ui.mainImage.addItem(self.beamPosition)

        scenePos = self.ui.mainImage.getImageItem().mapFromScene(pos)

        if "Image" in self.currentImageType or self.currentImageType == "Double Motor":
            x = (np.round(scenePos.x(), 3) * self.imageScale[0]) + self.xCenter - self.xRange / 2.
            y = (np.round(scenePos.y(), 3) * self.imageScale[1]) + self.yCenter - self.yRange / 2.
            # x = (np.round(pos.x(), 3) * self.imageScale[0]) + self.xCenter - self.xRange / 2.
            # y = (np.round(pos.y(), 3) * self.imageScale[1]) + self.yCenter - self.yRange / 2.
            xUnits = " um"
            yUnits = " um"
        elif "Focus" in self.currentImageType:
            lineRange = np.sqrt(self.xLineRange**2 + self.yLineRange**2)
            x = (np.round(scenePos.x(), 3) * self.imageScale[0]) * lineRange / self.xPts + self.xCenter - lineRange / 2.
            y = (np.round(scenePos.y(), 3) * self.imageScale[1]) * self.zRange / self.zPts + self.zCenter - self.zRange / 2.
            xUnits = " um"
            yUnits = " um"
        elif self.currentImageType == "Line Spectrum":
            eRange = self.stxm.energies["default"].max() - self.stxm.energies["default"].min()
            ePts = self.stxm.energies["default"].size
            eCenter = self.stxm.energies["default"].min() + eRange / 2.
            lineRange = np.sqrt(self.xLineRange**2 + self.yLineRange**2)
            y = (np.round(scenePos.y(), 3) * self.imageScale[1]) * lineRange / self.xPts + self.xCenter - lineRange / 2.
            x = (np.round(scenePos.x(), 3) * self.imageScale[0]) * eRange / ePts + eCenter - eRange / 2.
            xUnits = " eV"
            yUnits = " um"
        col, row = int(scenePos.y()), int(scenePos.x())
        self.ui.xCursorPos.setText(str(np.round(x,3)) + xUnits)
        self.ui.yCursorPos.setText(str(np.round(y,3)) + yUnits)

        if self.image is not None:
            sh = self.image.shape
            if len(sh) == 2:
                y, x = sh
            elif len(sh) == 3:
                z, y, x = sh
            frameIndex = self.ui.mainImage.currentIndex
            if (row in range(0,x)) and (col in range(0,y)):
                if len(sh) == 2:
                    cursorIntensity = np.transpose(self.image, axes=(1,0))[row,col]
                elif len(sh) == 3:
                    cursorIntensity = np.transpose(self.image, axes=(0,2,1))[frameIndex, row, col]
                self.ui.cursorIntensity.setText(str(cursorIntensity))
            else:
                self.ui.cursorIntensity.setText('0')
            if self.yPlot is not None:
                self.ui.mainPlot.removeItem(self.yPlot)
            if self.xPlot is not None:
                self.ui.mainPlot.removeItem(self.xPlot)

            if self.ui.plotType.currentText() == "Image X":
                if self.currentPlot is not None:
                    self.ui.mainPlot.removeItem(self.currentPlot)
                #y,x = self.image.shape
                xRange = x*self.imageScale[0]
                xOffset = self.imageCenter[0]
                xData = np.linspace(xOffset,xRange + xOffset, x)
                if len(sh) == 2:
                    yData = self.image[col,:]
                else:
                    yData = self.image[frameIndex,col,:]
                if (row in range(0, x)) and (col in range(0, y)):
                    self.xPlot = self.ui.mainPlot.plot(xData, yData, \
                                                         pen=pg.mkPen('w', width=1, style=QtCore.Qt.DotLine), symbol='o',
                                                         symbolPen='r', symbolSize=3, \
                                                         symbolBrush=(255, 0, 0))

            if self.ui.plotType.currentText() == "Image Y":
                if self.currentPlot is not None:
                    self.ui.mainPlot.removeItem(self.currentPlot)
                #y,x = self.image.shape
                xRange = y*self.imageScale[1]
                xOffset = self.imageCenter[1]
                xData = np.linspace(xOffset,xRange + xOffset, y)
                if len(sh) == 2:
                    yData = self.image[:,row]
                else:
                    yData = self.image[frameIndex,:,row]
                if (row in range(0, x)) and (col in range(0, y)):
                    self.yPlot = self.ui.mainPlot.plot(xData, yData, \
                                                         pen=pg.mkPen('w', width=1, style=QtCore.Qt.DotLine), symbol='o',
                                                         symbolPen='b', symbolSize=3, \
                                                         symbolBrush=(0, 0, 255))

            if self.ui.plotType.currentText() == "Image XY":
                if self.currentPlot is not None:
                    self.ui.mainPlot.removeItem(self.currentPlot)
                #y,x = self.image.shape
                xRange = x*self.imageScale[0]
                xOffset = self.imageCenter[0]
                xData = np.linspace(xOffset,xRange + xOffset, x)
                if len(sh) == 2:
                    yData = self.image[col,:]
                else:
                    yData = self.image[frameIndex,col,:]
                if (row in range(0, x)) and (col in range(0, y)):
                    self.xPlot = self.ui.mainPlot.plot(xData, yData, \
                                                         pen=pg.mkPen('w', width=1, style=QtCore.Qt.DotLine), symbol='o',
                                                         symbolPen='r', symbolSize=3, \
                                                         symbolBrush=(255, 0, 0))
                #y,x = self.image.shape
                xRange = y*self.imageScale[1]
                xOffset = self.imageCenter[1]
                xData = np.linspace(xOffset,xRange + xOffset, y)
                if len(sh) == 2:
                    yData = self.image[:,row]
                else:
                    yData = self.image[frameIndex,:,row]
                if (row in range(0, x)) and (col in range(0, y)):
                    self.yPlot = self.ui.mainPlot.plot(xData, yData, \
                                                         pen=pg.mkPen('w', width=1, style=QtCore.Qt.DotLine), symbol='o',
                                                         symbolPen='b', symbolSize=3, \
                                                         symbolBrush=(0, 0, 255))

    def printToConsole(self, message):
        self.lastMessage = message
        self.consoleStr = '['+str(message["time"])+']\n' + json.dumps(message) + '\n\n' + self.consoleStr
        self.ui.serverOutput.setText(self.consoleStr)

    def updateLineStepSize(self):
        length = float(self.ui.lineLengthEdit.text())
        points = int(self.ui.linePointsEdit.text())
        self.ui.lineStepSizeLabel.setText(str(np.round(length / points, 3)))

    def updateShutter(self):
        message = {"command": "setGate"}
        if self.ui.shutterComboBox.currentText() == "Shutter Auto":
            message["mode"] = "auto"
        elif self.ui.shutterComboBox.currentText() == "Shutter Open":
            message["mode"] = "open"
        elif self.ui.shutterComboBox.currentText() == "Shutter Closed":
            message["mode"] = "closed"
        self.client.send_message(message)

    def updateFocus(self):
        range = float(str(self.ui.focusRangeEdit.text()))
        steps = float(str(self.ui.focusStepsEdit.text()))
        stepSize = range / steps
        self.ui.focusStepSizeLabel.setText(str(np.round(stepSize,2)))
        self.focusRange = range
        self.focusSteps = steps
        self.focusStepSize = np.round(stepSize,2)

    def updateDial(self):
        self.ui.lineAngleEdit.setText(str(self.ui.scan_angle.value()))

    def updateLine(self):
        lineRange = float(str(self.ui.lineLengthEdit.text()))
        if lineRange > 75:
            lineRange = 70
            self.ui.lineLengthEdit.setText(str(70))
        steps = float(str(self.ui.linePointsEdit.text()))
        stepSize = lineRange / steps
        self.ui.lineStepSizeLabel.setText(str(np.round(stepSize,2)))
        self.lineLength = lineRange
        self.linePoints = steps
        self.lineStepSize = np.round(stepSize,2)
        self.lineAngle = float(self.ui.lineAngleEdit.text())
        self.updateROIfromRegion(1)

    def updateEnergy(self, energy = None):
        try:
            if energy == None:
                newValue = float(self.ui.energyEdit.text())
            else:
                newValue = energy
        except:
            print("Please enter a floating point number")
        else:
            message = {"command": "moveMotor"}
            message["axis"] = "Energy"
            message["pos"] = newValue
            self.messageQueue.put(message)
            if self.ui.toggleSingleEnergy.isChecked():
                self.energyRegList[-1].energyDef.energyStart.setText(str(newValue))

    def updateA0(self, A0 = None):
        if self.client.main_config["geometry"]["A0_calibrated"]:
            try:
                if A0 == None:
                    newValue = float(self.ui.A0Edit.text())
                else:
                    newValue = A0
            except:
                self.errorPopup("Please enter a valid number")
                return
            if (newValue < self.client.motorInfo["Energy"]["A0_min"]) or (newValue > self.client.motorInfo["Energy"]["A0_max"]):
                self.errorPopup("Requested A0 exceeds allowed limits")
            else:
                message = {"command": "changeMotorConfig"}
                message["data"] = {"motor":"Energy","config":"A0","value":newValue}
                self.messageQueue.put(message)

                message = {"command": "move_to_focus"}
                self.messageQueue.put(message)
                time.sleep(1)
                self.client.get_config()
        
    def updateA1(self, A1 = None):
        try:
            if A1 == None:
                newValue = float(self.ui.A1Edit.text())
            else:
                newValue = A1
        except:
            self.errorPopup("Please enter a valid number")
            return
        message = {"command": "changeMotorConfig"}
        message["data"] = {"motor":"Energy","config":"A1","value":newValue}
        self.messageQueue.put(message)
        self.client.get_config() 

    def updateDS(self):
        try:
            newValue = float(self.ui.dsEdit.text())
        except:
            print("Please enter a floating point number")
        else:
            message = {"command": "moveMotor"}
            message["axis"] = "DISPERSIVE_SLIT"
            message["pos"] = newValue
            self.messageQueue.put(message)

    def updateNDS(self):
        try:
            newValue = float(self.ui.ndsEdit.text())
        except:
            print("Please enter a floating point number")
        else:
            message = {"command": "moveMotor"}
            message["axis"] = "NONDISPERSIVE_SLIT"
            message["pos"] = newValue
            self.messageQueue.put(message)

    def updateM101(self):
        try:
            newValue = float(self.ui.m101Edit.text())
        except:
            print("Please enter a floating point number")
        else:
            message = {"command": "moveMotor"}
            message["axis"] = "M101PITCH"
            message["pos"] = newValue
            self.messageQueue.put(message)

    def updateFBK(self):
        try:
            newValue = float(self.ui.fbkEdit.text())
        except:
            print("Please enter a floating point number")
        else:
            message = {"command": "moveMotor"}
            message["axis"] = "FBKOFFSET"
            message["pos"] = newValue
            self.messageQueue.put(message)

    def updateEPU(self):
        try:
            newValue = float(self.ui.epuEdit.text())
        except:
            print("Please enter a floating point number")
        else:
            message = {"command": "moveMotor"}
            message["axis"] = "EPUOFFSET"
            message["pos"] = newValue
            self.messageQueue.put(message)

    def updatePOL(self):
        try:
            newValue = float(self.ui.polEdit.text())
        except:
            print("Please enter a floating point number")
        else:
            message = {"command": "moveMotor"}
            message["axis"] = "POLARIZATION"
            message["pos"] = newValue
            self.messageQueue.put(message)

    def updateHAR(self):
        newValue = self.ui.harSpin.value()
        message = {"command": "moveMotor"}
        message["axis"] = "HARMONIC"
        message["pos"] = newValue
        self.messageQueue.put(message)

    def mouseClicked(self, pos):

        if self.ui.channelSelect.currentText() == "CCD":
            return

        if self.image is not None and (self.currentImageType == self.ui.scanType.currentText()):
            pos = pos.pos()
            if self.horizontalLine is not None:
                self.ui.mainImage.removeItem(self.horizontalLine)
            if self.verticalLine is not None:
                self.ui.mainImage.removeItem(self.verticalLine)
            scenePos = self.ui.mainImage.getImageItem().mapFromScene(pos)

            if "Image" in self.scan["scan_type"] or self.scan["scan_type"] == "Double Motor":

                x = (scenePos.x() * self.imageScale[0]) + self.xGlobalCenter - self.xGlobalRange / 2. - self.xPixelSize / 2.
                y = (scenePos.y() * self.imageScale[1]) + self.yGlobalCenter - self.yGlobalRange / 2. - self.yPixelSize / 2.
                print(scenePos.x(),scenePos.y(),self.imageScale)
                self.cursorX, self.cursorY = x,y
                self.ui.motors2CursorButton.setEnabled(True)
                if self.scan["scan_type"] == "Double Motor":
                    self.ui.setCursor2ZeroButton.setEnabled(True)
            elif "Focus" in self.scan["scan_type"]:
                x = (np.round(scenePos.x(), 3) * self.imageScale[0]) + self.xCenter - self.xRange / 2.
                zRange = (np.round(scenePos.y(), 3) - self.zPts / 2) * float(self.ui.focusStepSizeLabel.text())
                yPos = zRange + float(self.ui.focusCenterEdit.text())
                y = np.round(scenePos.y(), 3) + self.imageCenter[1]
                self.cursorFocusZ = yPos
                self.ui.focusToCursorButton.setEnabled(True)
            elif "Line" in self.scan["scan_type"]:
                eRange = self.stxm.energies["default"].max() - self.stxm.energies["default"].min()
                y = (np.round(scenePos.y(), 3) * self.imageScale[1]) + self.yCenter - self.yRange / 2.
                x = np.round(scenePos.x(), 3) + self.imageCenter[0]

            pen = pg.mkPen(color = (0,255,0),width=1,style=QtCore.Qt.SolidLine)
            self.horizontalLine = pg.InfiniteLine(pos = y, angle = 0, pen = pen)
            self.verticalLine = pg.InfiniteLine(pos = x, angle = 90, pen = pen)
            self.ui.mainImage.addItem(self.horizontalLine)
            self.ui.mainImage.addItem(self.verticalLine)

    def setFocusZ(self):
        """
        The OSA focus scan is used to determine the corrent ZonePlateZ offset since the OSA is the ZERO of the Z coordinate.
        A regular sample focus scan is used to calibrate the current actual A0 value.
        """
        self.ui.focusToCursorButton.setEnabled(False)
        self.client.get_config()
        A0 = self.client.motorInfo["Energy"]["A0"]
        if "OSA" in self.scan["scan_type"]:
            #This changes the ZonePlateZ offset 
            offsetDelta = (self.zonePlateCalibration - A0 - self.cursorFocusZ)
            newOffset = self.zonePlateOffset + offsetDelta
            print(f"Setting ZonePlateZ offset to {newOffset}")
            message = {"command": "changeMotorConfig"}
            message["data"] = {"motor":"ZonePlateZ","config":"offset","value":newOffset}
            self.messageQueue.put(message)
            time.sleep(0.5)
        else:
            #This only changes the A0, so if requires the SampleZ stage to move to the correct focus position
            #How is the SampleZ stage offset calibrated.  That needs to be done.
            #We need another mode which doesn't move the SampleZ stage so that this will do just the old style focus scan.
            #zonePlateCalibration position is the expected focus on the sample.  Measure difference between that and focus in the scan.
            #apply that difference to A0.  This is a calibration of A0.
            if self.client.main_config["geometry"]["A0_calibrated"]:
                newA0 = A0 - (self.zonePlateCalibration - self.cursorFocusZ)
                print(f"Setting A0 to {newA0}")
                self.updateA0(A0=newA0)
                #change the motor offset to SampleZ such that it's position during the focus scan is set to the new A0 value.
                sampleZ_offsetDelta=newA0-A0
                newSampleZOffset = self.client.motorInfo["SampleZ"]["offset"]+sampleZ_offsetDelta
                print(f"Setting SampleZ offset to {newSampleZOffset}")
                message = {"command": "changeMotorConfig"}
                message["data"] = {"motor":"SampleZ","config":"offset","value":newSampleZOffset}
                self.messageQueue.put(message)
                time.sleep(0.5)
            else:
                #This changes the ZonePlateZ offset 
                offsetDelta = (self.zonePlateCalibration - A0 - self.cursorFocusZ)
                newOffset = self.zonePlateOffset + offsetDelta
                print(f"Setting ZonePlateZ offset to {newOffset}")
                message = {"command": "changeMotorConfig"}
                message["data"] = {"motor":"ZonePlateZ","config":"offset","value":newOffset}
                self.messageQueue.put(message)
                time.sleep(0.5)

        #move zone plate to new focus position
        message = {"command": "moveMotor"}
        message["axis"] = "ZonePlateZ"
        message["pos"] = self.zonePlateCalibration
        self.messageQueue.put(message)

        self.ui.scanType.setCurrentIndex(self.client.scanConfig["scans"][self.last_image_type]["index"])
        self.ui.mainImage.removeItem(self.horizontalLine)
        self.ui.mainImage.removeItem(self.verticalLine)

    def abortMove(self):
        message = {"command": "abortMove"}
        message["axis"] = self.lastMotor

    def moveMotor1(self):
        message = {"command": "moveMotor"}
        message["axis"] = str(self.ui.motorMover1.currentText())
        message["pos"] = float(str(self.ui.motorMover1Edit.text()))
        self.lastMotor = message["axis"]
        self.messageQueue.put(message)

    def moveMotor2(self):
        message = {"command": "moveMotor"}
        message["axis"] = str(self.ui.motorMover2.currentText())
        message["pos"] = float(self.ui.motorMover2Edit.text())
        self.messageQueue.put(message)

    def moveMotor1Plus(self):
        axis = str(self.ui.motorMover1.currentText())
        pos = self.currentMotorPositions[axis] + float(self.ui.motorMover1Edit.text())
        message = {"command": "moveMotor"}
        message["axis"] = axis
        message["pos"] = pos
        self.messageQueue.put(message)

    def moveMotor1Minus(self):
        axis = str(self.ui.motorMover1.currentText())
        pos = self.currentMotorPositions[axis] - float(self.ui.motorMover1Edit.text())
        message = {"command": "moveMotor"}
        message["axis"] = axis
        message["pos"] = pos
        self.messageQueue.put(message)

    def moveMotor2Plus(self):
        axis = str(self.ui.motorMover2.currentText())
        pos = self.currentMotorPositions[axis] + float(self.ui.motorMover2Edit.text())
        message = {"command": "moveMotor"}
        message["axis"] = axis
        message["pos"] = pos
        self.messageQueue.put(message)

    def moveMotor2Minus(self):
        axis = str(self.ui.motorMover2.currentText())
        pos = self.currentMotorPositions[axis] - float(self.ui.motorMover2Edit.text())
        message = {"command": "moveMotor"}
        message["axis"] = axis
        message["pos"] = pos
        self.messageQueue.put(message)

    def toggleJog(self):
        if self.ui.motorMover1Minus.isEnabled():
            self.ui.motorMover1Minus.setEnabled(False)
            self.ui.motorMover1Plus.setEnabled(False)
            self.ui.motorMover2Minus.setEnabled(False)
            self.ui.motorMover2Plus.setEnabled(False)
            self.ui.motorMover1Button.setEnabled(True)
            self.ui.motorMover2Button.setEnabled(True)
            self.ui.motorMover1Edit.setText(\
                str(np.round(self.currentMotorPositions[str(self.ui.motorMover1.currentText())],3)))
            self.ui.motorMover2Edit.setText(\
                str(np.round(self.currentMotorPositions[str(self.ui.motorMover2.currentText())], 3)))
        else:
            self.ui.motorMover1Minus.setEnabled(True)
            self.ui.motorMover1Plus.setEnabled(True)
            self.ui.motorMover2Minus.setEnabled(True)
            self.ui.motorMover2Plus.setEnabled(True)
            self.ui.motorMover1Button.setEnabled(False)
            self.ui.motorMover2Button.setEnabled(False)
            self.ui.motorMover1Edit.setText(str(10.))
            self.ui.motorMover2Edit.setText(str(10.))

    def updateMotorMover1(self):
        if self.ui.motorMover1Minus.isEnabled():
            self.ui.motorMover1Edit.setText(str(10.))
        else:
            self.ui.motorMover1Edit.setText(\
                str(np.round(self.currentMotorPositions[str(self.ui.motorMover1.currentText())],3)))
    def updateMotorMover2(self):
        if self.ui.motorMover1Minus.isEnabled():
            self.ui.motorMover2Edit.setText(str(10.))
        else:
            self.ui.motorMover2Edit.setText(\
                str(np.round(self.currentMotorPositions[str(self.ui.motorMover2.currentText())], 3)))

    def activateGUI(self):
        self.ui.compositeImageCheckbox.setEnabled(True)
        self.ui.removeLastImageButton.setEnabled(True)
        self.ui.clearImageButton.setEnabled(True)
        self.ui.firstEnergyButton.setEnabled(True)
        self.ui.scanRegSpinbox.setEnabled(True)
        self.ui.energyRegSpinbox.setEnabled(True)
        self.ui.beginScanButton.setEnabled(True)
        self.ui.scanType.setEnabled(True)
        if self.scanType in ("Image", "Spiral Image", "Double Motor"):
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.toggleSingleEnergy.setEnabled(True)
            for reg in self.scanRegList:
                reg.setEnabled(True)
            if self.scanType == "Double Motor":
                self.ui.xMotorCombo.setEnabled(True)
                self.ui.yMotorCombo.setEnabled(True)
        elif self.ui.scanType.currentText() == "Single Motor":
            self.ui.xMotorCombo.setEnabled(True)
            if self.ui.xMotorCombo.currentText() != "Energy":
                for reg in self.scanRegList:
                    reg.setEnabled(True)
        elif self.ui.scanType.currentText() == "Line Spectrum":
            pass
        if self.ui.showRangeFinder.isChecked():
            if "Image" in self.scanType:
                self.ui.mainImage.addItem(self.rangeROI)
        self.setScanParams()

    def deactivateGUI(self):
        self.ui.compositeImageCheckbox.setEnabled(False)
        self.ui.removeLastImageButton.setEnabled(False)
        self.ui.clearImageButton.setEnabled(False)
        self.ui.firstEnergyButton.setEnabled(False)
        self.ui.toggleSingleEnergy.setEnabled(False)
        self.ui.scanType.setEnabled(False)
        self.ui.scanRegSpinbox.setEnabled(False)
        self.ui.energyRegSpinbox.setEnabled(False)
        self.ui.beginScanButton.setEnabled(False)
        self.ui.focusToCursorButton.setEnabled(False)
        self.ui.xMotorCombo.setEnabled(False)
        self.ui.yMotorCombo.setEnabled(False)
        self.ui.motors2CursorButton.setEnabled(False)
        self.hideROIs()
        self.ui.roiCheckbox.setCheckState(QtCore.Qt.Unchecked)
        self.ui.roiCheckbox.setEnabled(False)
        for reg in self.scanRegList:
            reg.setEnabled(False)
        if (self.beamPosition is not None):# and self.ui.showBeamPosition.isChecked():
            self.ui.mainImage.removeItem(self.beamPosition)
        if self.horizontalLine is not None:
            self.ui.mainImage.removeItem(self.horizontalLine)
        if self.verticalLine is not None:
            self.ui.mainImage.removeItem(self.verticalLine)

    def disconnect(self):
        self.exiting = True
        self.controlThread.monitor = False
        self.messageQueue.put("exit")
        self.client.disconnect()

    def setROI(self):
        if self.ui.roiCheckbox.isChecked():
            self.showROIs()
        else:
            self.hideROIs()

    def cancelScan(self):

        if self.client.get_status()["mode"] == "scanning":
            message = {"command": "cancel"}
            self.messageQueue.put(message)

    @QtCore.Slot()
    def compileScan(self,caller = None, nowrite = True):
        self.scanList = {}
        self.scan = {}
        self.scanType = str(self.ui.scanType.currentText())
        scanMotorList = self.client.scanConfig["scans"][self.scanType]
        self.scan["driver"] = self.client.scanConfig["scans"][self.scanType]["driver"]
        self.scan["mode"] = self.client.scanConfig["scans"][self.scanType]["mode"]
        self.scan["spiral"] = False
        self.scan["scan_type"] = self.scanType
        self.scan["tiled"] = self.ui.tiledCheckbox.isChecked() #self.tiled_scan
        self.scan["proposal"] = self.ui.proposalComboBox.currentText()
        self.scan["experimenters"] = self.ui.experimentersLineEdit.text()
        self.scan["sample"] = self.ui.sampleLineEdit.text()
        self.scan["comment"] = self.ui.commentEdit.toPlainText()
        self.scan["nxFileVersion"] = self.client.main_config["server"]["nx_file_version"] #TODO: Move this in config file?
        self.scan["x_motor"] = self.ui.xMotorCombo.currentText() #["xMotor"]
        self.scan["y_motor"] = self.ui.yMotorCombo.currentText() #["yMotor"]
        self.scan["defocus"] = self.ui.defocusCheckbox.isChecked()
        self.scan['autofocus'] = self.ui.autofocusCheckbox.isChecked()
        self.scan["coarse_only"] = False #this is set True later in scanCheck() for coarse only scans
        self.scan["daq list"] = self.client.scanConfig["scans"][self.scanType]["daq list"].split(',')
        self.scan["oversampling_factor"] = self.client.daqConfig["default"]["oversampling_factor"]
        if self.scan["mode"] == "continuousSpiral":
            self.scan["spiral"] = True
        self.scan['retract'] = True
        self.scan["scan_regions"] = {}
        self.scan["energy_regions"] = {}
        for index, region in enumerate(self.scanRegList):
            regStr = "Region" + str(index + 1)
            self.scan["scan_regions"][regStr] = {}
            if "Image" in self.scanType:
                self.last_image_type = self.scanType
                self.scan["energy_motor"] = scanMotorList["energy_motor"]
                xCenter = float(region.ui.xCenter.text())
                yCenter = float(region.ui.yCenter.text())
                xRange = float(region.ui.xRange.text())
                yRange = float(region.ui.yRange.text())
                xPoints = int(region.ui.xNPoints.text())
                yPoints = int(region.ui.yNPoints.text())
                xStep = float(region.ui.xStep.text())
                yStep = float(region.ui.yStep.text())
                zCenter = 0
                zRange = 0
                zPoints = 1
                zStep = 0
            elif ("Focus" in self.scanType):
                self.scan["z_motor"] = scanMotorList["z_motor"]
                xCenter = float(region.ui.xCenter.text())
                yCenter = float(region.ui.yCenter.text())
                xRange = self.xLineRange
                yRange = self.yLineRange
                zCenter = float(self.ui.focusCenterEdit.text())
                zRange = float(self.ui.focusRangeEdit.text())
                zPoints = int(self.ui.focusStepsEdit.text())
                zStep = float(self.ui.focusStepSizeLabel.text())
                xPoints = int(self.ui.linePointsEdit.text())
                yPoints = int(self.ui.linePointsEdit.text())
                direction = np.array([xRange,yRange])/(xRange**2+yRange**2)**0.5
                xStep = float(self.ui.lineStepSizeLabel.text())*direction[0]
                yStep = float(self.ui.lineStepSizeLabel.text())*direction[1]
            elif (self.scanType == "Line Spectrum"):
                self.scan["energy_motor"] = scanMotorList["energy_motor"]
                xCenter = float(region.ui.xCenter.text())
                yCenter = float(region.ui.yCenter.text())
                xRange = self.xLineRange
                yRange = self.yLineRange
                xPoints = int(self.ui.linePointsEdit.text())
                yPoints = 1 #int(self.ui.linePointsEdit.text())
                direction = np.array([xRange,yRange])/(xRange**2+yRange**2)**0.5
                xStep = float(self.ui.lineStepSizeLabel.text())*direction[0]
                yStep = 0. #float(self.ui.lineStepSizeLabel.text())*direction[1]
                zCenter = 0
                zRange = 0
                zPoints = 1
                zStep = 0
            elif (self.scanType == "Single Motor"):
                self.singleMotorScanXData = []
                self.singleMotorScanYData = {}
                self.scan["x_motor"] = self.ui.xMotorCombo.currentText()
                self.scan["y_motor"] = self.ui.yMotorCombo.currentText()
                self.scan["energy_motor"] = scanMotorList["energy_motor"]
                xCenter = float(region.ui.xCenter.text())
                yCenter = 0
                xRange = float(region.ui.xRange.text())
                yRange = 0
                if self.scan["x_motor"] == "Energy":
                    xPoints = 1
                else:
                    xPoints = int(region.ui.xNPoints.text())
                yPoints = 1
                xStep = float(region.ui.xStep.text())
                yStep = 0
                zCenter = 0
                zRange = 0
                zPoints = 1
                zStep = 0
            elif (self.scanType == "Double Motor") or (self.scanType == "OSA Image"):
                xCenter = float(region.ui.xCenter.text())
                yCenter = float(region.ui.yCenter.text())
                xRange = float(region.ui.xRange.text())
                yRange = float(region.ui.yRange.text())
                xPoints = int(region.ui.xNPoints.text())
                yPoints = int(region.ui.yNPoints.text())
                xStep = float(region.ui.xStep.text())
                yStep = float(region.ui.yStep.text())
                zCenter = 0
                zRange = 0
                zPoints = 1
                zStep = 0
                zStep = 0
            
            #these are used to properly set the crosshairs when clicking in the image
            self.xPixelSize = xStep
            self.yPixelSize = yStep

            self.scan["scan_regions"][regStr]["xStart"] = xCenter - xRange / 2.0 + xStep / 2.
            self.scan["scan_regions"][regStr]["xStop"] = xCenter + xRange / 2.0 - xStep / 2.
            self.scan["scan_regions"][regStr]["xPoints"] = xPoints
            self.scan["scan_regions"][regStr]["yStart"] = yCenter - yRange / 2.0 + yStep / 2.
            self.scan["scan_regions"][regStr]["yStop"] = yCenter + yRange / 2.0 - yStep / 2.
            self.scan["scan_regions"][regStr]["yPoints"] = yPoints
            self.scan["scan_regions"][regStr]["xStep"] = xStep
            self.scan["scan_regions"][regStr]["yStep"] = yStep
            self.scan["scan_regions"][regStr]["xRange"] = xRange
            self.scan["scan_regions"][regStr]["yRange"] = yRange
            self.scan["scan_regions"][regStr]["xCenter"] = xCenter
            self.scan["scan_regions"][regStr]["yCenter"] = yCenter
            self.scan["scan_regions"][regStr]["zStart"] = zCenter - zRange / 2.0 + zStep / 2.
            self.scan["scan_regions"][regStr]["zStop"] = zCenter + zRange / 2.0 - zStep / 2.
            self.scan["scan_regions"][regStr]["zPoints"] = zPoints
            self.scan["scan_regions"][regStr]["zStep"] = zStep
            self.scan["scan_regions"][regStr]["zRange"] = zRange
            self.scan["scan_regions"][regStr]["zCenter"] = zCenter
        for index, region in enumerate(self.energyRegList):
            regStr = "EnergyRegion" + str(index + 1)
            #enforce single dwell
            if regStr == "EnergyRegion1":
                dwellStr = region.energyDef.dwellTime.text()
            #enforce dwell limits
            #currently limits are 0.1 for image scan, 0.31 for others.
            #Top range is 15 ms for each. This takes into account oversampling.
            #difference in limits is because of multi-axis scan for line/focus.
            if self.scanType == "Image":
                if self.scan['mode'] == "continuousSpiral":
                    if float(dwellStr)<0:
                        dwellStr = '0.'
                    # if float(dwellStr)>10.:
                    #     dwellStr = '10.'
                else:
                    if float(dwellStr)<0.12:
                        dwellStr = '0.12'
                    # elif float(dwellStr)>15.:
                    #     dwellStr = '15.'
            elif "Focus" in self.scanType or self.scanType == "Line Spectrum":
                if float(dwellStr)<0.31:
                    dwellStr = '0.31'
                # elif float(dwellStr)>15.:
                #     dwellStr = '15.'
                
            region.energyDef.dwellTime.setText(dwellStr)
            self.scan["energy_regions"][regStr] = {}
            self.scan["energy_regions"][regStr]["dwell"] = float(region.energyDef.dwellTime.text())
            self.scan["energy_regions"][regStr]["start"] = float(region.energyDef.energyStart.text())
            self.scan["energy_regions"][regStr]["stop"] = float(region.energyDef.energyStop.text())
            self.scan["energy_regions"][regStr]["step"] = float(region.energyDef.energyStep.text())
            self.scan["energy_regions"][regStr]["n_energies"] = int(region.energyDef.nEnergies.text())

        if self.ui.energyListCheckbox.isChecked():
            energyListStr = self.ui.energyListEdit.toPlainText()
            try:
                self.scan["energy_list"] = [float(x) for x in energyListStr.split(',')]
                #get the dwell from the first energy def
                self.scan["dwell"] = self.energyRegDefs[0][-1] #last list item is the dwell time
            except:
                return "Energy List Error"
            
        self.scanList[self.scanType] = self.scan

        if self.ui.doubleExposureCheckbox.isChecked():
            self.scan["doubleExposure"] = True
        else:
            self.scan["doubleExposure"] = False
        if self.ui.multiFrameCheckbox.isChecked():
            self.scan["n_repeats"] = 5
        else:
            self.scan["n_repeats"] = 1

        ##generate the local data structure
        if self.scan["mode"] in self.imageScanTypes:
            self.stxm = stxm(self.scan)

        if not(nowrite):
            self.client.main_config["lastScan"][self.scan["scan_type"]] = self.scan
            self.client.write_config()

    def updateEstimatedTime(self):
        self.compileScan('updateEstimatedTime')

        for i in range(len(self.energyRegList)):
            self.energyRegDefs[i][0] = float(self.energyRegList[i].energyDef.energyStart.text())
            self.energyRegDefs[i][1] = float(self.energyRegList[i].energyDef.energyStop.text())
            self.energyRegDefs[i][2] = float(self.energyRegList[i].energyDef.energyStep.text())
            self.energyRegDefs[i][3] = int(self.energyRegList[i].energyDef.nEnergies.text())
            self.energyRegDefs[i][4] = float(self.energyRegList[i].energyDef.dwellTime.text())

        estimatedTime = 0.
        nPoints = 0
        nLines = 0
        nEnergies = 0
        timePerPoint = 0

        self.lineOverhead = 0.095
        for region in self.scan["scan_regions"].keys():
            if "Image" in self.scan["scan_type"]:
                nPoints += self.scan["scan_regions"][region]["xPoints"] * \
                    self.scan["scan_regions"][region]["yPoints"]
                nLines += self.scan["scan_regions"][region]["yPoints"]
            elif "Focus" in self.scan["scan_type"]:
                nPoints += self.scan["scan_regions"][region]["xPoints"] * \
                    self.scan["scan_regions"][region]["zPoints"]
                nLines += self.scan["scan_regions"][region]["zPoints"]
            elif self.scan["scan_type"] == "Line Spectrum":
                nPoints += self.scan["scan_regions"][region]["xPoints"]
            if "Ptychography" in self.scan["scan_type"]:
                nPoints += 25 #for background points

        for region in self.scan["energy_regions"].keys():
            if self.scan["scan_type"] == "Line Spectrum":
                nLines = self.scan["energy_regions"][region]["n_energies"]
            if "Ptychography" in self.scan["scan_type"]:
                if self.ui.doubleExposureCheckbox.isChecked():
                    pointOverhead = 0.2
                    pointDwell = (self.scan["energy_regions"][region]["dwell"] + self.scan["energy_regions"][region]["dwell"]*10.)
                elif self.ui.multiFrameCheckbox.isChecked():
                    pointOverhead = 0.25
                    pointDwell = self.scan["energy_regions"][region]["dwell"]*5.
                else:
                    pointOverhead = 0.1
                    pointDwell = self.scan["energy_regions"][region]["dwell"]
                timePerPoint += (pointDwell / 1000. \
                                 + pointOverhead) * self.scan["energy_regions"][region]["n_energies"]
            else:
                timePerPoint += (self.scan["energy_regions"][region]["dwell"] / 1000. \
                               + self.pointOverhead) * self.scan["energy_regions"][region]["n_energies"]
            nEnergies += self.scan["energy_regions"][region]["n_energies"]
        estimatedTime = nPoints * timePerPoint + nLines * self.lineOverhead + (nEnergies - 1) * self.energyOverhead
        if estimatedTime < 100.:
            self.ui.estimatedTime.setText(str(np.round(estimatedTime, 2)) + ' s')
        elif estimatedTime < 3600.:
            self.ui.estimatedTime.setText(str(np.round(estimatedTime / 60., 2)) + ' m')
        else:
            self.ui.estimatedTime.setText(str(np.round(estimatedTime / 3600., 2)) + ' hr')
        try:
            velocityList = []
            for region in self.scan["scan_regions"].keys():
                velocityList.append(self.scan["scan_regions"][region]["xStep"] / self.scan["energy_regions"]["EnergyRegion1"]["dwell"])
            self.velocity = max(velocityList)
            self.ui.scanVelocity.setText(str(np.round(self.velocity,2))+" mm/s")
            if self.velocity > self.maxVelocity:
                self.ui.scanVelocity.setStyleSheet(self._movingStyle)
            else:
                self.ui.scanVelocity.setStyleSheet(self._staticStyle)
        except:
            pass

    def scanCheck(self):
        self.compileScan(nowrite=False)
        xMin = self.client.motorInfo[self.scan["x_motor"]]["minScanValue"]
        xMax = self.client.motorInfo[self.scan["x_motor"]]["maxScanValue"]
        yMin = self.client.motorInfo[self.scan["y_motor"]]["minScanValue"]
        yMax = self.client.motorInfo[self.scan["y_motor"]]["maxScanValue"]
        xMaxRange = self.client.motorInfo[self.scan["x_motor"]]["maxValue"] - self.client.motorInfo[self.scan["x_motor"]]["minValue"]
        yMaxRange = self.client.motorInfo[self.scan["y_motor"]]["maxValue"] - self.client.motorInfo[self.scan["y_motor"]]["minValue"]
        nRegions = len(self.scan["scan_regions"].keys())
        if self.ui.energyListCheckbox.isChecked():
            energyListStr = self.ui.energyListEdit.toPlainText()
            try:
                self.scan["energy_list"] = [float(x) for x in energyListStr.split(',')]
                #get the dwell from the first energy def
                self.scan["dwell"] = self.energyRegDefs[0][-1] #last list item is the dwell time
            except:
                return "Energy List Error"
        for regStr in self.scan["scan_regions"].keys():
            if self.scan["x_motor"] == "Energy":
                xRange = self.scan["energy_regions"]["EnergyRegion1"]["stop"]-self.scan["energy_regions"]["EnergyRegion1"]["start"]
                xStart = self.scan["energy_regions"]["EnergyRegion1"]["start"]
                xStop = self.scan["energy_regions"]["EnergyRegion1"]["stop"]
            else:
                xStart = self.scan["scan_regions"][regStr]["xStart"]
                xStop = self.scan["scan_regions"][regStr]["xStop"]
                xRange = xStop - xStart
            yRange = self.scan["scan_regions"][regStr]["yStop"] - self.scan["scan_regions"][regStr]["yStart"]
            if xStart < xMin:
                return "Scan X is below xMin."
            elif xStop > xMax:
                return "Scan X is above xMax"
            elif self.scan["scan_regions"][regStr]["yStart"] < yMin:
                return "Scan Y is below yMin"
            elif self.scan["scan_regions"][regStr]["yStop"] > yMax:
                return "Scan Y is above yMax"
            elif xRange > xMaxRange:
                if nRegions > 1:
                    return "Tiled scans and multi-region scans are incompatible.  Reduce the size of region %s" %regStr.split("Region")[1]
                #this should force a single region scan since it will be decomposed into several regions
                else:
                    if not self.ui.tiledCheckbox.isChecked():
                        if not self.client.main_config["geometry"]["enable_coarse_only"]:
                            return f"The X scan range of {xRange} exceeds the max range of {xMaxRange}.  Please try a tiled scan."
                        else:
                            self.scan["coarse_only"] = True
                    else:
                        if not self.client.main_config["geometry"]["enable_tiled_scan"]:
                            return f"The X scan range of {xRange} exceeds the max range of {xMaxRange}"
                        else:
                            self.tiled_scan = True
                            self.scan["tiled"] = True
            elif yRange > yMaxRange:
                if nRegions > 1:
                    return "Tiled scans and multi-region scans are incompatible.  Reduce the size of region %s" %regStr.split("Region")[1]
                #this should force a single region scan since it will be decomposed into several regions
                else:
                    if not self.ui.tiledCheckbox.isChecked():
                        if not self.client.main_config["geometry"]["enable_coarse_only"]:
                            return f"The X scan range of {yRange} exceeds the max range of {yMaxRange}.  Please try a tiled scan."
                        else:
                            self.scan["coarse_only"] = True
                    else:
                        if not self.client.main_config["geometry"]["enable_tiled_scan"]:
                            return f"The Y scan range of {yRange} exceeds the max range of {yMaxRange}"
                        else:
                            self.tiled_scan = True
                            self.scan["tiled"] = True
        return

    def warningPopup(self,message):
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Warning)
        msg.setText("Warning!")
        msg.setInformativeText(message)
        msg.setWindowTitle("Warning")
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        msg.setDefaultButton(QtWidgets.QMessageBox.Ok)
        result = msg.exec()
        return result == QtWidgets.QMessageBox.Ok

    def beginScan(self):
        self.tiled_scan = False
        scanCheck = self.scanCheck()
        if scanCheck is None:
            self.scanning = True
            #self.changePlot()
            self.deactivateGUI()
            self.client.scan = self.scan
            message = {"command": "scan"}
            message["scan"] = self.scan
            self.messageQueue.put(message)
        else:
            if not self.warningPopup(scanCheck):
                return
            return

    def errorPopup(self,message):
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Critical)
        msg.setText("Error!")
        msg.setInformativeText(message)
        msg.setWindowTitle("Error")
        msg.exec()

    def joinScan(self):
        self.scanning = False
        self.compileScan('joinScan')
        self.deactivateGUI()
        self.client.scan = self.scan

    def changePlot(self):
        try:
            self.ui.mainPlot.removeItem(self.currentPlot)
            self.currentPlot.clear()
            self.currentPlot.deleteLater()
        except:
            pass
        if self.ui.plotType.currentText() == "Monitor":
            if self.yPlot is not None:
                self.ui.mainPlot.removeItem(self.yPlot)
            if self.xPlot is not None:
                self.ui.mainPlot.removeItem(self.xPlot)
            channel = self.ui.channelSelect.currentText()
            if self.monitorData[channel]["meta"]["type"] == "point":
                self.currentPlot = self.ui.mainPlot.plot(np.array(self.monitorData[channel]["data"]), \
                pen = pg.mkPen('w', width = 1, style = QtCore.Qt.DotLine), symbol='o',symbolPen = 'g', symbolSize=3,\
                                                        symbolBrush=(0,255,0))
            self.ui.mainPlot.setLabel("bottom","Monitor")
        elif self.ui.plotType.currentText() == "Motor Scan":
            nEnergies = self.last_scan["Single Motor"]["energy_regions"]["EnergyRegion1"]["n_energies"]
            if nEnergies > 1:
                motor = "Energy"
            else:
                motor = self.last_scan["Single Motor"]["x_motor"]
            if self.yPlot is not None:
                self.ui.mainPlot.removeItem(self.yPlot)
            if self.xPlot is not None:
                self.ui.mainPlot.removeItem(self.xPlot)
            channel = self.ui.channelSelect.currentText()
            self.currentPlot = self.ui.mainPlot.plot(np.array(self.singleMotorScanXData),np.array(self.singleMotorScanYData[channel]), \
                                                     pen=pg.mkPen('w', width=1, style=QtCore.Qt.DotLine),
                                                     symbol='o', symbolPen='g', symbolSize=3, \
                                                     symbolBrush=(255, 255, 255))
            self.ui.mainPlot.setLabel("bottom",motor)
        elif self.ui.plotType.currentText() == "Sample X":
            self.ui.mainPlot.setLabel("bottom", "Sample X")
        elif self.ui.plotType.currentText() == "Sample Y":
            self.ui.mainPlot.setLabel("bottom", "Sample X")
        elif self.ui.plotType.currentText() == "Sample XY":
            self.ui.mainPlot.setLabel("bottom", "Sample XY")

    def updatePlot(self, message):
        try:
            self.ui.mainPlot.removeItem(self.currentPlot)
            self.currentPlot.clear()
            self.currentPlot.deleteLater()
        except:
            pass
        channel = self.ui.channelSelect.currentText()
        if self.ui.plotType.currentText() == "Monitor":
            if self.monitorData[channel]["meta"]["type"] == "spectrum":
                self.currentPlot = self.ui.mainPlot.plot(self.monitorData[channel]["meta"]["x"],np.squeeze(self.monitorData[channel]["data"]), \
                pen = pg.mkPen('w', width = 1, style = QtCore.Qt.DotLine), symbol='o',symbolPen = 'g', symbolSize=3,\
                                                        symbolBrush=(0,255,0))
                self.ui.mainPlot.setLabel("left", channel)
                self.ui.mainPlot.setLabel("bottom", self.monitorData[channel]["meta"]["x label"])
            else:
            #if self.monitorData[channel]["meta"]["type"] == "point":
                self.currentPlot = self.ui.mainPlot.plot(np.array(self.monitorData[channel]["data"]), \
                pen = pg.mkPen('w', width = 1, style = QtCore.Qt.DotLine), symbol='o',symbolPen = 'g', symbolSize=3,\
                                                        symbolBrush=(0,255,0))
                self.ui.mainPlot.setLabel("left", channel)
                self.ui.mainPlot.setLabel("bottom", "")
            self.ui.daqCurrentValue.setText(str(self.monitorData[self.client.daqConfig["default"]["name"]]["data"][-1]*10.))
        elif self.ui.plotType.currentText() == "Motor Scan":
            self.currentPlot = self.ui.mainPlot.plot(np.array(self.singleMotorScanXData),np.array(self.singleMotorScanYData[channel]), \
                pen = pg.mkPen('w', width = 1, style = QtCore.Qt.DotLine), symbol='o',symbolPen = 'g', symbolSize=3,\
                                                     symbolBrush=(255,255,255))
            self.ui.mainPlot.setLabel("left", channel)
        
    def setChannel(self):
        xScale, yScale = 1., 1.
        if self.ui.channelSelect.currentText() == "CCD":
            xScale, yScale = 1., 1.
            self.hideROIs()
            self.ui.mainImage.setImage(self.currentCCDData, autoRange=True, autoLevels=True, \
                    autoHistogramRange=True)
            self.ui.showRangeFinder.setCheckState(QtCore.Qt.Unchecked)
            self.ui.showRangeFinder.setEnabled(False)
            self.ui.roiCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.roiCheckbox.setEnabled(False)
            self.ui.showBeamPosition.setCheckState(QtCore.Qt.Unchecked)
            self.ui.showBeamPosition.setEnabled(False)
            if self.horizontalLine is not None:
                self.ui.mainImage.removeItem(self.horizontalLine)
            if self.verticalLine is not None:
                self.ui.mainImage.removeItem(self.verticalLine)
        elif self.ui.channelSelect.currentText() == self.client.daqConfig["default"]["name"]:
            xScale,yScale = self.imageScale
            if self.image is None:
                self.image = np.zeros((100,100))
            self.ui.mainImage.setImage(self.image.T, autoRange=True, autoLevels=True, \
                    autoHistogramRange=True, pos = self.imageCenter, scale = self.imageScale)
            self.ui.showRangeFinder.setEnabled(True)
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.showBeamPosition.setEnabled(True)
            self.ui.roiCheckbox.setCheckState(QtCore.Qt.Checked)
        elif self.ui.channelSelect.currentText() == "RPI":
            xScale = self.ptychoXpixm * 1e6
            yScale = self.ptychoYpixm * 1e6
            pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
            self.ui.mainImage.setImage(self.currentRPIData, autoRange=True, autoLevels=True, \
                   autoHistogramRange=True, pos=pos, scale=(xScale,yScale))
            self.ui.showRangeFinder.setEnabled(True)
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.showBeamPosition.setEnabled(True)
        self.scaleBarLength = np.round(100. / self.ui.mainImage.imageItem.pixelSize()[0] * xScale, 3)

    def updateImageFromCCD(self, ccdData):
        self.currentCCDData = ccdData
        if self.ui.channelSelect.currentText() == "CCD":
            self.ui.mainImage.setImage(self.currentCCDData, autoRange=self.ui.autorangeCheckbox.isChecked(),
                                               autoLevels=self.ui.autoscaleCheckbox.isChecked(), \
                                               autoHistogramRange=self.ui.autorangeCheckbox.isChecked(), pos=(0,0),
                                               scale=(1,1))
                        
    def updateImageFromRPI(self, rpiData):
        self.currentRPIData, self.ptychoXpixm, self.ptychoYpixm = rpiData
        if self.ui.channelSelect.currentText() == "RPI":
            self.ui.mainImage.setImage(self.currentRPIData, autoRange=False, autoLevels=False, \
                        autoHistogramRange=False)
          
    def updateImageFromMessage(self, message):
        try:
            self.currentMotorPositions = message['motorPositions']
            self.currentMotorStatus = message["motorPositions"]["status"]
            self.updateMotorPositions()
        except:
            pass
        if message is None:
            pass
        elif message == "scan_complete":
            self.activateGUI()
            self.scanning = False
        elif message["mode"] in self.imageScanTypes:
            self.currentDataDir,self.currentFile = os.path.split(message["scanID"])
            self.stxm.NXfile = message["scanID"]
            elapsedTime = message["elapsedTime"]
            ##if a scan is launched by a script, it needs to be compiled here to generate the correct dataset for viz.
            if message["scanID"].split("/")[-1] not in str(self.ui.scanFileName.text()):
                self.scan = message["scan"]
                self.setGUIfromScan(message["scan"])
                self.compileScan('updateImageFromMessage')
                self.deactivateGUI()
            self.ui.scanFileName.setText(message["scanID"].split("/")[-1])
            if elapsedTime < 100.:
                self.ui.elapsedTime.setText(str(np.round(elapsedTime, 2)) + ' s')
            elif elapsedTime < 3600.:
                self.ui.elapsedTime.setText(str(np.round(elapsedTime / 60., 2)) + ' m')
            else:
                self.ui.elapsedTime.setText(str(np.round(elapsedTime / 3600., 2)) + ' hr')
            scanRegNumber = int(message["scanRegion"].split("Region")[-1]) - 1
            energyIndex = message["energyIndex"]
            nRegions = self.stxm.nScanRegions
            nEnergies = self.stxm.energies["default"].size
            imageCountStr = "Region %i of %i | Energy %i of %i" %(scanRegNumber+1, nRegions, energyIndex+1,nEnergies)
            self.ui.imageCountText.setText(imageCountStr)
            self.yPts, self.xPts, self.zPts = self.scan["scan_regions"][message["scanRegion"]]["yPoints"], \
                        self.scan["scan_regions"][message["scanRegion"]]["xPoints"], \
                        self.scan["scan_regions"][message["scanRegion"]]["zPoints"]

            self.currentImageType = message["type"]
            self.currentEnergyIndex = message["energyIndex"]
            self.currentScanRegionIndex = scanRegNumber
            self.image = message["image"]["default"]

            # xCenters,yCenters = [],[]
            # for region in self.scan["scan_regions"].keys():
            #     xCenters.append(self.scan["scan_regions"][region]["xCenter"])
            #     yCenters.append(self.scan["scan_regions"][region]["xCenter"])
            # self.xCenter = (max(xCenters)+min(xCenters))/2.
            # self.yCenter = (max(yCenters)+min(yCenters))/2.

            self.xCenter = self.scan["scan_regions"][message["scanRegion"]]["xCenter"]
            self.yCenter = -self.scan["scan_regions"][message["scanRegion"]]["yCenter"]
            self.zCenter = self.scan["scan_regions"][message["scanRegion"]]["zCenter"]
            self.xRange = self.scan["scan_regions"][message["scanRegion"]]["xRange"]
            self.yRange = self.scan["scan_regions"][message["scanRegion"]]["yRange"]
            self.zRange = self.scan["scan_regions"][message["scanRegion"]]["zRange"]

            xMin = min([self.scan["scan_regions"][region]["xStart"] for region in self.scan["scan_regions"].keys()])
            xMax = max([self.scan["scan_regions"][region]["xStop"] for region in self.scan["scan_regions"].keys()])
            self.xGlobalCenter = (xMin + xMax) / 2.
            self.xGlobalRange = xMax - xMin
            yMin = min([self.scan["scan_regions"][region]["yStart"] for region in self.scan["scan_regions"].keys()])
            yMax = max([self.scan["scan_regions"][region]["yStop"] for region in self.scan["scan_regions"].keys()])
            self.yGlobalCenter = -(yMin + yMax) / 2.
            self.yGlobalRange = yMax - yMin

            self.energy = self.stxm.energies["default"][self.currentEnergyIndex]
            self.dwell = self.stxm.dwells[self.currentEnergyIndex]
            self.xStep = self.xRange / self.xPts
            pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
            if "Focus" in self.scan["scan_type"]:
                self.stxm.interp_counts["default"][scanRegNumber][message["energyIndex"],:,:] = message["image"]["default"]
                xScale = 1 
                yScale = 1 
            elif "Line Spectrum" in self.scan["scan_type"]:
                self.image = self.image.T
                for daq in self.scan["daq list"]:
                    self.stxm.interp_counts[daq][scanRegNumber][:,0,:] = message["image"][daq]
                xScale = 1 
                yScale = 1 
            elif "Image" in self.scan["scan_type"]:
                for daq in self.scan["daq list"]:
                    try:
                        self.stxm.interp_counts[daq][scanRegNumber][message["energyIndex"]] = message["image"][daq]
                    except KeyError:
                        pass
                xScale = float(self.xRange) / float(self.xPts)
                yScale = float(self.yRange) / float(self.yPts)
            else:
                xScale,yScale = 1,1

            self.currentImageType = self.scan["scan_type"]
            self.imageCenter = pos
            self.imageScale = xScale,yScale
            if self.ui.compositeImageCheckbox.isChecked():
                imageID = self.currentFile + ':' + message["scanRegion"]
                if imageID in self.images.keys():
                    self.images[imageID].setImage(self.image.T)
                else:
                    img = pg.ImageItem()
                    tr = QtGui.QTransform()
                    tr.scale(self.imageScale[0], self.imageScale[1])
                    tr.translate(self.imageCenter[0] / self.imageScale[0], self.imageCenter[1] / self.imageScale[1])
                    img.setTransform(tr)
                    self.images[imageID] = img
                    self.images[imageID].setImage(self.image.T)
                    self.ui.mainImage.addItem(self.images[imageID])
            else:
                self.ui.mainImage.setImage(self.image.T, autoRange=self.ui.autorangeCheckbox.isChecked(), autoLevels=self.ui.autoscaleCheckbox.isChecked(), \
                                            autoHistogramRange=self.ui.autorangeCheckbox.isChecked(), pos=pos, scale=(xScale, yScale))
            self.updateImageLabels()
            self.scaleBarLength = np.round(100. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0],3)
            if self.scaleBarLength < 1.:
                self.ui.scaleBarLength.setText(str(self.scaleBarLength * 1000.) + " nm")
            else:
                self.ui.scaleBarLength.setText(str(self.scaleBarLength) + " um")

            #call the recv data function in the analysis widgets
            #this really should be a signal.emit call but this hasn't worked yet
            if "Image" in self.scanType:
                self.ui.stack_viewer.recv_live_data(self.stxm, message)
            try:
                if "Image" in self.scanType:
                    self.ui.stack_viewer.recv_live_data(self.stxm, message)
                elif self.scanType == "Line Spectrum":
                    pass
                else:
                    pass
            except:
                pass
            if message["mode"] == 'point':
                self.ui.scanFileName.setText(message["scanID"].split("/")[-1])
                if self.scan["scan_type"] == "Single Motor":
                    for daq in message["rawData"].keys():
                        channel = self.client.daqConfig[daq]["name"]
                        if channel not in self.singleMotorScanYData.keys():
                            self.singleMotorScanYData[channel] = []
                        ydata = message["rawData"][daq]["data"][0]
                        self.singleMotorScanYData[channel].append(ydata)
                    xdata = message["scanMotorVal"]
                    self.singleMotorScanXData.append(xdata)
                    self.ui.plotType.setCurrentText("Motor Scan")
                    self.updatePlot(message)
                elif self.scan["scan_type"] == "Double Motor":
                    self.image = message["image"]["default"]
                    xScale = float(self.xRange) / float(self.xPts)
                    yScale = float(self.yRange) / float(self.yPts)
                    pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
                    self.imageCenter = pos
                    self.imageScale = xScale, yScale
                    self.ui.mainImage.setImage(self.image.T, autoRange=self.ui.autorangeCheckbox.isChecked(),
                                               autoLevels=self.ui.autoscaleCheckbox.isChecked(), \
                                               autoHistogramRange=self.ui.autorangeCheckbox.isChecked(), pos=pos,
                                               scale=(xScale, yScale))
                    self.updateImageLabels()
                    self.scaleBarLength = np.round(
                        100. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0], 3)
                    if self.scaleBarLength < 1.:
                        self.ui.scaleBarLength.setText(str(self.scaleBarLength * 1000.) + " nm")
                    else:
                        self.ui.scaleBarLength.setText(str(self.scaleBarLength) + " um")
                elif message["scan"]["driver"] == "osa_focus_scan":
                    self.image = message["image"]
                    xScale = 1. #float(self.xRange) / float(self.xPts)
                    yScale = 1. #float(self.zRange) / float(self.zPts)
                    pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
                    self.imageCenter = pos
                    self.imageScale = xScale, yScale
                    self.ui.mainImage.setImage(self.image.T, autoRange=self.ui.autorangeCheckbox.isChecked(),
                                               autoLevels=self.ui.autoscaleCheckbox.isChecked(), \
                                               autoHistogramRange=self.ui.autorangeCheckbox.isChecked(), pos=pos,
                                               scale=(xScale, yScale))
                    self.updateImageLabels()
                    self.scaleBarLength = np.round(
                        100. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0], 3)
                    if self.scaleBarLength < 1.:
                        self.ui.scaleBarLength.setText(str(self.scaleBarLength * 1000.) + " nm")
                    else:
                        self.ui.scaleBarLength.setText(str(self.scaleBarLength) + " um")

        elif message["type"] == "monitor":
            self.zonePlateCalibration = message['zonePlateCalibration']
            self.zonePlateOffset = message['zonePlateOffset']
            for daq in message["rawData"].keys():
                channel = self.client.daqConfig[daq]["name"]
                if channel not in self.monitorData.keys():
                    self.monitorData[channel] = {"data": [], "meta": None}
                if daq == "default":
                    self.monitorData[channel]["data"].append(message["rawData"][daq]["data"][0])
                    if len(self.monitorData[channel]["data"]) == self.monitorNPoints:
                        self.monitorData[channel]["data"] = self.monitorData[channel]["data"][1:]
                elif daq == "CCD":
                    data = message["rawData"][daq]["data"] 
                    data = ((data > 10.) * data).sum()
                    self.monitorData[channel]["data"].append(data)
                    if len(self.monitorData[channel]["data"]) == self.monitorNPoints:
                        self.monitorData[channel]["data"] = self.monitorData[channel]["data"][1:]                   
                else:
                    self.monitorData[channel]["data"] = message["rawData"][daq]["data"]
                self.monitorData[channel]["meta"] = message["rawData"][daq]["meta"]

            self.updatePlot(message)
        try:
            self.updateImageFromCCD(message["rawData"]["CCD"]["data"])
        except:
            pass
        xPos = self.currentMotorPositions["SampleX"]
        yPos = self.currentMotorPositions["SampleY"]
        size = 10. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0]
        if self.image is None:
            size = size / 8. * self.imageScale[0]
        if (self.beamPosition is not None):# and self.ui.showBeamPosition.isChecked():
            self.ui.mainImage.removeItem(self.beamPosition)
        if self.ui.showBeamPosition.isChecked():
            roiPen = pg.mkPen((0, 255, 255), width=2, style=self.penStyles[0])
            self.beamPosition = pg.RectROI((xPos - size / 2., yPos - size / 2), (size,size), \
                                        snapSize=0.0, pen=roiPen, movable=False, rotatable=False,
                                        resizable=False)
            self.beamPosition.setPos((xPos - size / 2., yPos - size / 2))
            self.beamPosition.setSize(size)
            self.ui.mainImage.addItem(self.beamPosition)
            self.beamPosition.removeHandle(self.beamPosition.getHandles()[0])

    def setMotorLabel(self,label,text,status):
        if status:
            label.setStyleSheet(self._movingStyle)
        else:
            label.setStyleSheet(self._staticStyle)
        label.setText(text)

    def updateMotorPositions(self):

        status = self.currentMotorStatus["Energy"]
        self.setMotorLabel(self.ui.energyLabel,str(np.round(self.currentMotorPositions["Energy"],1)), status)
        self.setMotorLabel(self.ui.energyLabel_2, str(np.round(self.currentMotorPositions["Energy"], 1)), status)
        Motor1 = str(self.ui.motorMover1.currentText())
        Motor2 = str(self.ui.motorMover2.currentText())
        status = self.currentMotorStatus[Motor1]
        self.setMotorLabel(self.ui.motorMover1Pos,str(np.round(self.currentMotorPositions[Motor1],3)),status)
        status = self.currentMotorStatus[Motor2]
        self.setMotorLabel(self.ui.motorMover2Pos,str(np.round(self.currentMotorPositions[Motor2],3)), status)
        status = self.currentMotorStatus["DISPERSIVE_SLIT"]
        self.setMotorLabel(self.ui.dsLabel,str(np.round(self.currentMotorPositions["DISPERSIVE_SLIT"], 1)),status)
        status = self.currentMotorStatus["NONDISPERSIVE_SLIT"]
        self.setMotorLabel(self.ui.ndsLabel,str(np.round(self.currentMotorPositions["NONDISPERSIVE_SLIT"], 1)),status)
        self.setMotorLabel(self.ui.A0Label,str(int(self.client.motorInfo["Energy"]["A0"])),False)
        self.setMotorLabel(self.ui.A1Label,str(round(self.client.motorInfo["Energy"]["A1"],4)),False)
        try:
            status = self.currentMotorStatus["POLARIZATION"]
            self.setMotorLabel(self.ui.polLabel,str(np.round(self.currentMotorPositions["POLARIZATION"], 2)),status)
            status = self.currentMotorStatus["M101PITCH"]
            self.setMotorLabel(self.ui.m101Label,str(np.round(self.currentMotorPositions["M101PITCH"], 2)),status)
            status = self.currentMotorStatus["FBKOFFSET"]
            self.setMotorLabel(self.ui.fbkLabel,str(np.round(self.currentMotorPositions["FBKOFFSET"], 2)),status)
            status = self.currentMotorStatus["EPUOFFSET"]
            self.setMotorLabel(self.ui.epuLabel,str(np.round(self.currentMotorPositions["EPUOFFSET"], 2)),status)
            self.ui.harSpin.setValue(int(self.currentMotorPositions["HARMONIC"]))
        except:
            pass

    def getScanFile(self):
        self.currentLoadFile = str(QtWidgets.QFileDialog.getOpenFileName(QtWidgets.QWidget(), \
            'Open File', self.currentDataDir, 'NXstxm (*.stxm)')[0])
        if self.currentLoadFile != '':
            try:
                self.loadScan()
            except IOError:
                print("No Such File or Directory.")

    def loadScan(self, fileName = None):
        try:
            self.nx = stxm(stxm_file = self.currentLoadFile)
        except:
            return
        else:
            if "Image" in self.nx.meta["scan_type"] or self.nx.meta["scan_type"] == "Double Motor":
                self.ui.scanFileName.setText(self.currentLoadFile.split('/')[-1])
                self.image = self.nx.data["entry0"]["counts"]
                self.currentImageType = self.nx.meta["scan_type"]
                ne,y,x = self.image.shape
                self.yPts,self.xPts = y,x
                self.image = np.reshape(self.image, (y,x))
                axes = (1,0)
                xpos = self.nx.data['entry0']['xpos']
                ypos = self.nx.data['entry0']['ypos']
                self.xRange = xpos.max()-xpos.min()
                self.xPts = xpos.size
                self.xCenter = xpos.min() + self.xRange / 2.
                self.yRange = ypos.max()-ypos.min()
                self.yPts = ypos.size
                self.yCenter = -(ypos.min() + self.yRange / 2.)
                xScale = float(self.xRange) / float(self.xPts)
                yScale = float(self.yRange) / float(self.yPts)
                pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
                self.imageCenter = pos
                self.imageScale = xScale,yScale
                self.ui.mainImage.setImage(np.transpose(self.image, axes = axes), autoRange=False, autoLevels=True, \
                    autoHistogramRange=True, pos = self.imageCenter, scale = self.imageScale)
                self.scaleBarLength = np.round(
                    100. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0], 3)
                if self.scaleBarLength < 1.:
                    self.ui.scaleBarLength.setText(str(self.scaleBarLength * 1000.) + " nm")
                else:
                    self.ui.scaleBarLength.setText(str(self.scaleBarLength) + " um")
                self.ui.scanType.setCurrentIndex(0)
            elif self.nx.meta["scan_type"]=="Single Motor":
                self.ui.scanFileName.setText(self.currentLoadFile.split('/')[-1])
                self.ui.plotType.setCurrentText("Motor Scan")
                motor = self.nx.meta["x_motor"]
                ne, ny, nx = self.nx.data["entry0"]["counts"].shape
                if motor == "Energy":
                    self.singleMotorScanXData = self.nx.data["entry0"]["energy"]
                    self.singleMotorScanYData = np.reshape(self.nx.data["entry0"]["counts"], (ne))
                else:
                    self.singleMotorScanXData = self.nx.data["entry0"]["xpos"]
                    self.singleMotorScanYData = np.reshape(self.nx.data["entry0"]["counts"], (nx))
                if self.yPlot is not None:
                    self.ui.mainPlot.removeItem(self.yPlot)
                if self.xPlot is not None:
                    self.ui.mainPlot.removeItem(self.xPlot)
                self.currentPlot = self.ui.mainPlot.plot(np.array(self.singleMotorScanXData),
                                                         np.array(self.singleMotorScanYData), \
                                                         pen=pg.mkPen('w', width=1, style=QtCore.Qt.DotLine),
                                                         symbol='o', symbolPen='g', symbolSize=3, \
                                                         symbolBrush=(255, 255, 255))
                self.ui.mainPlot.setLabel("bottom", motor)
            self.scanFromNX()

    def scanFromNX(self):
        data = self.nx.data["entry0"]["counts"]
        z,y,x = data.shape
        self.dwell = self.nx.data["entry0"]["dwell"][0]
        self.energy = self.nx.data["entry0"]["energy"][0]
        self.xRange = self.nx.data["entry0"]["xpos"].max() - self.nx.data["entry0"]["xpos"].min()
        self.yRange = self.nx.data["entry0"]["ypos"].max() - self.nx.data["entry0"]["ypos"].min()
        self.xCenter = self.nx.data["entry0"]["xpos"].min() + self.xRange / 2.
        self.yCenter = self.nx.data["entry0"]["ypos"].min() + self.yRange / 2.
        self.xStep = self.xRange / x
        self.yStep = self.yRange / y
        if self.nx.meta["scan_type"] in ["Image","Spiral Image","Double Motor","Ptychography Image"]:
            xScale = float(self.xRange) / float(x)
            yScale = float(self.yRange) / float(y)
            pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
            self.imageCenter = pos
            self.imageScale = xScale,yScale
            nScanRegions = len(self.nx.data.keys())
            self.ui.scanRegSpinbox.setValue(nScanRegions)
            for i in range(nScanRegions):
                self.dwell = self.nx.data["entry"+str(i)]["dwell"][0]
                self.energy = self.nx.data["entry"+str(i)]["energy"][0]
                self.xRange = round(self.nx.data["entry"+str(i)]["xpos"].max() - self.nx.data["entry"+str(i)]["xpos"].min(),3)
                self.yRange = round(self.nx.data["entry"+str(i)]["ypos"].max() - self.nx.data["entry"+str(i)]["ypos"].min(),3)
                self.xCenter = self.nx.data["entry"+str(i)]["xpos"].min() + self.xRange / 2.
                self.yCenter = self.nx.data["entry"+str(i)]["ypos"].min() + self.yRange / 2.
                self.xStep = self.xRange / x
                self.yStep = self.yRange / y
                self.scanRegList[i].ui.xCenter.setText(str(np.round(self.xCenter, 3)))
                self.scanRegList[i].ui.yCenter.setText(str(np.round(self.yCenter, 3)))
                self.scanRegList[i].ui.xRange.setText(str(np.round(self.xRange, 3)))
                self.scanRegList[i].ui.yRange.setText(str(np.round(self.yRange, 3)))
                self.scanRegList[i].ui.xNPoints.setText(str(x))
                self.scanRegList[i].ui.yNPoints.setText(str(y))
                self.scanRegList[i].ui.xStep.setText(str(np.round(self.xStep,3)))
                self.scanRegList[i].ui.yStep.setText(str(np.round(self.yStep,3)))
                self.regDefs[i][0] = np.round(self.xCenter, 3)
                self.regDefs[i][1] = np.round(self.yCenter, 3)
                self.regDefs[i][2] = np.round(self.xRange, 3)
                self.regDefs[i][3] = np.round(self.yRange, 3)
                self.regDefs[i][4] = x
                self.regDefs[i][5] = y
                self.regDefs[i][6] = self.xStep
                self.regDefs[i][7] = self.yStep
                self.updateROIfromRegion(i+1)
            self.compileScan()
            self.last_scan["Image"] = self.scan
            self.stxm.energies = self.nx.data["entry0"]["energy"]
            self.updateImageLabels()

    def updateImageLabels(self):
        self.ui.pixelSizeLabel.setText(str(np.round(self.xStep,3)) + " um")
        self.ui.dwellTimeLabel.setText(str(self.dwell) + " ms")
        self.ui.imageEnergyLabel.setText(str(self.energy) + " eV")

    def updateTimeIndex(self):
        energyIndex = self.ui.mainImage.currentIndex
        self.energy = self.stxm.energies["default"][energyIndex]
        self.updateImageLabels()

    def setGUIfromScan(self, scan, energyOnly = False):
        nScanRegions = len(scan["scan_regions"])
        nEnergyRegions = len(scan["energy_regions"])
        self.ui.energyRegSpinbox.setValue(nEnergyRegions)
        self.updateEnergyRegDef()
        for i in range(nEnergyRegions):
            self.energyRegList[i].energyDef.energyStart.setText(str(scan["energy_regions"]["EnergyRegion" + str(i+1)]["start"]))
            self.energyRegList[i].energyDef.energyStop.setText(str(scan["energy_regions"]["EnergyRegion" + str(i+1)]["stop"]))
            self.energyRegList[i].energyDef.energyStep.setText(str(scan["energy_regions"]["EnergyRegion" + str(i+1)]["step"]))
            self.energyRegList[i].energyDef.nEnergies.setText(str(scan["energy_regions"]["EnergyRegion" + str(i+1)]["n_energies"]))
            self.energyRegList[i].energyDef.dwellTime.setText(str(scan["energy_regions"]["EnergyRegion" + str(i+1)]["dwell"]))
        if not(energyOnly):
            nScanRegions = len(scan["scan_regions"].keys())
            self.ui.scanRegSpinbox.setValue(nScanRegions)
            for i in range(nScanRegions):
                #without this sleep statement there's some race condition that causes the lines below to fail....
                #seems like the scanRegList is not fully formed yet somehow
                self.xRange = scan["scan_regions"]["Region" + str(i+1)]["xRange"]
                self.yRange = scan["scan_regions"]["Region" + str(i+1)]["yRange"]
                self.xCenter = scan["scan_regions"]["Region" + str(i+1)]["xCenter"]
                self.yCenter = scan["scan_regions"]["Region" + str(i+1)]["yCenter"]
                self.xStep = scan["scan_regions"]["Region" + str(i+1)]["xStep"]
                self.yStep = scan["scan_regions"]["Region" + str(i+1)]["yStep"]
                self.scanRegList[i].ui.xCenter.setText(str(np.round(self.xCenter, 3)))
                self.scanRegList[i].ui.yCenter.setText(str(np.round(self.yCenter, 3)))
                self.scanRegList[i].ui.xRange.setText(str(np.round(self.xRange, 3)))
                self.scanRegList[i].ui.yRange.setText(str(np.round(self.yRange, 3)))
                self.scanRegList[i].ui.xNPoints.setText(str(scan["scan_regions"]["Region" + str(i+1)]["xPoints"]))
                self.scanRegList[i].ui.yNPoints.setText(str(scan["scan_regions"]["Region" + str(i+1)]["yPoints"]))
                self.scanRegList[i].ui.xStep.setText(str(self.xStep))
                self.scanRegList[i].ui.yStep.setText(str(self.yStep))
                self.regDefs[i][0] = np.round(self.xCenter, 3)
                self.regDefs[i][1] = np.round(self.yCenter, 3)
                self.regDefs[i][2] = np.round(self.xRange, 3)
                self.regDefs[i][3] = np.round(self.yRange, 3)
                self.regDefs[i][4] = scan["scan_regions"]["Region" + str(i+1)]["xPoints"]
                self.regDefs[i][5] = scan["scan_regions"]["Region" + str(i+1)]["yPoints"]
                self.regDefs[i][6] = self.xStep
                self.regDefs[i][7] = self.yStep
                self.updateROIfromRegion(i + 1)
        self.compileScan()
        self.last_scan[self.scan["scan_type"]] = self.scan

    def addROI(self, range = (70, 70), center = (35, 35)):
        scanType = self.client.scanConfig["scans"][self.ui.scanType.currentText()]["type"]
        nROI = len(self.roiList) + 1
        colorIndex = nROI % len(self.penColors) - 1
        styleIndex = int((nROI / len(self.penColors)) % 2)
        roiPen = pg.mkPen(self.penColors[colorIndex],\
           width = 3, style = self.penStyles[styleIndex])
        xMin, xMax = float(center[0]) - float(range[0]) / 2, float(center[0]) + float(range[0]) / 2
        yMin, yMax = float(center[1]) - float(range[1]) / 2, float(center[1]) + float(range[1]) / 2
        if scanType == "image":
            roi = pg.RectROI((xMin,yMin), range, snapSize = 5.0, pen = roiPen)
        elif scanType == "line":
            roi = pg.LineSegmentROI(positions = ((xMin,center[1]),(xMax,center[1])), pen = roiPen)
        else:
            return
        roi.sigRegionChanged.connect(self.updateScanRegFromROIdrag)
        self.roiList.append(roi)

    def showROIs(self):
        for roi in self.roiList:
            self.ui.mainImage.addItem(roi)

    def hideROIs(self):
        for roi in self.roiList:
            self.ui.mainImage.removeItem(roi)

    def updateScanRegFromROIdrag(self):
        for roi in self.roiList:
            self.updateScanRegFromROI(roi)

    def updateScanRegFromROI(self, roi):
        scanType = self.client.scanConfig["scans"][self.ui.scanType.currentText()]["type"]
        i = self.roiList.index(roi)
        regStr = 'Region' + str(i + 1)
        xPoints = int(self.scanRegList[i].ui.xNPoints.text()) #self.scan["scan_regions"][regStr]['xPoints']
        yPoints = int(self.scanRegList[i].ui.yNPoints.text()) #self.scan["scan_regions"][regStr]['yPoints']
        self.scanRegList[i].ui.noEmit = True
        if scanType == "image":
            xRange = roi.size()[0]
            yRange = roi.size()[1]
            xCenter = roi.pos()[0] + xRange / 2.
            yCenter = roi.pos()[1] + yRange / 2.
            newXStep = np.round(xRange / xPoints,3)
            newYStep = np.round(yRange / yPoints,3)
            self.scanRegList[i].ui.xRange.setText(str(np.round(xRange, 3)))
            self.scanRegList[i].ui.yRange.setText(str(np.round(yRange, 3)))
            self.scanRegList[i].ui.xStep.setText(str(np.round(newXStep, 3)))
            self.scanRegList[i].ui.yStep.setText(str(np.round(newYStep, 3)))
            self.regDefs[i][2] = np.round(xRange, 3)
            self.regDefs[i][3] = np.round(yRange, 3)
            self.regDefs[i][6] = newXStep
            self.regDefs[i][7] = newYStep
        elif scanType == "line":
            x0 = roi.mapSceneToParent(roi.getHandles()[0].scenePos()).x()
            x1 = roi.mapSceneToParent(roi.getHandles()[1].scenePos()).x()
            y0 = roi.mapSceneToParent(roi.getHandles()[0].scenePos()).y()
            y1 = roi.mapSceneToParent(roi.getHandles()[1].scenePos()).y()
            self.xLineRange = np.abs(x1 - x0)
            self.yLineRange = np.abs(y1 - y0)
            xCenter = np.min((x0,x1)) + self.xLineRange / 2.
            yCenter = np.min((y0,y1)) + self.yLineRange / 2.
            length = np.sqrt((x1-x0)**2+(y1-y0)**2)
            if length > 75:
                self.ui.lineLengthEdit.setText(str(70))
                self.ui.lineLengthEdit.returnPressed.emit()
                return
            try:
                if y0 > y1:
                    sign = -1
                else:
                    sign = 1
                self.lineAngle = sign * np.round(90.-np.abs(180.*np.arctan((x1-x0)/(y1-y0))/np.pi),1)
            except:
                pass
            self.ui.lineAngleEdit.setText(str(self.lineAngle))
            self.ui.lineLengthEdit.setText(str(np.round(length,3)))

        self.scanRegList[i].ui.xCenter.setText(str(np.round(xCenter,3)))
        self.scanRegList[i].ui.yCenter.setText(str(np.round(-yCenter,3)))
        self.regDefs[i][0] = np.round(xCenter, 3)
        self.regDefs[i][1] = np.round(yCenter, 3)
        self.scanRegList[i].ui.noEmit = False

    def addEnergyReg(self, regNum = None):
        if regNum == None:
            regNum = 0
        b = energyDefWidget()
        b.energyDef.energyStart.setText(str(self.energyRegDefs[regNum][0]))
        b.energyDef.energyStop.setText(str(self.energyRegDefs[regNum][1]))
        b.energyDef.energyStep.setText(str(self.energyRegDefs[regNum][2]))
        b.energyDef.nEnergies.setText(str(self.energyRegDefs[regNum][3]))
        b.energyDef.dwellTime.setText(str(self.energyRegDefs[regNum][4]))
        if regNum is None:
            regNum = str(self.ui.energyRegSpinbox.value())
        b.energyDef.regNum.setText("Region " + str(regNum+1))
        b.regionChanged.connect(self.updateEstimatedTime)
        if self.ui.energyRegSpinbox.value() > 1:
            b.setMultiEnergy()
        self.ui.energyDefWidget.addWidget(b.widget)
        self.energyRegList.append(b)
        self.nEnergyRegion += 1
        
    def updateRegionDefList(self):
        for i in range(len(self.scanRegList)):
            self.regDefs[i][0] = float(self.scanRegList[i].ui.xCenter.text())
            self.regDefs[i][1] = -float(self.scanRegList[i].ui.yCenter.text())
            self.regDefs[i][2] = float(self.scanRegList[i].ui.xRange.text())
            self.regDefs[i][3] = float(self.scanRegList[i].ui.yRange.text())
            self.regDefs[i][4] = int(self.scanRegList[i].ui.xNPoints.text())
            self.regDefs[i][5] = int(self.scanRegList[i].ui.yNPoints.text())
            self.regDefs[i][6] = float(self.scanRegList[i].ui.xStep.text())
            self.regDefs[i][7] = float(self.scanRegList[i].ui.yStep.text())
            
                ##update the region list first
        for i in range(len(self.energyRegList)):
            self.energyRegDefs[i][0] = float(self.energyRegList[i].energyDef.energyStart.text())
            self.energyRegDefs[i][1] = float(self.energyRegList[i].energyDef.energyStop.text())
            self.energyRegDefs[i][2] = float(self.energyRegList[i].energyDef.energyStep.text())
            self.energyRegDefs[i][3] = int(self.energyRegList[i].energyDef.nEnergies.text())
            self.energyRegDefs[i][4] = float(self.energyRegList[i].energyDef.dwellTime.text())

    @QtCore.Slot(np.intc)
    def updateROIfromRegion(self, regNum):
        self.updateRegionDefList()
        scanType = self.client.scanConfig["scans"][self.ui.scanType.currentText()]["type"]
        a = self.scanRegList[regNum - 1]
        xRange = float(a.ui.xRange.text())
        yRange = float(a.ui.yRange.text())
        xCenter = float(a.ui.xCenter.text())
        yCenter = -float(a.ui.yCenter.text())
        i = regNum - 1
        if scanType == "image":
            self.roiList[i].setPos((xCenter - xRange / 2.,yCenter - yRange / 2.))
            self.roiList[i].setSize((xRange,yRange))
            self.regDefs[i][0] = np.round(xCenter, 3)
            self.regDefs[i][1] = np.round(yCenter, 3)
            self.regDefs[i][2] = np.round(xRange, 3)
            self.regDefs[i][3] = np.round(yRange, 3)
            self.regDefs[i][6] = float(a.ui.xStep.text())
            self.regDefs[i][7] = float(a.ui.yStep.text())
            self.regDefs[i][4] = int(a.ui.xNPoints.text())
            self.regDefs[i][5] = int(a.ui.yNPoints.text())
        elif scanType == "line":
            roi = self.roiList[regNum - 1]
            length = float(str(self.ui.lineLengthEdit.text()))
            angle = float(str(self.ui.lineAngleEdit.text()))
            xRange = length * np.cos(np.pi * angle / 180.)
            yRange = abs(length * np.sin(np.pi * angle / 180.))

            nROI = len(self.roiList)
            colorIndex = nROI % len(self.penColors)-1
            styleIndex = int((nROI / len(self.penColors)) % 2)
            roiPen = pg.mkPen(self.penColors[colorIndex], \
                              width=3, style=self.penStyles[styleIndex])

            x0 = roi.mapSceneToParent(roi.getHandles()[0].scenePos()).x()
            x1 = roi.mapSceneToParent(roi.getHandles()[1].scenePos()).x()
            y0 = roi.mapSceneToParent(roi.getHandles()[0].scenePos()).y()
            y1 = roi.mapSceneToParent(roi.getHandles()[1].scenePos()).y()

            if x0 < x1:
                x0,x1 = xCenter - xRange / 2, xCenter + xRange / 2
            else:
                x1,x0 = xCenter - xRange / 2, xCenter + xRange / 2
            if np.sign(angle) == -1:
                y0,y1 = yCenter - yRange / 2, yCenter + yRange / 2
            else:
                y1,y0 = yCenter - yRange / 2, yCenter + yRange / 2
            roi = pg.LineSegmentROI(
                positions=((x0,y0), (x1,y1)), pen=roiPen)
            roi.sigRegionChanged.connect(self.updateScanRegFromROIdrag)

            self.xLineRange = np.abs(x1 - x0)
            self.yLineRange = np.abs(y1 - y0)

            self.hideROIs()
            self.roiList[regNum-1] = roi
            self.showROIs()
        self.updateEstimatedTime()

    def addScanReg(self, regNum = 0):
        a = scanRegionDef()
        a.ui.xCenter.setText(str(self.regDefs[regNum][0]))
        a.ui.yCenter.setText(str(self.regDefs[regNum][1]))
        a.ui.xRange.setText(str(self.regDefs[regNum][2]))
        a.ui.yRange.setText(str(self.regDefs[regNum][3]))
        a.ui.xNPoints.setText(str(self.regDefs[regNum][4]))
        a.ui.yNPoints.setText(str(self.regDefs[regNum][5]))
        a.ui.xStep.setText(str(self.regDefs[regNum][6]))
        a.ui.yStep.setText(str(self.regDefs[regNum][7]))
        a.regionChanged.connect(self.updateROIfromRegion)
        a.updateTimeEstimate.connect(self.updateEstimatedTime)
        a.ui.regNum.setText("Region " + str(len(self.scanRegList)+1))
        self.ui.regionDefWidget.addWidget(a.region)
        self.scanRegList.append(a)
        self.nRegion += 1
        xRange = a.ui.xRange.text()
        yRange = a.ui.yRange.text()
        xCenter = float(a.ui.xCenter.text())
        yCenter = -float(a.ui.yCenter.text())
        self.addROI(center = (xCenter,yCenter), range = (xRange,yRange))

    def updateScanRegDef(self):
        displayedWidgets = self.ui.regionDefWidget.widget.layout().count()
        requestedWidgets = self.ui.scanRegSpinbox.value()
        storedWidgets = len(self.scanRegList)
        while self.ui.scanRegSpinbox.value() > len(self.scanRegList):
            self.scanDefs["Region %i" %(storedWidgets+1)] = {}
            self.addScanReg(regNum = len(self.scanRegList))
            storedWidgets = len(self.scanRegList)
        if self.ui.scanRegSpinbox.value() < len(self.scanRegList):
            for i in range(self.ui.scanRegSpinbox.value(),len(self.scanRegList)):
                self.ui.regionDefWidget.removeWidget(self.scanRegList[-1].region)
                self.scanRegList[-1].region.deleteLater()
                self.scanRegList[-1] = None
                del self.scanRegList[-1]
                self.ui.mainImage.removeItem(self.roiList[-1])
                del self.roiList[-1]
                self.nRegion -= 1
        elif requestedWidgets > displayedWidgets:
            for i in range(displayedWidgets,requestedWidgets):
                self.ui.regionDefWidget.addWidget(self.scanRegList[i].region)
        if self.ui.roiCheckbox.isChecked():
            self.hideROIs()
            self.showROIs()
        self.updateEstimatedTime()

    def updateEnergyRegDef(self):
        displayedWidgets = self.ui.energyDefWidget.widget.layout().count()
        requestedWidgets = self.ui.energyRegSpinbox.value()
        storedWidgets = len(self.energyRegList)
        if self.ui.energyRegSpinbox.value() > 1:
            self.ui.toggleSingleEnergy.setCheckState(QtCore.Qt.Unchecked)
            #self.setSingleEnergy()
        while self.ui.energyRegSpinbox.value() > len(self.energyRegList):
            self.energyDefs["EnergyRegion %i" %(storedWidgets+1)] = {}
            self.addEnergyReg(regNum = len(self.energyRegList))
            storedWidgets = len(self.energyRegList)
        if self.ui.energyRegSpinbox.value() < len(self.energyRegList):
            for i in range(self.ui.energyRegSpinbox.value(),len(self.energyRegList)):
                self.ui.energyDefWidget.removeWidget(self.energyRegList[-1].widget)
                self.energyRegList[-1].widget.deleteLater()
                self.energyRegList[-1] = None
                del self.energyRegList[-1]
                self.nEnergyRegion -= 1
        elif requestedWidgets > displayedWidgets:
            for i in range(displayedWidgets,requestedWidgets):
                self.ui.energyDefWidget.addWidget(self.energyRegList[i].widget)

    def setEnergyRegionVals(self):
        if self.ui.energyRegSpinbox.value() == 1:
            self.energyRegList[-1].energyDef.energyStart.setText(str(self.client.motorInfo['Energy']['last value']))
            self.energyRegList[-1].energyDef.energyStop.setText(str(self.client.motorInfo['Energy']['last value']+1.))
            self.energyRegList[-1].energyDef.energyStep.setText(str(1))
            self.energyRegList[-1].energyDef.nEnergies.setText(str(2))
            self.energyRegList[-1].energyDef.dwellTime.setText(str(self.client.motorInfo['Energy']['last dwell time']))

    def setSingleEnergy(self):
        if self.ui.toggleSingleEnergy.isChecked():
            self.ui.energyListCheckbox.setCheckState(QtCore.Qt.Unchecked)
            if len(self.energyRegList) > 0:
                for i in range(1, len(self.energyRegList)):
                    self.ui.energyDefWidget.removeWidget(self.energyRegList[-1].widget)
                    self.energyRegList[-1].widget.deleteLater()
                    self.energyRegList[-1] = None
                    del self.energyRegList[-1]
                self.ui.energyRegSpinbox.setValue(1)
            else:
                self.addEnergyReg()
            self.energyRegList[-1].setSingleEnergy()
            self.energyRegList[0].energyDef.energyStart.setText(str(np.round(self.currentMotorPositions["Energy"],3)))
            self.energyRegList[0].energyDef.energyStop.setText(str(np.round(self.currentMotorPositions["Energy"]+1,3)))
            self.energyRegList[0].energyDef.energyStep.setText(str(1))
        else:
            self.energyRegList[-1].setMultiEnergy()
        self.updateEstimatedTime()

    def connectClient(self):
        self.client.monitor.scan_data.connect(self.updateImageFromMessage)
        self.controlThread.controlResponse.connect(self.printToConsole)
        try:
            self.client.ptycho.ptychoData.connect(self.updateImageFromRPI)
        except:
            print("Cannot connect to PTYCHO monitor")
        self.ui.serverAddress.setText("%s:%s" %(self.client.main_config["server"]["host"],\
                                                str(self.client.main_config["server"]["command_port"])))
        self.serverStatus = self.client.get_status()

    def initGUI(self):
        self.load_config()

        ##set the channels
        self.ui.channelSelect.clear()
        for key in self.client.daqConfig.keys():
            if self.client.daqConfig[key]["record"]:
                daq_name = self.client.daqConfig[key]["name"]
                self.ui.channelSelect.addItem(daq_name)
        self.currentMotorPositions = self.client.currentMotorPositions
        self.ui.scanType.clear()
        for scanType in self.client.scanConfig["scans"].keys():
            if self.client.scanConfig["scans"][scanType]["display"]:
                self.ui.scanType.addItem(scanType)
        self.ui.energyLabel.setText(str(self.currentEnergy) + ' eV')
        self.ui.focusCenterEdit.setText(str(self.currentMotorPositions["ZonePlateZ"]))
        self.nMotors = len(self.client.motorInfo.keys())
        #The motors should be added to the drop down lists in particular locations according to their index
        keys = list(self.client.motorInfo.keys())
        idx = [self.client.motorInfo[key]['index'] for key in keys]
        keys = [keys[i] for i in idx]
        idx.sort()
        self.motorScanParams = {}
        self.ui.motorMover1.clear()
        self.ui.motorMover2.clear()
        self.ui.xMotorCombo.clear()
        self.ui.yMotorCombo.clear()
        for key in keys:
            self.motorScanParams[key] = {}
            if self.client.motorInfo[key]["display"]:
                self.motorScanParams[key]["center"] = (self.client.motorInfo[key]["maxValue"] + self.client.motorInfo[key][
                    "minValue"]) / 2
                self.motorScanParams[key]["range"] = (self.client.motorInfo[key]["maxScanValue"] - self.client.motorInfo[key][
                    "minScanValue"]) / 2
                self.motorScanParams[key]["points"] = 100
        for key in keys:
            if self.client.motorInfo[key]["display"]:
                self.ui.motorMover1.addItem(key)
                self.ui.motorMover2.addItem(key)
                self.ui.xMotorCombo.addItem(key)
                self.ui.yMotorCombo.addItem(key)
        self.ui.motorMover1.setCurrentIndex(self.ui.motorMover1.findText("SampleX"))
        self.ui.motorMover2.setCurrentIndex(self.ui.motorMover2.findText("SampleY"))
        self.ui.xMotorCombo.setCurrentIndex(self.ui.xMotorCombo.findText("SampleX"))
        self.ui.yMotorCombo.setCurrentIndex(self.ui.yMotorCombo.findText("SampleY"))
        self.compileScan()
        xMotor = self.scan["x_motor"]
        yMotor = self.scan["y_motor"]
        xMax = self.client.motorInfo[xMotor]["maxScanValue"]
        xMin = self.client.motorInfo[xMotor]["minScanValue"]
        yMax = self.client.motorInfo[yMotor]["maxScanValue"]
        yMin = self.client.motorInfo[yMotor]["minScanValue"]
        self.xRange = xMax - xMin
        self.scanXrange = xMax - xMin
        self.scanYrange = yMax - yMin
        try:
            self.ui.mainImage.removeItem(self.rangeROI)
        except:
            pass
        roiPen = pg.mkPen((255,255,255),width = 1, style = QtCore.Qt.DashLine)
        self.rangeROI = pg.RectROI((xMin,yMin), (xMax - xMin, yMax - yMin), snapSize = 0.0, pen = roiPen, \
                         rotatable = False, resizable = False, movable = False, removable = False)
        self.ui.mainImage.addItem(self.rangeROI)
        self.rangeROI.removeHandle(self.rangeROI.getHandles()[0])
        self.imageCenter = 0,0
        self.imageScale = 0.1,0.1
        self.scaleBarLength = np.round(100. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0], 3)
        self.updateScanRegDef()
        self.ui.lineLengthEdit.setText(str(self.scanRegList[0].ui.xRange.text()))
        self.updateLine()
        self.setScanParams()
        self.setGUIfromScan(self.last_scan["Image"])
        self.setSingleEnergy()
        self.activateGUI()
        if not self.client.main_config["geometry"]["enable_coarse_only"]:
            #self.ui.tiledCheckbox.setChecked(self.client.main_config["geometry"]["enable_tiled_scan"])
            self.ui.tiledCheckbox.setEnabled(False)
        elif not self.client.main_config["geometry"]["enable_tiled_scan"]:
            self.ui.tiledCheckbox.setChecked(False)
            self.ui.tiledCheckbox.setEnabled(False)
        try:
            #This can fail if there's a problem with the alsapi server or the environment variables aren't set
            from pystxmcontrol.utils.alsapi import getCurrentEsafList
            self.esaf_list, self.participants_list = getCurrentEsafList(beamline = self.client.main_config["source"]["beamline"])
        except:
            #print(traceback.format_exc())
            self.esaf_list = []
        self.ui.proposalComboBox.clear()
        self.ui.proposalComboBox.addItem("Select a Proposal")
        for esaf in self.esaf_list:
            self.ui.proposalComboBox.addItem(esaf)
        self.ui.proposalComboBox.addItem("Staff Access")
        self.deactivateGUI()

        if self.serverStatus["mode"] == "scanning":
            print("server is scanning")
            self.scan = self.serverStatus["data"]
            self.setGUIfromScan(self.scan)
            self.joinScan()

    def updateMotorStatus(self):
        while True:
            print("Updating Motor Status")
            time.sleep(1)

    def updateROIs(self):
        self.hideROIs()
        self.roiList = []
        for reg in self.scanRegList:
            xCenter = float(reg.ui.xCenter.text())
            yCenter = -float(reg.ui.yCenter.text())
            xRange = reg.ui.xRange.text()
            yRange = reg.ui.yRange.text()
            self.addROI(center = (xCenter,yCenter), range = (xRange,yRange))
        if self.ui.roiCheckbox.isChecked():
            self.showROIs()

    def setFocusWidgets(self,value):
        self.ui.focusCenterEdit.setEnabled(value)
        self.ui.focusRangeEdit.setEnabled(value)
        self.ui.focusStepsEdit.setEnabled(value)

    def setLineWidgets(self, value):
        self.ui.lineLengthEdit.setEnabled(value)
        self.ui.lineAngleEdit.setEnabled(value)
        self.ui.lineAngleEdit.setText(str(self.lineAngle))
        self.ui.linePointsEdit.setEnabled(value)

    def setScanParams(self):
        self.updateROIs()
        scanType = self.ui.scanType.currentText()
        self.ui.motors2CursorButton.setEnabled(False)
        self.ui.setCursor2ZeroButton.setEnabled(False)
        self.ui.tiledCheckbox.setEnabled(False)
        if self.horizontalLine is not None:
            self.ui.mainImage.removeItem(self.horizontalLine)
        if self.verticalLine is not None:
            self.ui.mainImage.removeItem(self.verticalLine)
        if "Focus" in scanType:
            self.ui.yMotorCombo.setCurrentIndex(self.ui.yMotorCombo.findText(self.client.scanConfig["scans"][scanType]["y_motor"]))
            self.ui.xMotorCombo.setCurrentIndex(self.ui.xMotorCombo.findText(self.client.scanConfig["scans"][scanType]["x_motor"]))
            self.updateFocus()
            self.ui.defocusCheckbox.setEnabled(False)
            self.ui.xMotorCombo.setEnabled(False)
            self.ui.yMotorCombo.setEnabled(False)
            while len(self.scanRegList) > 1:
                self.ui.regionDefWidget.removeWidget(self.scanRegList[-1].region)
                self.scanRegList[-1].region.deleteLater()
                self.scanRegList[-1] = None
                del self.scanRegList[-1]
                self.ui.mainImage.removeItem(self.roiList[-1])
                del self.roiList[-1]
                self.nRegion -= 1
            self.ui.scanRegSpinbox.setValue(1)
            self.setSingleEnergy()
            self.ui.toggleSingleEnergy.setChecked(True)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(False)
            self.ui.scanRegSpinbox.setEnabled(False)
            if "Image" in self.currentImageType:
                self.ui.roiCheckbox.setCheckState(QtCore.Qt.Checked)
            else:
                self.ui.roiCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.setFocusWidgets(True)
            self.setLineWidgets(True)
            for reg in self.scanRegList:
                reg.setEnabled(False)
                reg.ui.xCenter.setEnabled(True)
                reg.ui.yCenter.setEnabled(True)
            self.ui.focusCenterEdit.setText(str(np.round(self.currentMotorPositions["ZonePlateZ"], 2)))
            self.ui.focusRangeEdit.setText(str(self.focusRange))
            self.ui.focusStepsEdit.setText(str(int(self.focusSteps)))
            self.ui.focusStepSizeLabel.setText(str(self.focusStepSize))
            self.ui.doubleExposureCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.doubleExposureCheckbox.setEnabled(False)
            self.ui.multiFrameCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.multiFrameCheckbox.setEnabled(False)
            if self.rangeROI is not None:
                self.ui.mainImage.removeItem(self.rangeROI)
            self.updateLine()
        elif scanType == "Line Spectrum":
            self.ui.defocusCheckbox.setEnabled(False)
            self.ui.xMotorCombo.setEnabled(False)
            self.ui.yMotorCombo.setEnabled(False)
            self.ui.yMotorCombo.setCurrentIndex(self.ui.yMotorCombo.findText(self.client.scanConfig["scans"]["Line Spectrum"]["y_motor"]))
            self.ui.xMotorCombo.setCurrentIndex(self.ui.xMotorCombo.findText(self.client.scanConfig["scans"]["Line Spectrum"]["x_motor"]))
            while len(self.scanRegList) > 1:
                self.ui.regionDefWidget.removeWidget(self.scanRegList[-1].region)
                self.scanRegList[-1].region.deleteLater()
                self.scanRegList[-1] = None
                del self.scanRegList[-1]
                self.ui.mainImage.removeItem(self.roiList[-1])
                del self.roiList[-1]
                self.nRegion -= 1
            self.ui.scanRegSpinbox.setValue(1)
            self.updateScanRegFromROI(self.roiList[-1])
            self.ui.doubleExposureCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.doubleExposureCheckbox.setEnabled(False)
            self.ui.multiFrameCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.multiFrameCheckbox.setEnabled(False)
            for reg in self.scanRegList:
                reg.setEnabled(False)
            self.ui.toggleSingleEnergy.setCheckState(QtCore.Qt.Unchecked)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(True)
            self.setFocusWidgets(False)
            self.setLineWidgets(True)
            if "Image" in self.currentImageType:
                self.ui.roiCheckbox.setCheckState(QtCore.Qt.Checked)
            else:
                self.ui.roiCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.lineLengthEdit.setText(str(self.scanRegList[0].ui.xRange.text()))
            self.updateScanRegFromROI(self.roiList[-1])
            if self.rangeROI is not None:
                self.ui.mainImage.removeItem(self.rangeROI)
            self.updateLine()
            self.setGUIfromScan(self.last_scan[scanType])
        elif "Image" in scanType and "OSA" not in scanType:
            for reg in self.scanRegList:
                reg.setEnabled(True)
            self.ui.yMotorCombo.setCurrentIndex(self.ui.yMotorCombo.findText(self.client.scanConfig["scans"]["Image"]["y_motor"]))
            self.ui.xMotorCombo.setCurrentIndex(self.ui.xMotorCombo.findText(self.client.scanConfig["scans"]["Image"]["x_motor"]))
            self.ui.energyRegSpinbox.setEnabled(True)
            self.ui.scanRegSpinbox.setEnabled(True)
            self.ui.focusToCursorButton.setEnabled(False)
            self.setFocusWidgets(False)
            self.setLineWidgets(False)
            self.ui.roiCheckbox.setEnabled(True)
            #This get's called twice on startup for some reason, first time before there are any scanReg's in the list
            if len(self.scanRegList) > 0: self.setGUIfromScan(self.last_scan[scanType])
            self.ui.toggleSingleEnergy.setCheckState(QtCore.Qt.Checked)
            self.ui.toggleSingleEnergy.setEnabled(True)
            self.setSingleEnergy()
            self.ui.xMotorCombo.setEnabled(False)
            self.ui.yMotorCombo.setEnabled(False)
            if "Ptychography" in scanType:
                self.ui.doubleExposureCheckbox.setEnabled(True)
                self.ui.multiFrameCheckbox.setEnabled(True)
                self.ui.defocusCheckbox.setEnabled(True)
            else:
                self.ui.tiledCheckbox.setEnabled(True)
                self.ui.doubleExposureCheckbox.setCheckState(QtCore.Qt.Unchecked)
                self.ui.doubleExposureCheckbox.setEnabled(False)
                self.ui.multiFrameCheckbox.setCheckState(QtCore.Qt.Unchecked)
                self.ui.multiFrameCheckbox.setEnabled(False)
                self.ui.defocusCheckbox.setEnabled(False)
            if not(self.currentImageType == self.ui.scanType.currentText()):
                # if scanType != "Ptychography Image":
                #     self.ui.mainImage.clear()
                if "Image" not in scanType:
                    self.ui.mainImage.clear()
                if self.horizontalLine is not None:
                    self.ui.mainImage.removeItem(self.horizontalLine)
                if self.verticalLine is not None:
                    self.ui.mainImage.removeItem(self.verticalLine)
            if self.ui.showRangeFinder.isChecked():
                if self.rangeROI is not None:
                    self.ui.mainImage.addItem(self.rangeROI)
        elif scanType == "Single Motor":
            self.ui.defocusCheckbox.setEnabled(False)
            self.ui.xMotorCombo.setEnabled(True)
            self.ui.yMotorCombo.setEnabled(False)
            while len(self.scanRegList) > 1:
                self.ui.regionDefWidget.removeWidget(self.scanRegList[-1].region)
                self.scanRegList[-1].region.deleteLater()
                self.scanRegList[-1] = None
                del self.scanRegList[-1]
                self.ui.mainImage.removeItem(self.roiList[-1])
                del self.roiList[-1]
                self.nRegion -= 1
            self.ui.scanRegSpinbox.setValue(1)
            self.setSingleEnergy()
            self.ui.toggleSingleEnergy.setChecked(True)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(False)
            self.ui.scanRegSpinbox.setEnabled(False)
            self.ui.xMotorCombo.setCurrentIndex(
                self.ui.xMotorCombo.findText(self.client.scanConfig["scans"]["Image"]["energy_motor"]))
            self.setGUIfromScan(self.last_scan[scanType])
        elif scanType == "Double Motor":
            self.setFocusWidgets(False)
            self.setLineWidgets(False)
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.defocusCheckbox.setEnabled(False)
            self.ui.xMotorCombo.setEnabled(True)
            self.ui.yMotorCombo.setEnabled(True)
            while len(self.scanRegList) > 1:
                self.ui.regionDefWidget.removeWidget(self.scanRegList[-1].region)
                self.scanRegList[-1].region.deleteLater()
                self.scanRegList[-1] = None
                del self.scanRegList[-1]
                self.ui.mainImage.removeItem(self.roiList[-1])
                del self.roiList[-1]
                self.nRegion -= 1
            self.ui.scanRegSpinbox.setValue(1)
            self.setSingleEnergy()
            self.ui.toggleSingleEnergy.setChecked(True)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(False)
            self.ui.scanRegSpinbox.setEnabled(False)
            x_motor = self.client.scanConfig["scans"]["Double Motor"]["x_motor"]
            y_motor = self.client.scanConfig["scans"]["Double Motor"]["y_motor"]
            self.ui.xMotorCombo.setCurrentIndex(self.ui.yMotorCombo.findText(x_motor))
            self.ui.yMotorCombo.setCurrentIndex(self.ui.yMotorCombo.findText(y_motor))
            self.setGUIfromScan(self.last_scan[scanType])
            self.setEnergyScan()
        elif scanType == "OSA Image":
            self.setFocusWidgets(False)
            self.setLineWidgets(False)
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.defocusCheckbox.setEnabled(False)
            while len(self.scanRegList) > 1:
                self.ui.regionDefWidget.removeWidget(self.scanRegList[-1].region)
                self.scanRegList[-1].region.deleteLater()
                self.scanRegList[-1] = None
                del self.scanRegList[-1]
                self.ui.mainImage.removeItem(self.roiList[-1])
                del self.roiList[-1]
                self.nRegion -= 1
            self.ui.scanRegSpinbox.setValue(1)
            self.setSingleEnergy()
            self.ui.toggleSingleEnergy.setChecked(True)
            self.ui.toggleSingleEnergy.setEnabled(False)
            self.ui.energyRegSpinbox.setEnabled(False)
            self.ui.scanRegSpinbox.setEnabled(False)
            x_motor = self.client.scanConfig["scans"]["Double Motor"]["x_motor"]
            y_motor = self.client.scanConfig["scans"]["Double Motor"]["y_motor"]
            self.ui.xMotorCombo.setCurrentIndex(self.ui.yMotorCombo.findText(x_motor))
            self.ui.yMotorCombo.setCurrentIndex(self.ui.yMotorCombo.findText(y_motor))
            self.setGUIfromScan(self.last_scan[scanType])
            self.setEnergyScan()
            self.ui.xMotorCombo.setEnabled(False)
            self.ui.yMotorCombo.setEnabled(False)


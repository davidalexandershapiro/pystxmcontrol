from pystxmcontrol.controller.client import stxmClient
from pystxmcontrol.gui.sampleScan_UI import Ui_MainWindow
from pystxmcontrol.gui.energyDef import energyDefWidget
from pystxmcontrol.gui.scanDef import scanRegionDef
from pystxmcontrol.utils.writeNX import *
from pystxmcontrol.controller.zmqFrameMonitor import zmqFrameMonitor
from PyQt5 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
import numpy as np
import time, datetime, json, atexit, sys, os, threading
import qdarkstyle
from queue import Queue

BASEPATH = sys.prefix
MAINCONFIGFILE = os.path.join(BASEPATH,'pystxmcontrol_cfg/main.json')

class controlThread(QtCore.QThread):
    '''
    The main App will create a client and queue for passing messages.  Those are handed to this thread and used
    for passing messages to the client in a controlled way.  The client socket connection to the server is protected
    by a Lock object but it should in principle only receive messages from this thread.
    '''
    controlResponse = QtCore.pyqtSignal(object)

    def __init__(self, client, messageQueue):
        QtCore.QThread.__init__(self)
        self.messageQueue = messageQueue
        self.client = client

    def run(self):

        while True:
            message = self.messageQueue.get(True)
            if message != "exit":
                response = self.client.sendMessage(message)
                if response is None:
                    response = {"command": message["command"],"status":"No response from server"}
                self.controlResponse.emit(response)
            else:
                print("Exiting messageThread...")
                return
                
class sampleScanWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self, parent=None):
        super(sampleScanWindow, self).__init__(parent=parent)

        # set up the form class as a `ui` attribute
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.client = stxmClient()
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

        self.ui.scanRegSpinbox.valueChanged.connect(self.updateScanRegDef)
        self.ui.energyRegSpinbox.valueChanged.connect(self.updateEnergyRegDef)
        self.ui.scanType.currentIndexChanged.connect(self.setScanParams)
        self.ui.channelSelect.currentIndexChanged.connect(self.setChannel)
        self.ui.toggleSingleEnergy.stateChanged.connect(self.setSingleEnergy)
        self.ui.action_Open_Image_Data.triggered.connect(self.getScanFile)
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
        self.ui.dsEdit.returnPressed.connect(self.updateDS)
        self.ui.ndsEdit.returnPressed.connect(self.updateNDS)
        self.ui.m101Edit.returnPressed.connect(self.updateM101)
        self.ui.fbkEdit.returnPressed.connect(self.updateFBK)
        self.ui.polEdit.returnPressed.connect(self.updatePOL)
        self.ui.epuEdit.returnPressed.connect(self.updateEPU)
        #self.ui.harSpin.valueChanged.connect(self.updateHAR)
        self.ui.lineLengthEdit.textChanged.connect(self.updateLineStepSize)
        self.ui.focusStepsEdit.returnPressed.connect(self.updateFocus)
        self.ui.focusRangeEdit.returnPressed.connect(self.updateFocus)
        self.ui.linePointsEdit.returnPressed.connect(self.updateLine)
        self.ui.lineLengthEdit.returnPressed.connect(self.updateLine)
        self.ui.lineAngleEdit.returnPressed.connect(self.updateLine)
        self.ui.shutterComboBox.currentIndexChanged.connect(self.updateShutter)
        self.ui.mainImage.scene.sigMouseMoved.connect(self.mouseMoved)
        self.ui.mainImage.scene.sigMouseClicked.connect(self.mouseClicked)
        self.ui.plotClearButton.clicked.connect(self.clearPlot)
        self.ui.action_Save_Scan_Definition.triggered.connect(self.saveScanDef)
        self.ui.action_Open_Energy_Definition.triggered.connect(self.openEnergyDefinition)
        self.ui.action_Open_Scan_Definition.triggered.connect(self.openScanDefinition)
        self.ui.beamToCursorButton.clicked.connect(self.beamToCursor)
        self.ui.focusToCursorButton.clicked.connect(self.setFocusZ)
        self.ui.mainImage.sigTimeChanged.connect(self.updateTimeIndex)
        self.ui.showRangeFinder.stateChanged.connect(self.showRangeFinder)
        # self.ui.serpentineCheckbox.stateChanged.connect(self.serpentineCheck)
        self.ui.serpentineCheckbox.setEnabled(False)
        # self.ui.flyscanCheckbox.stateChanged.connect(self.flyscanCheck)
        self.ui.flyscanCheckbox.setEnabled(False)
        self.ui.doubleExposureCheckbox.stateChanged.connect(self.updateEstimatedTime)

        self.ui.showBeamPosition.setCheckState(QtCore.Qt.Unchecked)
        self.ui.singleMotorScanCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
        self.ui.singleMotorScanCheckbox_2.stateChanged.connect(self.checkSingleMotorScan)
        self.ui.outerLoopCheckbox_2.stateChanged.connect(self.checkOuterLoop)
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
        self.ui.outerLoopCenter.setText(str(0))
        self.ui.outerLoopRange.setText(str(0))
        self.ui.outerLoopPoints.setText(str(0))
        self.ui.outerLoopStep.setText(str(0))
        self.ui.outerLoopRange.textChanged.connect(self.checkOuterLoop)
        self.ui.outerLoopPoints.textChanged.connect(self.checkOuterLoop)
        self.ui.outerLoopCenter.textChanged.connect(self.checkOuterLoop)
        self.ui.harSpin.setEnabled(False)
        self.ui.firstEnergyButton.clicked.connect(self.moveToFirstEnergy)
        self.ui.focusToCursorButton.setEnabled(False)
        self.ui.cursorToCenterButton.setEnabled(False)
        self.ui.beamToCursorButton.setEnabled(False)

        self.maxVelocity = 0.2
        self.velocity = 0.0
        self.imageScanTypes = ["ptychographyGrid", "rasterLine", "continuousLine"]
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
        self.scan["energyRegions"] = {}
        self.scan["scanRegions"] = {}
        self.nRegion = 0
        self.nEnergyRegion = 0
        self.penColors = [(255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),(0,255,255)]
        self.penStyles = [QtCore.Qt.SolidLine, QtCore.Qt.DashLine]
        self.roiList = []
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
        self.nRegDefs = 10
        self.nEnergyDefs = 10
        self.regDefs = []
        self.energyRegDefs = []
        for i in range(self.nRegDefs):
            regDef = [0,0,70,70,50,50,1.0,1.0]
            self.regDefs.append(regDef)
        for i in range(self.nEnergyDefs):
            energyDef = [500,600,1,2,1]
            self.energyRegDefs.append(energyDef)
        self.mainConfig = json.loads(open(MAINCONFIGFILE).read())
        self.lastScan = self.mainConfig["lastScan"]
        self.serverIP = self.mainConfig["server"]["ip"]
        self.serverCommandPort = self.mainConfig["server"]["commandPort"]
        self.serverDataPort = self.mainConfig["server"]["dataPort"]
        self.ui.roiCheckbox.setCheckState(QtCore.Qt.Checked)
        self.connectClient()
        self.initGUI()
        self.focusRange = 100
        self.focusSteps = 50
        self.focusStepSize = 2.0
        self.cursorX = None
        self.cursorY = None
        self.metaFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/meta.json')
        self.metaStr = json.loads(open(self.metaFile).read())
        self.ui.proposalLineEdit.setText(self.metaStr["proposal"])
        self.ui.experimentersLineEdit.setText(self.metaStr["experimenters"])
        self.ui.sampleLineEdit.setText(self.metaStr["sample"])
        #self.imageScale = 1.4,1.4
        self._movingStyle = """QLabel {color: red;}"""
        self._staticStyle = """QLabel {color: white;}"""
        self.xCenter, self.yCenter = 0.,0.
        self.xRange, self.yRange = 70.,70.

    # def flyscanCheck(self):
    #     if self.ui.flyscanCheckbox.isChecked():
    #         if self.scanType == "Image":
    #             pass
    #             #self.serpentineCheck()
    #     else:
    #         self.ui.serpentineCheckbox.setCheckState(QtCore.Qt.Unchecked)
    #         self.ui.serpentineCheckbox.setEnabled(False)

    # def serpentineCheck(self):
    #     if self.scanType == "Image":
    #         if self.velocity < self.maxVelocity:
    #             self.ui.serpentineCheckbox.setEnabled(True)
    #         else:
    #             self.ui.serpentineCheckbox.setEnabled(False)
    #         if self.ui.serpentineCheckbox.isChecked():
    #             self.ui.flyscanCheckbox.setCheckState(QtCore.Qt.Checked)
    #             self.ui.flyscanCheckbox.setEnabled(False)
    #         else:
    #             self.ui.flyscanCheckbox.setEnabled(True)
    #         self.updateEstimatedTime()

    def moveToFirstEnergy(self):
        self.updateEnergy(energy = float(self.energyRegList[0].energyDef.energyStart.text()))

    def showRangeFinder(self):
        if self.ui.showRangeFinder.isChecked():
            self.ui.mainImage.addItem(self.rangeROI)
        else:
            self.ui.mainImage.removeItem(self.rangeROI)

    def beamToCursor(self):
        if self.cursorX is not None:
            message = {"command": "moveMotor"}
            message["axis"] = "SampleX"
            message["pos"] = self.cursorX
            self.messageQueue.put(message)
            #if self.messageThread.is_alive():
            #    pass
            #else:
            #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
            #    self.messageThread.start()
        time.sleep(0.1)
        if self.cursorY is not None:
            message = {"command": "moveMotor"}
            message["axis"] = "SampleY"
            message["pos"] = self.cursorY
            self.messageQueue.put(message)
            #if self.messageThread.is_alive():
            #    pass
            #else:
            #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
            #    self.messageThread.start()

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
                    self.lastScan["Image"] = self.scan
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
            self.monitorDataList = []

    def checkSingleMotorScan(self):
        if self.ui.singleMotorScanCheckbox_2.isChecked():
            self.ui.outerLoopCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
        else:
            pass #self.ui.outerLoopCheckbox_2.setCheckState(QtCore.Qt.Checked)

    def checkOuterLoop(self):
        if self.ui.outerLoopCheckbox_2.isChecked():
            self.ui.singleMotorScanCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
            self.ui.scanRegSpinbox.setValue(1)
            if (float(self.ui.outerLoopRange.text()) == 0) or (int(self.ui.outerLoopPoints.text()) == 0):
                self.ui.outerLoopCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
        else:
            pass

    def checkOuterLoop(self):
        try:
            float(self.ui.outerLoopCenter.text())
        except:
            self.ui.outerLoopCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
            return
        try:
            float(self.ui.outerLoopRange.text())
        except:
            self.ui.outerLoopCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
            return
        try:
            int(self.ui.outerLoopPoints.text())
        except:
            self.ui.outerLoopCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
            return
        stepSize = float(self.ui.outerLoopRange.text()) / (float(self.ui.outerLoopPoints.text()) - 1)
        self.ui.outerLoopStep.setText(str(np.round(stepSize,3)))

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

        if self.image is not None:

            if "Image" in self.currentImageType:
                x = (np.round(scenePos.x(), 3) * self.imageScale[0]) + self.xCenter - self.xRange / 2.
                y = (np.round(scenePos.y(), 3) * self.imageScale[1]) + self.yCenter - self.yRange / 2.
                xUnits = " um"
                yUnits = " um"
            elif self.currentImageType == "Focus":
                lineRange = np.sqrt(self.xLineRange**2 + self.yLineRange**2)
                x = (np.round(scenePos.x(), 3) * self.imageScale[0]) * lineRange / self.xPts + self.xCenter - lineRange / 2.
                y = (np.round(scenePos.y(), 3) * self.imageScale[1]) * self.zRange / self.zPts + self.zCenter - self.zRange / 2.
                xUnits = " um"
                yUnits = " um"
            elif self.currentImageType == "Line Spectrum":
                eRange = self.stxm.energies.max() - self.stxm.energies.min()
                ePts = self.stxm.energies.size
                eCenter = self.stxm.energies.min() + eRange / 2.
                lineRange = np.sqrt(self.xLineRange**2 + self.yLineRange**2)
                y = (np.round(scenePos.y(), 3) * self.imageScale[1]) * lineRange / self.xPts + self.xCenter - lineRange / 2.
                x = (np.round(scenePos.x(), 3) * self.imageScale[0]) * eRange / ePts + eCenter - eRange / 2.
                xUnits = " eV"
                yUnits = " um"
            col, row = int(scenePos.y()), int(scenePos.x())
            self.ui.xCursorPos.setText(str(np.round(x,3)) + xUnits)
            self.ui.yCursorPos.setText(str(np.round(-y,3)) + yUnits)
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
        self.consoleText.insert(0,message)
        printStr = ''
        for item in self.consoleText:
            newStr = ''
            for key in item.keys():
                newStr += key + ': ' + str(item[key]) + ', '
            printStr += newStr + '\n'
        self.ui.serverOutput.setText(printStr)

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
        #response = self.client.server.sendMessage(message)
        self.client.sendMessage(message)

    def updateFocus(self):
        range = float(str(self.ui.focusRangeEdit.text()))
        steps = float(str(self.ui.focusStepsEdit.text()))
        stepSize = range / steps
        self.ui.focusStepSizeLabel.setText(str(np.round(stepSize,2)))
        self.focusRange = range
        self.focusSteps = steps
        self.focusStepSize = np.round(stepSize,2)

    def updateLine(self):
        lineRange = float(str(self.ui.lineLengthEdit.text()))
        steps = float(str(self.ui.linePointsEdit.text()))
        stepSize = lineRange / steps
        self.ui.lineStepSizeLabel.setText(str(np.round(stepSize,2)))
        self.lineLength = lineRange
        self.linePoints = steps
        self.lineStepSize = np.round(stepSize,2)
        self.lineAngle = float(self.ui.lineAngleEdit.text())
        self.updateROIfromRegion(1)
        #for roi in self.roiList:
        #    self.updateScanRegFromROI(roi)

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
            #if self.messageThread.is_alive():
            #    pass
            #else:
            #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
            #    self.messageThread.start()

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
            #if self.messageThread.is_alive():
            #    pass
            #else:
            #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
            #    self.messageThread.start()

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
            #if self.messageThread.is_alive():
            #    pass
            #else:
            #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
            #    self.messageThread.start()

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
            #if self.messageThread.is_alive():
            #    pass
            #else:
            #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
            #    self.messageThread.start()

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
            #if self.messageThread.is_alive():
            #    pass
            #else:
            #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
            #    self.messageThread.start()

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
            #if self.messageThread.is_alive():
            #    pass
            #else:
            #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
            #    self.messageThread.start()

    def updateHAR(self):
        newValue = self.ui.harSpin.value()
        message = {"command": "moveMotor"}
        message["axis"] = "HARMONIC"
        message["pos"] = newValue
        self.messageQueue.put(message)
        #if self.messageThread.is_alive():
        #    pass
        #else:
        #    self.messageThread = threading.Thread(target=self.client.sendMessage, args=(message,))
        #    self.messageThread.start()

    def mouseClicked(self, pos):

        if self.ui.channelSelect.currentText() == "CCD":
            return

        if self.image is not None:
            pos = pos.pos()
            if self.horizontalLine is not None:
                self.ui.mainImage.removeItem(self.horizontalLine)
            if self.verticalLine is not None:
                self.ui.mainImage.removeItem(self.verticalLine)
            scenePos = self.ui.mainImage.getImageItem().mapFromScene(pos)

            if "Image" in self.scan["type"]:
                x = (np.round(scenePos.x(), 3) * self.imageScale[0]) + self.xCenter - self.xRange / 2.
                y = (np.round(scenePos.y(), 3) * self.imageScale[1]) + self.yCenter - self.yRange / 2.
                self.cursorX, self.cursorY = x,y
            elif self.scan["type"] == "Focus":
                x = (np.round(scenePos.x(), 3) * self.imageScale[0]) + self.xCenter - self.xRange / 2.
                zRange = (np.round(scenePos.y(), 3) - self.zPts / 2) * float(self.ui.focusStepSizeLabel.text())
                yPos = zRange + float(self.ui.focusCenterEdit.text())
                y = np.round(scenePos.y(), 3) + self.imageCenter[1]
                self.cursorFocusZ = yPos
                self.ui.focusToCursorButton.setEnabled(True)
            elif "Line" in self.scan["type"]:
                eRange = self.stxm.energies.max() - self.stxm.energies.min()
                y = (np.round(scenePos.y(), 3) * self.imageScale[1]) + self.yCenter - self.yRange / 2.
                x = np.round(scenePos.x(), 3) + self.imageCenter[0]

            pen = pg.mkPen(color = (0,255,0),width=1,style=QtCore.Qt.SolidLine)
            self.horizontalLine = pg.InfiniteLine(pos = y, angle = 0, pen = pen)
            self.verticalLine = pg.InfiniteLine(pos = x, angle = 90, pen = pen)
            if (self.currentImageType == self.ui.scanType.currentText()) and not(self.ui.roiCheckbox.isChecked()):
                self.ui.mainImage.addItem(self.horizontalLine)
                self.ui.mainImage.addItem(self.verticalLine)

    def getZonePlateCalibrationFromServer(self):
        message = {"command": "getZonePlateCalibration"}
        response = self.client.sendMessage(message)
        if response is not None:
            return response["data"]

    def setFocusZ(self):
        try:
            offsetDelta = (self.zonePlateCalibration - self.cursorFocusZ)
        except:
            return
        else:
            self.ui.focusToCursorButton.setEnabled(False)
            newOffset = self.zonePlateOffset + offsetDelta
            print("Current zone plate calibrated position: %.3f \n \
                    Cursor Z position: %.2f  \n \
                    Current zone plate offset: %.2f \n \
                    Offset change: %.2f  \n \
                    New Offset: %.2f" %(self.zonePlateCalibration,self.cursorFocusZ,self.zonePlateOffset,offsetDelta,newOffset))

            #if np.abs(offsetDelta) > 200:
            msgBox = QtWidgets.QMessageBox()
            msgBox.setIcon(QtWidgets.QMessageBox.Information)
            msgBox.setText("This will change the focus by %.2f microns.  Proceed?" %offsetDelta)
            msgBox.setWindowTitle("Focus warning")
            msgBox.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
            #msgBox.buttonClicked.connect(msgButtonClick)

            returnValue = msgBox.exec()
            if returnValue == QtWidgets.QMessageBox.Ok:
                ##calculate difference with new position
                ##and change offset according to this difference
                message = {"command": "changeMotorConfig"}
                message["data"] = {"motor":"ZonePlateZ","config":"offset","value":newOffset}
                self.messageQueue.put(message)
                time.sleep(0.5)

            #move zone plate to new focus position
            message = {"command": "moveMotor"}
            message["axis"] = "ZonePlateZ"
            message["pos"] = self.zonePlateCalibration #self.cursorFocusZ
            self.messageQueue.put(message)

            self.ui.scanType.setCurrentIndex(0) #should set to Image scan after each focus/line scan
            self.ui.mainImage.removeItem(self.horizontalLine)
            self.ui.mainImage.removeItem(self.verticalLine)

    def abortMove(self):
        message = {"command": "abortMove"}
        message["axis"] = self.lastMotor
        #self.client.sendMessage(message)

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
        self.ui.firstEnergyButton.setEnabled(True)
        self.ui.scanRegSpinbox.setEnabled(True)
        self.ui.energyRegSpinbox.setEnabled(True)
        self.ui.beginScanButton.setEnabled(True)
        self.ui.scanType.setEnabled(True)
        if "Image" in self.scanType:
            self.ui.roiCheckbox.setEnabled(True)
            self.ui.toggleSingleEnergy.setEnabled(True)
        # if self.scanType == "Image":
        #     self.ui.flyscanCheckbox.setEnabled(True)
        if self.ui.scanType.currentText() == "Focus":
            #self.ui.focusToCursorButton.setEnabled(True)
            pass
        elif self.ui.scanType.currentText() == "Line Spectrum":
            pass
        else:
            self.ui.beamToCursorButton.setEnabled(True)
            for reg in self.scanRegList:
                reg.setEnabled(True)
        if self.ui.showRangeFinder.isChecked():
            if "Image" in self.scanType:
                self.ui.mainImage.addItem(self.rangeROI)


    def deactivateGUI(self):
        # self.ui.flyscanCheckbox.setEnabled(False)
        # self.ui.serpentineCheckbox.setEnabled(False)
        self.ui.firstEnergyButton.setEnabled(False)
        self.ui.toggleSingleEnergy.setEnabled(False)
        self.ui.scanType.setEnabled(False)
        self.ui.scanRegSpinbox.setEnabled(False)
        self.ui.energyRegSpinbox.setEnabled(False)
        self.ui.beginScanButton.setEnabled(False)
        self.ui.beamToCursorButton.setEnabled(False)
        self.ui.focusToCursorButton.setEnabled(False)
        self.hideROIs()
        self.ui.roiCheckbox.setCheckState(QtCore.Qt.Unchecked)
        self.ui.roiCheckbox.setEnabled(False)
        self.ui.singleMotorScanCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
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
        self.messageQueue.put("exit")
        #self.controlThread.join()
        self.client.disconnect()
        try:
            self.scanThread.join()
        except:
            pass

    @QtCore.pyqtSlot(np.float16)
    def updateTime(self, time):
        if time < 100.:
            self.ui.elapsedTime.setText(str(np.round(time, 2)) + ' s')
        elif time < 3600.:
            self.ui.elapsedTime.setText(str(np.round(time / 60., 2)) + ' m')
        else:
            self.ui.elapsedTime.setText(str(np.round(time / 3600., 2)) + ' hr')

    def setROI(self):
        if self.ui.roiCheckbox.isChecked():
            self.showROIs()
        else:
            self.hideROIs()

    def cancelScan(self):
        if self.client.getStatus()["mode"] == "scanning":
            #self.client.cancelScan()
            message = {"command": "cancel"}
            self.messageQueue.put(message)

    @QtCore.pyqtSlot()
    def compileScan(self,nowrite = True):
        self.scanList = {}
        self.scan = {}
        self.scanType = str(self.ui.scanType.currentText())
        scanMotorList = self.client.scanConfig["scans"][self.scanType]
        self.scan["type"] = self.scanType
        self.scan["function"] = self.client.scanConfig["scans"][self.scanType]["function"]
        self.scan["proposal"] = self.ui.proposalLineEdit.text()
        self.scan["experimenters"] = self.ui.experimentersLineEdit.text()
        self.scan["sample"] = self.ui.sampleLineEdit.text()
        self.scan["x"] = scanMotorList["xMotor"]
        self.scan["y"] = scanMotorList["yMotor"]
        self.scan["defocus"] = self.ui.defocusCheckbox.isChecked()
        if self.ui.flyscanCheckbox.isChecked():
            self.scan["mode"] = "continuousLine"
        else:
            self.scan["mode"] = "rasterLine"
        if "Ptychography" in self.scanType:
            self.scan["mode"] = "ptychographyGrid"
        self.scan["scanRegions"] = {}
        self.scan["energyRegions"] = {}
        for index, region in enumerate(self.scanRegList):
            regStr = "Region" + str(index + 1)
            self.scan["scanRegions"][regStr] = {}
            if "Image" in self.scanType:
                self.scan["energy"] = scanMotorList["energyMotor"]
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
                zPoints = 0
                zStep = 0
            if ("Focus" in self.scanType):
                self.scan["z"] = scanMotorList["zMotor"]
                xCenter = float(region.ui.xCenter.text())
                yCenter = float(region.ui.yCenter.text())
                xRange = self.xLineRange #float(region.ui.xRange.text())
                yRange = self.yLineRange #float(region.ui.yRange.text())
                zCenter = float(self.ui.focusCenterEdit.text())
                zRange = float(self.ui.focusRangeEdit.text())
                zPoints = int(self.ui.focusStepsEdit.text())
                zStep = float(self.ui.focusStepSizeLabel.text())
                xPoints = int(self.ui.linePointsEdit.text())
                yPoints = xPoints
                xStep = float(self.ui.lineStepSizeLabel.text())
                yStep = xStep
            if (self.scanType == "Line Spectrum"):
                self.scan["energy"] = scanMotorList["energyMotor"]
                xCenter = float(region.ui.xCenter.text())
                yCenter = -float(region.ui.yCenter.text())
                xRange = self.xLineRange
                yRange = self.yLineRange
                xPoints = int(self.ui.linePointsEdit.text())
                yPoints = xPoints
                xStep = float(self.ui.lineStepSizeLabel.text())
                yStep = xStep
                zCenter = 0
                zRange = 0
                zPoints = 0
                zStep = 0
            self.scan["scanRegions"][regStr]["xStart"] = xCenter - xRange / 2.0 + xStep / 2.
            self.scan["scanRegions"][regStr]["xStop"] = xCenter + xRange / 2.0 - xStep / 2.
            self.scan["scanRegions"][regStr]["xPoints"] = xPoints
            self.scan["scanRegions"][regStr]["yStart"] = yCenter - yRange / 2.0 + yStep / 2.
            self.scan["scanRegions"][regStr]["yStop"] = yCenter + yRange / 2.0 - yStep / 2.
            self.scan["scanRegions"][regStr]["yPoints"] = yPoints
            self.scan["scanRegions"][regStr]["xStep"] = xStep
            self.scan["scanRegions"][regStr]["yStep"] = yStep
            self.scan["scanRegions"][regStr]["xRange"] = xRange
            self.scan["scanRegions"][regStr]["yRange"] = yRange
            self.scan["scanRegions"][regStr]["xCenter"] = xCenter
            self.scan["scanRegions"][regStr]["yCenter"] = yCenter
            self.scan["scanRegions"][regStr]["zStart"] = zCenter - zRange / 2.0 + zStep / 2.
            self.scan["scanRegions"][regStr]["zStop"] = zCenter + zRange / 2.0 - zStep / 2.
            self.scan["scanRegions"][regStr]["zPoints"] = zPoints
            self.scan["scanRegions"][regStr]["zStep"] = zStep
            self.scan["scanRegions"][regStr]["zRange"] = zRange
            self.scan["scanRegions"][regStr]["zCenter"] = zCenter
        for index, region in enumerate(self.energyRegList):
            regStr = "EnergyRegion" + str(index + 1)
            #enforce single dwell
            if regStr == "EnergyRegion1":
                dwellStr = region.energyDef.dwellTime.text()
            region.energyDef.dwellTime.setText(dwellStr)
            self.scan["energyRegions"][regStr] = {}
            self.scan["energyRegions"][regStr]["dwell"] = float(region.energyDef.dwellTime.text())
            self.scan["energyRegions"][regStr]["start"] = float(region.energyDef.energyStart.text())
            self.scan["energyRegions"][regStr]["stop"] = float(region.energyDef.energyStop.text())
            self.scan["energyRegions"][regStr]["step"] = float(region.energyDef.energyStep.text())
            self.scan["energyRegions"][regStr]["nEnergies"] = int(region.energyDef.nEnergies.text())
        self.scanList[self.scanType] = self.scan

        if self.ui.outerLoopCheckbox_2.isChecked() and "Image" in self.scan["type"]: #self.scan["type"] == "Image":
            self.scan["outerLoop"] = {}
            self.scan["outerLoop"]["motor"] = self.ui.outerLoopMotor.currentText()
            self.scan["outerLoop"]["range"] = float(self.ui.outerLoopRange.text())
            self.scan["outerLoop"]["center"] = float(self.ui.outerLoopCenter.text())
            self.scan["outerLoop"]["points"] = int(self.ui.outerLoopPoints.text())
            #self.scan["type"] = self.scanType + "Loop"
            for i in range(1,self.scan["outerLoop"]["points"]):
                regStr = "Region" + str(i + 1)
                self.scan["scanRegions"][regStr] = self.scan["scanRegions"]["Region1"]

        if self.ui.doubleExposureCheckbox.isChecked():
            self.scan["doubleExposure"] = True
        else:
            self.scan["doubleExposure"] = False

        ##generate the local data structure
        if self.scan["type"] in self.imageScanTypes:
            self.stxm = stxm(self.scan)

        if not(nowrite):
            self.mainConfig["lastScan"][self.scan["type"]] = self.scan
            with open(MAINCONFIGFILE, 'w') as fp:
                json.dump(self.mainConfig, fp, indent=4)

    def updateEstimatedTime(self):
        self.compileScan()

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
        for region in self.scan["scanRegions"].keys():
            if "Image" in self.scan["type"]:
                nPoints += self.scan["scanRegions"][region]["xPoints"] * \
                    self.scan["scanRegions"][region]["yPoints"]
                nLines += self.scan["scanRegions"][region]["yPoints"]
            elif "Focus" in self.scan["type"]:
                nPoints += self.scan["scanRegions"][region]["xPoints"] * \
                    self.scan["scanRegions"][region]["zPoints"]
                nLines += self.scan["scanRegions"][region]["zPoints"]
            elif self.scan["type"] == "Line Spectrum":
                nPoints += self.scan["scanRegions"][region]["xPoints"]
            if "Ptychography" in self.scan["type"]:
                nPoints += 25 #for background points

        for region in self.scan["energyRegions"].keys():
            if self.scan["type"] == "Line Spectrum":
                nLines = self.scan["energyRegions"][region]["nEnergies"]
            if "Ptychography" in self.scan["type"]:
                if self.ui.doubleExposureCheckbox.isChecked():
                    pointOverhead = 0.2
                    pointDwell = (self.scan["energyRegions"][region]["dwell"] + self.scan["energyRegions"][region]["dwell"]*10.)
                else:
                    pointOverhead = 0.1
                    pointDwell = self.scan["energyRegions"][region]["dwell"]
                timePerPoint += (pointDwell / 1000. \
                                 + pointOverhead) * self.scan["energyRegions"][region]["nEnergies"]
            else:
                timePerPoint += (self.scan["energyRegions"][region]["dwell"] / 1000. \
                               + self.pointOverhead) * self.scan["energyRegions"][region]["nEnergies"]
            nEnergies += self.scan["energyRegions"][region]["nEnergies"]
        estimatedTime = nPoints * timePerPoint + nLines * self.lineOverhead + (nEnergies - 1) * self.energyOverhead
        if estimatedTime < 100.:
            self.ui.estimatedTime.setText(str(np.round(estimatedTime, 2)) + ' s')
        elif estimatedTime < 3600.:
            self.ui.estimatedTime.setText(str(np.round(estimatedTime / 60., 2)) + ' m')
        else:
            self.ui.estimatedTime.setText(str(np.round(estimatedTime / 3600., 2)) + ' hr')
        try:
            velocityList = []
            for region in self.scan["scanRegions"].keys():
                velocityList.append(self.scan["scanRegions"][region]["xStep"] / self.scan["energyRegions"]["EnergyRegion1"]["dwell"])
            self.velocity = max(velocityList)
            self.ui.scanVelocity.setText(str(np.round(self.velocity,2))+" mm/s")
        except:
            pass

    def scanCheck(self):
        xMin = self.client.motorInfo[self.scan['x']]["minScanValue"]
        xMax = self.client.motorInfo[self.scan['x']]["maxScanValue"]
        yMin = self.client.motorInfo[self.scan['y']]["minScanValue"]
        yMax = self.client.motorInfo[self.scan['y']]["maxScanValue"]
        for regStr in self.scan["scanRegions"].keys():
            deltaX = self.scan["scanRegions"][regStr]["xStop"] - self.scan["scanRegions"][regStr]["xStart"]
            deltaY = self.scan["scanRegions"][regStr]["yStop"] - self.scan["scanRegions"][regStr]["yStart"]
            if deltaX > self.client.motorInfo[self.scan['x']]["maxScanRange"]:
                return False
            elif deltaY > self.client.motorInfo[self.scan['y']]["maxScanRange"]:
                return False
            elif self.scan["scanRegions"][regStr]["xStart"] < xMin:
                return False
            elif self.scan["scanRegions"][regStr]["xStop"] > xMax:
                return False
            elif self.scan["scanRegions"][regStr]["yStart"] < yMin:
                return False
            elif self.scan["scanRegions"][regStr]["yStop"] > yMax:
                return False
            else:
                return True

    def beginScan(self):
        self.compileScan(nowrite = False)
        if self.scanCheck():
            self.scanning = True
            self.deactivateGUI()
            self.ui.outerLoopCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
            self.client.scan = self.scan
            #self.client.doScan(self.scan)
            message = {"command": "doScan"}
            message["scan"] = self.scan
            self.messageQueue.put(message)
        else:
            msg = QtWidgets.QMessageBox()
            msg.setIcon(QtWidgets.QMessageBox.Critical)
            msg.setText("Scan Error")
            msg.setInformativeText('Please check scan ranges')
            msg.setWindowTitle("Scan Error")
            msg.exec_()
            return

    def joinScan(self):
        self.scanning = False
        self.compileScan()
        self.deactivateGUI()
        self.client.scan = self.scan

    @QtCore.pyqtSlot()
    def endScan(self):
        # self.scanThread.join()
        print("joined scan thread")

    def updatePlot(self, data):
        if self.currentPlot is not None:
            self.ui.mainPlot.removeItem(self.currentPlot)
        if len(self.monitorDataList) < self.monitorNPoints:
            self.monitorDataList.append(data)
        else:
            self.monitorDataList.append(data)
            self.monitorDataList = self.monitorDataList[1:]
        self.currentPlot = self.ui.mainPlot.plot(np.array(self.monitorDataList), \
            pen = pg.mkPen('w', width = 1, style = QtCore.Qt.DotLine), symbol='o',symbolPen = 'g', symbolSize=3,\
                                                 symbolBrush=(0,255,0))
        self.ui.daqCurrentValue.setText(str(data*10.))
        
    def setChannel(self):
        if self.ui.channelSelect.currentText() == "CCD":
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
        elif self.ui.channelSelect.currentText() == "Diode":
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
            self.ui.mainImage.setImage(self.currentCCDData, autoRange=False, autoLevels=False, \
                        autoHistogramRange=False)
                        
    def updateImageFromRPI(self, rpiData):
        self.currentRPIData, self.ptychoXpixm, self.ptychoYpixm = rpiData
        if self.ui.channelSelect.currentText() == "RPI":
            self.ui.mainImage.setImage(self.currentRPIData, autoRange=True, autoLevels=True, \
                        autoHistogramRange=True)
          
    def updateImageFromMessage(self, message):

        try:
            self.currentMotorPositions = message['motorPositions']
            self.currentMotorStatus = message["motorPositions"]["status"]
            self.updateMotorPositions()
            self.zonePlateCalibration = message['zonePlateCalibration']
            self.zonePlateOffset = message['zonePlateOffset']
        except:
           pass
        if message is None:
            pass
        elif message == "endOfScan":
            self.activateGUI()
        elif message["type"] in self.imageScanTypes:
            self.currentDataDir = os.path.split(message["scanID"])[0]
            elapsedTime = message["elapsedTime"]
            self.ui.scanFileName.setText(message["scanID"].split("/")[-1])
            if elapsedTime < 100.:
                self.ui.elapsedTime.setText(str(np.round(elapsedTime, 2)) + ' s')
            elif elapsedTime < 3600.:
                self.ui.elapsedTime.setText(str(np.round(elapsedTime / 60., 2)) + ' m')
            else:
                self.ui.elapsedTime.setText(str(np.round(elapsedTime / 3600., 2)) + ' hr')
            scanRegNumber = int(message["scanRegion"].split("Region")[-1]) - 1
            energyIndex = message["energyIndex"]
            #energyRegNumber = int(message["energyRegion"].split("EnergyRegion")[-1]) - 1
            nRegions = self.stxm.nScanRegions
            nEnergies = self.stxm.energies.size
            imageCountStr = "Region %i of %i | Energy %i of %i" %(scanRegNumber+1, nRegions, energyIndex+1,nEnergies)
            self.ui.imageCountText.setText(imageCountStr)
            self.yPts, self.xPts, self.zPts = self.scan["scanRegions"][message["scanRegion"]]["yPoints"], \
                        self.scan["scanRegions"][message["scanRegion"]]["xPoints"], \
                        self.scan["scanRegions"][message["scanRegion"]]["zPoints"]
            xStart = int(message["index"])
            xStop = int(message["index"]) + np.size(message["data"])
            self.currentImageType = message["type"]
            self.currentEnergyIndex = message["energyIndex"]
            self.currentScanRegionIndex = scanRegNumber
            self.stxm.counts[scanRegNumber][0][message["energyIndex"],xStart:xStop] = message["data"]
            self.xCenter = self.scan["scanRegions"][message["scanRegion"]]["xCenter"]
            self.yCenter = -self.scan["scanRegions"][message["scanRegion"]]["yCenter"]
            self.zCenter = self.scan["scanRegions"][message["scanRegion"]]["zCenter"]
            self.xRange = self.scan["scanRegions"][message["scanRegion"]]["xRange"]
            self.yRange = self.scan["scanRegions"][message["scanRegion"]]["yRange"]
            self.zRange = self.scan["scanRegions"][message["scanRegion"]]["zRange"]
            self.energy = self.stxm.energies[self.currentEnergyIndex]
            self.dwell = self.stxm.dwells[self.currentEnergyIndex]
            self.xStep = self.xRange / self.xPts
            if "Image" in self.scan["type"]:
                self.image = np.reshape(self.stxm.counts[scanRegNumber][0][message["energyIndex"]], (self.yPts, self.xPts))
                xScale = float(self.xRange) / float(self.xPts)
                yScale = float(self.yRange) / float(self.yPts)
                pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
            elif "Focus" in self.scan["type"]:
                self.image = np.reshape(self.stxm.counts[scanRegNumber][0][message["energyIndex"]], (self.zPts, self.xPts))
                xScale = 1 #float(self.xRange) / float(self.xPts)
                yScale = 1 #float(self.xPts) / float(self.zPts)
                pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
            elif "Line Spectrum" in self.scan["type"]:
                self.image = self.stxm.counts[scanRegNumber][0].T #np.reshape(self.stxm.counts[scanRegNumber][0], (self.xPts, nEnergies))
                xScale = 1 #float(self.xRange) / float(self.xPts)
                yScale = 1 #float(self.zRange) / float(self.zPts)
                pos = (self.xCenter - float(self.xRange) / 2., self.yCenter - float(self.yRange) / 2.)
            if self.ui.channelSelect.currentText() == "Diode":
                self.currentImageType = self.scan["type"]
                self.imageCenter = pos
                self.imageScale = xScale,yScale
                self.ui.mainImage.setImage(self.image.T, autoRange=False, autoLevels=False, \
                        autoHistogramRange=False, pos = pos, scale = (xScale,yScale))
                self.ui.mainImage.autoRange()
                self.updateImageLabels()
                self.scaleBarLength = np.round(100. / self.ui.mainImage.imageItem.pixelSize()[0] * self.imageScale[0],3)
                if self.scaleBarLength < 1.:
                    self.ui.scaleBarLength.setText(str(self.scaleBarLength * 1000.) + " nm")
                else:
                    self.ui.scaleBarLength.setText(str(self.scaleBarLength) + " um")
        elif message["type"] == "monitor":
            if self.ui.plotType.currentText() == "Monitor":
                if self.yPlot is not None:
                    self.ui.mainPlot.removeItem(self.yPlot)
                if self.xPlot is not None:
                    self.ui.mainPlot.removeItem(self.xPlot)
                self.updatePlot(message["data"][0])
        try: 
            self.updateImageFromCCD(message["ccd_frame"])
        except:
            pass
        xPos = self.currentMotorPositions["SampleX"]
        yPos = -self.currentMotorPositions["SampleY"]
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
        self.setMotorLabel(self.ui.energyLabel,str(np.round(self.currentMotorPositions["Energy"],2)), status)
        self.setMotorLabel(self.ui.energyLabel_2, str(np.round(self.currentMotorPositions["Energy"], 2)), status)
        Motor1 = str(self.ui.motorMover1.currentText())
        Motor2 = str(self.ui.motorMover2.currentText())
        status = self.currentMotorStatus[Motor1]
        self.setMotorLabel(self.ui.motorMover1Pos,str(np.round(self.currentMotorPositions[Motor1],3)),status)
        status = self.currentMotorStatus[Motor2]
        self.setMotorLabel(self.ui.motorMover2Pos,str(np.round(self.currentMotorPositions[Motor2],3)), status)
        status = self.currentMotorStatus["DISPERSIVE_SLIT"]
        self.setMotorLabel(self.ui.dsLabel,str(np.round(self.currentMotorPositions["DISPERSIVE_SLIT"], 2)),status)
        status = self.currentMotorStatus["NONDISPERSIVE_SLIT"]
        self.setMotorLabel(self.ui.ndsLabel,str(np.round(self.currentMotorPositions["NONDISPERSIVE_SLIT"], 2)),status)
        status = self.currentMotorStatus["POLARIZATION"]
        self.setMotorLabel(self.ui.polLabel,str(np.round(self.currentMotorPositions["POLARIZATION"], 2)),status)
        status = self.currentMotorStatus["M101PITCH"]
        self.setMotorLabel(self.ui.m101Label,str(np.round(self.currentMotorPositions["M101PITCH"], 2)),status)
        status = self.currentMotorStatus["FBKOFFSET"]
        self.setMotorLabel(self.ui.fbkLabel,str(np.round(self.currentMotorPositions["FBKOFFSET"], 2)),status)
        status = self.currentMotorStatus["EPUOFFSET"]
        self.setMotorLabel(self.ui.epuLabel,str(np.round(self.currentMotorPositions["EPUOFFSET"], 2)),status)
        self.ui.harSpin.setValue(int(self.currentMotorPositions["HARMONIC"]))

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
            if "Image" in self.nx.meta["scan_type"]:
                self.ui.scanFileName.setText(self.currentLoadFile.split('/')[-1])
                self.setScanParams()
                self.image = self.nx.data["entry0"]["counts"]
                self.currentImageType = self.nx.meta["scan_type"]
                z,y,x = self.image.shape
                self.zPts,self.yPts,self.xPts = z,y,x
                if z == 1:
                    self.image = np.reshape(self.image, (y,x))
                    axes = (1,0)
                else:
                    axes = (0,2,1)
                xpos = self.nx.data['entry0']['xpos']
                ypos = self.nx.data['entry0']['ypos']
                self.xRange = xpos.max()-xpos.min()
                self.xPts = xpos.size
                self.xCenter = xpos.min() + self.xRange / 2.
                self.yRange = ypos.max()-ypos.min()
                self.yPts = ypos.size
                self.yCenter = ypos.min() + self.yRange / 2.
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
                self.scanFromNX()
            else:
                pass

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
        if "Image" in self.nx.meta["scan_type"]:
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
                self.xRange = self.nx.data["entry"+str(i)]["xpos"].max() - self.nx.data["entry"+str(i)]["xpos"].min()
                self.yRange = self.nx.data["entry"+str(i)]["ypos"].max() - self.nx.data["entry"+str(i)]["ypos"].min()
                self.xCenter = self.nx.data["entry"+str(i)]["xpos"].min() + self.xRange / 2.
                self.yCenter = self.nx.data["entry"+str(i)]["ypos"].min() + self.yRange / 2.
                self.xStep = self.xRange / x
                self.yStep = self.yRange / y
                self.scanRegList[i].ui.xCenter.setText(str(np.round(self.xCenter, 3)))
                self.scanRegList[i].ui.yCenter.setText(str(np.round(-self.yCenter, 3)))
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
            self.lastScan["Image"] = self.scan
            self.stxm.energies = self.nx.data["entry0"]["energy"]
            self.updateImageLabels()

    def updateImageLabels(self):
        self.ui.pixelSizeLabel.setText(str(np.round(self.xStep,3)) + " um")
        self.ui.dwellTimeLabel.setText(str(self.dwell) + " ms")
        self.ui.imageEnergyLabel.setText(str(self.energy) + " eV")

    def updateTimeIndex(self):
        energyIndex = self.ui.mainImage.currentIndex
        self.energy = self.stxm.energies[energyIndex]
        self.updateImageLabels()

    def setGUIfromScan(self, scan, energyOnly = False):
        nScanRegions = len(scan["scanRegions"])
        nEnergyRegions = len(scan["energyRegions"])
        self.setSingleEnergy()
        self.ui.energyRegSpinbox.setValue(nEnergyRegions)
        self.updateEnergyRegDef()
        for i in range(nEnergyRegions):
            self.energyRegList[i].energyDef.energyStart.setText(str(scan["energyRegions"]["EnergyRegion" + str(i+1)]["start"]))
            self.energyRegList[i].energyDef.energyStop.setText(str(scan["energyRegions"]["EnergyRegion" + str(i+1)]["stop"]))
            self.energyRegList[i].energyDef.energyStep.setText(str(scan["energyRegions"]["EnergyRegion" + str(i+1)]["step"]))
            self.energyRegList[i].energyDef.nEnergies.setText(str(scan["energyRegions"]["EnergyRegion" + str(i+1)]["nEnergies"]))
            self.energyRegList[i].energyDef.dwellTime.setText(str(scan["energyRegions"]["EnergyRegion" + str(i+1)]["dwell"]))
        if not(energyOnly):
            nScanRegions = len(scan["scanRegions"].keys())
            self.ui.scanRegSpinbox.setValue(nScanRegions)
            for i in range(nScanRegions):
                self.xRange = scan["scanRegions"]["Region" + str(i+1)]["xRange"]
                self.yRange = scan["scanRegions"]["Region" + str(i+1)]["yRange"]
                self.xCenter = scan["scanRegions"]["Region" + str(i+1)]["xCenter"]
                self.yCenter = scan["scanRegions"]["Region" + str(i+1)]["yCenter"]
                self.xStep = scan["scanRegions"]["Region" + str(i+1)]["xStep"]
                self.yStep = scan["scanRegions"]["Region" + str(i+1)]["yStep"]
                self.scanRegList[i].ui.xCenter.setText(str(np.round(self.xCenter, 3)))
                self.scanRegList[i].ui.yCenter.setText(str(np.round(-self.yCenter, 3)))
                self.scanRegList[i].ui.xRange.setText(str(np.round(self.xRange, 3)))
                self.scanRegList[i].ui.yRange.setText(str(np.round(self.yRange, 3)))
                self.scanRegList[i].ui.xNPoints.setText(str(scan["scanRegions"]["Region" + str(i+1)]["xPoints"]))
                self.scanRegList[i].ui.yNPoints.setText(str(scan["scanRegions"]["Region" + str(i+1)]["yPoints"]))
                self.scanRegList[i].ui.xStep.setText(str(self.xStep))
                self.scanRegList[i].ui.yStep.setText(str(self.yStep))
                self.regDefs[i][0] = np.round(self.xCenter, 3)
                self.regDefs[i][1] = np.round(self.yCenter, 3)
                self.regDefs[i][2] = np.round(self.xRange, 3)
                self.regDefs[i][3] = np.round(self.yRange, 3)
                self.regDefs[i][4] = scan["scanRegions"]["Region" + str(i+1)]["xPoints"]
                self.regDefs[i][5] = scan["scanRegions"]["Region" + str(i+1)]["yPoints"]
                self.regDefs[i][6] = self.xStep
                self.regDefs[i][7] = self.yStep
                self.updateROIfromRegion(i + 1)
        self.compileScan()
        self.lastScan[self.scan["type"]] = self.scan

    def addROI(self, range = (70, 70), center = (35, 35)):
        scanMode = self.client.scanConfig["scans"][self.ui.scanType.currentText()]["mode"]
        nROI = len(self.roiList) + 1
        colorIndex = nROI % len(self.penColors) - 1
        styleIndex = int((nROI / len(self.penColors)) % 2)
        roiPen = pg.mkPen(self.penColors[colorIndex],\
           width = 3, style = self.penStyles[styleIndex])
        xMin, xMax = float(center[0]) - float(range[0]) / 2, float(center[0]) + float(range[0]) / 2
        yMin, yMax = float(center[1]) - float(range[1]) / 2, float(center[1]) + float(range[1]) / 2
        if scanMode == "image":
            roi = pg.RectROI((xMin,yMin), range, snapSize = 5.0, pen = roiPen)
        elif scanMode == "line":
            roi = pg.LineSegmentROI(positions = ((xMin,center[1]),(xMax,center[1])), pen = roiPen)
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
        scanMode = self.client.scanConfig["scans"][self.ui.scanType.currentText()]["mode"]
        i = self.roiList.index(roi)
        regStr = 'Region' + str(i + 1)
        xPoints = int(self.scanRegList[i].ui.xNPoints.text()) #self.scan["scanRegions"][regStr]['xPoints']
        yPoints = int(self.scanRegList[i].ui.yNPoints.text()) #self.scan["scanRegions"][regStr]['yPoints']
        self.scanRegList[i].ui.noEmit = True
        if scanMode == "image":
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
        elif scanMOde == "line":
            x0 = roi.mapSceneToParent(roi.getHandles()[0].scenePos()).x()
            x1 = roi.mapSceneToParent(roi.getHandles()[1].scenePos()).x()
            y0 = roi.mapSceneToParent(roi.getHandles()[0].scenePos()).y()
            y1 = roi.mapSceneToParent(roi.getHandles()[1].scenePos()).y()
            self.xLineRange = np.abs(x1 - x0)
            self.yLineRange = np.abs(y1 - y0)
            xCenter = np.min((x0,x1)) + self.xLineRange / 2.
            yCenter = np.min((y0,y1)) + self.yLineRange / 2.
            length = np.sqrt((x1-x0)**2+(y1-y0)**2)
            try:
                if y0 > y1:
                    sign = -1
                else:
                    sign = 1
                self.lineAngle = sign * np.round(90.-np.abs(180.*np.arctan((x1-x0)/(y1-y0))/np.pi),1)
            except:
                pass
                #angle = 0
            self.ui.lineAngleEdit.setText(str(self.lineAngle))
            self.ui.lineLengthEdit.setText(str(np.round(length,3)))

        self.scanRegList[i].ui.xCenter.setText(str(np.round(xCenter,3)))
        self.scanRegList[i].ui.yCenter.setText(str(np.round(-yCenter,3)))
        self.regDefs[i][0] = np.round(xCenter, 3)
        self.regDefs[i][1] = np.round(yCenter, 3)
        self.scanRegList[i].ui.noEmit = False

    def updateGUIfromScan(self, scan):
        if len(self.scanRegList) < len([*scan["scanRegions"]]):
            while len(self.scanRegList) < len([*scan["scanRegions"]]):
                self.ui.scanRegSpinbox.setValue(len(self.scanRegList) + 1)
        elif len(self.scanRegList) > len([*scan["scanRegions"]]):
            while len(self.scanRegList) > len([*scan["scanRegions"]]):
                self.ui.scanRegSpinbox.setValue(len(self.scanRegList) - 1)
        for i in range(len([*scan["scanRegions"]])):
            regStr = [*scan["scanRegions"]][i]
            xStep = scan["scanRegions"][regStr]["xStep"]
            yStep = scan["scanRegions"][regStr]["yStep"]
            xRange = scan["scanRegions"][regStr]['xRange']
            yRange = scan["scanRegions"][regStr]['yRange']
            xCenter = scan["scanRegions"][regStr]['xCenter']
            yCenter = scan["scanRegions"][regStr]['yCenter']
            xPoints = scan["scanRegions"][regStr]['xPoints']
            yPoints = scan["scanRegions"][regStr]['yPoints']
            self.scanRegList[i].ui.xCenter.setText(str(np.round(xCenter,3)))
            self.scanRegList[i].ui.yCenter.setText(str(np.round(-yCenter,3)))
            self.scanRegList[i].ui.xRange.setText(str(np.round(xRange,3)))
            self.scanRegList[i].ui.yRange.setText(str(np.round(yRange,3)))
            self.scanRegList[i].ui.xStep.setText(str(xStep))
            self.scanRegList[i].ui.yStep.setText(str(yStep))
            self.scanRegList[i].ui.xNPoints.setText(str(xPoints))
            self.scanRegList[i].ui.yNPoints.setText(str(yPoints))
        self.energyRegList[0].energyDef.dwellTime.setText(str(scan["energyRegions"]["EnergyRegion1"]["dwell"]))
        self.setGUIfromScan(scan)
        self.compileScan()

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
            self.regDefs[i][1] = float(self.scanRegList[i].ui.yCenter.text())
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
            
        #Need to update the lastScan dict here as well
        scanType = self.ui.scanType.currentText()
        #for i in range(len(self.lastScan[scanType]['scanRegions'].keys())):

        # for i in range(len(self.scanRegList)):
        #     self.lastScan[scanType]['scanRegions']['Region'+str(i+1)]['xCenter'] = float(self.scanRegList[i].ui.xCenter.text())
        #     self.lastScan[scanType]['scanRegions']['Region'+str(i+1)]['yCenter'] = float(self.scanRegList[i].ui.yCenter.text())
        #     self.lastScan[scanType]['scanRegions']['Region'+str(i+1)]['xRange'] = float(self.scanRegList[i].ui.xRange.text())
        #     self.lastScan[scanType]['scanRegions']['Region'+str(i+1)]['yRange'] = float(self.scanRegList[i].ui.yRange.text())
        #     self.lastScan[scanType]['scanRegions']['Region'+str(i+1)]['xPoints'] = int(self.scanRegList[i].ui.xNPoints.text())
        #     self.lastScan[scanType]['scanRegions']['Region'+str(i+1)]['yPoints'] = int(self.scanRegList[i].ui.yNPoints.text())
        #     self.lastScan[scanType]['scanRegions']['Region'+str(i+1)]['xStep'] = float(self.scanRegList[i].ui.xStep.text())
        #     self.lastScan[scanType]['scanRegions']['Region'+str(i+1)]['yStep'] = float(self.scanRegList[i].ui.yStep.text())

    @QtCore.pyqtSlot(np.intc)
    def updateROIfromRegion(self, regNum):
        self.updateRegionDefList()
        scanMode = self.client.scanConfig["scans"][self.ui.scanType.currentText()]["mode"]
        a = self.scanRegList[regNum - 1]
        xRange = float(a.ui.xRange.text())
        yRange = float(a.ui.yRange.text())
        xCenter = float(a.ui.xCenter.text())
        yCenter = -float(a.ui.yCenter.text())
        i = regNum - 1
        if scanMode == "image":
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
        elif scanMode == "line":
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
        a.ui.yCenter.setText(str(-self.regDefs[regNum][1]))
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
        if self.ui.scanRegSpinbox.value() > 1:
            self.ui.outerLoopCheckbox_2.setCheckState(QtCore.Qt.Unchecked)
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
            self.setSingleEnergy()

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
        self.client.connect(self.serverIP, self.serverCommandPort, self.serverDataPort)
        self.client.getMotorConfig()
        self.client.connectMonitor()
        self.client.monitor.scanData.connect(self.updateImageFromMessage)
        self.controlThread.controlResponse.connect(self.printToConsole)
        self.client.monitor.elapsedTime.connect(self.updateTime)
        self.client.monitor.scanDone.connect(self.endScan)
        try:
            self.client.ccd.framedata.connect(self.updateImageFromCCD)
            # addr = self.client.daqConfig["ccd"]["sub_address"]
            # port = self.client.daqConfig["ccd"]["sub_port"]
            # self.ccdMonitor = zmqFrameMonitor(sub_address = addr + ":" + str(port))
            # self.ccdMonitor.zmqFrameData.connect(self.updateImageFromCCD)
            # self.ccdMonitor.start()
        except:
            print("Cannot connect to CCD monitor")
        try:
            self.client.ptycho.ptychoData.connect(self.updateImageFromRPI)
            # addr = self.client.daqConfig["ptychography"]["sub_address"]
            # port = self.client.daqConfig["ptychography"]["sub_port"]
            # self.ptychoMonitor = zmqFrameMonitor(sub_address = addr + ":" + str(port))
            # self.ptychoMonitor.zmqFrameData.connect(self.updateImageFromRPI)
            # self.ptychoMonitor.start()
        except:
            print("Cannot connect to PTYCHO monitor")
        self.ui.beamToCursorButton.setEnabled(False)
        self.ui.serverAddress.setText(self.serverIP + ':' + str(self.serverCommandPort))
        self.serverStatus = self.client.getStatus()
        #self.messageThread = threading.Thread()  #this thread is needed later on

    def initGUI(self):
        self.currentMotorPositions = self.client.currentMotorPositions
        self.imageScanTypes = self.client.scanConfig["scans"].keys()
        for scanType in self.imageScanTypes:
            self.ui.scanType.addItem(scanType)
        self.ui.energyLabel.setText(str(self.currentEnergy) + ' eV')
        self.ui.focusCenterEdit.setText(str(self.currentMotorPositions["ZonePlateZ"]))
        self.nMotors = len(self.client.motorInfo.keys())

        #The motors should be added to the drop down lists in particular locations according to their index
        keys = list(self.client.motorInfo.keys())
        idx = [self.client.motorInfo[key]['index'] for key in keys]
        keys = [keys[i] for i in idx]
        idx.sort()
        for key in keys:
            if self.client.motorInfo[key]["display"]:
                self.ui.motorMover1.addItem(key)
                self.ui.motorMover2.addItem(key)
                self.ui.outerLoopMotor.addItem(key)
        self.ui.motorMover2.setCurrentIndex(1)
        xMotor = self.scan["x"]
        yMotor = self.scan["y"]
        xMax = self.client.motorInfo[xMotor]["maxValue"] - 10
        xMin = self.client.motorInfo[xMotor]["minValue"] + 10
        yMax = self.client.motorInfo[yMotor]["maxValue"] - 10
        yMin = self.client.motorInfo[yMotor]["minValue"] + 10
        self.xRange = xMax - xMin

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
        self.setGUIfromScan(self.lastScan["Image"])
        self.setSingleEnergy()
        self.activateGUI()

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
        self.ui.xMotor.clear()
        self.ui.yMotor.clear()
        self.ui.xMotor.addItem(self.client.scanConfig["scans"][scanType]["xMotor"])
        self.ui.yMotor.addItem(self.client.scanConfig["scans"][scanType]["yMotor"])
        if "Focus" in scanType:
            self.updateFocus()
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
            #self.updateScanRegFromROI(self.roiList[-1])
            self.setSingleEnergy()
            self.ui.beamToCursorButton.setEnabled(False)
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
            #self.ui.lineLengthEdit.setText(str(self.scanRegList[0].ui.xRange.text()))
            # self.ui.flyscanCheckbox.setEnabled(False)
            self.ui.doubleExposureCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.doubleExposureCheckbox.setEnabled(False)
            if self.rangeROI is not None:
                self.ui.mainImage.removeItem(self.rangeROI)
            # self.ui.serpentineCheckbox.setCheckState(QtCore.Qt.Unchecked)
            # self.ui.serpentineCheckbox.setEnabled(False)
            self.updateLine()
        elif "Line" in scanType:
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
            self.updateScanRegFromROI(self.roiList[-1])
            self.ui.doubleExposureCheckbox.setCheckState(QtCore.Qt.Unchecked)
            self.ui.doubleExposureCheckbox.setEnabled(False)
            # self.ui.flyscanCheckbox.setEnabled(True)
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
            # self.ui.flyscanCheckbox.setEnabled(False)
            # self.ui.serpentineCheckbox.setCheckState(QtCore.Qt.Unchecked)
            # self.ui.serpentineCheckbox.setEnabled(False)
            if self.rangeROI is not None:
                self.ui.mainImage.removeItem(self.rangeROI)
            self.updateLine()
        else:
            for reg in self.scanRegList:
                reg.setEnabled(True)
            self.ui.energyRegSpinbox.setEnabled(True)
            self.ui.scanRegSpinbox.setEnabled(True)
            self.ui.beamToCursorButton.setEnabled(False)
            self.ui.focusToCursorButton.setEnabled(False)
            self.setFocusWidgets(False)
            self.setLineWidgets(False)
            self.ui.roiCheckbox.setEnabled(True)
            self.setGUIfromScan(self.lastScan[scanType])
            # if len(self.scanRegList) > 0:
            #     #self.setGUIfromScan(self.lastScan[scanType])
            #     #self.updateROIfromRegion(1)
            #     if self.lastScan["Image"]["serpentine"]:
            #         self.ui.serpentineCheckbox.setCheckState(QtCore.Qt.Checked)
            self.ui.toggleSingleEnergy.setCheckState(QtCore.Qt.Checked)
            self.ui.toggleSingleEnergy.setEnabled(True)
            self.setSingleEnergy()
            if "Ptychography" in scanType:
                # self.ui.flyscanCheckbox.setCheckState(QtCore.Qt.Unchecked)
                # self.ui.flyscanCheckbox.setEnabled(False)
                # self.ui.serpentineCheckbox.setCheckState(QtCore.Qt.Unchecked)
                # self.ui.serpentineCheckbox.setEnabled(False)
                self.ui.doubleExposureCheckbox.setEnabled(True)
                self.ui.defocusCheckbox.setEnabled(True)
            else:
                # self.ui.flyscanCheckbox.setEnabled(True)
                # self.ui.flyscanCheckbox.setCheckState(QtCore.Qt.Checked)
                self.ui.doubleExposureCheckbox.setCheckState(QtCore.Qt.Unchecked)
                self.ui.doubleExposureCheckbox.setEnabled(False)
                self.ui.defocusCheckbox.setEnabled(False)
            if not(self.currentImageType == self.ui.scanType.currentText()):
                if scanType != "Ptychography Image":
                    self.ui.mainImage.clear()
                if self.horizontalLine is not None:
                    self.ui.mainImage.removeItem(self.horizontalLine)
                if self.verticalLine is not None:
                    self.ui.mainImage.removeItem(self.verticalLine)
            if self.ui.showRangeFinder.isChecked():
                if self.rangeROI is not None:
                    self.ui.mainImage.addItem(self.rangeROI)


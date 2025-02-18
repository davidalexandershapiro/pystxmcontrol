import os.path
import pyqtgraph as pg
from PySide6 import QtWidgets, QtCore
from numpy import array, fliplr, log
from pystxmcontrol.utils.image import despike
from pystxmcontrol.utils.image import image
from pystxmcontrol.utils.general import find_nearest
from .linescanreader_mainwindow import Ui_CustomWidget
import matplotlib.pyplot as plt


class lineScanReaderWidget(QtWidgets.QWidget, QtCore.QObject):

    def __init__(self, parent=None):
        super(lineScanReaderWidget, self).__init__(parent=parent)

        self.currentBGPlot = None
        self.currentBG = None
        self.currentSpecPlot = None
        self.currentSpec = None
        self.od = None
        self.offset = 0.0
        self.statusOD = False
        self.imageData = None
        self.energies = None
        self.statusMain = False
        self.statusBG = False

        # set up the form class as a `ui` attribute
        self.ui = Ui_CustomWidget()
        self.ui.setupUi(self)

        # access your UI elements through the `ui` attribute
        self.region = pg.LinearRegionItem(orientation = pg.LinearRegionItem.Horizontal)
        self.region.setZValue(10)
        self.region.setRegion([10, 20])
        # simple demonstration of pure Qt widgets interacting with pyqtgraph
        self.ui.linearRegionCheckBox.stateChanged.connect(self.toggleLinearRegion)
        self.ui.backgroundCheckBox.stateChanged.connect(self.toggleBGButton)
        self.ui.displayOD.stateChanged.connect(self.toggleODButton)
        self.region.sigRegionChanged.connect(self.getRegionData)
        self.ui.fileLoadButton.clicked.connect(self.getFileName)
        self.ui.fileSaveButton.clicked.connect(self.saveData)
        self.ui.dataOffset.setText(str(0.0))
        self.ui.dataOffset.textChanged.connect(self.updateOffset)
        self.ui.fileSaveButton.clicked.connect(self.saveData)
        self.ui.bgPlotWidget.setLabel('bottom', 'Energy', units = 'eV')
        self.ui.specPlotWidget.setLabel('bottom', 'Energy', units = 'eV')
        self.ui.bgPlotWidget.setLabel('left', 'Transmission', units = 'AU')
        self.ui.specPlotWidget.setLabel('left', 'Transmission',)
        self.ui.specPlotWidget.scene().sigMouseMoved.connect(self.mouseEnergySelectFromPlot)

        self.penColors = ['r','g','b','y','c','m']
        self.roiLineWidth = 4
        self.plotLineWidth = 2
        self.plotPen = pen=pg.mkPen('w',width=self.plotLineWidth, style = QtCore.Qt.SolidLine)
        self.penStyles = [QtCore.Qt.SolidLine, QtCore.Qt.DashLine]
        self.ui.bgPlotWidget.showGrid(x = True, y = True)
        self.ui.bgPlotWidget.setMouseEnabled(x = False, y = False)
        self.ui.bgPlotWidget.enableAutoRange()#Scale()
        self.ui.specPlotWidget.showGrid(x = True, y = True)
        self.ui.specPlotWidget.setMouseEnabled(x = False, y = False)
        self.ui.specPlotWidget.enableAutoRange()#Scale()

    def mouseEnergySelectFromPlot(self, pos):
        if self.currentSpec is not None:
            vb = self.ui.specPlotWidget.plotItem.vb
            if self.ui.specPlotWidget.plotItem.sceneBoundingRect().contains(pos):
                mousePoint = vb.mapSceneToView(pos)
                energyIdx = find_nearest(self.energies,mousePoint.x())
                self.ui.energyLabel.setText("Energy = %s eV" %str(self.energies[energyIdx+1]))
                self.ui.dataLabel.setText("Data = %.2f" %self.currentSpec[energyIdx+1])

    def receiveLinescan(self, fileName):
        self.currentLoadFile = fileName
        self.openData()

    def writeHeader(self,f,fileHeader):
        for key in fileHeader.keys():
            f.write(key + ',' + str(fileHeader[key]) + '\n')

    def saveData(self):
        if self.currentBG is not None:
            self.currentFileExtension = os.path.splitext(self.currentLoadFile)[1]
            I0CSVFile = self.currentLoadFile.replace(self.currentFileExtension,'_I0.csv')
            spectrumCSVFile = self.currentLoadFile.replace(self.currentFileExtension,'_spectrum.csv')

            fileHeader = {  'STXM File: ': self.currentLoadFile, \
                            'Data Offset: ': self.offset, \
                            'Data type: ': 'Optical density'}
            f = open(spectrumCSVFile,'w')
            self.writeHeader(f,fileHeader)
            for i in range(len(self.currentSpec)):
                f.write(str(self.energies[i]) + ',' + str(self.currentSpec[i]) + '\n')
            f.close()

            fileHeader = {  'STXM File: ': self.currentLoadFile, \
                            'Data Offset: ': self.offset, \
                            'Data type: ': 'I0'}
            f = open(I0CSVFile,'w')
            self.writeHeader(f,fileHeader)
            for i in range(len(self.currentSpec)):
                f.write(str(self.energies[i]) + ',' + str(self.currentBG[i]) + '\n')
            f.close()

            plt.plot(self.energies, self.currentSpec)
            plt.xlabel('Energy (eV)')
            plt.ylabel('Optical Density')
            plt.title(self.currentLoadFile)
            plt.savefig(self.currentLoadFile.replace(self.currentFileExtension,'_spectrum.png'),dpi = 100)
            plt.clf()

    def updateOffset(self):
        self.offset = float(self.ui.dataOffset.text())
        self.getOD()
        self.updateMainImage()
        self.updatePlots()

    def initializeGUI(self):
        self.statusMain = True
        self.statusBG = False
        self.currentBG = None
        self.currentSpec = None
        self.od = None
        self.offset = 0.0
        self.statusOD = False
        self.statusBG = False
        self.ui.backgroundCheckBox.setCheckState(QtCore.Qt.Unchecked)
        self.ui.displayOD.setCheckState(QtCore.Qt.Unchecked)
        self.offset = 0.0
        self.ui.dataOffset.setText(str(0.0))

    def openData(self):
        self.im = image(file = self.currentLoadFile)

        if (self.im.type != 'NEXAFS Line Scan') and (self.im.type != 'Line Spectrum'):
            print("Not a Line Scan data file!")
        else:
            ##Ignore last column (energy) of data as it's null
            if "hdr" in self.currentLoadFile:
                self.energies = self.im.hdr['energies'][1:-1]
            else:
                self.energies = self.im.energy[1:-1]
            self.imageData = despike(self.im.processedFrame.T)
        self.initializeGUI()
        self.updateMainImage()

    def getFileName(self):
        self.currentLoadFile = str(QtWidgets.QFileDialog.getOpenFileName(QtWidgets.QWidget(), \
            'Open File', '/')[0])
        try: self.openData()
        except IOError: print("No Such File or Directory.")

    def getOD(self):
        try: self.od = -log((self.imageData.transpose() - self.offset) / (self.currentBG - self.offset)).transpose()
        except: pass

    def getBG(self,minY,maxY):
        try: self.currentBG = self.imageData[:,minY:maxY].mean(axis = 1)
        except: pass

    def toggleODButton(self, state):
        if state == QtCore.Qt.Checked:
            self.ui.backgroundCheckBox.setCheckState(QtCore.Qt.Unchecked)
            self.statusOD = True
            self.getOD()
        else:
            self.statusOD = False
        self.updateMainImage()

    def toggleBGButton(self, state):
        if state == QtCore.Qt.Checked:
            self.ui.displayOD.setCheckState(QtCore.Qt.Unchecked)
            self.statusBG = True
        else:
            self.statusBG = False

    def getRegionData(self):
        minY, maxY = self.region.getRegion()
        minY, maxY = int(minY), int(maxY)
        if self.statusBG:
            self.getBG(minY,maxY)
        if self.statusOD:
            self.getOD()
            self.currentSpec = self.od[:,minY:maxY].mean(axis = 1)
        else:
            self.currentSpec = self.imageData[:,minY:maxY].mean(axis = 1)
        self.updatePlots()

    def updatePlots(self):
        if self.statusBG:
            if self.currentBGPlot != None:
                self.ui.bgPlotWidget.removeItem(self.currentBGPlot)
            self.currentBGPlot = self.ui.bgPlotWidget.plot(self.energies, self.currentBG, pen = self.plotPen)
        else:
            if self.currentSpecPlot != None:
                self.ui.specPlotWidget.removeItem(self.currentSpecPlot)
            self.currentSpecPlot = self.ui.specPlotWidget.plot(self.energies, self.currentSpec, pen = self.plotPen)

    def updateMainImage(self):
        if self.statusOD:
            try:
                self.ui.mainImage.setImage(self.od)
            except:
                pass
            self.ui.specPlotWidget.setLabel('left', 'Optical Density',)
        else:
            self.ui.mainImage.setImage(self.imageData)
            self.ui.specPlotWidget.setLabel('left', 'Transmission',)

    def toggleLinearRegion(self, state):
        if state == QtCore.Qt.Checked:
            enabled = True
            self.ui.mainImage.addItem(self.region, ignoreBounds=False)
        else:
            enabled = False
            self.ui.mainImage.removeItem(self.region)
        self.ui.bgPlotWidget.setMouseEnabled(x=enabled, y=enabled)


if __name__ == '__main__':

    app = QtWidgets.QApplication([])
    widget = lineScanReaderWidget()
    widget.show()
    app.exec_()

from PySide6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from .stack_mainwindow import Ui_stackViewer
from .filterwindowwidget import filterWindowWidget
from .registerwindowwidget import registerWindowWidget
from .pca_mainwindow import Ui_pcaViewer
from .stackImportwindowwidget import stackImportWindow
from .bkgwindowwidget import bkgWindowWidget
from pystxmcontrol.utils.general import find_nearest
from pystxmcontrol.utils.stack import stack
from pystxmcontrol.utils.image import image
from skimage.io import imsave
import os
import numpy as np
import calendar, time
from skimage.io import imsave
import scipy.misc
import ntpath
import matplotlib.pyplot as plt

class CircleItem(pg.GraphicsObject):
    def __init__(self, center, pen):
        pg.GraphicsObject.__init__(self)
        self.center = center
        self.radius = 1
        self.pen = pen
        self.generatePicture()

    def generatePicture(self):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        p.setPen(self.pen)
        p.drawEllipse(self.center[0], self.center[1],self.radius,self.radius)
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QtCore.QRectF(self.picture.boundingRect())

class scaleBar(pg.GraphicsObject):
    def __init__(self, dims, length, pixelSize, color = 'w'):
        pg.GraphicsObject.__init__(self)
        self.y, self.x = dims
        self.pen = pg.mkPen('b', width = 14, style = QtCore.Qt.SolidLine)
        self.x0 = int(0.05 * self.x)
        self.x1 = self.x0 + length
        self.y0 = self.y - self.x0
        self.y1 = self.y0
        self.font = QtGui.QFont("Helvetica [Cronyx]", max(int(0.02 * self.x),4))
        self.length, self.pixelSize = length, pixelSize
        self.size = np.round(self.length * self.pixelSize, decimals = 1)
        self.generatePicture()

    def generatePicture(self):
        self.picture = QtGui.QPicture()
        p = QtGui.QPainter(self.picture)
        p.setPen(self.pen)
        p.setFont(self.font)
        p.drawLine(self.x0, self.y0, self.x1, self.y1)
        p.drawText(self.x1 + max(int(0.02 * self.x),4), self.y1 + 1, str(self.size) + ' um')
        p.end()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return QtCore.QRectF(self.picture.boundingRect())

class pcaWidget(QtWidgets.QDialog, Ui_pcaViewer):
    def __init__(self,parent=None):
        QtWidgets.QDialog.__init__(self,parent)
        self.setupUi(self)
        self.stack = None
        self.stackSlider.valueChanged.connect(self.updateImageDisplays)
        self.pcaSlider.valueChanged.connect(self.updateImageDisplays)
        self.calcButton.clicked.connect(self.calculatePCA)
        self.mapButton.clicked.connect(self.componentsToRGB)
        self.pcaCombo.currentIndexChanged.connect(self.updateGUI)
        self.stackCombo.currentIndexChanged.connect(self.updateGUI)
        self.plotCombo.currentIndexChanged.connect(self.updateSpectrumPlot)
        self.spectraBin = []
        self.spectraBinPlots = []
        self.penColors = [(255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),(0,255,255)]
        self.penStyles = [QtCore.Qt.SolidLine, QtCore.Qt.DashLine]
        self.stackMaps.scene.sigMouseMoved.connect(self.mouseMoved)
        self.mouseY, self.mouseX = 0,0
        self.nPCCombo.setCurrentIndex(4)
        self.nClustersCombo.setCurrentIndex(2)
        self.targetSpectra = []
        self.preEdgeButton.stateChanged.connect(self.togglePreEdge)
        self.saveButton.clicked.connect(self.saveAll)
        self.resize(1200,750)

    def saveAll(self):
        self.stack.saveAll(filePrefix = "test")

    def togglePreEdge(self):
        if self.stack.filteredImages is not None:
            if self.preEdgeButton.isChecked(): self.stack.removePreEdge()
            else: self.stack.addPreEdge()
            self.calculatePCA()

    def mouseMoved(self, pos):
        data = self.stackMaps.image  # or use a self.data member
        sh = data.shape
        if len(sh) == 2: nRows, nCols = sh
        elif len(sh) == 3: nRows, nCols, c = sh

        scenePos = self.stackMaps.getImageItem().mapFromScene(pos)
        self.mouseY, self.mouseX = int(scenePos.y()), int(scenePos.x())

        if (0 <= self.mouseX < nRows - 1) and (0 <= self.mouseY < nCols - 1):
            self.updateSpectrumPlot()
        else:
            self.mouseY, self.mouseX = 0,0
            self.updateSpectrumPlot()

    def calculatePCA(self):
        pcaOffset = int(self.massCheckBox.isChecked())
        try:
            self.stack.calcPCA(nPC = int(self.nPCCombo.currentIndex() + 1), \
                nClusters = int(self.nClustersCombo.currentIndex()) + 1, pcaOffset = pcaOffset)
        except:
            print("Clustering failed.  Try fewer clusters.")
        else:
            self.spectraBin = self.stack.targetSpectra
            self.updateRGBCombos()
            self.clustersToRGB()
            self.componentsToRGB()
            self.updateGUI()
            self.updateImageDisplays()
            self.updateSpectrumPlot()

    def updateRGBCombos(self):
        itemList = ['None'] + ['Cluster ' + str(i + 1) for i in range(int(self.nClustersCombo.currentIndex()) + 1)]
        self.redCombo.clear(); self.redCombo.addItems(itemList)
        self.greenCombo.clear(); self.greenCombo.addItems(itemList)
        self.blueCombo.clear(); self.blueCombo.addItems(itemList)

    def getTargetSpectra(self):
        """
        Select target spectra from the RGB combo boxes.  These are a subset of
        the stack.clusterSpectra which are determined from all clusters.
        """
        if self.stack.pcaImages is not None:
            self.targetSpectra = []
            self.rgb = [0,0,0]
            if self.redCombo.currentIndex() != 0:
                self.rgb[0] = 1
                self.targetSpectra.append(self.stack.clusterSpectra[self.redCombo.currentIndex() - 1])
            if self.greenCombo.currentIndex() != 0:
                self.rgb[1] = 1
                self.targetSpectra.append(self.stack.clusterSpectra[self.greenCombo.currentIndex() - 1])
            if self.blueCombo.currentIndex() != 0:
                self.rgb[2] = 1
                self.targetSpectra.append(self.stack.clusterSpectra[self.blueCombo.currentIndex() - 1])

    def componentsToRGB(self):
        if self.stack.pcaImages is not None:
            self.getTargetSpectra()
            if self.targetSpectra == []:
                targetSpectra = self.stack.clusterSpectra[0:3]
                self.rgb = [1,1,1]
            else: targetSpectra = self.targetSpectra
            print(len(targetSpectra), len(self.targetSpectra), self.rgb)
            self.stack.rgbMap(targetSpectra, self.rgb)
            self.updateImageDisplays()

    def updateGUI(self):
        if self.stack is not None:
            if self.stackCombo.currentText() == "Stack Frames":
                self.stackSlider.setValue(0)
                self.stackSlider.setMaximum(len(self.stack.rawFrames) - 1)
            if self.stack.pcaImages is not None:
                self.pcaSlider.setValue(0)
                if self.pcaCombo.currentText() == 'PCA Images':
                    self.pcaSlider.setMaximum(len(self.stack.pcaImages) - 1)
                elif self.pcaCombo.currentText() == 'Clusters':
                    self.pcaSlider.setMaximum(0)
                if self.stackCombo.currentText() == "R-factor Map":
                    self.stackSlider.setValue(0)
                    self.stackSlider.setMaximum(0)
                elif self.stackCombo.currentText() == "RGB Map":
                    self.stackSlider.setValue(0)
                    self.stackSlider.setMaximum(0)
                elif self.stackCombo.currentText() == "PCA Filtered Stack Frames":
                    self.stackSlider.setValue(0)
                    self.stackSlider.setMaximum(len(self.stack.filteredImages) - 1)
                elif self.stackCombo.currentText() == "Component Maps":
                    self.stackSlider.setValue(0)
                    self.stackSlider.setMaximum(len(self.stack.targetSVDmaps) - 1)
        self.updateImageDisplays()

    def updateImageDisplays(self):
        if self.stack is not None:
            if self.stackCombo.currentText() == "Stack Frames":
                self.stackMaps.setImage(self.stack.odFrames[self.stackSlider.value()].T)
            if self.stack.pcaImages is not None:
                if self.pcaCombo.currentText() == 'PCA Images':
                    self.pcaMaps.setImage(self.stack.pcaImages[self.pcaSlider.value()].T)
                elif self.pcaCombo.currentText() == 'Clusters':
                    self.pcaMaps.setImage(self.rgbClusterImage)
                if self.stackCombo.currentText() == 'PCA Filtered Stack Frames':
                    self.stackMaps.setImage(self.stack.filteredImages[self.stackSlider.value()].T)
                elif self.stackCombo.currentText() == 'R-factor Map':
                    self.stackMaps.setImage(self.stack.rMap.T)
                elif self.stackCombo.currentText() == 'Component Maps':
                    self.stackMaps.setImage(self.stack.targetSVDmaps[self.stackSlider.value()].T)
                elif self.stackCombo.currentText() == 'RGB Map':
                    self.stackMaps.setImage(np.transpose(self.stack.rgbImage, axes = (1,0,2)))

    def showClusterMap(self):
        a = pg.image(self.rgbClusterImage.T)

    def clearPlots(self):
        while len(self.spectraBinPlots) > 0:
            self.spectraPlot.removeItem(self.spectraBinPlots[0])
            del(self.spectraBinPlots[0])

    def clustersToRGB(self):
        #self.rgbClusterImage = np.transpose(self.rgbClusterImage * 255. / self.rgbClusterImage.max(), axes = (1,0,2))
        self.rgbClusterImage = np.transpose(self.stack.rgbClusterMap(), axes = (1,0,2))

    def addPlots(self):
        try:
            self.legend.scene().removeItem(self.legend)
        except: pass

        if self.plotCombo.currentText() == 'Cluster Spectra':
            i = 0
            for spectrum in self.spectraBin:
                colorIndex = int(i % len(self.penColors))
                styleIndex = int((i / len(self.penColors)) % 2)
                pen = pg.mkPen(self.penColors[colorIndex],\
                   width = 2, style = self.penStyles[styleIndex])
                self.spectraBinPlots.append(self.spectraPlot.plot(self.stack.energies, \
                    spectrum, pen = pen, name = 'Cluster ' + str(i + 1)))
                i += 1
        elif self.plotCombo.currentText() == 'Eigen Values':
            self.spectraBinPlots.append(self.spectraPlot.plot(np.log(self.stack.eigenVals[:-1]), \
            pen = None, symbol = 'o', name = 'Eigen Values'))
        elif self.plotCombo.currentText() == 'Point Spectrum':
            self.spectraBinPlots.append(self.spectraPlot.plot(self.stack.odFrames[:,self.mouseY, self.mouseX],\
                pen = None, symbol = 'o', name = 'Point Spectrum'))
            self.spectraBinPlots.append(self.spectraPlot.plot(self.stack.filteredImages[:,self.mouseY, self.mouseX],
                pen = pg.mkPen('w', width = 2, style = QtCore.Qt.SolidLine), name = 'PCA Fit'))
        self.legend = self.spectraPlot.addLegend()

    def updateSpectrumPlot(self):
        if self.stack.pcaImages is not None:
            self.clearPlots()
            self.addPlots()


class stackViewerWidget(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super(stackViewerWidget, self).__init__(parent=parent)

        # set up the form class as a `ui` attribute
        self.ui = Ui_stackViewer()
        self.ui.setupUi(self)
        self.stack_file = None
        self.scaleBar = None
        self.viewFrames = None
        self.haveStack = False
        self.clickPoint = False
        self.currentSpecPlot = None
        self.currentSpec = None
        self.rgbImage = None
        self.roiSpecList = []
        self.roiSpecPlotList = []
        self.penColors = [(255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),(0,255,255)]
        self.roiLineWidth = 3
        self.plotLineWidth = 1
        self.vb = None
        self.offset = 0.0
        self.pointPens = []
        self.roiPens = []
        self.iRegion = 0
        self.mainPlotPen = pg.mkPen('w',width=self.plotLineWidth, style = QtCore.Qt.SolidLine)
        self.penStyles = [QtCore.Qt.SolidLine, QtCore.Qt.DashLine]
        self.ui.specPlot.showGrid(x = True, y = True)
        self.ui.specPlot.setMouseEnabled(x = False, y = False)
        self.ui.specPlot.enableAutoRange()
        self.ui.verticalSlider.valueChanged.connect(self.updateDisplay)
        self.ui.autoButton.clicked.connect(self.autoProcess)
        self.ui.mainImage.scene.sigMouseMoved.connect(self.mouseMoved)
        self.ui.mainImage.scene.sigMouseClicked.connect(self.mouseClicked)
        self.ui.addROIButton.clicked.connect(self.createROI)
        self.ui.clearROIButton.clicked.connect(self.clearROI)
        self.ui.registerButton.clicked.connect(self.registerWindow)
        self.ui.filterButton.clicked.connect(self.filterWindow)
        self.ui.specPlot.scene().sigMouseMoved.connect(self.mouseEnergySelectFromPlot)
        self.ui.mapButton.clicked.connect(self.mapROIspectra)
        self.ui.saveButton.clicked.connect(self.saveAllData)
        self.ui.stackLoadButton.clicked.connect(self.getFileName)
        self.ui.resetButton.clicked.connect(self.reset)
        self.ui.trackMouseBox.setCheckState(QtCore.Qt.Checked)
        self.ui.scaleBox.setCheckState(QtCore.Qt.Checked)
        self.ui.scaleBox.stateChanged.connect(self.toggleScaleBar)
        self.ui.trackMouseBox.stateChanged.connect(self.toggleTrackMouse)
        self.ui.toggleOD.stateChanged.connect(self.toggleOD)
        self.ui.preEdgeBox.stateChanged.connect(self.togglePreEdge)
        self.ui.pcaButton.clicked.connect(self.pcaWindow)
        self.stackImportWindow = stackImportWindow()
        self.ui.bkgRemovalButton.clicked.connect(self.bkgWindow)
        self.bkgWindow = bkgWindowWidget()
        self.ui.regionSelect.currentIndexChanged.connect(self.changeRegion)
        self.ui.importButton.clicked.connect(self.importWindow)
        self.ui.deleteButton.clicked.connect(self.deleteFrame)
        self.ui.darkLineEdit.textChanged.connect(self.updateDark)

    def updateDark(self):
        if self.haveStack:
            try: 
                d = float(self.ui.darkLineEdit.text())
                self.stack.darkField = d
            except:
                pass
            else:
                print("Changed dark field values to:", self.stack.darkField)

    def deleteFrame(self):
        if len(self.stack.rawFrames) > 2:
            self.stack.deleteFrame(energy = self.stack.energies[self.ui.verticalSlider.value()])
            sliderVal = self.ui.verticalSlider.value()
            self.initializeGUI()
            if sliderVal > 0: self.ui.verticalSlider.setValue(sliderVal - 1)
            else: self.ui.verticalSlider.setValue(0)
            self.updateMainImage()

    def importWindow(self):
        if self.haveStack:
            self.stackImportWindow.baseStack = self.stack
            self.stackImportWindow.importStack = None
            self.stackImportWindow.updateGUI()
            self.stackImportWindow.exec_()

    def changeRegion(self):
        self.reset()
        print(self.ui.regionSelect.currentIndex())
        self.stack = stack(fileName = self.stack_file, iRegion = self.ui.regionSelect.currentIndex())
        self.iRegion = self.ui.regionSelect.currentIndex()
        self.haveStack = True
        self.ui.verticalSlider.setMaximum(len(self.stack.energies) - 1)
        self.updateMainImage()

    def toggleTrackMouse(self):
        if self.haveStack:
            self.updatePlot()

    def togglePreEdge(self):
        if self.haveStack and self.stack.odFrames is not None:
            if not(self.ui.preEdgeBox.isChecked()): self.stack.intercept = 0.
            self.updateROISpecs()
            self.updatePlot()
        elif self.haveStack:
            self.ui.preEdgeBox.setCheckState(QtCore.Qt.Unchecked)
        else:
            self.ui.preEdgeBox.setCheckState(QtCore.Qt.Unchecked)

    def toggleScaleBar(self):
        if self.scaleBar is None:
            self.ui.scaleBox.setCheckState(QtCore.Qt.Checked)
        elif self.ui.scaleBox.isChecked():
            self.ui.mainImage.addItem(self.scaleBar)
        else:
            self.ui.mainImage.removeItem(self.scaleBar)
        self.updateMainImage()


    def toggleOD(self):
        if self.haveStack and self.stack.I0 is not None:
            if self.ui.toggleOD.isChecked(): self.stack.calcOD()
            self.updateMainImage()
            self.updateROISpecs()
            self.updatePlot()
        elif self.haveStack:
            self.ui.toggleOD.setCheckState(QtCore.Qt.Unchecked)
            self.updateMainImage()
        else:
            self.ui.toggleOD.setCheckState(QtCore.Qt.Unchecked)

    def mouseClicked(self, pos):
        if self.haveStack and self.clickPoint:
            data = self.ui.mainImage.image.transpose()  # or use a self.data member
            nRows, nCols = data.shape
            scenePos = self.ui.mainImage.getImageItem().mapFromScene(pos.pos())
            row, col = int(scenePos.y()), int(scenePos.x())

            if (0 <= row < nRows) and (0 <= col < nCols):
                nROI = len(self.stack.rois)
                colorIndex = int(nROI % len(self.penColors))
                styleIndex = int((nROI / len(self.penColors)) % 2)
                roiPlotPen = pg.mkPen(self.penColors[colorIndex],\
                   width=self.plotLineWidth, style = self.penStyles[styleIndex])
                roiPen = pg.mkPen(color = self.penColors[colorIndex],\
                   width=self.roiLineWidth, style = self.penStyles[styleIndex])
                circ = CircleItem((col,row),roiPen)
                self.stack.rois.append({'type': 'point','region': circ, 'point': (col,row), \
                    'imagePen':roiPen, 'plotPen':roiPlotPen})
                self.ui.mainImage.addItem(circ)
                self.roiSpecPlotList.append(None)
                self.updateROISpecs()
                self.updatePlot()
            else:
                pass
        self.clickPoint = False

    def getFileName(self):
        self.stack_file = str(QtWidgets.QFileDialog.getOpenFileName(QtWidgets.QWidget(), \
            'Open File', '/')[0])
        if self.stack_file != '':
            try: self.receiveStack(self.stack_file)
            except IOError:print("No Such File or Directory.")

    def mapROIspectra(self):
        if self.haveStack:
            if (len(self.stack.spectra) > 1) and self.ui.toggleOD.isChecked():
                if self.ui.preEdgeBox.isChecked():
                    offset = 1.
                else: offset = 0.
                self.stack.linFitSpectra(self.stack.odFrames - self.stack.odFrames[0] * offset, self.stack.spectra)
                nSpectra, ny, nx = self.stack.targetSVDmaps.shape
                self.rgbImage = np.zeros((ny,nx,3))
                svdMaps = self.stack.targetSVDmaps
                if nSpectra < 7:
                    for i in range(nSpectra):
                        self.rgbImage += np.transpose(np.ones((3,ny,nx)) * svdMaps[i], \
                            axes = (1,2,0)) * self.penColors[i]
                a = pg.image(np.transpose(self.rgbImage * 255. / self.rgbImage.max(), axes = (1,0,2)))
                if self.ui.scaleBox.isChecked(): a.addItem(self.scaleBar)
            elif len(self.stack.rawFrames) == 2:
                if self.stack.odFrames is None:
                    self.stack.despike()
                    self.stack.alignFrames()
                    self.stack.calcOD()
                    self.stack.denoise()
                    self.stack.alignODFrames(mode = 'affine')
                a = pg.image((self.stack.odFrames[1] - self.stack.odFrames[0]).T)
                if self.ui.scaleBox.isChecked(): a.addItem(self.scaleBar)

    def writeHeader(self,f,fileHeader):
        for key in fileHeader.keys():
            f.write(key + ',' + str(fileHeader[key]) + '\n')

    def saveAllData(self):
        if self.haveStack:
            print("saving all data!")
            dataDir, dataFile = ntpath.split(self.stack_file)
            filePrefix = dataFile.split('.')[0]
            saveDir = os.path.join(dataDir, filePrefix + '_pystxmOutput_' + str(calendar.timegm(time.gmtime())))
            os.mkdir(saveDir)
            imsave(os.path.join(saveDir, "intensityFrames.tif"), self.stack.processedFrames.astype('float32'))
            if self.stack.odFrames is not None:
                imsave(os.path.join(saveDir, "odFrames.tif"), self.stack.odFrames.astype('float32'))
            if self.stack.targetSVDmaps is not None:
                if self.rgbImage is not None:
                    imsave(os.path.join(saveDir, 'rgbMap.jpg'), self.rgbImage)
                for i in range(len(self.stack.targetSVDmaps)):
                    imsave(os.path.join(saveDir, "map_" + str(i) + '.tif'), \
                        self.stack.targetSVDmaps[i].astype('float32'))
                self.ui.mainImage.getImageItem().save(os.path.join(saveDir, 'displayImage.png'))
            if len(self.stack.spectra) != 0:
                spectrumCSVFile = os.path.join(saveDir,'roiSpectra.csv')
                fileHeader = {  'STXM HDR File: ': self.stack_file, \
                                'Data Offset: ': self.offset, \
                                'Data type: ': 'Optical density'\
                                'Energy, I0, ROI Spectra'}
                f = open(spectrumCSVFile,'w')
                self.writeHeader(f,fileHeader)
                nEnergies = len(self.stack.energies)
                nSpectra = len(self.stack.spectra)
                for i in range(nEnergies):
                    if self.stack.I0 is not None:
                        I0str = str(self.stack.I0[i,0,0])
                    else:
                        I0str = ''
                    thisStr = str(self.stack.energies[i]) + ',' + I0str
                    for j in range(nSpectra):
                        thisStr += ',' + str(self.stack.spectra[j][i])
                    thisStr += '\n'
                    f.write(thisStr)
                f.close()
                for spectrum in self.stack.spectra:
                    plt.plot(self.stack.energies, spectrum)
                plt.xlabel('Energy (eV)')
                plt.ylabel('Optical Density')
                plt.title(self.stack_file)
                plt.savefig(os.path.join(saveDir,'spectra.png'), dpi = 100)
                plt.clf()
                plt.plot(self.stack.energies, self.stack.I0[:,0,0])
                plt.xlabel('Energy (eV)')
                plt.ylabel('I0')
                plt.title(self.stack_file)
                plt.savefig(os.path.join(saveDir,'I0.png'), dpi = 100)
                plt.clf()

    def filterWindow(self):
        window = filterWindowWidget()
        if self.haveStack:
            window.stack = self.stack
            window.updateGUI()
        window.exec_()
        # if self.haveStack:
        #     self.filterWindow.stack = self.stack
        #     self.filterWindow.updateGUI()
        # self.filterWindow.exec_()
        self.updateMainImage()

    def pcaWindow(self):
        window = pcaWidget()
        if self.haveStack and (self.stack.odFrames is not None):
            window.stack = self.stack
            window.updateGUI()
            window.exec_()

    def registerWindow(self):
        window = registerWindowWidget()
        if self.haveStack:
            window.stack = self.stack
            window.updateGUI()
        window.exec_()
        self.updateMainImage()
        
    def bkgWindow(self):
        if self.haveStack :
            self.bkgWindow.stack = self.stack   
            self.bkgWindow.viewFrames = self.stack.rawFrames.copy()
            self.bkgWindow.stack_file = self.stack_file
            self.bkgWindow.updateGUI()
        self.bkgWindow.exec_()
        

    def clearROI(self):
        if str(self.ui.spectraComboBox.currentText()) == 'I0':
            if (len(self.stack.I0rois) > 0):
                self.ui.mainImage.removeItem(self.stack.I0rois[-1]['region'])
                del(self.stack.I0rois[-1])
                self.stack.updateI0()
        else:
            print("Clearing ROI...")
            if (len(self.stack.rois) > 0):
                print("clearing ROI")
                self.ui.mainImage.removeItem(self.stack.rois[-1]['region'])
                del(self.stack.rois[-1])
                self.ui.specPlot.removeItem(self.roiSpecPlotList[-1])
                del(self.roiSpecPlotList[-1])
                del(self.stack.spectra[-1])

    def createROI(self):
        if self.haveStack:
            if str(self.ui.spectraComboBox.currentText()) == "ROI":
                nROI = len(self.stack.rois)
                colorIndex = int(nROI % len(self.penColors))
                styleIndex = int((nROI / len(self.penColors)) % 2)
                roiPen = pg.mkPen(self.penColors[colorIndex],\
                   width=self.roiLineWidth, style = self.penStyles[styleIndex])
                roiPlotPen = pg.mkPen(color = self.penColors[colorIndex],\
                   width=self.plotLineWidth, style = self.penStyles[styleIndex])
                self.roiPens.append(roiPlotPen)
                roi = pg.EllipseROI([0,0], [10, 10], snapSize = 5.0, pen = roiPen)
                roi.sigRegionChanged.connect(self.updateROISpecs)
                self.ui.mainImage.addItem(roi)
                print(len(self.stack.rois))
                self.stack.rois.append({'type': 'ellipse','region':roi, 'imagePen':roiPen, \
                    'plotPen': roiPlotPen, 'image': self.ui.mainImage.getImageItem()})
                print(len(self.stack.rois))
                self.roiSpecPlotList.append(None)
                self.updateROISpecs()
                self.updatePlot()
                print(len(self.stack.rois),nROI)
            elif str(self.ui.spectraComboBox.currentText()) == "Point":
                self.clickPoint = True
            elif str(self.ui.spectraComboBox.currentText()) == 'I0':
                self.createI0ROI()

    def createI0ROI(self):
        if self.haveStack:
            nROI = len(self.stack.I0rois)
            roiPen = pg.mkPen('b',\
               width=self.roiLineWidth, style = QtCore.Qt.DashLine)
            roi = pg.EllipseROI([0,0], [10, 10], snapSize = 5.0, pen = roiPen)
            roi.sigRegionChanged.connect(self.updateROISpecs)
            self.ui.mainImage.addItem(roi)
            self.stack.I0rois.append({'type': 'ellipse','region':roi, 'imagePen':roiPen, \
                'plotPen': roiPen, 'image': self.ui.mainImage.getImageItem()})
            self.updateROISpecs()
            self.updatePlot()

    def reset(self):
        if self.haveStack:
            self.ui.toggleOD.setCheckState(QtCore.Qt.Unchecked)
            self.ui.preEdgeBox.setCheckState(QtCore.Qt.Unchecked)
            self.stack.odFrames = None
            self.stack.I0 = None
            self.stack.reset()
            self.updateMainImage()
        for i in range(len(self.stack.I0rois)):
            self.ui.mainImage.removeItem(self.stack.I0rois[-1]['region'])
            del(self.stack.I0rois[-1])
            self.stack.updateI0()
        for i in range(len(self.stack.rois)):
            self.clearROI()
        self.stack.I0rois = []
        self.stack.rois = []

    def mouseMoved(self, pos):
        if self.haveStack:
            if self.ui.toggleOD.isChecked(): viewFrames = self.stack.odFrames
            else: viewFrames = self.stack.processedFrames
            data = self.ui.mainImage.image  # or use a self.data member
            nRows, nCols = data.shape

            scenePos = self.ui.mainImage.getImageItem().mapFromScene(pos)
            col, row = int(scenePos.y()), int(scenePos.x())

            if (0 <= row < nRows - 1) and (0 <= col < nCols - 1):
                if self.ui.preEdgeBox.isChecked():
                     self.currentSpec = viewFrames[:,col,row] - viewFrames[:,col,row].min()
                else:
                    self.currentSpec = viewFrames[:,col,row]
                self.updatePlot()
            else:
                pass

    def updateROISpecs(self):
        self.stack.spectraFromROIS(OD = self.ui.toggleOD.isChecked(), \
            removePreEdge = self.ui.preEdgeBox.isChecked())
        if len(self.stack.I0rois) > 0: self.stack.updateI0()
        self.updatePlot()

    def updatePlot(self):
        if self.haveStack:
            if self.currentSpecPlot is not None:
                self.ui.specPlot.removeItem(self.currentSpecPlot)
            if self.currentSpec is not None and self.ui.trackMouseBox.isChecked():
                self.currentSpecPlot = self.ui.specPlot.plot(self.stack.energies, \
                    self.currentSpec, pen = self.mainPlotPen)
        if self.haveStack and (len(self.stack.rois) > 0):
            for i in range(len(self.stack.rois)):
                if self.roiSpecPlotList[i] is not None:
                    self.ui.specPlot.removeItem(self.roiSpecPlotList[i])
                self.roiSpecPlotList[i] = self.ui.specPlot.plot(self.stack.energies, \
                    self.stack.spectra[i], pen = self.stack.rois[i]['plotPen'])

    def autoProcess(self):
        if self.haveStack:
            self.stack.subtractDarkField()
            self.stack.despike()
            self.stack.alignFrames(mode = 'translation')
            self.stack.calcOD()
            self.ui.toggleOD.setCheckState(QtCore.Qt.Checked)
            self.updateMainImage()

    def filterImages(self):
        if self.haveStack:
            self.stack.medianFilter()

    def receiveStack(self, fileName):
        self.initializeGUI()
        self.stack_file = fileName
        self.stack = stack(fileName = self.stack_file)
        self.haveStack = True
        self.ui.verticalSlider.setMaximum(len(self.stack.energies) - 1)
        self.ui.frameEnergy.setText("Energy = %s eV" %str(self.stack.energies[self.ui.verticalSlider.value()]))
        self.ui.fileName.setText(self.stack_file)
        if ".hdr" in fileName:
            self.nRegion = self.stack.hdr['nRegions']
        elif ".stxm" in fileName:
            self.nRegion = self.stack.nx.nRegions
        self.updateMainImage()
        self.updateRegionCombo()

    def stack_from_nx(self,nxdata):
        self.stack = stack()
        self.stack.nx = nxdata
        self.stack.energies = self.stack.nx.energies
        self.stack.rawFrames = []
        ne,ny,nx = self.stack.nx.interp_counts[self.iRegion].shape
        for i in range(ne):
            im = image(data = self.stack.nx.interp_counts[self.iRegion][i])
            im.energy = self.stack.energies[i]
            im.xpixelsize = self.stack.nx.xstepsize[self.iRegion]
            im.ypixelsize = self.stack.nx.ystepsize[self.iRegion]
            im.nypixels, im.nxpixels = im.data.shape
            self.stack.rawFrames.append(im)
        self.stack.xpixelsize = im.xpixelsize
        self.stack.ypixelsize = im.ypixelsize
        self.stack.reset()
        self.stack.shape = self.stack.processedFrames.shape
    
    def _update_stack(self,nxdata):
        self.stack.nx = nxdata
        self.stack.rawFrames = []
        ne,ny,nx = self.stack.nx.interp_counts[self.iRegion].shape
        for i in range(ne):
            im = image(data = self.stack.nx.interp_counts[self.iRegion][i])
            im.energy = self.stack.energies[i]
            im.xpixelsize = self.stack.nx.xstepsize[self.iRegion]
            im.ypixelsize = self.stack.nx.ystepsize[self.iRegion]
            im.nypixels, im.nxpixels = im.data.shape
            self.stack.rawFrames.append(im)
        self.stack.processedFrames = np.array(nxdata.interp_counts[0])

    def recv_live_data(self, nxdata, scanInfo):
        if self.ui.live_display.isChecked():
            if nxdata.NXfile == self.stack_file:
                self._update_stack(nxdata)
            else:
                self.stack_from_nx(nxdata)
                self.stack_file = scanInfo["scanID"]
                self.haveStack = True
            self.ui.verticalSlider.setMaximum(len(self.stack.energies) - 1)
            self.ui.frameEnergy.setText("Energy = %s eV" %str(self.stack.energies[scanInfo["energyIndex"]]))
            self.ui.verticalSlider.setValue(scanInfo["energyIndex"])
            self.ui.fileName.setText(self.stack_file)
            self.nRegion = len(self.stack.nx.interp_counts)
            self.updateMainImage()
            self.updateRegionCombo()

    def updateRegionCombo(self):
        nItems = self.ui.regionSelect.count()
        if self.nRegion > nItems:
            for i in range(nItems, self.nRegion):
                item = 'Region ' + str(i + 1)
                self.ui.regionSelect.addItem(item)
        elif self.nRegion < nItems:
            for i in range(self.nRegion, nItems)[::-1]:
                self.ui.regionSelect.removeItem(i)

    def updateDisplay(self):
        self.ui.frameEnergy.setText("Energy = %s eV" %str(self.stack.energies[self.ui.verticalSlider.value()]))
        self.updateMainImage()

    def mouseEnergySelectFromPlot(self, pos):
        if self.haveStack and self.ui.trackMouseBox.isChecked():
            vb = self.ui.specPlot.plotItem.vb
            if self.ui.specPlot.plotItem.sceneBoundingRect().contains(pos):
                mousePoint = vb.mapSceneToView(pos)
                mouseEnergy = mousePoint.x()
                stackIndex = find_nearest(self.stack.energies,mouseEnergy)
                self.ui.verticalSlider.setValue(stackIndex)
            self.updateDisplay()

    def initializeGUI(self):
        self.ui.regionSelect.setCurrentIndex(0)
        self.currentSpec = None
        if self.haveStack:
            self.ui.verticalSlider.setMaximum(len(self.stack.energies) - 1)
            for i in range(len(self.stack.rois)):
                self.ui.mainImage.removeItem(self.stack.rois[-1]['region'])
                del(self.stack.rois[-1])
                self.ui.specPlot.removeItem(self.roiSpecPlotList[-1])
                del(self.roiSpecPlotList[-1])
            for i in range(len(self.stack.I0rois)):
                self.ui.mainImage.removeItem(self.stack.I0rois[-1]['region'])
                del(self.stack.I0rois[-1])
        self.ui.verticalSlider.setValue(0)
        self.ui.toggleOD.setCheckState(QtCore.Qt.Unchecked)
        self.ui.preEdgeBox.setCheckState(QtCore.Qt.Unchecked)

    def updateMainImage(self):
        if self.haveStack:
            if (self.scaleBar is not None) and self.ui.scaleBox.isChecked():
                self.ui.mainImage.removeItem(self.scaleBar)
            if self.ui.toggleOD.isChecked(): color = 'w'
            else: color = 'k'
            self.scaleBar = scaleBar((self.stack.processedFrames.shape[1::]), \
                self.stack.scaleBarLength(), self.stack.xpixelsize, color)
            if self.ui.scaleBox.isChecked(): self.ui.mainImage.addItem(self.scaleBar)
            if self.ui.toggleOD.isChecked():
                self.ui.mainImage.setImage(self.stack.odFrames[self.ui.verticalSlider.value()].T)
            else:
                self.ui.mainImage.setImage(self.stack.processedFrames[self.ui.verticalSlider.value()].T)

if __name__ == '__main__':

    app = QtWidgets.QApplication([])
    widget = stackViewerWidget()
    widget.show()
    app.exec_()

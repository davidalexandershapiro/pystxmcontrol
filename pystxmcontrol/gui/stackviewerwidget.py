from PySide6 import QtWidgets, QtCore, QtGui
import pyqtgraph as pg
from .stack_mainwindow import Ui_stackViewer
from pystxmcontrol.utils.general import find_nearest
from pystxmcontrol.utils.stack import stack
from pystxmcontrol.utils.image import image
from skimage.io import imsave
import os
import numpy as np
import calendar, time
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

class stackViewerWidget(QtWidgets.QWidget):

    stack_loaded = QtCore.Signal()        # emitted after a stack is fully loaded/updated
    progress_updated = QtCore.Signal(int) # emitted during alignment with percent 0-100
    auto_process_done = QtCore.Signal()   # emitted specifically after autoProcess (OD ready)

    def __init__(self, parent=None):
        super(stackViewerWidget, self).__init__(parent=parent)

        # set up the form class as a `ui` attribute
        self.ui = Ui_stackViewer()
        self.ui.setupUi(self)

        # ── Post-setupUi layout: equal-width columns, shorter image, metadata ──
        # Remove mainImage from the horizontal layout so we can wrap it
        self.ui.horizontalLayout_main.removeWidget(self.ui.mainImage)

        # Remove horizontal stretch and cap the image height; keep it top-aligned
        sp = self.ui.mainImage.sizePolicy()
        sp.setHorizontalStretch(0)
        sp.setVerticalPolicy(QtWidgets.QSizePolicy.Policy.Maximum)
        self.ui.mainImage.setSizePolicy(sp)
        self.ui.mainImage.setMinimumHeight(600)
        self.ui.mainImage.setMaximumHeight(600)

        # Build left column: image pinned to top, metadata expands below
        self._left_widget = QtWidgets.QWidget()
        _left_vbox = QtWidgets.QVBoxLayout(self._left_widget)
        _left_vbox.setContentsMargins(0, 0, 0, 0)
        _left_vbox.setSpacing(4)
        _left_vbox.addWidget(self.ui.mainImage, stretch=0, alignment=QtCore.Qt.AlignTop)

        self.metadata_edit = QtWidgets.QTextEdit()
        self.metadata_edit.setReadOnly(True)
        self.metadata_edit.setMinimumHeight(80)
        _mono = QtGui.QFont("Monospace", 8)
        _mono.setStyleHint(QtGui.QFont.StyleHint.Monospace)
        self.metadata_edit.setFont(_mono)
        self.metadata_edit.setPlaceholderText("Load a stack to see scan metadata.")
        _left_vbox.addWidget(self.metadata_edit, stretch=1)

        # Insert left column at index 0; right side (verticalLayout_right) is index 1
        self.ui.horizontalLayout_main.insertWidget(0, self._left_widget, stretch=1)
        self.ui.horizontalLayout_main.setStretch(1, 1)
        # ────────────────────────────────────────────────────────────────────────

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
        self.ui.regionSelect.currentIndexChanged.connect(self.changeRegion)
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

    def changeRegion(self):
        self.reset()
        print(self.ui.regionSelect.currentIndex())
        self.stack = stack(fileName = self.stack_file, iRegion = self.ui.regionSelect.currentIndex())
        self.iRegion = self.ui.regionSelect.currentIndex()
        self.haveStack = True
        self.ui.verticalSlider.setMaximum(len(self.stack.energies) - 1)
        self.updateMainImage()
        self._populate_metadata()

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
        self.stack_file = str(QtWidgets.QFileDialog.getOpenFileName(self, \
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
        self.stack_loaded.emit()

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
            self.progress_updated.emit(0)
            self.stack.subtractDarkField()
            self.stack.despike()
            self.stack.alignFrames(mode='translation',
                                   progress_callback=lambda pct: self.progress_updated.emit(pct))
            self.stack.calcOD()
            self.ui.toggleOD.setCheckState(QtCore.Qt.Checked)
            self.updateMainImage()
            self.progress_updated.emit(100)
            self.stack_loaded.emit()
            self.auto_process_done.emit()

    def subtractDarkLevel(self, value):
        """Subtract a constant dark level from processedFrames (saves undo state first)."""
        if self.haveStack:
            self.stack.update()
            self.stack.processedFrames = self.stack.processedFrames - value
            self.stack_loaded.emit()

    def undoFilter(self):
        """Restore processedFrames from lastFrames via stack.undo()."""
        if self.haveStack:
            self.stack.undo()
            self.stack_loaded.emit()

    def applyMedianFilter(self, size):
        """Apply median filter with given kernel size (saves undo state first)."""
        if self.haveStack:
            self.stack.medianFilter(size=size)
            self.stack_loaded.emit()

    def applyDespike(self, kernel_size, n_sigma):
        """Apply despike with given kernel size and sigma threshold (saves undo state first)."""
        if self.haveStack:
            self.stack.despike(kernel_size=kernel_size, n_sigma=n_sigma)
            self.stack_loaded.emit()

    def applyPCA(self, n_components, n_clusters, reduce_mass_effects, remove_pre_edge):
        """Run PCA and k-means clustering.  Optionally remove pre-edge background first."""
        if not self.haveStack:
            return
        if self.stack.odFrames is None:
            self.stack.calcOD()
        pca_offset = 1 if reduce_mass_effects else 0
        if remove_pre_edge:
            self.stack.removePreEdge()
        self.stack.calcPCA(nPC=n_components, pcaOffset=pca_offset, nClusters=n_clusters)
        self.stack.rgbClusterImage = self.stack.rgbClusterMap()
        self.stack_loaded.emit()

    def applyRGBMap(self, cluster_indices):
        """Compute the RGB map from the selected cluster spectra (1-based indices)."""
        if not self.haveStack or not self.stack.clusterSpectra:
            return
        spectra = [self.stack.clusterSpectra[i - 1] for i in cluster_indices
                   if 0 < i <= len(self.stack.clusterSpectra)]
        n = len(spectra)
        if n < 2:
            return
        rgb = [1] * n + [0] * (3 - n)
        self.stack.rgbMap(spectra, rgb)
        self.stack_loaded.emit()

    def applyRegistration(self, mode, sobel_filter=False, autocrop=True):
        """Run frame registration with the given mode and options."""
        if self.haveStack:
            self.progress_updated.emit(0)
            self.stack.alignFrames(
                mode=mode,
                sobelFilter=sobel_filter,
                autocrop=autocrop,
                progress_callback=lambda pct: self.progress_updated.emit(pct)
            )
            self.progress_updated.emit(100)
            self.stack_loaded.emit()

    def filterImages(self):
        if self.haveStack:
            self.stack.medianFilter()

    def _populate_metadata(self):
        """Fill the metadata text panel from the currently loaded stack."""
        if not self.haveStack:
            return
        nx = getattr(self.stack, 'nx', None)
        if nx is None:
            return
        meta = getattr(nx, 'meta', {})

        def m(key):
            return meta.get(key, '')

        lines = [
            f"File:          {os.path.basename(m('file_name') or self.stack_file or '')}",
            f"Scan type:     {m('scan_type')}",
            f"Start time:    {m('start_time')}",
            f"End time:      {m('end_time')}",
            f"Experimenters: {m('experimenters')}",
            f"Sample:        {m('sample_description')}",
            f"Proposal:      {m('proposal')}",
            "\u2500" * 44,
        ]

        try:
            iReg = self.iRegion
            ne, ny_pts, nx_pts = nx.interp_counts["default"][iReg].shape
            dx = nx.xstepsize[iReg]
            dy = nx.ystepsize[iReg]
            lines.append(f"X range:       {nx_pts * dx:.3f} \u00b5m  ({nx_pts} pts, {dx:.4f} \u00b5m/pt)")
            lines.append(f"Y range:       {ny_pts * dy:.3f} \u00b5m  ({ny_pts} pts, {dy:.4f} \u00b5m/pt)")
        except Exception:
            pass

        try:
            energies = nx.energies["default"]
            if len(energies):
                lines.append(f"Energies:      {len(energies)}  ({energies[0]:.2f} \u2013 {energies[-1]:.2f} eV)")
        except Exception:
            pass

        try:
            dwells = nx.dwells
            if dwells is not None and len(dwells):
                lines.append(f"Dwell:         {dwells[0]:.1f} ms")
        except Exception:
            pass

        if m('x_motor'):
            lines.append(f"X motor:       {m('x_motor')}")
        if m('y_motor'):
            lines.append(f"Y motor:       {m('y_motor')}")

        self.metadata_edit.setPlainText("\n".join(lines))

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
        self._populate_metadata()
        self.stack_loaded.emit()

    def stack_from_nx(self,nxdata):
        self.stack = stack()
        self.stack.nx = nxdata
        self.stack.energies = self.stack.nx.energies["default"]
        self.stack.rawFrames = []
        ne,ny,nx = self.stack.nx.interp_counts["default"][self.iRegion].shape
        for i in range(ne):
            im = image(data = self.stack.nx.interp_counts["default"][self.iRegion][i])
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
        ne,ny,nx = self.stack.nx.interp_counts["default"][self.iRegion].shape
        for i in range(ne):
            im = image(data = self.stack.nx.interp_counts["default"][self.iRegion][i])
            im.energy = self.stack.energies[i]
            im.xpixelsize = self.stack.nx.xstepsize[self.iRegion]
            im.ypixelsize = self.stack.nx.ystepsize[self.iRegion]
            im.nypixels, im.nxpixels = im.data.shape
            self.stack.rawFrames.append(im)
        self.stack.processedFrames = np.array(nxdata.interp_counts["default"][0])

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
            self.nRegion = len(self.stack.nx.interp_counts["default"])
            self.updateMainImage()
            self.updateRegionCombo()
            self._populate_metadata()
            self.stack_loaded.emit()

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
                self.ui.mainImage.setImage(np.ascontiguousarray(self.stack.odFrames[self.ui.verticalSlider.value()].T))
            else:
                self.ui.mainImage.setImage(np.ascontiguousarray(self.stack.processedFrames[self.ui.verticalSlider.value()].T))

if __name__ == '__main__':

    app = QtWidgets.QApplication([])
    widget = stackViewerWidget()
    widget.show()
    app.exec_()

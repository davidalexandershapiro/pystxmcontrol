from PySide6 import QtWidgets, QtCore, QtGui
from pystxmcontrol.gui.bkg_mainwindow import Ui_bkgWindow

class bkgWindowWidget(QtWidgets.QDialog, Ui_bkgWindow):
    def __init__(self,parent=None):
        QtWidgets.QDialog.__init__(self,parent)
        self.setupUi(self)
        self.stack = None
        self.bkgRoi = None
        self.rawSlider.valueChanged.connect(self.updateMainImage)
        
        self.bkgSubtractSlider.valueChanged.connect(self.updateMainImage)
        self.LoadBKGFrameButton.clicked.connect(self.read_bkg_file)
        self.bkgRemovalButton.clicked.connect(self.bkgRemoval)
        self.bkgUndoButton.clicked.connect(self.bkgUndo)
        self.bkgApplyButton.clicked.connect(self.bkgApply)
        self.spectraBin = []
        self.spectraBinPlots = []
        self.roiSpecList = []
        self.roiSpecPlotList = []
        self.roiPens = []
        self.rois = []
        self.roiLineWidth = 3
        self.plotLineWidth = 1
        self.penColors = [(255,0,0),(0,255,0),(0,0,255),(255,255,0),(255,0,255),(0,255,255)]
        self.penStyles = [QtCore.Qt.SolidLine, QtCore.Qt.DashLine]
        self.rawMaps.scene.sigMouseMoved.connect(self.mouseMoved_rawMaps)
        
        self.setROIButton.clicked.connect(self.set_Bkg_ROI)
        self.getbkgFromROIButton.clicked.connect(self.get_Bkg_From_ROI)
        
        self.bkgSubtractMaps.scene.sigMouseMoved.connect(self.mouseMoved_bkgSubtractMaps)
        self.mouseY, self.mouseX = 0,0
        self.nRows = 0
        self.nCols = 0
        self.bkgRemoved = False
        #self.getbkgFromROIButton = False
        self.setROI = False
        self.setROIButton.setDisabled(True)
        self.getbkgFromROIButton.setDisabled(True)
        self.bkgRemovalButton.setDisabled(True)
        self.bkgUndoButton.setDisabled(True)
        self.bkgApplyButton.setDisabled(True)
        self.currentLoadFile = []
        #self.processedFrames = self.stack.rawFrames
                        

    def mouseMoved_rawMaps(self, pos): #from pcaWidget
        if self.stack is not None:
            #self.viewFrames = self.stack.rawFrames
            data = self.viewFrames
            sh = data.shape
            if len(sh) == 2: self.nRows, self.nCols = sh
            elif len(sh) == 3: c, self.nRows, self.nCols = sh
            scenePos = self.rawMaps.getImageItem().mapFromScene(pos)
            self.mouseY, self.mouseX = int(scenePos.y()), int(scenePos.x())
            if (0 <= self.mouseX < self.nRows - 1) and (0 <= self.mouseY < self.nCols - 1):
                self.updateSpectrumPlot()
            else:
                self.mouseY, self.mouseX = 0,0
                self.updateSpectrumPlot()
            
    
    def mouseMoved_bkgSubtractMaps(self, pos): #from pcaWidget
        if self.stack is not None:
            data = self.bkgSubtractMaps.image  # or use a self.data member
            sh = data.shape
            if len(sh) == 2: self.nRows, self.nCols = sh
            elif len(sh) == 3: self.nRows, self.nCols, c = sh
            scenePos = self.bkgSubtractMaps.getImageItem().mapFromScene(pos)
            self.mouseY, self.mouseX = int(scenePos.y()), int(scenePos.x())
            
            if (0 <= self.mouseX < self.nRows - 1) and (0 <= self.mouseY < self.nCols - 1):
                self.updateSpectrumPlot()
            else:
                self.mouseY, self.mouseX = 0,0
                self.updateSpectrumPlot()
           
    
    def getDwellTime(self):
        if (self.currentLoadFile != []):
            fname = self.currentLoadFile
            f = open(fname,mode='r')
            header_string = f.read()
            t = header_string.replace('\r\n','')
            f.close()
            t = t.upper()
            index1 = t.find('DWELL =')
            s = t[index1 : index1 + 10]
            index2 = s.find(';')
            dwell = s[len('Dwell =') : index2]
            self.rawDwell = float(dwell)

            self.bkgLoadFile = self.bkgLoadFile[:-9] + '.hdr'
            fileExtension = os.path.splitext(self.bkgLoadFile)[-1]
            if fileExtension == ".hdr":
                fname = self.bkgLoadFile
                f = open(fname,mode='r')
                header_string = f.read()
                t = header_string.replace('\r\n','')
                f.close()
                t = t.upper()
                index1 = t.find('DWELL =')
                s = t[index1 : index1 + 10]
                index2 = s.find(';')
                dwell = s[len('Dwell =') : index2]
                self.bkgDwell = float(dwell)
            else :
                QMessageBox.warning(self, "Oops!!", "Not a .hdr file & no dwell time")
                self.bkgDwell = self.rawDwell
            return self.rawDwell, self.bkgDwell
        else : 
            QMessageBox.warning(self, "Oops!!", "No rawframe were read..")
            return 1, 1
        
    
    def set_Bkg_ROI(self):
        if self.bkgImageData is not None: 
            for i in range(len(self.rois)):
                self.bkgMaps.removeItem(self.rois[-1]['region'])
                del(self.rois[-1])
            #self.updateMainImage()
            nROI = len(self.rois)
            colorIndex = nROI % len(self.penColors)
            styleIndex = (nROI / len(self.penColors)) % 2
            roiPen = pg.mkPen(self.penColors[colorIndex],\
               width=self.roiLineWidth, style = self.penStyles[styleIndex])
            roiPlotPen = pg.mkPen(color = self.penColors[colorIndex],\
               width=self.plotLineWidth, style = self.penStyles[styleIndex])
            self.roiPens.append(roiPlotPen)
            self.bkgRoi = pg.RectROI([10, 10], [50, 50], snapSize = 5.0, pen = roiPen)
            self.rois.append({'type': 'rectangula','region':self.bkgRoi, 'imagePen':roiPen, \
                    'plotPen': roiPlotPen, 'image': self.bkgMaps.getImageItem()})
            self.bkgMaps.addItem(self.bkgRoi)
            #self.roiSpecPlotList.append(None)
            self.setROI = True
            self.getbkgFromROIButton.setEnabled(True)


    def get_Bkg_From_ROI(self, pos):
        self.bkg_Count_Rate = 0.0
        data = self.bkgImageData
        sh = data.shape
        nRows, nCols = sh
        roiW, roiH = self.bkgRoi.size() # = self.bkgRoi.getState()['size']
        roiX, roiY = self.bkgRoi.getState()['pos']
        roiW, roiH = int(roiW), int(roiH)
        roiX, roiY = int(roiX), int(roiY)
        if (roiX < 0) or (roiY < 0) or (roiX + roiW > nRows) or (roiY + roiH > nCols):
            self.countRate.setText("ROI is out of frame...")
            QMessageBox.warning(self, "Warning", "ROI is out of frame...")
        else:
            temp = sum(data[roiX : roiX + roiW, roiY : roiY + roiH])
            denom = float(roiW * roiH)
            bkgSum = sum(temp) / denom
            self.bkg_Count_Rate = bkgSum / self.bkgDwell    # count_rate (pulse/sec)
            self.countRate.setText("Count_rate = %0.5f" %self.bkg_Count_Rate)
        if self.bkg_Count_Rate < 0.0:
            self.countRate.setText("Count_rate < 0.0")
            QMessageBox.warning(self, "Oops!!", "Subtracted counts are negative. Please try again")
        if self.stack is not None:
            self.bkgRemovalButton.setEnabled(True)
            self.bkgUndoButton.setEnabled(True)
        return(self.bkg_Count_Rate)
        
        
    def addPlots(self):
        self.rawSpectrum = self.viewFrames[:,self.mouseY,self.mouseX]
        self.bkgSpectrum = self.processedFrames[:,self.mouseY,self.mouseX]
        for i in range(2):
            colorIndex = i % len(self.penColors)
            styleIndex = (i / len(self.penColors)) % 2
            pen = pg.mkPen(self.penColors[colorIndex], width = 2, style = self.penStyles[styleIndex])
            if (i == 0):
                spectrum = self.rawSpectrum
            else :
                spectrum = self.bkgSpectrum 
            self.spectraBinPlots.append(self.bkgSpectra.plot(self.stack.energies, \
                spectrum, pen = pen))


    def bkgRemoval(self):
        self.backupFrame = self.viewFrames.copy()
        self.viewFrames = self.stack.rawFrames.copy()
        
        self.processedFrames = self.viewFrames - (self.bkg_Count_Rate * self.rawDwell)
        self.bkgRemoved = True
        self.updateGUI()
        #self.updateMainImage()
        self.updateSpectrumPlot()
        self.bkgUndoButton.setEnabled(True)
        self.bkgRemovalButton.setDisabled(True)

        
    def bkgApply(self): #From registerWindowWidget
        self.stack.rawFrames = self.processedFrames
        self.stack.processedFrames = self.processedFrames.copy()
        self.close()
        

    def clearPlots(self):
        while len(self.spectraBinPlots) > 0:
            self.bkgSpectra.removeItem(self.spectraBinPlots[0])
            del(self.spectraBinPlots[0])
        
        
    def updateSpectrumPlot(self):
        if self.bkgSpectra is not None:
            self.clearPlots()
            self.addPlots()

            
    def bkgUndo(self):     
        #self.bkgSubtractMaps = self.backupFrame
        #self.viewFrames = self.stack.rawFrames
        self.bkgUndoButton.setDisabled(True)
        self.bkgRemovalButton.setEnabled(True)
        self.bkgRemoved = False
        self.updateMainImage()
        self.updateSpectrumPlot()
    
       
    def updateMainImage(self):  #From registerWindowWidget,
        if self.stack is not None:
            self.rawMaps.setImage(self.viewFrames[self.rawSlider.value()].T)
            if self.bkgRemoved :
                self.bkgApplyButton.setEnabled(True)
                self.bkgUndoButton.setEnabled(True)
                self.bkgSubtractMaps.setImage(self.processedFrames[self.bkgSubtractSlider.value()].T)
            else: 
                self.processedFrames = self.stack.rawFrames.copy()
                self.bkgSubtractMaps.setImage(self.stack.processedFrames[self.bkgSubtractSlider.value()].T)
        else : 
            self.processedFrames = self.stack.rawFrames
            self.rawMaps.setImage(self.stack.rawFrames[self.rawSlider.value()].T)
            self.bkgSubtractMaps.setImage(self.processedFrames[self.bkgSubtractSlider.value()].T)
            

    def updateGUI(self):
        if self.stack is not None:
            self.rawSlider.setValue(0)
            self.rawSlider.setMaximum(len(self.stack.rawFrames) - 1)
            if self.bkgSubtractMaps is not None:
                self.bkgSubtractSlider.setValue(0)
                self.bkgSubtractSlider.setMaximum(len(self.stack.rawFrames) - 1)
            else : pass
        else : pass
        self.getbkgFromROIButton.setDisabled(True)
        self.updateMainImage()
               
        
    def read_bkg_file(self):
        self.bkgLoadFile = str(QtWidgets.QFileDialog.getOpenFileName(QtWidgets.QWidget(), \
            'Open File', '/')[0])
        if self.bkgLoadFile is not '':
            try: 
                self.bkgImageData = array([readASCIIMatrix(self.bkgLoadFile)])
                self.bkgImageData = rescale_intensity(self.bkgImageData[0], in_range=(0.,self.bkgImageData[0].max()), out_range=(0., 1.))
                self.bkgImageData = self.bkgImageData.T
                self.bkgMaps.setImage(self.bkgImageData) #.transpose())
            except IOError: print("No Such File or Directory.")
        
        if self.bkgImageData is not None: 
            self.setROIButton.setEnabled(True)
            if self.setROI:
                self.getbkgFromROIButton.setEnabled(True)
                if self.getbkgFromROIButton:
                    self.bkgRemovalButton.setEnabled(True)
                    self.bkgUndoButton.setEnabled(True)
                    self.bkgApplyButton.setEnabled(True)

        temp = self.bkgLoadFile[:]
        self.rawDwell, self.bkgDwell = self.getDwellTime()
        self.bkgLoadFile = temp

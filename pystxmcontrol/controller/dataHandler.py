from pystxmcontrol.utils.writeNX import stxm
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, as_completed
import time, os, datetime, threading, zmq
import numpy as np
from threading import Lock
import scipy

class dataHandler:
    def __init__(self, controller, logger = None):
        self.controller = controller
        self.daq = self.controller.daq
        self.dataQueue = Queue()
        self.scanQueue = self.controller.scanQueue
        self.main_config = self.controller.main_config
        self.lineScanModes = ["rasterLine", "continuousLine","continuousSpiral"]
        self.currentScanID = None
        self.monitorDaq = True
        self.ccd_data_port = self.main_config["server"]["ccd_data_port"]
        self.stxm_data_port = self.main_config["server"]["stxm_data_port"]
        self.stxm_file_port = self.main_config["server"]["stxm_file_port"]
        self.pause = False
        self._logger = logger
        self._lock = Lock()
        context = zmq.Context()

        if "ccd" in self.controller.daq.keys():
            #publish ccd data to the preprocessor
            self.controller.daq["ccd"].config(10, 0, 0)
            self.ccd_pub_address = 'tcp://%s:%s' % (self.main_config["server"]["host"],self.ccd_data_port)
            print("Publishing ccd frames on: %s" %self.ccd_pub_address)
            self.ccd_pub_socket = context.socket(zmq.PUB)
            self.ccd_pub_socket.set_hwm(2000)
            self.ccd_pub_socket.bind(self.ccd_pub_address)

        #publish stxm data to the gui
        #publish to other listeners like RPI reconstruction for instance
        self.stxm_pub_address = 'tcp://%s:%s' % (self.main_config["server"]["host"], self.stxm_data_port)
        print("Publishing stxm data on: %s" % self.stxm_pub_address)
        self.stxm_pub_socket = context.socket(zmq.PUB)
        self.stxm_pub_socket.bind(self.stxm_pub_address)

    def getScanName(self, dir = None, prefix = None, ptychography = False):
        """
        Just looks in the current days directory and finds the latest file
        number.  Returns today's directory and the next scan name.
        """
        baseDir = dir
        filePrefix = prefix
        now = datetime.datetime.now()
        yr = str(now.year)
        mo = str(now.month)

        if len(mo) == 1: mo = '0' + mo
        dy = str(now.day)
        if len(dy) == 1: dy = '0' + dy
        dayStr = yr[-2:] + mo + dy
        if not os.path.exists(os.path.join(baseDir, yr)):
            os.mkdir(os.path.join(baseDir, yr))
        if not os.path.exists(os.path.join(baseDir, yr, mo)):
            os.mkdir(os.path.join(baseDir, yr, mo))
        if not os.path.exists(os.path.join(baseDir, yr, mo, dayStr)):
            os.mkdir(os.path.join(baseDir, yr, mo, dayStr))
        scanDir = os.path.join(baseDir, yr, mo, dayStr)
        scanList = np.sort([x for x in os.listdir(scanDir) if filePrefix in x])
        if len(scanList) == 0:
            fileName = filePrefix + "_" + dayStr + "000.stxm"
        else:
            #lastScan = int(scanList[-1].split(filePrefix + '_')[1][6:9])
            lastScan = int(os.path.splitext(scanList[-1])[0].split(filePrefix + "_")[1].split(dayStr)[1].split("_")[0])
            if (lastScan + 1) < 10:
                nextScan = "00" + str(lastScan + 1)
            elif (lastScan + 1) < 100:
                nextScan = "0" + str(lastScan + 1)
            #elif (lastScan + 1) < 1000:
            else:
                nextScan = str(lastScan + 1)

            fileName = filePrefix + "_" + dayStr + nextScan + '.stxm'
        self.ptychoDir = os.path.join(scanDir,fileName.split('.')[0])
        self.currentScanID = os.path.join(scanDir, fileName)
        return self.currentScanID

    def fill2d(self,im):

        sigma = 5
        newim = np.copy(im)
        fim = scipy.signal.medfilt2d(im)  # default kernel size is 3.

        peakIndices = np.where(np.logical_and(im == 0,fim !=0))
        newim[peakIndices] = fim[peakIndices]
                   
        return(newim)


    def interpolate_points(self, scanInfo):
        ###TODO: need to get the oversampling factor into a config file and have it used by both the MCL and the DAQ.  Currently
        ###it is only used by the MCL and is hard coded.

        #For linear trajectories we only interpolate one line at a time and pass that to the STXM file and GUI
        #positions and data are measured along a well defined time coordinate since each point is sampled with the same dwell time.
        #users have requested a specific pixel size and dwell time.  If we sample the data at a fixed pixel size, the central pixels
        #will have the correct dwell time (where there is constant velocity) but the edge pixels will have non-constant dwell (where 
        #there is acceleration).
        #For spiral trajectories we interpolate the entire image area at once.

        #It will take a while to figure out the interpolation of the XRF spectra so the easiest thing to do here is run the interpolation
        #on the default DAQ is usual and also just the sum of the XRF spectra, so we at least get some image from the data
        #The full spectra will still be saved in the file under nx.counts["XRF"]

        try:
            if scanInfo["coarse_only"]:
                return scanInfo["rawData"]
        except:
            pass

        if not scanInfo["interpolate"]:
            return scanInfo["rawData"]

        if scanInfo["mode"] == "continuousLine":

            xReq = scanInfo["xVal"]
            yReq = scanInfo["yVal"]
            xstart = xReq[0]
            xstop = xReq[-1]
            ystart = yReq[0]
            ystop = yReq[-1]
            #direction here is a unit vector in the direction of the scan.
            direction = np.array([xstop-xstart,ystop-ystart])
            direction = direction/np.linalg.norm(direction)
            #We need to convert the requested and measured positions to distances along this direction.

            distReq = np.array([(xReq[i]-xstart)*direction[0]+(yReq[i]-ystart)*direction[1] for i in range(len(xReq))])
            #TODO: FIX THIS
            xMeas = scanInfo["line_positions"][0]
            yMeas = scanInfo["line_positions"][1]
            
            distMeas = np.array([(xMeas[i]-xstart)*direction[0]+(yMeas[i]-ystart)*direction[1] for i in range(len(xMeas))])

            #This doesn't assume even spacing of positions which is probably overkill.
            #Generate bins for np.histogram function.
            distBins = (distReq[1:]+distReq[:-1])/2
            distBins = np.append(distBins,2*distReq[-1]-distBins[-1])
            distBins = np.insert(distBins,0,2*distReq[0]-distBins[0])
            
            try:
                cutoff = np.where(distMeas>ddistBins[-1])[0][0]
            except:
                cutoff = np.where(distMeas == max(distMeas))[0][0]
                
            
            distMeas = distMeas[:cutoff]
            
            data = scanInfo["rawData"]["default"]["data"][:cutoff]
            
            if len(data)>len(distMeas):
                data = data[:len(distMeas)]
                
            elif len(distMeas)>len(data):
                distMeas = distMeas[:len(data)]
            

            #nEvents is just the number of times we had an x value in each of the bins. May be useful to track.
            nEvents,edges = np.histogram(distMeas,bins = distBins)
            #This is the total counts in each bin.
            binCounts,edges = np.histogram(distMeas,bins = distBins, weights = data)
            #Final counts are the counts per bin divided by the events.
            #The oversampling factor is put in here so that the count rate is independent of the oversampling factor.
            #For zero events in a bin, we replace the inf values with zero (and ignore error messages).
            with np.errstate(divide='ignore',invalid='ignore'):
                counts = binCounts/nEvents*scanInfo["oversampling_factor"]
            counts[np.isinf(counts)] = 0
            counts[np.isnan(counts)] = 0
            
            #Interpolate if the pixel is zero. This is most common for very small pixel sizes.
            for i in range(len(counts)):
                if counts[i] == 0:
                    if i != 0 and i != len(counts)-1:
                        if counts[i+1] != 0 and counts[i-1] != 0:
                            counts[i] = (counts[i+1]+counts[i-1])/2
                    elif i == 0:
                        if counts[1] != 0:
                            counts[0] = counts[1]
                    else:
                        if counts[-2] != 0:
                            counts[-1] = counts[-2]

        elif scanInfo["mode"] == "continuousSpiral":
            #Could do a similar method as above where we sample the spiral on an xy grid. This would use np.2dhistogram instead.
            #This would only work if there is at least 1 point per pixel.
            
            #First the requested x and y values
            xReq = scanInfo['xVal']
            yReq = scanInfo['yVal']
            
            #We will also need the bin edges. We assume here an evenly spaced grid so if that changes, we need to update this.
            dx = (xReq[-1]-xReq[0])/(len(xReq)-1)
            dy = (yReq[-1]-yReq[0])/(len(yReq)-1)
            
            xBins = np.append(xReq-dx/2,xReq[-1]+dx/2)
            yBins = np.append(yReq-dy/2,yReq[-1]+dy/2)
            
            region = int(scanInfo['scanRegion'].split('Region')[-1])-1
            
            #Next, the measured x and y values. Only take the ones which have been measured so far.
            mi = (scanInfo['index'])*scanInfo['line_positions'][0].size
            xMeasOld = self.data.xMeasured[region][scanInfo['energyIndex'],:mi]
            yMeasOld = self.data.yMeasured[region][scanInfo['energyIndex'],:mi]
            
            xMeas = np.append(xMeasOld,scanInfo['line_positions'][0])
            yMeas = np.append(yMeasOld,scanInfo['line_positions'][1])
            
            
            #Also, the raw data.
            di = (scanInfo['index'])*scanInfo["rawData"]["default"]["data"].size
            dataOld = self.data.counts["default"][region][scanInfo['energyIndex'],:di]
            data = np.append(dataOld,scanInfo["rawData"]["default"]["data"])
            
            #Determine the actual motor dwell and daq dwell. Determined by testing.
            motDwellOffset = 0.0 #ms
            if scanInfo['multiTrigger']:
                #Shouldn't need this if we are triggering off the motor position.
                DAQDwellOffset = 0.0 #ms
            else:
                DAQDwellOffset = 0.002275 #ms
            DAQdelay = 0.
            Motdelay = 0.
            actMotDwell = scanInfo['motorDwell']+motDwellOffset
            actDAQDwell = scanInfo['DAQDwell']+DAQDwellOffset
            
            
            if scanInfo['multiTrigger']:
                xytraj = np.arange(len(scanInfo['line_positions'][0]))*actMotDwell+Motdelay
                DAQsamples = int(len(data)/len(xMeas))
                DAQtraj = np.array([np.arange(DAQsamples)*actDAQDwell+val+actDAQDwell*0.5 for val in xytraj]).flatten() 
            else:
                #Find the times that each point was collected. Could need some work maybe.
                xytraj = np.arange(len(scanInfo['line_positions'][0]))*actMotDwell+Motdelay
                DAQtraj = np.arange(len(scanInfo["rawData"]["default"]["data"]))*actDAQDwell+DAQdelay
            
            endpoint = max(xytraj[-1],DAQtraj[-1])
            xy_tVals = np.array([xytraj+endpoint*i for i in range(scanInfo['index']+1)]).flatten()
            DAQ_tVals = np.array([DAQtraj+endpoint*i for i in range(scanInfo['index']+1)]).flatten()
            
            #xy_tVals = np.arange(len(xMeas))*scanInfo['motorDwell']
            #DAQ_tVals = np.arange(len(data))*scanInfo['DAQDwell']
            
            xInterp = np.interp(DAQ_tVals, xy_tVals, xMeas)
            yInterp = np.interp(DAQ_tVals, xy_tVals, yMeas)
            
            nEvents, ybins, xbins = np.histogram2d(yInterp, xInterp, bins = [yBins,xBins])
            binCounts, ybins, xbins = np.histogram2d(yInterp, xInterp, bins = [yBins,xBins], weights = data)
            
            with np.errstate(divide = 'ignore', invalid = 'ignore'):
                avCounts = binCounts/nEvents*scanInfo['DAQOversample']
            avCounts[np.isinf(avCounts)] = 0
            avCounts[np.isnan(avCounts)] = 0
            
            counts = avCounts
            
            #fill in empty pixels
            counts = self.fill2d(counts)

        return counts

    def addDataToStack(self, scanInfo):
        """This function puts the raw data into the data structure and returns the data that will be the "image" which the user analyzes.  This is also what is displayed
        in the GUI.  The philosophy here is that the scan driver decides what the correct indices are and this function just puts
        the data there.  So no need to calculate what "i" is here, for example.
        scanInfo["rawData"] is the uninterpolated data where as scanInfo["data"] is interpolated.  Not all scans need
        do the interpolation, like ptychography and single/double motor scans."""
        i = scanInfo["index"] #index along the long vector
        y = scanInfo["lineIndex"]
        j = i + scanInfo["rawData"].size
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        for daq in scanInfo["rawData"].keys():
            if scanInfo["rawData"][daq]["meta"]["type"] == "point":
                self.data.counts[daq][k][m,i:j] = scanInfo["rawData"][daq]["data"]
            if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
                self.data.counts[daq][k][:,i:j] = scanInfo["rawData"][daq]["data"]
        if scanInfo["type"] == "Image":
            self.data.interp_counts[k][m,y,:] = scanInfo["data"] #this is a matrix
            self.data.xMeasured[k][m,i:j] = scanInfo["line_positions"][0] #these are long vectors
            self.data.yMeasured[k][m,i:j] = scanInfo["line_positions"][1]
        elif scanInfo["type"] == "Spiral Image":
            mi = scanInfo['index']*scanInfo['line_positions'][0].size
            mj = mi + scanInfo['line_positions'][0].size
            self.data.xMeasured[k][m,mi:mj] = scanInfo['line_positions'][0]
            self.data.yMeasured[k][m,mi:mj] = scanInfo['line_positions'][1]
            self.data.interp_counts[k][m,:,:] = scanInfo['data']
        elif scanInfo["type"] == "Ptychography Image":
            c = scanInfo["columnIndex"]
            self.data.interp_counts[k][m,y,c] = scanInfo['rawData']
        elif "Focus" in scanInfo["type"]:
            if scanInfo["mode"]=="continuousLine":
                self.data.interp_counts[k][0, y, :] = scanInfo["data"]  # this is a matrix
                self.data.xMeasured[k][0,i:j] = scanInfo["line_positions"][0] #these are long vectors
                self.data.yMeasured[k][0,i:j] = scanInfo["line_positions"][1]
            else:
                c = scanInfo["columnIndex"]
                self.data.interp_counts[k][0, y, c] = scanInfo["data"]  # this is a matrix
        elif scanInfo["type"] == "Line Spectrum":
            self.data.interp_counts[k][m, 0, :] = scanInfo["data"]  # this is a matrix
            self.data.xMeasured[k][m, i:j] = scanInfo["line_positions"][0]  # these are long vectors
            self.data.yMeasured[k][m, i:j] = scanInfo["line_positions"][1]
            return self.data.interp_counts[k][:,0,:]
        elif scanInfo["type"] == "Single Motor":
            self.data.interp_counts[k][m,0,i] = scanInfo["rawData"]
        elif scanInfo["type"] == "Double Motor":
            c = scanInfo["columnIndex"]
            self.data.interp_counts[k][0, y, c] = scanInfo["rawData"]
        return self.data.interp_counts[k][m,:,:]

    def tiled_scan(self, scan):
        xStart = scan["scan_regions"]["Region1"]["xStart"]
        xStop = scan["scan_regions"]["Region1"]["xStop"]
        yStart = scan["scan_regions"]["Region1"]["yStart"]
        yStop = scan["scan_regions"]["Region1"]["yStop"]
        xStep = scan["scan_regions"]["Region1"]["xStep"]
        yStep = scan["scan_regions"]["Region1"]["yStep"]
        nxblocks, xcoarse, x_fine_start, x_fine_stop = \
            self.controller.motors[scan["x"]]["motor"].decompose_range(xStart,xStop)
        nyblocks, ycoarse, y_fine_start, y_fine_stop = \
            self.controller.motors[scan["y"]]["motor"].decompose_range(yStart,yStop)
        nblocks = nxblocks * nyblocks

        xcoarse, ycoarse = np.meshgrid(xcoarse, ycoarse)
        x_fine_start, y_fine_start = np.meshgrid(x_fine_start, y_fine_start)
        x_fine_stop, y_fine_stop = np.meshgrid(x_fine_stop, y_fine_stop)
        for i in range(ycoarse.shape[0]):
            if i % 2 != 0:
                xcoarse[i] = xcoarse[i, ::-1]
                x_fine_start[i] = x_fine_start[i, ::-1]
                x_fine_stop[i] = x_fine_stop[i, ::-1]
        xcoarse = xcoarse.flatten()
        ycoarse = ycoarse.flatten()
        x_fine_start = x_fine_start.flatten()
        x_fine_stop = x_fine_stop.flatten()
        y_fine_start = y_fine_start.flatten()
        y_fine_stop = y_fine_stop.flatten()

        #convert from one large scan region to several small scan regions
        #extract some data (like step size) from existing scan region before overwriting
        xstep = scan["scan_regions"]["Region1"]["xStep"]
        ystep = scan["scan_regions"]["Region1"]["yStep"]
        scan["scan_regions"] = {}
        for i in range(nblocks):
            xstart = xcoarse[i] + x_fine_start[i] ##fine_start is always negative because the fine range is centered on 0
            xstop = xcoarse[i] + x_fine_stop[i]  ##fine_stop is always positive for the same reason
            ystart = ycoarse[i] + y_fine_start[i]
            ystop = ycoarse[i] + y_fine_stop[i]
            xrange = xstop - xstart
            xcenter = xstart + xrange / 2.
            xpoints = int(xrange / xstep)
            yrange = ystop - ystart
            ycenter = ystart + yrange / 2.
            ypoints = int(yrange / ystep)
            scan["scan_regions"]["Region" + str(i+1)] = {"xStart": xstart,
                                                      "xStop": xstop,
                                                      "xPoints": xpoints,
                                                      "xStep": xstep,
                                                      "xRange": xrange,
                                                      "xCenter": xcenter,
                                                      "yStart": ystart,
                                                      "yStop": ystop,
                                                      "yPoints": ypoints,
                                                      "yStep": ystep,
                                                      "yRange": yrange,
                                                      "yCenter": ycenter,
                                                      "zStart": 0,
                                                      "zStop": 0,
                                                      "zPoints": 0}
        return scan

    def startScanProcess(self, scan):
        #allocate memory for data to be saved
        if scan["tiled"]:
            scan = self.tiled_scan(scan)
        scan["file_name"] = self.currentScanID
        scan["start_time"] = datetime.datetime.now().isoformat()
        self.data = stxm(scan)
        self.dataStream = threading.Thread(target = self.sendScanData, args = ())
        self.dataStream.start()
        print("Started data process.")

    def stopScanProcess(self):
        self.dataStream.join()
        self.data.close()
        print("Completed scan process.")

    def monitor(self):
        #the daqs are configured for the monitor by the monitorStart/Stop methods in the controller
        scanInfo = {"type": "monitor"}
        scanInfo["mode"] = "monitor"
        scanInfo["energy"] = 500
        scanInfo["energyRegion"] = "EnergyRegion1"
        scanInfo["scanRegion"] = "Region1"
        scanInfo["dwell"] = self.controller.main_config["monitor"]["dwell"]
        scanInfo["rawData"] = {}
        for daq in self.daq.keys():
            scanInfo["rawData"][daq]={"meta":self.daq[daq].meta,"data": None}
        chunk = []
        while True:
            scanInfo["elapsedTime"] = time.time()
            self.daq["default"].autoGateOpen(shutter=0)
            t0 = time.time()
            self.getPoint(scanInfo)
            print(f"[dataHandler] getPoint time {time.time()-t0}")
            self.daq["default"].autoGateClosed()
            self.controller.getMotorPositions()
            scanInfo = self.dataQueue.get(True)
            scanInfo['motorPositions'] = self.controller.allMotorPositions
            scanInfo['zonePlateCalibration'] = self.controller.motors["Energy"]["motor"].getZonePlateCalibration()
            scanInfo['zonePlateOffset'] = self.controller.motors["ZonePlateZ"]["motor"].offset
            if self.scanQueue.empty():
                self.sendDataToSock(scanInfo)
            else:
                return
                
    def processFrame(self, frame):
        y,x = frame.shape
        frame = (frame.astype('float64') - self.darkFrame.astype('float64'))[y//2-100:y//2+100,x//2-100:x//2+100]
        return frame[frame > 1.].sum()

    def zmq_start_event(self, scan, metadata=None):
        self.ccd_pub_socket.send_pyobj({'event':'start','data':scan, 'metadata':metadata})
    
    def zmq_stop_event(self):
        self.ccd_pub_socket.send_pyobj({'event':'stop','data':None})
    
    def zmq_send(self, info):
        self.ccd_pub_socket.send_pyobj(info)

    def sendScanData(self):
        t0 = time.time()
        chunk = []
        pointData = 0.
        while True:
            scanInfo = self.dataQueue.get(True)
            if scanInfo == 'endOfScan':
                self.regionComplete = True
                try:
                    self.stxm_pub_socket.send_pyobj('scan_complete')
                except:
                    pass
                return
            elif scanInfo == "endOfRegion":
                self.data.saveRegion(region)
                self.regionComplete = True
            else:
                self.regionComplete = False
                region = int(scanInfo['scanRegion'].split('Region')[1]) - 1
                scanInfo["elapsedTime"] = time.time() - t0
                if scanInfo["mode"] == "ptychographyGrid":
                    self.ptychodata.addFrame(scanInfo["ccd_frame"],scanInfo["ccd_frame_num"],mode=scanInfo["ccd_mode"])
                    self.zmq_send({'event':'frame','data':scanInfo})
                    if scanInfo["ccd_mode"] == "exp":
                        if scanInfo["doubleExposure"]:
                            if scanInfo["ccd_frame_num"] % 2 == 0:
                                pointData = self.processFrame(scanInfo["ccd_frame"])
                        else:
                            pointData = self.processFrame(scanInfo["ccd_frame"])
                        scanInfo["rawData"] = pointData
                        scanInfo.pop("ccd_frame",None)
                    else:
                        self.darkFrame = scanInfo["ccd_frame"]
                    scanInfo['image'] = self.addDataToStack(scanInfo)
                elif scanInfo["mode"] == "point":
                    scanInfo["data"] = scanInfo["rawData"]
                    scanInfo['image'] = self.addDataToStack(scanInfo)
                else:
                    #prepare data to send onto socket (for the GUI)
                    #interpolate_points takes scanInfo["rawData"] and converts to image coordinates 
                    scanInfo["data"] = self.interpolate_points(scanInfo)
                    #addDataToStack puts the image in the data structure and returns the thing to display in the GUI
                    scanInfo["image"] = self.addDataToStack(scanInfo)
                self.sendDataToSock(scanInfo)

    def sendDataToSock(self, scan_info):
        scan_info["scanID"] = self.currentScanID
        self.stxm_pub_socket.send_pyobj(scan_info)

    def getPoint(self, scanInfo):
        if scanInfo["mode"] == "ptychographyGrid":
            data = self.daq["ccd"].getPoint()
            if data is not None:
                frame_num, scanInfo["ccd_frame"] = data
                scanInfo["rawData"]["ccd"]["data"] = np.array(0.)
            else:
                return False
        else:
            for daq in self.daq.keys():
                if self.controller.daqConfig[daq]["record"]:
                    if self.controller.daqConfig[daq]["type"] != "image":
                        scanInfo["rawData"][daq]["data"] = np.array(self.daq[daq].getPoint())
            # with ThreadPoolExecutor(max_workers=5) as executor:
            #     futures = []
            #     for daq in self.daq.keys():
            #         future = executor.submit(self.read_daq, daq)
            #         futures.append(future)
            # for future in as_completed(futures):
            #     scanInfo["rawData"][daq]["data"] = future.result() # Blocks until the task is complete
            #     print(scanInfo["rawData"][daq]["data"])

        self.dataQueue.put(scanInfo)
        #Without this sleep time, the first item in a sequence gets unsynchronized somehow.  It appears out of order and
        #data gets mixed up.  very strange!
        time.sleep(0.01)
        return True

    def read_daq(self,daq):
        return np.array(self.daq[daq].getPoint())

    def getLine(self, scanInfo):
        for daq in self.daq.keys():
            if self.controller.daqConfig[daq]["record"]:
                scanInfo["rawData"][daq]["data"] = np.array(self.daq[daq].getLine())
        #Check if scanInfo has different lengths for motor positions and daq positions. If it does, redo the line.
        #Until sendscandata is called, the raw data is stored in 'data'
        # if len(scanInfo['rawData']) != len(scanInfo['line_positions'][0]):
        #     print(len(scanInfo['rawData']),len(scanInfo['line_positions'][0]))
        #     if not scanInfo['scan']['spiral']:
        #         print('mismatched arrays!')
        #         return False
        self.dataQueue.put(scanInfo)
        return True
        
    def updateDwells(self, scanInfo):
        self.data.DAQdwell = scanInfo['DAQDwell']
        self.data.motdwell = scanInfo['motorDwell']

from pystxmcontrol.utils.writeNX import stxm
from pystxmcontrol.utils.test_sample import test_sample
from pystxmcontrol.controller.zmq_publisher import ZMQPublisher
from concurrent.futures import ThreadPoolExecutor, as_completed
import time, os, datetime, threading
import numpy as np
import scipy
import asyncio
from copy import deepcopy
import json, h5py

class dataHandler:

    def _ensure_queues(self):
        """Ensure queues exist in the current event loop"""
        if self.dataQueue is None:
            self.dataQueue = asyncio.Queue()
        if self.scanQueue is None:
            self.scanQueue = self.controller._ensure_scan_queue()
        return self.dataQueue, self.scanQueue

    def __init__(self, controller, lock = None, logger = None):
        self.controller = controller
        self.daq = self.controller.daq
        self.dataQueue = None ##will be created lazily
        self.scanQueue = None  # Will reference controller's queue when needed
        self.main_config = self.controller.main_config
        self.lineScanModes = ["rasterLine", "continuousLine","continuousSpiral"]
        self.currentScanID = None
        self.monitorDaq = True
        self.pause = False
        self._framenum = 0
        self._logger = logger
        self._lock = lock

        # Initialize ZMQ publisher (replaces direct socket management)
        self.zmq_publisher = ZMQPublisher(
            config=self.main_config["server"],
            daq_dict=self.controller.daq,
            logger=logger
        )

        # Configure CCD if present
        if "CCD" in self.controller.daq.keys():
            self.controller.daq["CCD"].config([10, 0], 0)

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
        scanList = np.sort([x for x in os.listdir(scanDir) if '.stxm' in x])
        scanNumList = np.sort([int(os.path.splitext(x)[0].split('_')[1].split(dayStr)[1]) for x in scanList if 'ccdframes' not in x])

        if len(scanList) == 0:
            fileName = filePrefix + "_" + dayStr + "000.stxm"
        else:
            #lastScan = int(scanList[-1].split(filePrefix + '_')[1][6:9])
            #lastScan = int(os.path.splitext(scanList[-1])[0].split(filePrefix + "_")[1].split(dayStr)[1].split("_")[0])
            lastScan = scanNumList[-1]
            if (lastScan + 1) < 10:
                nextScan = "00" + str(lastScan + 1)
            elif (lastScan + 1) < 100:
                nextScan = "0" + str(lastScan + 1)
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


    def interpolate_points(self, scanInfo, daq):
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

        if scanInfo["rawData"][daq]["meta"]["type"] == "point":
            raw_data = scanInfo["rawData"][daq]["data"]
        elif scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            raw_data = scanInfo["rawData"][daq]["data"].sum(0)

        try:
            if scanInfo["coarse_only"]:
                return raw_data
        except:
            pass

        if not scanInfo["rawData"][daq]["interpolate"]:
            return raw_data

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
                cutoff = np.where(distMeas>distBins[-1])[0][0]
            except:
                cutoff = np.where(distMeas == max(distMeas))[0][0]
                
            
            distMeas = distMeas[:cutoff]
            
            data = raw_data[:cutoff]
            
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
            mi = scanInfo['position_index']#*scanInfo['line_positions'][0].size
            xMeasOld = self.data.xMeasured[region][scanInfo['energyIndex'],:mi]
            yMeasOld = self.data.yMeasured[region][scanInfo['energyIndex'],:mi]
            
            xMeas = np.append(xMeasOld,scanInfo['line_positions'][0])
            yMeas = np.append(yMeasOld,scanInfo['line_positions'][1])

            
            
            #Also, the raw data.
            di = (scanInfo['trajnum'])*raw_data.size
            dataOld = self.data.counts["default"][region][scanInfo['energyIndex'],:di]
            data = np.append(dataOld,raw_data)
            
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
                DAQtraj = np.arange(len(raw_data))*actDAQDwell+DAQdelay
            
            endpoint = max(xytraj[-1],DAQtraj[-1])
            xy_tVals = np.array([xytraj+endpoint*i for i in range(scanInfo['trajnum']+1)]).flatten()
            DAQ_tVals = np.array([DAQtraj+endpoint*i for i in range(scanInfo['trajnum']+1)]).flatten()
            
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

    # --- Stack writer methods ---
    # Each writer handles the interp_counts indexing for one storage pattern and
    # returns the image slice that goes to the GUI.  The raw-data store (counts)
    # is handled once in addDataToStack after the writer returns.

    def _write_2d_line(self, scanInfo, daq):
        """Continuous line image (LinearImageScan): one y-row per call."""
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        y = scanInfo["lineIndex"]
        mi = scanInfo["index"]
        mj = mi + scanInfo["line_positions"][0].size
        self.data.interp_counts[daq][k][m, y, :] = scanInfo["data"][daq]
        self.data.xMeasured[k][m, mi:mj] = scanInfo["line_positions"][0]
        self.data.yMeasured[k][m, mi:mj] = scanInfo["line_positions"][1]
        return self.data.interp_counts[daq][k][m, :, :]

    def _write_focus_line(self, scanInfo, daq):
        """Continuous line focus (LinearFocusScan): always uses default daq, energy index 0."""
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        y = scanInfo["lineIndex"]
        i = scanInfo["index"]
        j = i + scanInfo["rawData"][daq]["data"].shape[-1]
        self.data.interp_counts["default"][k][0, y, :] = scanInfo["data"]["default"]
        self.data.xMeasured[k][0, i:j] = scanInfo["line_positions"][0]
        self.data.yMeasured[k][0, i:j] = scanInfo["line_positions"][1]
        return self.data.interp_counts[daq][k][m, :, :]

    def _write_line_spectrum(self, scanInfo, daq):
        """Continuous line spectrum (LinearSpectrumScan): data stored in row 0, image is energy stack."""
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        i = scanInfo["index"]
        j = i + scanInfo["rawData"][daq]["data"].shape[-1]
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            self.data.interp_counts[daq][k][m, 0, :] = scanInfo["data"][daq].sum(0)
        else:
            self.data.interp_counts[daq][k][m, 0, :] = scanInfo["data"][daq]
        self.data.xMeasured[k][m, i:j] = scanInfo["line_positions"][0]
        self.data.yMeasured[k][m, i:j] = scanInfo["line_positions"][1]
        return self.data.interp_counts[daq][k][:, 0, :]

    def _write_spiral(self, scanInfo, daq):
        """Continuous spiral image (derived_spiral_image): full 2D image written each trajectory."""
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        mi = scanInfo["position_index"]
        mj = mi + scanInfo["line_positions"][0].size
        self.data.xMeasured[k][m, mi:mj] = scanInfo["line_positions"][0]
        self.data.yMeasured[k][m, mi:mj] = scanInfo["line_positions"][1]
        self.data.interp_counts[daq][k][m, :, :] = scanInfo["data"][daq]
        return self.data.interp_counts[daq][k][m, :, :]

    def _write_ptychography(self, scanInfo, daq):
        """Ptychography grid (derived_ptychography_image): one point per call."""
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        y = scanInfo["lineIndex"]
        c = scanInfo["columnIndex"]
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            self.data.interp_counts[daq][k][m, y, c] = scanInfo["rawData"][daq]["data"].sum(0)
        else:
            self.data.interp_counts[daq][k][m, y, c] = scanInfo["rawData"][daq]["data"][0]
        return self.data.interp_counts[daq][k][m, :, :]

    def _write_single_motor(self, scanInfo, daq):
        """Single motor scan: one point per call stored in row 0 at the current x index."""
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        i = scanInfo["index"]
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            self.data.interp_counts[daq][k][m, 0, i] = scanInfo["rawData"][daq]["data"].sum(0)
        else:
            self.data.interp_counts[daq][k][m, 0, i] = scanInfo["rawData"][daq]["data"][0]
        return self.data.interp_counts[daq][k][m, :, :]

    def _write_double_motor_point(self, scanInfo, daq):
        """Double motor point scan: one point per call stored at (row, col). Energy index fixed at 0."""
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        y = scanInfo["lineIndex"]
        c = scanInfo["columnIndex"]
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            self.data.interp_counts[daq][k][0, y, c] = scanInfo["rawData"][daq]["data"].sum(0)
        else:
            self.data.interp_counts[daq][k][0, y, c] = scanInfo["rawData"][daq]["data"][0]
        m = scanInfo["energyIndex"]
        return self.data.interp_counts[daq][k][m, :, :]

    _STACK_WRITERS = {
        "2d_line":            "_write_2d_line",
        "focus_line":         "_write_focus_line",
        "line_spectrum":      "_write_line_spectrum",
        "spiral":             "_write_spiral",
        "ptychography":       "_write_ptychography",
        "single_motor":       "_write_single_motor",
        "double_motor_point": "_write_double_motor_point",
    }

    def addDataToStack(self, scanInfo, daq):
        """Route scanInfo to the correct writer via storage_pattern, then store raw counts."""
        writer = getattr(self, self._STACK_WRITERS[scanInfo["storage_pattern"]])
        image = writer(scanInfo, daq)

        # Store raw (uninterpolated) data — common to all patterns
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        i = scanInfo["index"]
        j = i + scanInfo["rawData"][daq]["data"].shape[-1]
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            self.data.counts[daq][k][m, :, i:j] = scanInfo["rawData"][daq]["data"]
        else:
            self.data.counts[daq][k][m, i:j] = scanInfo["rawData"][daq]["data"]

        return image

    def tiled_scan(self, scan):
        xStart = scan["scan_regions"]["Region1"]["xStart"]
        xStop = scan["scan_regions"]["Region1"]["xStop"]
        yStart = scan["scan_regions"]["Region1"]["yStart"]
        yStop = scan["scan_regions"]["Region1"]["yStop"]
        xStep = scan["scan_regions"]["Region1"]["xStep"]
        yStep = scan["scan_regions"]["Region1"]["yStep"]
        nxblocks, xcoarse, x_fine_start, x_fine_stop = \
            self.controller.motors[scan["x_motor"]]["motor"].decompose_range(xStart,xStop)
        nyblocks, ycoarse, y_fine_start, y_fine_stop = \
            self.controller.motors[scan["y_motor"]]["motor"].decompose_range(yStart,yStop)
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
                                                      "zPoints": 1}
        return scan

    async def startScanProcess(self, scan):
        #allocate memory for data to be saved
        self._ensure_queues()
        if scan["tiled"]:
            scan = self.tiled_scan(scan)
        scan["file_name"] = self.currentScanID
        scan["start_time"] = datetime.datetime.now().isoformat()
        self._current_scan_type = scan.get("scan_type", "")
        intel = getattr(self, 'intelligence', None)
        if intel and intel.enabled:
            intel.on_scan_start(scan)
        self.data = stxm(scan)
        #for DAQs that define the energy range, like energy dispersives, get their energy list
        #into the data structure
        #Also ready this detector and set the filename for data.
        for daq in self.controller.daq.keys():
            if self.controller.daq[daq].meta["type"] == "spectrum":
                self.data.energies[daq] = self.controller.daq[daq].energies
                #These are currently specific to the xrf detector and will need to be implemented
                #in other daqs of this type. Probably a better way to do this.
                # self.controller.daq[daq].set_filename(self.currentScanID)
                # self.controller.daq[daq].ready()
        await self.sendScanData(scan["synch_event"])

    async def monitor(self, scanQueue):
        #the daqs are configured for the monitor by the monitorStart/Stop methods in the controller
        self._ensure_queues()
        scanInfo = {"type": "monitor"}
        scanInfo["mode"] = "monitor"
        scanInfo["energy"] = 500
        scanInfo['index'] = 0
        scanInfo["energyRegion"] = "EnergyRegion1"
        scanInfo["scanRegion"] = "Region1"
        scanInfo["scan_type"] = None
        scanInfo["dwell"] = self.controller.main_config["monitor"]["dwell"]
        scanInfo["daq_list"] = list(self.daq.keys())
        scanInfo["rawData"] = {}
        scanInfo["data"] = {}
        for daq in scanInfo["daq_list"]:
            scanInfo["rawData"][daq]={"meta":self.daq[daq].meta,"data": None}

        while True:
            scanInfo["elapsedTime"] = time.time()
            self.daq["default"].autoGateOpen(shutter=0)
            t0 = time.time()
            await self.getPoint(scanInfo)
            self.daq["default"].autoGateClosed()

            #self.controller.getMotorPositions(log = False) #this happens too frequently for logging
            self.controller.getMotorPositions(log=False, monitor_only=True)  # too frequent to log; respects "monitor" flag in motorConfig
            scanInfo = await self.dataQueue.get()
            scanInfo['motorPositions'] = self.controller.allMotorPositions
            scanInfo['gate_mode'] = self.controller.daq["default"].gate.mode
            scanInfo['zonePlateCalibration'] = self.controller.motors["Energy"]["motor"].getZonePlateCalibration()
            #this must be gotten from the current motor config so updates are applied
            scanInfo['zonePlateOffset'] = self.controller.motors["ZonePlateZ"]["motor"].config.get("offset")
            if "CCD" in scanInfo["daq_list"]:
                #just subtract background from the monitor data which goes to the GUI
                scanInfo["data"]["CCD"] = self.daq["CCD"].display_data
            if scanQueue.empty():
                await self.sendDataToSock(scanInfo)
            else:
                await scanQueue.get()
                return

    def processFrame(self, frame,threshold=0.1):
        point = ((frame>threshold) * frame).sum()
        return point

    def zmq_start_event(self, scan, metadata=None):
        """Send scan start event via ZMQ publisher"""
        #load the ACME config
        config_file = '/global/software/ptycholive/ACME_Data_Cleaning_And_Assembly/src/acme_data_cleaning/config.json'
        acme_config = json.loads(open(config_file).read())
        metadata['preprocessor_config'] = acme_config

        #load a probe
        #probe_file = '/cosmic-dtn/groups/cosmic/Data/2026/03/260311/NS_260311008_ccdframes_0_0.h5'
        #f = h5py.File(probe_file,'r')
        #probe = f['probe'][()]
        #f.close()
        #metadata['illumination'] = probe.tolist()
        self.zmq_publisher.send_scan_start_event(scan, metadata)

    def zmq_stop_event(self):
        """Send scan stop event via ZMQ publisher"""
        self.zmq_publisher.send_scan_stop_event()

    def zmq_send(self, info):
        """Send CCD frame data via ZMQ publisher"""
        self.zmq_publisher.publish_ccd_frame(info)

    def zmq_send_string(self, info):
        """Send STXM data as JSON string via ZMQ publisher"""
        self.zmq_publisher.publish_stxm_string(info)

    # --- Data processors for sendScanData ---
    # Each processor populates scanInfo["data"] and scanInfo["image"] for its scan mode.

    def _process_ptycho(self, scanInfo):
        """Ptychography frame: store CCD frame, compute point intensity, update stack."""
        self.ptychodata.addFrame(scanInfo["rawData"]["CCD"]["data"],
                                 scanInfo["ccd_frame_num"], mode=scanInfo["ccd_mode"])
        if self.controller.main_config["ptychography"]["streaming"]:
            scanInfo["ccd_frame"] = scanInfo["rawData"]["CCD"]["data"]
            self.zmq_send({"event": "frame", "data": scanInfo})
        if scanInfo["ccd_mode"] == "exp":
            if scanInfo["doubleExposure"]:
                if scanInfo["ccd_frame_num"] % 2 == 0:
                    self._ptycho_point_data = self.processFrame(self.daq["CCD"].display_data)
            else:
                self._ptycho_point_data = self.processFrame(self.daq["CCD"].display_data)
            scanInfo["data"]["default"] = self._ptycho_point_data
            scanInfo["rawData"]["default"]["data"][0] = self._ptycho_point_data #over write rawData since the diode measurement which is meaningless here
            scanInfo["data"]["CCD"] = self.daq["CCD"].display_data
        else:
            self.darkFrame = scanInfo["rawData"]["CCD"]["data"]
            scanInfo["data"]["default"] = 0.
            scanInfo["data"]["CCD"] = self.darkFrame
        scanInfo["image"]["default"] = self.addDataToStack(scanInfo, "default")

    def _process_point(self, scanInfo):
        """Point scan: pass raw data directly, no interpolation."""
        for daq in scanInfo["daq_list"]:
            scanInfo["data"][daq] = scanInfo["rawData"][daq]["data"]
            scanInfo["image"][daq] = self.addDataToStack(scanInfo, daq)

    def _process_continuous(self, scanInfo):
        """Continuous (line or spiral) scan: interpolate to image coordinates then store."""
        for daq in scanInfo["daq_list"]:
            scanInfo["data"][daq] = self.interpolate_points(scanInfo, daq)
            scanInfo["image"][daq] = self.addDataToStack(scanInfo, daq)

    _DATA_PROCESSORS = {
        "ptychographyGrid": "_process_ptycho",
        "ptychographySpiral": "_process_ptycho",
        "continuousLine": "_process_continuous",
        "continuousSpiral": "_process_continuous",
        "point":            "_process_point",
    }

    async def sendScanData(self, event):
        t0 = time.time()
        self._ptycho_point_data = 0.
        intel = getattr(self, 'intelligence', None)
        event.set()  # asyncio.Event from the controller to synchronize with the scan routine
        while True:
            scanInfo = await self.dataQueue.get()
            if scanInfo == "endOfScan":
                self.regionComplete = True
                self.zmq_publisher.publish_stxm_data("scan_complete")
                if intel and intel.enabled:
                    intel.on_scan_complete(scan_id=getattr(self, 'currentScanID', None))
                return
            elif scanInfo == "endOfRegion":
                self.regionComplete = True
                self.data.saveRegion(region)
                if intel and intel.enabled:
                    image = self.data.interp_counts.get("default", [None])[region]
                    if image is not None and len(image) > 0:
                        intel.on_region_complete(
                            image=image[last_energy_index] if image.ndim == 3 else image,
                            scan_type=getattr(self, '_current_scan_type', ''),
                            region=f"Region{region + 1}",
                            energy_index=last_energy_index,
                        )
            else:
                self.regionComplete = False
                region = int(scanInfo["scanRegion"].split("Region")[1]) - 1
                last_energy_index = scanInfo.get("energyIndex", 0)
                scanInfo["elapsedTime"] = time.time() - t0
                scanInfo["data"] = {}
                scanInfo["image"] = {}
                processor_name = self._DATA_PROCESSORS.get(scanInfo["mode"], "_process_continuous")
                # Run the processor in a thread executor so that blocking file I/O
                # (h5py writes to NFS mounts) does not stall the event loop and delay
                # asyncio.sleep callbacks in the scan loop, causing timing errors.
                await asyncio.get_running_loop().run_in_executor(
                    None, getattr(self, processor_name), scanInfo
                )
                if intel and intel.enabled:
                    intel.on_scan_data(scanInfo)
                await self.sendDataToSock(scanInfo)

    async def sendDataToSock(self, scan_info):
        scan_info["scanID"] = self.currentScanID
        scan_info.setdefault("gate_mode", self.controller.daq["default"].gate.mode)
        self.zmq_publisher.publish_stxm_data(scan_info)

    async def getPoint(self, scanInfo):
        daq_tasks = []
        for daq in scanInfo["daq_list"]:
            if self.controller.daqConfig[daq]["record"]:
                daq_tasks.append(self.daq[daq].getPoint())

        t0 = time.time()
        await asyncio.gather(*daq_tasks)
        t1 = time.time()
        for daq in scanInfo["daq_list"]:
            scanInfo["rawData"][daq]["data"] = self.daq[daq].data

        #send a copy or it gets overwritten before being sent
        await self.dataQueue.put(deepcopy(scanInfo))
        #print(f"[Get Point] Acquisition time: {t1-t0}")
        if "CCD" in scanInfo["daq_list"]:
            if self._framenum == 0:
                self.darkFrame = scanInfo["rawData"]["CCD"]["data"]
        self._framenum += 1
        return True

    async def read_daq(self,daq):
        data = await self.daq[daq].getPoint()
        return data

    async def getLine(self, scanInfo):
        daq_tasks = []
        for daq in scanInfo["daq_list"]:
            if self.controller.daqConfig[daq]["record"]:
                daq_tasks.append(self.daq[daq].getLine())
        t0 = time.time()
        await asyncio.gather(*daq_tasks)
        t1 = time.time()
        for daq in scanInfo["daq_list"]:
            if scanInfo["direction"] == "backward":
                    scanInfo["rawData"][daq]["data"] = self.daq[daq].data[::-1]
            else:
                scanInfo["rawData"][daq]["data"] = self.daq[daq].data

        if self.controller.daqConfig["default"]["simulation"]:
            row_index = scanInfo["lineIndex"]
            column_index = scanInfo["index"]
            y_center = scanInfo["yCenter"]
            x_center = scanInfo["xCenter"]
            y_size = scanInfo["yPoints"]
            x_size = scanInfo["xPoints"]
            pixel_size = scanInfo["xStep"]
            dwell = scanInfo["dwell"]
            if self.controller.daq["default"].gate.mode != "close":
                shutter = 1
            else:
                shutter = 0
            sample_type = self.controller.main_config.get("simulation", {}).get("sample_type", "star")
            energy = scanInfo.get("energy", 700.0)
            scanInfo["rawData"]["default"]["data"] = shutter * test_sample(
                row_index, column_index, y_size, x_size,
                pixel_size, dwell, y_center, x_center,
                sample_type=sample_type, energy=energy)

        await self.dataQueue.put(deepcopy(scanInfo))
        #print(f"[Get Line] Acquisition time: {t1-t0}")
        return True
        
    def updateDwells(self, scanInfo):
        self.data.DAQdwell = scanInfo['DAQDwell']
        self.data.motdwell = scanInfo['motorDwell']

    def record_event(self, event_type: str, **kwargs) -> None:
        """Record a semantic event to the intelligence event recorder if enabled."""
        intel = getattr(self, 'intelligence', None)
        if intel and intel.enabled:
            intel.recorder.record('events', event_type, **kwargs)

    def cleanup(self):
        """
        Cleanup method to properly close ZMQ sockets.
        Called automatically on program exit via atexit.
        """
        # Delegate cleanup to ZMQ publisher
        if hasattr(self, 'zmq_publisher'):
            self.zmq_publisher.cleanup()

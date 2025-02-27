from pystxmcontrol.utils.writeNX import stxm
from queue import Queue
import asyncio, prefect
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
        self.controller.daq["ccd"].config(10, 0, 0)
        self.ccd_data_port = self.main_config["server"]["ccd_data_port"]
        self.stxm_data_port = self.main_config["server"]["stxm_data_port"]
        self.stxm_file_port = self.main_config["server"]["stxm_file_port"]
        self.pause = False
        self._logger = logger
        self._lock = Lock()

        #publish to other listeners like RPI reconstruction for instance
        self.ccd_pub_address = 'tcp://%s:%s' % (self.main_config["server"]["host"],self.ccd_data_port)
        self.stxm_pub_address = 'tcp://%s:%s' % (self.main_config["server"]["host"], self.stxm_data_port)
        print("Publishing ccd frames on: %s" %self.ccd_pub_address)
        print("Publishing stxm data on: %s" % self.stxm_pub_address)
        context = zmq.Context()
        #publish ccd data to the preprocessor
        self.ccd_pub_socket = context.socket(zmq.PUB)
        self.ccd_pub_socket.set_hwm(2000)
        self.ccd_pub_socket.bind(self.ccd_pub_address)
        #publish stxm data to the gui
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

    def saveCurrentScan(self):
        self.data.save()

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
            
            data = scanInfo["data"][:cutoff]
            
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
            xMeasOld = self.data.xMeasured[region][scanInfo['energyIndex']][:mi]
            yMeasOld = self.data.yMeasured[region][scanInfo['energyIndex']][:mi]
            
            xMeas = np.append(xMeasOld,scanInfo['line_positions'][0])
            yMeas = np.append(yMeasOld,scanInfo['line_positions'][1])
            
            
            #Also, the raw data.
            di = (scanInfo['index'])*scanInfo['data'].size
            dataOld = self.data.counts[region][0][scanInfo['energyIndex']][:di]
            data = np.append(dataOld,scanInfo['data'])
            
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
                DAQtraj = np.arange(len(scanInfo['data']))*actDAQDwell+DAQdelay
            
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
        i = scanInfo["index"]*scanInfo["rawData"].size#*scanInfo["oversampling_factor"]
        j = i + scanInfo["rawData"].size
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        self.data.counts[k][0][m,i:j] = scanInfo["rawData"] #the 0 index is for channel which isn't implemented yet
        if scanInfo["mode"] == 'continuousLine':
            #print(len(scanInfo["line_positions"][0]))
            self.data.xMeasured[k][m,i:j] = scanInfo["line_positions"][0]
            self.data.yMeasured[k][m,i:j] = scanInfo["line_positions"][1]
        #For a spiral scan, the motor positions are decoupled from the daq samples.    
        elif scanInfo['mode'] == 'continuousSpiral':
            mi = scanInfo['index']*scanInfo['line_positions'][0].size
            mj = mi + scanInfo['line_positions'][0].size
            
            self.data.xMeasured[k][m,mi:mj] = scanInfo['line_positions'][0]
            self.data.yMeasured[k][m,mi:mj] = scanInfo['line_positions'][1]
             
        #Also need to handle the interpolated data.
        if scanInfo['mode'] == 'continuousSpiral':
            #self.data.interp_counts[k][0][m] = scanInfo['data'].flatten()
            self.data.interp_counts[k][0][m] = scanInfo['data']
        elif scanInfo['mode'] == 'ptychographyGrid':
            #For ptycho grid scanInfo['data'] is a single value. We have to put it in the right place.
            #Shape of array is given by the array. If we have to transpose, we will.
            index = np.unravel_index(scanInfo['index'],self.data.interp_counts[k][0][m].shape)
            self.data.interp_counts[k][0][m,index[0],index[1]] = scanInfo['data']
            #print(scanInfo['index'])
            #self.data.interp_counts[k][0][j,i] = scanInfo['data']
        else:
            pi = scanInfo["index"]*scanInfo["data"].size
            pj = pi + scanInfo["data"].size
            j = scanInfo["index"]
            # self.data.interp_counts[k][0][m,pi:pj] = scanInfo["data"]
            self.data.interp_counts[k][0][m,j,:] = scanInfo["data"]

            #self.data.interp_counts[k][0][m] = scanInfo["data"]
        return self.data.interp_counts[k][0][m]

    def tiled_scan(self, scan):
        xStart = scan["scanRegions"]["Region1"]["xStart"]
        xStop = scan["scanRegions"]["Region1"]["xStop"]
        yStart = scan["scanRegions"]["Region1"]["yStart"]
        yStop = scan["scanRegions"]["Region1"]["yStop"]
        xStep = scan["scanRegions"]["Region1"]["xStep"]
        yStep = scan["scanRegions"]["Region1"]["yStep"]
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
        xstep = scan["scanRegions"]["Region1"]["xStep"]
        ystep = scan["scanRegions"]["Region1"]["yStep"]
        scan["scanRegions"] = {}
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
            scan["scanRegions"]["Region" + str(i+1)] = {"xStart": xstart,
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
        self.data = stxm(scan)
        self.data.start_time = str(datetime.datetime.now())
        self.data.file_name = self.currentScanID
        self.data.startOutput()
        #TODO: save all motor positions in data file
        self.data.motors = self.controller.allMotorPositions
        #launch DAQ process
        self.dataStream = threading.Thread(target = self.sendScanData, args = ())
        self.dataStream.start()
        print("Started data process")

    def stopScanProcess(self):
        self.dataStream.join()
        self.data.end_time = str(datetime.datetime.now())
        self.data.closeFile()
        #print("Stopped data process and saved data.  Transferring file to NERSC...")
        ###Add code here to do prefect_NERSC transfer
        # self.prefect_nersc_transfer(os.path.basename(self.data.file_name))
        # self.prefect_stxmdb_transfer()
        # if self.data.scan_dict["type"] == "Ptychography Image":
        #    self.prefect_nersc_transfer(os.path.basename(self.ptychodata.file_name))

    def get_prefect_client(self, prefect_api_url, prefect_api_key, httpx_settings=None):
        # Same prefect client, but if you know the url and api_key
        # httpx_settings allows you to affect the http client that the prefect client uses
        return prefect.PrefectClient(
            prefect_api_url,
            api_key=prefect_api_key,
            httpx_settings=httpx_settings)

    async def prefect_start_nersc_flow(self, prefect_client, deployment_name, file_path):
        deployment = await prefect_client.read_deployment_by_name(deployment_name)
        flow_run = await prefect_client.create_flow_run_from_deployment(
            deployment.id,
            name=os.path.basename(file_path),
            parameters={"file_path": file_path},
        )
        return flow_run

    async def prefect_start_stxmdb_flow(self, prefect_client, deployment_name, file_path):
        deployment = await prefect_client.read_deployment_by_name(deployment_name)
        flow_run = await prefect_client.create_flow_run_from_deployment(
            deployment.id,
            name=os.path.basename(file_path),
            parameters={"file_path": file_path},
        )
        return flow_run

    def prefect_nersc_transfer(self, file_name):
        print("[prefect]: Initializing data transfer to NERSC for file %s" %file_name)
        year_2digits = file_name[3:5]
        year_4digits = '20' + year_2digits
        month = file_name[5:7]
        day = file_name[7:9]
        file_path = f"{year_4digits}/{month}/{year_2digits}{month}{day}/{file_name}"
        print("[prefect]: Saving data in path %s" %file_path)

        prefect_api_url = os.getenv('PREFECT_API_URL')
        prefect_api_key = os.getenv('PREFECT_API_KEY')
        prefect_deployment = "process_newfile_7012_ptycho4/process_newdata7012_ptycho4"
        client = self.get_prefect_client(prefect_api_url, prefect_api_key)
        asyncio.run(self.prefect_start_nersc_flow(client, prefect_deployment, file_path))

    def prefect_stxmdb_transfer(self):
        print("[prefect]: Initializing entry to stxmdb %s" %self.data.file_name)
        prefect_api_url = os.getenv('PREFECT_API_URL')
        prefect_api_key = os.getenv('PREFECT_API_KEY')
        prefect_deployment = "stxmdb_add_entry/stxmdb_add_entry"
        client = self.get_prefect_client(prefect_api_url, prefect_api_key)
        asyncio.run(self.prefect_start_stxmdb_flow(client, prefect_deployment, self.data.file_name))

    def monitor(self):
        scanInfo = {"type": "monitor"}
        scanInfo["mode"] = "monitor"
        scanInfo["energy"] = 500
        scanInfo["energyRegion"] = "EnergyRegion1"
        scanInfo["scanRegion"] = "Region1"
        scanInfo["dwell"] = self.controller.main_config["monitor"]["dwell"]
        scanInfo["elapsedTime"] = time.time()
        chunk = []
        while True:
            time.sleep(0.1)
            self.daq["default"].autoGateOpen(shutter=0)
            self.getPoint(scanInfo)
            self.daq["default"].autoGateClosed()
            self.controller.getMotorPositions()
            scanInfo = self.dataQueue.get(True)
            scanInfo['motorPositions'] = self.controller.allMotorPositions
            scanInfo['zonePlateCalibration'] = self.controller.motors["Energy"]["motor"].getZonePlateCalibration()
            scanInfo['zonePlateOffset'] = self.controller.motors["ZonePlateZ"]["motor"].offset
            if self.scanQueue.empty():
                chunk.append(scanInfo)
                self.sendDataChunkToSock(chunk)
                chunk = []
            else:
                print(self.scanQueue.get(True))
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
                if len(chunk) != 0:
                    self.sendDataChunkToSock(chunk)
                try:
                    self.stxm_pub_socket.send_pyobj('scan_complete')
                except:
                    pass
                return
            elif scanInfo == "endOfRegion":
                self.data.saveRegion(region,nt = totalSplit)
                self.regionComplete = True
                if len(chunk) != 0:
                    self.sendDataChunkToSock(chunk)
                chunk = []
            else:
                self.regionComplete = False
                region = int(scanInfo['scanRegion'].split('Region')[1]) - 1
                totalSplit = scanInfo['totalSplit']
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
                        scanInfo["data"] = pointData
                        #print(scanInfo['data'])
                        scanInfo.pop("ccd_frame",None)
                        #ccd data needs to be in an image. pointData is the value for the current pixel.
                        # chunk.append(scanInfo)
                        # self.sendDataChunkToSock(chunk)
                        # chunk = []
                    else:
                        self.darkFrame = scanInfo["ccd_frame"]
                    scanInfo['rawData'] = scanInfo['data']
                    scanInfo['image'] = self.addDataToStack(scanInfo)
                    chunk.append(scanInfo)
                    self.sendDataChunkToSock(chunk)
                    chunk = []
                else:
                    #prepare data to send onto socket (for the GUI)
                    with self._lock:
                        scanInfo['rawData'] = scanInfo["data"].copy()
                        scanInfo["data"] = self.interpolate_points(scanInfo)
                        scanInfo["image"] = self.addDataToStack(scanInfo)
                        chunk.append(scanInfo)

                if scanInfo["mode"] in self.lineScanModes:
                    self.sendDataChunkToSock(chunk)
                    chunk = []            
                elif len(chunk) == 50:
                    self.sendDataChunkToSock(chunk)
                    chunk = []

    def sendDataChunkToSock(self, chunk):
        ##grab data from all chunks and use the first as a template for the
        ##scanInfo dictionary to send
        data = np.array([item["data"] for item in chunk])
        scan_info = chunk[0]
        scan_info["data"] = data
        scan_info["scanID"] = self.currentScanID
        scan_info["elapsedTime"] = chunk[-1]["elapsedTime"]
        self.stxm_pub_socket.send_pyobj(scan_info)

    def getPoint(self, scanInfo):
        if scanInfo["mode"] == "ptychographyGrid":
            data = self.daq["ccd"].getPoint()
            if data is not None:
                #frame_num, scanInfo["ccd_frame"] = self.daq["ccd"].getPoint()
                frame_num, scanInfo["ccd_frame"] = data
                scanInfo["data"] = np.array(0.)
            else:
                return False
        else:
            scanInfo["data"] = np.array(self.daq["default"].getPoint())
        self.dataQueue.put(scanInfo)
        return True

    def getLine(self, scanInfo):
        scanInfo["data"] = self.daq["default"].getLine()
        #Check if scanInfo has different lengths for motor positions and daq positions. If it does, redo the line.
        #Until sendscandata is called, the raw data is stored in 'data'
        if len(scanInfo['data']) != len(scanInfo['line_positions'][0]):
            if not scanInfo['scan']['spiral']:
                print('mismatched arrays!')
                return False
        self.dataQueue.put(scanInfo)
        return True
        
    def updateDwells(self, scanInfo):
        self.data.DAQdwell = scanInfo['DAQDwell']
        self.data.motdwell = scanInfo['motorDwell']

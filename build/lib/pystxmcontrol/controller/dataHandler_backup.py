from pystxmcontrol.utils.writeNX import stxm
from multiprocessing import Process, Queue
import time, datetime, os, datetime, threading, zmq
import numpy as np

class dataHandler:
    def __init__(self, controller, daq, scanQueue, mainConfig, clientSocket = None):
        self.controller = controller
        self.daq = daq
        self.clientSocket = clientSocket
        self.dataQueue = Queue()
        self.scanQueue = scanQueue
        self.mainConfig = mainConfig
        self.lineScanModes = ["rasterLine", "continuousLine"]
        self.currentScanID = None
        self.monitorDaq = True
        self.controller.daq["ccd"].config(10, 0, 0)
        self.zmq_address = mainConfig["zmq"]["address"]
        self._publish_zmq = mainConfig["zmq"]["connect"]
        if self._publish_zmq:
            print("Publishing scanInfo on %s" %self.zmq_address)
            #publish to other listeners like RPI reconstruction for instance
            self.zmq_address = 'tcp://%s' % self.zmq_address
            context = zmq.Context()
            self.zmq_pub_socket = context.socket(zmq.PUB)
            self.zmq_pub_socket.set_hwm(2000)
            self.zmq_pub_socket.bind(self.zmq_address)

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
            lastScan = int(scanList[-1].split(filePrefix + '_')[1][6:9])
            if (lastScan + 1) < 10:
                nextScan = "00" + str(lastScan + 1)
            elif (lastScan + 1) < 100:
                nextScan = "0" + str(lastScan + 1)
            elif (lastScan + 1) < 1000:
                nextScan = str(lastScan + 1)
            fileName = filePrefix + "_" + dayStr + nextScan + '.stxm'
        self.ptychoDir = os.path.join(scanDir,fileName.split('.')[0])
        self.currentScanID = os.path.join(scanDir, fileName)
        return self.currentScanID

    def saveCurrentScan(self):
        self.data.save()

    def addDataToStack(self, scanInfo):
        i = scanInfo["index"]
        j = i + scanInfo["data"].size
        k = int(scanInfo["scanRegion"].split("Region")[-1]) - 1
        m = scanInfo["energyIndex"]
        self.data.counts[k][0][m,i:j] = scanInfo["data"] #the 0 index is for channel which isn't implemented yet

    def startScanProcess(self, scan):
        #allocate memory for data to be saved
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
        self.controller.daq["ccd"].config(10, 0, 0)
        print("Stopped data process and saved data.")
        
    def zmq_start_event(self):
        if self._publish_zmq:
            self.zmq_pub_socket.send_pyobj({'event':'start','data':scan})    
    
    def zmq_stop_event(self):
        if self._publish_zmq:
            self.zmq_pub_socket.send_pyobj({'event':'stop','data':None})    
    
    def zmq_send(self, info):
        if self._publish_zmq:
            self.zmq_pub_socket.send_pyobj(info)

    def monitor(self):
        scanInfo = {"type": "monitor"}
        scanInfo["mode"] = "monitor"
        scanInfo["energy"] = 500
        scanInfo["energyRegion"] = "EnergyRegion1"
        scanInfo["scanRegion"] = "Region1"
        scanInfo["dwell"] = self.controller.mainConfig["monitor"]["dwell"]
        scanInfo["elapsedTime"] = time.time()
        chunk = []
        while True:
            self.daq["default"].autoGateOpen()#shutter=0)
            time.sleep(scanInfo["dwell"]/1000.)
            self.getPoint(scanInfo)
            self.daq["default"].autoGateClosed()
            self.controller.getMotorPositions()
            scanInfo = self.dataQueue.get(True)
            scanInfo['motorPositions'] = self.controller.allMotorPositions
            scanInfo['zonePlateCalibration'] = self.controller.getZonePlateCalibration()
            scanInfo['zonePlateOffset'] = self.controller.motors["ZonePlateZ"]["motor"].offset
            pointData, scanInfo["ccd_frame"] = self.processFrame(scanInfo["ccd_frame"])
            if self.scanQueue.empty():
                chunk.append(scanInfo)
                self.sendDataChunkToSock(chunk)
                chunk = []
            else:
                self.scanQueue.get(True)
                return
                
    def processFrame(self, frame):
        d = np.zeros((960,960))
        y,x = frame.shape
        frame = frame.astype('float64') - self._dark_frame.astype('float64')
        for i in range(0,10):
            d[0:480,i::10] = frame[0:480,i::12]
            d[-480:,i::10] = frame[-480:,i::12]
        return d[d > 1.].sum(), d

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
                    self.clientSocket.sendMessage('endOfScan')
                except:
                    pass
                return
            elif scanInfo == "endOfRegion":
                self.regionComplete = True
                if len(chunk) != 0:
                    self.sendDataChunkToSock(chunk)
                chunk = []
            else:
                self.regionComplete = False
                scanInfo["elapsedTime"] = time.time() - t0
                if scanInfo["mode"] == "ptychographyGrid":
                    self.ptychodata.addFrame(scanInfo["ccd_frame"],scanInfo["ccd_frame_num"],mode=scanInfo["ccd_mode"])
                    self.zmq_send({'event':'frame','data':scanInfo})
                    if scanInfo["ccd_mode"] == "exp":
                        if scanInfo["doubleExposure"]:
                            if scanInfo["ccd_frame_num"] % 2 == 0:
                                pointData, displayFrame = self.processFrame(scanInfo["ccd_frame"])
                        else:
                            pointData, displayFrame = self.processFrame(scanInfo["ccd_frame"])
                        scanInfo["data"] = pointData
                        scanInfo["ccd_frame"] = displayFrame
                        chunk.append(scanInfo)
                        self.sendDataChunkToSock(chunk)
                        chunk = []
                    else:
                        self._dark_frame = scanInfo["ccd_frame"]
                else:
                    chunk.append(scanInfo)
                self.addDataToStack(scanInfo)
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
        scanInfo = chunk[0]
        scanInfo["data"] = data
        scanInfo["scanID"] = self.currentScanID
        scanInfo["elapsedTime"] = chunk[-1]["elapsedTime"]
        try:
            self.clientSocket.sendMessage(scanInfo)
        except Exception as e:
            print("Data socket not available.")

    def getPoint(self, scanInfo):
        if scanInfo["mode"] == "ptychographyGrid":
            framenum, scanInfo["ccd_frame"] = self.daq["ccd"].getPoint()
            scanInfo["data"] = np.array(0.)
        elif scanInfo["mode"] == "monitor":
            scanInfo["data"] = np.array(self.daq["default"].getPoint())
            framenum, scanInfo["ccd_frame"] = self.daq["ccd"].getPoint()
        else:
            scanInfo["data"] = np.array(self.daq["default"].getPoint())
        if framenum == 0:
            self._dark_frame = scanInfo["ccd_frame"].copy()
        self.dataQueue.put(scanInfo)

    def getLine(self, scanInfo):
        scanInfo["data"] = self.daq["default"].getLine()
        if scanInfo["direction"] == "backward":
            scanInfo["data"] = scanInfo["data"][::-1]
        self.dataQueue.put(scanInfo)

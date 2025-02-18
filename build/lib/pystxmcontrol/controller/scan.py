from pystxm_core.io.writeNX import stxm
from pystxmcontrol.controller.scans.arbitrary_linescan import arbitrary_linescan
from pystxmcontrol.controller.spiral import spiralcreator
from threading import Lock
import numpy as np
import time, datetime


class scanner:
    def __init__(self, controller, dataHandler, logger):

        self.controller = controller
        self.dataHandler = dataHandler
        self.queue = self.controller.scanQueue  ##this is the queue that kill requests come from
        self.scan = None
        self.scanning = False
        self.nRetries = 5
        self._logger = logger
        self._lock = Lock()

    def run(self, scan):
        self.controller.daq["default"].start()
        if scan["mode"] == "ptychographyGrid":
            self.controller.daq["ccd"].start()
        self.controller.scanDef = scan
        self.dataHandler.startScanProcess(scan)
        if "Image" in scan["type"]:
            if scan["mode"] == "ptychographyGrid":
                self.ptychographyGridScan(scan)
            elif scan["mode"] == "rasterLine":
                self.rasterLineScan(scan)
            elif scan["mode"] == "continuousLine":
                if scan['spiral']:
                    self.spiralScan(scan)
                else:
                    #self.continuousLineScan(scan)
                    arbitrary_linescan(scan, self.dataHandler, self.controller, self.queue)
                    #derivedLineScan(scan, self.dataHandler, self.controller, self.queue)
            else:
                print("Unsupported scan type.")
        elif scan["type"] == "Focus":
            self.focusScan(scan)
        elif scan["type"] == "Point Spectrum":
            self.timePointScan(scan)
        elif scan["type"] == "Line Spectrum":
            self.lineSpectrumScan(scan)
        else:
            print("Unsupported scan type.")
        self.dataHandler.stopScanProcess()
        self.controller.daq["default"].stop()
        if scan["mode"] == "ptychographyGrid":
            self.controller.daq["ccd"].stop()

    def moveToStart(self, scan, scanRegion):
        ##move to start positions
        xStart, yStart, zStart = scan["scanRegions"][scanRegion]["xStart"],scan["scanRegions"][scanRegion]["yStart"],\
            scan["scanRegions"][scanRegion]["xStart"]
        self.controller.moveMotor(scan["x"], xStart)
        self.controller.moveMotor(scan["y"], yStart)
        self.controller.moveMotor(scan["z"], zStart)

    def configureScan(self, sock, scanInfo, mode = "dark"):
        """
        This communicates the meta-data to cincontrol as separate commands.  Order is important.
        """
        if mode == "dark":
            sock.sendall(b"setCapturePath %s\n\r" %scanInfo["darkDir"].encode('utf-8'))
        elif mode == "exp":
            sock.sendall(b"setCapturePath %s\n\r" %scanInfo["expDir"].encode('utf-8'))
        print(sock.recv(4096).decode().strip())
        sock.sendall(b"startCapture\n\r")
        print(sock.recv(4096).decode().strip())
        sock.sendall(b"setExp %i\n\r" %scanInfo["dwell1"])
        print(sock.recv(4096).decode().strip())
        sock.sendall(b"setExp2 %i\n\r" %scanInfo["dwell2"])
        print(sock.recv(4096).decode().strip())
        sock.sendall(b"setDoubleExpCount %i\n\r" %scanInfo["isDoubleExp"])
        print(sock.recv(4096).decode().strip())
        sock.sendall(b"resetCounter\n\r")
        print(sock.recv(4096).decode().strip())
        
    def insertSTXMDetector(self):
        self.controller.moveMotor("Detector Y", 0)
        time.sleep(10)
        
    def retractSTXMDetector(self):
        self.controller.moveMotor("Detector Y", -6500)
        time.sleep(10)

    def ptychographyGridScan(self, scan):
        scan["randomize"] = True
        energies = self.dataHandler.data.energies
        xPos,yPos,zPos = self.dataHandler.data.xPos, self.dataHandler.data.yPos, self.dataHandler.data.zPos
        scanInfo = {"mode": "ptychographyGrid"}
        scanInfo["type"] = scan["type"]
        scanInfo["scan"] = scan
        energyIndex = 0
        nScanRegions = len(xPos)
        scanID = self.dataHandler.ptychoDir
        scanInfo["energyIndex"] = energyIndex
        scanInfo["dwell"] = self.dataHandler.data.dwells[energyIndex]
        scanInfo["doubleExposure"] = scan["doubleExposure"]
        scanInfo["n_repeats"] = scan["n_repeats"]
        scanInfo["oversampling_factor"] = 1
        scanInfo['totalSplit'] = None
        scanInfo['retract'] = scan['retract']

        print("starting ptychography scan: ", scanID)
        if scanInfo['retract']:
            self.retractSTXMDetector()
        print("Done!")
        
        if scan["doubleExposure"]:
            dwell1 = scanInfo["dwell"] * 10.
            dwell2 = scanInfo["dwell"]
        else:
            dwell1 = scanInfo["dwell"]
            dwell2 = 0
        self.controller.daq["ccd"].start()
        self.controller.daq["ccd"].config(dwell1+10., dwell2+10., scan["doubleExposure"])
        
        if "outerLoop" in scan.keys():
            loopMotorPos = self.getLoopMotorPositions(scan)
            
        
        if scanInfo['scan']['refocus']:
            print('refocusing')
            currentZonePlateZ = self.controller.motors['ZonePlateZ']['motor'].getPos()
            time.sleep(1)
        
        for energy in energies:
            ##scanInfo is what gets passed with each data transmission
            scanInfo["energy"] = energy
            scanInfo['energyIndex'] = energyIndex
            for j in range(nScanRegions):
                scanRegion = "Region" + str(j+1)
                if "outerLoop" in scan.keys():
                    print("Moving %s motor to %.4f" %(scan["outerLoop"]["motor"],loopMotorPos[j]))
                    self.controller.moveMotor(scan["outerLoop"]["motor"],loopMotorPos[j])            
                self.dataHandler.ptychodata = stxm(scan)
                self.dataHandler.ptychodata.start_time = str(datetime.datetime.now())
                self.dataHandler.ptychodata.file_name = self.dataHandler.currentScanID.replace('.stxm','_ccdframes_' + \
                    str(energyIndex) + '_' + str(j) + '.stxm')
                self.controller.getMotorPositions()
                self.dataHandler.data.motorPositions[j] = self.controller.allMotorPositions #all regions in one file
                self.dataHandler.ptychodata.motorPositions[0] = self.controller.allMotorPositions #regions in separate files
                scanInfo["motorPositions"] = self.controller.allMotorPositions
                self.dataHandler.ptychodata.startOutput()
                
                #move to focus without changing energy
                if len(energies) > 1:
                    self.controller.moveMotor(scan["energy"], energy)
                    if not scanInfo['scan']['refocus']:
                        if energy == energies[0]:
                            scanInfo['refocus_offset'] = currentZonePlateZ - self.controller.motors['ZonePlateZ']['motor'].calibratedPosition
                            print('calculated offset: {}'.format(scanInfo['refocus_offset']))
                        
                        self.controller.moveMotor('ZonePlateZ', self.controller.motors['ZonePlateZ']['motor'].calibratedPosition + scanInfo['refocus_offset'])
                    
                
                if scan["defocus"]:
                    step = energies[0] / 700. * 15.
                    print("Defocusing zone plate by %.4f microns" %step)
                    self.controller.motors["ZonePlateZ"]["motor"].moveBy(step = step)
                scanMeta = {"header": self.dataHandler.currentScanID}
                for key in self.controller.mainConfig.keys():
                    scanMeta[key] = self.controller.mainConfig[key]
                scanMeta["repetition"] = 1
                scanMeta["defocus"] = scan["defocus"]
                scanMeta["isDoubleExp"] = int(scan["doubleExposure"])
                scanMeta["pos_x"] = scan["scanRegions"][scanRegion]["xCenter"]
                scanMeta["pos_y"] = scan["scanRegions"][scanRegion]["yCenter"]
                scanMeta["step_size_x"] = scan["scanRegions"][scanRegion]["xStep"]
                scanMeta["step_size_y"] = scan["scanRegions"][scanRegion]["yStep"]
                scanMeta["num_pixels_x"] = scan["scanRegions"][scanRegion]["xPoints"]
                scanMeta["num_pixels_y"] = scan["scanRegions"][scanRegion]["yPoints"]
                scanMeta["background_pixels_x"] = 5
                scanMeta["background_pixels_y"] = 5
                scanMeta["dwell1"] = dwell1
                scanMeta["dwell2"] = dwell2
                scanMeta["energy"] = energy
                scanMeta["energyIndex"] = energyIndex #ABE - I added this and the following line
                scanMeta["scanRegion"] = j
                scanMeta["dark_num_x"] = 5
                scanMeta["dark_num_y"] = 5
                scanMeta["exp_num_x"] = scanMeta["num_pixels_x"]
                scanMeta["exp_num_y"] = scanMeta["num_pixels_y"]
                scanMeta["exp_step_x"] = scanMeta["step_size_x"]
                scanMeta["exp_step_y"] = scanMeta["step_size_y"]
                scanMeta["double_exposure"] = bool(scanMeta["isDoubleExp"])
                scanMeta["exp_num_total"] = scanMeta["exp_num_x"] * scanMeta["exp_num_y"] * (2 - int(not(scanMeta["double_exposure"])))
                xp,yp = np.meshgrid(xPos[j],yPos[j])
                xp,yp = xp.flatten(),yp.flatten()
                if scan["randomize"]:
                    xp = xp + (np.random.rand(len(xp)) - 0.5) * scanMeta["step_size_x"] / 2.
                    yp = yp + (np.random.rand(len(yp)) - 0.5) * scanMeta["step_size_y"] / 2.
                scanMeta["translations"] = [pos for pos in zip(yp,xp)]
                scanMeta["n_repeats"] = scan["n_repeats"]
                scanMeta["scan"] = scan
                
                ##add ptychography metadata to main scanInfo for sending to Abe's processes
                # scanInfo["ptychoMeta"] = scanMeta # ABE - I remove this, and only send it with the start event
                # I also moved the start event to here, so that we can have the full scan metadata dictionary to send
                #self.dataHandler.zmq_start_event(scan, metadata=scanMeta)
                self.dataHandler.zmq_send({'event': 'start', 'data': scan, 'metadata': scanMeta})

                time.sleep(0.1)
                scanInfo["scanRegion"] = scanRegion
                xp_dark = np.linspace(xp.min(),xp.max(),5)
                yp_dark = np.linspace(yp.min(),yp.max(),5)
                scanInfo["ccd_mode"] = "dark"
                print("acquiring background")
                if self.pointLoopSquareGrid(scan, scanInfo.copy(), (xp_dark,yp_dark,zPos[j]), shutter = False, daq = False):
                    self.dataHandler.dataQueue.put('endOfRegion')
                else:
                    self.dataHandler.zmq_send({'event': 'abort', 'data': None})
                    if scanInfo['retract']:
                        self.insertSTXMDetector()
                    if scan["defocus"]:
                        self.controller.motors["ZonePlateZ"]["motor"].moveBy(step=-step)
                    return
                scanInfo["ccd_mode"] = "exp"
                print("acquiring data")
                if self.pointLoopSquareGrid(scan, scanInfo.copy(), (xp,yp,zPos[j]), shutter = True):
                    self.dataHandler.dataQueue.put('endOfRegion')
                else:
                    self.dataHandler.zmq_send({'event': 'abort', 'data': None})
                    if scanInfo['retract']:
                        self.insertSTXMDetector()
                    if scan["defocus"]:
                        self.controller.motors["ZonePlateZ"]["motor"].moveBy(step=-step)
                    return
                while not self.dataHandler.regionComplete:
                    #need to wait here until all the data has gone through the pipe
                    pass
                print("Scan region complete, saving data...")
                self.dataHandler.ptychodata.addDict(scanMeta,"metadata") #stuff needed by the preprocessor
                self.dataHandler.ptychodata.saveRegion(0)
                self.dataHandler.ptychodata.closeFile()
                self.dataHandler.data.end_time = str(datetime.datetime.now())
                #self.dataHandler.data.saveRegion(j)
                #self.dataHandler.zmq_stop_event()
                self.dataHandler.zmq_send({'event': 'stop', 'data': None})
                print("Done!")
            energyIndex += 1
        self.dataHandler.dataQueue.put('endOfScan')
        if scanInfo['retract']:
            self.insertSTXMDetector()
        if scan["defocus"]:
            self.controller.motors["ZonePlateZ"]["motor"].moveBy(step=-step)
        print("Finished Grid Scan")

    def pointLoopSquareGrid(self, scan, scanInfo, positionList, shutter = True, daq = True):

        xPos, yPos, zPos = positionList
        if shutter == True:
            n_repeats = scanInfo["n_repeats"]
        else:
            n_repeats = 1
        if scan["doubleExposure"]:
            dwell1 = round(scanInfo["dwell"] * 10.)
            dwell2 = round(scanInfo["dwell"])
        else:
            dwell1 = round(scanInfo["dwell"])
            dwell2 = 0
        self.controller.daq["default"].setGateDwell(dwell1,0)
        if shutter:
            self.controller.daq["default"].gate.mode = "auto"
        else:
            self.controller.daq["default"].gate.mode = "close"
        
        frame_num = 0
        scanInfo["ccd_frame_num"] = frame_num
        for i in range(len(yPos)):
            if i % 50 == 0: ##used to be every line, now looping through points so just do this periodically
                self.controller.getMotorPositions()
                self.dataHandler.data.motorPositions[0] = self.controller.allMotorPositions
            scanInfo["motorPositions"] = self.controller.allMotorPositions
            self.controller.moveMotor(scan["y"], yPos[i])
            self.controller.moveMotor(scan["x"], xPos[i])
            # time.sleep(0.01) #motor move
            scanInfo["index"] = i
            ##need to also be able to request measured positions
            scanInfo["xVal"], scanInfo["yVal"] = xPos[i], yPos[i] * np.ones(len(xPos))
            scanInfo['xPos'] = xPos[i]
            scanInfo['yPos'] = yPos[i]
            scanInfo['isDoubleExposure'] = scan['doubleExposure']
            if self.queue.empty():
                if scan["doubleExposure"]:
                    scanInfo['dwell'] = dwell2
                    self.controller.daq["ccd"].init()
                    self.controller.daq["default"].setGateDwell(dwell2,0)
                    self.controller.daq["default"].autoGateOpen()
                    time.sleep((dwell2+10.)/1000.)
                    self.dataHandler.getPoint(scanInfo.copy())
                    frame_num += 1
                    scanInfo["ccd_frame_num"] = frame_num
                    scanInfo['dwell'] = dwell1
                    self.controller.daq["ccd"].init()
                    self.controller.daq["default"].setGateDwell(dwell1,0)
                    self.controller.daq["default"].autoGateOpen()
                    time.sleep((dwell1+10.)/1000.) ##shutter open dwell time
                    self.dataHandler.getPoint(scanInfo.copy())
                    frame_num += 1
                    scanInfo["ccd_frame_num"] = frame_num
                else:
                    for i in range(n_repeats):
                        #self.controller.daq["ccd"].init()
                        self.controller.daq["default"].setGateDwell(dwell1,0)
                        self.controller.daq["default"].autoGateOpen()
                        time.sleep((dwell1+10.)/1000.) ##shutter open dwell time
                        self.dataHandler.getPoint(scanInfo.copy())
                        frame_num += 1
                        scanInfo["ccd_frame_num"] = frame_num
            else:
                self.queue.get()
                #self.dataHandler.data.saveRegion(0)
                self.dataHandler.dataQueue.put('endOfScan')
                self._logger.log("Terminating grid scan")
                return False
        return True

    def twoMotorGrid(self, scan):
        energies = self.dataHandler.data.energies
        xPos,yPos,zPos = self.dataHandler.data.xPos[0], self.dataHandler.data.yPos[0], self.dataHandler.data.zPos[0]
        scanInfo = {"mode": "image"}
        scanInfo["type"] = scan["type"]
        dwell = self.dataHandler.data.dwells[0]
        scanInfo["energy"] = self.dataHandler.data.energies[0]
        scanInfo["energyIndex"] = 0
        scanInfo["dwell"] = dwell
        scanInfo["scanRegion"] = "Region1"
        scanInfo["xPoints"] = len(xPos)
        scanInfo['totalSplit'] = None
        self.controller.daq["default"].setGateDwell(dwell, 0)
        for i in range(len(yPos)):
            self.controller.getMotorPositions()
            self.dataHandler.data.motorPositions[0] = self.controller.allMotorPositions
            scanInfo["motorPositions"] = self.controller.allMotorPositions
            scanInfo["index"] = len(xPos) * i
            self.controller.moveMotor(scan["y"], yPos[i])
            self.controller.daq["default"].autoGateOpen()
            for j in range(len(xPos)):
                self.controller.moveMotor(scan["x"], xPos[j])
                scanInfo["index"] = i * len(xPos) + j
                scanInfo['xPos'] = xPos[j]
                scanInfo['yPos'] = yPos[i]
                if self.queue.empty():
                    self.dataHandler.getPoint(scanInfo.copy())
                else:
                    self.queue.get()
                    self.dataHandler.data.saveRegion(0)
                    self.dataHandler.dataQueue.put('endOfScan')
                    print("Terminating twoMotorGrid scan")
                    return False
                self.controller.daq["default"].autoGateClosed()

        self.dataHandler.dataQueue.put('endOfRegion')
        self.dataHandler.data.saveRegion(0)
        self.dataHandler.dataQueue.put('endOfScan')
        self.controller.scanQueue.queue.clear()
        return True

    def getLoopMotorPositions(self, scan):
        r = scan["outerLoop"]["range"]
        center = scan["outerLoop"]["center"]
        motor = scan["outerLoop"]["motor"]
        points = scan["outerLoop"]["points"]
        start = center - r / 2
        stop = center + r / 2
        return np.linspace(start,stop,points)

    def continuousLineScan(self, scan):
        """
        Image scan in continuous flyscan mode.  Uses linear trajectory function on the controller
        :param scan:
        :return:
        """
        
        energies = self.dataHandler.data.energies
        xPos, yPos, zPos = self.dataHandler.data.xPos, self.dataHandler.data.yPos, self.dataHandler.data.zPos
        scanInfo = {"mode": "continuousLine"}
        scanInfo["scan"] = scan
        scanInfo["type"] = scan["type"]
        scanInfo["oversampling_factor"] = scan["oversampling_factor"]
        scanInfo['totalSplit'] = None
        energyIndex = 0
        #option for including the return trajectory in the line (speeds things up)
        if "Image" in scanInfo["type"]:
            scanInfo["include_return"] = True
        else:
            scanInfo["include_return"] = False
        nScanRegions = len(xPos)
        if "outerLoop" in scan.keys():
            loopMotorPos = self.getLoopMotorPositions(scan)
        energy = energies[0]
        if not scanInfo['scan']['refocus']:
            currentZonePlateZ = self.controller.motors['ZonePlateZ']['motor'].getPos()
        for energy in energies:
            ##scanInfo is what gets passed with each data transmission
            scanInfo["energy"] = energy
            scanInfo["energyIndex"] = energyIndex
            scanInfo["dwell"] = self.dataHandler.data.dwells[energyIndex]
            if len(energies) > 1:
                self.controller.moveMotor(scan["energy"], energy)
                if not scanInfo['scan']['refocus']:
                    if energy == energies[0]:
                        scanInfo['refocus_offset'] = currentZonePlateZ - self.controller.motors['ZonePlateZ']['motor'].calibratedPosition
                        print('calculated offset: {}'.format(scanInfo['refocus_offset']))
                    
                    self.controller.moveMotor('ZonePlateZ', self.controller.motors['ZonePlateZ']['motor'].calibratedPosition + scanInfo['refocus_offset'])
                    
            else:
                if scanInfo['scan']['refocus']:
                    self.controller.moveMotor("ZonePlateZ", self.controller.motors["ZonePlateZ"]["motor"].calibratedPosition)
                    
            
            for j in range(nScanRegions):
                if "outerLoop" in scan.keys():
                    self.controller.moveMotor(scan["outerLoop"]["motor"],loopMotorPos[j])
                x,y = xPos[j],yPos[j]
                scanInfo["scanRegion"] = "Region" + str(j + 1)
                xStart, xStop = x[0], x[-1]
                yStart, yStop = y[0], y[-1]
                xRange, yRange = xStop - xStart, yStop - yStart
                xPoints, yPoints = len(x), len(y)
                xStep, yStep = xRange / (xPoints - 1), yRange / (yPoints - 1)
                #I'm putting all of these into scanINfo so the GUI knows where to put the data for a script scan
                scanInfo["xPoints"] = xPoints
                scanInfo["xStep"] = xStep
                scanInfo["xStart"] = xStart
                scanInfo["xCenter"] = xStart + xRange / 2.
                scanInfo["xRange"] = xRange
                scanInfo["yPoints"] = yPoints
                scanInfo["yStep"] = yStep
                scanInfo["yStart"] = yStart
                scanInfo["yCenter"] = yStart + yRange / 2.
                scanInfo["yRange"] = yRange
                waitTime = 0.005+xPoints*0.0001 #0.005 + xRange * 0.02

                self.controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints * scan["oversampling_factor"]
                self.controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = self.dataHandler.data.dwells[energyIndex] / scan["oversampling_factor"]
                self.controller.motors[scan["x"]]["motor"].lineMode = "continuous"
                self.controller.motors[scan["x"]]["motor"].trajectory_start = (xStart, yStart)
                self.controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop, yStart)
                self.controller.motors[scan["x"]]["motor"].include_return = scanInfo["include_return"]
                self.controller.motors[scan["x"]]["motor"].update_trajectory()
                scanInfo['nPoints'] = self.controller.motors[scan["x"]]["motor"].npositions
                #
                #if scanInfo['include_return']:
                if energy == energies[0]:
                    #print('updating array')
                    self.dataHandler.data.updateArrays(j,scanInfo['nPoints'])
                self.controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1,\
                                                       samples=scanInfo['nPoints'], trigger="EXT")            
                start_position_x = self.controller.motors[scan["x"]]["motor"].trajectory_start[0] - \
                                     self.controller.motors[scan["x"]]["motor"].xpad
                start_position_y = self.controller.motors[scan["x"]]["motor"].trajectory_start[1] - \
                                     self.controller.motors[scan["x"]]["motor"].ypad
                scanInfo["start_position_x"] = start_position_x
                #move to start
                self.controller.moveMotor(scan["x"],start_position_x)
                self.controller.moveMotor(scan["y"],start_position_y)
                #self.controller.motors[scan["x"]]["motor"].update_trajectory()
                time.sleep(0.5)
                
                #turn on position trigger
                trigger_axis = self.controller.motors[scan["x"]]["motor"].trigger_axis
                trigger_position = self.controller.motors[scan["x"]]["motor"].trajectory_trigger[trigger_axis-1]
                self.controller.motors[scan["x"]]["motor"].setPositionTriggerOn(pos = trigger_position)

                scanInfo["trigger_axis"] = trigger_axis
                scanInfo["xpad"] = self.controller.motors[scan["x"]]["motor"].xpad
                scanInfo["ypad"] = self.controller.motors[scan["x"]]["motor"].ypad
                
                x0,y0 = xStart,yStart
                x1,y1 = xStop, yStop
                distance = np.sqrt((x1-x0)**2 + (y1-y0)**2)
                for i in range(len(y)):
                    #if i % 5 == 0:
                    self.controller.getMotorPositions()
                    self.dataHandler.data.motorPositions[j] = self.controller.allMotorPositions
                    scanInfo["motorPositions"] = self.controller.allMotorPositions
                    scanInfo["index"] = i#*scanInfo['nPoints']
                    
                    ##need to also be able to request measured positions
                    scanInfo["xVal"], scanInfo["yVal"] = x, y[i] * np.ones(len(x))
                    if self.queue.empty():
                        while self.controller.pause:
                            if not(self.queue.empty()):
                                self.queue.get()
                                self.dataHandler.dataQueue.put('endOfScan')
                                print("Terminating grid scan")
                                return False
                            time.sleep(0.1)
                        scanInfo["direction"] = "forward"
                        
                        
                        #self.controller.moveMotor(scan["x"],scanInfo["start_position_x"])
                        if scanInfo["include_return"]:
                            pass
                            self.controller.moveMotor(scan["y"],y[i])
                            #self.controller.motors[scan["y"]]["motor"].move2(pos=y[i])
                        #self.controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints * scan["oversampling_factor"]
                        #scan is set up for the motion already if the return trajectory is included and we only need to do the line again.
                        #If there's a 2d trajectory, we have to reset the trajectory every line of the scan.
                        else:
                            self.controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = self.dataHandler.data.dwells[energyIndex] / scan["oversampling_factor"]
                            self.controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints * scan["oversampling_factor"]
                            self.controller.motors[scan["x"]]["motor"].trajectory_start = (xStart, y[i])
                            self.controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop, y[i])
                            self.controller.motors[scan["x"]]["motor"].update_trajectory()       
                        if self.doFlyscanLine(scan, scanInfo, waitTime):
                            if i < (len(y)-1) and not scanInfo["include_return"]:
                            
                                self.executeReturnTrajectory(self.controller.motors[scan["x"]]["motor"], xStart, xStop, y[i+1], y[i])
                            
                        else:
                            return self.terminateFlyscan(scan, "x", "Data acquisition failed for flyscan line!")
                    else:
                        self.queue.get()
                        self.dataHandler.data.saveRegion(j)
                        return self.terminateFlyscan(scan, "x", "Flyscan aborted.")
                self.dataHandler.dataQueue.put('endOfRegion')
                #self.dataHandler.data.saveRegion(j)
            energyIndex += 1
        self.terminateFlyscan(scan, "x", "Flyscan completed.")

    def terminateFlyscan(self, scan, axis, message):
        self.dataHandler.dataQueue.put('endOfScan')
        self.controller.motors[scan[axis]]["motor"].setPositionTriggerOff()
        #self.controller.moveMotor("ZonePlateZ", self.controller.motors["ZonePlateZ"]["motor"].calibratedPosition)
        self.controller.scanQueue.queue.clear()
        print(message)
        return False
        
    def executeReturnTrajectory(self,motor,xStart,xStop,yStart,yStop):
        maxSpeed = 2.0 #um/ms or mm/s
        minpoints = 5
        motor.trajectory_start = (xStop, yStop)
        motor.trajectory_stop = (xStart, yStart)
        xyRange = ((xStop - xStart)**2+(yStop-yStart)**2)**0.5
        dwell = 0.301 #ms. Unimportant I think.
        xyPoints = int(max(xyRange/(maxSpeed*dwell),minpoints))
        motor.trajectory_pixel_count = xyPoints
        motor.trajectory_pixel_dwell = dwell
        motor.update_trajectory()
        motor.moveLine()      
        

    def doFlyscanLine(self, scan, scanInfo, waitTime):
        devMode = False
        if devMode:
            self.controller.daq["default"].initLine()
            self.controller.daq["default"].autoGateOpen()
            time.sleep(waitTime) #shutter open has a 1.4 ms delay after command and 1ms rise time
            self.controller.motors[scan["x"]]["motor"].moveLine(direction=scanInfo["direction"])
            scanInfo["line_positions"] = self.controller.motors[scan["x"]]["motor"].positions
            self.controller.daq["default"].autoGateClosed()
            if not self.dataHandler.getLine(scanInfo.copy()):
                raise Exception('mismatched array lengths')
            return True
        
        try:
            self.controller.daq["default"].initLine()
            self.controller.daq["default"].autoGateOpen()
            time.sleep(waitTime) #shutter open has a 1.4 ms delay after command and 1ms rise time
            self.controller.motors[scan["x"]]["motor"].moveLine(direction=scanInfo["direction"])
            scanInfo["line_positions"] = self.controller.motors[scan["x"]]["motor"].positions
            self.controller.daq["default"].autoGateClosed()
            if not self.dataHandler.getLine(scanInfo.copy()):
                raise Exception('mismatched array lengths')
            return True
        except:
            print("getLine failed.")
            try:
                self.controller.daq["default"].stop()
                self.controller.daq["default"].start()
                self.controller.daq["default"].config(scanInfo["dwell"], count=1, samples=scanInfo["xPoints"], trigger="EXT")
                self.controller.moveMotor(scan["x"],scanInfo["start_position_x"])
                time.sleep(0.1)
                self.controller.daq["default"].initLine()
                self.controller.daq["default"].autoGateOpen()
                time.sleep(0.003)
                self.controller.motors[scan["x"]]["motor"].moveLine(direction=scanInfo["direction"])
                self.controller.daq["default"].autoGateClosed()
                if not self.dataHandler.getLine(scanInfo.copy()):
                    raise Exception('mismatched array lengths')
                return True
               
            except:
                print("Terminating grid scan")
                return False

    def lineSpectrumScan(self, scan):
        """
        Image scan in continuous flyscan mode.  Uses linear trajectory function on the controller
        :param scan:
        :return:
        """
        energies = self.dataHandler.data.energies
        self.controller.moveMotor("Energy", energies[0])
        xPos, yPos, zPos = self.dataHandler.data.xPos, self.dataHandler.data.yPos, self.dataHandler.data.zPos
        scanInfo = {"mode": "continuousLine"}
        scanInfo["scan"] = scan
        scanInfo["type"] = scan["type"]
        scanInfo["include_return"] = True
        scanRegion = "Region1" #only single region scans for line spectrum
        energyIndex = 0
        scanInfo["oversampling_factor"] = scan["oversampling_factor"]
        
        xStart, xStop = scan["scanRegions"][scanRegion]["xStart"], scan["scanRegions"][scanRegion]["xStop"]
        yStart, yStop = scan["scanRegions"][scanRegion]["yStart"], scan["scanRegions"][scanRegion]["yStop"]
        xPoints = scan["scanRegions"][scanRegion]["xPoints"]
        scanInfo["xPoints"] = xPoints
        
        scanInfo['totalSplit'] = None
        
        
        self.controller.motors[scan["x"]]["motor"].include_return = scanInfo["include_return"]


        ##THIS ONLY WORKS FOR HORIZONTAL SCANS.  NEED TO GENERALIZE
        #set the PID and fly wait time according to the range
        xRange = xStop - xStart
        if xRange <= 5.: 
            iGain = 150.
            waitTime = 0.005
        elif xRange > 15.: 
            iGain = 50.
            waitTime = 0.1
        else: 
            iGain = 150. - (xRange - 5.) * 10.
            waitTime = 0.005 + (xRange - 5.) * 0.01
        startPID = self.controller.motors[scan["x"]]["motor"].getPID()
        print("Using waitime:", waitTime)
        #self.controller.motors[scan["x"]]["motor"].setPID(pid = [0,iGain,0])

        # for arbitrary line, xPoints and yPoints are the same
        self.controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints*scanInfo["oversampling_factor"]
        self.controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = self.dataHandler.data.dwells[0]/scanInfo["oversampling_factor"]
        self.controller.motors[scan["x"]]["motor"].lineMode = "continuous"
        self.controller.motors[scan["x"]]["motor"].trajectory_start = (xStart, yStart)
        self.controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop, yStop)
        ##during the scan, the driver takes care of padding for the acceleration distance automagically but for the
        # move to start command it needs to be added manually I guess
        self.controller.motors[scan["x"]]["motor"].update_trajectory()
        scanInfo['nPoints'] = self.controller.motors[scan["x"]]["motor"].npositions
        print('nPoints: {}'.format(scanInfo['nPoints']))
        self.dataHandler.data.updateArrays(0,scanInfo['nPoints'])
        start_position_x = self.controller.motors[scan["x"]]["motor"].trajectory_start[0] - \
                           self.controller.motors[scan["x"]]["motor"].xpad
        start_position_y = self.controller.motors[scan["x"]]["motor"].trajectory_start[1] - \
                           self.controller.motors[scan["x"]]["motor"].ypad
        
        scanInfo["dwell"] = self.dataHandler.data.dwells[energyIndex]
        scanInfo["start_position_x"] = start_position_x
        scanInfo["start_position_y"] = start_position_y
        #move to start positions
        self.controller.moveMotor(scan["x"],scanInfo["start_position_x"])
        self.controller.moveMotor(scan["y"],scanInfo["start_position_y"])
        self.controller.moveMotor(scan["energy"], energies[0])
        self.controller.daq["default"].config(scanInfo["dwell"]/scanInfo["oversampling_factor"], count=1,\
                                                 samples=scanInfo['nPoints'], trigger="EXT")
        
        #turn on position trigger
        trigger_axis = self.controller.motors[scan["x"]]["motor"].trigger_axis
        trigger_position = self.controller.motors[scan["x"]]["motor"].trajectory_trigger[trigger_axis-1]
        self.controller.motors[scan["x"]]["motor"].setPositionTriggerOn(pos = trigger_position)
        
        x0,y0 = xStart,yStart
        x1,y1 = xStop, yStop
        distance = np.sqrt((x1-x0)**2 + (y1-y0)**2)
        
        for energy in energies:
            ##scanInfo is what gets passed with each data transmission
            scanInfo["energy"] = energy
            scanInfo["energyIndex"] = energyIndex
            scanInfo["dwell"] = self.dataHandler.data.dwells[energyIndex]

            #self.controller.moveMotor(scan["x"], start_position_x)
            #self.controller.moveMotor(scan["y"], start_position_y)
            self.controller.moveMotor("Energy", energy)
            self.controller.getMotorPositions()
            self.dataHandler.data.motorPositions[0] = self.controller.allMotorPositions
            scanInfo["motorPositions"] = self.controller.allMotorPositions
            scanInfo["scanRegion"] = scanRegion
            scanInfo["index"] = 0

            scanInfo["xVal"] = xPos[0]
            scanInfo["yVal"] = yPos[0]
                               
            if self.queue.empty():
                while self.controller.pause:
                    if not (self.queue.empty()):
                        self.queue.get()
                        self.dataHandler.dataQueue.put('endOfScan')
                        print("Terminating grid scan")
                        return False
                    time.sleep(0.1)
                scanInfo["direction"] = "forward"
                #self.controller.moveMotor(scan["x"],scanInfo["start_position_x"])
                #self.controller.moveMotor(scan["y"],scanInfo["start_position_y"])

                #self.controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = self.dataHandler.data.dwells[
                #                                                                        energyIndex] / scan[
                #                                                                        "oversampling_factor"]
                #self.controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints * scan[
                #    "oversampling_factor"]
                #self.controller.motors[scan["x"]]["motor"].trajectory_start = (xStart, yStart)
                #self.controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop, yStop)
                #self.controller.motors[scan["x"]]["motor"].update_trajectory()

                if self.doFlyscanLine(scan, scanInfo, waitTime):
                    if not scanInfo["include_return"]:
                        self.executeReturnTrajectory(self.controller.motors[scan["x"]]["motor"], xStart, xStop, yStart, yStop)
                else:
                    return self.terminateFlyscan(scan, "x", "Data acquisition failed for flyscan line!")
            else:
                self.queue.get()
                self.dataHandler.data.saveRegion(0)
                return self.terminateFlyscan(scan, "x", "Flyscan aborted.")
            #self.dataHandler.data.saveRegion(0)
            self.dataHandler.dataQueue.put('endOfRegion')
            energyIndex += 1
        self.terminateFlyscan(scan, "x", "Flyscan completed.")

    def focusScan(self,scan):
        energies = self.dataHandler.data.energies
        scanInfo = {"mode": "continuousLine"}
        scanInfo["scan"] = scan
        scanInfo["type"] = scan["type"]
        xPos, yPos, zPos = self.dataHandler.data.xPos[0], self.dataHandler.data.yPos[0], self.dataHandler.data.zPos[0]
        energyRegion = "EnergyRegion1"
        scanRegion = "Region1"
        scanInfo["energy"] = energies[0]
        scanInfo["energyRegion"] = energyRegion
        scanInfo["energyIndex"] = 0
        scanInfo["dwell"] = scan["energyRegions"][energyRegion]["dwell"]
        scanInfo["scanRegion"] = scanRegion
        xStart,xStop = scan["scanRegions"][scanRegion]["xStart"], scan["scanRegions"][scanRegion]["xStop"]
        yStart,yStop = scan["scanRegions"][scanRegion]["yStart"], scan["scanRegions"][scanRegion]["yStop"]
        zStart, zStop = scan["scanRegions"][scanRegion]["zStart"], scan["scanRegions"][scanRegion]["zStop"]
        xPoints = scan["scanRegions"][scanRegion]["xPoints"]
        scanInfo["xPoints"] = xPoints
        scanInfo["oversampling_factor"] = scan["oversampling_factor"]
        scanInfo["xVal"] = xPos
        scanInfo["yVal"] = yPos
        scanInfo['totalSplit'] = None
        
        scanInfo["include_return"] = True
        self.controller.motors[scan["x"]]["motor"].include_return = scanInfo["include_return"]

        self.controller.getMotorPositions()
        self.dataHandler.data.motorPositions[0] = self.controller.allMotorPositions

        #Move to start position
        self.controller.moveMotor(scan["z"], zStart)
        
        ##THIS ONLY WORKS FOR HORIZONTAL SCANS.  NEED TO GENERALIZE
        #set the PID and fly wait time according to the range
        xRange = xStop - xStart
        if xRange <= 5.: 
            iGain = 150.
            waitTime = 0.005
        elif xRange > 15.: 
            iGain = 50.
            waitTime = 0.1
        else: 
            iGain = 150. - (xRange - 5.) * 10.
            waitTime = 0.005 + (xRange - 5.) * 0.01
        startPID = self.controller.motors[scan["x"]]["motor"].getPID()
        #self.controller.motors[scan["x"]]["motor"].setPID(pid = [0,iGain,0])
        
        #for arbitrary line, xPoints and yPoints are the same

        self.controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints * scanInfo["oversampling_factor"]
        self.controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = self.dataHandler.data.dwells[0]/scanInfo["oversampling_factor"]
        self.controller.motors[scan["x"]]["motor"].lineMode = "continuous"
        self.controller.motors[scan["x"]]["motor"].trajectory_start = (xStart, yStart)
        self.controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop, yStop)
        self.controller.motors[scan["x"]]["motor"].include_return = scanInfo["include_return"]
        ##during the scan, the driver takes care of padding for the acceleration distance automagically but for the
        #move to start command it needs to be added manually I guess
        self.controller.motors[scan["x"]]["motor"].update_trajectory()
        scanInfo['nPoints'] = self.controller.motors[scan["x"]]["motor"].npositions
        self.dataHandler.data.updateArrays(0,scanInfo['nPoints'])
        self.controller.daq["default"].config(scanInfo["dwell"]/scanInfo["oversampling_factor"], count=1, \
                                                        samples=scanInfo['nPoints'], trigger="EXT")
        start_position_x = self.controller.motors[scan["x"]]["motor"].trajectory_start[0] - \
                           self.controller.motors[scan["x"]]["motor"].xpad
        start_position_y = self.controller.motors[scan["x"]]["motor"].trajectory_start[1] - \
                           self.controller.motors[scan["x"]]["motor"].ypad
        scanInfo["start_position_x"] = start_position_x
        scanInfo["start_position_y"] = start_position_y
        self.controller.moveMotor(scan["x"], start_position_x)
        self.controller.moveMotor(scan["y"], start_position_y)
        self.controller.moveMotor(scan["z"],zPos[0])
        time.sleep(1)
        
        #turn on position trigger
        trigger_axis = self.controller.motors[scan["x"]]["motor"].trigger_axis
        trigger_position = self.controller.motors[scan["x"]]["motor"].trajectory_trigger[trigger_axis-1]
        self.controller.motors[scan["x"]]["motor"].setPositionTriggerOn(pos = trigger_position)
        
        x0,y0 = xStart,yStart
        x1,y1 = xStop, yStop
        distance = np.sqrt((x1-x0)**2 + (y1-y0)**2)

        for i in range(len(zPos)):
            self.controller.getMotorPositions()
            scanInfo["motorPositions"] = self.controller.allMotorPositions
            scanInfo["index"] = i #* xPoints
            if self.queue.empty():
                scanInfo["direction"] = "forward"
                self.controller.moveMotor(scan["z"],zPos[i])
                #self.controller.moveMotor(scan["x"],scanInfo["start_position_x"])
                #self.controller.moveMotor(scan["y"],scanInfo["start_position_y"])
                waitTime = 0.05
                #self.controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = self.dataHandler.data.dwells[
                #                                                                        0] / scan[
                #                                                                        "oversampling_factor"]
                #self.controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints * scan[
                #    "oversampling_factor"]
                #self.controller.motors[scan["x"]]["motor"].trajectory_start = (xStart, yStart)
                #self.controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop, yStop)
                #self.controller.motors[scan["x"]]["motor"].update_trajectory()

                if self.doFlyscanLine(scan, scanInfo, waitTime):
                    if not scanInfo["include_return"]:
                        self.executeReturnTrajectory(self.controller.motors[scan["x"]]["motor"], xStart, xStop, yStart, yStop)
                else:
                    return self.terminateFlyscan(scan, "x", "Data acquisition failed for flyscan line!")
            else:
                self.queue.get()
                self.dataHandler.data.saveRegion(0)
                return self.terminateFlyscan(scan, "x", "Flyscan aborted.")
        #self.dataHandler.data.saveRegion(0)
        self.dataHandler.dataQueue.put('endOfRegion')
        self.terminateFlyscan(scan, "x", "Flyscan completed.")

    def timePointScan(self, scan):
        """
        Minimal scan.  No motor moves, just a dwell time and a counter
        TODO: moveToStart, getPoint loop
        """
        scanInfo = {"type": "timePointScan"}
        for scanRegion in scan["scanRegions"]:
            for energyRegion in scan["energyRegions"]:
                energy = scan["energyRegions"][energyRegion]["start"]
                self.moveToStart(scan, scanRegion, energyRegion)
                scanInfo["energy"] = energy
                scanInfo["energyRegion"] = energyRegion
                scanInfo["energyValue"] = "EnergyValue" + str(energies.index(energy) + 1)
                scanInfo["scanRegion"] = scanRegion
                scanInfo["dwell"] = scan["energyRegions"][energyRegion]["dwell"]
                for i in range(scan["scanRegions"][scanRegion]["nPoints"]):
                    if self.queue.empty():
                        self.dataHandler.getPoint(scanInfo.copy())
                    else:
                        self.queue.get()
                        self.dataHandler.dataQueue.put('endOfScan')
                        print("Terminating grid scan")
                        return False
        self.dataHandler.dataQueue.put('endOfScan')
        print("Finished Point Scan")
        
    def spiralScan(self,scan):
        '''
        Spiral scan using an arbitrary xy trajectory.
        '''
        
        energies = self.dataHandler.data.energies
        xPos, yPos, zPos = self.dataHandler.data.xPos, self.dataHandler.data.yPos, self.dataHandler.data.zPos
        scanInfo = {"mode": "continuousSpiral"}
        scanInfo["scan"] = scan
        scanInfo["type"] = scan["type"]
        #scanInfo["oversampling_factor"] = scan["oversampling_factor"] Probably separate for spiral scan
        #This flag adjusts whether the daq is triggered once at the start of the scan or every time the motor moves through a position.
        scanInfo['multiTrigger'] = True
        energyIndex = 0
        nScanRegions = len(xPos)
        if not scanInfo['scan']['refocus']:
            currentZonePlateZ = self.controller.motors['ZonePlateZ']['motor'].getPos()
        if "outerLoop" in scan.keys():
            loopMotorPos = self.getLoopMotorPositions(scan)
        energy = energies[0]
        for energy in energies:
            ##scanInfo is what gets passed with each data transmission
            scanInfo["energy"] = energy
            scanInfo["energyIndex"] = energyIndex
            #scanInfo["dwell"] = self.dataHandler.data.dwells[energyIndex]
            if len(energies) > 1:
                self.controller.moveMotor(scan["energy"], energy)
                if not scanInfo['scan']['refocus']:
                    if energy == energies[0]:
                        scanInfo['refocus_offset'] = currentZonePlateZ - self.controller.motors['ZonePlateZ']['motor'].calibratedPosition
                        print('calculated offset: {}'.format(scanInfo['refocus_offset']))
                    
                    self.controller.moveMotor('ZonePlateZ', self.controller.motors['ZonePlateZ']['motor'].calibratedPosition + scanInfo['refocus_offset'])
            else:
                if scanInfo['scan']['refocus']:
                    self.controller.moveMotor("ZonePlateZ",
                                          self.controller.motors["ZonePlateZ"]["motor"].calibratedPosition)
                                          
            for j in range(nScanRegions):
                if "outerLoop" in scan.keys():
                    self.controller.moveMotor(scan["outerLoop"]["motor"],loopMotorPos[j])
                x,y = xPos[j],yPos[j]
                scanInfo["scanRegion"] = "Region" + str(j + 1)
                xStart, xStop = x[0], x[-1]
                yStart, yStop = y[0], y[-1]
                xRange, yRange = xStop - xStart, yStop - yStart
                xPoints, yPoints = len(x), len(y)
                xStep, yStep = xRange / (xPoints - 1), yRange / (yPoints - 1)
                #I'm putting all of these into scanINfo so the GUI knows where to put the data for a script scan
                scanInfo["xPoints"] = xPoints
                scanInfo["xStep"] = xStep
                scanInfo["xStart"] = xStart
                scanInfo["xCenter"] = xStart + xRange / 2.
                scanInfo["xRange"] = xRange
                scanInfo["yPoints"] = yPoints
                scanInfo["yStep"] = yStep
                scanInfo["yStart"] = yStart
                scanInfo["yCenter"] = yStart + yRange / 2.
                scanInfo["yRange"] = yRange
                scanInfo['xVal'] = x
                scanInfo['yVal'] = y
                
                # The spiral scan makes a circular spiral. We need to scale it to get an oval if the y and x range are different
                
                radius = max(xRange,yRange)/2.
                aspectRatio = xRange/yRange
                
                # The dwell time plus the number of pixels sets the overall scan time.
                # This is multiplied by the DAQ oversampling factor.
                # Because this time is treated as a minimum, physical constraints can cause this time to increase.
                # Setting dwell to 0 will run the scan as fast as possible.
                DAQOversample = 2. # Average number of DAQ measurements per pixel. Doesn't affect scan time.
                reqDwell = self.dataHandler.data.dwells[energyIndex]
                numTotalPixels = xPoints*yPoints*np.pi/4 #float
                reqScanTime = reqDwell*numTotalPixels/1000 #seconds
                
                # number of loops is given by half the number of pixels (max of x and y).
                # Loop oversampling multiplies this number to reduce number of pixels without any loops, but makes it slower.
                # Number of loops is (probably) the limiting speed factor for small scans so don't set this too high.
                loopOversample = 1.2
                numLoops = int(max(xPoints, yPoints)*loopOversample / 2.)
                
                # There's a maximal frequency at which the scan can be performed.
                # We end up scanning at a constant linear velocity for larger scans, so I am unsure how to set this without
                # changing how the spiral is generated. There's a fudge factor of 2 here because the inner spiral is faster.
                fMax = 100. #Hz
                minTime = numLoops/fMax*2.
                minFreqScanTime = max(minTime,reqScanTime)
        
                # We also can't have more than 5000 points per motor trajectory.
                # The number of corners per loop sets how circular they are. Setting this larger shouldn't affect speed too much.
                # We also limit the motor positions based on the dwell allowed by the MCL controller.
                # The original script also had a maximal speed. We ignore that here.
                numCorners = 50 #minimum average corners per loop
                minMotorDwell = 0.12 #ms
                maxMotorDwell = 10. #ms
                
                # minimal time allowed for motor movements (many loops)
                minLoopMotorPoints = numCorners*numLoops
                minLoopMotorScanTime = minLoopMotorPoints*minMotorDwell/1000
                
                # total scan time is now determined
                totScanTime = max(minFreqScanTime,minLoopMotorScanTime)
                
                # Another case to look at is when the dwell is very long.
                minDwellMotorPoints = totScanTime/maxMotorDwell
                
                # The total time for a single trajectory cannot be larger than 2.5 or MCL will crash.
                # We fix this by separating into multiple trajectories if necessary.
                maxTrajTime = 2.5 #seconds
                timeSplit = int(np.ceil(max(1,totScanTime/maxTrajTime)))
                
                # We also may need to split it based on motor points if there are a large number of loops or a long dwell.
                maxTrajPoints = 5000 #points
                reqMotorPoints = max(minDwellMotorPoints,minLoopMotorPoints)
                motorSplit = int(np.ceil(max(1,reqMotorPoints/maxTrajPoints)))
                
                # Now we know the total number of times the scan has to be split and we can set up the trajectories.
                totalSplit = max(timeSplit,motorSplit)
                totalTrajTime = totScanTime/totalSplit

                # The number of motor points can be set to maximum unless this makes the dwell too short.
                # These are the desired number of points, but we have to adjust them again to round to the nearest 0.01 ms.
                motorTimeResolution = 0.001 #ms (based off old manual. Likely correct though.)
                # Here we set the dwell to the value for 5000 motor points in a trajectory.
                if totalTrajTime/maxTrajPoints >= minMotorDwell/1000.:
                    desMotorDwell = totalTrajTime/maxTrajPoints*1000.
                    # Round to nearest dwell time. Ceiling so we don't have > 5000 points
                    actMotorDwell = np.ceil(desMotorDwell/motorTimeResolution)*motorTimeResolution
                    numTrajMotorPoints = int(totalTrajTime/actMotorDwell*1000.)
                # If we can't, we instead set the dwell to the minimum
                else:
                    actMotorDwell = minMotorDwell
                    numTrajMotorPoints = int(totalTrajTime/actMotorDwell*1000.)

                #scanTime might be slightly different than the prior estimate    
                scanTime = numTrajMotorPoints*actMotorDwell*totalSplit/1000. #s

                #The spiral construction needs the sampling frequency and some of the future calculations need the total number of positions.
                samplingFrequency = 1/actMotorDwell*1000. #Hz
                nPosSamples = numTrajMotorPoints * totalSplit
                
                #The DAQ dwell time is set by the number of pixels requested and the actual scan time
                #Resolution for the DAQ is 1 us.
                DAQTimeResolution = 0.001 #ms (based on keysight manual and reading out CONF? command)
                trajPixels = int(numTotalPixels/totalSplit*DAQOversample)
                reqDAQDwell = totalTrajTime/trajPixels*1000.
                actDAQDwell = int(reqDAQDwell/DAQTimeResolution)*DAQTimeResolution
                numTrajDAQPoints = int(totalTrajTime/actDAQDwell*1000.)
                
                scanInfo['motorDwell'] = actMotorDwell
                scanInfo['DAQDwell'] = actDAQDwell
                scanInfo['DAQOversample'] = DAQOversample
                scanInfo['totalSplit'] = totalSplit
                
                self.dataHandler.updateDwells(scanInfo)

                #Generates a spiral based on parameters given.
                ySpiral,xSpiral = spiralcreator(samplingfrequency = samplingFrequency, scantime = scanTime, numloops = numLoops, clockwise = True, \
                    spiralscantype = "InstrumentLimits", inratio = 0.05, scanradius = radius, maxFreqXY = fMax)
                    
                #Readjust these points to shrink the appropriate dimension and add the center back in.
                if aspectRatio>1:
                    ySpiral = ySpiral/aspectRatio
                else:
                    xSpiral = xSpiral*aspectRatio
                    
                xSpiral += scanInfo['xCenter']
                ySpiral += scanInfo['yCenter']
                
                #Wait time (50 ms, test this)
                waitTime = 0.05
                
                #enforce the correct size of these arrays to avoid off by one errors.
                if len(xSpiral)<nPosSamples:
                    
                    xSpiral = np.pad(xSpiral, (0, nPosSamples-len(xSpiral)),mode = 'edge')
                    ySpiral = np.pad(ySpiral, (0, nPosSamples-len(xSpiral)),mode = 'edge')
                elif len(xSpiral)>nPosSamples:
                    xSpiral = xSpiral[:nPosSamples]
                    ySpiral = ySpiral[:nPosSamples]
                    
                #Split the list according to the number of splits identified previously.
                xList = xSpiral.reshape(totalSplit,int(nPosSamples/totalSplit))
                yList = ySpiral.reshape(totalSplit,int(nPosSamples/totalSplit))
                
                #Set up DAQ acquisition
                if scanInfo['multiTrigger']:
                    DAQcount = numTrajMotorPoints
                    DAQsamples = int(np.ceil(numTrajDAQPoints/DAQcount))
                    numTrajDAQPoints = DAQsamples*DAQcount
                    #we pad the dwell time so that the daq is done collecting by the time the motor has moved on to the next position.
                    #May have to make this dependent on the motor dwell time? 4 us is a total guess.
                    dwellPad = 0.004*DAQsamples
                    actDAQDwell = int(np.floor((actMotorDwell-dwellPad)/DAQsamples/DAQTimeResolution))*DAQTimeResolution
                else:
                    DAQcount = 1
                    DAQsamples = numTrajDAQPoints
                self.controller.daq["default"].config(actDAQDwell, count=DAQcount, samples=DAQsamples, trigger="EXT")
                
                #Move to first position
                self.controller.moveMotor(scan["x"],scanInfo['xCenter'])
                self.controller.moveMotor(scan["y"],scanInfo['yCenter'])
                #self.controller.motors[scan["x"]]["motor"].update_trajectory()
                time.sleep(0.2)
                
                #Fix raw data sizes in writeNX (only first energy)
                if energy == energies[0]:
                    params = {}
                    params['numTrajMotorPoints'] = numTrajMotorPoints
                    params['numTraj'] = totalSplit
                    params['numTrajDAQPoints'] = numTrajDAQPoints
                    self.dataHandler.data.updateArrays(j,params)
                
                #MCL "position" trigger does not need a position. I am unsure whether this is the pixel triggering mode.
                self.controller.motors[scan["x"]]["motor"].setPositionTriggerOn(0)
                
                for i in range(len(xList)):
         
                    
                    
                    self.controller.getMotorPositions()
                    self.dataHandler.data.motorPositions[j] = self.controller.allMotorPositions
                    scanInfo["motorPositions"] = self.controller.allMotorPositions
                    scanInfo["index"] = i#*scanInfo['nPoints']
                    
                    #Do flyscan line?
                    if self.queue.empty():
                        while self.controller.pause:
                            if not(self.queue.empty()):
                                self.queue.get()
                                self.dataHandler.dataQueue.put('endOfScan')
                                print("Terminating grid scan")
                                return False
                            time.sleep(0.1)
                        scanInfo["direction"] = "forward"
                    
                        #Set up motor trajectory
                        xMotorPos = xList[i]
                        yMotorPos = yList[i]
                        self.controller.motors[scan["x"]]["motor"].trajectory_pixel_count = len(xMotorPos)
                        self.controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = actMotorDwell
                        self.controller.motors[scan["x"]]["motor"].lineMode = "arbitrary"
                        self.controller.motors[scan["x"]]["motor"].trajectory_x_positions = xMotorPos
                        self.controller.motors[scan["x"]]["motor"].trajectory_y_positions = yMotorPos
                        self.controller.motors[scan["x"]]["motor"].update_trajectory()
                        
                        #If we ever have a position trigger, we will need this.
                        #trigger_axis = self.controller.motors[scan["x"]]["motor"].trigger_axis
                        #trigger_position = self.controller.motors[scan["x"]]["motor"].trajectory_trigger[trigger_axis-1]
                        #self.controller.motors[scan["x"]]["motor"].setPositionTriggerOn(pos = trigger_position)
                    
                        if self.doFlyscanLine(scan,scanInfo,waitTime):
                            pass
                        else:
                            return self.terminateFlyscan(scan, "x", "Data acquisition failed for flyscan line!")
                    else:
                        self.queue.get()
                        self.dataHandler.data.saveRegion(j,nt = totalSplit)
                        return self.terminateFlyscan(scan, "x", "Flyscan aborted.")
                with self._lock:
                    
                    self.dataHandler.dataQueue.put('endOfRegion')
                    #self.dataHandler.data.saveRegion(j,nt = totalSplit)
                
            energyIndex += 1       
        self.terminateFlyscan(scan, "x", "Flyscan completed.")
                        

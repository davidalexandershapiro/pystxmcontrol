import json, time, traceback
import threading
from queue import Queue
from pystxmcontrol.drivers import *
import os, sys
from pystxmcontrol.controller.zmqFrameMonitor import zmqFrameMonitor
from pystxmcontrol.drivers.derivedEnergy import derivedEnergy
from pystxmcontrol.controller.dataHandler import dataHandler
from pystxmcontrol.controller.scans import *

BASEPATH = sys.prefix

class controller:
    def __init__(self, simulation = False, logger = None):
        """
        :param simulation: simulation mode
        :type simulation: boolean

        Reads required configuration files, initializes motors, controllers and daqs and manages
        all hardware communication.  Also manages the calibration of the zone plate position for a given
        photon energy.
        """
        self.simulation = simulation
        self.motorConfigFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/motorConfig.json')
        self.daqConfigFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/daqConfig.json')
        self.scanConfigFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/scans.json')
        self.mainConfigFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/main.json')
        self.scanThread = threading.Thread(target=self.scan, args=(None,))
        self.motors = {}
        self.controllers = {}
        self.allMotorPositions = {}
        self.allMotorPositions["status"] = {}
        self.scanQueue = Queue() ##for the Abort signal
        self.status = "Idle"
        self.dataSocket = None
        self.scanDef = None
        self.scanning = False
        self.pause = False
        self.autoZonePlate = True
        self._logger = logger
        self.initialize()
        self.startMonitor()

    def readConfig(self):
        """
        Reads the required JSON config files into dictionaries.
        looks in sys.prefix for:
        pystxmcontrol_cfg/motorConfig.json
        pystxmcontrol_cfg/daqConfig.json
        pystxmcontrol_cfg/scans.json
        pystxmcontrol_cfg/main.json
        """
        self.motorConfig = json.loads(open(self.motorConfigFile).read())
        self.scanConfig = json.loads(open(self.scanConfigFile).read())
        self.main_config = json.loads(open(self.mainConfigFile).read())
        self.daqConfig = json.loads(open(self.daqConfigFile).read())

    def addController(self, config):
        """
        :param config: motor configuration dictionary
        :type config: dict
        :return: None
        Adds to an existing dictionary with a newly defined controller.  For
        | controller = config["controller"]
        | address = config['controllerID']
        | port = config['port']
        | This executes: controllerType(address = address, port = port) which initializes the controller class
        and communication with the device.
        """
        print("Adding controller type %s with ID %s" %(config["controller"],config["controllerID"]))
        self.controllers[config["controllerID"]] = {}
        self.controllers[config["controllerID"]]["device"] = eval("%s(address = '%s', port = %i, simulation = %i)" \
                                      %(config["controller"], config["controllerID"], config["port"], config["simulation"]))

    def initialize(self):
        self.readConfig()
        for key in self.motorConfig.keys():
            if self.motorConfig[key]["type"] == "primary":
                ##for this motor, add the controller if it doesn't exist
                if self.motorConfig[key]["controllerID"] not in self.controllers.keys():
                    self.addController(self.motorConfig[key])
                    simulation = bool(self.motorConfig[key]["simulation"])
                    self.controllers[self.motorConfig[key]["controllerID"]]["device"].initialize(simulation = simulation)
                else:
                    print("controller %s already available" %self.motorConfig[key]["controllerID"])

                ##initialize the motor driver and add the controller
                self.motors[key] = {"motor": eval(self.motorConfig[key]["driver"] + '()')}
                self.motors[key]["motor"].controller = self.controllers[self.motorConfig[key]["controllerID"]]["device"]

                ##add the config to the motor for later use
                setattr(self.motors[key]["motor"], "config", self.motorConfig[key])
                self.motors[key]["motor"].connect(axis = self.motorConfig[key]["axis"])
        for key in self.motorConfig.keys():
            if self.motorConfig[key]["type"] == "derived":
                self.motors[key] = {"motor": eval(self.motorConfig[key]["driver"] + '()')}
                for axis in self.motorConfig[key]["axes"]:
                    #self.motors[key]["motor"].axes[self.motorConfig[key]["axes"][axis]] = self.motors[self.motorConfig[key]["axes"][axis]]["motor"]
                    self.motors[key]["motor"].axes[axis] = self.motors[self.motorConfig[key]["axes"][axis]]["motor"]
                setattr(self.motors[key]["motor"], "config", self.motorConfig[key])
                self.motors[key]["motor"].connect(axis=key) #derived motor needs a name and "axes" is a list
        for motor in self.motors.keys():
            self.motors[motor]["motor"].offset = self.motors[motor]["motor"].config["offset"]
            self.motors[motor]["motor"].units = self.motors[motor]["motor"].config["units"]

        #get all initial motor positions
        self.getMotorPositions()
        
        ##get the list of daqs from the config and start them
        daqList = json.loads(open(self.daqConfigFile).read())
        self.daq = {}
        for daq in daqList:
            simulation = daqList[daq]["simulation"]
            self.daq[daq] = eval(daqList[daq]["driver"] + '(simulation = %s)' %simulation)
            self.daq[daq].start()
        self.dataHandler = dataHandler(self, self._logger)
        self.getMotorPositions()

    def updateMotorStatus(self):
        pass

    def getMotorPositions(self):
        
        for motor in self.motors:
            if "variable" in self.motorConfig[motor].keys():
                try:
                    self.allMotorPositions[motor] = self.motors[motor]["motor"].getVar(self.motorConfig[motor]["varType"])
                except:
                    print("getVar failed on %s" %motor)
                self.allMotorPositions["status"][motor] = False
            else:
                try:
                    self.allMotorPositions[motor] = self.motors[motor]["motor"].getPos()
                except:
                    print("getPos failed on %s" %motor)
                try:
                    self.allMotorPositions["status"][motor] = self.motors[motor]["motor"].getStatus()
                except:
                    print("getStatus failed on %s" %motor)
        

    def moveMotor(self, axis, pos):
        #software limits are handled at the driver level
        if self._logger is not None:
            self._logger.log("Controller moved motor %s to position %.2f" %(axis, pos))
        if "varType" in self.motorConfig[axis].keys():
            self.motors[axis]["motor"].setVar(pos, self.motorConfig[axis]["varType"])
        else:
            self.motors[axis]["motor"].moveTo(pos)

    def changeMotorConfig(self, c):
        if c["config"] == "offset":
            self.motors[c["motor"]]["motor"].offset = c["value"]
            self.motors[c["motor"]]["motor"].config["offset"] = c["value"]
            self.motorConfig[c["motor"]]["offset"] = round(c["value"],3)
        self.writeConfig()

    def writeConfig(self):
        with open(self.motorConfigFile,'w') as fp:
            json.dump(self.motorConfig,fp,indent=4)
        
    def getMotorConfig(self, motor):
        return self.motors[motor]["motor"].config

    def startMonitor(self):
        self.daq["default"].start()
        self.daq["default"].config(self.main_config["monitor"]["dwell"])
        self.dataHandler.monitorDaq = True
        self.monitorThread = threading.Thread(target = self.dataHandler.monitor, args = ())
        self.monitorThread.start()

    def stopMonitor(self):
        self.scanQueue.put('end')
        self.monitorThread.join()
        self.daq["default"].stop()

    def getScanID(self, ptychography = False):
        self.currentScanID = self.dataHandler.getScanName(dir = self.main_config["server"]["data_dir"], \
                                                      prefix = self.main_config["server"]["file_prefix"],\
                                                      ptychography = ptychography)
        return self.currentScanID

    def scan_helper(self, scan):
        self.scanning = True
        self.stopMonitor()
        self.scanQueue.queue.clear()
        self.daq["default"].start()
        if scan["mode"] == "ptychographyGrid":
            self.daq["ccd"].start()
        self.scanDef = scan
        self.dataHandler.startScanProcess(scan)
        eval(scan["driver"]+"(scan, self.dataHandler, self, self.scanQueue)")
        self.dataHandler.stopScanProcess()
        self.daq["default"].stop()
        if scan["mode"] == "ptychographyGrid":
            self.daq["ccd"].stop()
        self.startMonitor()
        self.scanning = False

    def scan(self, scan):
        self.scanThread = threading.Thread(target=self.scan_helper, args=(scan,))
        self.scanThread.start()

    def end_scan(self):
        self.scanQueue.put('end')
        self.scanThread.join()
        self.scanQueue.queue.clear()
        self.scanning = False

    def read_daq(self, daq, dwell, shutter = True):
        try:
            self.daq[daq].config(dwell, dwell, False)
            self.daq["default"].setGateDwell(dwell,0)
            self.daq["default"].gate.mode = "auto"
            self.daq["default"].autoGateOpen(shutter = int(shutter))
            data = self.daq[daq].getPoint()
        except Exception:
            data = None
            print(traceback.format_exc())
        return data
    
    
    
    
    
    
        
        
        

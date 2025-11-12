import json, time, traceback
import threading
from pystxmcontrol.drivers import *
import os, sys
from pystxmcontrol.controller.zmqFrameMonitor import zmqFrameMonitor
from pystxmcontrol.drivers.derivedEnergy import derivedEnergy
from pystxmcontrol.controller.dataHandler import dataHandler
from pystxmcontrol.controller.scans import *
from pystxmcontrol.controller.operation_logger import OperationLogger
import asyncio
import atexit

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
        self.motorConfigFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/motor.json')
        self.daqConfigFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/daq.json')
        self.scanConfigFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/scan.json')
        self.mainConfigFile = os.path.join(BASEPATH,'pystxmcontrol_cfg/main.json')
        self.scanThread = threading.Thread(target=self.scan, args=(None,))
        self.motors = {}
        self.controllers = {}
        self.allMotorPositions = {}
        self.allMotorPositions["status"] = {}
        self.scanQueue = None ##for the Abort signal - will be created lazily
        self.status = "Idle"
        self.dataSocket = None
        self.scanDef = None
        self.scanning = False
        self.pause = False
        self.autoZonePlate = True
        self.lock = asyncio.Lock()
        self._log_motors = True
        self._logger = logger
        self.readConfig()
        self.initialize()
        self.operation_logger = OperationLogger(db_path = self.main_config["server"]["data_dir"], logger=logger,readonly=False)
        self.operation_logger.start()
        self.startMonitor()
        self.getMotorPositions()
        self._motor_logger_thread = threading.Thread(target=self._motor_logger, args=(), daemon=True)
        self._motor_logger_thread.start()

        # Register cleanup handler for graceful shutdown
        atexit.register(self.cleanup)

    def _motor_logger(self):
        while self._log_motors:
            self.getMotorPositions()
            time.sleep(self.main_config["server"]["motor log period"])

    def _ensure_scan_queue(self):
        """Ensure scanQueue exists in the current event loop"""
        if self.scanQueue is None:
            self.scanQueue = asyncio.Queue()
        return self.scanQueue

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
        self.daqConfigFromFile = json.loads(open(self.daqConfigFile).read())
        self.daqConfig = {}
        for daq in self.daqConfigFromFile.keys():
            if self.daqConfigFromFile[daq]["record"]:
                self.daqConfig[daq] = self.daqConfigFromFile[daq]
        self.backupConfig()

    def updateMotorConfig(self):
        for key in self.motorConfig.keys():
            setattr(self.motors[key]["motor"], "config", self.motorConfig[key])

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
                self.motors[key] = {"motor": eval(self.motorConfig[key]["driver"] + '()')} #{"motor":xpsMotor()}
                self.motors[key]["motor"].controller = self.controllers[self.motorConfig[key]["controllerID"]]["device"]

                ##add the config to the motor for later use
                setattr(self.motors[key]["motor"], "config", self.motorConfig[key])
                self.motors[key]["motor"].connect(axis = self.motorConfig[key]["axis"])
        for key in self.motorConfig.keys():
            if self.motorConfig[key]["type"] == "derived":
                self.motors[key] = {"motor": eval(self.motorConfig[key]["driver"] + '()')}
                for axis in self.motorConfig[key]["axes"]:
                    self.motors[key]["motor"].axes[axis] = self.motors[self.motorConfig[key]["axes"][axis]]["motor"]
                setattr(self.motors[key]["motor"], "config", self.motorConfig[key])
                self.motors[key]["motor"].connect(axis=key) #derived motor needs a name and "axes" is a list
        #I think this is redundant.  setattr above should set all config items
        for motor in self.motors.keys():
            self.motors[motor]["motor"].offset = self.motors[motor]["motor"].config["offset"]
            self.motors[motor]["motor"].units = self.motors[motor]["motor"].config["units"]

        self.daq = {}
        for daq in self.daqConfig.keys():
            meta = self.daqConfig[daq]
            simulation = meta["simulation"]
            driver = meta["driver"]
            address = meta["address"]
            record = meta["record"]
            self.daq[daq] = eval(f"{driver}(address = '{address}', simulation = {simulation})")
            self.daq[daq].meta = meta
            self.daq[daq].start()
        self.dataHandler = dataHandler(self, self.lock, self._logger)
        self.monitorThread = threading.Thread(target=self.dataHandler.monitor, args=())

    def updateMotorStatus(self):
        pass

    def getMotorPositions(self, log = True):
        
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
                if log:
                    self.operation_logger.log_motor_position(motor,self.allMotorPositions[motor],
                                                         motor_offset = self.motors[motor]["motor"].config["offset"])
        

    def moveMotor(self, axis, pos, log=None, **kwargs):

        # Determine if we should log this move
        # If log is explicitly set, use that. Otherwise, auto-detect: log if NOT scanning
        should_log = log if log is not None else not self.scanning or self.main_config["server"]["log motors while scanning"]

        # Log the move start
        if should_log:
            self.operation_logger.log_motor_move(axis, pos)

        # Record start time for duration calculation
        start_time = time.time() if should_log else None

        try:
            if "varType" in self.motorConfig[axis].keys():
                self.motors[axis]["motor"].setVar(pos, self.motorConfig[axis]["varType"])
            else:
                self.motors[axis]["motor"].moveTo(pos, **kwargs)

            # Log successful completion with actual position
            if should_log:
                try:
                    actual_pos = self.motors[axis]["motor"].getPos()
                except:
                    actual_pos = None
                duration = time.time() - start_time
                self.operation_logger.log_motor_move(
                    axis, pos, actual_position=actual_pos,
                    duration=duration, success=True
                )
        except Exception as e:
            # Log failed move
            if should_log:
                duration = time.time() - start_time
                self.operation_logger.log_motor_move(
                    axis, pos, duration=duration,
                    success=False, error_message=str(e)
                )
            raise

    def changeMotorConfig(self, c):
        key = c["config"]
        if key == "offset":
            self.motors[c["motor"]]["motor"].offset = c["value"]
        self.motorConfig[c["motor"]][key] = round(c["value"],3)
        self.motors[c["motor"]]["motor"].config[key] = c["value"]
        self.writeConfig()
        return c

    def writeConfig(self):
        with open(self.motorConfigFile,'w') as fp:
            json.dump(self.motorConfig,fp,indent=4)

    def backupConfig(self):
        basedir = os.path.join(self.main_config["server"]["data_dir"],"pystxmcontrol_data")
        os.makedirs(basedir, exist_ok=True)
        motorConfigFile = os.path.join(basedir,"motorConfig.json")
        with open(motorConfigFile,'w') as fp:
            json.dump(self.motorConfig,fp,indent=4)       
        mainConfigFile = os.path.join(basedir,"main.json")
        with open(mainConfigFile,'w') as fp:
            json.dump(self.main_config,fp,indent=4)  
        daqConfigFile = os.path.join(basedir,"daqConfig.json")
        with open(daqConfigFile,'w') as fp:
            json.dump(self.daqConfigFromFile,fp,indent=4)
        scanConfigFile = os.path.join(basedir,"scans.json")
        with open(scanConfigFile,'w') as fp:
            json.dump(self.scanConfig,fp,indent=4)  

    def getMotorConfig(self, motor):
        return self.motors[motor]["motor"].config

    def startMonitor(self):
        #the monitor is now a coroutine so that the queues can be asyncio.Queues.  Need a helper function to 
        #run that in a thread
        self._ensure_scan_queue()
        for daq in self.daq.keys():
            self.daq[daq].start()
            if self.daq[daq].meta['type'] == "spectrum":
                #The spectrum detector is slow so we set it up to collect many samples and just poll it.
                self.daq[daq].config(dwell = self.main_config["monitor"]["dwell"],samples = 10000)
            else:
                self.daq[daq].config(dwell=self.main_config["monitor"]["dwell"])


        self.dataHandler.monitorDaq = True
        def run_monitor():
            asyncio.run(self.dataHandler.monitor(self.scanQueue))
        if not self.monitorThread.is_alive():
            self.monitorThread = threading.Thread(target=run_monitor, args=())
            self.monitorThread.start()
        if self.scanQueue is not None:
            while not self.scanQueue.empty():
                try:
                    self.scanQueue.get_nowait()
                except asyncio.QueueEmpty:
                    break #stopMonitor adds to the queue so that needs to be cleared

    def stopMonitor(self):
        if self.scanQueue is not None:
            self.scanQueue.put_nowait('end')
        if self.monitorThread.is_alive():
            self.monitorThread.join(timeout=2)
        for daq in self.daq.keys():
            self.daq[daq].stop()
        self.scanQueue = None
        self.dataHandler.dataQueue = None

    def getScanID(self, ptychography = False):
        self.currentScanID = self.dataHandler.getScanName(dir = self.main_config["server"]["data_dir"], \
                                                      prefix = self.main_config["server"]["file_prefix"],\
                                                      ptychography = ptychography)
        return self.currentScanID

    async def scan_helper(self, scan):
        self.scanning = True
        scan_start_time = time.time()
        scan_id = None
        scan_status = "started"
        scan_error = None

        # Log scan start
        scan_params = {
            "driver": scan.get("driver"),
            "scan_type": scan.get("scan_type"),
            "x_motor": scan.get("x_motor"),
            "y_motor": scan.get("y_motor"),
            "energy_motor": scan.get("energy_motor"),
            "dwell": scan.get("dwell"),
            "oversampling_factor": scan.get("oversampling_factor"),
            "proposal": scan.get("proposal"),
            "experimenters": scan.get("experimenters"),
            "sample": scan.get("sample"),
            "comment": scan.get("comment"),
            "nxFileVersion": scan.get("nxFileVersion"),
            "daq list": scan.get("daq list"),
        }

        try:
            self.stopMonitor()
            self._ensure_scan_queue()
            while not self.scanQueue.empty():
                try:
                    self.scanQueue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            for daq in self.daq.keys():
                self.daq[daq].start()
            self.scanDef = scan
            scan["synch_event"] = asyncio.Event()

            # Get scan ID after data file is created
            scan_id = getattr(self, 'currentScanID', None)
            self.operation_logger.log_scan_start(
                scan_id=scan_id,
                scan_type=scan.get("scan_type", "unknown"),
                parameters=scan_params
            )

            scan_tasks = []
            scan_tasks.append(self.dataHandler.startScanProcess(scan))
            scan_tasks.append(eval(scan["driver"]+"(scan, self.dataHandler, self, self.scanQueue)"))
            await asyncio.gather(*scan_tasks)

            #close the data file and send the zmq event to downstream processing
            self.dataHandler.data.close()
            file_path = self.dataHandler.data.file_name
            self.dataHandler.zmq_send_string({'event': 'stxm', 'data': {"identifier":os.path.basename(file_path)}})

            scan_status = "completed"

        except Exception as e:
            scan_status = "failed"
            scan_error = str(e)
            raise
        finally:
            # Log scan end
            scan_duration = time.time() - scan_start_time
            file_path = getattr(self.dataHandler.data, 'file_name', None) if hasattr(self, 'dataHandler') else None

            self.operation_logger.log_scan_end(
                scan_id=scan_id,
                scan_type=scan.get("scan_type", "unknown"),
                parameters=scan_params,
                file_path=file_path,
                duration=scan_duration,
                status=scan_status,
                error_message=scan_error
            )

            #clean up and restart the monitor
            for daq in self.daq.keys():
                self.daq[daq].stop()
            self.scanQueue = None
            self.dataHandler.dataQueue = None
            self.startMonitor()
            self.scanning = False

    def scan(self, scan):
        scan["main_config"] = self.main_config
        def run_scan():
            asyncio.run(self.scan_helper(scan))
        if not self.scanThread.is_alive():
            self.scanThread = threading.Thread(target=run_scan, args=())
            self.scanThread.start()


    def end_scan(self):
        if self.scanQueue is not None:
            self.scanQueue.put_nowait('end')
        self.scanning = False

    def config_daqs(self, dwell, count, samples, trigger):
        for daq in self.daq.keys():
            if self.daqConfig[daq]["record"]:
                try:
                    dwell / self.daqConfig[daq]["oversampling_factor"]
                except:
                    pass
                self.daq[daq].config(dwell, count = count, samples = samples, trigger = trigger)

    async def read_daq(self, daq, dwell, shutter = True):
        try:
            self.daq["default"].start()
            self.daq["default"].config(dwell)
            self.daq["default"].autoGateOpen(shutter=0)
            data = await self.daq["default"].getPoint()
            self.daq["default"].autoGateClosed()
            self.daq["default"].stop()
        except Exception:
            data = None
            print(traceback.format_exc())
        return data
    
    def move_to_focus(self):
        #move the SampleZ to A0
        self.moveMotor("SampleZ",pos = self.motors["Energy"]["motor"].config["A0"])
        self.motors["Energy"]["motor"].getZonePlateCalibration()
        #move the zone plate to the calibrated position
        self.moveMotor("ZonePlateZ",pos = self.motors["Energy"]["motor"].calibratedPosition)

    def cleanup(self):
        """
        Cleanup method for graceful shutdown.
        Stops operation logger and closes resources.
        Called automatically on program exit via atexit.
        """
        try:
            if hasattr(self, 'operation_logger'):
                self._log_motors = False
                self.operation_logger.stop()
                if self._logger:
                    self._logger.log("Operation logger stopped during cleanup", level="info")
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error stopping operation logger: {e}", level="error")
            else:
                print(f"Error stopping operation logger: {e}")

        try:
            if hasattr(self, 'dataHandler'):
                self.dataHandler.cleanup()
        except Exception as e:
            if self._logger:
                self._logger.log(f"Error cleaning up dataHandler: {e}", level="error")
            else:
                print(f"Error cleaning up dataHandler: {e}")









import threading, traceback, zmq
from pystxmcontrol.controller.controller import controller
from pystxmcontrol.utils.logger import logger
import time, os, datetime, sys
from optparse import OptionParser

parser = OptionParser()
parser.add_option('--simulation', dest = 'simulation', default = '1', help = 'use simulation motor moves and data. ON by default.')
parser.add_option('--tty', dest = 'TTYNAME', default = '/dev/pts/0')
(options, args) = parser.parse_args()
options = vars(options)
TTYNAME = options['TTYNAME']
options['simulation'] = bool(int(options['simulation']))
allowedSubnets = ['131.243.73','131.243.163','131.243.191','127.0.0']

class stxmServer:
    def __init__(self, simulation = True):
        self.simulation = simulation
        context = zmq.Context()
        self.command_sock = context.socket(zmq.REP)
        self.controller = None
        self.listening = True
        self._logger = logger(name = self.__class__.__name__, outfile = os.path.join(sys.prefix,'pystxmcontrol_cfg/stxmLog.txt'))
        self.controller = controller(self.simulation, self._logger)
        self.command_sock.bind("tcp://%s:%s" %(self.controller.main_config["server"]["host"],\
                                                       self.controller.main_config["server"]["command_port"]))

    def command_handler(self):
        while True:
            #time.sleep(0.1)
            message = self.command_sock.recv_pyobj()
            #recv_pyobj is blocking so we need to check the scan thread status after getting the message
            scanning = self.controller.scanThread.is_alive()
            if message["command"] == "get_config":
                message["status"] = True
                message["data"] = self.controller.motorConfig, self.controller.scanConfig, \
                    self.controller.allMotorPositions, self.controller.daqConfig
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "moveMotor":
                message["status"] = True
                try:
                    message["data"] = self.controller.moveMotor(message["axis"], message["pos"])
                except:
                    message['data'] = None
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "stop_monitor":
                message["status"] = True
                try:
                    self.controller.stopMonitor()
                except:
                    message["status"] = False
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "start_monitor":
                message["status"] = True
                try:
                    self.controller.startMonitor()
                except:
                    message["status"] = False
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "getData":
                if not(scanning):
                    message["status"] = True
                    message["data"] = self.controller.read_daq(daq=message["daq"], dwell=message["dwell"],
                                                   shutter=message["shutter"])
                else:
                    message["status"] = False
                    message["data"] = None
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "getMotorPositions":
                message["status"] = True
                self.controller.getMotorPositions()
                message["data"] = self.controller.allMotorPositions
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "getStatus":
                if scanning:
                    message["status"] = False
                    message["mode"] = "scanning"
                    message["data"] = self.controller.scanDef
                else:
                    message["status"] = True
                    message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "getMotorStatus":
                message["status"] = False
                message["mode"] = "scanning"
                message["data"] = self.controller.motors[message["axis"]]["motor"].getStatus()
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "scan":
                if not(scanning):
                    print('starting scan')
                    message["status"] = True
                    self.command_sock.send_pyobj(message)
                    if "Ptychography" in message["scan"]["type"]:
                        ptychography = True
                    else:
                        ptychography = False
                    message["data"] = self.controller.getScanID(ptychography=ptychography)
                    message["mode"] = "scanning"
                    message["time"] = str(datetime.datetime.now())
                    self.controller.scan(message["scan"])
                else:
                    message["status"] = False
                    message["data"] = None
                    message["mode"] = "scanning"
                    message["time"] = str(datetime.datetime.now())
                    self.command_sock.send_pyobj(message)
            elif message["command"] == "getZonePlateCalibration":
                message["status"] = True
                message["data"] = self.controller.motors["Energy"]["motor"].getZonePlateCalibration()
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "changeMotorConfig":
                message["status"] = True
                message["data"] = self.controller.changeMotorConfig(message["data"])
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "getMotorConfig":
                message["status"] = True
                message["data"] = self.controller.getMotorConfig(message["data"])
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "getScanID":
                message["status"] = True
                message["data"] = self.controller.getScanID()
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "cancel":
                if self.controller.scanning:
                    message["status"] = True
                    message["mode"] = "idle"
                    self.controller.end_scan()
                else:
                    message["status"] = False
                    message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "pause":
                if self.controller.scanning:
                    message["status"] = True
                    message["mode"] = "idle"
                    self.controller.pause = not (self.controller.pause)
                else:
                    message["status"] = False
                    message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "getStatus":
                if self.controller.scanning:
                    message["status"] = True
                    message["mode"] = "scanning"
                    message["data"] = self.controller.scanDef
                else:
                    message["status"] = True
                    message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            elif message["command"] == "setGate":
                if message["mode"] == "open":
                    status = True
                    self.controller.daq["default"].gate.mode = "open"
                elif message["mode"] == "closed":
                    status = False
                    self.controller.daq["default"].gate.mode = "close"
                elif message["mode"] == "auto":
                    status = False
                    self.controller.daq["default"].gate.mode = "auto"
                message["time"] = str(datetime.datetime.now())
                self.controller.daq["default"].gate.setStatus()
                self.command_sock.send_pyobj(message)
            else:
                message["status"] = False
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)
            if message["command"] == "close":
                self.command_sock.send_pyobj(message)
        else:
            print("Controller is not initialized.  Killing script socket.")
            message["status"] = False
            message["data"] = "Controller not initialized."
            message["time"] = str(datetime.datetime.now())
            self.command_sock.send_pyobj(message)

a = stxmServer(simulation = options['simulation'])
command_thread = threading.Thread(target=a.command_handler, args=())
command_thread.start()



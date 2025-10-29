import threading, traceback, zmq
from pystxmcontrol.controller.controller import controller
from pystxmcontrol.utils.logger import logger
import time, os, datetime, sys
import asyncio
import atexit
from optparse import OptionParser
import zmq.asyncio

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
        self.context = zmq.asyncio.Context()
        self.command_sock = self.context.socket(zmq.REP)
        self.controller = None
        self.listening = True
        self.running = True
        self._logger = logger(name = self.__class__.__name__, outfile = os.path.join(sys.prefix,'pystxmcontrol_cfg/stxmLog.txt'))
        self.controller = controller(self.simulation, self._logger)
        self.command_sock.bind("tcp://%s:%s" %(self.controller.main_config["server"]["host"],\
                                                       self.controller.main_config["server"]["command_port"]))
        atexit.register(self.cleanup)

    def cleanup(self):
        """Clean shutdown of server and controller"""
        self.running = False

        # Stop the controller monitor and cleanup
        if hasattr(self, 'controller') and self.controller is not None:
            try:
                self.controller.stopMonitor()
                if self._logger:
                    self._logger.log("Controller monitor stopped", level="info")
            except Exception as e:
                if self._logger:
                    self._logger.log(f"Error stopping controller monitor: {e}", level="error")

        # Close ZMQ socket
        if hasattr(self, 'command_sock') and self.command_sock is not None:
            try:
                self.command_sock.close(linger=0)
                if self._logger:
                    self._logger.log("Command socket closed", level="info")
            except Exception as e:
                if self._logger:
                    self._logger.log(f"Error closing command socket: {e}", level="error")

        # Terminate ZMQ context
        if hasattr(self, 'context') and self.context is not None:
            try:
                self.context.term()
                if self._logger:
                    self._logger.log("ZMQ context terminated", level="info")
            except Exception as e:
                if self._logger:
                    self._logger.log(f"Error terminating ZMQ context: {e}", level="error")

    async def command_handler(self):
        while self.running:
            message={"command":None}
            message = await self.command_sock.recv_pyobj()

            # Record start time for command logging
            cmd_start_time = time.time()
            command_name = message.get("command")

            #recv_pyobj is blocking so we need to check the scan thread status after getting the message
            scanning = self.controller.scanThread.is_alive()
            if message["command"] == "get_config":
                self.controller.readConfig()
                self.controller.updateMotorConfig()
                message["status"] = True
                message["data"] = self.controller.motorConfig, self.controller.scanConfig, \
                    self.controller.allMotorPositions,self.controller.daqConfig, self.controller.main_config
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "move_to_focus":
                self.controller.move_to_focus()
                message["status"] = True
                message["data"] = None
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "moveMotor":
                message["status"] = True
                error_msg = None
                try:
                    message["data"] = self.controller.moveMotor(message["axis"], message["pos"])
                except Exception as e:
                    message['data'] = None
                    error_msg = str(e)
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={"axis": message.get("axis"), "pos": message.get("pos")},
                    status=message["status"],
                    mode=message["mode"],
                    error_message=error_msg,
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "stop_monitor":
                message["status"] = True
                error_msg = None
                try:
                    self.controller.stopMonitor()
                except Exception as e:
                    message["status"] = False
                    error_msg = str(e)
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    error_message=error_msg,
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "start_monitor":
                message["status"] = True
                error_msg = None
                try:
                    self.controller.startMonitor()
                except Exception as e:
                    message["status"] = False
                    error_msg = str(e)
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    error_message=error_msg,
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "getData":
                if not(scanning):
                    message["status"] = True
                    message["data"] = await self.controller.read_daq(daq=message["daq"], dwell=message["dwell"],
                                                   shutter=message["shutter"])
                else:
                    message["status"] = False
                    message["data"] = None
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={"daq": message.get("daq"), "dwell": message.get("dwell"), "shutter": message.get("shutter")},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "getMotorPositions":
                message["status"] = True
                self.controller.getMotorPositions()
                message["data"] = self.controller.allMotorPositions
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
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

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "getMotorStatus":
                message["status"] = False
                message["mode"] = "scanning"
                message["data"] = self.controller.motors[message["axis"]]["motor"].getStatus()
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={"axis": message.get("axis")},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "scan":
                if not(scanning):
                    message["status"] = True
                    if "Ptychography" in message["scan"]["scan_type"]:
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

                # Log command
                scan_params = message.get("scan", {})
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={"scan_type": scan_params.get("scan_type"), "scan_id": message.get("data")},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "getZonePlateCalibration":
                message["status"] = True
                message["data"] = self.controller.motors["Energy"]["motor"].getZonePlateCalibration()
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "changeMotorConfig":
                message["status"] = True
                message["data"] = self.controller.changeMotorConfig(message["data"])
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={"config_data": message.get("data")},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "getMotorConfig":
                message["status"] = True
                message["data"] = self.controller.getMotorConfig(message["data"])
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={"config_data": message.get("data")},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
            elif message["command"] == "getScanID":
                message["status"] = True
                message["data"] = self.controller.getScanID()
                message["mode"] = "idle"
                message["time"] = str(datetime.datetime.now())
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
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

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
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

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={"pause_state": self.controller.pause if self.controller.scanning else None},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
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

                # Log command (second getStatus handler)
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=message["status"],
                    mode=message["mode"],
                    duration=time.time() - cmd_start_time
                )
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

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={"gate_mode": message.get("mode")},
                    status=True,
                    mode="idle",
                    duration=time.time() - cmd_start_time
                )
            # else:
            #     message["status"] = False
            #     message["mode"] = "idle"
            #     message["time"] = str(datetime.datetime.now())
            #     self.command_sock.send_pyobj(message)
            if message["command"] == "close":
                self.command_sock.send_pyobj(message)

                # Log command
                self.controller.operation_logger.log_command(
                    command=command_name,
                    parameters={},
                    status=True,
                    mode="idle",
                    duration=time.time() - cmd_start_time
                )
        else:
            print("Controller is not initialized.  Killing script socket.")
            message["status"] = False
            message["data"] = "Controller not initialized."
            message["time"] = str(datetime.datetime.now())
            self.command_sock.send_pyobj(message)

if __name__=="__main__":
    a = stxmServer(simulation = options['simulation'])
    try:
        asyncio.run(a.command_handler())
    except KeyboardInterrupt:
        print("\nShutting down server...")
        a.cleanup()
        print("Server stopped")
        sys.exit(0)

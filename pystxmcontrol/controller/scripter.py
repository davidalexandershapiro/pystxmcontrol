import sys, zmq, os, json, traceback, datetime, asyncio
import numpy as np
from time import time, sleep
from pystxmcontrol.controller.scan_model import ScanModel
from pystxmcontrol.controller.scan_conversion import (
    build_energy_regions, energy_list_for_scan,
)


class scripter:
    def __init__(self,host: str = "127.0.0.1", port: int = 9999, timeout: int = 30000):
        """
        """

        context = zmq.Context()
        self.sock = context.socket(zmq.REQ)
        # Set receive timeout to prevent hanging (in milliseconds)
        self.sock.setsockopt(zmq.RCVTIMEO, timeout)
        # Set send timeout as well
        self.sock.setsockopt(zmq.SNDTIMEO, timeout)
        self.sock.connect("tcp://%s:%s" %(host,port))

        ##This is just a default metadata dictionary created when scripter is imported
        ##MOTORS from the last line is used as a check in the move_motor command.  This isn't needed otherwise
        self.scan = ScanModel().model_dump()

    def update_scan(self,**kwargs) -> str:
        """
        TODO:
        1. get_config(), determine the motors used for the various scan types
        2. update_scan(), sets the scan parameters as desired, dwell time units are milliseconds.
        3. confirm the scan configuration with the user
        4. run the scan if requested

        Docstring for update_scan.  The parameters listed below are part of the scan definition in scripter.py and can
        be changed upon request.  Any scan defined in the control system configuration can be defined here.  For example,
        to do an OSA x/y image scan, the scan_type will be set to "OSA Image" if that is the name in the configuration and
        the x/y motors will be set to those defined in the config, likely OSA_X/OSA_Y for example.

        At a minimum, the x/y motors must be set in kwargs according to what is in the configuration for the given scan_type.
        For single and double_motor_scans, the x/y motors can be arbitrarily set and don't need to follow a specific configuration.
        
        :param proposal: str = None,
        :param experimenters: str = None,
        :param sample_descriptions: str = None,
        :param x_motor: str = None,
        :param y_motor: str = None,
        :param z_motor: str = None,
        :param x_center: float = None,
        :param y_center: float = None,
        :param z_center: float = None,
        :param x_range: float = None,
        :param y_range: float = None,
        :param z_range: float = None,
        :param x_points: int = None,
        :param y_points: int = None,
        :param z_points: int = None,
        :param energy_start: float = None,
        :param energy_stop: float = None,
        :param energy_points: int = None,
        :param dwell: float = None,
        :param spiral: bool = None,
        :param autofocus: bool = None,
        :param defocus: bool = None,
        :param scan_type: str = None,
        :param daq_list: str = None,
        :param comment: str = None,
        :param energy_list: list = None,
        :param scan_type: str = None,
        :param retract: bool = True
        """

        try:
            if kwargs:
                updated = ScanModel(**{**self.scan, **kwargs})
                self.scan = updated.model_dump()
                return "The current scan definition has been updated: " + json.dumps(self.scan)
            else:
                return "The current scan definition is: " + json.dumps(self.scan)
        except Exception as e:
            return f"Failed to update scan parameters: {e}"

    def move_motor(self, axis=None, pos=None):
        if axis not in list(self.MOTORS.keys()):
            print("Bad motor name. Available motors are:")
            for m in list(self.MOTORS.keys()):
                print(m)
            return
        message = {"command": "moveMotor", "axis": axis, "pos": pos}
        self.sock.send_pyobj(message)
        try:
            response = self.sock.recv_pyobj()
        except Exception as e:
            print(e)
            return None
        return response

    def get_config(self):
        message = {"command": "get_config"}
        try:
            self.sock.send_pyobj(message)
            response = self.sock.recv_pyobj()
            self.MOTORS,self.SCANS,self.POSITIONS,self.DAQS,self.CONFIG = response["data"]
            if response is not None: return response["data"]
            else: return False
        except zmq.Again:
            raise TimeoutError("Timeout waiting for response from pystxmcontrol server")
        except zmq.ZMQError as e:
            raise ConnectionError(f"ZMQ error communicating with server: {str(e)}")

    def read_daq(self, daq,dwell, shutter = True):
        message = {"command":"get_data","daq":daq,"dwell":dwell, "shutter":shutter}
        self.sock.send_pyobj(message)
        response = self.sock.recv_pyobj()
        if response is not None: return response["data"]
        else: return False

    def stop_monitor(self):
        message = {"command": "stop_monitor"}
        self.sock.send_pyobj(message)
        response = self.sock.recv_pyobj()
        if response is not None: return response["status"]
        else: return False

    def start_monitor(self):
        message = {"command": "start_monitor"}
        self.sock.send_pyobj(message)
        response = self.sock.recv_pyobj()
        if response is not None: return response["status"]
        else: return False

    def ptychography_scan(self):
        xstart = self.scan['x_center'] - self.scan['x_range'] / 2.
        xstop = self.scan['x_center'] + self.scan['x_range'] / 2.
        xstep = np.round((xstop - xstart) / (self.scan["x_points"] - 1), 3)
        x_range = xstop - xstart
        xcenter = self.scan['x_center']
        ystart = self.scan['y_center'] - self.scan['y_range'] / 2.
        ystop = self.scan['y_center'] + self.scan['y_range'] / 2.
        ystep = np.round((ystop - ystart) / (self.scan["y_points"] - 1), 3)
        y_range = ystop - ystart
        ycenter = self.scan['y_center']
        scan = {"scan_type": "Ptychography Image", "proposal": self.scan["proposal"], "experimenters": self.scan["experimenters"],
                "sample": self.scan["sample_description"],
                "x_motor": "SampleX",
                "y_motor": "SampleY",
                "energy_motor": "Energy",
                "doubleExposure": self.scan["double_exposure"],
                "n_repeats": 1,
                "defocus": self.scan["defocus"],
                "autofocus": self.scan["autofocus"],
                "oversampling_factor": 1,
                "mode": 'ptychographyGrid',
                "coarse_only": False,
                "spiral": False,
                "retract": self.scan["retract"],
                "tiled": False,
                "daq_list": self.scan["daq_list"],
                "comment": self.scan["comment"],
                "coarse_only": False,
                "loop_scan": self.scan["loop_scan"],
                "driver": self.SCANS["Ptychography Image"]["driver"], #"ptychography_image",
                "scan_regions": {"Region1": {"xStart": xstart,
                                            "xStop": xstop,
                                            "xPoints": self.scan['x_points'],
                                            "xStep": xstep,
                                            "xRange": x_range,
                                            "xCenter": xcenter,
                                            "yStart": ystart,
                                            "yStop": ystop,
                                            "yPoints": self.scan['y_points'],
                                            "yStep": ystep,
                                            "yRange": y_range,
                                            "yCenter": ycenter,
                                            "zStart": 0,
                                            "zStop": 0,
                                            "zPoints": 1}},
                "energy_regions": build_energy_regions(self.scan)
                }
        energy_list = energy_list_for_scan(self.scan)
        if energy_list is not None:
            scan["energy_list"] = energy_list
            scan["dwell"] = self.scan["dwell"]
        message = {"command": "scan", "scan": scan}
        self.sock.send_pyobj(message)
        response = self.sock.recv_pyobj()
        if not response["status"]:
            return False
        file_name = response["data"]
        status = False
        while not status:
            sleep(1)
            self.sock.send_pyobj({"command":"getStatus"})
            response = self.sock.recv_pyobj()
            status = response["status"]
        return file_name

    def stxm_scan(self):
        """
        Docstring for stxm_scan

        This executes any scan defined in the scan config file.  The global scan definition, self.scan, has
        default values which can be changed by external processes or scripts.
        
        """
 
        xstart = self.scan['x_center'] - self.scan['x_range'] / 2.
        xstop = self.scan['x_center'] + self.scan['x_range'] / 2.
        xstep = np.round((xstop - xstart) / (self.scan["x_points"] - 1), 3)
        xrange = xstop - xstart
        xcenter = xrange / 2. + xstart
        ystart = self.scan['y_center'] - self.scan['y_range'] / 2.
        ystop = self.scan['y_center'] + self.scan['y_range'] / 2.
        ystep = np.round((ystop - ystart) / (self.scan["y_points"] - 1), 3)
        yrange = ystop - ystart
        ycenter = yrange / 2. + ystart
        zstart = self.scan['z_center'] - self.scan['z_range'] / 2.
        zstop = self.scan['z_center'] + self.scan['z_range'] / 2.
        zstep = np.round((zstop - zstart) / max(self.scan["z_points"] - 1,1), 3)
        zrange = zstop - zstart
        zcenter = zrange / 2. + zstart
        if self.scan["energy_list"] is not None:
            self.scan["energy_start"] = self.scan["energy_list"][0]
            self.scan["energy_stop"] = self.scan["energy_list"][-1]
            self.scan["energy_points"] = len(self.scan["energy_list"])
        scan = {"scan_type": self.scan["scan_type"], "proposal": self.scan["proposal"], "experimenters": self.scan["experimenters"],
                "sample": self.scan["sample_description"],
                "x_motor": self.scan["x_motor"],
                "y_motor": self.scan["y_motor"],
                "z_motor": self.scan["z_motor"],
                "energy_motor": "Energy",
                "doubleExposure": self.scan["double_exposure"],
                "n_repeats": 1,
                "defocus": self.scan["defocus"],
                "autofocus": self.scan["autofocus"],
                "oversampling_factor": 3,
                "mode": self.SCANS[self.scan["scan_type"]]["mode"],
                "coarse_only": False,
                "spiral": self.scan["spiral"],
                "tiled": False,
                "daq_list": self.scan["daq_list"],
                "comment": self.scan["comment"],
                "loop_scan": self.scan["loop_scan"],
                "energy_list": energy_list_for_scan(self.scan),
                "dwell": self.scan["dwell"],
                "retract": self.scan["retract"],
                "scan_regions": {"Region1": {"xStart": xstart,
                                            "xStop": xstop,
                                            "xPoints": self.scan['x_points'],
                                            "xStep": xstep,
                                            "xRange": xrange,
                                            "xCenter": xcenter,
                                            "yStart": ystart,
                                            "yStop": ystop,
                                            "yPoints": self.scan['y_points'],
                                            "yStep": ystep,
                                            "yRange": yrange,
                                            "yCenter": ycenter,
                                            "zStart": zstart,
                                            "zStop": zstop,
                                            "zPoints": self.scan['z_points'],
                                            "zStep": zstep,
                                            "zRange": zrange,
                                            "zCenter": zcenter}},
                "energy_regions": build_energy_regions(self.scan)
                }
        scan["driver"] = self.SCANS[self.scan["scan_type"]]["driver"]
        message = {"command": "scan", "scan": scan}
        self.sock.send_pyobj(message)
        response = self.sock.recv_pyobj()
        if not response["status"]:
            return False
        file_name = response["data"]
        status = False
        while not status:
            sleep(1)
            self.sock.send_pyobj({"command":"getStatus"})
            response = self.sock.recv_pyobj()
            status = response["status"]
        return file_name

    def multi_region_ptychography_scan(self, scanRegList):
        scan = {"scan_type": "Ptychography Image", "proposal": self.scan["proposal"], "experimenters": self.scan["experimenters"], "nx_file_version": 3,
                "sample": self.scan["Sample"],
                "x_motor": "SampleX",
                "y_motor": "SampleY",
                "energy_motor": "Energy",
                "doubleExposure": self.scan["double_exposure"],
                "n_repeats": 1,
                "defocus": self.scan["defocus"],
                "autofocus": self.scan["autofocus"],
                "oversampling_factor": 1,
                "mode": "ptychographyGrid",
                "coarse_only": False,
                "spiral": self.scan["spiral"],
                "retract": self.scan["retract"],
                "daq_list": self.scan["daq_list"],
                "comment": self.scan["comment"],
                "coarse_only": False,
                "loop_scan": self.scan["loop_scan"],
                "driver": self.SCANS["Ptychography Image"]["driver"],
                "energy_regions": build_energy_regions(self.scan)
                }
        scan["scan_regions"] = {}
        i = 1
        for region in scanRegList:
            xstart, xstop, ystart, ystop = region
            x_range = xstop - xstart
            xcenter = xstart + x_range / 2.
            xpoints = int(x_range / self.scan["xstep"])
            y_range = ystop - ystart
            ycenter = ystart + y_range / 2.
            ypoints = int(y_range / self.scan["ystep"])
            scan["scan_regions"]["Region" + str(i)] = {"xStart": xstart,
                                        "xStop": xstop,
                                        "xPoints": xpoints,
                                        "xStep": self.scan["xstep"],
                                        "xRange": x_range,
                                        "xCenter": xcenter,
                                        "yStart": ystart,
                                        "yStop": ystop,
                                        "yPoints": ypoints,
                                        "yStep": self.scan["ystep"],
                                        "yRange": y_range,
                                        "yCenter": ycenter,
                                        "zStart": 0,
                                        "zStop": 0,
                                        "zPoints": 0}
            i += 1
        message = {"command": "doScan", "scan": scan}
        self.sock.send_pyobj(message)
        response = self.sock.recv_pyobj()
        if not response["status"]:
            return False
        file_name = response["data"]
        status = False
        while not status:
            sleep(1)
            self.sock.send_pyobj({"command":"getStatus"})
            response = self.sock.recv_pyobj()
            status = response["status"]
        return file_name

    def multi_region_stxm_scan(self, scanRegList):
        # s = connect(ADDRESS, PORT)
        scan = {"scan_type": self.scan["scan_type"], "proposal": self.scan["proposal"], "experimenters": self.scan["experimenters"], "nx_file_version": 3,
                "sample": self.scan["Sample"],
                "x_motor": "SampleX",
                "y_motor": "SampleY",
                "energy_motor": "Energy",
                "doubleExposure": False,
                "n_repeats": 1,
                "defocus": False,
                "autofocus": self.scan["autofocus"],
                "oversampling_factor": 1,
                "mode": self.scan["mode"],
                "coarse_only": False,
                "spiral": self.scan["spiral"],
                "daq_list": self.scan["daq_list"],
                "comment": self.scan["comment"],
                "coarse_only": False,
                "loop_scan": self.scan["loop_scan"],
                "energy_regions": build_energy_regions(self.scan)
                }
        scan["scan_regions"] = {}
        i = 1
        for region in scanRegList:
            xstart, xstop, ystart, ystop = region
            x_range = xstop - xstart
            xcenter = xstart + x_range / 2.
            xpoints = int(x_range / self.scan["xstep"])
            y_range = ystop - ystart
            ycenter = ystart + y_range / 2.
            ypoints = int(y_range / self.scan["ystep"])
            scan["scan_regions"]["Region" + str(i)] = {"xStart": xstart,
                                        "xStop": xstop,
                                        "xPoints": xpoints,
                                        "xStep": self.scan["xstep"],
                                        "xRange": x_range,
                                        "xCenter": xcenter,
                                        "yStart": ystart,
                                        "yStop": ystop,
                                        "yPoints": ypoints,
                                        "yStep": self.scan["ystep"],
                                        "yRange": y_range,
                                        "yCenter": ycenter,
                                        "zStart": 0,
                                        "zStop": 0,
                                        "zPoints": 0}
            i += 1
        energy_list = energy_list_for_scan(self.scan)
        if energy_list is not None:
            scan["energy_list"] = energy_list
            scan["dwell"] = self.scan["dwell"]
        if self.scan["spiral"]:
            scan["driver"] = self.SCANS["Spiral Image"]["driver"] #"spiral_image"
            scan["scan_type"] = 'Spiral Image'
        else:
            scan["driver"] = self.SCANS["Image"]["driver"] #"line_image"
        message = {"command": "doScan", "scan": scan}
        self.sock.send_pyobj(message)
        response = self.sock.recv_pyobj()
        if not response["status"]:
            return False
        file_name = response["data"]
        status = False
        while not status:
            sleep(1)
            self.sock.send_pyobj({"command":"getStatus"})
            response = self.sock.recv_pyobj()
            status = response["status"]
        return file_name

    def get_motor_position(self, motor):
        self.sock.send_pyobj({"command": "getMotorPositions"})
        response = self.sock.recv_pyobj()
        return response['data'][motor]
    
    def help(self):
        print('='*40)
        print("Current scan definition")
        print('='*40)
        for key in self.scan.keys():
            print(f"{key}: \t{self.scan[key]}")
        print('='*40)
        print("Available Motors and positions")
        print('='*40)
        for key in self.MOTORS.keys():
            if key != 'status':
                print(f"{key}: \t{self.POSITIONS[key]}")
        print('='*40)
        print("Available Scans")
        print('='*40)
        for key in self.SCANS.keys():
            print(f"{key}")
        print('='*40)
        print("Available daqs")
        print('='*40)
        for key in self.DAQS.keys():
            print(f"{key}")
        print('='*40)





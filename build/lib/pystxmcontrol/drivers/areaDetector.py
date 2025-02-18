import time, traceback
import numpy as np
from pystxmcontrol.controller.daq import daq
from epics import caget, caput, cainfo

class areaDetector(daq):
    def __init__(self, address = "BL7ANDOR1", simulation = False):
        self.address = address
        self.simulation = simulation
        self.timeout = 1
        self.framenum = 0
        self.image_prefix = ':image1'
        self.camera_prefix = ':cam1'
        self.dim = 1024
        #set up a ZMQ publisher
        if not(self.simulation):
            pass

    def start(self):
        self.fbuffer = []
        if not (self.simulation):
            try:
                #put something here about setting the acquisition mode
                self.temperature = caget(self.address + self.camera_prefix + ":TemperatureActual.VAL")
            except Exception:
                print("Failed to connect to Andor camera with error: \n\s" %traceback.format_exc())
            else:
                print("Connected to Andor server.  Current temperature: %.2f degrees" %self.temperature)

    def stop(self):
        if not (self.simulation):
            pass

    def set_dwell(self, dwell):
        self.dwell = dwell

    def config(self, dwell = 2, dwell2 = 0, exposure_mode = 0):
        #need to configure for external trigger
        #need to test acquisitions using an internal trigger
        self.dwell = dwell
        self.dwell2 = dwell2
        self.doubleExposureMode = exposure_mode

        if self.simulation:
            pass
        else:
            #set exposure times
            caput(self.address + self.camera_prefix + ":TriggerMode", "External", wait = True)
            caput(self.address + self.camera_prefix + ":ImageMode", "Continuous", wait=True)
            caput(self.address + self.camera_prefix + ":AcquireTime.VAL", dwell / 1000., wait = True)
            #self.readout_time is the total time including exposure.  This is in seconds
            self.readout_time_seconds = caget(self.address + self.camera_prefix + ":AcquirePeriod_RBV")
            #reset counter
            self.framenum = 0

    def init(self):
        caput(self.address + self.camera_prefix + ":Acquire", 1)


    def getPoint(self):
        self.framenum += 1
        if self.simulation:
            #time.sleep(self.dwell / 1000.)
            return self.framenum - 1, 2. * np.random.random((1040,1152))
        else:
            time.sleep(self.readout_time_seconds)
            self.frame = caget(self.address + self.image_prefix + ":ArrayData")
            #publish each frame to ZMQ to it can be received by GUI
            return self.framenum - 1, np.reshape(self.frame, (self.dim,self.dim))

    def getLine(self):
        pass


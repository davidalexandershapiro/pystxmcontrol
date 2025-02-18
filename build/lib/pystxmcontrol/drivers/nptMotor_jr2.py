# -*- coding: utf-8 -*-
from pystxmcontrol.controller.motor import motor
import time
import numpy as np

class nptMotor(motor):

    def __init__(self, controller = None):

        # refer to page 29 of NPoint manual for device write/read formatting info
        #self.devID = ftdi_device_id
        self.controller = controller
        self.axesList = list(enumerate(['x','y']))
        #self.simulation = False
        self.config = None
        self.axis = None
        self.position = 0.
        self.waitTime = 0.0
        self.minValue = -50.0
        self.maxValue = 50.0
        self.offset = 0.0
        self.lineCenterX = 0.
        self.lineCenterY = 0.
        self.linePixelSize = 0.1
        self.linePixelCount = 11
        self.linePixelDwellTime = 10.
        self.lineDwellTime = 0.
        self.pulseOffsetTime = 0.0
        self.imageLineCount = 1
        #self.lineMode = "raster"
        self.lineMode = 0
        self.trajectory_start = 0
        self.trajectory_stop = 0.1
        self.trajectory_pixel_count = 10 #integer number of pixels in a trajectory
        self.trajectory_pixel_dwell = 1 #millisecond dwell time per trajectory pixel
        self._tragectory_trigger = None
        self.trigger_axis = 1 #1 for X and 2 for Y
        self.velocity = 0.2 ##microns/millisecond
        self.pad = 0.2 ##nanometers
        self.xpad = None
        self.ypad = None
        self.acceleration = 0.02
        self._padMaximum = 5.0
        self.offset = 0.
        self.units = 1.

    def connect(self, axis = 'x'):
        self.simulation = self.controller.simulation
        self.axis = axis
        self.fastAxis = axis
        if not(self.simulation):
            self._axis = self.controller.getAxis(self.axis)
            self.pid = self.controller.pidRead(axis = self._axis)
            self.position = self.controller.getPos(axis = self._axis)

    def getStatus(self, **kwargs):
        pass

    def moveBy(self, pos = None):
        pass

    def update_trajectory(self):
        x_range = abs(self.trajectory_start[0] - self.trajectory_stop[0])
        y_range = abs(self.trajectory_start[1] - self.trajectory_stop[1])
        self.velocity = np.sqrt(x_range**2 + y_range**2) / (self.trajectory_pixel_count * self.trajectory_pixel_dwell)

        self._xVelocity = x_range / (self.trajectory_pixel_count * self.trajectory_pixel_dwell)
        self._yVelocity = y_range / (self.trajectory_pixel_count * self.trajectory_pixel_dwell)

        self.xpad = 0.5 * self._xVelocity**2 / self.acceleration
        self.ypad = 0.5 * self._yVelocity**2 / self.acceleration
        self.xpad = min(self.xpad,self._padMaximum)
        self.ypad = min(self.ypad,self._padMaximum)

        #select the trigger axis based on which dimension travels further.  This accounts for 1D trajectories
        #2D trajectories could trigger off of either axis
        if x_range < y_range:
            self.trigger_axis = 2
        else:
            self.trigger_axis = 1


    def moveTo(self, pos = None):
        if not(self.simulation):
            self.controller.moveTo(axis = self._axis, pos = pos)
            time.sleep(0.01) #piezo settling time of 10 ms
        else:
            self.position = pos
            time.sleep(self.waitTime / 1000.)

    def moveLine(self, direction = 1):
        #convert milliseconds to seconds for the controller call
        #if self.lineMode == 'raster':
        if self.lineMode == 0:
            if not(self.simulation):
                self.controller.rasterScan(center = (self.lineCenterX,self.lineCenterY), fastAxis = self.fastAxis, 
                                pixelSize = self.linePixelSize, pixelCount = (self.linePixelCount,self.imageLineCount), 
                                pixelDwellTime = self.linePixelDwellTime/1000., lineDwellTime = self.lineDwellTime/1000., 
                                pulseOffsetTime = self.pulseOffsetTime/1000.)
            else:
                pass
        #elif self.lineMode == 'continuous':
        elif self.lineMode == 1:
            self.update_trajectory()
            x0,y0 = self.trajectory_start
            x1,y1 = self.trajectory_stop
            #if direction == "forward":
            if direction == 1:
                start = x0 - self.xpad, y0 - self.ypad
                stop = x1 + self.xpad, y1 + self.ypad
                self._trajectory_trigger = x0,y0
           #elif direction == "backward":
            elif direction == 0:
                start = x1 + self.xpad, y1 + self.ypad
                stop = x0 - self.xpad, y0 - self.ypad
                self._trajectory_trigger = x1,y1
            if not (self.simulation):
                self.controller.linear_trajectory(start, stop, trigger_axis = self.trigger_axis, \
                                    trigger_position = self._trajectory_trigger[self.trigger_axis-1], \
                                    velocity = (self._xVelocity,self._yVelocity), dwell = 10.)

    def getPos(self):
        if not(self.simulation):
            return self.controller.getPos(axis = self._axis)
        else:
            return self.position

    def get_status(self):
        return self.controller.get_status(axis=self._axis)



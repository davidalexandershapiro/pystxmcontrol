# -*- coding: utf-8 -*-
from pystxmcontrol.controller.motor import motor
import time
import numpy as np

class nptMotor(motor):

    def __init__(self, controller = None, config = None):

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
        self.lineMode = "raster"
        #self.lineMode = 0
        self.trajectory_start = 0
        self.trajectory_stop = 0.1
        self.trajectory_pixel_count = 10 #integer number of pixels in a trajectory
        self.trajectory_pixel_dwell = 1 #millisecond dwell time per trajectory pixel
        self._tragectory_trigger = None
        self.trigger_axis = 1 #1 for X and 2 for Y
        self.velocity = 0.2 ##microns/millisecond
        self.pad = 0.2 ##nanometers
        self.acceleration = 0.05
        self._padMaximum = 5.0
        self._padMinimum = 0.2
        self.units = 1.

    def connect(self, axis = 'x'):
        self.simulation = self.controller.simulation
        self.axis = axis
        self.fastAxis = axis
        if not(self.simulation):
            self._axis = self.controller.getAxis(self.axis)
            self.pid = self.controller.pidRead(axis = self._axis)
            self.position = self.controller.getPos(axis = self._axis)

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getPID(self):
        if not(self.simulation):
            self.pid = self.controller.pidRead(axis = self._axis)
            return self.pid
        else:
            return (0.,150.,0.)
        
    def setPID(self, pid):
        if not(self.simulation):
            self.controller.pidWrite(pid, axis = self._axis)

    def getStatus(self, **kwargs):
        return False

    def moveBy(self, pos = None):
        pass

    def stop(self):
        return
        
    def setPositionTriggerOn(self, pos, debug = False):
        if not(self.simulation):
            if debug:
                print(f"[nptMotor] Turning position trigger on for axis {self._axis} at position {pos}")
            self.controller.setPositionTrigger(pos = pos, axis = self._axis, mode = 'on')
        
    def setPositionTriggerOff(self):
        if not(self.simulation):
            self.controller.setPositionTrigger()

    def update_trajectory(self, direction = "forward"):
        #FIXME commented out tuple values for caproto use
        x_range = abs(self.trajectory_start[0] - self.trajectory_stop[0])
        y_range = abs(self.trajectory_start[1] - self.trajectory_stop[1])
        #x_range = abs(self.trajectory_start - self.trajectory_stop)
        #y_range = abs(self.trajectory_start - self.trajectory_stop)
        self.velocity = np.sqrt(x_range**2 + y_range**2) / (self.trajectory_pixel_count * self.trajectory_pixel_dwell)

        self._xVelocity = x_range / (self.trajectory_pixel_count * self.trajectory_pixel_dwell)
        self._yVelocity = y_range / (self.trajectory_pixel_count * self.trajectory_pixel_dwell)

        self.xpad = 0.5 * self._xVelocity**2 / self.acceleration
        self.ypad = 0.5 * self._yVelocity**2 / self.acceleration
        self.xpad = min(self.xpad,self._padMaximum)
        self.ypad = min(self.ypad,self._padMaximum)
        self.xpad = max(self.xpad,self._padMinimum)
        self.ypad = max(self.ypad,self._padMinimum) 

        #select the trigger axis based on which dimension travels further.  This accounts for 1D trajectories
        #2D trajectories could trigger off of either axis
        if x_range < y_range:
            self.trigger_axis = 2
            self.xpad = 0
        else:
            self.trigger_axis = 1
            self.ypad = 0
            
        x0,y0 = self.trajectory_start
        x1,y1 = self.trajectory_stop
        if direction == "forward":
            self.start = x0 - self.xpad, y0 - self.ypad
            self.stop = x1 + self.xpad, y1 + self.ypad
            #start = x0, y0
            #stop = x1, y1
            self.trajectory_trigger = x0,y0
        elif direction == "backward":
            self.start = x1 + self.xpad, y1 + self.ypad
            self.stop = x0 - self.xpad, y0 - self.ypad
            self.trajectory_trigger = x1,y1

    def moveTo(self, pos = None):
        if self.checkLimits(pos):
            if not(self.simulation):
                pos = round((pos - self.config["offset"]) / self.config["units"],3)
                self.controller.moveTo(axis = self._axis, pos = pos)
                time.sleep(0.01) #piezo settling time of 10 ms
            else:
                self.position = pos
                time.sleep(self.waitTime / 1000.)
        else:
            print("[nPoint] Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def moveTo2(self, pos = None):
        if self.checkLimits(pos):
            if not(self.simulation):
                self.controller.moveTo2(axis = self._axis, pos = pos)
                time.sleep(0.01) #piezo settling time of 10 ms
            else:
                self.position = pos
                time.sleep(self.waitTime / 1000.)
        else:
            print("[nPoint] Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def moveLine(self, direction = "forward"):
        #convert milliseconds to seconds for the controller call
        """
        Currently not protected by limits
        """
        if self.lineMode == 'raster':
            if not(self.simulation):
                self.controller.rasterScan(center = (self.lineCenterX,self.lineCenterY), fastAxis = self.fastAxis, 
                                pixelSize = self.linePixelSize, pixelCount = (self.linePixelCount,self.imageLineCount), 
                                pixelDwellTime = self.linePixelDwellTime/1000., lineDwellTime = self.lineDwellTime/1000., 
                                pulseOffsetTime = self.pulseOffsetTime/1000.)
            else:
                pass
        elif self.lineMode == 'continuous':
            self.update_trajectory(direction = direction)
            if not (self.simulation):
                self.controller.linear_trajectory(self.start, self.stop, trigger_axis = self.trigger_axis, \
                                    trigger_position = self.trajectory_trigger[self.trigger_axis-1], \
                                    velocity = (self._xVelocity,self._yVelocity), dwell = 10.)
                self.positions = np.zeros((self.trajectory_pixel_count))

    def getPos(self):
        if not(self.simulation):
            pos = self.controller.getPos(axis = self._axis)
            self.position = pos * self.config["units"] + self.config["offset"]
            return self.position
        else:
            return self.position
            
    def setZero(self):
        if not(self.simulation):
            self.controller.setZero(self._axis)
        else:
            self.position = 0.
        
    def servoState(self, servo = True):
        if not(self.simulation):
            self.controller.sWrite(self._axis, int(servo))

    def get_status(self):
        if not(self.simulation):
            return self.controller.get_status(axis=self._axis)
        else:
            return False



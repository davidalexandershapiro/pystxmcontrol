# -*- coding: utf-8 -*-
from pystxmcontrol.controller.motor import motor
import time
import numpy as np

class mclMotor(motor):

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
        self.trajectory_start = 0
        self.trajectory_stop = 0.1
        self.trajectory_pixel_count = 10 #integer number of pixels in a trajectory
        self.trajectory_pixel_dwell = 1 #millisecond dwell time per trajectory pixel
        self.trajectory_xpositions = None
        self.trajectory_ypositions = None
        self._tragectory_trigger = None
        self.trigger_axis = 1 #1 for X and 2 for Y
        self.velocity = 0.2 ##microns/millisecond
        self.pad = 0.2 ##nanometers
        self.acceleration = 0.05
        self._padMaximum = 5.0
        self._padMinimum = 0.4
        self.units = 1.
        self.include_return = True
        self.config = {"minValue":0,"maxValue":100,"offset":0,"units":1.}

    def connect(self, axis = 'x'):
        self.simulation = self.controller.simulation
        self.axis = axis
        self.fastAxis = axis
        if not(self.simulation):
            self._axis = self.controller.getAxis(self.axis)
            self.pid = self.controller.readPID(axis = self._axis)
            self.position = self.controller.read(axis = self._axis)
            #self.controller.setPositionTrigger(pos = 0, axis = 1, mode = 'on',clock = 2)

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getPID(self):
        if not(self.simulation):
            self.pid = self.controller.readPID(axis = self._axis)
            return self.pid
        else:
            return (0.,150.,0.)
        
    def setPID(self, pid):
        if not(self.simulation):
            self.controller.writePID(pid, axis = self._axis)

    def getStatus(self, **kwargs):
        return False

    def moveBy(self, pos = None):
        pass

    def stop(self):
        return
        
    def setPositionTriggerOn(self, pos):
        if not(self.simulation):
            #print("Setting position trigger on axis %i and position = %.4f" %(self.trigger_axis,pos))
            self.controller.setPositionTrigger(pos = pos, axis = self.trigger_axis, mode = 'on')
        
    def setPositionTriggerOff(self):
        if not(self.simulation):
            self.controller.setPositionTrigger()

    def scale2controller(self, value):
        return (value - self.config["offset"]) / self.config["units"]
    
    def scale2gui(self, value):
        return value * self.config["units"] + self.config["offset"]

    def update_trajectory(self, direction = "forward"):
    
        #If the scan is an arbitrary waveform, we have all the positions already.
        
        if self.lineMode == 'arbitrary':
            controllerxpos = self.scale2controller(self.trajectory_x_positions)
            controllerypos = self.scale2controller(self.trajectory_y_positions)
            
            axes = [self.controller.getAxis('x')-1,self.controller.getAxis('y')-1]
            ax1pos, ax2pos = [[controllerxpos,controllerypos][i] for i in axes]
            if not self.simulation:
                self.controller.setup_xy(ax1pos, ax2pos,self.trajectory_pixel_dwell)
            self.npositions = len(self.trajectory_x_positions)

            self.trajectory_trigger = controllerxpos[0],controllerypos[0]
            return
    
        
        #FIXME commented out tuple values for caproto use
        x_range = abs(self.trajectory_start[0] - self.trajectory_stop[0])
        y_range = abs(self.trajectory_start[1] - self.trajectory_stop[1])

        self.pad = 0.5*self.velocity**2 / self.acceleration
        self.pad = min(self.pad, self._padMaximum)
        self.pad = max(self.pad, self._padMinimum)
        
        x0,y0 = self.trajectory_start
        x1,y1 = self.trajectory_stop
        
        self.direction = np.array([x1-x0,y1-y0])/np.linalg.norm([x1-x0,y1-y0])
        
        self.xpad = self.pad*self.direction[0]
        self.ypad = self.pad*self.direction[1]
        
        x_range += 2*self.xpad
        y_range += 2*self.ypad

        #select the trigger axis based on which dimension travels further.  This accounts for 1D trajectories
        #2D trajectories could trigger off of either axis
        if x_range < y_range:
            self.trigger_axis = 1
            #self.xpad = 0
        else:
            self.trigger_axis = 2
            #self.ypad = 0

        if direction == "forward":
            #self.start = x0 - self.xpad, y0 - self.ypad
            self.start = x0-self.xpad, y0 -self.ypad
            self.stop = x1 + self.xpad, y1 + self.ypad
            self.trajectory_trigger = x0,y0
        elif direction == "backward":
            self.start = x1 + self.xpad, y1 + self.ypad
            self.stop = x0 - self.xpad, y0 - self.ypad
            self.trajectory_trigger = x1,y1
        self.start = self.scale2controller(self.start[0]),self.scale2controller(self.start[1])
        self.stop = self.scale2controller(self.stop[0]),self.scale2controller(self.stop[1])

        if self.include_return:
            if y_range<0.001:
                mode = "1d_line_with_return"
                self.dim = 1
            else:
                mode = "2d_line_with_return"
                self.dim = 2
        else: 
            mode = "line"
            self.dim = 2
        if not (self.simulation):
            self.controller.setup_trajectory(self.trigger_axis, self.start, self.stop, \
                                             self.trajectory_pixel_dwell, self.trajectory_pixel_count, \
                                             mode = mode)
            self.npositions = self.controller.npositions
        else:
            self.npositions = self.trajectory_pixel_count

    def moveTo(self, pos = None):
        if self.checkLimits(pos):
            if not(self.simulation):
                pos = (pos - self.config["offset"]) / self.config["units"]
                self.controller.write(axis = self._axis, pos = pos)
            else:
                self.position = pos
                time.sleep(self.waitTime / 1000.)
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def move2(self, pos = None):
        if self.checkLimits(pos):
            if not(self.simulation):
                start = self.controller.read(axis = self._axis)
                stop = self.scale2controller(pos)
                self.controller.setup_trajectory(self.axis, start, stop, 0.1, 20, mode = "smooth_move")
                self.positions = self.controller.trigger_1d_waveform_new(axis = self.axis)
            else:
                self.position = pos
                time.sleep(self.waitTime / 1000.)
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def moveLine(self, **kwargs):
        if self.lineMode == 'continuous':
            if not (self.simulation):
                if self.dim == 1:
                    self.positions = self.controller.trigger_1d_waveform()
                    self.positions = self.scale2gui(self.positions[0]),self.scale2gui(self.positions[1])
                else:
                    self.positions = self.controller.acquire_xy()
                    self.positions = self.scale2gui(self.positions[0]),self.scale2gui(self.positions[1])
            else:
                xpositions = np.linspace(self.trajectory_start[0],self.trajectory_stop[0],self.trajectory_pixel_count)
                ypositions = np.linspace(self.trajectory_start[1],self.trajectory_stop[1],self.trajectory_pixel_count)
                self.positions = xpositions,ypositions
        elif self.lineMode == 'arbitrary':
            if not self.simulation:
                self.positions = self.controller.acquire_xy()
                self.positions = self.scale2gui(self.positions[0]),self.scale2gui(self.positions[1])
            else:
                xpositions = self.trajectory_x_positions
                ypositions = self.trajectory_y_positions
                self.positions = xpositions, ypositions

    def getPos(self):
        if not(self.simulation):
            self.position = self.controller.read(axis = self._axis) * self.config["units"] + self.config["offset"]
            return self.position
        else:
            return self.position
            
    def setPosToZero(self):
        pass
        
    def servoState(self, servo = True):
        pass

    def get_status(self):
        return self.controller.getStatus(axis=self._axis)



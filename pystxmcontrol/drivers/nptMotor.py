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
            self.controller.setupStages()
            self._axis = self.controller.getAxis(self.axis)
            self.pid = self.controller.pidRead(axis = self._axis)
            # Latch the initial position through the bounds-checked getPos(),
            # not the raw controller read: a garbled first read (e.g. a link
            # still settling) would otherwise be stored as self.position and
            # then returned forever as the outlier fallback.
            self.position = self.getPos()

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
            #pos = round((pos - self.config["offset"]) / self.config["units"],3)
            if debug:
                print(f"[nptMotor] Turning position trigger on for axis {self._axis} at position {pos}")
            self.controller.setPositionTrigger(pos = pos, axis = self._axis, mode = 'on')
        
    def setPositionTriggerOff(self):
        if not(self.simulation):
            self.controller.setPositionTrigger()

    def _scale2controller(self, value):
        """Scale a GUI-space coordinate to controller units (matches
        derivedPiezo.scale2controller; identity when offset=0/units=1)."""
        return (value - self.config["offset"]) / self.config["units"]

    def update_trajectory(self, direction = "forward", include_return = False):
        """Pre-load a continuous fly-line trajectory on the controller.

        Mirrors the proven legacy path (derivedPiezo.update_trajectory +
        nptController.setup_trajectory): compute a single acceleration pad
        projected along the line direction, pick the trigger axis, pre-load the
        trajectory via ``controller.setup_trajectory``, and record the
        (unpadded) line-start crossing as ``trajectory_trigger``. The motion and
        the line-start gate pulse are issued later in ``moveLine`` via
        ``controller.acquire_xy`` -- NOT the older ``linear_trajectory`` path,
        which never emitted the position trigger and so wedged the counter.
        """
        x0, y0 = self.trajectory_start
        x1, y1 = self.trajectory_stop
        distance = np.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
        if distance > 0:
            self.velocity = distance / (self.trajectory_pixel_count * self.trajectory_pixel_dwell)

        self.pad = 0.5 * self.velocity ** 2 / self.acceleration
        self.pad = min(self.pad, self._padMaximum)
        self.pad = max(self.pad, self._padMinimum)
        self.direction = np.array([x1 - x0, y1 - y0]) / np.linalg.norm([x1 - x0, y1 - y0])
        self.xpad = self.pad * self.direction[0]
        self.ypad = self.pad * self.direction[1]
        x_range = abs(x0 - x1) + 2 * abs(self.xpad)
        y_range = abs(y0 - y1) + 2 * abs(self.ypad)

        #select the trigger axis based on which dimension travels further.  This accounts for 1D trajectories
        #2D trajectories could trigger off of either axis
        if x_range < y_range:
            self.trigger_axis = 2
        else:
            self.trigger_axis = 1

        if direction == "forward":
            self.start = x0 - self.xpad, y0 - self.ypad
            self.stop = x1 + self.xpad, y1 + self.ypad
            self.trajectory_trigger = x0, y0
        elif direction == "backward":
            self.start = x1 + self.xpad, y1 + self.ypad
            self.stop = x0 - self.xpad, y0 - self.ypad
            self.trajectory_trigger = x1, y1

        self.start = self._scale2controller(self.start[0]), self._scale2controller(self.start[1])
        self.stop = self._scale2controller(self.stop[0]), self._scale2controller(self.stop[1])
        if not (self.simulation):
            self.controller.setup_trajectory(self.trigger_axis, self.start, self.stop,
                                             self.trajectory_pixel_dwell,
                                             self.trajectory_pixel_count,
                                             mode="line", pad=(self.xpad, self.ypad))
            self.npositions = self.controller.npositions
        else:
            self.npositions = self.trajectory_pixel_count

    def moveTo(self, pos = None):
        if self.checkLimits(pos):
            if not(self.simulation):
                pos = round((pos - self.config["offset"]) / self.config["units"],3)
                self.controller.moveTo(axis = self._axis, pos = pos)
                #time.sleep(0.01) #piezo settling time of 10 ms
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
            # Trajectory must already be pre-loaded by update_trajectory() (the
            # fly IOC calls it just before moveLine, mirroring the legacy scan
            # sequence -- so we do NOT call it again here).
            if not (self.simulation):
                # Arm the single line-start position-trigger pulse, run the
                # pre-loaded trajectory (the controller emits the gate pulse as
                # the stage crosses trajectory_trigger, gating the counter),
                # then disarm. This is the proven derivedPiezo +
                # scan_utils.doFlyscanLine flow.
                self.setPositionTriggerOn(pos = self.trajectory_trigger[self.trigger_axis - 1])
                try:
                    positions = self.controller.acquire_xy(axes = [self.trigger_axis])
                finally:
                    self.setPositionTriggerOff()
                # Report the fast/trigger-axis pixel positions (controller ->
                # GUI units) so the fly IOC's :POS waveform gets real line
                # coordinates.
                fast = np.asarray(positions[self.trigger_axis - 1], dtype=float)
                self.positions = fast * self.config["units"] + self.config["offset"]
            else:
                (x0, y0), (x1, y1) = self.trajectory_start, self.trajectory_stop
                if self.trigger_axis == 2:  # y is the fast (triggering) axis
                    self.positions = np.linspace(y0, y1, self.trajectory_pixel_count)
                else:
                    self.positions = np.linspace(x0, x1, self.trajectory_pixel_count)

    def getPos(self):
        if not(self.simulation):
            min_val = self.config["minValue"]
            max_val = self.config["maxValue"]
            travel_range = max_val - min_val
            lower_bound = min_val - travel_range
            upper_bound = max_val + travel_range
            last_converted = None
            for attempt in range(5):
                pos = self.controller.getPos(axis=self._axis)
                converted = pos * self.config["units"] + self.config["offset"]
                last_converted = converted
                if lower_bound <= converted <= upper_bound:
                    self.position = converted
                    return self.position
                if attempt < 4:
                    time.sleep(0.02)
            print(f"[nptMotor] getPos: encoder outlier on axis {self.axis} after "
                  f"5 attempts (last read {last_converted:.3f} um, outside "
                  f"[{lower_bound:.1f}, {upper_bound:.1f}]), returning last known "
                  f"position {self.position:.3f}")
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



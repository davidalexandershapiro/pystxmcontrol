from pystxmcontrol.controller.motor import motor
import time
import numpy as np

class derivedPiezo(motor):
    def __init__(self, controller=None, simulation=False):
        """
        axis1 = FineX/Y
        axis2 = CoarseX/Y
        """
        self.controller = controller
        self.simulation = simulation
        self.position = 0.5
        self.offset = 0.
        self.units = 1.
        self.axes = {}
        self.moving = False
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
        self.trigger_axis = 1 #1 for X and 2 for Y
        self.velocity = 0.2 ##microns/millisecond
        self.pad = 0.2 ##microns
        self.acceleration = 0.05
        self._padMaximum = 5.0
        self._padMinimum = 0.2
        self.units = 1.

    def getStatus(self, **kwargs):
        return self.moving

    def stop(self):
        return

    def getPID(self):
        if not (self.simulation):
            self.pid = self.axes["axis1"].controller.pidRead(axis=self._piezoAxis)
            return self.pid
        else:
            return (0., 150., 0.)

    def setPID(self, pid):
        if not (self.simulation):
            self.axes["axis1"].controller.pidWrite(pid, axis=self._piezoAxis)

    def setPositionTriggerOn(self, pos, debug = False):
        if debug:
            print(f"[derivedPiezo] Setting position trigger for piezo axis {self.axis} (controller axes {self._piezoAxis}) at position {pos}")
        self.axes["axis1"].setPositionTriggerOn(pos = pos)

    def setPositionTriggerOff(self):
        self.axes["axis1"].setPositionTriggerOff()

    def checkLimits(self,pos,axis = 1):
        return self.axes["axis"+str(axis)].checkLimits(pos - self._coarsePos)

    def checkRange(self,positionTuple,axis=1):
        pos1,pos2 = positionTuple
        positionOK = self.checkLimits(pos1,axis) and self.checkLimits(pos2,axis)
        rangeOK = (pos2 - pos1) < (self.axes["axis1"].config["maxValue"] - self.axes["axis1"].config["minValue"])
        return positionOK, rangeOK

    def scale2controller(self, value, axis = 1):
        """
        This scales the piezo values to the piezo controller system.
        """
        return (value - self.axes["axis%i" %axis].config["offset"]) / self.axes["axis%i" %axis].config["units"]

    def scale2gui(self, value, axis = 1):
        """
        This scales from the piezo controller to the piezo system.  We also need to scale to the global system.
        """
        return value * self.axes["axis%i" %axis].config["units"] + self.axes["axis%i" %axis].config["offset"]

    def update_trajectory(self, direction="forward", include_return = False):
        """

        """
        if self.lineMode == 'arbitrary':
            controllerxpos = self.scale2controller(self.trajectory_x_positions)
            controllerypos = self.scale2controller(self.trajectory_y_positions)

            axes = [self.axes["axis1"].controller.getAxis('x') - 1, self.axes["axis1"].controller.getAxis('y') - 1]
            ax1pos, ax2pos = [[controllerxpos, controllerypos][i] for i in axes]
            if not self.simulation:
                self.axes["axis1"].controller.setup_xy(ax1pos, ax2pos, self.trajectory_pixel_dwell)
            self.npositions = len(self.trajectory_x_positions)

            self.trajectory_trigger = controllerxpos[0], controllerypos[0]
            return

        x_range = abs(self.trajectory_start[0] - self.trajectory_stop[0])
        y_range = abs(self.trajectory_start[1] - self.trajectory_stop[1])
        self.pad = 0.5 * self.velocity ** 2 / self.acceleration
        self.pad = min(self.pad, self._padMaximum)
        self.pad = max(self.pad, self._padMinimum)
        x0, y0 = self.trajectory_start
        x1, y1 = self.trajectory_stop
        self.direction = np.array([x1 - x0, y1 - y0]) / np.linalg.norm([x1 - x0, y1 - y0])
        self.xpad = self.pad * self.direction[0]
        self.ypad = self.pad * self.direction[1]
        x_range += 2 * self.xpad
        y_range += 2 * self.ypad

        # select the trigger axis based on which dimension travels further.  This accounts for 1D trajectories
        # 2D trajectories could trigger off of either axis
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
        self.start = self.scale2controller(self.start[0]), self.scale2controller(self.start[1])
        self.stop = self.scale2controller(self.stop[0]), self.scale2controller(self.stop[1])
        if include_return:
            if y_range < 0.001:
                mode = "1d_line_with_return"
                self.dim = 1
            else:
                mode = "2d_line_with_return"
                self.dim = 2
        else:
            mode = "line"
            self.dim = 2
        if not (self.simulation):
            self.axes["axis1"].controller.setup_trajectory(self.trigger_axis, self.start, self.stop, \
                                             self.trajectory_pixel_dwell, self.trajectory_pixel_count, \
                                             mode=mode,pad=(self.xpad,self.ypad))
            self.npositions = self.axes["axis1"].controller.npositions
        else:
            self.npositions = self.trajectory_pixel_count

    def moveLine(self, **kwargs):
        #convert milliseconds to seconds for the controller call
        """
        Currently not protected by limits
        """
        if "coarse_only" in kwargs.keys():
            coarse_only = kwargs["coarse_only"]
        else:
            coarse_only = False
        if "coarse_offset" in kwargs.keys():
            offset = kwargs["coarse_offset"]
        else:
            offset = [0,0]
        if "axes" in kwargs.keys():
            axes = kwargs["axes"]
        else:
            axes = [1,]

        if self.lineMode == 'continuous':
            if not(coarse_only):
                if not (self.simulation):
                    if self.dim == 1:
                        self.positions = self.axes["axis1"].controller.trigger_1d_waveform()
                    else:
                        self.positions = self.axes["axis1"].controller.acquire_xy(axes=axes)

                    self.positions = self.scale2gui(self.positions[0]) + offset[0], self.scale2gui(self.positions[1]) + offset[1]
                else:
                    xpositions = np.linspace(self.trajectory_start[0], self.trajectory_stop[0],
                                             self.trajectory_pixel_count)
                    ypositions = np.linspace(self.trajectory_start[1], self.trajectory_stop[1],
                                             self.trajectory_pixel_count)
                    self.positions = xpositions + offset[0], ypositions + offset[1]
            #commenting this so I can test the coarse stage scan without the piezo talking
            #elif not(self.simulation):
            else:
                #this hack just applies to the XPS which  uses microns/second for velocity.  Need to generalize units in config
                #self.velocity is calculated above with reasonable units of microns/millisecond
                xpositions = np.linspace(self.trajectory_start[0], self.trajectory_stop[0],
                                         self.trajectory_pixel_count)
                ypositions = np.linspace(self.trajectory_start[1], self.trajectory_stop[1],
                                         self.trajectory_pixel_count)
                self.positions = xpositions + offset[0], ypositions + offset[1]
                x_range = abs(self.trajectory_start[0] - self.trajectory_stop[0])
                velocity = x_range / (self.trajectory_pixel_dwell * self.trajectory_pixel_count)
                if velocity > self.axes["axis2"].config["max velocity"]:
                    velocity = self.axes["axis2"].config["max velocity"]
                self.axes["axis2"].setAxisParams(velocity = velocity)
                t0 = time.time()
                self.moveTo(self.stop[0], coarse_only = True)
                #print(f"[derived piezo] moving {self.axis} to {self.stop[0]} took {time.time()-t0} seconds")
                self.axes["axis2"].setAxisParams(velocity = 2.0)
        elif self.lineMode == 'arbitrary':
            if not self.simulation:
                self.positions = self.axes["axis1"].controller.acquire_xy()
                self.positions = self.scale2gui(self.positions[0]) + offset[0], self.scale2gui(self.positions[1]) + offset[1]
            else:
                xpositions = self.trajectory_x_positions
                ypositions = self.trajectory_y_positions
                self.positions = xpositions + offset[0], ypositions + offset[1]

    def moveBy(self, step):
        if not (self.simulation):
            self.moving = True
            self.getPos()
            self.moveTo(self.position + step)
            self.moving = False
        else:
            self.position = self.position + step

    def moveTo(self, pos = None, sleep = True, **kwargs):
        pos = (pos - self.config["offset"]) / self.config["units"]
        if "coarse_only" in kwargs.keys():
            coarse_only = kwargs["coarse_only"]
        else:
            coarse_only = False
        self.moving = True
        deltaPos = pos - self.getPos()
        newFinePos = self._finePos + deltaPos
        if self.axes["axis1"].checkLimits(newFinePos) and not(coarse_only):
            self.axes["axis1"].moveTo(newFinePos)
        else:
            self.axes["axis1"].moveTo(pos = 0.)
            if self.config["reset_after_move"]:
                self.axes["axis1"].servoState(False)
                time.sleep(0.03)
                self.axes["axis1"].setZero()
            self.axes["axis2"].moveTo(pos)
            if self.config["reset_after_move"]:
                self.axes["axis1"].setZero()
                self.axes["axis1"].servoState(True)
                #use the piezo to clean up slop in the coarse motion
                deltaPos = pos - self.getPos()
                if self.axes["axis1"].checkLimits(deltaPos) and not(coarse_only):
                    self.axes["axis1"].moveTo(deltaPos)
        self.moving = False

    def moveCoarse(self, pos):
        pos = (pos - self.config["offset"]) / self.config["units"]
        self.moving = True
        self.axes["axis1"].moveTo(pos = 0.)
        if self.config["reset_after_move"]:
            self.axes["axis1"].servoState(False)
            self.axes["axis1"].setZero()
        self.axes["axis2"].moveTo(pos)
        if self.config["reset_after_move"]:
            self.axes["axis1"].setZero()
            self.axes["axis1"].servoState(True)
        self.getPos()
        self.moving = False

    def getPos(self, setPointOnly = True):
        self._finePos = self.axes["axis1"].getPos()
        self._coarsePos = self.axes["axis2"].getPos()
        self.position = self._coarsePos + self._finePos
        return self.position * self.config["units"] + self.config["offset"]

    def decompose(self, pos):
        deltaPos = pos - self.getPos(setPointOnly = True)
        newFinePos = self._finePos + deltaPos
        if self.axes["axis1"].checkLimits(newFinePos):
            return newFinePos, self.axes["axis2"].getPos()
        else:
            return 0.,pos

    def decompose_range(self, pmin,pmax):
        """
        This will generate the tiles of a tiled fine scan.  For each block, the fine motor is at 0 in the center and
        scans some range to be determined here.  For each block, there is a specific coarse position.  This function
        will return a list of coarse positions and fine ranges for the list of blocks.
        """
        ##calculate the number of blocks in each dimension
        prange = round(pmax - pmin,2)
        piezo_range = self.axes["axis1"].config["maxScanRange"] #axis1 is the piezo
        nblocks = int(1 + (prange // piezo_range) * (prange > piezo_range))

        ###start with the simple case of a single block, the fine range is less than or equal to its maximum allowed
        if nblocks == 1:
            if (self.checkLimits(pmin, 1) and self.checkLimits(pmax, 1)):
                pcoarse = self._coarsePos
                fine_start = pmin - self._coarsePos
                fine_stop = pmax - self._coarsePos
            else:
                pcoarse = (pmax + pmin) / 2.
                fine_start = -prange / 2.
                fine_stop = prange / 2.
        else:
            trailing_block_size = (prange % piezo_range) * bool(nblocks - 1) ##set to 0 for 1 block
            pcoarse = [pmin + piezo_range / 2. + (i * piezo_range) for i in range(nblocks - 1)]
            fine_start = [-piezo_range / 2 for i in range(nblocks -1)]
            fine_stop = [piezo_range / 2 for i in range(nblocks -1)]
            if trailing_block_size:
                pcoarse.append(pcoarse[-1] + piezo_range / 2. + trailing_block_size / 2)
                fine_start.append(-trailing_block_size / 2.)
                fine_stop.append(trailing_block_size / 2.)
            else:
                pcoarse.append((pmax + pmin) / 2.)
                fine_start.append(-prange / 2.)
                fine_stop.append(prange / 2.)

        return nblocks,pcoarse,fine_start,fine_stop

    def move_coarse_to_fine_range(self,pmin,pmax):
        if not (self.checkLimits(pmin,1) and self.checkLimits(pmax,1)):
            self.moveCoarse((pmin + pmax) / 2.)

    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs.keys():
            self.logger = kwargs["logger"]
        self.simulation = self.config["simulation"]
        self.axis = axis
        self.position = self.getPos()
        self.piezoAxis = self.axes["axis1"].axis #str X/Y
        self._piezoAxis = self.axes["axis1"].controller.getAxis(self.piezoAxis) #int 1/2

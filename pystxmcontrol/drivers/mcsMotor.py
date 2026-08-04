from pystxmcontrol.controller.motor import motor
import time

class mcsMotor(motor):
    def __init__(self, controller=None, config=None):
        self.controller = controller
        self.config = config
        self.position = 0.5
        self.offset = 0.
        self.units = 1.
        self.calibratedPosition = 0.
        self.moving = False
        self.config = {"minValue":-3000,"maxValue":3000,"units":0.000001,"offset":0} #convert micrometers to picometers
        self.auto_sensor = False

        # --- trajectory (spiral/arbitrary) state -----------------------------
        # Mirrors mclMotor so a SmarAct fine stage can serve as the trajectory
        # motor for derived_spiral_image, either directly or as a derivedPiezo
        # axis1.  The scan/derived layer populates these before calling
        # update_trajectory()/moveLine().
        self.lineMode = "raster"
        self.trajectory_pixel_count = 10   # integer number of pixels in a trajectory
        self.trajectory_pixel_dwell = 1    # millisecond dwell per trajectory pixel
        self.trajectory_x_positions = None
        self.trajectory_y_positions = None
        self.trajectory_trigger = (0., 0.)
        self.trigger_axis = 1              # 1 for X, 2 for Y
        self.npositions = 0
        self.velocity = 0.2                # microns/millisecond

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getStatus(self, **kwargs):
        if not (self.simulation):
            with self.lock:
                self.moving = self.controller.getStatus(self._axis)
        return self.moving

    def moveBy(self, step):
        self.position += step

    def set_sensor_on(self):
        self.controller.set_sensor_on(self._axis)

    def set_sensor_off(self):
        self.controller.set_sensor_off(self._axis)

    def set_sensor_auto(self):
        self.controller.set_sensor_auto(self._axis)

    def moveTo(self, pos):
        if self.checkLimits(pos):
            if not (self.simulation):
                t0 = time.time()
                with self.lock:
                    self.moving = True
                    if self.auto_sensor: self.set_sensor_on()
                    pos = (pos - self.config["offset"]) / self.config["units"]
                    self.controller.move(self._axis,pos)
                    if self.auto_sensor: self.set_sensor_off()
            else:
                self.position = pos
        else:
            print(f"[mcsMotor] Software limits exceeded for axis {self.axis}. Requested position: {pos}",
                            level="info")

    def getPos(self):
        if not self.simulation:
            with self.lock:
                if self.auto_sensor: self.set_sensor_on()
                self.position = self.controller.getPos(self._axis) * self.config["units"] + self.config["offset"]
                if self.auto_sensor: self.set_sensor_off()
                return self.position
        else:
            return self.position

    def home(self):
        if not self.simulation:
            self.controller.home(self._axis)

    def stop(self):
        if not self.simulation:
            self.controller.stop(self._axis)

    def setAxisParams(self, velocity):
        if not self.simulation:
            self.controller.set_velocity(self._axis,velocity)

    def scale2controller(self, value):
        """GUI units (microns) -> controller units (picometres)."""
        return (value - self.config["offset"]) / self.config["units"]

    def scale2gui(self, value):
        """Controller units (picometres) -> GUI units (microns)."""
        return value * self.config["units"] + self.config["offset"]

    def update_trajectory(self, direction="forward"):
        """Load a streamed (arbitrary/spiral) trajectory into the controller.

        Mirrors ``mclMotor.update_trajectory`` for ``lineMode == 'arbitrary'``: the
        pre-computed x/y position arrays are scaled to controller units, ordered per
        the controller's getAxis convention, and handed to ``setup_xy``.

        The MCS2 trajectory driver only supports streamed (arbitrary/spiral) motion;
        it has no ``setup_trajectory`` for continuous raster lines, so any other
        ``lineMode`` is rejected rather than silently mis-scanned.
        """
        if self.lineMode == 'arbitrary':
            controllerxpos = self.scale2controller(self.trajectory_x_positions)
            controllerypos = self.scale2controller(self.trajectory_y_positions)

            axes = [self.controller.getAxis('x') - 1, self.controller.getAxis('y') - 1]
            ax1pos, ax2pos = [[controllerxpos, controllerypos][i] for i in axes]
            if not self.simulation:
                self.controller.setup_xy(ax1pos, ax2pos, self.trajectory_pixel_dwell)
            self.npositions = len(self.trajectory_x_positions)
            self.trajectory_trigger = controllerxpos[0], controllerypos[0]
            return

        raise NotImplementedError(
            "[mcsMotor] update_trajectory supports lineMode='arbitrary' (spiral) only; "
            "the MCS2 driver has no continuous-line trajectory (setup_trajectory).")

    def moveLine(self, **kwargs):
        """Execute the prepared trajectory and store the achieved positions.

        For ``lineMode == 'arbitrary'`` this triggers the stream and reads back the
        measured (captured) positions via the controller, then scales them to GUI
        units.  In simulation it echoes the commanded arrays.
        """
        if self.lineMode == 'arbitrary':
            if not self.simulation:
                self.positions = self.controller.acquire_xy()
                self.positions = self.scale2gui(self.positions[0]), self.scale2gui(self.positions[1])
            else:
                self.positions = self.trajectory_x_positions, self.trajectory_y_positions
            return

        raise NotImplementedError(
            "[mcsMotor] moveLine supports lineMode='arbitrary' (spiral) only.")

    def armLine(self, **kwargs):
        """DAQ-master path: arm the externally-clocked stream before the DAQ starts.

        The trajectory must already be loaded (update_trajectory -> setup_xy).  Opens
        the stream in EXTERNAL_SYNC and leaves it waiting for the DAQ gate edges; the
        caller starts the DAQ, then calls finishLine().  No-op in simulation.
        """
        if self.simulation:
            return
        self.controller.set_stream_clock(
            "external", input_index=self.config.get("stream_trigger_input"))
        self.controller.arm_xy()

    def finishLine(self, **kwargs):
        """DAQ-master path: drain the DAQ-clocked stream and store positions."""
        if self.simulation:
            self.positions = self.trajectory_x_positions, self.trajectory_y_positions
            return
        self.positions = self.controller.finish_xy()
        self.positions = self.scale2gui(self.positions[0]), self.scale2gui(self.positions[1])

    def servoState(self, servo=True):
        """No-op for parity with mclMotor (the MCS2 flexure is always closed-loop)."""
        pass

    def setPosToZero(self):
        """No-op for parity with mclMotor."""
        pass

    def get_status(self):
        if not self.simulation:
            return self.controller.getStatus(axis=self._axis)
        return self.moving

    def setPositionTriggerOn(self, pos, increment=None):
        """Enable the DAQ pixel-clock trigger output on this motor's channel."""
        if not self.simulation:
            self.controller.setPositionTrigger(pos=pos, axis=self._axis,
                                               mode="on", increment=increment)

    def setPositionTriggerOff(self):
        if not self.simulation:
            self.controller.setPositionTrigger(axis=self._axis, mode="off")

    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs.keys():
            self.logger = kwargs["logger"]
        self.simulation = self.config.get("simulation", True)
        self.lock = self.controller.lock
        self.axis = axis
        # Stage type governs whether this channel can run trajectory streams
        # (spiral scans).  Defaults to stick-slip to preserve historical behaviour.
        self.stage_type = self.config.get("stage_type", "stick-slip")
        if axis == 'x':
            self._axis = self.config.get("controller_index",0)
        elif axis == 'y':
            self._axis = self.config.get("controller_index",1)
        elif axis == 'z':
            self._axis = self.config.get("controller_index",2)
        if not self.simulation:
            self.controller.setup_axis(self._axis, stage_type=self.stage_type)
            # Publish the (scan axis -> channel) mapping so the shared controller
            # can assemble 2-D trajectory streams across both fine axes.
            self.controller.register_axis(axis, self._axis, stage_type=self.stage_type)
        return True

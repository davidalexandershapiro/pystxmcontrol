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

    def moveLine(self):
        pass

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

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

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getStatus(self, **kwargs):
        if not (self.simulation):
            with self.lock:
                self.moving = self.controller.getStatus(self._axis)
        return self.moving

    def moveBy(self, step):
        self.position += step

    def moveTo(self, pos):
        if self.checkLimits(pos):
            if not (self.simulation):
                t0 = time.time()
                with self.lock:
                    self.moving = True
                    pos = (pos - self.config["offset"]) / self.config["units"]
                    self.controller.move(self._axis,pos)
            else:
                self.position = pos
        else:
            self.logger.log("Software limits exceeded for axis %s. Requested position: %.2f" % (self.axis, pos),
                            level="info")

    def getPos(self):
        if not self.simulation:
            with self.lock:
                self.position = self.controller.getPos(self._axis) * self.config["units"] + self.config["offset"]
                return self.position
        else:
            return self.position

    def home(self):
        if not self.simulation:
            self.controller.home(self._axis)

    def stop(self):
        if not self.simulation:
            self.controller.stop(self._axis)

    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs.keys():
            self.logger = kwargs["logger"]
        self.simulation = self.controller.simulation
        self.lock = self.controller.lock
        self.axis = axis
        if axis == 'x':
            self._axis = 3
        elif axis == 'y':
            self._axis = 4
        elif axis == 'z':
            self._axis = 5
        if not self.simulation:
            self.controller.setup_axis(self._axis)
        return True

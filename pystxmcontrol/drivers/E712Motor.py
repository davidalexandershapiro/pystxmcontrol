from pystxmcontrol.controller.motor import motor
import time

class E712Motor(motor):

    def __init__(self, controller = None, config = None):

        # refer to page 29 of NPoint manual for device write/read formatting info
        #self.devID = ftdi_device_id
        self.controller = controller
        self.axesList = list(enumerate(['x','y']))
        #self.simulation = False
        self.config = None
        self.axis = None
        self.trigger_axis = 1 #1 for X and 2 for Y
        self.include_return = True
        self.config = {"minValue":-5000,"maxValue":5000,"offset":0,"units":1.}

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getStatus(self, **kwargs):
        if not (self.simulation):
            with self.lock:
                self.moving = self.controller.getStatus(self._axis)
        return self.moving
    
    def setAxisParams(self, velocity = 1.0):
        """
        Set the axis parameters.
        """
        self.velocity = velocity
        if not self.simulation:
            #print(f"[E712] Setting axis {self.axis} velocity to {velocity}")
            self.controller.setVelocity(axis = self._axis, velocity = velocity)

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
            self._axis = '1'
        elif axis == 'y':
            self._axis = '2'
        self.setAxisParams()
        return True

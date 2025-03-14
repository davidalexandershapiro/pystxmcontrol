from pystxmcontrol.controller.motor import motor
import numpy as np

class derivedSlitWidth(motor):
    def __init__(self, controller = None, simulation = False):
        """
        axis1 = Left Blade
        axis2 = Right Blade
        """
        self.controller = controller
        self.simulation = simulation
        self.position = 0.5
        self.offset = 0.
        self.units = 1.
        self.axes = {}
        self.moving = False

    def getStatus(self, **kwargs):
        return self.moving

    def stop(self):
        return

    def moveBy(self, step):
        if not(self.simulation):
            self.moving = True
            self.getPos()
            self.moveTo(self.position + step)
            self.moving = False
        else:
            self.position = self.position + step

    def moveTo(self, pos):
        self.moving = True
        self.logger.log("moving Entrance Slit Width to %.4f" %(pos), level="info")
        deltaPos = pos - self.position
        self.axes["axis1"].moveBy(deltaPos / 2. * self.config["units"])
        self.axes["axis2"].moveBy(-deltaPos / 2. * self.config["units"])
        self.moving = False

    def getPos(self):
        axis1pos = self.axes["axis1"].getPos()
        axis2pos = self.axes["axis2"].getPos()
        self.position = (axis1pos - axis2pos) * self.config["units"] + self.config["offset"]
        return self.position

    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs.keys():
            self.logger = kwargs["logger"]
        self.simulation = self.config["simulation"]
        self.axis = axis
        self.position = self.getPos()


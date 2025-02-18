from pystxmcontrol.controller.motor import motor
from epics import caget, caput, cainfo
import time

class epicsMotor(motor):
    def __init__(self, controller = None, config = None):
        self.controller = controller
        self.config = config
        self.position = 0.5
        self.offset = 0.
        self.units = 1.
        self.calibratedPosition = 0.

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getStatus(self, **kwargs):
        if not (self.simulation):
            self.moving = caget(self.axis + ".MOVN")
            return self.moving
        else:
            return True

    def stop(self):
        return

    def moveBy(self, step):
        pos = self.getPos()
        if self.checkLimits(pos + step):
            if not(self.simulation):
                print("moving from ZP_Z %.4f to %.4f" %(self.position,self.position + step))
                self.moveTo(self.position + step)
                while self.getStatus():
                    time.sleep(0.1)
            else:
                self.position = self.position + step
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos+step))

    def moveTo(self, pos):
        if self.checkLimits(pos):
            if not(self.simulation):
                pos = (pos - self.config["offset"]) / self.config["units"]
                caput(self.axis + ".VAL", pos, wait = True)
                while self.getStatus():
                    time.sleep(0.1)
            else:
                self.position = pos
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def getPos(self):
        if not(self.simulation):
            self.position = caget(self.axis + ".VAL") * self.config["units"] + self.config["offset"]
            return self.position
        else:
            return self.position

    def connect(self, axis = None):
        self.simulation = self.controller.simulation
        self.axis = axis
        if not(self.simulation):
            self.position = self.getPos()

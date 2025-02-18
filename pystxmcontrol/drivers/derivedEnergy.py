from pystxmcontrol.controller.motor import motor
import time

class derivedEnergy(motor):
    def __init__(self, controller = None, simulation = False):
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
        
    def getZonePlateCalibration(self):
        ##should this use the position provided by the beamline or the theoretical value?
        ##I don't trust the beamline numbers
        A0 = self.config["A0"]
        A1 = self.config["A1"]
        energy = self.getPos()
        self.calibratedPosition = -(A0 + A1 * energy)
        return self.calibratedPosition

    def moveBy(self, energy_step):
        if not(self.simulation):
            self.moving = True
            self.getPos()
            self.moveTo(self.position + energy_step)
            self.moving = False
        else:
            self.position = self.position + step

    def moveTo(self, energy):
        if not(self.simulation):
            self.moving = True
            if abs(energy - self.position) > 50.:
                self.axes["axis1"].moveTo(energy - 1.)
                self.axes["axis1"].moveTo(energy)
            else:
                self.axes["axis1"].moveTo(energy)
            self.calibratedPosition = self.getZonePlateCalibration()
            self.axes["axis2"].moveTo(self.calibratedPosition)
            self.axes["axis2"].calibratedPosition = self.calibratedPosition
            self.moving = False
            self.getPos()
        else:
            self.position = pos

    def getPos(self):
        if not(self.simulation):
            self.position = self.axes["axis1"].getPos()
            return self.position
        else:
            return self.position

    def connect(self, axis = None):
        self.axis = axis
        self.position = self.getPos()
        self.calibratedPosition = self.getZonePlateCalibration()
        self.axes["axis2"].calibratedPosition = self.calibratedPosition

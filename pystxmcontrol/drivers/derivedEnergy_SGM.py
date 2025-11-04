from pystxmcontrol.controller.motor import motor
import numpy as np

class derivedEnergy_SGM(motor):
    def __init__(self, controller = None, simulation = False):
        """
        axis1 = Beamline Energy
        axis2 = ZonePlateZ
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
        
    def getZonePlateCalibration(self, energy = None):
        ##should this use the position provided by the beamline or the theoretical value?
        ##I don't trust the beamline numbers
        A0 = self.config["A0"]
        A1 = self.config["A1"]
        if energy == None:
            energy = self.getPos()
        self.calibratedPosition = A0 - (A1 * energy)
        return self.calibratedPosition

    def moveBy(self, energy_step):
        if not(self.simulation):
            self.moving = True
            self.getPos()
            self.moveTo(self.position + energy_step)
            self.moving = False
        else:
            self.position = self.position + step

    def moveTo(self, pos, debug = False):
        """
        pos = Energy (eV)
        """
        ##this "pos" is energy and needs to be converted to "GratingArm" units which is what the BCS motor will use
        alpha = np.arcsin(0.5 * self.grooveDensity * 0.001239852 / (pos * np.cos(0.5 * self.config["includedAngle"] * np.pi/180.)))
        gratingPos = self.monoArm * np.tan(-alpha)
        self.moving = True
        #self.logger.log("Moving beamline energy to %.4f" %pos,level = "info")
        if not(debug):
            self.axes["axis1"].moveTo(gratingPos)
        else:
            print("[moveTo] gratingPos: ", gratingPos)
        # self.logger.log("Moving zone plate to %.4f" %self.calibratedPosition,level = "info")
        self.calibratedPosition = self.getZonePlateCalibration()
        # self.logger.log("moving zone plate to %.4f" %self.calibratedPosition, level="info")
        if not(debug):
            self.axes["axis2"].moveTo(self.calibratedPosition)
        else:
            print("[moveTo] Calibrated zone plate position: %.4f" %self.getZonePlateCalibration(energy = pos))
        self.moving = False

    def getPos(self, debug = False):
        #This gets the grating arm motor position from the XPS controller
        gratingPos = self.axes["axis1"].getPos()
        #This calculates the angle of the grating assuming the correct value for the monoArm
        alpha = np.arctan(gratingPos/self.monoArm)
        #This converts angle to energy assuming the correct parameters: grooveDensity, includedAngle
        # Formula looks correct, except for the lack of offset
        self.position = 0.001239852*self.grooveDensity*0.5/(np.cos(0.5 * self.config["includedAngle"] * np.pi/180.)*np.sin(-alpha))
        if debug:
            print("[getPos] gratingPos: %.4f" %gratingPos)
            print("[getPos] energy: %.4f" %self.position)
            print("[getPos] zoneplate_z calibrated position: %.4f" %self.axes["axis2"].getPos())
        return self.position

    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs.keys():
            self.logger = kwargs["logger"]
        self.simulation = self.config["simulation"]
        self.monoArm = self.config["monoArm"]
        self.grooveDensity = self.config["grooveDensity"]
        self.axis = axis
        self.position = self.getPos()
        # self.calibratedPosition = self.getZonePlateCalibration()
        # self.axes["axis2"].calibratedPosition = self.calibratedPosition


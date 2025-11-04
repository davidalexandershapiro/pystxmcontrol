from pystxmcontrol.controller.motor import motor
import time

class xpsMotor(motor):
    def __init__(self, controller = None, config = None):
        self.controller = controller
        self.simulation = False
        self.config = config
        self.axis = None
        self.position = 500.
        self.moving = False
        self.config = {"units":1, "offset":0, "minValue":-40,"maxValue":40}
        self._controller_position = 0. #used for simulation mode

    def getStatus(self, **kwargs):
        return self.moving

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getAxisParams(self):
        dummy,self.velocity, self.acceleration, self.minimumJerkTime, self.maximumJerkTime = \
            self.controller.getParameters(self.controller.controlSocket, self.axis)

    def setAxisParams(self, velocity):
        if not self.simulation:
            self.controller.setParameters(self.controller.controlSocket, self.axis, velocity * 1000, \
                                        self.acceleration, self.minimumJerkTime, self.maximumJerkTime)

    def moveBy(self, step):
        pos = self.getPos()
        if self.checkLimits(pos + step):
            if not(self.simulation):
                step = step / self.config["units"]
                self.err, retStr = self.controller.moveBy(self.controller.controlSocket, self.axis, step)
            else:
                self.position = self.position + step
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def moveTo(self, pos):
        #print("Moving XPS motor to: %.2f" %pos, flush=True)
        if self.checkLimits(pos):
            if not(self.simulation):
                pos = (pos - self.config["offset"]) / self.config["units"]
                self.moving = True
                self.err, retStr = self.controller.moveTo(self.controller.controlSocket, self.axis, pos)
                self.moving = False
            else:
                self.controller.moving = True
                self._controller_position = (pos - self.config["offset"]) / self.config["units"]
                self.position = self.getPos()
                self.controller.moving = False
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def getPos(self):
        if not(self.simulation):
            self.err,self.position = self.controller.getPosition(self.controller.monitorSocket, self.group)
            #print(self.config["units"],self.config["offset"],self.position)
            return self.position * self.config["units"] + self.config["offset"]
        else:
            return self._controller_position * self.config["units"] + self.config["offset"]
            
    def stop(self):
        self.err, self.returnedStr = self.controller.abortMove(self.controller.monitorSocket, self.group)
        return

    def connect(self, axis = None):
        self.axis = axis
        self.group = self.axis.split('.')[0]
        self.simulation = self.controller.simulation
        if not(self.simulation):
            self.position = self.getPos()
            self.getAxisParams()


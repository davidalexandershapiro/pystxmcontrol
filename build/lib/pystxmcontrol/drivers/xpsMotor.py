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

    def getStatus(self, **kwargs):
        return self.moving

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def moveBy(self, step):
        pos = self.getPos()
        if self.checkLimits(pos + step):
            if not(self.simulation):
                step = step / self.config["units"]
                self.err, retStr = self.controller.GroupMoveRelative(self.controller.controlSocket, self.axis, [step])
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
                self.err, retStr = self.controller.GroupMoveAbsolute(self.controller.controlSocket, self.axis, [pos])
                self.moving = False
            else:
                self.controller.moving = True
                time.sleep(1)
                self.controller.moving = False
                self.position = pos
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def getPos(self):
        if not(self.simulation):
            self.err,self.position = self.controller.GroupPositionCurrentGet(self.controller.monitorSocket, self.group, 1)
            return self.position * self.config["units"] + self.config["offset"]
        else:
            return self.position
            
    def stop(self):
        self.err, self.returnedStr = self.controller.GroupMoveAbort(self.controller.monitorSocket, self.group)
        return

    def connect(self, axis = None):
        self.axis = axis
        self.group = self.axis.split('.')[0]
        self.simulation = self.controller.simulation
        if not(self.simulation):
            self.position = self.getPos()


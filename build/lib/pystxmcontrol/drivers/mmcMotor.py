from pystxmcontrol.controller.motor import motor

class mmcMotor(motor):
    def __init__(self):
        self.position = 500.

    def getStatus(self, **kwargs):
        pass

    def moveBy(self, step):
        self.position += step

    def moveTo(self, pos):
        self.position = pos

    def getPos(self):
        return self.position

    def connect(self, **kwargs):
        return True

from pystxmcontrol.controller.motor import motor
import time
class mmcMotor(motor):
    def __init__(self, controller = None, config = None):
        self.controller = controller
        self.config = config
        self.position = 0.5
        self.offset = 0.
        self.units = 1.
        self.calibratedPosition = 0.
        self.moving = False
        self.idleStrings = ['8','136']
        self.lt = '\r'

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getStatus(self, **kwargs):
        if not(self.simulation):
            with self.lock:
                self.controller.serialPort.write((str(self._axis) + "STA?\r").encode())
                status = self.controller.serialPort.readline().decode().strip()
                if status[1::] not in self.idleStrings: ##this number seems to have changed!!
                    self.moving = True
                else:
                    self.moving = False
        return self.moving

    def moveBy(self, step):
        self.position += step

    def moveTo(self, pos):
        if self.checkLimits(pos):
            if not(self.simulation):
                t0 = time.time()
                with self.lock:
                    self.moving = True
                    pos = (pos - self.config["offset"]) / self.config["units"]
                    self.controller.serialPort.write((str(self._axis) + "MVA" + str(pos) + "\r").encode())
                while True:
                    self.getStatus()
                    if self.moving:
                        time.sleep(0.02)
                    else:
                        #print("OSA move took %.4f ms" %((time.time()-t0)*1000.))
                        return
            else:
                self.position = pos
        else:
            self.logger.log("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos),level = "info")

    def getPos(self):
        if not self.simulation:
            with self.lock:
                self.controller.serialPort.write((str(self._axis) + "POS?" + self.lt).encode())
                pos = float(self.controller.serialPort.readline().decode().split(',')[1].rstrip())
                self.position = pos * self.config["units"] + self.config["offset"]
                return self.position
        else:
            return self.position

    def setServo(self,servo = True):
        if servo:
            servoStr = '3'
        else:
            servoStr = '0'
        writeStr = str(self._axis) + "FBK" + servoStr + self.lt
        if not self.simulation:
            self.controller.serialPort.write(writeStr.encode())

    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs.keys():
            self.logger = kwargs["logger"]
        self.simulation = self.controller.simulation
        self.lock = self.controller.lock
        self.axis = axis
        if axis == 'x':
            self._axis = 1
        elif axis == 'y':
            self._axis = 2
        elif axis == 'z':
            self._axis = 3
        self.setServo(True)
        return True

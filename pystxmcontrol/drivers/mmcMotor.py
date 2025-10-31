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
        self._lt = '\r'
        self._timeout = 1

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

    def setAxisParams(self,velocity):
        self.velocity = round(velocity,3)
        if not self.simulation:
            with self.lock:
                self.controller.serialPort.write((str(self._axis) + "VEL" + str(self.velocity) + self._lt).encode())

    def get_velocity(self):
        if not self.simulation:
            with self.lock:
                self.controller.serialPort.write((str(self._axis) + "VEL?" + self._lt).encode())
                self.velocity = float(self.controller.serialPort.readline().decode().split(',')[1].rstrip())
        return self.velocity

    def moveTo(self, pos):
        pos = int(pos)
        if self.checkLimits(pos):
            if not(self.simulation):
                t0 = time.time()
                with self.lock:
                    self.moving = True
                    pos = round((pos - self.config["offset"]) / self.config["units"],3) #MMC needs fewer sig digits
                    self.controller.serialPort.write((str(self._axis) + "MVA" + str(pos) + "\r").encode())
                while True:
                    self.getStatus()
                    dt = time.time() - t0
                    if self.moving and dt < self._timeout:
                        time.sleep(0.005)
                    else:
                        self.moving = False
                        return
            else:
                self.position = pos
        else:
            self.logger.log(f"[mmcMotor] Software limits exceeded for axis {self.axis}. Requested position: {pos}",level = "info")

    def getPos(self):
        if not self.simulation:
            with self.lock:
                self.controller.serialPort.write((str(self._axis) + "POS?" + self._lt).encode())
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
        if not self.simulation:
            writeStr = str(self._axis) + "FBK" + servoStr + self._lt
            self.controller.serialPort.write(writeStr.encode())

    def home(self):
        if not self.simulation:
            writeStr = str(self._axis) + "HOM" + self._lt
            self.controller.serialPort.write(writeStr.encode())

    def configure_home(self, direction = 0):
        """
        Direction: 0 or 1
        """
        if not self.simulation:
            writeStr = str(self._axis) + "HCG" + str(direction) + self._lt
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

from pystxmcontrol.controller.motor import motor
import time

class bcsMotor(motor):
    def __init__(self, controller = None, config = None):
        self.controller = controller
        self.config = config
        self.axis = None
        self.position = 600.0
        self.offset = 0.
        self.units = 1.
        self.moving = False

    def connect(self, axis = 'x'):
        self.axis = axis
        if not(self.controller.simulation):
            self.lock = self.controller.lock
            ##The controller connects with controller.initialize()
            ##maybe put something to check connection???

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getBCSCommandList(self):
        # BCS command delimiter is '\r\n', required to terminate a command
        message = 'listcommands' + '\r\n'
        self.controller.monitorSocket.sendall(message.encode())
        self.bcs_commands = self.controller.monitorSocket.recv(4096).decode().split('\r\n')
        retval=False
        if self.bcs_commands.__len__()>0:
            retval=True

        return retval

    def getBCSStatus(self):
        with self.lock:
            message = 'getmotorstat %s \r\n' %self.axis
            self.controller.monitorSocket.sendall(message.encode())
            msg = self.controller.monitorSocket.recv(4096).decode()
        return msg

    def moveTo(self, pos):
        if self.checkLimits(pos):
            pos = (pos - self.config["offset"]) / self.config["units"]
            if (self.axis is not None) and not(self.controller.simulation):
                with self.lock:
                    message = ('moveto %s %f\r\n') % (self.axis, pos)
                    self.moving = True
                    self.controller.controlSocket.sendall(message.encode())
                    ##need a loop here to check move status???
                    response = self.controller.controlSocket.recv(4096).decode()
                retval = False
                if response.strip() == 'OK!0':
                    self.position = self.getPos()
                    retval = True
                status = self.getBCSStatus()
                while status.split('.')[0] != "Move finished":
                    time.sleep(0.1)
                    status = self.getBCSStatus()
                self.moving = False
                return retval
            elif self.controller.simulation:
                self.position = pos
                self.moving = True
                time.sleep(1)
                self.moving = False
            else:
                return -1
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))

    def getPos(self):

        if (self.axis is not None) and not(self.controller.simulation):
            with self.lock:
                message = ('getpos %s\r\n') % (self.axis)
                self.controller.monitorSocket.sendall(message.encode())
                response = self.controller.monitorSocket.recv(4096).decode()
            iPos = 0
            data=response.strip().replace('!0','')
            if data.__len__() >0 :
                try:
                    iPos = float(data)
                except:
                    iPos = 0.0
            iPos = iPos * self.config["units"] + self.config["offset"]
            return iPos
        elif self.controller.simulation:
            return self.position
        else:
            return -1

    def getVar(self, varType):
        if (self.axis is not None) and not(self.controller.simulation):
            with self.lock:
                if varType == "Double":
                    message = ('getdoublevar %s\r\n') % (self.axis)
                elif varType == "Int":
                    message = ('getintvar %s\r\n') % (self.axis)
                self.controller.controlSocket.sendall(message.encode())
                ##need a loop here to check move status???
                response = self.controller.controlSocket.recv(4096).decode()
            iPos = 0
            data = response.strip().replace('!0', '')
            if data.__len__() > 0:
                try:
                    iPos = float(data)
                except:
                    iPos = 0.0
            return iPos
        elif self.controller.simulation:
            return self.position
        else:
            return -1

    def setVar(self, value, varType):
        print("Setting variable %s to value: %.2f" %(self.axis,value))
        if (self.axis is not None) and not(self.controller.simulation):
            with self.lock:
                if varType == "Double":
                    message = ('SetDoubleVar(%s,%f)\r\n') % (self.axis, value)
                elif varType == "Int":
                    message = ('SetIntVar(%s,%f)\r\n') % (self.axis, value)
                self.controller.controlSocket.sendall(message.encode())
                ##need a loop here to check move status???
                response = self.controller.controlSocket.recv(4096).decode()
            retval = False
            if response.strip() == 'OK!0':
                self.position = self.getVar(varType)
                retval = True
            return retval
        elif self.controller.simulation:
            self.position = value
        else:
            return -1

    def getStatus(self, **kwargs):
        return self.moving

    def moveBy(self, step, **kwargs):
        pass

    def stop(self):
        return

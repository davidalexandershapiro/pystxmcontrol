import socket, time
from pystxmcontrol.controller.hardwareController import hardwareController

class xpsController(hardwareController):
    def __init__(self, address = '192.168.168.253', port = 5001, simulation = False):
        self.address = address
        self.port = port
        self.simulation = simulation
        self.stopped = False
        self.moving = False
        self._nSockets = 0
        self._sockets = []

    def initialize(self, simulation = False):
        self.simulation = simulation
        if not(self.simulation):
            print("Connecting to XPS controller...", self.address, self.port)
            self.controlSocket = self.connect(self.address, self.port, 1)
            self.monitorSocket = self.connect(self.address, self.port, 1)

    def __sendAndReceive(self, socketId, command):
        try:
            self._sockets[socketId].send(command.encode())
            response = self._sockets[socketId].recv(1024).decode()
            while (response.find(',EndOfAPI') == -1):
                response += self._sockets[socketId].recv(1024)
        except socket.timeout:
            return [-2, '']
        except socket.error as errString:
            print( 'Socket error : ' + errString)
            return [-2, '']
        for i in range(len(response)):
            if (response[i] == ','):
                return [int(response[0:i]), response[i+1:-9]]

    def connect(self, IP, port, timeOut):
        self._nSockets = len(self._sockets)
        socketId = self._nSockets
        try:
            self._sockets.append(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            self._sockets[socketId].connect((IP, port))
            self._sockets[socketId].settimeout(timeOut)
            self._sockets[socketId].setblocking(1)
        except socket.error:
            print("Failed to connect to XPS controller on: %s:%s" %(self.address, self.port))
            return -1
        return socketId

    def abortMove(self, socketId, motor):
        command = 'GroupMoveAbort(' + motor + ')'
        [err, retString] = self.__sendAndReceive(socketId, command)
        return [err, retString]

    def moveTo(self, socketId, motor, target):
        err,currentPos = self.getPosition(socketId, motor)
        moveDelta = abs(target - currentPos)
        command = 'GroupMoveAbsolute(' + motor + ',' + str(target) + ')'
        self.moving = True
        [err, retString] = self.__sendAndReceive(socketId, command)
        t0 = time.time()
        while self.moving:
            err,currentPos = self.getPosition(socketId, motor)
            positionErr = target - currentPos
            if abs(positionErr) > 2.0: #0.05 * moveDelta:
                if not(self.stopped):
                    if (time.time() - t0) > 1.0:
                        print("XPS move timeout. Aborting...")
                        self.moving = False
                        return self.abortMove(socketId, motor)
                    else:
                        time.sleep(0.1)
                else:
                    self.moving = False
                    self.stopped = False
                    return [err, retString]
            else:
                self.moving = False
                return [err, retString]

    def moveBy(self, socketId, motor, displacement):
        command = 'GroupMoveRelative(' + motor + ',' + str(displacement)+')'
        [err, retString] = self.__sendAndReceive(socketId, command)
        return [err, retString]

    def getPosition(self, socketId, motor):
        command = 'GroupPositionCurrentGet(' + motor + ', double *)'
        [err, retString] = self.__sendAndReceive(socketId, command)
        if (err != 0):
            print(err,retString)
            return [err, float(retString)]
        return [err, float(retString)]





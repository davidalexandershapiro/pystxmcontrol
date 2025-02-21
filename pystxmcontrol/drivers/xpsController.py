import socket, time
from pystxmcontrol.controller.hardwareController import hardwareController

class xpsController(hardwareController):
    def __init__(self, address = '192.168.168.253', port = 5001, simulation = False):
        self.address = address
        self.port = port
        self.simulation = simulation
        self.stopped = False
        self.moving = False
        xpsController._nSockets = 0
        xpsController._sockets = []

    def initialize(self, simulation = False):
        self.simulation = simulation
        if not(self.simulation):
            print("Connecting to XPS socket...", self.address, self.port)
            self.controlSocket = self.connect(self.address, self.port, 1)
            self.monitorSocket = self.connect(self.address, self.port, 1)

    def __sendAndReceive(self, socketId, command):
        try:
            xpsController._sockets[socketId].send(command.encode())
            response = xpsController._sockets[socketId].recv(1024).decode()
            while (response.find(',EndOfAPI') == -1):
                response += xpsController._sockets[socketId].recv(1024)
        except socket.timeout:
            return [-2, '']
        except socket.error as errString:
            print( 'Socket error : ' + errString)
            return [-2, '']
        for i in range(len(response)):
            if (response[i] == ','):
                return [int(response[0:i]), response[i+1:-9]]

    def connect(self, IP, port, timeOut):
        xpsController._nSockets = len(xpsController._sockets)
        socketId = xpsController._nSockets
        try:
            xpsController._sockets.append(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            xpsController._sockets[socketId].connect((IP, port))
            xpsController._sockets[socketId].settimeout(timeOut)
            xpsController._sockets[socketId].setblocking(1)
        except socket.error:
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
            if abs(positionErr) > 0.2: #0.05 * moveDelta:
                if not(self.stopped):
                    if (time.time() - t0) > 30.0:
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
            return [err, retString]
        return [err, float(retString)]





# -*- coding: utf-8 -*-
from pylibftdi import Device, Driver
from pystxmcontrol.controller.hardwareController import hardwareController
import socket
from threading import Lock

class bcsController(hardwareController):

    """
    Ethernet controllers need to have two sockets.  The higher level code is not thread safe for
    single sockets.  Testing this but the idea is to have a control socket that sends move commands
    and a monitor socket which requests information.  getPos() will run in a different thread than
    moveTo()
    """

    def __init__(self, address = 'localhost', port = 50000, simulation = False):
        self.address = address
        self.port = port
        self.controlSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.monitorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.moving = False
        self.lock = Lock()

    def initialize(self, simulation = False):
        self.simulation = simulation
        print("simulation on bcsController: ", simulation)
        if not(self.simulation):
            self.controlSocket.connect((self.address, self.port))
            self.monitorSocket.connect((self.address, self.port))
            print("Connected to BCS Server: %s:%s" % (self.address, self.port))

    def disconnect(self):
        self.socket.close()


# -*- coding: utf-8 -*-
from pylibftdi import Device, Driver
from pystxmcontrol.controller.hardwareController import hardwareController
import serial
from threading import Lock

class mmcController(hardwareController):

    def __init__(self, address = '/dev/ttyUSB0', port = 5000, simulation = False):

        # refer to page 29 of NPoint manual for device write/read formatting info
        self.devID = address
        self.isInitialized = False
        self.address = address
        self.simulation = simulation
        self.lock = Lock()

    def initialize(self, simulation = False):
        self.simulation = simulation
        if not(self.simulation):
            self.serialPort = serial.Serial(port=self.address, baudrate=38400,
                bytesize=8, timeout=1, stopbits=serial.STOPBITS_ONE)

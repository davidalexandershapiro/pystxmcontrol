# -*- coding: utf-8 -*-
from pylibftdi import Device, Driver
from pystxmcontrol.controller.hardwareController import hardwareController

class mmcController(hardwareController):

    def __init__(self, address = 'localhost', port = 5000, simulation = False):

        # refer to page 29 of NPoint manual for device write/read formatting info
        self.devID = address
        self.isInitialized = False

    def initialize(self, simulation = False):
        self.simulation = simulation

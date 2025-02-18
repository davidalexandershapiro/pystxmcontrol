from pystxmcontrol.controller.hardwareController import hardwareController

class epicsController(hardwareController):

    # Initialization Function
    def __init__(self, address = None, port = None, simulation = False):
        self.address = address
        self.port = port
        self.simulation = simulation

    def initialize(self, simulation = False):
        self.simulation = simulation


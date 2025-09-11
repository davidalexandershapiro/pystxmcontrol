from pystxmcontrol.controller.hardwareController import hardwareController

class epicsController(hardwareController):

    # Initialization Function
    def __init__(self, address = None, port = None, simulation = False):
        self.address = address
        self.port = port
        self.simulation = simulation
        self.position = 0. #used for simulation mode

    def initialize(self, simulation = False):
        self.simulation = simulation


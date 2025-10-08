from pystxmcontrol.controller.hardwareController import hardwareController
import serial
from threading import Lock
from pipython import GCSDevice, pitools
import logging
logging.getLogger('pipython').setLevel(logging.WARNING)

__signature__ = 0x986c0f898592ce476e1c88820b09bf94
CONTROLLERNAME = 'E-712'  # 'C-884' will also work
STAGES = None
REFMODES = ['FRF','FRF',] #for 2 axes

class E712Controller(hardwareController):

    def __init__(self, address = '192.168.1.201', port = 5000, simulation = False):

        # refer to page 29 of NPoint manual for device write/read formatting info
        self.devID = address
        self.isInitialized = False
        self.address = address
        self.simulation = simulation
        self.lock = Lock()

    def getPos(self, axis):
        self.position = self.pidevice.qPOS(axis)[axis]  # query single axis
        return self.position

    def getStatus(self, axis):
        return False
    
    def setVelocity(self, axis, velocity):
        self.pidevice.VEL(axis,velocity)

    def home(self, axis):
        pass

    def move(self, axis, pos):
        print('move axis {} to {:.2f}'.format(axis, pos))
        self.pidevice.MOV(axis, pos)
        pitools.waitontarget(self.pidevice, axes=axis)

    def initialize(self, simulation = False):
        self.simulation = simulation
        if not(self.simulation):
            self.pidevice = GCSDevice(CONTROLLERNAME)
            self.pidevice.ConnectTCPIP(ipaddress=self.address)
            print('connected: {}'.format(self.pidevice.qIDN().strip()))
            if self.pidevice.HasqVER():
                print('version info:\n{}'.format(self.pidevice.qVER().strip()))
            pitools.startup(self.pidevice, stages=STAGES, refmodes=REFMODES)

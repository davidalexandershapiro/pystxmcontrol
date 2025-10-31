from pystxmcontrol.controller.hardwareController import hardwareController
import serial
from threading import Lock
from pipython import GCSDevice, pitools
import logging
logging.getLogger('pipython').setLevel(logging.CRITICAL)
logging.getLogger('PIlogger').setLevel(logging.CRITICAL)

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
        #controller velocity units are microns/second, so scale from mm/s
        self.pidevice.VEL(axis,velocity*1000)

    def getVelocity(self, axis):
        return self.pidevice.qVEL(axis)[axis]

    def home(self, axis):
        pass

    def configureTrigger(self, axis, trigger_mode=2, trigger_step=None):
        """
        Configure trigger output for the specified axis.

        Parameters:
        -----------
        axis : str
            Axis identifier ('1' or '2')
        trigger_mode : int
            Trigger mode (default 2 for position distance)
            1 = on target
            2 = position distance
            3 = in motion
        trigger_step : float
            Distance between triggers in microns (for mode 2)
        """
        # Enable trigger output
        self.pidevice.TRO(axis, True)

        # Set trigger mode (CTO parameter 0x03000200)
        self.pidevice.CTO(axis, 1, trigger_mode)

        # Set trigger step if provided (for position distance mode)
        if trigger_step is not None and trigger_mode == 2:
            self.pidevice.CTO(axis, 2, trigger_step)

    def disableTrigger(self, axis):
        """Disable trigger output for the specified axis."""
        self.pidevice.TRO(axis, False)

    def move(self, axis, pos):
        print(f"Moving axis {axis} to {pos} with velocity {self.getVelocity(axis)}")
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
            print('connected: {}'.format(self.pidevice.qPUN()))

import time
from pystxmcontrol.controller.motor import motor
from pystxmcontrol.drivers.U2356A import U2356A
from numpy.random import poisson

class keysightA33500B(motor):
    def __init__(self, visa_address = "USB::0x0957::0x2807::INSTR", simulation = False):
        self.visa_address = visa_address
        self.simulation = simulation

    def getStatus(self):
        pass
        
    def moveBy(self):
        pass
        
    def moveTo(self):
        pass
        
    def getPos(self):
        pass
        
    def stop(self):
        pass
        
    def connect(self, axis = None):
        pass

    def config(self):
        pass




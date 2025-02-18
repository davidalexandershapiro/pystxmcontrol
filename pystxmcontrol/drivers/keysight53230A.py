import time
from pystxmcontrol.controller.daq import daq
from pystxmcontrol.drivers.keysightCounter import counter
from pystxmcontrol.drivers.shutter import shutter
from numpy.random import poisson

class keysight53230A(daq):
    def __init__(self, visa_address = "USB::0x0957::0x1907::INSTR", simulation = False):
        self.visa_address = visa_address
        self.simulation = simulation
        self.gate = shutter()
        self.gate.connect(simulation = self.simulation)
        self.gate.setStatus(softGATE = 0)
        if not(self.simulation):
            self.counter = counter()
            self.idle_ms = 1
            self.ctrNum = 0

    def start(self):
        if not (self.simulation):
            self.counter.connect(visa_address=self.visa_address)

    def stop(self):
        if not (self.simulation):
            self.counter.disconnect()
    def set_dwell(self, dwell):
        self.dwell = dwell

    def config(self, dwell, dwell2 = 0, count=1, samples=1, trigger='BUS', output = 'OFF'):
        self.dwell = dwell
        self.count = count
        self.trigger = trigger
        self.samples = samples
        self.output = output
        if self.simulation:
            pass
        else:
            self.counter.config(self.dwell, count=count, samples=samples, trigger=trigger, output=output)
            self.setGateDwell(0,0)

    def initLine(self):
        if self.simulation:
            pass
        else:
            self.counter.initLine()

    def autoGateOpen(self, shutter = 1):
        self.gate.setStatus(softGATE = 1, shutterMASK = shutter)

    def autoGateClosed(self):
        self.gate.setStatus(softGATE = 0)
            
    def setGateDwell(self, dwell1, dwell2 = 0):
        self.gate.dwell1 = dwell1
        self.gate.dwell2 = dwell2
        self.gate.setStatus()

    def getLine(self):
        if self.simulation:
            data = poisson(1e7 * self.dwell / 1000., self.count * self.samples)
            time.sleep(self.dwell / 1000.*self.count*self.samples)
            return data
        else:
            data = self.counter.getLine()
            return data

    def getPoint(self):
        if self.simulation:
            time.sleep(self.dwell / 1000.)
            data = poisson(1e7 * self.dwell / 1000.)
            return data
        else:
            data = self.counter.getPoint()
            return data

    def setGate(self, gate):
        """
        Gate is boolean (up/down)
        :param gate:
        :return:
        """
        self.gate = gate

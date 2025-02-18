import time
from pystxmcontrol.controller.daq import daq
from pystxmcontrol.drivers.U2356A import U2356A
from numpy.random import poisson

class keysightU2356A(daq):
    def __init__(self, visa_address = "USB::0x0957::0x1418::INSTR", simulation = False):
        self.visa_address = visa_address
        self.simulation = simulation

    def start(self):
        pass

    def stop(self):
        pass

    def set_dwell(self, dwell):
        self.dwell = dwell

    def config(self, dwell, dwell2 = 0, count=1, samples=1, trigger='BUS', output = 'OFF'):
        self.dwell = dwell
        self.count = count
        self.trigger = trigger
        self.samples = samples
        self.output = output

    def initLine(self):
        pass

    def getLine(self):
        if self.simulation:
            data = poisson(1e7 * self.dwell / 1000., self.count * self.samples)
            #time.sleep(self.count * self.samples * self.dwell / 1000.)
            return data
        else:
            pass

    def getPoint(self):
        if self.simulation:
            time.sleep(self.dwell / 1000.)
            data = poisson(1e7 * self.dwell / 1000.)
            return data
        else:
            pass



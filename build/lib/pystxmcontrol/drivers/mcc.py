import time
from pystxmcontrol.controller.daq import daq
from pystxmcontrol.drivers.mccCounter import mccCtr
from numpy.random import poisson
import numpy as np

class mcc(daq):
    def __init__(self, simulation = False):
        self.simulation = simulation
        if not(self.simulation):
            self.counter = mccCtr(0)
            self.idle_ms = 1
            self.ctrNum = 0

    def start(self):
        if not(self.simulation):
            self.counter.connect()
            #self.counter.timer_start()

    def stop(self):
        if not(self.simulation):
            #self.counter.timer_stop()
            self.counter.dio_stop()
            self.counter.disconnect()

    def getLine(self, scan):
        if simulation:
            return poisson(1e7 * scan["dwell"] / 1000., scan["xPoints"])

    def getPoint(self, dwell):
        if self.simulation:
            time.sleep(dwell / 1000.)
            return poisson(1e7 * dwell / 1000.)
        else:
            self.counter.timer_start()
            self.counter.convert_msec_to_ticks(dwell, self.idle_ms, 4)
            self.counter.counter_start()
            dio_output_byte = 1
            self.counter.dio_output(dio_output_byte, 0)
            self.counter.wait_till_scan_done()
            counts = self.counter.read_counts(self.ctrNum)
            dio_output_byte = 0
            self.counter.dio_output(dio_output_byte, 0)
            self.counter.counter_stop()
            self.counter.timer_stop()
            return np.array(counts).mean()

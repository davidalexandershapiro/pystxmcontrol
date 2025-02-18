from abc import ABC, abstractmethod

class daq(ABC):

    def __init__(self, simulation = False):
        super.__init__()
        self.simulation = simulation

    @abstractmethod
    def getPoint(self, scan, **kwargs):
        return True

    @abstractmethod
    def getLine(self, step, **kwargs):
        return True

    @abstractmethod
    def config(self, dwell, points, mode):
        return True

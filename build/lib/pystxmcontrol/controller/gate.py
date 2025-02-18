from abc import ABC, abstractmethod

class gate(ABC):

    def __init__(self, simulation = False):
        super.__init__()
        self.simulation = simulation
        self.status = False

    @abstractmethod
    def setStatus(self, **kwargs):
        return self.status

    @abstractmethod
    def getStatus(self, **kwargs):
        return self.status

    @abstractmethod
    def connect(self, **kwargs):
        return self.status
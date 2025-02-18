from abc import ABC, abstractmethod

class motor(ABC):

    def __init__(self, simulation = False):
        super.__init__()
        self.simulation = simulation

    @abstractmethod
    def moveTo(self, position, **kwargs):
        return self.getPos()

    @abstractmethod
    def moveBy(self, step, **kwargs):
        return self.getPos()

    @abstractmethod
    def getPos(self, **kwargs):
        return 1

    @abstractmethod
    def getStatus(self, **kwargs):
        return True

    @abstractmethod
    def connect(self, **kwargs):
        return True

from abc import ABC, abstractmethod

class hardwareController(ABC):

    def __init__(self, simulation = False):
        super.__init__()
        self.simulation = simulation

    @abstractmethod
    def initialize(self, **kwargs):
        pass

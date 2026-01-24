from abc import ABC, abstractmethod


class SoftwareLimitError(Exception):
    """Raised when a motor movement would exceed software limits"""
    def __init__(self, axis, position, limit, limit_type="upper"):
        self.position = position
        self.limit = limit
        self.limit_type = limit_type
        message = f"Position {position} exceeds {limit_type} limit of {limit} for axis {axis}"
        super().__init__(message)


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

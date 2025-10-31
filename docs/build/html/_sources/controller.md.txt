# Setting up a controller device

A controller device is the lowest level object in pystxmcontrol which talks directly to a physical hardware device.
There are only three requirements for a new controller class:
- It must inheret the hardwareController class
- It must be instantiated with a boolean argument "simulation"
- It must have at least one method called initialize

The inheritance of the hardwareController class enforces the last two requirements.  Below is the definition of the
abstract hardwareController class which enforces the interface
```
from abc import ABC, abstractmethod

class hardwareController(ABC):

    def __init__(self, simulation = False):
        super.__init__()
        self.simulation = simulation

    @abstractmethod
    def initialize(self, **kwargs):
        pass
```
Additional methods for executing the functionality of the actual hardware device must be separately developed. 
 
The particular needs of a given piece of hardware might not require any functionality at this controller level.  pystxmcontrol's epicsController is an example of this since the calling of epics process variables can be done within the motor class.  Regardless, the structure of the motor class and higher level software controller requires that each motor have an associated controller.  As an example, the epicsController code is shown below.  This code has no functionality beyond obeying the interface which is required of all devices.
```
from pystxmcontrol.controller.hardwareController import hardwareController

class epicsController(hardwareController):

    # Initialization Function
    def __init__(self, address = None, port = None, simulation = False):
        self.address = address
        self.port = port
        self.simulation = simulation

    def initialize(self, simulation = False):
        self.simulation = simulation
```

Here is a more complex example which shows the initialize function opening socket communication to a device.  In this case the device is a TCP network interface to another control program.  It's important to notice that the __init__ method instantiates a Lock() object.  Every motor object which uses this controller will have access to that lock object and should use it to protect its methods from race conditions among the various threads which may call the motors methods.  This is explained in more detail in the section on implementing motors.

```
from pylibftdi import Device, Driver
from pystxmcontrol.controller.hardwareController import hardwareController
import socket
from threading import Lock

class bcsController(hardwareController):

    def __init__(self, address = 'localhost', port = 50000, simulation = False):
        self.address = address
        self.port = port
        self.controlSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.monitorSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.moving = False
        self.lock = Lock()

    def initialize(self, simulation = False):
        self.simulation = simulation
        if not(self.simulation):
            self.controlSocket.connect((self.address, self.port))
            self.monitorSocket.connect((self.address, self.port))
```

# Using a device controller
A controller object can be (is) used to communicate directly with a piece of hardware but in pystxmcontrol they are used primarily within motor objects which are the interface to the higher level software functionality.  Motor objects are described separately but the controllers are handed as inputs to motor objects as shown in this example
```
c = epicsController(simulation = True)
c.initialize()
m = epicsMotor(controller = c)
m.connect(axis = "cosmic:ZP_Z")
```

A single controller can be used for multiple motors so the motor connect() method specifies which axis it refers to.

# setting up a motor device

A motor object is an enforced interface between the high level logic of pystxmcontrol and the hardware device functionality.  Any device which may change value on command, like a motor position or an amplifier voltage, can be designed as a motor object.  A driver designed with the abstract methods shown in the definition below can be automatically included in the graphical interface and scan routines after inclusion in the global motor config file.

```
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
```
Here is an implementation which shows the connect and getStatus methods.  In this particular case, the controller has established the socket communication and the motor object is using it to check the status of it's axis.  This example also demonstrates how to use the controller.lock object to render the socket communication thread safe.
```
class bcsMotor(motor):
    def __init__(self, controller = None):
        self.controller = controller
        self.config = {}
        self.axis = None
        self.position = 600.0
        self.offset = 0.
        self.units = 1.
        self.moving = False

    def connect(self, axis = 'x'):
        self.axis = axis
        if not(self.controller.simulation):
            self.lock = self.controller.lock

    def getStatus(self):
        with self.lock:
            message = 'getmotorstat %s \r\n' %self.axis
            self.controller.monitorSocket.sendall(message.encode())
            msg = self.controller.monitorSocket.recv(4096).decode()
        return msg
```

This example shows the motor objects moveTo method and how it can both utilize the underlying controller to actually move a motor or produce feedback in the simulation mode.  The controllers function need not be named "moveTo" and the motor object could in fact a execute a much more complex routine as needed.
```
def moveTo(self, pos = None):
    if not(self.simulation):
        self.controller.moveTo(axis = self._axis, pos = pos)
        time.sleep(self.waitTime) #piezo settling time of 10 ms
    else:
        self.position = pos
        time.sleep(self.waitTime / 1000.)
```

# using a motor device

Each motor requires a controller (this may even be a controller which has no functionality) and each controller can have several associated motors.  Basic usage is shown below.  Using motors in this way, at the lowest level, is risky because without the higher level integration described below, motors do not have any configuration which will describe things like software limits and encoder units that are used by the software controller and GUI.

```
c = epicsController(simulation = True)
c.initialize()
m = epicsMotor(controller = c)
m.connect(axis = "cosmic:ZP_Z")
print(m.config)
m.getPos()
m.moveTo(0)
```

# configuring a motor device

Motors are configured for use by the software controller and GUI using the motorConfig.json file.  The software controller (which is initialized by the server)
reads all config files and provides this information to the controller and motor objects described therein.  During installation, these files are saved in the directory returned
by the python method sys.prefix().  When using a conda environment the directory containing the config files is, for example,
miniconda3/envs/pystxmcontrol/pystxmcontrol_cfg.  The contents of these JSON files are read into python dictionaries by the
software controller when initialized.

The top level item is the motor name that will be available in the GUI.  Each motor entry must have at least the following entries:
- index (int): starting at 0 
- type (str): "primary" or "derived"
- axis (str): how the motor is identified by the controller
- driver (str): this is the unique name of the required motor class
- controller (str): this is the unique name of the required controller class
- controllerID (str): a unique address used by the controller
- port (int): port number if used.  If not used any number should be entered
- min/maxValue (float): software limits
- offset (float): any relative difference between the controller coordinate system and the desired GUI coordinate system
- units (float): any scale factor between the controller units and the desired GUI units
- simulation (int): simulation state of the controller

An example configuration file including three motors is shown below.  These motors will automatically be available in the GUI
without further setup.

```
{
    "Beamline Energy": {
        "index": 0,
        "type": "primary",
        "axis": "Beamline Energy",
        "driver": "bcsMotor",
        "controllerID": "131.243.73.68",
        "port": 50000,
        "controller": "bcsController",
        "max velocity": 1000.0,
        "max acceleration": 5000.0,
        "last value": 500.0,
        "minValue": 250.0,
        "maxValue": 2600.0,
        "minScanValue": 250.0,
        "maxScanValue": 2600.0,
        "last range": 30.0,
        "last N points": 100.0,
        "last step:": 1.0,
        "last dwell time": 1,
        "offset": 0.0,
        "units": 1.0,
        "simulation": 1
    },
    "ZonePlateZ": {
        "index": 1,
        "type": "primary",
        "axis": "cosmic:ZP_Z",
        "driver": "epicsMotor",
        "controllerID": "smarAct",
        "port": 8000,
        "controller": "epicsController",
        "max velocity": 1000.0,
        "max acceleration": 5000.0,
        "last value": -5600.0,
        "minValue": -30000.0,
        "maxValue": -5000.0,
        "minScanValue": -30000.0,
        "maxScanValue": -5000.0,
        "last range": 100.0,
        "last N points": 50.0,
        "last step:": 2.0,
        "offset": -10828.148,
        "units": 1000.0,
        "simulation": 1
    },
    "SampleX": {
        "index": 2,
        "type": "primary",
        "axis": "x",
        "driver": "nptMotor",
        "port": 0,
        "controller": "nptController",
        "controllerID": "7340010",
        "max velocity": 1000.0,
        "max acceleration": 5000.0,
        "last value": 28.5,
        "minValue": -50.0,
        "maxValue": 50.0,
        "minScanValue": -40.0,
        "maxScanValue": 45.0,
        "last range": 10.0,
        "last N points": 100.0,
        "last step:": 0.1,
        "offset": 0.0,
        "waitTime": 0.0,
        "units": 1.0,
        "simulation": 1
    }
}
```

# derived motors

Derived motors are motor objects which utilize more than one primary motor for its action.  Creating a derived motor requires first setting up the motor
object which inherets the motor class just like primary motors.  The standard methods of that class will then actuate multiple axes which are connected
by the software controller and definted in motorConfig.json.  An example configuration is shown below.
```
    "Energy": {
        "index": 21,
        "type": "derived",
        "axes": {
            "axis1": "Beamline Energy",
            "axis2": "ZonePlateZ"
            },
        "driver": "derivedEnergy",
        "A0": 0,
        "A1": 13.333,
        "dr": 0.045,
        "max velocity": 1000.0,
        "max acceleration": 5000.0,
        "last value": 500.0,
        "minValue": 250.0,
        "maxValue": 2600.0,
        "last range": 30.0,
        "last N points": 100.0,
        "last step:": 1.0,
        "last dwell time": 1,
        "offset": 0.0,
        "units": 1000.0,
        "simulation": 1
    }
```
In this case, the type is "derived" and there is a new entry called "axes" which lists the primary motors that contribute to this derived motor.  The primary
motors must be separately defined in the same configuration file.  These axes are then available to the motor class.  An example "moveTo" method of the motor
class is shown below.  This shows how the axes defined in the JSON file can be accessed by the motor class.
```
    def moveTo(self, energy):
        if not(self.simulation):
            with self.lock:
                self.moving = True
                self.calibratedPosition = self.getZonePlateCalibration(energy)
                self.axes["ZonePlateZ"].calibratedPosition = self.calibratedPosition
                self.axes["ZonePlateZ"].moveTo(self.calibratedPosition)
                self.axes["Beamline Energy"].moveTo(energy)
                self.moving = False
        else:
            self.position = pos
```

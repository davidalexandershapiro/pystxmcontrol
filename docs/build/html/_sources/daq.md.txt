# setting up a daq device
In pystxmcontrol, a daq is anything that can be configured to return data either one value at a time or as a sequence of values.
It's abstract class thus only requires three methods: config, getPoint (a single value) and getLine (a sequence) as shown here:
```
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
```
An example from an actual daq class which interfaces with a Keysight 53230A counter is shown here:
```
    def getPoint(self):
        if self.simulation:
            time.sleep(self.dwell / 1000.)
            data = poisson(1e7 * self.dwell / 1000.)
            return data
        else:
            data = self.counter.getPoint()
            return data
```
This code simply executes the getPoint() method of the daq controller shown here:
```
    def getPoint(self):

        self.session.write("INIT:IMM")
        self.session.write("*TRG")
        data = self.session.ask("FETC?")
        return float(data)
```
In this case, the daq controller is sending SCPI commands to the counter using the usbtmc module.

# configuring a daq device

daq devices, like motors, are also configured using a JSON file.  Here is an example that defines
three daq devices, the default device and two others, an ADC and a CCD.  Each device requires it's
own daq driver definitioin.
```
{
  "default": {
    "index": 0,
    "name": "Diode",
    "driver": "keysight53230A",
    "visa": "USB::0x0957::0x1907::INSTR",
    "address": "169.254.2.30",
    "port": 5025,
    "simulation": true
  },
  "adc": {
    "index": 1,
    "name": "ADC",
    "driver": "keysightU2356A",
    "visa": "USB::0x0957::0x1418::INSTR",
    "channel": 101,
    "name": "dummy",
    "simulation": true
  },
  "ccd": {
    "index": 2,
    "name": "CCD",
    "driver": "fccd_control",
    "address": "131.243.73.179",
    "port": 49206,
    "simulation": true
  }
}
```

The only device which is automatically integrated into pystxmcontrol (at the GUI and scan level) is the default device.  The monitor thread managed by the server will poll the values of the default device periodically.  The update rate of that polling can be set in the main.json config file.  The other devices can be used by custom scan routines or custom gui displays but that is not currently automated.

# using a daq device with a hardware trigger

It is often necessary to closely synchronize motor motion with data acquisition.  pystxmcontrol achieves this with the combination of three elements:
- a motor driver which can configure an output TTL pulse on position
- a daq device which can be configured to record a sequence of data using a TTL trigger
- a combined software and hardware beam gate within which the first two items execute

The basic sequence of events is below.  In this example, the "controller" refers to the software controller which has read in all config files during controller.initialize().  The "scan" refers to the scan definition which has been communicated from the GUI.  This is described separately.  The basic sequence of events is the following:
- configure the motor driver to output pulse on position
```
controller.motors[scan["x"]]["motor"].setPositionTriggerOn(pos = trigger_position)
```
- configure daq to record a data sequence when triggered
```
controller.daq["default"].config(scanInfo["dwell"], count=1, samples=xPoints, trigger="EXT")
```
- utilize a software actuated shutter to ensure the beam is on while data is collected.  Shutter actuation is usually quite slow and thus not tightly synchronized to data acquisition.  It proceeds first with some delay before the hardware trigger is sent.
```
controller.daq["default"].initLine()
controller.daq["default"].autoGateOpen()
time.sleep(0.1) #shutter open has a 1.4 ms delay after command and 1ms rise time
controller.motors[scan["x"]]["motor"].moveLine(direction=scanInfo["direction"])
controller.daq["default"].autoGateClosed()
dataHandler.getLine(scanInfo.copy())
```
This final snippet of code is what performs a linear trajectory scan using a piezo controller.  The daq initLine() method arms the counter while autoGateOpen() is the combined software/hardware shutter which allows beam on the sample.  The motor moveLine() method is separately configured but utilizes the linear trajectory function of the piezo controller.  This has already been configured to provide a pulse at the start of the line.  After the line is complete the shutter is closed with autoGatClose() and finally the data is retrieved with getLine().  The getLine() method is called via the dataHandler, described separately, which manages all data transfer.  The line of data will be added to the local data structure, saved to disk and placed on a socket for access by the GUI.

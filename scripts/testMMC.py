from pystxmcontrol.drivers.mmcController import *
from pystxmcontrol.drivers.mmcMotor import *
import time

c = mmcController()
c.initialize()
m = mmcMotor(controller = c)
m.connect(axis = "z") #x, y or z
m.config = {"units":1, "offset": 0, "minValue":-1000, "maxValue":1000}
print(m.getPos())
m.moveTo(-5)
print(m.getPos())



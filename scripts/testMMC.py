from pystxmcontrol.drivers.mmcController import *
from pystxmcontrol.drivers.mmcMotor import *
import time

c = mmcController()
c.initialize()
m = mmcMotor(controller = c)
m.connect(axis = "y") #x, y or z
m.config = {"units":1000, "offset": 0, "minValue":-50000, "maxValue":10000}
print(m.getPos())
m.moveTo(0)
#m.configure_home()
#m.home()
print(m.getPos())



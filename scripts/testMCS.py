from pystxmcontrol.drivers.mcsController import *
from pystxmcontrol.drivers.mcsMotor import *

c = mcsController()
c.initialize()
m = mcsMotor(controller=c)
m.connect(axis='y')
print(m.getPos())
m.moveTo(pos=1000)
print(m.getPos())
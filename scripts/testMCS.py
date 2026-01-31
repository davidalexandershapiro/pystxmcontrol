from pystxmcontrol.drivers.mcsController import *
from pystxmcontrol.drivers.mcsMotor import *

c = mcsController(address='192.168.1.200',port=18307)
c.initialize()
print(c.getPos(0))
print(c.getPos(1))
print(c.getPos(2))
#m = mcsMotor(controller=c)
#m.connect(axis='x')
#print(m.getPos())
#m.moveTo(pos=1000)
#print(m.getPos())

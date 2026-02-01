from pystxmcontrol.drivers.mcsController import *
from pystxmcontrol.drivers.mcsMotor import *

c = mcsController(address='192.168.168.200',port=12959)
c.initialize()
print(c.getPos(5))
#c.set_sensor_on(4)
#c.move(4,0)
#print(c.getPos(4))
# print(c.getPos(4))
# print(c.getPos(5))
#m = mcsMotor(controller=c)
#m.connect(axis='x')
#print(m.getPos())
#m.moveTo(pos=1000)
#print(m.getPos())

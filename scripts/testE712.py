from pystxmcontrol.drivers.E712Controller import *
from pystxmcontrol.drivers.E712Motor import *

pos = -1000

c = E712Controller()
c.initialize()
m = E712Motor(controller = c)
m.connect(axis = 'y')
print(m.getPos())
m.moveTo(pos)
print(m.getPos())
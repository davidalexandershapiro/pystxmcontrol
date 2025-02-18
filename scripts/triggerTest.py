from pystxmcontrol.drivers.nptController import *
from pystxmcontrol.drivers.nptMotor import *
import time

c = nptController()
c.initialize()
m = nptMotor(controller = c)
m.connect(axis='x')

pos = -5.
d = 1.
c.setPositionTrigger(pos = pos, axis = 1, mode = 'off')

while True:
    m.moveTo(pos=pos+d/2.)
    time.sleep(0.02)
    m.moveTo(pos=pos-d/2.)
    time.sleep(0.02)

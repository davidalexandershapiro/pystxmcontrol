from pystxmcontrol.drivers.xpsController import *
from pystxmcontrol.drivers.xpsMotor import *

c = xpsController(address = '192.168.168.154', port = 5001)
c.initialize()
m = xpsMotor(controller = c)
m.connect(axis = "CompuStageAlpha.AlphaPos")

print(m.getPos())
#m.moveTo(pos = 2)
m.stop()
print(m.getPos())

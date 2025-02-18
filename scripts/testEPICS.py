from pystxmcontrol.drivers.epicsController import *
from pystxmcontrol.drivers.epicsMotor import *
import time

c = epicsController(simulation = False)
m = epicsMotor(controller = c)
m.config = {"minValue":-2.0,"maxValue":-1}
m.connect(axis = "cosmic:ZP_Z")
print(m.getPos())
t0 = time.time()
m.moveTo(pos = -1.4)
print("Motor move took %.4f ms" %((time.time()-t0)*1000.))

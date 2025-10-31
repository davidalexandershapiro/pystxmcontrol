from pystxmcontrol.drivers.shutter import *
import time

s = shutter(address='/dev/arduino')
s.connect()
s.dwell1 = 10
s.dwell2 = 0
s.shutterMASK = 1
s.softGATE = 0
s.setStatus(softGATE = 1)
print(s.getStatus())

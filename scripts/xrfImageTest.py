from pystxmcontrol.drivers.xspress3 import xspress3
import matplotlib.pyplot as plt
import numpy as np
import sys
from pystxmcontrol.drivers.mclController import mclController
from pystxmcontrol.drivers.mclMotor import mclMotor
from pystxmcontrol.drivers.shutter import shutter


args = sys.argv

dwell = float(args[1]) #ms

xcenter = float(args[2])
ycenter = float(args[3])
xrange = float(args[4])
yrange = float(args[5])
xstep = float(args[6])
ystep = float(args[7])
simulation = bool(args[8])
try:
    save = args[9]
except:
    save = None

gate = shutter('arduino')
gate.connect(simulation = simulation)
gate.setStatus(softGATE = 0)

c = mclController(simulation = simulation)
c.initialize()
mx = mclMotor(controller = c)
mx.connect(axis = 'x')
my = mclMotor(controller = c)
my.connect(axis = 'y')

ystart = ycenter-yrange/2
ystop = ycenter + yrange/2
xstart = xcenter-xrange/2
xstop = xcenter + xrange/2

for y in np.arange(ystart,ystop,ystep):
    mx.moveTo(xstart)
    my.moveTo(y)
    c.setup_trajectory('x',xstart,xstop,dwell,int(abs(xstop-xstep)/xstep),mode = '1d_line_with_return')

xrf = xspress3(simulation = simulation)

xrf.config(dwell,count,samples,trigger='BUS')

data = xrf.getLine()
print('shape of data: {}'.format(data.shape))
plt.plot(np.arange(0,10*len(data[0]),10)/1000,data.mean(axis = 0))
plt.xlabel('Energy (keV)')
plt.ylabel('Counts')
plt.show()
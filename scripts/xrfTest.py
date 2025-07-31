from pystxmcontrol.drivers.xspress3 import xrfDetector
import matplotlib.pyplot as plt
import numpy as np
import sys

args = sys.argv

dwell = int(args[1]) #ms
count = 1
samples = int(args[2])

xrf = xrfDetector(simulation = True)

xrf.config(dwell,count,samples,trigger='BUS')

data = xrf.getLine()
print('shape of data: {}'.format(data.shape))
plt.plot(np.arange(0,10*len(data[0]),10)/1000,data.mean(axis = 0))
plt.xlabel('Energy (keV)')
plt.ylabel('Counts')
plt.show()
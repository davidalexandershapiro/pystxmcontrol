from pystxmcontrol.drivers.keysightCounter import *
from pystxmcontrol.drivers.shutter import shutter
import numpy as np
import matplotlib.pyplot as plt



gate = shutter()
gate.connect(simulation = True)
gate.setStatus(softGATE = 0)

trigger = "BUS" # "BUS" or "EXT"

print('creating counter object')
a = counter()
print('connecting to counter')
a.connect()
print('configuring counter')
a.config(1, count = 1, samples = 10000, trigger = trigger, output = 'OFF')

##open shutter and get data
gate.setStatus(softGATE = 1, shutterMASK = 1)

print('initializing line')

a.initLine()

print('triggering counter')

if trigger == "BUS": a.busTrigger()

print('collecting data')

counts = a.getLine()
print('data points received: ',len(counts))
    

gate.setStatus(softGATE = 0, shutterMASK = 1)

##Disconnect from counter
print('disconnecting')
a.disconnect()
print('plotting')
#plt.figure()
#plt.plot(y)
#plt.plot(x)

plt.figure()
plt.plot(counts)

plt.figure()
plt.semilogy(np.fft.fftfreq(10000,0.001),np.abs(np.fft.fft(counts))**2)
plt.xlim(-5,200)
plt.show()
from pystxmcontrol.drivers.U2356A import *
from pystxmcontrol.drivers.keysightCounter import *
from pystxmcontrol.drivers.shutter import shutter
import numpy as np
import matplotlib.pyplot as plt
from scipy import interpolate
from pystxmcontrol.controller.spiral import spiralcreator

from pystxmcontrol.drivers.mclController import mclController
from pystxmcontrol.drivers.mclMotor import mclMotor

import time

import os

date = '231103'
datadir = '/global/scratch/pystxmcontrolData/20'+date[0:2]+'/'+date[2:4]+'/'+date+'/SpiralTest/'
try:
    os.makedirs(datadir)
except FileExistsError:
    pass

import glob

oldfiles = glob.glob(datadir+'STXMSpiral_'+date+'*.hdf5')
oldfiles.sort()
try:
    last = int(oldfiles[-1][-8:-5])
except:
    last = -1
next = last + 1

import h5py

import sys
xCenter = float(sys.argv[1])
yCenter = float(sys.argv[2])
radius = float(sys.argv[3])
nPoints = int(sys.argv[4])
try:
    maxSpeed = float(sys.argv[5])
except:
    maxSpeed = 1. #um/ms or mm/s
#xCenter = 18.5
#yCenter = 9.8
#radius = 3

#First we find the number of revolutions
numloops = int(nPoints/2)
#Next the number of measurements. There is a difference between the position measurements and the daq measurements.
#The number of position samples is calculated by the number of corners in a circle (arbitrary).
nCorners = 100
nPosSamplesMin = numloops*nCorners 
#Max samples in 1 scan is given by the motor, limited to 5000 for xy scan.
nSingleScanMax = 5000
#The total samples collected is set to 5000 if it would otherwise be lower.
nPosSamples = max(nPosSamplesMin,nSingleScanMax)
#Motor dwell time min and max are set by the motor.
minPosDwell = 0.1 #ms
#Seem to be running into some issues when dwell is too long.
maxPosDwell = 5. #ms

#maxSpeed is set by the user (arg 5, default of 1 mm/s)
#maxSpeed occurs at the edge of the scan. 2pir/t
#time is given by dwell*nCornersinCircle
#dwell is then 2pir/(maxSpeed*nCorners)
#actual speed could be off by a factor of 2 (spiral tends to put more points at the center of the scan).
actualDwell = 2*np.pi*radius/(maxSpeed*nCorners)

#Keeping maxSpeed constant, if dwell is too short, we use less points. This only happens if speed is very large or nLoops is small.
if actualDwell < minPosDwell:
    nPosSamples = int(nPosSamples/minPosDwell*actualDwell)
    actualDwell = minPosDwell
    
#Similarly, if dwell is too long, we use more points. This only happens if the nLoops is very large or speed is very small.
if actualDwell > maxPosDwell:
    nPosSamples = int(nPosSamples/maxPosDwell*actualDwell)
    actualDwell = maxPosDwell
 
    
#These are the numbers the spiral generator needs
scanTime = actualDwell*nPosSamples/1000. #seconds
fMax = 50. #Hz


#The other failure mode is if the frequency gets too high.
#This sets the average frequency to fMax.
avFreq = numloops/scanTime
if avFreq > fMax/2:
    factor = avFreq/fMax*2
    if actualDwell*factor>maxPosDwell:
        nPosSamples = int(nPosSamples*factor)
    else:
        actualDwell = actualDwell*factor
    
    scanTime = scanTime*factor
    

#One final failure mode is if there are too many points or if the scan takes too long.
#We deal with this by splitting up the scan into multiple parts.

maxTime = 2.5 #seconds
#These ratios are how many sections we should split the scan into.
timeRatio = scanTime/maxTime #>1 only for ?
pointRatio = nPosSamples/nSingleScanMax #>1 only for extremely large number of loops or very large scans possibly.

#The number of splits are the maximum between 1 (no splits) and the two ratios above.
nSplits = int(np.ceil(max(1,timeRatio,pointRatio)))
nPosSamples = nSplits*int(nPosSamples/nSplits) #still total number of samples.

print("Splitting scan into %s trajectories." %nSplits)

#This can cause problems if the number of points doesn't evenly divide the number of splits so we have to update this.
scanTime = actualDwell*nPosSamples/1000. #seconds

samplingFrequency = 1./actualDwell*1000. #Hz
    
#print(nPosSamples)
#print(actualDwell)
#print(scanTime)
#print(samplingFrequency)

DAQOversample = 2 # Number of DAQ measurements per pixel (on average)

reqDAQPoints = DAQOversample*nPoints**2*np.pi/4

#DAQFactor is the ratio between number of DAQ points vs motor points.
DAQFactor = reqDAQPoints/nPosSamples

print("DAQFactor: %s" %DAQFactor)


# Incorrect, time needs to be rounded to nearest 1 us.
reqDAQPointsPerScan = int(reqDAQPoints/nSplits)






print("Estimated Time: %s" %scanTime)

#connect to the shutter.  Must turn off pystxmcontrol first
gate = shutter()
gate.connect(simulation = False)
gate.setStatus(softGATE = 0)

trigger = "EXT" # "BUS" or "EXT"
#fMax = 100. #Hz
#scanRange = 5. #microns
#scanTime = 1.
#samplesPerSecond = 5000.

##setup of spiral waveform here
#numloops is roughly half number of pixels in the FOV
#scanradius will always be 2**15 and then the function generated needs to be given the proper voltage scale to convert to microns
y,x = spiralcreator(samplingfrequency = samplingFrequency, scantime = scanTime, numloops = numloops, clockwise = True, \
    spiralscantype = "InstrumentLimits", inratio = 0.05, scanradius = radius, maxFreqXY = fMax)
x += xCenter
y += yCenter

#enforce the correct size of these arrays to avoid off by one errors.
if len(x)<nPosSamples:
    x = np.pad(x, (0, nPosSamples-len(x)),mode = 'edge')
    y = np.pad(y, (0, nPosSamples-len(x)),mode = 'edge')
elif len(x)>nPosSamples:
    x = x[:nPosSamples]
    y = y[:nPosSamples]


#Split the list according to the number of splits identified previously.
xList = x.reshape(nSplits,int(nPosSamples/nSplits))
yList = y.reshape(nSplits,int(nPosSamples/nSplits))

#x = x[::-1]
#y = y[::-1]
    
#This is wrong, needs to be changed to Keysight Counter 
a = counter()
a.connect(visa_address = "USB::0x0957::0x1907::INSTR")


##configure counter
a.config(actualDwell/DAQFactor, count = 1, samples = reqDAQPointsPerScan, trigger = trigger, output = 'OFF')

##Configure and run MCL
c = mclController(simulation = False)
c.initialize()
#c.setPositionTrigger(pos = 0, axis = 1, mode = 'on')
#Move to center of spiral
c.write(1,50+yCenter)
c.write(2,50+xCenter)


##open shutter and get data
gate.setStatus(softGATE = 1, shutterMASK = 1)
dataList = []
xMeasList = []
yMeasList = []
t1 = time.time()
for i in range(nSplits):


    a.initLine()

    #print('Begin Loop: %s' %(time.time()-t1))
    xReq = xList[i]
    yReq = yList[i]
    if trigger == "BUS": a.busTrigger()

    #print('Prior to setup: %s' %(time.time()-t1))
    c.setup_xy(yReq+50,xReq+50,actualDwell)
    #print('After setup: %s' %(time.time()-t1))
    time.sleep(0.1)
    #Do the spiral scan
    
    #print('Prior to acquire: %s' %(time.time()-t1))
    xVals, yVals = c.acquire_xy()-np.vstack([50,50])
    
    #print('After acquire: %s' %(time.time()-t1))
    xMeasList.append(xVals)
    yMeasList.append(yVals)

    #print('Prior to getLine: %s' %(time.time()-t1))
    counts = a.getLine()
    
    #print('After getLine: %s' %(time.time()-t1))
    dataList.append(counts)
    
    #print('End Loop: %s' %(time.time()-t1))

print("Measurement Time: %s" %(time.time()-t1))

xMeas = np.array(xMeasList).flatten()
yMeas = np.array(yMeasList).flatten()
data = np.array(dataList).flatten()

xy_tVals = np.linspace(0,1,len(xMeas))
data_tVals = np.linspace(0,1,len(data))

xInterp = np.interp(data_tVals, xy_tVals, xMeas)
yInterp = np.interp(data_tVals, xy_tVals, yMeas)




c.close() #disconnect MCL
##close shutter
gate.setStatus(softGATE = 0, shutterMASK = 1)

##Disconnect from counter
a.disconnect()

#plt.figure()
#plt.plot(y)
#plt.plot(x)

plt.figure()
plt.plot(x)
plt.plot(xMeas)


plt.figure()
plt.plot(x,y)
plt.plot(xMeas,yMeas)
plt.xlabel("X Position (um)")
plt.ylabel("Y Position (um)")


#Here the oversampling factor is the approximate number of events per pixel.
#pixels are resized according to this value.

#May need to be transposed?
nEvents, xbins, ybins = np.histogram2d(xInterp,yInterp,bins = nPoints)
binCounts, xbins, ybins = np.histogram2d(xInterp,yInterp,bins = nPoints, weights = data)

avCounts = binCounts/nEvents*DAQOversample
avCounts[np.isinf(avCounts)] = 0
avCounts[np.isnan(avCounts)] = 0

plt.figure()
plt.imshow(nEvents.T)
plt.title('nEvents')
plt.clim([0,10])
plt.colorbar()

plt.figure()
plt.imshow(avCounts.T)
plt.title('avCounts')
plt.colorbar()



newfile = (datadir + 'STXMSpiral_'+date+'{:03d}.hdf5').format(next)

print("writing to " + newfile)
with h5py.File(newfile,'w') as f:
    xdset = f.create_dataset("xPositions", data = xMeas)
    
    ydset = f.create_dataset("yPositions", data = yMeas)
    xidset = f.create_dataset("xInterp", data = xInterp)
    yidset = f.create_dataset("yInterp", data = yInterp)
    datadset = f.create_dataset("data", data = data)
    nEventsdset = f.create_dataset("nEvents", data = nEvents)
    avCountsdset = f.create_dataset("avCounts",data = avCounts)
    
#Compare with CLV and CAV

#xIL = xMeas
#yIL = yMeas

#x,y = spiralcreator(samplingfrequency = samplesPerSecond, scantime = scanTime, numloops = 25, clockwise = True, \
#    spiralscantype = "CAV", inratio = 0.05, scanradius = radius, maxFreqXY = fMax)
    

#c.setup_xy(y+50,x+50,scanTime / samplesPerSecond * 1000)
#xCAV, yCAV = c.acquire_xy()-np.vstack([50,50])

#x,y = spiralcreator(samplingfrequency = samplesPerSecond, scantime = scanTime, numloops = 25, clockwise = True, \
#    spiralscantype = "CLV", inratio = 0.05, scanradius = 5., maxFreqXY = fMax)
    

#c.setup_xy(y+50,x+50,scanTime / samplesPerSecond * 1000)
#xCLV, yCLV = c.acquire_xy()-np.vstack([50,50])

#plt.figure()
#plt.plot(xIL,label = 'IL')
#plt.plot(xCAV, label = 'CAV')
#plt.plot(xCLV, label = 'CLV')
#plt.legend()
#plt.title('IL vs CAV vs CLV')

#nCLV, xbins, ybins = np.histogram2d(xCLV,yCLV,bins = [nx, ny])
#nCAV, xbins, ybins = np.histogram2d(xCAV,yCAV,bins = [nx, ny])

#plt.figure()
#plt.imshow(nCAV)
#plt.clim([0,10])
#plt.colorbar()
#plt.title('CAV Event Binning')

#plt.figure()
#plt.imshow(nCLV)
#plt.clim([0,10])
#plt.colorbar()
#plt.title('CLV Event Binning')



plt.show()





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

#date = '240307'
#datadir = '/global/scratch/pystxmcontrolData/20'+date[0:2]+'/'+date[2:4]+'/'+date+'/SpiralTest/'
#try:
#    os.makedirs(datadir)
#except FileExistsError:
#    pass

#import glob

#oldfiles = glob.glob(datadir+'STXMSpiral_'+date+'*.hdf5')
#oldfiles.sort()
#try:
#    last = int(oldfiles[-1][-8:-5])
#except:
#    last = -1
#next = last + 1

#import h5py

import sys

xCenter = float(sys.argv[1])
yCenter = float(sys.argv[2])
radius = float(sys.argv[3])
nPoints = int(sys.argv[4])
dwell = float(sys.argv[5])
try:
    maxSpeed = float(sys.argv[6])
except:
    maxSpeed = 1. #um/ms or mm/s
    
xRange = radius*2
yRange = radius*2
xPoints = nPoints
yPoints = nPoints


# The dwell time plus the number of pixels sets the overall scan time.
# This is multiplied by the DAQ oversampling factor.
# Because this time is treated as a minimum, physical constraints can cause this time to increase.
# Setting dwell to 0 will run the scan as fast as possible.
DAQOversample = 2. # Average number of measurements per pixel.
reqDwell = dwell
numTotalPixels = xPoints*yPoints*np.pi/4 #float
reqScanTime = reqDwell*numTotalPixels/1000 #seconds

# number of loops is given by half the number of pixels (max of x and y).
# Loop oversampling multiplies this number to reduce number of pixels without any loops, but makes it slower.
# Number of loops is (probably) the limiting speed factor for small scans so don't set this too high.
loopOversample = 1.2
numLoops = int(max(xPoints, yPoints)*loopOversample / 2.)

# There's a maximal frequency at which the scan can be performed.
# We end up scanning at a constant linear velocity for larger scans, so I am unsure how to set this without
# changing how the spiral is generated. Hence the fudge factor of 2 here because the inner spiral is faster.
fMax = 50. #Hz
minTime = numLoops/fMax*2.
minFreqScanTime = max(minTime,reqScanTime)

# We also can't have more than 5000 points per motor trajectory.
# The number of corners per loop sets how circular they are. Setting this larger shouldn't affect speed too much.
# We also limit the motor positions based on the dwell allowed by the MCL controller.
# The original script also had a maximal speed. We ignore that here.
numCorners = 100 #minimum average corners per loop. Try messing with this
minMotorDwell = 0.12 #ms (See "December 2023" notebook for explanation of this number)
maxMotorDwell = 10. #ms

# minimal time allowed for motor movements (many loops)
minLoopMotorPoints = numCorners*numLoops
minLoopMotorScanTime = minLoopMotorPoints*minMotorDwell/1000

# total scan time is now determined
totScanTime = max(minFreqScanTime,minLoopMotorScanTime)

# Another case to look at is when the dwell is very long.
minDwellMotorPoints = totScanTime/maxMotorDwell

# The total time for a single trajectory cannot be larger than 2.5 or MCL will crash.
# We fix this by separating into multiple trajectories if necessary.
maxTrajTime = 2.5 #seconds
timeSplit = int(max(1,totScanTime/maxTrajTime))

# We also may need to split it based on motor points if there are a large number of loops or a long dwell.
maxTrajPoints = 5000 #points
reqMotorPoints = max(minDwellMotorPoints,minLoopMotorPoints)
motorSplit = int(np.ceil(max(1,reqMotorPoints/maxTrajPoints)))

# Now we know the total number of times the scan has to be split and we can set up the trajectories.
totalSplit = max(timeSplit,motorSplit)
totalTrajTime = totScanTime/totalSplit

# The number of motor points can be set to maximum unless this makes the dwell too short.
# These are the desired number of points, but we have to adjust them again to round to the nearest 0.01 ms.
motorTimeResolution = 0.001 #ms (based off old manual. Likely correct though.)
# Here we set the dwell to the value for 5000 motor points in a trajectory.
if totalTrajTime/maxTrajPoints >= minMotorDwell/1000.:
    desMotorDwell = totalTrajTime/maxTrajPoints*1000.
    # Round to nearest dwell time. Ceiling so we don't have > 5000 points
    actMotorDwell = np.ceil(desMotorDwell/motorTimeResolution)*motorTimeResolution
    numTrajMotorPoints = int(totalTrajTime/actMotorDwell*1000.)
# If we can't, we instead set the dwell to the minimum
else:
    actMotorDwell = minMotorDwell
    numTrajMotorPoints = int(totalTrajTime/actMotorDwell*1000.)

#scanTime might be slightly different than the prior estimate    
scanTime = numTrajMotorPoints*actMotorDwell*totalSplit/1000. #s

#The spiral construction needs the sampling frequency and some of the future calculations need the total number of positions.
samplingFrequency = 1/actMotorDwell*1000. #Hz
nPosSamples = numTrajMotorPoints * totalSplit
#The DAQ dwell time is set by the number of pixels requested and the actual scan time
#Resolution for the DAQ is 1 us.
DAQTimeResolution = 0.001 #ms (based on keysight manual and reading out CONF? command)
trajPixels = int(numTotalPixels/totalSplit*DAQOversample)
reqDAQDwell = totalTrajTime/trajPixels*1000.
actDAQDwell = int(reqDAQDwell/DAQTimeResolution)*DAQTimeResolution
numTrajDAQPoints = int(totalTrajTime/actDAQDwell*1000.)



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
y,x = spiralcreator(samplingfrequency = samplingFrequency, scantime = scanTime, numloops = numLoops, clockwise = True, \
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
xList = x.reshape(totalSplit,int(nPosSamples/totalSplit))
yList = y.reshape(totalSplit,int(nPosSamples/totalSplit))

#x = x[::-1]
#y = y[::-1]
    
#This is wrong, needs to be changed to Keysight Counter 
a = counter()
a.connect(visa_address = "USB::0x0957::0x1907::INSTR")

DAQcount = numTrajMotorPoints
DAQsamples = int(np.ceil(numTrajDAQPoints / DAQcount))
numTrajDAQPoints = DAQsamples * DAQcount
# we pad the dwell time so that the daq is done collecting by the time the motor has moved on to the next position.
# May have to make this dependent on the motor dwell time? 4 us is a total guess.
dwellPad = 0.005 * DAQsamples
actDAQDwell = int(
    np.floor((actMotorDwell - dwellPad) / DAQsamples / DAQTimeResolution)) * DAQTimeResolution

##configure counter
a.config(actDAQDwell, count = DAQcount, samples = DAQsamples, trigger = trigger, output = 'OFF')

##Configure and run MCL
c = mclController(simulation = False)
c.initialize()
mx = mclMotor(controller = c)
mx.connect(axis = 'x')
my = mclMotor(controller = c)
my.connect(axis = 'y')
#c.setPositionTrigger(pos = 0, axis = 1, mode = 'on')
#Move to center of spiral
#c.write(1,50+yCenter)
#c.write(2,50+xCenter)
mx.moveTo(50+xCenter)
my.moveTo(50+yCenter)


##open shutter and get data
gate.setStatus(softGATE = 1, shutterMASK = 1)
dataList = []
xMeasList = []
yMeasList = []
t1 = time.time()
for i in range(totalSplit):


    a.initLine()

    #print('Begin Loop: %s' %(time.time()-t1))
    xReq = xList[i]
    yReq = yList[i]
    if trigger == "BUS": a.busTrigger()

    mx.trajectory_pixel_count = len(xReq)
    mx.trajectory_pixel_dwell = actMotorDwell
    mx.lineMode = "arbitrary"
    mx.trajectory_x_positions = xReq+50
    mx.trajectory_y_positions = yReq+50
    mx.update_trajectory()


    #print('Prior to setup: %s' %(time.time()-t1))
    #c.setup_xy(yReq+50,xReq+50,actMotorDwell)
    #print('After setup: %s' %(time.time()-t1))
    time.sleep(0.1)
    #Do the spiral scan
    
    #print('Prior to acquire: %s' %(time.time()-t1))
    #xVals, yVals = c.acquire_xy()-np.vstack([50,50])
    mx.moveLine()
    xVals,yVals = mx.positions - np.vstack([50,50])

    
    #print('After acquire: %s' %(time.time()-t1))
    xMeasList.append(xVals)
    yMeasList.append(yVals)

    #print('Prior to getLine: %s' %(time.time()-t1))
    counts = a.getLine()
    print(len(counts))
    
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



#newfile = (datadir + 'STXMSpiral_'+date+'{:03d}.hdf5').format(next)

#print("writing to " + newfile)
#with h5py.File(newfile,'w') as f:
#    xdset = f.create_dataset("xPositions", data = xMeas)
#
#    ydset = f.create_dataset("yPositions", data = yMeas)
#    xidset = f.create_dataset("xInterp", data = xInterp)
#    yidset = f.create_dataset("yInterp", data = yInterp)
#    datadset = f.create_dataset("data", data = data)
#    nEventsdset = f.create_dataset("nEvents", data = nEvents)
#    avCountsdset = f.create_dataset("avCounts",data = avCounts)
    
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



#plt.show()





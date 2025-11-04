from pystxmcontrol.drivers.nptMotor import nptMotor
from pystxmcontrol.drivers.nptController import nptController
from pystxmcontrol.drivers.xpsMotor import xpsMotor
from pystxmcontrol.drivers.derivedPiezoWithStepper import derivedPiezoWithStepper
from pystxmcontrol.drivers.xpsController import xpsController
from pystxmcontrol.drivers.keysight53230A import keysight53230A
import numpy, time, sys
import pylibftdi as ftdi

#The nPoint address can be found with the following
ftdi_devices = ftdi.Driver().list_devices()
for device in ftdi_devices:
    nDevices = len([d for d in device if "LC403" in d])
    if nDevices == 1:
        nPoint_address = device[2]
        print("Found nPoint device address: %s" %nPoint_address)
    elif nDevices == 0:
        print("No nPoint device found")
        sys.exit()

l = 100000 #number of lines
n = 100 #number of points per dimenion
dwell = 1 #pixel dwell in milliseconds
r = 20.,0. #range in microns
c = 0.,0.0 #center in microns

#initialize DAQ
daq = keysight53230A()
daq.start()
daq.config(dwell, count=1, samples = n, trigger='EXT') # count =1 for continuous

#Set up the piezo motors
c1 = nptController(address = nPoint_address)
c1.initialize()
xFine = nptMotor(controller=c1)
yFine = nptMotor(controller=c1)
xFine.config = {"offset":0,"units":1,"minValue":-50,"maxValue":50}
yFine.config = {"offset":0,"units":1,"minValue":-50,"maxValue":50}
xFine.connect(axis='x')
yFine.connect(axis='y')

#Set up the coarse motors
c2 = xpsController(address = '192.168.0.251')
c2.initialize()
xCoarse = xpsMotor(controller=c2)
yCoarse = xpsMotor(controller=c2)
xCoarse.config = {"offset":-34,"units":1,"minValue":-5000,"maxValue":5000}
yCoarse.config = {"offset":1214,"units":1,"minValue":-5000,"maxValue":5000}
xCoarse.connect(axis = "CoarseX.Pos")
yCoarse.connect(axis = "CoarseY.Pos")

#Set up the derived motors
x = derivedPiezoWithStepper()
x.axes = {"axis1":xFine, "axis2":xCoarse}
x.config = {"offset":0,"units":1,"minValue":-5000,"maxValue":5000,"reset_after_move":True,"simulation":False}
x.connect(axis = 'x')
y = derivedPiezoWithStepper()
y.axes = {"axis1":yFine, "axis2":yCoarse}
y.config = {"offset":0,"units":1,"minValue":-5000,"maxValue":5000,"reset_after_move":True,"simulation":False}
y.connect(axis = 'y')

# x.resetPiezo()
# y.resetPiezo()

print(x.getPos(),y.getPos())
print(xCoarse.getPos(),yCoarse.getPos())
print(xFine.getPos(),yFine.getPos())

x.moveBy(-200.00)
y.moveBy(-200.00)

print(x.getPos(),y.getPos())
print(xCoarse.getPos(),yCoarse.getPos())
print(xFine.getPos(),yFine.getPos())

# #generate positions
# start_position = c[0] - r[0] / 2., c[1] - r[1] / 2.
# stop_position = c[0] + r[0] / 2., c[1] + r[1] / 2.
#
# ##initial setup
# xMotor.lineMode = "continuous"
# xMotor.trajectory_pixel_dwell = dwell
# xMotor.trajectory_pixel_count = n
# xMotor.trajectory_start = start_position
# xMotor.trajectory_stop = stop_position
# xMotor.update_trajectory()
# print("Stage velocity is %.4f mm/s" %xMotor.velocity)
# xMotor.moveTo(pos = stop_position[0] + xMotor.xpad)
# time.sleep(0.1)
# xMotor.moveTo(pos = start_position[0] - xMotor.xpad)
# yMotor.moveTo(pos = start_position[1] - xMotor.ypad)
# time.sleep(0.1)
#
# print(start_position[0] - xMotor.xpad,stop_position[0] + xMotor.xpad)
#
# #Scan loop
# t0 = time.time()
# for i in range(l):
#     #daq.initLine()
#     #if (i % 2) == 0: xMotor.moveLine(direction = "forward")
#     #else: xMotor.moveLine(direction = "backward")
#     xMotor.moveLine(direction = "forward")
#     #data = daq.getLine()
#     xMotor.moveTo(pos = start_position[0] - xMotor.xpad)
#     time.sleep(0.01)
# t = time.time()-t0
# print("Overhead time per point (ms): %.4f" %(1000. * t / l / n - dwell))
# xMotor.moveTo(pos = 0.)
# yMotor.moveTo(pos = 0.)


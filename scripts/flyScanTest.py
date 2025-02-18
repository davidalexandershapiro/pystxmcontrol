from pystxmcontrol.drivers.nptMotor import nptMotor
from pystxmcontrol.drivers.nptController import nptController
from pystxmcontrol.drivers.keysight53230A import keysight53230A
import numpy, time



l = 100000 #number of lines
n = 100 #number of points per dimenion
dwell = 1 #pixel dwell in milliseconds
r = 20.,0. #range in microns
c = 0.,0.0 #center in microns

#initialize DAQ
daq = keysight53230A()
daq.start()
daq.config(dwell, count=1, samples = n, trigger='EXT') # count =1 for continous

#initialize controller and motors
controller = nptController()
controller.initialize()
xMotor = nptMotor(controller=controller)
yMotor = nptMotor(controller=controller)
xMotor.connect(axis='x')
yMotor.connect(axis='y')

#generate positions
start_position = c[0] - r[0] / 2., c[1] - r[1] / 2.
stop_position = c[0] + r[0] / 2., c[1] + r[1] / 2.

##initial setup
xMotor.lineMode = "continuous"
xMotor.trajectory_pixel_dwell = dwell
xMotor.trajectory_pixel_count = n
xMotor.trajectory_start = start_position
xMotor.trajectory_stop = stop_position
xMotor.update_trajectory()
print("Stage velocity is %.4f mm/s" %xMotor.velocity)
xMotor.moveTo(pos = stop_position[0] + xMotor.xpad)
time.sleep(0.1)
xMotor.moveTo(pos = start_position[0] - xMotor.xpad)
yMotor.moveTo(pos = start_position[1] - xMotor.ypad)
time.sleep(0.1)

print(start_position[0] - xMotor.xpad,stop_position[0] + xMotor.xpad)

#Scan loop
t0 = time.time()
for i in range(l):
    #daq.initLine()
    #if (i % 2) == 0: xMotor.moveLine(direction = "forward")
    #else: xMotor.moveLine(direction = "backward")
    xMotor.moveLine(direction = "forward")
    #data = daq.getLine()
    xMotor.moveTo(pos = start_position[0] - xMotor.xpad)
    time.sleep(0.01)
t = time.time()-t0
print("Overhead time per point (ms): %.4f" %(1000. * t / l / n - dwell))
xMotor.moveTo(pos = 0.)
yMotor.moveTo(pos = 0.)


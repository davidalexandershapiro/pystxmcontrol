from pystxmcontrol.drivers.mclController import *
import time
import matplotlib.pyplot as plt

mcl = mclController()
mcl.initialize()

#move to the center of the range
mcl.write(axis = 1, pos = 50)
mcl.write(axis = 2, pos = 50)

#set up a linear trajectory
start = 45,50 #x,y
stop = 55,50
dwell = 1
count = 100
pad = 1,0
trigger_axis = 1
mcl.setup_trajectory(trigger_axis, start, stop, dwell, count, mode = "line", pad = pad)

#set waveform trigger
mcl.setPositionTrigger(mode="off")
mcl.setPositionTrigger(mode = "on", clock = 2)

for i in range(20):
    #move to start 
    mcl.write(axis = 1, pos = start[0])
    mcl.write(axis = 2, pos = start[1])

    #execute the trajectory with position read
    positions = mcl.acquire_xy(axes=[1,])
    print(positions)
    time.sleep(1)

print("---------------------------------------")
print("Mad City Labs Nanodrive Positions...")
print("---------------------------------------")
print("Axis 1 position: %.4f" %mcl.read(1))
print("Axis 2 position: %.4f" %mcl.read(2))
print("---------------------------------------\n")
mcl.close()

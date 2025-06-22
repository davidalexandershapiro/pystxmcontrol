from pystxmcontrol.drivers.mclController import *
import time
import matplotlib.pyplot as plt

mcl = mclController()
mcl.initialize()
#mcl.setClock(mode = 0)
#mcl.setPositionTrigger(pos = 0., axis = 1, mode = "off", clock = 2)
#mcl.write(1,0)
#mcl.write(1,0)
#mcl.write(1,40.0)
#mcl.write(2,40.0)
#time.sleep(1)
#mcl.setup_line(1,50,52,0.05)
#mcl.trigger_line(1)

#Assumes config offset is zero, drives from one end to the other.
start = (10,10)
stop = (20,20)
repeats = 1
tot_time = 2.0 #keep less than 2.5

#Circular test
Freq = 50 #Hz
ang_freq = Freq*(np.pi*2)
nPoints = 4000
dwell = tot_time/nPoints*1000
trajx = 50+40*np.sin(np.linspace(0,tot_time,nPoints)*ang_freq)
trajy = 50+40*np.cos(np.linspace(0,tot_time,nPoints)*ang_freq)

#plt.plot(np.linspace(0,tot_time,4000),trajx)
#plt.show()

for i in range(repeats):
    #mcl.setup_trajectory(1,start,stop,dwell,100)
    #xpos, ypos = mcl.acquire_xy()
    #time.sleep(0.2)
    #mcl.setup_trajectory(1,stop,start,dwell,100)
    #xpos, ypos = mcl.acquire_xy()
    mcl.setup_xy(trajx, trajy,dwell)
    mcl.acquire_xy()
    time.sleep(0.2)
    print('iteration {}'.format(i))

#mcl.write(1,11)
#mcl.write(2,11)

print("---------------------------------------")
print("Mad City Labs Nanodrive Positions...")
print("---------------------------------------")
print("Axis 1 position: %.4f" %mcl.read(1))
print("Axis 2 position: %.4f" %mcl.read(2))
print("---------------------------------------\n")
mcl.close()

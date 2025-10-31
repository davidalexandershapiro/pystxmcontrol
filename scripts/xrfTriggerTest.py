from pystxmcontrol.drivers.xspress3 import xspress3
import sys
import numpy as np
from pystxmcontrol.drivers.mclController import mclController
import time
import matplotlib.pyplot as plt
import asyncio


async def main(args):
    dwell = int(args[1]) #ms
    xrf_pad = float(args[2]) #ms
    num = int(args[3]) #number of events
    mot_dwell = dwell + xrf_pad
    print(mot_dwell)

    mcl = mclController(simulation = False)
    mcl.initialize()
    mcl.setPositionTrigger()

    xrf = xspress3(simulation = False)
    xrf.config(dwell,count = 1, samples = num,trigger='EXT')
    xrf.set_filename('/cosmic-dtn/groups/cosmic/XRF-Data/2025/10/251008/testfile2.stxm')

    trajx = 50+40*np.sin(np.linspace(0,1,num)*2*np.pi*10)
    trajy = 50+40*np.cos(np.linspace(0,1, num)*2*np.pi*10)
    mcl.setup_xy(trajx, trajy, mot_dwell)

    xrf.ready()

    time.sleep(1)
    mcl.acquire_xy()
    await xrf.getLine()
    data = xrf.data



    plt.plot(xrf.energies,np.sum(data,axis = 1))
    plt.show()

if __name__ == '__main__':
    asyncio.run(main(sys.argv))




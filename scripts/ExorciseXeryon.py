from pystxmcontrol.controller.scripter import *
import time

##set up and execute basic STXM scan
meta = {"proposal": "BLS-000001", "experimenters":"Ditter, Shapiro", "nxFileVersion":2.1}
meta["xcenter"] = 0
meta["xrange"] = 5
meta["xpoints"] = 50
meta["ycenter"] = 0
meta["yrange"] = 5
meta["ypoints"] = 50
meta["energyStart"] = 605
meta["energyStop"] = 700
meta["energyPoints"] = 20
meta["dwell"] = 0.2
meta["spiral"] = False

#moveMotor("ZonePlateZ", -25000.)

steps = 20
for i in range(steps):
    #time.sleep(1)
    moveMotor("ZonePlateZ", -5000.)
    time.sleep(5)
    moveMotor("ZonePlateZ", -25000.)
    time.sleep(5)

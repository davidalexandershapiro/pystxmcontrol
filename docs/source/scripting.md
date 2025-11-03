# Scripting

```
from pystxmcontrol.controller.scripter import *

# ##set up and execute basic metadata required of all scans
meta = {"proposal": "", "experimenters":"", "nxFileVersion":3.0, "Sample": ""}
meta["xcenter"] = 0
meta["xrange"] = 5
meta["xpoints"] = 10
meta["ycenter"] = 0
meta["yrange"] = 5
meta["ypoints"] = 15
meta["energyStart"] = 700
meta["energyStop"] = 700
meta["energyPoints"] = 1
meta["dwell"] = 10
meta["spiral"] = False
meta["autofocus"] = True
meta["cmap"] = "viridis" #viridis', 'plasma', 'inferno', 'magma', 'cividis', 'Greys',
meta["daq list"] = ["default"]
meta["comment"] = "test scan"
```

```
#################################################################################################
##XMCD and 2 energies############################################################################
meta["energyStart"] = 700
meta["energyStop"] = 710
meta["energyPoints"] = 2
polarizations = [-1,1]
for p in polarizations:
    print("Moving polarization to %s" %p)
    move_motor("POLARIZATION",p)
    stxm_scan(meta)
```
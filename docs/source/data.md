# .stxm files

PYSTXMCONTROL uses the NXstxm file format described [here](https://manual.nexusformat.org/classes/applications/NXstxm.html).
There are some sublties of the PYSTXMCONTROL version of NXstxm driven by the needs of scanning with arbitrary trajectories.  For example, scanning with arbitrary trajectories necessitates measuring data (x-ray and position) along an arbitrary coordinate system which is calculated by the control system rather than requested by the user.  Though the user defined scan sets boundary conditions for the trajectories which are automatically defined.  Furthermore, as a convenience, PYSTXMCONTROL regrids the measured data into the coordinate system requested by the user.  Both the raw and regridded data are saved in the .stxm file.  The raw data are saved under *entry0/instrument* whereas the regridded data are saved under *entry0/default*.  In this case, *default* refers to the default detector defined in *daq.json*.  Additional detectors will have additional entries named accordingly.  The overall layout fo the file structure is shown below.

```{figure} images/pystxmcontrol_NXstxm.png
---
align: center
---
Graphical layout of the .stxm file which follows the NXstxm format
```

# ZMQ publishing
The dataHandler manages a publisher which publishes data using pyzmq.
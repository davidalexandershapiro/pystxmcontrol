# Configuring a scan
Scans are configured in the scans.json file.  A typical entry must include the following:
- index: used by the GUI to position the scan in the dropdown list
- x_motor: the motor used for the X coordinate.  This is needed by all scans.
- y_motor: the motor used for the Y coordinate.  This is needed by all scans.
- energy_motor: the motor used for the energy coordinate.  This is only needed for scans that require energy change
- type: options are "image", "line" and "point".  This defines how the data is managed by the GUI.
- driver: this is the name of the scan class used to execute the scan.  This is called by the controller.
- include_return: for trajectories, this tells the driver how to manage the end of the trajectory
- daq list: a comma separated list of DAQ names, for example, "default,ccd,xrf"
- mode: this is the scanning mode described below
- display: this tells the GUI whether to display the scan in its list
```
    "Image": {
      "index": 0,
      "x_motor": "SampleX",
      "y_motor": "SampleY",
      "energy_motor": "Energy",
      "type": "image",
      "driver": "linear_image",
      "include_return": false,
      "daq list": "default",
      "mode": "continuousLine",
      "display": true
    }
```

# The scan definition
Scans are defined as a python dictionary which have the structure below when saved to a JSON file.
```
"Image": {
            "driver": "linear_image",
            "mode": "continuousLine",
            "spiral": false,
            "scan_type": "Image",
            "tiled": false,
            "proposal": null,
            "experimenters": "",
            "sample": "",
            "comment": "",
            "nxFileVersion": "3",
            "x_motor": "SampleX",
            "y_motor": "SampleY",
            "defocus": false,
            "autofocus": true,
            "coarse_only": false,
            "daq list": [
                "default"
            ],
            "oversampling_factor": 1,
            "retract": true,
            "scanRegions": {
                "Region1": {
                    "xStart": -34.5,
                    "xStop": 34.5,
                    "xPoints": 50,
                    "yStart": -34.5,
                    "yStop": 34.5,
                    "yPoints": 50,
                    "xStep": 1.0,
                    "yStep": 1.0,
                    "xRange": 70.0,
                    "yRange": 70.0,
                    "xCenter": 0.0,
                    "yCenter": 0.0,
                    "zStart": 0.0,
                    "zStop": 0.0,
                    "zPoints": 0,
                    "zStep": 0,
                    "zRange": 0,
                    "zCenter": 0
                }
            },
            "energyRegions": {
                "EnergyRegion1": {
                    "dwell": 1.0,
                    "start": 600.0,
                    "stop": 601.0,
                    "step": 1.0,
                    "nEnergies": 1
                }
            },
            "energy": "Energy",
            "doubleExposure": false
        }
```
The means of scanning is defined largely by a scan "type" and a scan "mode".  The mode of the scan refers largely to how
the motors are actuated during the scan.  The possibilities are:
- continuousLine: linear or spiral trajectory actuated by the piezo controller.  The scan loop performs each trajectory independently.
- point: a start-stop raster scan for which each point is executed by the scan loop
- ptychographyGrid: a start-stop raster scan for which each point is executed by the scan loop

Meanwhile, the type of scan refers more to the collection of motors which are used.  The available types are:
- Image
- Spiral Image
- Ptychography Image
- Point Spectrum
- Line Spectrum
- Line Focus
- Single Motor
- Double Motor

Currently, the display in the GUI requries that the data falls on a rectangular grid.  

# executing a scan




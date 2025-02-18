# setting up a scan
Scans are defined as a python dictionary which have the following structure when saved to a JSON file
```
"Image": {
            "type": "Image",
            "proposal": "",
            "experimenters": "",
            "sample": "",
            "x": "SampleX",
            "y": "SampleY",
            "defocus": false,
            "serpentine": false,
            "mode": "continuousLine",
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
- continuousLine: linear trajectory actuated by the piezo controller.  The scan loop performs each line independently.
- rasterLine: a start-stop raster scan that is fully controlled by the piezo controller.  The scan loop performs each line independently.
- ptychographyGrid: a start-stop raster scan for which each point is executed by the scan loop

Meanwhile, the type of scan refers more to the collection of motors which are used.  The available types are:
- Image
- Ptychography Image
- Point Spectrum
- Line Spectrum
- Focus

Currently, the display in the GUI assumes that the data falls on a rectangular grid.  So, while it is entirely possible (and straight forward) to generate
scan code that does non-rectangular patterns, the display side needs to be refactor to account for this.  Coming soon...

# executing a scan




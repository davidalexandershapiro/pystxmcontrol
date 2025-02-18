from pystxmcontrol.controller.client import stxmClient
import time
bind_ip = '131.243.163.138'
a = stxmClient()
a.connect(bind_ip = bind_ip, bind_port = 9999)
a.connectMonitor()
a.getMotorConfig()

scan = {}
scan["x"] = "SampleX"
scan["y"] = "SampleY"
scan["type"] = "pointGrid"
scan["scanRegions"] = {}
scan["scanRegions"]["Region1"] = {}
scan["scanRegions"]["Region1"]["xStart"] = -1.0
scan["scanRegions"]["Region1"]["xStop"] = 1.0
scan["scanRegions"]["Region1"]["xPoints"] = 50
scan["scanRegions"]["Region1"]["yStart"] = -1.0
scan["scanRegions"]["Region1"]["yStop"] = 1.0
scan["scanRegions"]["Region1"]["yPoints"] = 50
scan["scanRegions"]["Region1"]["nPoints"] = 50
# scan["scanRegions"]["Region2"] = {}
# scan["scanRegions"]["Region2"]["xStart"] = 1.0
# scan["scanRegions"]["Region2"]["xStop"] = 3.0
# scan["scanRegions"]["Region2"]["xPoints"] = 50
# scan["scanRegions"]["Region2"]["yStart"] = 1.0
# scan["scanRegions"]["Region2"]["yStop"] = 3.0
# scan["scanRegions"]["Region2"]["yPoints"] = 50
# scan["scanRegions"]["Region2"]["nPoints"] = 50
scan["energyRegions"] = {}
scan["energyRegions"]["EnergyRegion1"] = {}
scan["energyRegions"]["EnergyRegion1"]["dwell"] = 0.1
scan["energyRegions"]["EnergyRegion1"]["start"] = 500
scan["energyRegions"]["EnergyRegion1"]["stop"] = 505
scan["energyRegions"]["EnergyRegion1"]["step"] = 5
scan["energyRegions"]["EnergyRegion1"]["nEnergies"] = 2
# scan["energyRegions"]["EnergyRegion2"] = {}
# scan["energyRegions"]["EnergyRegion2"]["dwell"] = 1
# scan["energyRegions"]["EnergyRegion2"]["start"] = 511
# scan["energyRegions"]["EnergyRegion2"]["stop"] = 512
# scan["energyRegions"]["EnergyRegion2"]["step"] = 1
# scan["energyRegions"]["EnergyRegion2"]["nEnergies"] = 2

a.doScan(scan)
time.sleep(5)
a.close()

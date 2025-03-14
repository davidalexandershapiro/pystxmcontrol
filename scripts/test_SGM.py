from pystxmcontrol.drivers.xpsController import *
from pystxmcontrol.drivers.xpsMotor import *
from pystxmcontrol.drivers.derivedEnergy_SGM import *


c1 = xpsController(address = '192.168.0.253', port = 5001)
c1.initialize()
g = xpsMotor(controller = c1)
g.connect(axis = "Monochromator.X")
g.config["offset"] = -420.105
g.config["minValue"] = -6000
g.config["maxValue"] = 6000

c2 = xpsController(address = '192.168.0.251', port = 5001)
c2.initialize()
zp_z = xpsMotor(controller = c2)
zp_z.connect(axis = "ZonePlateZ.Pos")
zp_z.config["offset"] = -4516.7615
zp_z.config["minValue"] = -6000
zp_z.config["maxValue"] = -1000
print(zp_z.getPos())

sgm = derivedEnergy_SGM()
sgm.config = {"monoArm": 466900,"grooveDensity": 300,"includedAngle": 172.8702, "simulation": False}
sgm.axes = {"axis1":g,"axis2":zp_z}
sgm.connect(axis = "Energy")
sgm.config["A0"] = 309.5
sgm.config["A1"] = 4.8778

theenergy = sgm.getPos()
#sgm.moveTo(320.)



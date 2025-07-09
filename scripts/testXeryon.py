from pystxmcontrol.drivers.xerMotor import xerMotor
from pystxmcontrol.drivers.xerController import xerController
import json
from time import sleep

#config = json.loads(open("../config/motorConfig.json").read())
#c = xerController(address = config["xeryon"]["controllerID"])
c = xerController(address = "/dev/ttyACM3")
c.initialize(simulation = False)

m = xerMotor(controller = c)
m.connect(axis = 'X')
print("Current xeryon position: %.4f" %m.getPos())
m.moveTo(m.getPos()-1000)
m.home()

print("Xeryon home position: %.4f" %m.getPos())
#m.moveTo(pos = -9000.)
sleep(5.)
print("New xeryon position: %.4f" %m.getPos())
m.stop()





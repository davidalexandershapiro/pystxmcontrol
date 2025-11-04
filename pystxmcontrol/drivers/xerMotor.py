from pystxmcontrol.controller.motor import motor
from pystxmcontrol.drivers.xerController import Stage
import time
import numpy as np

class xerMotor(motor):

    def __init__(self, controller = None):
    
        self.position = 1.3
        self.controller = controller
        self.config = {}
        self.config['controllerID'] = '/dev/ttyACM3'
        self.config["minValue"] = -15000.0
        self.config['maxValue'] = 15000.0
        self.config["offset"] = -10000
        self.config["units"] = 1000.
    
    def connect(self, axis = 'X'):
        self.simulation = self.controller.simulation
        self.axis = axis
        if not(self.simulation):
            self.lock = self.controller.lock
            self._axis = self.controller.addAxis(Stage.XLS_5, axis)
            self.controller.start()
            self.home()
            self.getPos()

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def getStatus(self, **kwargs):
        pass

    def moveBy(self, step = None):
        pos = self.getPos()
        if self.checkLimits(pos + step):
            if not(self.simulation):
                print("moving from ZP_Z %.4f to %.4f" %(self.position,self.position + step))
                self.moveTo(self.position + step)
            else:
                self.position = self.position + step
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos+step))

    def stop(self):
        return
        
    def moveTo(self, pos):
        print("Moving motor to %.4f in Xeryon units" %pos)
        if self.checkLimits(pos):
            if not(self.simulation):
                with self.lock:
                    self._axis.setDPOS((pos - self.config["offset"]) / self.config["units"])
                    self.position = self._axis.getEPOS() * self.config["units"] + self.config["offset"]
                    self._axis.sendCommand('STOP=0')
                    count = 1
                    #print('position requested: {}, position reached: {}'.format(pos,self.position))
                    while abs(pos - self.position) > 0.05 and count < 30:
                        #print('position requested: {}, position reached: {}'.format(pos,self.position))
                        #print("Tolerance not reached. Position error: %.4f" %abs(pos - self.position))
                        self._axis.setDPOS((pos - self.config["offset"]) / self.config["units"])
                        self._axis.sendCommand('STOP=0')
                        self.position = self._axis.getEPOS() * self.config["units"] + self.config["offset"]
                        time.sleep(0.01)
                        count += 1
                    if count == 6:
                        print("ZonePlateZ motor giving up.  Just couldn't get there. Sorry y'all.")
            else:
                self.position = pos
        else:
            print("Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))
        
    def getPos(self):
        if not(self.simulation):
            with self.lock:
                self.position = self._axis.getEPOS() * self.config["units"] + self.config["offset"]
            return self.position
        else:
            return self.position
        
    def home(self):
        if not(self.simulation):
            with self.lock:
                self._axis.findIndex()

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
            #self.home()
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
        #print("Moving motor to %.4f in Xeryon units" %pos)
        if self.checkLimits(pos):
            if not(self.simulation):
                with self.lock:
                    #self._axis.setDPOS((pos - 50 - self.config["offset"]) / self.config["units"])
                    self._axis.setDPOS((pos - self.config["offset"]) / self.config["units"])
                    self.position = self._axis.getEPOS() * self.config["units"] + self.config["offset"]
                    self.last_position = self.position
                    #self._axis.sendCommand('STOP=0')
                    count = 0
                    #give it a chance to get there first for large moves (> .1 mm).
                    if abs(self.position-pos)>100.:
                        time.sleep(5)
                        self.position = self._axis.getEPOS()*self.config["units"]+self.config["offset"]
                        while abs(self.position - self.last_position)>10:
                            time.sleep(0.25)
                            self.last_position = self.position
                            self.position = self._axis.getEPOS()*self.config["units"]+self.config["offset"]
                            #print('moving. Current position: {}'.format(self.position))
                    #print('position requested: {}, position reached: {}'.format(pos,self.position))
                    while abs(pos - self.position) > 0.05 and count < 3:
                        #print('position requested: {}, position reached: {}'.format(pos,self.position))
                        #print("Tolerance not reached. Position error: %.4f" %abs(pos - self.position))
                        self._axis.setDPOS((pos - self.config["offset"]) / self.config["units"])
                        self._axis.sendCommand('STOP=0')
                        time.sleep(0.05)
                        self.position = self._axis.getEPOS() * self.config["units"] + self.config["offset"]

                        #if abs(self.last_position-self.position) < 10:
                        count += 1
                        self.last_position = self._axis.getEPOS() * self.config["units"] + self.config["offset"]
                    while abs(pos - self.position) > 0.05 and count < 6:
                        self._axis.setDPOS((pos - 5 - self.config["offset"]) / self.config["units"])
                        time.sleep(0.05)
                        self._axis.setDPOS((pos - self.config["offset"]) / self.config["units"])
                        self._axis.sendCommand('STOP=0')
                        time.sleep(0.05)
                        self.position = self._axis.getEPOS() * self.config["units"] + self.config["offset"]
                        count += 1
                    if count == 11:
                        print("ZonePlateZ motor giving up.  Just couldn't get there. Sorry y'all.")
                    self._axis.sendCommand('STOP=0')
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

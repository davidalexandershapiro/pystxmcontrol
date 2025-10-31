# -*- coding: utf-8 -*-
from pystxmcontrol.controller.gate import gate
import serial
import time

class shutter(gate):

    def __init__(self, address):
        self._port = address
        self.status = False
        self.mode = "auto"
        self.dwell1 = 0
        self.dwell2 = 0
        self.shutterMASK = 1
        self.softGATE = 0

    def connect(self, simulation = False):
        self.simulation = simulation
        if not(self.simulation):
            self.ser = serial.Serial(self._port, 115200)
            time.sleep(0.1)
            print(self.ser.readline().decode())

    def setStatus(self,softGATE = None, shutterMASK = None):
        if softGATE == None:
            softGATE = str(self.softGATE)
        else:
            softGATE = str(softGATE)
        if self.mode == "auto":
            if shutterMASK == None:
                shutterMASK = '0'
            else:
                shutterMASK = str(shutterMASK)
        elif self.mode == "close":
            shutterMASK = '0'
        elif self.mode == "open":
            shutterMASK = '1'
            #softGATE = '1'
        if self.dwell1 < 1:
            dwell1Str = '000'
        elif self.dwell1 < 10:
            dwell1Str = '00'+str(self.dwell1)
        elif self.dwell1 < 100:
            dwell1Str = '0'+str(self.dwell1)
        elif self.dwell1 < 1000:
            dwell1Str = str(self.dwell1)
        else:
            dwell1Str = '999'
        if self.dwell2 < 1:
            dwell2Str = '000'
        elif self.dwell2 < 10:
            dwell2Str = '00'+str(self.dwell2)
        elif self.dwell2 < 100:
            dwell2Str = '0'+str(self.dwell2)
        elif self.dwell2 < 1000:
            dwell2Str = str(self.dwell2)
        else:
            dwell2Str = '999'
        statusStr = dwell1Str + ',' + dwell2Str + ',' + shutterMASK + ',' + softGATE
        if not(self.simulation):
            self.ser.write(statusStr.encode())


    def getStatus(self):
        if not(self.simulation):
            return True #self.ser.readline().decode()
        else:
            return self.status
    #
    # def setDwell(self, dwell):
    #     if not(self.simulation):
    #         self.ser.write(str(dwell).encode())

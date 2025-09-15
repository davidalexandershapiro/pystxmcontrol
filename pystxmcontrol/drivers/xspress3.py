import numpy as np
from pystxmcontrol.controller.daq import daq
from epics import caget, caput, cainfo
from numpy.random import poisson
import time

class xspress3(daq):

    def __init__(self, address = 'XSP3_4Chan',simulation = False):

        self.address = address
        self.simulation = simulation
        self.det_prefix = ':det1:'
        self.MCA_prefix = ':MCA1:'

        #defaults for simulation mode
        self.dwell = 50 #ms
        self.count = 1
        self.samples = 1
        #Default is 4096 bins, 10 eV per bin.
        self.nbins = 4096

    def start(self):
        pass

    def config(self, dwell = 50, count  = 1, samples = 1,trigger = 'BUS', output = 'OFF'):
        # Trying to make this the same inputs as the keysight counter so that we can feed it the same thing.

        self.dwell = dwell
        self.count = count
        self.samples = samples
        if not self.simulation:
            # Assign dwell in seconds. Only matters if trigger is bus.
            caput(self.address+self.det_prefix+'AcquireTime', dwell/1000)
            # Assign total number of images as count*samples
            caput(self.address+self.det_prefix+'NumImages',count*samples)
            # Assign the trigger state: BUS is internal. EXT is external (probably not correct there is another option)
            if trigger == 'BUS':
                caput(self.address+self.det_prefix+'TriggerMode', 1) #Internal trigger
            elif trigger == 'EXT':
                caput(self.address+self.det_prefix+'TriggerMode', 3) #External trigger
                #Note: This trigger expects it to stay high for the duration of the measurement then goes low when stopped.
                #This may be an output of the keysight that we can hook into.

        #Not using output there yet but keeping it so the arguments are the same.

    def getPoint(self):
        if self.simulation:
            #1e7 total counts/second across nbins
            time.sleep(self.dwell/1000)
            data = poisson(1e7/self.nbins*self.dwell/1000,(self.nbins,))
            return(data)
        else:
            #Get old configuration
            oldTrigger = caget(self.address+self.det_prefix+'TriggerMode_RBV')
            #Configure to take a point
            #There may be a better way to do this by using the acquire time.
            #Will have to consider dead time.
            caput(self.address+self.det_prefix+'TriggerMode', 2)
            caput(self.address+self.det_prefix+'Acquire', 1)
            time.sleep(self.dwell/1000)
            caput(self.address+self.det_prefix+'Acquire',0)
            #How to read????
            data = caget(self.addres+self.MCA_prefix+'ArrayData')
            #set back to old trigger mode
            caput(self.address+self.det_prefix+'TriggerMode',oldTrigger)
            return(data)

    def getLine(self):
        if self.simulation:
            #1e7 total counts/second across nbins, collection of count*samples points
            time.sleep(self.dwell/1000*self.count*self.samples)
            data = poisson(1e7/self.nbins*self.dwell/1000,(self.count*self.samples,self.nbins))
            return(data)
        else:
            # Should already be configured to take a number of samples. Else the default is 1.
            caput(self.address+self.det_prefix+'Acquire',1)
            #How to tell when it's done? We wait for idle maybe?
            while caget(self.address+self.det_prefix+'DetectorState_RBV') != 'Idle':
                #print(caget(self.address+self.det_prefix+'DetectorState_RBV'))
                pass
            #How to read data? I am missing some PVs.
            data = caget(self.address+self.MCA_prefix+'ArrayData')

            #Can we update data as it is collected?

            #How do we put the gate in here? Look at keysight53230A.py probably.

            return(data)
import numpy as np
from pystxmcontrol.controller.daq import daq
from epics import caget, caput, cainfo
from numpy.random import poisson
import time
import asyncio
import os
import h5py

class xspress3(daq):

    def __init__(self, address = 'XSP3_2Chan',simulation = False):

        self.address = address
        self.simulation = simulation
        self.det_prefix = ':det1:'
        self.MCA_prefix = ':MCA1:'
        self.hdf_prefix = ':HDF1:'

        #defaults for simulation mode
        self.dwell = 50 #ms
        self.count = 1
        self.samples = 1
        #Default is 4096 bins, 10 eV per bin.
        self.nbins = 4096
        self._bin_ev_delta = 10.0
        self._bottom_bin = 0.0 #this is just a place holder
        self.all_energies = np.linspace(self._bottom_bin, self._bottom_bin + self.nbins * self._bin_ev_delta, self.nbins)
        self.meta = {"ndim": 1, "type": "spectrum", "name": "XSPRESS3", "x label": "Energy", "max energy": 3000}
        self.xrf_filename = None

    def start(self):
        pass

    def stop(self):
        pass

    def config(self, dwell = (1,0), count  = 1, samples = 1,trigger = 'BUS', output = 'OFF'):
        # Trying to make this the same inputs as the keysight counter so that we can feed it the same thing.
        if isinstance(dwell, list):
            self.dwell,self.dwell2 = dwell
        else:
            self.dwell = dwell
        self._idx = max(np.where(self.all_energies <= self.meta["max energy"])[0])
        self.energies = self.all_energies[:self._idx]
        self.meta["x"] = self.energies
        self.count = count
        self.samples = samples
        if not self.simulation:
            # Assign dwell in seconds. Only matters if trigger is bus.
            caput(self.address+self.det_prefix+'AcquireTime', dwell/1000)
            caput(self.address+self.det_prefix+'NumImages',self.count*self.samples)
            #caput(self.address+self.det_prefix+'Acquire', 1)
            # Assign total number of images as count*samples
            #caput(self.address+self.det_prefix+'NumImages',count*samples)
            # Assign the trigger state: BUS is internal. EXT is external (probably not correct there is another option)
            if trigger == 'BUS':
                caput(self.address+self.det_prefix+'TriggerMode', 1) #Internal trigger
            elif trigger == 'EXT':
                caput(self.address+self.det_prefix+'TriggerMode', 8) #External trigger
                #This triggers on the pulse
            self.ready()

            pass
        #Not using output there yet but keeping it so the arguments are the same.

    async def getPoint(self):
        if self.simulation:
            #but this is a spectrum so we need to return some energy information.  I assume that is done below
            #but I don't yet know the format of the data.  For now I"ll return it as two lists

            #1e7 total counts/second across nbins
            await asyncio.sleep(self.dwell/1000)
            self.data = poisson(1e7/self.nbins*self.dwell/1000,(self.nbins,))[:self._idx]
            self.data = np.reshape(self.data,(self.data.size,1))
            return self.data
        else:
            #this just polls the detector and collects data. Should be automatically collecting after configured.
            #caput(self.address+self.det_prefix+'NumImages',1)
            #Get old configuration
            #oldTrigger = caget(self.address+self.det_prefix+'TriggerMode_RBV')

            #Configure to take a point
            #There may be a better way to do this by using the acquire time.
            #Will have to consider dead time.
            #caput(self.address+self.det_prefix+'Acquire', 1)
            #status = True
            #while status:
            #    array_counter = caget(self.address+self.det_prefix+'ArrayCounter_RBV')
            #    status = not bool(array_counter)
            #    print(array_counter)
            #    time.sleep(self.dwell/1000.)
            #caput(self.address+self.det_prefix+'Acquire',0)
            #How to read????
            self.data = caget(self.address+self.MCA_prefix+'ArrayData')[:self._idx]
            #set back to old trigger mode
            if caget(self.address+self.det_prefix+'ArrayCounter_RBV')>self.samples*self.count-100:
                self.ready()
            #caput(self.address+self.det_prefix+'TriggerMode',oldTrigger)
            return self.data
    def ready(self):
        if not self.simulation:
            # Stop saving data to file (unnecessary?)
            caput(self.address+self.hdf_prefix+'Capture', 0)
            time.sleep(0.1)
            # Stop any previous acquisition
            caput(self.address+self.det_prefix+'Acquire',0)
            time.sleep(0.1)
            # Erase previous data (should be saved to file)
            caput(self.address+self.det_prefix+'ERASE',1)
            time.sleep(0.1)
            # Start saving data to file (will overwrite previous unless set_filename has been run)
            caput(self.address+self.hdf_prefix+'Capture', 1)
            time.sleep(0.1)
            # Start acquisition
            caput(self.address+self.det_prefix+'Acquire',1)
            time.sleep(0.1)
            # To do: make this better. Check we are in the right state.
            while caget(self.address+self.det_prefix+'DetectorState_RBV') != 1:
                time.sleep(0.1)

    def set_filename(self, stxm_filename):
        if not self.simulation:
            #input comes from controller.getScanID which is the stxm filename
            directory = os.path.dirname(stxm_filename)
            #new filename should be same as .stxm file except with _xrf in it.
            xrf_filename = os.path.basename(stxm_filename).replace('.stxm','_xrf')
            self.xrf_file = os.path.join(directory, xrf_filename+'.stxm')
            #set directory and filename
            caput(self.address+self.hdf_prefix+'FilePath',directory)
            caput(self.address+self.hdf_prefix+'FileName',xrf_filename)
            #disable automatic numbering as this is set by the filename
            caput(self.address+self.hdf_prefix+'AutoIncrement', 0)
            caput(self.address+self.hdf_prefix+'FileTemplate', '%s%s.stxm')



    async def getLine(self):
        if self.simulation:
            #1e7 total counts/second across nbins, collection of count*samples points
            await asyncio.sleep(self.dwell/1000*self.count*self.samples)
            self.data = poisson(1e7/self.nbins*self.dwell/1000,(self.nbins,self.count*self.samples))[:self._idx,:]
            return self.data
        else:
            # Should already be configured to take a number of samples. Else the default is 1.
            # How to tell when it's done? We wait for idle maybe? Probably a good idea to have
            # a timeout in case triggers are missed?
            while caget(self.address+self.det_prefix+'DetectorState_RBV')!= 0 and \
                    caget(self.address+self.det_prefix+'ArrayCounter_RBV')< self.count*self.samples:
                await asyncio.sleep(0.1)


            #How to read data? Look at h5 file. Should I try this a bunch of times until it succeeds? I dunno.
            #print('attempting to open {}'.format(self.xrf_file))
            while True:
                try:
                    #print('attempting to open file')
                    with h5py.File(self.xrf_file, 'r') as xrf_h5:
                        all_data = xrf_h5['entry/data/data'][()][:, 0].T  # indexing for only detector 1.
                    break
                except:
                    await asyncio.sleep(0.1)



            #How do we put the gate in here? Look at keysight53230A.py probably. Do we need this?

            self.data = all_data[:self._idx]
            #print(self.data.shape)

            return self.data

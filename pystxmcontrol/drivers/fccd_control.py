import time
import numpy as np
from pystxmcontrol.controller.daq import daq
from numpy.random import poisson
import zmq
from pystxmcontrol.drivers.cin import CIN
from pystxmcontrol.drivers.fccd import FCCD
import asyncio
import zmq.asyncio as zmq_asyncio

class fccd_control(daq):
    def __init__(self, address = "131.243.73.85", port = 49206, simulation = False, shape = (1040,1152)):
        self.address = address
        self.port = port
        self.addr = 'tcp://%s' % (self.address + ':' + str(self.port))
        self.simulation = simulation
        self.timeout = 1
        self.framenum = 0
        self.num_rows = shape[0] // 2
        self.num_adcs = shape[1] // 6
        self.CCD = FCCD(nrows = self.num_rows)
        self.cin = CIN()
        if not(self.simulation):
            pass
        self.meta = {"ndim": 2, "type": "image", "name": "FCCD", "x label": "X Position", "y label": "Y Position",\
                     "oversampling_factor": 1}

    def start(self):
        self.fbuffer = []
        if not (self.simulation):
            context = zmq_asyncio.Context()
            self.frame_socket = context.socket(zmq.SUB)
            self.frame_socket.setsockopt(zmq.SUBSCRIBE, b'')
            self.frame_socket.setsockopt(zmq.MAXMSGSIZE,2**34)
            self.frame_socket.set_hwm(10000)
            self.frame_socket.connect(self.addr)
            print(f"[fccd control] Subscribed to {self.addr}")

    def stop(self):
        if not (self.simulation):
            self.frame_socket.disconnect(self.addr)

    def set_dwell(self, dwell):
        self.dwell = dwell

    def init(self):
        """
        This function will arm the device to wait for an external trigger.  This is not needed for the FCCD but is needed
        by ANDOR, for example.
        """
        pass

    def config(self, dwell, exposure_mode = 0, count  = 1, samples = 1, trigger = 'BUS'):
        if isinstance(dwell,list):
            self.dwell,self.dwell2 = dwell
        else:
            self.dwell = dwell
            self.dwell2 = 0.
        self.doubleExposureMode = exposure_mode
        if self.simulation:
            pass
        else:
            #set exposure times
            self.cin.setExpTime(self.dwell)
            self.cin.setAltExpTime(self.dwell2)

            #set double exposure mode
            if self.doubleExposureMode:
                self.cin.set_register("8050", "8000", 1)
            else:
                self.cin.set_register("8050", "0000", 1)

            #reset counter
            self.cin.set_register("8001", "0106", 0)
            time.sleep(0.002)

    async def getPoint(self):
        if self.simulation:
            self.framenum += 1
            self.data = 2. * np.random.random((1040,1152))
            return self.data
        else:
            self.data = await self.zmq_receive()
            return self.data

    def getLine(self):
        pass

    async def zmq_receive(self):
        if self.timeout == 0:
            number, frame = self.frame_socket.recv_multipart()  # blocking
            # Could have been stopped in the meantime, so we need to
            # discard this one
            return self.frame_to_image((number,frame))
        else:
            # This could probablu have been done cleaner with a Poller
            # But I rather have the GIL released with sleep instead
            # of polling all the time.
            slp = 0.01 #self.timeout / 1000.
            frame_received = False
            t0 = time.time()
            while not frame_received:
                t1 = time.time() - t0
                if t1 < self.timeout:
                    try:
                        #print("Waiting for frame...")
                        #number, frame = self.frame_socket.recv_multipart(flags=zmq.NOBLOCK)  # not blocking
                        frame = await self.frame_socket.recv(flags=zmq.NOBLOCK)
                        print(frame)
                        frame_received = True
                    except zmq.ZMQError as e:
                        time.sleep(slp)
                        continue
                    else:
                        return self.frame_to_image((frame))
                else:
                    return None


    def frame_to_image(self, frame):
        print("Assembling frame...")
        buf = frame
        # self.framename = num
        npbuf = np.frombuffer(buf, '<u2')
        npbuf = npbuf.reshape((12 * self.num_rows, self.num_adcs))
        image = self.CCD.assemble2(npbuf.astype(np.uint16))
        return image

import time
from pystxmcontrol.controller.daq import daq
from numpy.random import poisson
from numpy import array
import asyncio
import zmq
import numpy as np
import json

def get_array(bytesequence, dtype, shape_y, shape_x, byteorder, order):
    dt = np.dtype(dtype)
    dt = dt.newbyteorder(byteorder)
    array = np.frombuffer(bytesequence, dtype=dt)
    array = array.reshape((shape_y, shape_x), order=order)

    return array

def recv_rec(sock, flags=0):
    KEY_SHAPE_Y = 'shape_y'
    KEY_SHAPE_X = 'shape_x'
    KEY_DTYPE = 'dtype'
    KEY_BYTEORDER = 'byteorder'
    KEY_ORDER = 'order'
    KEY_IDENT = 'ident'
    KEY_INDEX = 'index'
    KEY_POSY = 'posy'
    KEY_POSX = 'posx'
    KEY_OBJ_PIXELSIZE_Y = 'obj_pixelsize_y'
    KEY_OBJ_PIXELSIZE_X = 'obj_pixelsize_x'

    topic, metadata_bytes, rec_bytes = sock.recv_multipart(flags)

    metadata = json.loads(metadata_bytes.decode())

    obj_pixelsize_y = metadata[KEY_OBJ_PIXELSIZE_Y]
    obj_pixelsize_x = metadata[KEY_OBJ_PIXELSIZE_X]

    rec = get_array(
        rec_bytes,
        metadata[KEY_DTYPE],
        metadata[KEY_SHAPE_Y],
        metadata[KEY_SHAPE_X],
        metadata[KEY_BYTEORDER],
        metadata[KEY_ORDER]
    )

    return rec, obj_pixelsize_y, obj_pixelsize_x, metadata

class zmq_frame_reader(daq):
    def __init__(self, address = "127.0.0.1", port = 49206, simulation = False):
        self.address = f"tcp://{address}:{port}"
        self.simulation = simulation
        self.meta = {"crop": 256, "gate": False}

    def start(self):
        if not(self.simulation):
            context = zmq.Context()
            self.sock = context.socket(zmq.SUB)
            self.sock.setsockopt(zmq.SUBSCRIBE, b'')
            self.sock.set_hwm(2000)
            self.sock.connect(self.address)

    def stop(self):
        if not (self.simulation):
            self.sock.close()
            
    def set_dwell(self, dwell):
        pass

    def config(self, dwell, exposure_mode = 0, count  = 1, samples = 1, trigger = 'BUS', crop = 256):
        self.crop = crop

    def initLine(self):
        pass

    async def getLine(self):
        pass

    async def getPoint(self):
        crop = self.meta["crop"]
        if crop < 1:
            crop = 1
        if self.simulation:
            await asyncio.sleep(self.dwell / 1000.)
            self.data = array([poisson(1e7 * self.dwell / 1000.)])
            self.data = 2. * np.random.random((1040,1152))
            self.display_data = self.data.copy()
            return self.data
        else:
            try:
                obj, px_size_y, px_size_x, metadata = recv_rec(self.sock, flags=zmq.NOBLOCK)
                self.data = np.abs(obj[crop:-crop,crop:-crop])
            except:
                self.data = None
            return self.data



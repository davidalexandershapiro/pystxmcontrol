from PySide6 import QtCore
import numpy as np
import threading, os
from pystxmcontrol.drivers.fccd import FCCD
import sys, time, zmq, json

CCDPRESENT = True
BASEPATH = sys.prefix
MAINCONFIGFILE = os.path.join(BASEPATH,'pystxmcontrol_cfg/main.json')

class ccd_monitor(QtCore.QThread):

    framedata = QtCore.Signal(np.ndarray)

    def __init__(self, rows=520, roi=480, cols=1152, sub_address="131.243.73.179:49206", pub_address = "131.243.73.225:49207", simulation = True):
        self.sub_address = sub_address
        self.pub_address = pub_address
        QtCore.QThread.__init__(self)
        self.number = ''
        self.frame = None
        self.CCD = FCCD(nrows=roi + 10)
        self.rows = rows
        self.roi = roi
        self.cols = cols
        self.simulation = simulation

    def __del__(self):
        self.wait()

    def run(self):

        if self.simulation:
            while True:
                self.framedata.emit(np.random.random((960,960)))
                time.sleep(0.1)
        else:
            #subscribe to the frameserver
            addr = 'tcp://%s' % self.sub_address
            context = zmq.Context()
            frame_socket = context.socket(zmq.SUB)
            frame_socket.setsockopt(zmq.SUBSCRIBE, b'')
            frame_socket.set_hwm(2000)
            frame_socket.connect(addr)

            row_bytes = self.cols * 4
            i = 0.
            while True:
                self.number, buf = frame_socket.recv_multipart()  # blocking
                # npbuf = np.frombuffer(buf[2304 * (975-self.roi -10) * 2: 2304 * 975 *2],'<u2')
                # pedestal = np.frombuffer(buf[2304 * 100 * 2: 2304 * 300 *2],'<u2')
                # print npbuf.size / 2304
                npbuf = np.frombuffer(buf[row_bytes * 5: row_bytes * (self.roi + 15)], '<u2')
                pedestal = np.frombuffer(buf[row_bytes * 5: row_bytes * 55], '<u2')
                npbuf = npbuf.reshape((npbuf.size // self.CCD._nbmux, self.CCD._nbmux)).astype('float')
                pedestal = pedestal.reshape((pedestal.size // self.CCD._nbmux, self.CCD._nbmux)).astype('float')
                if i == 0.:
                    bg = npbuf.copy()
                assembled = self.CCD.assemble_nomask(npbuf - bg)
                self.frame = assembled  
                #self.frame[0:480,840:] = 0.
                self.frame[self.frame < 1] = 1.
                self.framedata.emit(np.log10(self.frame.T/400.))
                i += 1.

            frame_socket.disconnect(addr)

class rpi_monitor(QtCore.QThread):

    rpidata = QtCore.Signal(np.ndarray)

    def __init__(self, rows=520, roi=480, cols=1152, sub_address="131.243.73.205:37014", pub_address = "131.243.73.225:49207", simulation = False):
        self.sub_address = sub_address
        self.pub_address = pub_address
        QtCore.QThread.__init__(self)
        self.number = ''
        self.frame = None
        self.CCD = FCCD(nrows=roi + 10)
        self.rows = rows
        self.roi = roi
        self.cols = cols
        self.simulation = simulation

    def __del__(self):
        self.wait()

    def run(self):

        #subscribe to the frameserver
        addr = 'tcp://%s' % self.sub_address
        context = zmq.Context()
        frame_socket = context.socket(zmq.SUB)
        frame_socket.setsockopt(zmq.SUBSCRIBE, b'')
        frame_socket.set_hwm(2000)
        frame_socket.connect(addr)

        while True:
            obj = frame_socket.recv_pyobj()
            if obj is not None and obj['event'] == 'frame':
                self.rpidata.emit(np.abs(obj['data']).transpose()) # For some reason, it displays transposed, so I need to transpose it here
            
        frame_socket.disconnect(addr)

class ptycho_monitor(QtCore.QThread):

    ptychoData = QtCore.Signal(object)
    
    def __init__(self, sub_address="ptycho2.lbl.gov:37015", pub_address="131.243.73.225:49207", cropsize = 128, simulation=False):
        self.sub_address, self.sub_port = sub_address.split(':')
        self.pub_address, self.pub_port = pub_address.split(':')
        QtCore.QThread.__init__(self)
        self.number = ''
        self.frame = None
        self.simulation = simulation
        self.cropsize = cropsize
        try:
            from cosmicstreams.sockets.Rec import RecSocketSub
            self.reco_socket = RecSocketSub(self.sub_address)
        except:
            pass
        
    def __del__(self):
        self.wait()
        
    def run(self):
        while True:
            obj, px_size_y, px_size_x, metadata = self.reco_socket.recv_rec()

            if obj is not None:
                self.ptychoData.emit((abs(obj[self.cropsize:-self.cropsize,self.cropsize:-self.cropsize]).T,px_size_x,px_size_y))

class stxm_monitor(QtCore.QThread):

    scan_data  = QtCore.Signal(object) #emit message dict with data and descriptors
    elapsed_time = QtCore.Signal(np.float16)
    scan_done = QtCore.Signal()

    def __init__(self, ip, port):
        QtCore.QThread.__init__(self)
        self.stxm_data_ip = ip
        self.stxm_data_port = port
        # self.dataSocket = mySocket(self.bind_ip, self.bind_port, client = True)
        # self.image = None
        # self.spectrum = None
        self.monitor = False

        # subscribe to the frameserver
        stxm_data_addr = 'tcp://%s:%s' %(self.stxm_data_ip, self.stxm_data_port)
        context = zmq.Context()
        self.stxm_data_socket = context.socket(zmq.SUB)
        self.stxm_data_socket.setsockopt(zmq.SUBSCRIBE, b'')
        self.stxm_data_socket.connect(stxm_data_addr)

    def get_data(self):
        return self.stxm_data_socket.recv_pyobj()
        
    def run(self):
        self.monitor = True
        while True:
            if self.monitor:
                self.scan_data.emit(self.get_data())
            else:
                print("Closing monitor thread.")
                return

class stxm_client(QtCore.QThread):

    serverMessage = QtCore.Signal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.scan = None
        self.listen = False
        self.lock = threading.Lock()
        self.main_config = json.loads(open(MAINCONFIGFILE).read())
        self.server_address = self.main_config["server"]["host"]
        self.command_port = self.main_config["server"]["command_port"]
        self.data_port = self.main_config["server"]["stxm_data_port"]

        context = zmq.Context()
        self.command_sock = context.socket(zmq.REQ)
        self.command_sock.connect("tcp://%s:%s" % (self.main_config["server"]["host"], self.main_config["server"]["command_port"]))

        self.monitor = stxm_monitor(self.server_address, self.data_port)
        self.data_thread = threading.Thread(target=self.monitor.run, args=())
        self.data_thread.daemon = True
        self.data_thread.start()
        self.get_config()

        try:
            self.ccd = ccd_monitor(simulation = not(CCDPRESENT))
            self.ccd.start()
        except:
            print("Cannot start CCD monitor")
        try:
            self.rpi = rpi_monitor(simulation = not(CCDPRESENT))
            self.rpi.start()
        except:
            print("Cannot start RPI monitor")
        try:
            self.ptycho = ptycho_monitor(simulation = not(CCDPRESENT))
            self.ptycho.start()
        except:
            print("Cannot start PTYCHO monitor")

    def get_status(self):
        message = {"command": "getStatus"}
        return self.send_message(message)

    def closeMonitor(self):
        self.monitor.close()

    def disconnect(self):
        print("Disconnecting client from STXM server")
        message = {"command": "disconnect"}
        self.command_sock.send_pyobj(message)
        self.monitor.monitor = False
        self.data_thread.join()
        
    def send_message(self,message):
        with self.lock:
            self.command_sock.send_pyobj(message)
            response = self.command_sock.recv_pyobj()
            return response

    def get_config(self):
        message = {"command": "get_config"}
        response = self.send_message(message)
        self.motorInfo, self.scanConfig, self.currentMotorPositions, self.daqConfig = response['data']

    def write_config(self):
        with open(MAINCONFIGFILE, 'w') as fp:
            json.dump(self.main_config, fp, indent=4)

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
        self.monitor = True

    def run(self):
        if self.simulation:
            while self.monitor:
                self.framedata.emit(np.random.random((960,960)))
                time.sleep(0.1)
            print("Exiting ccd monitor")
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
            while self.monitor:
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
            return

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
        self.monitor = True

    # def __del__(self):
    #     self.wait()

    def run(self):
        print("started rpi monitor loop")
        #subscribe to the frameserver
        addr = 'tcp://%s' % self.sub_address
        context = zmq.Context()
        frame_socket = context.socket(zmq.SUB)
        frame_socket.setsockopt(zmq.SUBSCRIBE, b'')
        frame_socket.set_hwm(2000)
        frame_socket.connect(addr)

        if self.monitor:
            if not(self.simulation):
                obj = frame_socket.recv_pyobj()
                if obj is not None and obj['event'] == 'frame':
                    self.rpidata.emit(np.abs(obj['data']).transpose()) # For some reason, it displays transposed, so I need to transpose it here
        else:
            frame_socket.disconnect(addr)
            return

class ptycho_monitor(QtCore.QThread):

    ptychoData = QtCore.Signal(object)
    
    def __init__(self, sub_address="ptycho2.lbl.gov:37015", pub_address="131.243.73.225:49207", cropsize = 128, simulation=False):
        self.sub_address, self.sub_port = sub_address.split(':')
        self.pub_address, self.pub_port = pub_address.split(':')
        QtCore.QThread.__init__(self)
        self.number = ''
        self.frame = None
        self.reco_socket = None
        self.simulation = simulation
        self.cropsize = cropsize
        self.monitor = True
        try:
            from cosmicstreams.sockets.Rec import RecSocketSub
            self.reco_socket = RecSocketSub(self.sub_address)
        except:
            print("Could not connect ptychography socket")
        
    # def __del__(self):
    #     self.wait()
        
    def run(self):
        if self.reco_socket is None:
            return
        if self.monitor:
            obj, px_size_y, px_size_x, metadata = self.reco_socket.recv_rec()
            if obj is not None:
                self.ptychoData.emit((abs(obj[self.cropsize:-self.cropsize,self.cropsize:-self.cropsize]).T,px_size_x,px_size_y))
        else:
            return

class stxm_monitor(QtCore.QThread):

    scan_data  = QtCore.Signal(object) #emit message dict with data and descriptors

    def __init__(self, ip, port):
        QtCore.QThread.__init__(self)
        self.stxm_data_ip = ip
        self.stxm_data_port = port
        self.monitor = True

        # subscribe to the frameserver
        stxm_data_addr = 'tcp://%s:%s' %(self.stxm_data_ip, self.stxm_data_port)
        context = zmq.Context()
        self.stxm_data_socket = context.socket(zmq.SUB)
        self.stxm_data_socket.setsockopt(zmq.SUBSCRIBE, b'')
        self.stxm_data_socket.connect(stxm_data_addr)

    def get_data(self):
        return self.stxm_data_socket.recv_pyobj()
        
    def run(self):
        while True:
            if self.monitor:
                self.scan_data.emit(self.get_data())
            else:
                return

class stxm_client(QtCore.QThread):

    serverMessage = QtCore.Signal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.scan = None
        self.listen = False
        self.lock = threading.Lock()
        self.client_config = json.loads(open(MAINCONFIGFILE).read())
        self.server_address = self.client_config["server"]["host"]
        self.command_port = self.client_config["server"]["command_port"]
        self.data_port = self.client_config["server"]["stxm_data_port"]
        self.monitor_threads = []
        self.context = zmq.Context()

        self.connect_to_server(self.server_address,self.command_port,self.data_port)
        #self.start_monitors(self.server_address,self.data_port)

    def connect_to_server(self, address, command_port = None, data_port = None):
        self.server_address = address
        if command_port is not None:
            self.command_port = command_port
        if data_port is not None:
            self.data_port = data_port
        try:
            self.command_sock = self.context.socket(zmq.REQ)
            self.command_sock.connect("tcp://%s:%s" % (address, command_port))
            self.get_config()
            self.start_monitors(address,data_port)
        except:
            return False
        else:
            return True

    def close_monitors(self):
        #check whether the monitor is running and start if needed
        for monitor in self.monitor_threads:
            if monitor.isRunning():
                monitor.monitor = False
                monitor.wait()

    def start_monitors(self, address, data_port):
        self.close_monitors()
        self.monitor = stxm_monitor(address, data_port)
        self.monitor.start()
        self.monitor_threads = []
        self.monitor_threads.append(self.monitor)

    def get_status(self):
        message = {"command": "getStatus"}
        return self.send_message(message)

    def closeMonitor(self):
        self.monitor.close()

    def disconnect(self):
        message = {"command": "disconnect"}
        self.command_sock.send_pyobj(message)
        self.close_monitors()
        
    def send_message(self,message):
        with self.lock:
            self.command_sock.send_pyobj(message)
            response = self.command_sock.recv_pyobj()
            return response

    def get_config(self):
        self.client_config = json.loads(open(MAINCONFIGFILE).read())
        message = {"command": "get_config"}
        response = self.send_message(message)
        self.motorInfo, self.scanConfig, self.currentMotorPositions, self.daqConfig, self.main_config = response['data']

    def write_config(self):
        with open(MAINCONFIGFILE, 'w') as fp:
            json.dump(self.main_config, fp, indent=4)

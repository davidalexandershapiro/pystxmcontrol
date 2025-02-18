from PySide6 import QtWidgets, QtCore, QtGui
import zmq
from numpy import ndarray
class zmqFrameMonitor(QtCore.QThread):

    zmqFrameData = QtCore.Signal(ndarray)
    def __init__(self, sub_address="ptycho2.lbl.gov:37015", pub_address="131.243.73.225:49207", cropsize = 256, cosmic = False, simulation=False):
        self.sub_address, self.sub_port = sub_address.split(':')
        self.pub_address, self.pub_port = pub_address.split(':')
        QtCore.QThread.__init__(self)
        self.number = ''
        self.frame = None
        self.simulation = simulation
        self.cropsize = 256
        self.cosmic = cosmic

    def __del__(self):
        self.wait()
    def run(self):
        if not(self.simulation):
            if self.cosmic:
                from cosmicstreams.sockets.Rec import RecSocketSub
                reco_socket = RecSocketSub(self.sub_address)
            else:
                addr = 'tcp://%s' % (self.sub_address + ':' + self.sub_port)
                print("Connecting ZMQ monitor to address %s" %addr)
                context = zmq.Context()
                frame_socket = context.socket(zmq.SUB)
                frame_socket.setsockopt(zmq.SUBSCRIBE, b'')
                frame_socket.set_hwm(2000)
                frame_socket.connect(addr)

            while True:
                if self.cosmic:
                    obj, px_size_y, px_size_x, metadata = reco_socket.recv_rec()
                    if obj is not None:
                        self.zmqFrameData.emit(abs(obj[self.cropsize:-self.cropsize,self.cropsize:-self.cropsize]).transpose())
                else:
                    obj = frame_socket.recv_pyobj()
                    if obj is not None:
                        print("Received frame....")
                        self.zmqFrameData.emit(abs(obj['data']).transpose())

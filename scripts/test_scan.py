import os, asyncio, threading, json, sys
from pystxmcontrol.controller.controller import controller
from pystxmcontrol.controller.scans import derived_ptychography_image
BASEPATH = sys.prefix
config_file = os.path.join(BASEPATH,'pystxmcontrol_cfg/main.json')
scan_type = "Ptychography Image"
scan = json.loads(open(config_file).read())["lastScan"][scan_type]

def monitor():
    # subscribe to the frameserver
    stxm_data_addr = 'tcp://127.0.0.1:9998'
    context = zmq.Context()
    stxm_data_socket = context.socket(zmq.SUB)
    stxm_data_socket.setsockopt(zmq.SUBSCRIBE, b'')
    stxm_data_socket.connect(stxm_data_addr)

    while True:
        print(stxm_data_socket.recv_pyobj)

def test_scan(scan):
    c = controller(True)
    c.getScanID(ptychography=True)
    c.scan(scan)

print(scan)
test_scan(scan)








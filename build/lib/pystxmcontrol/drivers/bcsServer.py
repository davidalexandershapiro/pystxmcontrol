import socket

class bcsServer:
    def __init__(self, bind_ip = None, bind_port = None):
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def connect(self, bind_ip=None, bind_port=None):
        self.socket.connect((bind_ip, bind_port))
        print("Connected to BCS Server: %s:%s" %(bind_ip, bind_port))

    def disconnect(self):
        self.socket.close()

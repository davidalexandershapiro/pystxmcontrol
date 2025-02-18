from pystxmcontrol.server.mySocket import *
import threading, traceback, time

class server:
    def __init__(self, address = 'localhost', port = 9999):
        self.sock = mySocket(address, port)
        self.sock.connect()

    def accept(self):
        self.sock.accept()

    def start(self):
        print("Starting message loop.")
        while True:
            message = self.sock.getMessage()
            time.sleep(1)
            if message == 'close':
                self.sock.sendMessage("Received message: %s" %message)
                return
            #time.sleep(5)
            self.sock.sendMessage("Received message: %s" %message)

class client:
    def __init__(self, address = 'localhost', port = 9999):
        self.sock = mySocket(address, port, client = True)
        self.sock.connect()

    def sendMessage(self, message):
        print(self.sock.sendMessage(message))



s = server()
c = client()
s.accept()
s_thread = threading.Thread(target=s.start,args=())
s_thread.start()
c.sendMessage("Hello from the client.")
c.sendMessage('close')
s_thread.join()



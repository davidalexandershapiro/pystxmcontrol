import zmq
import threading, traceback, time

class server:
    def __init__(self, address = 'tcp://127.0.0.1', sender_port = 9999, receiver_port = 9998):
        context = zmq.Context()
        self.receiver = context.socket(zmq.PULL)
        self.sender = context.socket(zmq.PUSH)
        self.receiver.connect(address + ':' + str(receiver_port))
        self.sender.connect(address + ':' + str(sender_port))

    def start(self):
        print("Starting message loop.")
        while True:
            message = self.receiver.recv_json()
            time.sleep(10)
            print("Server received message: %s" %message['message'])
            self.sender.send_json(message)
            if message['message'] == 'close':
                return

class client:
    def __init__(self, address = 'tcp://127.0.0.1', sender_port = 9998, receiver_port = 9999):
        context = zmq.Context()
        self.receiver = context.socket(zmq.PULL)
        self.sender = context.socket(zmq.PUSH)
        self.receiver.bind(address + ':' + str(receiver_port))
        self.sender.bind(address + ':' + str(sender_port))

    def sendMessage(self, message):
        message = {'message': message}
        self.sender.send_json(message)
        response = self.receiver.recv_json()
        print("Client received response: %s" %response['message'])



s = server()
c = client()
s_thread = threading.Thread(target=s.start,args=())
s_thread.start()
c.sendMessage("Hello from the client.")
c.sendMessage('close')
s_thread.join()



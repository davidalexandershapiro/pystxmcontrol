from pystxmcontrol.drivers.bcsController import *
from pystxmcontrol.drivers.bcsMotor import *
from pystxmcontrol.drivers.xpsController import *
from pystxmcontrol.drivers.xpsMotor import *
import time

c = bcsController(address = "192.168.168.100", port = 50000)
c.initialize()
m = bcsMotor(controller = c)
#m.connect(axis = "Mono Energy")
#m.config = {"units":1,"offset":0,"minValue":400,"maxValue":1000}
m.connect(axis = "Detector Y")
m.config = {"units":1, "offset": 0, "minValue":-13000, "maxValue":100}

#print(m.getVar("Double"))
##m.setVar(-1.2,"Double")
#print(m.getVar("Double"))

delta = -500
t0 = time.time()
currentPos = m.getPos()
print("Moving from %.4f eV to %.4f eV" %(currentPos, currentPos + delta))
m.moveTo(pos = currentPos + delta)
print("Move took %.2f seconds" %(time.time()-t0))
print(m.getPos())

#var = "annoyingTestVar"
#val = -1.2

#import socket
#sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#sock.connect(("131.243.73.68",50000))

#get initial value
#message = "getdoublevar %s\r\n" %var
#sock.sendall(message.encode())
#print(sock.recv(4096).decode())

#set to -1.2
#message = "SetDoubleVar(%s,%.4f)\r\n" %(var,val)
#sock.sendall(message.encode())
#print(sock.recv(4096).decode())

#get final value
#message = "getdoublevar %s\r\n" %var
#sock.sendall(message.encode())
#print(sock.recv(4096).decode())
#sock.close()


from pystxmcontrol.server.mySocket import mySocket

bind_port = 9999
bind_ip = "localhost"

clientSock = mySocket(bind_ip, bind_port, client = True)
clientSock.sendMessage("testMessage")
clientSock.close()

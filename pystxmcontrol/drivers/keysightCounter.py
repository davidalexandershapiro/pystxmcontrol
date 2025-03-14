#import pyvisa as visa
import usbtmc
from numpy import array
import time


class counter:
    def __init__(self):
        # Create a connection (session) to the TCP/IP socket on the instrument.
        #self.visa_TCPaddress = 'TCPIP::K-53230A-70140.local::5025::SOCKET'
        self.visa_address = "USB::0x0957::0x1907::INSTR"

    def connect(self, visa_address = None):
        if visa_address is not None:
            self.visa_address = visa_address
        #self.resourceManager = visa.ResourceManager()
        #self.session = self.resourceManager.open_resource(self.visa_address)
        self.session =  usbtmc.Instrument(self.visa_address)

        # For Serial and TCP/IP socket connections enable the read Termination Character, or read's will timeout
        #if self.session.resource_name.startswith('ASRL') or self.session.resource_name.endswith('SOCKET'):
        #    self.session.read_termination = '\n'

        # We can find out details of the connection
        #print('IP: %s\nHostname: %s\nPort: %s\n' %
        #      (self.session.get_visa_attribute(visa.constants.VI_ATTR_TCPIP_ADDR),
        #       self.session.get_visa_attribute(visa.constants.VI_ATTR_TCPIP_HOSTNAME),
        #       self.session.get_visa_attribute(visa.constants.VI_ATTR_TCPIP_PORT)))

        # Send the *IDN? and read the response
        self.session.write("*RST")
        print(self.session.ask('*IDN?'))

        #print('*IDN? returned: %s' % idn.rstrip('\n'))

    def config(self, dwell, count = 1, samples = 1, trigger = 'BUS', output = 'OFF', channel = 1):
        #print("Configuring counter with dwell = %.2f ms, count = %i, samples = %i and trigger = %s" %(dwell, count, samples, trigger))
        self.dwell = dwell
        self.count = count
        self.session.write("*RST")
        self.session.write("DISP OFF")
        self.session.write("CONF:TOT:TIM %.6f, (@%i)" %(dwell / 1000., channel))
        self.session.write("TRIG:COUN %i" %count)
        self.session.write("SAMP:COUN %i" %samples)
        self.session.write("TRIG:DEL 0")
        self.session.write("TRIG:SLOP POS")
        self.session.write("OUTP:STAT %s" %output) #output the gate signal for shutter timing
        self.session.write("TRIG:SOUR %s" %trigger)
        self.session.ask("CONF?") #this is needed.  Blocks until config is complete I think

    def getPoint(self):
        self.session.write("INIT:IMM")
        self.session.write("*TRG")
        data = self.session.ask("FETC?")
        return float(data)
        
    def busTrigger(self):
        self.session.write("*TRG")

    def initLine(self):
        self.session.write("INIT:IMM")

    def getLine(self):
        data = self.session.ask("FETC?")
        return array(data.split(',')).astype('float')

    def getPointLoop(self, dwell):
        pass

    def disconnect(self):
        # Close the connection to the instrument
        self.session.close()
        #self.resourceManager.close()

    def setGate(self, gate):
        self.gate = gate
        if self.gate == True:
            pass
        else:
            pass

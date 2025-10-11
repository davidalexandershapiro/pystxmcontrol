#import pyvisa as visa
import usbtmc
from numpy import array
import time
import asyncio


class counter:
    def __init__(self):
        # Create a connection (session) to the TCP/IP socket on the instrument.
        #self.visa_TCPaddress = 'TCPIP::K-53230A-70140.local::5025::SOCKET'
        self.visa_address = "USB::0x0957::0x1907::INSTR"

    def connect(self, visa_address = None):
        if visa_address is not None:
            self.visa_address = visa_address
        self.session =  usbtmc.Instrument(self.visa_address)
        self.session.write("*RST")
        print(self.session.ask('*IDN?'))

        #print('*IDN? returned: %s' % idn.rstrip('\n'))

    def config(self, dwell, count = 1, samples = 1, trigger = 'BUS', output = 'OFF', channel = 1):
        #print("Configuring counter with dwell = %.2f ms, count = %i, samples = %i and trigger = %s" %(dwell, count, samples, trigger))
        self.dwell = dwell
        self.count = count
        self.trigger = trigger
        self.session.write("*RST")
        self.session.write("DISP OFF")
        self.session.write(f"CONF:TOT:TIM {dwell/1000.}, (@{channel})")
        self.session.write(f"TRIG:COUN {count}")
        self.session.write(f"SAMP:COUN {samples}")
        self.session.write(f"TRIG:DEL 0")
        self.session.write(f"TRIG:SLOP POS")
        self.session.write(f"OUTP:STAT {output}") #output the gate signal for shutter timing
        self.session.write(f"TRIG:SOUR {trigger}")
        self.session.ask("CONF?") #this is needed.  Blocks until config is complete I think

    async def getPoint(self):
        self.session.write("INIT:IMM")
        self.session.write("*TRG")
        data = self.session.ask("FETC?")
        return array([float(data)],dtype="float")
        
    def busTrigger(self):
        self.session.write("*TRG")

    def initLine(self):
        self.session.write("INIT:IMM")

    async def getLine(self):
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

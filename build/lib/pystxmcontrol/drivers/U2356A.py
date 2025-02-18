import usbtmc
import time
import struct
import numpy as np

class U2356A:
    def __init__(self):
        self.visa_address = "USB::0x0957::0x1418::INSTR"
        self.voltage_range = 10
        
    def connect(self, visa_address = None):
        if visa_address is not None:
            self.visa_address = visa_address
        self.session = usbtmc.Instrument(self.visa_address)
        self.session.write("*RST")
        self.device_info = self.session.ask("*IDN?")
        print(self.device_info)

    def config(self, mode = "single", rate = 1000, points = 1, trigger = "NONE", channel = [101]):
        
        self.channel = channel
        self.n_channels = len(self.channel)
        self.rate = rate
        self.points = points
        self.trigger = trigger
        self.mode = mode
        
        #set up the string defining the channel list (@channel1,channel2,...)
        self._channelStr = '(@'
        for channel in self.channel:
            self._channelStr += str(channel)+','
        self._channelStr = self._channelStr[:-1] + ')'
    
        self.session.write("VOLT:RANG %i, %s" %(self.voltage_range, self._channelStr))
        self.session.write("VOLT:STYP DIFF, %s" %self._channelStr)
        self.session.write("VOLT:POL BIP, %s" %self._channelStr)
    
        if mode == "single":
            pass
        elif mode == "continuous":
            #set the channels to monitor
            self.session.write("ROUT:SCAN %s" %self._channelStr)
            #set sampling rate in Hz
            self.session.write("ACQ:SRAT %i" %self.rate)
            #set number of acquisition points
            self.session.write("ACQ:POIN %i" %self.points)
            #set immediate trigger
            self.session.write("TRIG:SOUR %s" %self.trigger)

    def getPoint(self):
        return self.session.ask("MEAS? %s" %self._channelStr)
        
    def getLine(self):
        #start a continuous acquisition
        self.session.write("DIG")
        
        #check status
        self.status = self.session.ask("WAV:STAT?")
        while self.status != "DATA":
            ##this returns "DATA" once it's all available in the FIFO
            time.sleep(1./self.rate*self.points)
            self.status = self.session.ask("WAV:STAT?")
        self.session.write("WAV:DATA?")
        raw_bytes = self.session.read_raw()
        #First 10 bytes are header. Bytes 2:10 are the number of data bytes
        #n_bytes = int(raw_bytes[2:10])
        raw_bytes = raw_bytes[10:]
        n_bytes = len(raw_bytes)
        
        #de-interleave the bytes according to channel.  Creates 3 lists, one for each channel
        ##byte1_ch1,byte1_ch2,byte1_ch3,byte2_ch1,byte2_ch2,byte2_ch3, byte3_ch1,byte3_ch2,byte3_ch3...
        ##[byte1_ch1,byte2_ch1,byte3_ch1...],[byte1_ch2,byte2_ch2,byte3_ch2...],[byte1_ch3,byte2_ch3,byte3_ch3...]
        #raw_bytes = [raw_bytes[i::self.n_channels] for i in range(self.n_channels)]
        
        #check for correct number of bytes, two bytes per data point per channel
        if n_bytes != self.points * self.n_channels * 2:
            print("Expected %i bytes but received %i" %(self.points * self.n_channels * 2, n_bytes))
            return None
            
        #unpack the bytes to numpy dtype
        data = [[] for channel in self.channel]
        #for i in range(n_bytes):
        #    if (i % (self.n_channels * 2)) < self.n_channels:
        #        j = i % self.n_channels
        #        data[j].append(struct.unpack('h', bytes([raw_bytes[i],raw_bytes[i + self.n_channels]])))
        for i in range(0,n_bytes,2):
            j = (i // 2) % self.n_channels
            data[j].append(struct.unpack('h',bytes([raw_bytes[i],raw_bytes[i+1]])))
        #for j in range(self.n_channels):
        #    i = 0
        #    while i < len(raw_bytes[j]):
        #        this_bytes = bytes([raw_bytes[j][i],raw_bytes[j][i+1]])
        #        data[j].append(struct.unpack('<h',this_bytes)) #big endian short integer type (16bit integer)
        #        i += 2
        return data
            
    def disconnect(self):
        self.session.close()






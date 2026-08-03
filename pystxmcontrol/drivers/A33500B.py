import usbtmc
import time
import struct
import numpy as np

class A33500B:
    def __init__(self):
        self.visa_address = "USB::0x0957::0x2807::INSTR"
        
    def connect(self, visa_address = None):
        if visa_address is not None:
            self.visa_address = visa_address
        self.session = usbtmc.Instrument(self.visa_address)
        self.session.write("*RST")
        self.session.write("*CLS")
        self.device_info = self.session.ask("*IDN?")
        self._voltage_calibration = 10./100./2. ##volts per micron analog input/output.  OUtput is doubled for some reason
        print(self.device_info)

    def config(self, amplitude = (1,1), offset = (0,0), srate = 10000):
        """
        hi/lo are positions in microns
        """
        for i in range(2):
            channel_str = 'SOUR' + str(i + 1)
            self.session.write(channel_str + ':VOLT:HIGH %.2f' %(amplitude[i] * self._voltage_calibration))
            self.session.write(channel_str + ':VOLT:LOW %.2f' %(-amplitude[i] * self._voltage_calibration))
        #if mode == 'sin':
        #    self.session.write(channel_str + ':FUNC SIN')
        #    self.session.write(channel_str + ':FREQ %.2f' %frequency)
        #    self.session.write(channel_str + ':VOLT:HIGH %.2f' %(amplitude * self._voltage_calibration))
        #    self.session.write(channel_str + ':VOLT:LOW %.2f' %(-amplitude * self._voltage_calibration))
        #    self.session.write(channel_str + ':PHAS %.2f' %phase)
        
    def setWaveform(self, waveform, maxAmplitude = (1,1), offset = (0,0), srate = 10000):
        """
        Waveform is a concatenated list of x,y positions: x1,x2,x3,...,y1,y2,y3,...
        The values should be scaled to (-1,+1)
        maxAmplitude will set the maximum physical position for a position value of +/-1
        maxAmplitude needs to be converted to output voltage using the calibration
        """
        self.config(amplitude = maxAmplitude)
        self.session.write('SOURce1:DATA:VOLatile:CLEar')
        self.session.write('SOURce2:DATA:VOLatile:CLEar')
        self.session.write("DATA:ARB2:FORM AABB")
        self.session.write('SOURCE1:FUNCtion:ARB:SRATe ' + str(srate))
        self.session.write('SOURCE2:FUNCtion:ARB:SRATe ' + str(srate))
        self.session.write('SOURCE1:VOLT:HIGH %.2f' %(maxAmplitude[0] * self._voltage_calibration))
        self.session.write('SOURCE2:VOLT:LOW %.2f' %(-maxAmplitude[1] * self._voltage_calibration))        
        # DC offset positions a non-zero-centred trajectory (nPoint input sets absolute
        # position).  offset is in microns; convert with the same volts/micron cal.
        self.session.write('SOURCE1:VOLT:OFFSET %.4f' % (offset[0] * self._voltage_calibration))
        self.session.write('SOURCE2:VOLT:OFFSET %.4f' % (offset[1] * self._voltage_calibration))
        
        dataStr = ''
        for dataPoint in waveform:
            dataStr += str(dataPoint) + ','
        dataStr = "DATA:ARB2:DAC stxm," + dataStr[0:-1] #get rid of the last comma
        #print(dataStr[0:100])
        self.session.write(dataStr)
        #self.session.write('MMEM:STOR:DATA1 "INT:\stxm.arb"')
        self.session.write('SOURce1:FUNCtion ARB')
        self.session.write('SOURce2:FUNCtion ARB')
        print(self.session.ask('SYST:ERR?'))
        
    def clearAllErrors(self):
        for i in range(100):
            print(self.session.ask('SYST:ERR?'))
            
    def start(self):
        self.session.write('OUTPut1 ON')
        self.session.write('OUTPut2 ON')
        
    def stop(self):
        self.session.write('OUTPut1 OFF')
        self.session.write('OUTPut2 OFF')

    def configStartTrigger(self, slope="POS"):
        """Arm a single-cycle triggered burst on both channels and enable a Trig Out
        pulse at burst start.  fire() then plays the trajectory once and emits one TTL
        edge on the rear Trig Out BNC -- that edge is what launches the DAQ scan.

        NOTE (verify on bench): the 33500B documents Trig Out for sweep/burst; the exact
        burst+trig-out SCPI and two-channel coupling should be confirmed against the
        instrument.  With DATA:ARB2 the two channels share one sample clock.
        """
        slope_scpi = "POSitive" if str(slope).upper().startswith("P") else "NEGative"
        for ch in (1, 2):
            self.session.write('SOURce%d:BURSt:MODE TRIGgered' % ch)
            self.session.write('SOURce%d:BURSt:NCYCles 1' % ch)
            self.session.write('SOURce%d:BURSt:STATe ON' % ch)
        self.session.write('TRIGger1:SOURce BUS')            # software *TRG starts it
        self.session.write('OUTPut:TRIGger:SLOPe %s' % slope_scpi)
        self.session.write('OUTPut:TRIGger ON')

    def fire(self):
        """Software-trigger the armed single-cycle burst (one trajectory playthrough
        plus the Trig Out start pulse)."""
        self.session.write('*TRG')

    def disconnect(self):
        self.session.close()
        
        






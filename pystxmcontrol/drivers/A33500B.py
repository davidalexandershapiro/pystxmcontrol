import usbtmc
import time
import struct
import numpy as np
from contextlib import contextmanager

class A33500B:

    # Opt-in profiling: when True, setWaveform/configStartTrigger record per-block
    # wall times (ms) into self.timings.  Off by default => the context managers just
    # yield, adding no measurable overhead.  Enabled by scripts/testAWGSpiral --timing.
    profile = False

    def __init__(self):
        self.visa_address = "USB::0x0957::0x2807::INSTR"
        self.timings = {}

    @contextmanager
    def _prof(self, key):
        """Record the wall time (ms) of the wrapped block into self.timings[key]."""
        if not self.profile:
            yield
            return
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.timings[key] = (time.perf_counter() - t0) * 1e3
        
    def connect(self, visa_address = None):
        if visa_address is not None:
            self.visa_address = visa_address
        self.session = usbtmc.Instrument(self.visa_address)
        self.session.write("*RST")
        self.session.write("*CLS")
        self.device_info = self.session.ask("*IDN?")
        # Volts per micron for the nPoint analog command.  Bench result (spiral checked
        # against the correctly-centred digital encoder frame): the earlier /2 under-drove
        # the AWG by 2x -- correct centre but a half-amplitude spiral.  Removing it makes
        # the played spiral match the commanded amplitude.  (The nPoint's true monitor/
        # input scale is ~5 um/V, i.e. 0.2 V/um; the effective output likely reaches that
        # via the 33500B's high-Z 2x, which is why the programmed value here is 0.1 V/um.)
        self._voltage_calibration = 10./100.  ## volts per micron analog input/output
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
        with self._prof('setwf_setup_scpi'):
            self.session.write('SOURce1:DATA:VOLatile:CLEar')
            self.session.write('SOURce2:DATA:VOLatile:CLEar')
            self.session.write("DATA:ARB2:FORM AABB")
            self.session.write('SOURCE1:FUNCtion:ARB:SRATe ' + str(srate))
            self.session.write('SOURCE2:FUNCtion:ARB:SRATe ' + str(srate))

        # waveform holds normalized values in [-1, +1]; the :DAC form of the arb
        # download expects *integer DAC codes* (-32767..+32767), so scale first.
        # (Sending floats to :DAC quantizes everything to -1/0/+1 codes -> a garbage,
        # near-zero-amplitude arb that plays back as a corrupted waveform.)
        with self._prof('setwf_encode'):
            codes = np.clip(np.round(np.asarray(waveform, dtype=np.float64) * 32767.0),
                            -32767, 32767).astype(np.int32)
            dataStr = "DATA:ARB2:DAC stxm," + ",".join(str(c) for c in codes)
        #print(dataStr[0:100])
        with self._prof('setwf_dac_write'):
            self.session.write(dataStr)     # the big USB transfer (2*N ASCII codes)
        #self.session.write('MMEM:STOR:DATA1 "INT:\stxm.arb"')
        # Select the freshly-loaded arb as the active waveform on both channels.
        # DATA:ARB2:DAC only puts "STXM" into volatile memory; without this the
        # channels keep playing whatever arb was previously selected (the built-in
        # EXP_RISE default), so the trajectory never comes out.
        with self._prof('setwf_select_func'):
            self.session.write('SOURce1:FUNCtion:ARBitrary "STXM"')
            self.session.write('SOURce2:FUNCtion:ARBitrary "STXM"')
            self.session.write('SOURce1:FUNCtion ARB')
            self.session.write('SOURce2:FUNCtion ARB')

        # Amplitude + offset MUST be set *after* the arb is selected: selecting a new
        # arb resets the channel amplitude to the instrument default (~100 mVpp), which
        # would otherwise clobber the trajectory scale.  The normalized arb spans +/-1,
        # so peak-to-peak volts = 2 * maxAmplitude(um) * cal, centred on offset(um)*cal.
        with self._prof('setwf_amplitude'):
            for ch in (1, 2):
                vpp = 2.0 * maxAmplitude[ch - 1] * self._voltage_calibration
                voff = offset[ch - 1] * self._voltage_calibration
                self.session.write('SOURce%d:VOLTage %.6f' % (ch, vpp))
                self.session.write('SOURce%d:VOLTage:OFFSet %.6f' % (ch, voff))
        with self._prof('setwf_err_query'):
            err = self.session.ask('SYST:ERR?')
        print(err)
        
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
            # BOTH channels must wait for the software *TRG.  A channel left at its
            # post-*RST default trigger source (IMMediate) free-runs its burst, which
            # both replays that channel's arb continuously and spews extra Trig Out
            # pulses -- the DAQ then latches onto one of those instead of the real
            # trajectory-start edge.  Set the source per channel, not just ch1.
            self.session.write('TRIGger%d:SOURce BUS' % ch)
        # Drive the Trig Out from channel 1 so the launch edge is the single burst
        # that plays the trajectory (both fire together on one *TRG).
        self.session.write('OUTPut:TRIGger:SOURce CH1')
        self.session.write('OUTPut:TRIGger:SLOPe %s' % slope_scpi)
        self.session.write('OUTPut:TRIGger ON')

    def fire(self):
        """Software-trigger the armed single-cycle burst (one trajectory playthrough
        plus the Trig Out start pulse)."""
        self.session.write('*TRG')

    def disconnect(self):
        self.session.close()
        
        






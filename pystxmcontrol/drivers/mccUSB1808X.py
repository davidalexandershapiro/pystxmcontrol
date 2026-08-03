"""
DAQ driver for the Measurement Computing USB-1808X.

Behaves like ``keysight53230A``: same config/output contract, same gate/shutter
integration, same simulation fallback.  The USB-1808X carries both event counters
and an ADC, so this driver exposes a ``mode`` switch ("counter", "adc", or
"adc+counter") while keeping config and output identical either way -- every
acquisition yields a 1-D float array of length ``count * samples``.

In "adc" mode the hardware always digitizes at its 200 kS/s ceiling (one sample
every 5 us) and averages the samples in each dwell window down to a single value,
so requested dwell times >= 100 us average >= 20 raw samples per point.

In "adc+counter" mode the ADC and a counter are scanned *together* off one pacer
clock (uldaq's synchronous daq_in_scan), so position readback and photon counts are
latched on the same edges by construction -- ideal for a spiral fly-scan where the
AWG plays the trajectory and emits a single start trigger.  One subsystem (``primary``,
default "counter") is returned from getLine/getPoint as usual; the other is latched
on ``self.aux_data`` (same length and order) for the scan to pull separately.

Configure it in daq.json, e.g.::

    "mcc": {
        "driver": "mccUSB1808X",
        "mode": "adc",                 # "counter" | "adc" | "adc+counter"
        "type": "point",
        "channel": 0,                  # AI channel (adc) or counter (counter)
        "ai_channels": [0, 1],         # adc+counter: position-readback AI channels [xmon, ymon]
        "ctr_channel": 0,              # adc+counter: photon-counting counter
        "primary": "counter",          # adc+counter: which feeds self.data
        "input_mode": "differential",  # or "single-ended"
        "position_readback": false,    # true when using the adc as the position encoder
        "voltage_range": 10.0,
        "adc_max_rate": 200000,
        "serial": null,
        "address": null,
        "gate": false,
        "gate address": "/dev/arduino",
        "minimum_dwell": 0.005,
        "dwell_pad": 0,
        "time_resolution": 0.005,
        "record": true,
        "simulation": false
    }
"""

from pystxmcontrol.controller.daq import daq
from pystxmcontrol.drivers.usb1808x import usb1808x
from pystxmcontrol.drivers.shutter import shutter
from numpy.random import poisson, normal
from numpy import array
import asyncio


class mccUSB1808X(daq):
    def __init__(self, address=None, port=None, simulation=False):
        self.address = address
        self.simulation = simulation
        self.meta = {"ndim": 0, "x": [], "type": "point", "name": "MCC USB-1808X",
                     "channel": 0, "mode": "counter", "gate": False}
        self.device = usb1808x()
        self.idle_ms = 1
        self.ctrNum = 0
        #: in "adc+counter" mode the secondary channel (e.g. ADC position readback)
        #: is latched here alongside every self.data return; None otherwise.
        self.aux_data = None

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #
    def start(self):
        if not self.simulation:
            self._apply_meta()
            self.device.connect(serial=self.meta.get("serial"))
        if self.meta.get("gate"):
            self.gate = shutter(address=self.meta["gate address"])
            self.gate.connect(simulation=self.simulation)
            self.gate.setStatus(softGATE=0)

    def stop(self):
        if not self.simulation:
            self.device.disconnect()

    def _apply_meta(self):
        """Copy hardware options from daq.json meta onto the low-level wrapper."""
        self.device.mode = self.meta.get("mode", "counter")
        self.device.channel = int(self.meta.get("channel", 0))
        self.device.input_mode = self.meta.get("input_mode", "differential")
        self.device.voltage_range_volts = float(self.meta.get("voltage_range", 10.0))
        self.device.adc_max_rate = float(self.meta.get("adc_max_rate", 200000.0))
        self.device.serial = self.meta.get("serial")
        # "adc+counter" dual mode: AI channels + counter on one pacer clock
        ai_channels = self.meta.get("ai_channels",
                                    self.meta.get("ai_channel", self.meta.get("channel", 0)))
        if not isinstance(ai_channels, (list, tuple)):
            ai_channels = [ai_channels]
        self.device.ai_channels = [int(c) for c in ai_channels]
        self.device.ctr_channel = int(self.meta.get("ctr_channel", 0))
        self.device.primary = self.meta.get("primary", "counter")

    def set_dwell(self, dwell):
        self.dwell = dwell

    # ------------------------------------------------------------------ #
    #  Configuration
    # ------------------------------------------------------------------ #
    def config(self, dwell, count=1, samples=1, trigger="BUS", output="OFF"):
        if isinstance(dwell, list):
            self.dwell, self.dwell2 = dwell
        else:
            self.dwell = dwell
        self.count = count
        self.samples = samples
        self.trigger = trigger
        self.output = output
        self.mode = self.meta.get("mode", "counter")
        if self.simulation:
            return
        self._apply_meta()
        self.device.config(self.dwell, count=count, samples=samples,
                           trigger=trigger, output=output,
                           channel=self.meta.get("channel", 0),
                           mode=self.meta.get("mode", "counter"))
        if self.meta.get("gate"):
            self.setGateDwell(0, 0)

    def initLine(self):
        if not self.simulation:
            self.device.initLine()

    def bus_trigger(self):
        if not self.simulation:
            self.device.bus_trigger()

    # ------------------------------------------------------------------ #
    #  Gate / shutter
    # ------------------------------------------------------------------ #
    def autoGateOpen(self, shutter=1):
        self.gate.setStatus(softGATE=1, shutterMASK=shutter)

    def autoGateClosed(self):
        self.gate.setStatus(softGATE=0)

    def setGateDwell(self, dwell1, dwell2=0):
        self.gate.dwell1 = dwell1
        self.gate.dwell2 = dwell2
        self.gate.setStatus()

    def setGate(self, gate):
        """Gate is boolean (up/down)."""
        self.gate = gate

    # ------------------------------------------------------------------ #
    #  Acquisition
    # ------------------------------------------------------------------ #
    def _n_ai(self):
        """Number of AI channels configured for dual mode (default 1)."""
        ai = self.meta.get("ai_channels", self.meta.get("ai_channel", 0))
        return len(ai) if isinstance(ai, (list, tuple)) else 1

    def _simLine(self):
        n = max(1, int(self.count) * int(self.samples))
        mode = self.meta.get("mode", "counter")
        if mode == "adc+counter":
            ai_list = [normal(1.0, 0.01, n) for _ in range(self._n_ai())]  # position volts
            ctr = poisson(1e7 * self.dwell / 1000., n)                      # counts
            if self.meta.get("primary", "counter") == "adc":
                self.aux_data = [ctr] + ai_list[1:]
                return ai_list[0]
            self.aux_data = ai_list
            return ctr
        if mode == "adc":
            # a noisy voltage around a nominal level, one value per window
            return normal(1.0, 0.01, n)
        return poisson(1e7 * self.dwell / 1000., n)

    async def getLine(self):
        if self.simulation:
            self.data = self._simLine()
            await asyncio.sleep(self.dwell / 1000. * self.count * self.samples)
            return self.data
        else:
            self.data = (await asyncio.gather(self.device.getLine()))[0]
            self.aux_data = self.device.aux_data
            return self.data

    async def getPoint(self):
        if self.simulation:
            await asyncio.sleep(self.dwell / 1000.)
            mode = self.meta.get("mode", "counter")
            if mode == "adc+counter":
                ai_list = [array([normal(1.0, 0.01)]) for _ in range(self._n_ai())]
                ctr = array([float(poisson(1e7 * self.dwell / 1000.))])
                if self.meta.get("primary", "counter") == "adc":
                    self.aux_data, self.data = [ctr] + ai_list[1:], ai_list[0]
                else:
                    self.aux_data, self.data = ai_list, ctr
            elif mode == "adc":
                self.data = array([normal(1.0, 0.01)])
            else:
                self.data = array([poisson(1e7 * self.dwell / 1000.)])
            return self.data
        else:
            self.data = (await asyncio.gather(self.device.getPoint()))[0]
            self.aux_data = self.device.aux_data
            return self.data

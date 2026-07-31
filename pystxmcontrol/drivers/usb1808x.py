"""
Low-level wrapper for the Measurement Computing USB-1808X.

This mirrors the role of ``keysightCounter.counter`` / ``U2356A.U2356A``: it hides
the vendor API and exposes a small, uniform surface (connect / config / initLine /
bus_trigger / getPoint / getLine / disconnect) that the ``mccUSB1808X`` daq driver
drives.

The USB-1808X has both 32-bit event counters and an 18-bit ADC (200 kS/s aggregate),
so a single instrument can serve as either a photon counter (like the Keysight
53230A) or an analog input.  The ``mode`` selector chooses which, while config and
output stay identical from the caller's point of view: every acquisition returns a
1-D float array of length ``count * samples``, one value per dwell window.

ADC mode always digitizes at the hardware maximum (``adc_max_rate``, default
200 kS/s = one sample every 5 us) and averages the samples that fall inside each
dwell window down to a single value.  With dwell times >= 100 us that is >= 20
samples per point.

The ``uldaq`` Python package is imported lazily (inside ``connect``) so that this
module, and therefore the whole drivers package, imports cleanly on machines where
uldaq is not installed -- simulation runs never touch it.
"""

import time
import asyncio
import numpy as np


class usb1808x:

    #: seconds; a scan is considered hung if it does not finish within
    #: expected_duration * this factor (+ a small floor).  Mirrors the FETC? timeout
    #: behaviour the fly-scan loop relies on to detect a missed trigger.
    TIMEOUT_MARGIN = 3.0

    def __init__(self):
        # uldaq handles, populated on connect()
        self._ul = None                 # the uldaq module
        self.device = None              # DaqDevice
        self.ai_device = None           # AiDevice
        self.ctr_device = None          # CtrDevice
        self._ai_info = None

        # configuration, filled by config()
        self.mode = "counter"           # "counter" or "adc"
        self.channel = 0                # AI channel or counter number
        self.dwell = 1.0                # ms
        self.count = 1                  # number of hardware triggers
        self.samples = 1               # measurement windows per trigger
        self.trigger = "BUS"            # "BUS" (software) or "EXT" (hardware)
        self.output = "OFF"

        # ADC parameters
        self.adc_max_rate = 200000.0    # S/s, hardware ceiling of the USB-1808X
        self.voltage_range_volts = 10.0 # +/- full scale
        self.input_mode = "differential"

        # optional device serial number, to disambiguate multiple USB-1808X units
        self.serial = None

        # runtime state
        self._oversamples = 1           # ADC raw samples averaged per dwell window
        self._armed = False
        self._scan_running = False
        self._buffer = None

    # ------------------------------------------------------------------ #
    #  Connection
    # ------------------------------------------------------------------ #
    def connect(self, serial=None):
        """Discover and connect to the USB-1808X.  Imports uldaq lazily.

        Idempotent: uldaq allows only one live connection per physical unit, so a
        second call while already connected is a no-op.  (The controller calls
        start()/connect() twice during init -- DAQ setup and startMonitor.)
        """
        import uldaq
        self._ul = uldaq

        if serial is not None:
            self.serial = serial

        if self.device is not None:
            try:
                if self.device.is_connected():
                    return
            except Exception:
                pass
            # stale handle -- tear it down before reconnecting
            self.disconnect()

        devices = uldaq.get_daq_device_inventory(uldaq.InterfaceType.USB)
        if not devices:
            raise RuntimeError("No MCC USB DAQ devices found.")

        descriptor = None
        for dev in devices:
            if "1808" in dev.product_name:
                if self.serial is None or dev.unique_id == str(self.serial):
                    descriptor = dev
                    break
        if descriptor is None:
            raise RuntimeError(
                "No USB-1808X found (serial=%r) among: %s"
                % (self.serial, [d.product_name for d in devices]))

        self.device = uldaq.DaqDevice(descriptor)
        self.device.connect()
        self.ai_device = self.device.get_ai_device()
        self.ctr_device = self.device.get_ctr_device()
        self._ai_info = self.ai_device.get_info() if self.ai_device else None
        print("Connected to %s (%s)" % (descriptor.product_name, descriptor.unique_id))

    def disconnect(self):
        self._stop_scan()
        if self.device is not None:
            try:
                if self.device.is_connected():
                    self.device.disconnect()
                self.device.release()
            except Exception:
                pass
        self.device = None
        self.ai_device = None
        self.ctr_device = None

    # ------------------------------------------------------------------ #
    #  uldaq enum helpers
    # ------------------------------------------------------------------ #
    def _range(self):
        ul = self._ul
        return {
            10.0: ul.Range.BIP10VOLTS,
            5.0: ul.Range.BIP5VOLTS,
            2.0: ul.Range.BIP2VOLTS,
            1.0: ul.Range.BIP1VOLTS,
        }.get(float(self.voltage_range_volts), ul.Range.BIP10VOLTS)

    def _input_mode(self):
        ul = self._ul
        if str(self.input_mode).lower().startswith("single"):
            return ul.AiInputMode.SINGLE_ENDED
        return ul.AiInputMode.DIFFERENTIAL

    # ------------------------------------------------------------------ #
    #  Configuration
    # ------------------------------------------------------------------ #
    def config(self, dwell, count=1, samples=1, trigger="BUS", output="OFF",
               channel=0, mode="counter"):
        """
        Configure an acquisition.

        :param dwell:    dwell time per window, in ms
        :param count:    number of hardware triggers (pixels) in the line; 1 for a point
        :param samples:  measurement windows produced per trigger
        :param trigger:  "BUS" (software timed) or "EXT" (external hardware trigger)
        :param output:   retained for API parity with the Keysight driver (unused here)
        :param channel:  AI channel (adc mode) or counter number (counter mode)
        :param mode:     "counter" or "adc"
        """
        self.dwell = dwell
        self.count = int(count)
        self.samples = int(samples)
        self.trigger = trigger
        self.output = output
        self.channel = int(channel)
        self.mode = mode

        # number of raw ADC samples to average per dwell window; always digitize at
        # the hardware ceiling and average down to the requested dwell.
        self._oversamples = max(1, int(round(self.dwell * 1e-3 * self.adc_max_rate)))

        self._stop_scan()
        self._armed = False

    # ------------------------------------------------------------------ #
    #  Line acquisition (buffered scan)
    # ------------------------------------------------------------------ #
    def initLine(self):
        """
        Arm a buffered line acquisition.

        For EXT triggering the scan is started here so the hardware is already
        waiting when the motor begins to emit trigger pulses.  For BUS triggering we
        only mark the driver armed and defer the (software-paced) start to
        bus_trigger(), matching the Keysight INIT:IMM / *TRG split.
        """
        self._stop_scan()
        self._armed = True
        if self.trigger == "EXT":
            self._start_scan(external=True)

    def bus_trigger(self):
        """Software start for a BUS-triggered line scan."""
        if self.trigger == "BUS" and self._armed and not self._scan_running:
            self._start_scan(external=False)

    def _windows(self):
        """Total number of dwell windows in the current line."""
        return max(1, self.count * self.samples)

    def _rate(self):
        """Raw sample rate for the current scan (always the ADC ceiling for adc mode)."""
        if self.mode == "adc":
            return self.adc_max_rate
        # counter mode is paced one latch per dwell window
        return 1.0 / (self.dwell * 1e-3)

    def _start_scan(self, external):
        """Kick off a buffered a_in_scan / c_in_scan that fills self._buffer."""
        ul = self._ul
        windows = self._windows()

        if external:
            scan_options = ul.ScanOption.EXTCLOCK
        else:
            scan_options = ul.ScanOption.DEFAULTIO

        if self.mode == "adc":
            # one channel, windows * oversamples raw samples at the ADC ceiling
            n_raw = windows * self._oversamples
            self._buffer = ul.create_float_buffer(1, n_raw)
            self.ai_device.a_in_scan(
                self.channel, self.channel, self._input_mode(), self._range(),
                n_raw, self.adc_max_rate, scan_options,
                ul.AInScanFlag.DEFAULT, self._buffer)
        else:
            # counter accumulates; latch it once per dwell window and difference later.
            self.ctr_device.c_clear(self.channel)
            self._buffer = ul.create_int_buffer(1, windows)
            self.ctr_device.c_in_scan(
                self.channel, self.channel, windows, self._rate(),
                scan_options, ul.CInScanFlag.DEFAULT, self._buffer)

        self._scan_running = True

    def _wait_scan(self):
        """Block until the running scan finishes, then stop it.  Raises on timeout."""
        ul = self._ul
        expected = self._windows() * self.dwell * 1e-3
        timeout = expected * self.TIMEOUT_MARGIN + 1.0
        device = self.ai_device if self.mode == "adc" else self.ctr_device
        # WAIT_UNTIL_DONE returns early if already done; timeout is in seconds here.
        try:
            device.scan_wait(ul.WaitType.WAIT_UNTIL_DONE, timeout)
        except Exception as e:
            self._stop_scan()
            raise TimeoutError("USB-1808X scan did not complete: %s" % e)

    def _stop_scan(self):
        if not self._scan_running:
            return
        device = self.ai_device if self.mode == "adc" else self.ctr_device
        try:
            if device is not None:
                device.scan_stop()
        except Exception:
            pass
        self._scan_running = False

    def _reduce_line(self):
        """Turn the raw scan buffer into a length-(count*samples) float array."""
        windows = self._windows()
        raw = np.array(self._buffer[:], dtype="float")
        if self.mode == "adc":
            # average each block of oversamples raw ADC samples into one window value
            raw = raw[:windows * self._oversamples]
            return raw.reshape(windows, self._oversamples).mean(axis=1)
        # counter: buffer holds cumulative counts latched per window -> per-window diff
        return np.diff(raw, prepend=0.0)

    async def getLine(self):
        self._wait_scan()
        self._stop_scan()
        self._armed = False
        return self._reduce_line()

    # ------------------------------------------------------------------ #
    #  Point acquisition (self-contained, software timed)
    # ------------------------------------------------------------------ #
    async def getPoint(self):
        ul = self._ul
        if self.mode == "adc":
            n_raw = self._oversamples
            buf = ul.create_float_buffer(1, n_raw)
            self.ai_device.a_in_scan(
                self.channel, self.channel, self._input_mode(), self._range(),
                n_raw, self.adc_max_rate, ul.ScanOption.DEFAULTIO,
                ul.AInScanFlag.DEFAULT, buf)
            self.ai_device.scan_wait(ul.WaitType.WAIT_UNTIL_DONE,
                                     self.dwell * 1e-3 * self.TIMEOUT_MARGIN + 1.0)
            return np.array([np.mean(buf[:])], dtype="float")
        else:
            # totalize: clear, count for the dwell window, read.
            self.ctr_device.c_clear(self.channel)
            await asyncio.sleep(self.dwell / 1000.)
            counts = self.ctr_device.c_in(self.channel)
            return np.array([float(counts)], dtype="float")

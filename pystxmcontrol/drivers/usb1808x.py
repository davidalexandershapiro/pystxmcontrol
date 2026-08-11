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
        self.daqi_device = None         # DaqiDevice (synchronous mixed AI+counter scan)
        self._ai_info = None

        # configuration, filled by config()
        self.mode = "counter"           # "counter", "adc", or "adc+counter" (synchronous dual)
        self.channel = 0                # AI channel or counter number (single-subsystem modes)
        self.ai_channels = [0]          # AI channels scanned in dual mode, e.g. [xmon, ymon]
        self.ctr_channel = 0            # counter number used in "adc+counter" mode
        self.primary = "counter"        # which subsystem feeds getLine/getPoint in dual mode;
                                        # the other is stashed on self.aux_data (list of arrays)
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
        #: in "adc+counter" mode the primary subsystem is returned from getLine/getPoint
        #: and the secondary channel(s) are latched here as a list of 1-D arrays (same
        #: length/order as the primary), e.g. [xmon, ymon]; None otherwise.
        self.aux_data = None

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
        self.daqi_device = self.device.get_daqi_device()
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
        self.daqi_device = None

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
               channel=0, mode="counter", ai_channels=None, ctr_channel=None,
               primary=None):
        """
        Configure an acquisition.

        :param dwell:    dwell time per window, in ms
        :param count:    number of hardware triggers (pixels) in the line; 1 for a point
        :param samples:  measurement windows produced per trigger
        :param trigger:  "BUS" (software timed) or "EXT" (external hardware trigger)
        :param output:   retained for API parity with the Keysight driver (unused here)
        :param channel:  AI channel (adc mode) or counter number (counter mode)
        :param mode:     "counter", "adc", or "adc+counter" (synchronous dual scan)
        :param ai_channels: list of AI channels in "adc+counter" mode, e.g. [xmon, ymon]
                            (int accepted; falls back to attribute if None)
        :param ctr_channel: counter number in "adc+counter" mode (falls back to attribute)
        :param primary:  in "adc+counter" mode, which subsystem is returned by
                         getLine/getPoint ("counter" or "adc"); the other is on aux_data
        """
        self.dwell = dwell
        self.count = int(count)
        self.samples = int(samples)
        self.trigger = trigger
        self.output = output
        self.channel = int(channel)
        self.mode = mode
        # dual-mode channels/primary: keep the attribute (set from meta) if not passed
        if ai_channels is not None:
            self.ai_channels = [int(c) for c in
                                (ai_channels if isinstance(ai_channels, (list, tuple))
                                 else [ai_channels])]
        if ctr_channel is not None:
            self.ctr_channel = int(ctr_channel)
        if primary is not None:
            self.primary = primary

        # number of raw ADC samples to average per dwell window; always digitize at
        # the per-channel ceiling and average down to the requested dwell.  Uses the
        # *ceiling* rate (not _scan_rate, which is derived back from _oversamples).
        self._oversamples = max(1, int(round(self.dwell * 1e-3 * self._ceiling_rate())))

        self.aux_data = None
        self._stop_scan()
        self._armed = False

    # ------------------------------------------------------------------ #
    #  Line acquisition (buffered scan)
    # ------------------------------------------------------------------ #
    def initLine(self):
        """
        Arm a buffered line acquisition.

        For EXT triggering the scan is started here so the hardware is already
        waiting when the motor reaches the trigger point.  The external signal is
        interpreted one of two ways depending on the config shape (see
        ``_ext_is_start_trigger``): a per-line START trigger that arms an
        internally-paced line (count==1, samples>1 -- the nPoint line-sync case), or
        a per-pixel sample CLOCK that latches one sample per edge (count>1,
        samples==1 -- a stage-master pixel clock).  For BUS triggering we only mark
        the driver armed and defer the (software-paced) start to bus_trigger(),
        matching the Keysight INIT:IMM / *TRG split.
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

    def _dual(self):
        """True when acquiring AI + counter synchronously on one pacer clock."""
        return self.mode == "adc+counter"

    def _nchan(self):
        """Number of scan channels (len(ai_channels)+1 counter for dual mode, else 1)."""
        return len(self.ai_channels) + 1 if self._dual() else 1

    def _ceiling_rate(self):
        """Per-channel raw sample-rate ceiling, before dwell alignment.

        adc / dual modes oversample at the ADC ceiling and average down to the
        requested dwell.  The USB-1808X's 200 kS/s is an *aggregate* across scan
        channels, so dual mode gets the ceiling divided by the channel count.
        This sets how many raw samples fall in a dwell window (_oversamples).
        """
        if self.mode == "adc" or self._dual():
            return self.adc_max_rate / self._nchan()
        # counter mode is paced one latch per dwell window
        return 1.0 / (self.dwell * 1e-3)

    def _scan_rate(self):
        """Per-channel pacing rate for the internally-paced (dual) scan.

        Oversample at the ceiling, but pace so each dwell window is *exactly*
        self.dwell long: rate = oversamples / dwell.  Using the raw ceiling
        directly would make the window oversamples/ceiling seconds -- not dwell,
        because _oversamples is round()ed -- so an internally-paced scan would
        drift against an external trajectory (e.g. the AWG spiral) by that
        rounding error accumulated over every window.  For the AWG dual mode this
        is what keeps the position readback phase-locked to the commanded points.
        """
        if self.mode == "adc" or self._dual():
            return self._oversamples / (self.dwell * 1e-3)
        # counter mode is paced one latch per dwell window
        return 1.0 / (self.dwell * 1e-3)

    def _rate(self):
        """Alias kept for the single-subsystem scan paths."""
        return self._scan_rate()

    def _daqi_descriptors(self):
        """Build the mixed AI+counter channel descriptor list for a daqi scan.

        Order is fixed [ai0, ai1, ..., CTR]; the interleaved scan buffer therefore
        holds one row [ai0, ai1, ..., ctr] per sample, which _reduce_line() splits.
        """
        ul = self._ul
        ai_type = (ul.DaqInChanType.ANALOG_SE
                   if str(self.input_mode).lower().startswith("single")
                   else ul.DaqInChanType.ANALOG_DIFF)
        descriptors = [ul.DaqInChanDescriptor(c, ai_type, self._range())
                       for c in self.ai_channels]
        descriptors.append(ul.DaqInChanDescriptor(self.ctr_channel, ul.DaqInChanType.CTR32))
        return descriptors

    def _ext_is_start_trigger(self):
        """True when the external signal should START an internally-paced line
        rather than clock each sample.

        A conventional linear_image in ``trigger_mode="line"`` configures the DAQ
        with count==1, samples==N: one external trigger per line, and the DAQ paces
        the N dwell windows itself off its internal clock (the nPoint line-sync
        model, mirroring the Keysight ``TRIG:SOUR EXT`` + internal timebase).
        ``trigger_mode="point"`` instead configures count==N, samples==1: one
        external edge per pixel, i.e. a stage-master pixel clock (EXTCLOCK).
        """
        return self.count == 1 and self.samples > 1

    def _arm_ext_start_trigger(self):
        """Configure the dedicated external TTL pin as a rising-edge START trigger
        for a single-subsystem (counter/adc) line scan.

        POS_EDGE is the hardware TRIG pin, so the channel/level/variance args are
        ignored, but uldaq's set_trigger still requires them.  Mirrors the dual
        path's set_trigger call; retrigger count 0 = a single trigger per scan.
        """
        ul = self._ul
        device = self.ai_device if self.mode == "adc" else self.ctr_device
        device.set_trigger(ul.TriggerType.POS_EDGE, 0, 0.0, 0.0, 0)

    def _start_scan(self, external):
        """Kick off a buffered a_in_scan / c_in_scan / daq_in_scan into self._buffer."""
        ul = self._ul
        windows = self._windows()

        if self._dual():
            # Synchronous AI + counter on one pacer clock.  For this driver the AWG
            # emits a single trajectory-start pulse, so an external trigger *starts*
            # the internally-paced scan (EXTTRIGGER) rather than clocking each sample.
            n_scan = windows * self._oversamples          # samples per channel
            self._buffer = ul.create_float_buffer(self._nchan(), n_scan)
            if external:
                # POS_EDGE is the dedicated hardware TTL-trigger pin: level/variance
                # and the descriptor's channel are ignored, but ulDaqInSetTrigger still
                # requires a valid DaqInChanDescriptor struct, so hand it ai0's.
                trig_chan = self._daqi_descriptors()[0]
                self.daqi_device.set_trigger(ul.TriggerType.POS_EDGE, trig_chan, 0.0, 0.0, 0)
                scan_options = ul.ScanOption.EXTTRIGGER
            else:
                scan_options = ul.ScanOption.DEFAULTIO
            self.ctr_device.c_clear(self.ctr_channel)
            self.daqi_device.daq_in_scan(
                self._daqi_descriptors(), n_scan, self._scan_rate(),
                scan_options, ul.DaqInScanFlag.DEFAULT, self._buffer)
            self._scan_running = True
            return

        if external:
            if self._ext_is_start_trigger():
                # per-line external START trigger, internally paced: one trigger
                # arms the line and the internal pacer clocks the samples -- what
                # the nPoint sends in a conventional linear_image (line sync).
                self._arm_ext_start_trigger()
                scan_options = ul.ScanOption.EXTTRIGGER
            else:
                # per-pixel external sample CLOCK: one external edge latches each
                # sample (stage-master pixel clock).
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

    def _scan_device(self):
        """The uldaq scan subsystem driving the current mode."""
        if self._dual():
            return self.daqi_device
        return self.ai_device if self.mode == "adc" else self.ctr_device

    def _wait_scan(self):
        """Block until the running scan finishes, then stop it.  Raises on timeout."""
        ul = self._ul
        expected = self._windows() * self.dwell * 1e-3
        timeout = expected * self.TIMEOUT_MARGIN + 1.0
        device = self._scan_device()
        # WAIT_UNTIL_DONE returns early if already done; timeout is in seconds here.
        try:
            device.scan_wait(ul.WaitType.WAIT_UNTIL_DONE, timeout)
        except Exception as e:
            self._stop_scan()
            raise TimeoutError("USB-1808X scan did not complete: %s" % e)

    def _stop_scan(self):
        if not self._scan_running:
            return
        device = self._scan_device()
        try:
            if device is not None:
                device.scan_stop()
        except Exception:
            pass
        self._scan_running = False

    def _split_primary(self, ai_list, ctr):
        """Return the primary channel (per self.primary), stash the rest on aux_data.

        ai_list is a list of 1-D AI arrays (e.g. [xmon, ymon]); ctr is 1-D counts.
        aux_data is always a list of 1-D arrays for a uniform downstream interface.
        """
        ai_list = [np.asarray(a, dtype="float") for a in ai_list]
        ctr = np.asarray(ctr, dtype="float")
        if self.primary == "adc":
            # first AI channel is the returned signal; counts + any other AI go to aux
            self.aux_data = [ctr] + ai_list[1:]
            return ai_list[0]
        # default: counts primary, AI position monitors on aux
        self.aux_data = ai_list
        return ctr

    def _reduce_line(self):
        """Turn the raw scan buffer into a length-(count*samples) float array."""
        windows = self._windows()
        raw = np.array(self._buffer[:], dtype="float")
        if self._dual():
            # interleaved rows [ai0, ai1, ..., ctr] -> (n_raw, nchan)
            nchan = self._nchan()
            n_ai = len(self.ai_channels)
            n = windows * self._oversamples
            raw = raw[:n * nchan].reshape(n, nchan)
            # AI: average each oversamples block into one window value, per channel
            ai_list = [raw[:, i].reshape(windows, self._oversamples).mean(axis=1)
                       for i in range(n_ai)]
            # CTR (last column): cumulative counts latched every raw sample; take the
            # last latch in each window and difference to recover per-window counts.
            ctr_cum = raw[:, -1].reshape(windows, self._oversamples)[:, -1]
            ctr = np.diff(ctr_cum, prepend=0.0)
            return self._split_primary(ai_list, ctr)
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
        if self._dual():
            # one dwell window's worth of synchronous AI + counter samples
            nchan = self._nchan()
            n_ai = len(self.ai_channels)
            n_scan = self._oversamples
            buf = ul.create_float_buffer(nchan, n_scan)
            self.ctr_device.c_clear(self.ctr_channel)
            self.daqi_device.daq_in_scan(
                self._daqi_descriptors(), n_scan, self._scan_rate(),
                ul.ScanOption.DEFAULTIO, ul.DaqInScanFlag.DEFAULT, buf)
            self.daqi_device.scan_wait(ul.WaitType.WAIT_UNTIL_DONE,
                                       self.dwell * 1e-3 * self.TIMEOUT_MARGIN + 1.0)
            raw = np.array(buf[:], dtype="float").reshape(n_scan, nchan)
            ai_list = [np.array([raw[:, i].mean()]) for i in range(n_ai)]
            ctr = np.array([raw[-1, -1] - raw[0, -1]])   # counter cleared before scan
            return self._split_primary(ai_list, ctr)
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

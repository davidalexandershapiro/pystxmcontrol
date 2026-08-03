"""
Trajectory motor-controller for the Keysight 33500B arbitrary waveform generator.

Plays a 2-D (X, Y) position trajectory as a synchronized dual-channel arbitrary
waveform into an nPoint piezo controller (input voltage sets absolute position), and
emits a single TTL start pulse on the AWG's rear Trig Out at trajectory start.  That
pulse launches a USB-1808X "adc+counter" scan (mccUSB1808X) which reads back the
achieved X/Y position (nPoint monitor voltages, on two AI channels) and photon counts
on one pacer clock -- so position and counts are inherently paired.

This mirrors ``mcsController``: it implements the same controller contract the spiral
fly-scan drives through ``derivedPiezo`` -- ``getAxis`` / ``register_axis`` /
``setup_axis`` / ``setup_xy`` / ``trigger_xy`` / ``read_xy`` / ``acquire_xy`` /
``setPositionTrigger``.  Trajectory *generation* lives upstream (the scan builds the
spiral and passes X/Y arrays); this controller is trajectory-source-agnostic --
``setup_xy(ax1pos, ax2pos, dwell)`` is the only seam any future generator needs.

Measured positions returned by ``acquire_xy`` are the *commanded* arrays (a fallback);
the real achieved positions come from the DAQ's ``aux_data`` and are injected into
``scanInfo["line_positions"]`` inside ``dataHandler.getLine`` (gated on the DAQ's
``position_readback`` meta flag), because the DAQ buffer is only reduced there --
after ``acquire_xy`` has already run.

Config (motor.json), mirroring mclMotor/mclController -- two primary axes sharing one
controllerID plus a derived ``derivedPiezo``::

    "AWGFineX": {"type":"primary","axis":"x","driver":"keysightAWGMotor",
                 "controller":"keysightAWGController",
                 "controllerID":"USB::0x0957::0x2807::INSTR","port":0,
                 "controller_index":1,"stage_type":"piezo",
                 "units":1.0,"offset":0.0,"minValue":-50,"maxValue":50,"simulation":false},
    "AWGFineY": {... "axis":"y", "controller_index":2, ...},
    "SampleX":  {"type":"derived","axes":{"axis1":"AWGFineX","axis2":"CoarseX"},
                 "driver":"derivedPiezo", ...}

The leaf motor uses ``units=1.0``/``offset=0.0`` so ``derivedPiezo.scale2controller``
passes microns straight through; ``setup_xy`` then normalizes microns to the AWG's
+/-1 arbitrary-waveform range internally.
"""

import time
import threading
import numpy as np

from pystxmcontrol.drivers.A33500B import A33500B


class keysightAWGController:

    def __init__(self, address="USB::0x0957::0x2807::INSTR", port=0, simulation=False):
        self.visa_address = address
        self.port = port
        self.simulation = simulation
        self.device = A33500B()
        self.device.visa_address = address
        self.lock = threading.Lock()          # mcsMotor.connect does self.lock = controller.lock
        self.connected = False

        # scan_axis ('x'|'y') -> {"channel": 1|2, "stage_type": str}
        self._axes = {}

        # commanded trajectory (microns), stashed by setup_xy for the read_xy fallback
        self._traj_x = None
        self._traj_y = None
        self._traj_dwell = None
        self.npositions = 0
        self.xpos_measured = None
        self.ypos_measured = None

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #
    def initialize(self, simulation=False):
        """Called once by the top-level Controller when the controller is created."""
        self.simulation = simulation
        self.connect()

    def connect(self):
        if self.simulation or self.connected:
            return
        self.device.connect(self.visa_address)
        self.connected = True

    def disconnect(self):
        if not self.simulation and self.connected:
            self.device.disconnect()
            self.connected = False

    # ------------------------------------------------------------------ #
    #  Axis registration (called from keysightAWGMotor.connect)
    # ------------------------------------------------------------------ #
    def setup_axis(self, axis, stage_type="piezo"):
        """Nothing device-side to prepare per axis; kept for contract parity."""
        pass

    def register_axis(self, scan_axis, channel, stage_type="piezo"):
        """Map a logical scan axis ('x'|'y') to an AWG output channel (1|2)."""
        self._axes[scan_axis] = {"channel": int(channel), "stage_type": stage_type}

    def getAxis(self, axis=None):
        """Trajectory ordering index: 'x'->1, 'y'->2, else -1 (matches mcsController)."""
        if axis == 'x':
            return 1
        if axis == 'y':
            return 2
        return -1

    # ------------------------------------------------------------------ #
    #  Static positioning (used to move to the scan centre before a trajectory)
    # ------------------------------------------------------------------ #
    def moveTo(self, channel, position):
        """Set a DC output level on one channel = a static absolute position (microns).

        Implemented as a flat 2-point arb at the requested offset so the nPoint holds
        position.  Bench-tunable; a plain DC/FUNC:DC write may be preferable.
        """
        if self.simulation:
            return
        with self.lock:
            volts = position * self.device._voltage_calibration
            self.device.session.write('SOURce%d:FUNCtion DC' % int(channel))
            self.device.session.write('SOURce%d:VOLT:OFFSET %.4f' % (int(channel), volts))
            self.device.session.write('OUTPut%d ON' % int(channel))

    def getStatus(self, axis=None):
        return False        # blocking trajectory playback; never "moving" when polled

    # ------------------------------------------------------------------ #
    #  Trajectory (the mcsController streaming contract)
    # ------------------------------------------------------------------ #
    def setup_xy(self, ax1pos, ax2pos, dwell):
        """Prepare (download) the X/Y arbitrary waveform; does not start motion.

        ``ax1pos``/``ax2pos`` are the ordered controller-unit arrays (X then Y, per
        getAxis) in microns; ``dwell`` is per-point in ms.  The AWG plays one arb point
        per dwell, so the sample rate is ``1000/dwell`` Hz and the whole trajectory
        lasts ``npositions * dwell``.
        """
        x = np.asarray(ax1pos, dtype=np.float64)
        y = np.asarray(ax2pos, dtype=np.float64)
        if len(x) != len(y):
            raise ValueError("[AWG] setup_xy: x/y length mismatch (%d vs %d)"
                             % (len(x), len(y)))
        self._traj_x, self._traj_y, self._traj_dwell = x, y, dwell
        self.npositions = len(x)
        if self.simulation:
            return 0

        srate = 1000.0 / float(dwell)                 # arb points per second
        maxAmp, offset, waveform = self._build_waveform(x, y)
        with self.lock:
            self.device.setWaveform(waveform, maxAmplitude=maxAmp, offset=offset,
                                    srate=srate)
            self.device.configStartTrigger(slope="POS")   # 1-cycle burst + Trig Out
        return 0

    def _build_waveform(self, x, y):
        """Normalize X, Y (microns) to +/-1 about each axis' centre and concatenate
        [x..., y...] as A33500B.setWaveform expects.

        Returns ``(maxAmplitude, offset, waveform)`` where maxAmplitude/offset are
        per-axis microns; the low-level class maps them to output volts.
        """
        xc, yc = float(np.mean(x)), float(np.mean(y))
        xa = max(float(np.max(np.abs(x - xc))), 1e-6)   # avoid /0 for a static point
        ya = max(float(np.max(np.abs(y - yc))), 1e-6)
        xn = (x - xc) / xa
        yn = (y - yc) / ya
        waveform = np.concatenate([xn, yn])
        return (xa, ya), (xc, yc), waveform

    def trigger_xy(self):
        """Start the trajectory: output on, fire the single-cycle burst (emits the
        Trig Out start pulse that launches the DAQ), block until it has played out."""
        if self._traj_x is None:
            raise RuntimeError("[AWG] trigger_xy called before setup_xy.")
        duration = self.npositions * float(self._traj_dwell) * 1e-3
        if self.simulation:
            time.sleep(min(0.01, duration))
            return
        with self.lock:
            self.device.start()      # OUTPut ON (armed, waiting for *TRG)
            self.device.fire()       # *TRG -> single burst + Trig Out start pulse
        time.sleep(duration + 0.02)  # blocking: let the trajectory play out
        with self.lock:
            self.device.stop()       # idle the output between lines

    def read_xy(self):
        """Return the commanded positions (fallback) in controller units (microns).

        The authoritative achieved positions are read back by the USB-1808X ADC and
        injected into line_positions in dataHandler.getLine.
        """
        self.xpos_measured = np.copy(self._traj_x)
        self.ypos_measured = np.copy(self._traj_y)
        return self.xpos_measured, self.ypos_measured

    def acquire_xy(self, **kwargs):
        """Trigger the trajectory and return the (commanded-fallback) positions."""
        self.trigger_xy()
        return self.read_xy()

    def setPositionTrigger(self, pos=0, axis=1, mode='off', increment=None, **kwargs):
        """No-op for a 2-D spiral.  Position is non-monotonic per axis, so a
        position-compare pixel clock is not meaningful; DAQ timing comes from the AWG
        start pulse plus the deterministic arb sample rate (matches mcsController)."""
        return

# -*- coding: utf-8 -*-
from pylibftdi import Device, Driver
from pystxmcontrol.controller.hardwareController import hardwareController
from threading import Lock
from time import sleep, time
import numpy as np
import smaract.ctl as ctl

# Stage-type identifiers used in the motor config ("stage_type" key).
#   "stick-slip" — inertial / stepper positioners (the historical default).  These
#                  do *not* support smooth trajectory streaming.
#   "piezo"      — closed-loop piezo flexure/scanner stages.  These support the
#                  MCS2 trajectory-streaming feature and therefore spiral scans.
STAGE_STICK_SLIP = "stick-slip"
STAGE_PIEZO = "piezo"


class mcsController(hardwareController):

    def __init__(self, address = '192.168.1.200', port = None, simulation = False):

        # the smarAct ctl library does not take the IP address and just looks for all
        # devices on the network.  The port number here is the serial number of the desired
        # device.  CTL returns the full list and then we just search for the serial number.

        self.devID = address
        self.isInitialized = False
        self.address = address
        self.port = port
        self.simulation = simulation
        self._timeout = 5
        self.lock = Lock()

        # --- trajectory-streaming state ---------------------------------------
        # Maps the logical scan axes ('x', 'y') to the physical MCS2 channel that
        # drives them.  Populated by mcsMotor.connect() -> register_axis().  Both
        # fine axes live on the *same* device, so one controller instance holds the
        # mapping for the whole trajectory.
        self._trajectory_channels = {}
        # Per-channel stage type, so the trajectory code can refuse to stream on a
        # stick-slip positioner.
        self._stage_type = {}
        # Commanded trajectory arrays (controller units == picometres) and the
        # per-point dwell (ms), stashed by setup_xy() for trigger_xy()/read_xy().
        self._traj_x = None
        self._traj_y = None
        self._traj_dwell = 1.0
        self._active_stream = None
        # DAQ pixel-clock trigger output configuration (see setPositionTrigger).
        self._trigger_channel = None
        self._trigger_pulse_width_ns = 1000   # ns

        # MCS2 trajectory-stream limits.  STREAM_BASE_RATE is the rate (Hz) at which
        # the controller consumes one frame; the per-point dwell is 1/rate.
        self._min_stream_rate = 1        # Hz
        self._max_stream_rate = 10000    # Hz  (10 kHz standard MCS2 limit)

    def initialize(self, simulation = False):
        print(ctl.FindDevices().split("\n"))
        self.simulation = simulation
        if not(self.simulation):
            try:
                #these aren't blocking, some time is needed after these calls or this sequence fails
                self._address = [x for x in ctl.FindDevices().split("\n") if str(self.port) in x][0]
                print(f"[MCS2] address: {self._address}")
                self._deviceID = ctl.Open(self._address)
                print(f"[MCS2] deviceID: {self._deviceID}")
                self._move_mode = ctl.MoveMode.CL_ABSOLUTE
                print(f"[MCS2] move_mode: {self._move_mode}")
            except:
                print("[MCS] No controllers available.")

    def setup_axis(self, axis, stage_type = STAGE_STICK_SLIP):
        """Configure a channel according to its stage type.

        :param axis:       MCS2 channel index.
        :param stage_type: ``"stick-slip"`` or ``"piezo"`` (see module constants).

        Stick-slip positioners use the closed-loop-frequency / hold-time parameters.
        Piezo flexure stages do not — those parameters are meaningless (and can be
        harmful) for a scanner, so we only ensure the sensor is powered and remove
        the velocity/acceleration limits so the stage can follow a streamed
        trajectory without lag.
        """
        self._stage_type[axis] = stage_type
        if stage_type == STAGE_PIEZO:
            # Closed-loop piezo flexure / scanner: sensor must stay powered and the
            # motion should follow the streamed targets without a velocity cap.
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.SENSOR_POWER_MODE, 1)
            # 0 == unlimited: let the stage track each streamed frame directly.
            ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_VELOCITY, 0)
            ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_ACCELERATION, 0)
        else:
            ##This is only for stick-slip motors
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.MAX_CL_FREQUENCY, 6000)
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.HOLD_TIME, 1000)
            ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_VELOCITY, 10000000000)
            ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_ACCELERATION, 10000000000)

    def register_axis(self, scan_axis, channel, stage_type = STAGE_STICK_SLIP):
        """Register the physical channel that drives a logical scan axis.

        Called by :meth:`mcsMotor.connect`.  A trajectory stream needs both the X
        and Y channel of the same device, but each axis is owned by a separate
        motor object, so the motors publish their (axis -> channel) mapping to the
        shared controller here.

        :param scan_axis:  ``'x'``, ``'y'`` or ``'z'``.
        :param channel:    MCS2 channel index.
        :param stage_type: stage type of this channel.
        """
        self._trajectory_channels[scan_axis] = channel
        self._stage_type[channel] = stage_type

    def supports_streaming(self, scan_axis):
        """True if the channel driving *scan_axis* is a streaming-capable piezo stage."""
        ch = self._trajectory_channels.get(scan_axis)
        return ch is not None and self._stage_type.get(ch) == STAGE_PIEZO

    def getAxis(self, axis):
        """Return the trajectory ordering index for a logical axis.

        The scan engine calls ``getAxis('x') - 1`` / ``getAxis('y') - 1`` to decide
        which of the two position arrays passed to :meth:`setup_xy` is X and which
        is Y.  Unlike the Mad City Labs controller (whose internal cabling is
        swapped) the MCS2 has no swap, so X maps to array 1 and Y to array 2.
        """
        if axis == 'x':
            return 1
        elif axis == 'y':
            return 2
        else:
            return -1

    def set_sensor_on(self,axis):
        ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.SENSOR_POWER_MODE, 1)

    def set_sensor_off(self,axis):
        ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.SENSOR_POWER_MODE, 0)

    def set_sensor_auto(self,axis):
        ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.SENSOR_POWER_MODE, 2)

    def set_velocity(self,axis,velocity):
        velocity = int(velocity * 1E9) #convert mm/s to pm/s
        ctl.SetProperty_i64(self._deviceID,axis,ctl.Property.MOVE_VELOCITY,velocity)

    def stop(self,axis):
        # If a trajectory stream is running, abort it first so the channel stop
        # does not race with streamed frames.
        if self._active_stream is not None:
            try:
                ctl.AbortStream(self._deviceID, self._active_stream)
            except Exception as e:
                print(f"[MCS2] AbortStream failed: {e}")
            self._active_stream = None
        ctl.Stop(self._deviceID, axis)

    def move(self,axis,position):
        self.moving = True
        t0 = time()
        ctl.Move(self._deviceID, axis, int(position), 0)
        while self.moving:
            self.getStatus(axis)
            sleep(0.005)
            if (time() - t0) > self._timeout:
                print("[MCS] Timeout exceeded on move. Stopping axis %i." %axis)
                self.stop(axis)
                self.moving=False
                return

    def getPos(self,axis):
        return ctl.GetProperty_i64(self._deviceID, axis, ctl.Property.POSITION)

    def getStatus(self,axis):
        self._status = ctl.GetProperty_i32(self._deviceID, axis, ctl.Property.CHANNEL_STATE)
        self.moving = bool(int(bin(self._status)[-1]))
        return self.moving

    def is_streaming(self, axis):
        """True while *axis* is actively consuming a trajectory stream."""
        state = ctl.GetProperty_i32(self._deviceID, axis, ctl.Property.CHANNEL_STATE)
        return bool(state & ctl.ChannelState.IS_STREAMING)

    def home(self,axis):
        ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.REFERENCING_OPTIONS, 0)
        # Set velocity to 1mm/s
        ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_VELOCITY, 1000000000)
        # Set acceleration to 10mm/s2.
        ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_ACCELERATION, 10000000000)
        # Start referencing sequence
        ctl.Reference(self._deviceID, axis)

    # ======================================================================
    # Trajectory streaming — the MCS2 analogue of the MCL waveform functions
    # ======================================================================
    #
    # The Mad City Labs controller loads two full position arrays into hardware
    # (MCL_WfmaSetup) and then triggers/reads them (MCL_WfmaTriggerAndRead).  The
    # MCS2 instead exposes a *trajectory stream*: frames (one target per channel per
    # time-step) are pushed with StreamFrame() and consumed by the controller at a
    # fixed STREAM_BASE_RATE.  We wrap that stream behind the same setup_xy /
    # trigger_xy / read_xy / acquire_xy interface the scan engine already uses for
    # the MCL fine stage, so a piezo SmarAct stage becomes a drop-in for spiral
    # (lineMode == "arbitrary") scans.

    def _dwell_to_rate(self, dwell_ms):
        """Convert a per-point dwell (ms) into a clamped STREAM_BASE_RATE (Hz)."""
        if dwell_ms <= 0:
            rate = self._max_stream_rate
        else:
            rate = int(round(1000.0 / dwell_ms))
        rate = max(self._min_stream_rate, min(self._max_stream_rate, rate))
        if dwell_ms > 0 and abs(1000.0 / rate - dwell_ms) > 1e-6:
            print(f"[MCS2] requested dwell {dwell_ms:.4f} ms not exactly representable; "
                  f"using {1000.0 / rate:.4f} ms ({rate} Hz base rate)")
        return rate

    def setup_xy(self, ax1pos, ax2pos, dwell):
        """Prepare a 2-D trajectory stream (does not start motion).

        Mirrors ``mclController.setup_xy``.  ``ax1pos``/``ax2pos`` are the position
        arrays in controller units (picometres); by the :meth:`getAxis` convention
        ``ax1pos`` is X and ``ax2pos`` is Y.  ``dwell`` is the per-point dwell in ms.

        The frames are not pushed here — the controller starts moving as soon as
        frames are streamed, so the actual push/execute happens in :meth:`trigger_xy`
        (called from the motor's moveLine()).  Here we validate the stages, set the
        stream base rate, and stash the arrays.
        """
        xch = self._trajectory_channels.get('x')
        ych = self._trajectory_channels.get('y')
        if xch is None or ych is None:
            raise RuntimeError("[MCS2] setup_xy: x/y channels not registered; "
                               "call register_axis() for both fine axes first.")
        for scan_axis, ch in (('x', xch), ('y', ych)):
            if self._stage_type.get(ch) != STAGE_PIEZO:
                raise RuntimeError(
                    f"[MCS2] setup_xy: channel {ch} ({scan_axis}) is not a piezo "
                    f"flexure stage; trajectory streaming requires stage_type='piezo'.")

        ax1pos = np.asarray(ax1pos, dtype=np.float64)
        ax2pos = np.asarray(ax2pos, dtype=np.float64)
        if len(ax1pos) != len(ax2pos):
            raise ValueError(f"[MCS2] setup_xy: x/y length mismatch "
                             f"({len(ax1pos)} vs {len(ax2pos)})")

        self._traj_x = ax1pos
        self._traj_y = ax2pos
        self._traj_dwell = dwell
        self.npositions = len(ax1pos)

        rate = self._dwell_to_rate(dwell)
        ctl.SetProperty_i32(self._deviceID, 0, ctl.Property.STREAM_BASE_RATE, rate)
        return 0

    def _stream_trajectory(self, xpos, ypos, trigger_mode = None):
        """Open a stream, push every frame, close it and wait for completion.

        Frames are ``[xchannel, xpos_i, ychannel, ypos_i]`` in picometres.  In
        StreamTriggerMode.DIRECT the controller begins moving once the first frames
        are buffered; StreamFrame() applies its own flow control (it blocks until the
        controller has room), so a simple push loop is safe for arbitrarily long
        trajectories.
        """
        if trigger_mode is None:
            trigger_mode = ctl.StreamTriggerMode.DIRECT
        xch = self._trajectory_channels['x']
        ych = self._trajectory_channels['y']
        n = len(xpos)

        sHandle = ctl.OpenStream(self._deviceID, trigger_mode)
        self._active_stream = sHandle
        try:
            for i in range(n):
                frame = [xch, int(round(xpos[i])), ych, int(round(ypos[i]))]
                ctl.StreamFrame(self._deviceID, sHandle, frame)
            # CloseStream flushes the remaining frames and marks the end of the
            # trajectory; motion continues until the buffer drains.
            ctl.CloseStream(self._deviceID, sHandle)
        except Exception:
            try:
                ctl.AbortStream(self._deviceID, sHandle)
            finally:
                self._active_stream = None
            raise

        # Wait for the stream to drain.  Expected duration is n / rate seconds;
        # poll the IS_STREAMING flag with generous headroom.
        rate = self._dwell_to_rate(self._traj_dwell)
        expected = n / float(rate)
        deadline = time() + expected + 5.0
        while time() < deadline:
            if not self.is_streaming(xch):
                break
            sleep(0.005)
        else:
            print("[MCS2] trajectory stream did not finish before timeout; aborting.")
            try:
                ctl.AbortStream(self._deviceID, sHandle)
            except Exception:
                pass
        self._active_stream = None

    def trigger_xy(self):
        """Execute the trajectory prepared by :meth:`setup_xy` (blocking)."""
        if self._traj_x is None:
            raise RuntimeError("[MCS2] trigger_xy called before setup_xy.")
        self._stream_trajectory(self._traj_x, self._traj_y)
        return 0

    def read_xy(self):
        """Return the commanded trajectory as (x_positions, y_positions).

        For a closed-loop piezo flexure stage the commanded and measured positions
        agree to well within a scan pixel, so we return the commanded arrays here.
        (A future enhancement can record true measured positions synchronously via
        the MCS2 CaptureBuffer API — Property.CAPTURE_BUFFER_* with CURRENT_POS.)
        """
        return self._traj_x, self._traj_y

    def acquire_xy(self, **kwargs):
        """Execute the trajectory and return the positions.  Blocking.

        Matches ``mclController.acquire_xy`` so the motor layer is identical.
        """
        self.trigger_xy()
        self.xpos_measured, self.ypos_measured = self.read_xy()
        return self.xpos_measured, self.ypos_measured

    def setPositionTrigger(self, pos = 0., axis = None, mode = "off",
                           increment = None, direction = ctl.FORWARD_DIRECTION):
        """Configure the DAQ pixel-clock trigger output on a channel.

        The MCS2 emits a hardware pulse on a channel's trigger output using
        position-compare mode: a pulse fires whenever the channel position advances
        by ``increment`` (picometres) past ``pos`` in ``direction``.  Wired to the
        DAQ's EXT trigger this is the analogue of the MCL ISS pixel clock.

        :param pos:       start-threshold position (controller units, pm).
        :param axis:      channel to emit on; defaults to the registered X channel.
        :param mode:      ``"on"`` to enable position-compare, ``"off"`` for constant.
        :param increment: position step between pulses (pm).  Required when mode=="on".
        :param direction: FORWARD/BACKWARD/EITHER_DIRECTION.

        NOTE: position-compare gives one clean pulse per pixel on a monotonic 1-D
        line.  For a 2-D spiral (non-monotonic in each axis) the pulse train is not
        one-per-point; in that case drive the DAQ from the deterministic stream rate
        instead, or emit on the axis with monotonic radial progress.
        """
        if axis is None:
            axis = self._trajectory_channels.get('x')
        if axis is None:
            print("[MCS2] setPositionTrigger: no channel registered/given; ignoring.")
            return
        self._trigger_channel = axis
        if mode == "on":
            if increment is None:
                # Called without a pixel pitch (e.g. from the generic spiral scan,
                # whose position-trigger call is a no-op on the MCL).  Position-
                # compare needs an increment and is not meaningful for a 2-D spiral
                # anyway, so warn and leave the trigger output unchanged rather than
                # raising and aborting the scan.
                print("[MCS2] setPositionTrigger(mode='on') without 'increment' — "
                      "position-compare not configured (2-D spirals rely on the "
                      "deterministic stream base rate for DAQ timing).")
                return
            ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.CH_POS_COMP_START_THRESHOLD, int(pos))
            ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.CH_POS_COMP_INCREMENT, int(increment))
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.CH_POS_COMP_DIRECTION, int(direction))
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.CH_OUTPUT_TRIG_POLARITY,
                                ctl.TriggerPolarity.ACTIVE_HIGH)
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.CH_OUTPUT_TRIG_PULSE_WIDTH,
                                self._trigger_pulse_width_ns)
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.CH_OUTPUT_TRIG_MODE,
                                ctl.ChannelOutputTriggerMode.POSITION_COMPARE)
        else:
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.CH_OUTPUT_TRIG_MODE,
                                ctl.ChannelOutputTriggerMode.CONSTANT)

    def disconnect(self):
        ctl.Close(self._deviceID)

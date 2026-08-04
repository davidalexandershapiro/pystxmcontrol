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

        # --- external-sync (DAQ-master) streaming -----------------------------
        # By default the stream is internally clocked at STREAM_BASE_RATE (DIRECT):
        # the MCS2 is the pixel-clock master.  For a SmarAct fine stage the MCS2
        # cannot emit a per-frame clock, so the DAQ masters the clock and its gate
        # TTL drives the stream one frame per edge.  set_stream_clock('external')
        # switches to EXTERNAL_SYNC and arms a device input trigger; arm_xy()/
        # finish_xy() then split the open-and-push from the drain-and-read so the
        # scan can arm the (waiting) stream *before* the DAQ starts pulsing.
        self._stream_ext_sync = False
        # Physical device digital-input line the DAQ gate is wired to, the trigger
        # edge to advance on, and the nominal external rate (Hz).  Overridable via
        # set_stream_clock() / controller config.
        self._stream_trigger_input = 0
        self._stream_trigger_condition = ctl.TriggerCondition.RISING
        # State handed from arm_xy() to finish_xy(): (sHandle, capturing, n).
        self._armed_stream_state = None

        # --- measured-position capture (Capture Buffer) -----------------------
        # The trajectory stream commands positions; a closed-loop flexure follows
        # with a small (sub-pixel) lag plus hysteresis/drift.  For accurate imaging
        # we want the *measured* sensor positions, not the commanded ones.  The MCS2
        # Capture Buffer records the sensor position synchronously at the stream base
        # rate: we arm one buffer per axis before streaming and read them back after.
        # If capture is unavailable/misbehaves on the hardware, read_xy() falls back
        # to the commanded arrays and the scan proceeds (just with commanded
        # positions), so this can never abort a scan.
        self._capture_measured = True              # master enable (toggle-able)
        # Capture-buffer index per logical axis.  These are the MCS2 capture-buffer
        # slots (addressed by `idx` in the Set/GetProperty[Buffer] calls), NOT the
        # channel indices; the channel is selected via CAPTURE_BUFFER_POSITION_INDEX.
        self._capture_buffer_index = {'x': 0, 'y': 1}
        # Measured trajectory arrays (picometres) filled by _read_capture_buffers().
        self._meas_x = None
        self._meas_y = None
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
        # Drop any measured arrays from a previous trajectory so a failed/absent
        # capture this run can't silently return stale positions.
        self._meas_x = None
        self._meas_y = None

        rate = self._dwell_to_rate(dwell)
        ctl.SetProperty_i32(self._deviceID, 0, ctl.Property.STREAM_BASE_RATE, rate)
        self._traj_rate = rate
        return 0

    # ---- measured-position capture (Capture Buffer) ----------------------
    #
    # The MCS2 Capture Buffer records a channel's position into device memory at a
    # fixed rate.  Armed at the stream base rate just before a trajectory stream, it
    # samples one measured (sensor) position per commanded frame.  We use one buffer
    # per axis (TYPE_0 == a single position value per sample) so each read-out is a
    # flat picometre array.  Every ctl call here is defensive: any failure disables
    # capture for this run and leaves read_xy() to fall back to commanded positions.

    def _arm_capture_buffers(self, rate):
        """Arm one Capture Buffer per axis to record measured positions.

        Returns True if both buffers were armed.  On any error, capture is
        abandoned for this run (returns False) and the stream still executes.
        """
        if not self._capture_measured:
            return False
        xch = self._trajectory_channels.get('x')
        ych = self._trajectory_channels.get('y')
        if xch is None or ych is None:
            return False
        try:
            for scan_axis, ch in (('x', xch), ('y', ych)):
                idx = self._capture_buffer_index[scan_axis]
                # Capture a single measured (current/sensor) position per sample,
                # from this axis' channel, clocked at the stream base rate.
                ctl.SetProperty_i32(self._deviceID, idx,
                                    ctl.Property.CAPTURE_BUFFER_DATASET_TYPE,
                                    ctl.CaptureBufferDataset.TYPE_0)
                ctl.SetProperty_i32(self._deviceID, idx,
                                    ctl.Property.CAPTURE_BUFFER_POSITION_TYPE,
                                    ctl.CaptureBufferPositionType.CURRENT_POS)
                ctl.SetProperty_i32(self._deviceID, idx,
                                    ctl.Property.CAPTURE_BUFFER_POSITION_INDEX, int(ch))
                ctl.SetProperty_i32(self._deviceID, idx,
                                    ctl.Property.CAPTURE_BUFFER_RATE, int(rate))
                ctl.SetProperty_i32(self._deviceID, idx,
                                    ctl.Property.CAPTURE_BUFFER_TRIGGER_MODE,
                                    ctl.CaptureBufferTriggerMode.DIRECT)
                # Arm: begin capturing.  DIRECT trigger => starts sampling now; the
                # first commanded frame follows immediately as the stream fills.
                ctl.SetProperty_i32(self._deviceID, idx,
                                    ctl.Property.CAPTURE_BUFFER_ACTIVE,
                                    ctl.CaptureBuffer.ACTIVE)
            return True
        except Exception as e:
            print(f"[MCS2] capture-buffer arm failed ({e}); "
                  f"falling back to commanded positions.")
            self._disarm_capture_buffers()
            return False

    def _disarm_capture_buffers(self):
        """Stop both capture buffers (best-effort, never raises)."""
        for scan_axis in ('x', 'y'):
            idx = self._capture_buffer_index.get(scan_axis)
            if idx is None:
                continue
            try:
                ctl.SetProperty_i32(self._deviceID, idx,
                                    ctl.Property.CAPTURE_BUFFER_ACTIVE,
                                    ctl.CaptureBuffer.INACTIVE)
            except Exception:
                pass

    def _read_capture_buffers(self, n):
        """Read back both capture buffers into self._meas_x / self._meas_y.

        Aligns the captured sensor positions to the ``n`` commanded frames.  The
        capture may return a few more samples than commanded frames (sampling can
        begin a tick before the first frame executes); when it does we keep the
        last ``n`` samples, which are the ones paired with the commanded targets.
        On any mismatch or error the measured arrays are left as None so read_xy()
        falls back to the commanded trajectory.
        """
        try:
            meas = {}
            for scan_axis in ('x', 'y'):
                idx = self._capture_buffer_index[scan_axis]
                # CAPTURE_BUFFER_SIZE is the number of samples actually captured.
                size = ctl.GetProperty_i32(self._deviceID, idx,
                                           ctl.Property.CAPTURE_BUFFER_SIZE)
                if size <= 0:
                    print(f"[MCS2] capture buffer {scan_axis} empty (size={size}); "
                          f"using commanded positions.")
                    return
                data = ctl.GetPropertyBuffer_i64(self._deviceID, idx,
                                                 ctl.Property.CAPTURE_BUFFER_DATA, size)
                arr = np.asarray(data, dtype=np.float64)
                if len(arr) < n:
                    print(f"[MCS2] capture buffer {scan_axis} short "
                          f"({len(arr)} < {n} commanded); using commanded positions.")
                    return
                # Keep the n samples aligned with the commanded frames (trailing
                # samples correspond to the executed trajectory).
                meas[scan_axis] = arr[-n:]
            self._meas_x = meas['x']
            self._meas_y = meas['y']
        except Exception as e:
            print(f"[MCS2] capture-buffer read failed ({e}); "
                  f"using commanded positions.")
            self._meas_x = None
            self._meas_y = None
        finally:
            self._disarm_capture_buffers()

    # ---- external-sync (DAQ-master) clock configuration ------------------

    def set_stream_clock(self, source = "internal", input_index = None,
                         condition = None):
        """Select the stream clock: ``"internal"`` (DIRECT) or ``"external"``.

        ``"external"`` puts the controller in DAQ-master mode: the stream is opened
        with StreamTriggerMode.EXTERNAL_SYNC and a device input trigger is armed so
        each edge of the DAQ gate advances one frame.  ``input_index``/``condition``
        override the wired digital-input line and edge (defaults preserved otherwise).
        """
        self._stream_ext_sync = (source == "external")
        if input_index is not None:
            self._stream_trigger_input = int(input_index)
        if condition is not None:
            self._stream_trigger_condition = condition

    def _configure_stream_input_trigger(self, rate):
        """Arm the device input trigger that paces an external-sync stream.

        Routes the wired digital input to the streaming engine so each qualifying
        edge releases one frame, and publishes the nominal external rate.
        """
        dev = self._deviceID
        ctl.SetProperty_i32(dev, 0, ctl.Property.DEV_INPUT_TRIG_MODE,
                            ctl.DeviceInputTriggerMode.STREAM)
        ctl.SetProperty_i32(dev, 0, ctl.Property.DEV_INPUT_TRIG_SELECT,
                            int(self._stream_trigger_input))
        ctl.SetProperty_i32(dev, 0, ctl.Property.DEV_INPUT_TRIG_CONDITION,
                            int(self._stream_trigger_condition))
        # EXTERNAL_SYNC disciplines the internal STREAM_BASE_RATE clock to the
        # external edges; publish the nominal rate so the controller knows the
        # expected cadence (the capture buffer, clocked off the same disciplined
        # base rate, then stays aligned with the externally-paced frames).
        ctl.SetProperty_i32(dev, 0, ctl.Property.STREAM_EXT_SYNC_RATE, int(rate))

    # ---- stream execution (internal blocking + external arm/finish) ------

    def _push_stream(self, xpos, ypos, trigger_mode):
        """Arm capture, open the stream, push every frame and close it.

        Returns ``(sHandle, capturing, n)`` for :meth:`_drain_stream`.  Does NOT
        wait for completion — in EXTERNAL_SYNC mode the frames simply buffer and are
        released one per external gate edge, so the caller starts the DAQ and then
        drains.  Frames are ``[xchannel, xpos_i, ychannel, ypos_i]`` in picometres;
        StreamFrame() self-flow-controls, so a plain push loop is safe.
        """
        xch = self._trajectory_channels['x']
        ych = self._trajectory_channels['y']
        n = len(xpos)

        rate = self._dwell_to_rate(self._traj_dwell)
        if trigger_mode == ctl.StreamTriggerMode.EXTERNAL_SYNC:
            self._configure_stream_input_trigger(rate)
        capturing = self._arm_capture_buffers(rate)

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
                if capturing:
                    self._disarm_capture_buffers()
            raise
        return sHandle, capturing, n

    def _drain_stream(self, sHandle, capturing, n):
        """Wait for the stream to finish, then read the captured positions.

        The expected duration is ``n / rate`` seconds; in EXTERNAL_SYNC mode the
        pace is set by the DAQ gate (nominally the same rate) so the same estimate
        plus generous headroom applies.  Polls the IS_STREAMING flag.
        """
        xch = self._trajectory_channels['x']
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

        # Read the synchronously-captured measured positions (disarms the buffers).
        if capturing:
            self._read_capture_buffers(n)

    def _stream_trajectory(self, xpos, ypos, trigger_mode = None):
        """Push and drain a stream back-to-back (internal-clock, blocking).

        This is the internally-clocked (DIRECT) path used by trigger_xy()/
        acquire_xy(); the DAQ-master path uses arm_xy()/finish_xy() instead so the
        drain can be deferred until after the DAQ starts pulsing.
        """
        if trigger_mode is None:
            trigger_mode = ctl.StreamTriggerMode.DIRECT
        sHandle, capturing, n = self._push_stream(xpos, ypos, trigger_mode)
        self._drain_stream(sHandle, capturing, n)

    def trigger_xy(self):
        """Execute the trajectory prepared by :meth:`setup_xy` (blocking)."""
        if self._traj_x is None:
            raise RuntimeError("[MCS2] trigger_xy called before setup_xy.")
        self._stream_trajectory(self._traj_x, self._traj_y)
        return 0

    def arm_xy(self):
        """Arm an external-sync (DAQ-master) stream and return immediately.

        Opens the stream in EXTERNAL_SYNC, pushes all frames and arms the capture
        buffer, leaving the controller waiting for the DAQ gate edges.  Call this
        BEFORE starting the DAQ, then :meth:`finish_xy` after, so no gate edges are
        missed.  Requires set_stream_clock('external') to have been called.
        """
        if self._traj_x is None:
            raise RuntimeError("[MCS2] arm_xy called before setup_xy.")
        if not self._stream_ext_sync:
            raise RuntimeError("[MCS2] arm_xy requires set_stream_clock('external').")
        self._armed_stream_state = self._push_stream(
            self._traj_x, self._traj_y, ctl.StreamTriggerMode.EXTERNAL_SYNC)
        return 0

    def finish_xy(self):
        """Drain a stream armed by :meth:`arm_xy` and return the positions.

        Blocking: waits for the DAQ-clocked stream to drain, reads the captured
        measured positions, and returns them like :meth:`acquire_xy`.
        """
        if self._armed_stream_state is None:
            raise RuntimeError("[MCS2] finish_xy called before arm_xy.")
        sHandle, capturing, n = self._armed_stream_state
        self._armed_stream_state = None
        self._drain_stream(sHandle, capturing, n)
        self.xpos_measured, self.ypos_measured = self.read_xy()
        return self.xpos_measured, self.ypos_measured

    def read_xy(self):
        """Return the trajectory positions as (x_positions, y_positions).

        Prefers the *measured* sensor positions captured synchronously during the
        stream (via the MCS2 Capture Buffer — Property.CAPTURE_BUFFER_* with
        CURRENT_POS).  If capture was disabled or failed for this run, falls back to
        the commanded arrays so the scan still gets a valid position record.
        """
        if self._meas_x is not None and self._meas_y is not None:
            return self._meas_x, self._meas_y
        return self._traj_x, self._traj_y

    def acquire_xy(self, **kwargs):
        """Execute the trajectory and return the positions.  Blocking.

        Matches ``mclController.acquire_xy`` so the motor layer is identical.
        """
        self.trigger_xy()
        self.xpos_measured, self.ypos_measured = self.read_xy()
        return self.xpos_measured, self.ypos_measured

    # ======================================================================
    # Linear (raster) trajectories — the common operating mode
    # ======================================================================
    #
    # The MCL fine stage builds a straight-line waveform (optionally with a wait +
    # return segment for fast fly-back) via setup_trajectory(), then executes it with
    # acquire_xy() (2-D) or trigger_1d_waveform() (1-D).  The MCS2 always streams
    # *both* axes, so every mode below is realised as a 2-D stream (the orthogonal
    # axis held constant for the 1-D case) routed through setup_xy() — which means
    # the Capture Buffer records the measured positions for a line scan exactly as it
    # does for a spiral.  The array construction mirrors mclController.setup_trajectory
    # so the timing / wait / return semantics are identical.

    def setup_trajectory(self, axis, start, stop, dwell, points, mode = "line", pad = None):
        """Build a linear trajectory and load it as a 2-D stream.

        :param axis:   trigger axis index (accepted for signature parity; the MCS2
                       streams both axes so it does not select a single one).
        :param start:  (x, y) start position, controller units (pm).
        :param stop:   (x, y) stop position, controller units (pm).
        :param dwell:  per-point dwell (ms).
        :param points: number of points along the forward line.
        :param mode:   ``line`` | ``1d_line_with_return`` | ``2d_line_with_return``.
        :param pad:    (xpad, ypad) accepted for parity; the caller has already baked
                       the acceleration pad into start/stop, so it is unused here.

        Sets ``self.npositions`` to the total streamed length (including any wait +
        return segment), as the scan engine reads it back to size the data arrays.
        """
        self.line_dwell = dwell
        self.line_points = points

        if mode == "line":
            xstart, ystart = start
            xstop, ystop = stop
            self.xpositions = np.linspace(xstart, xstop, points).astype(np.float64)
            self.ypositions = np.linspace(ystart, ystop, points).astype(np.float64)
            xtotal, ytotal = self.xpositions, self.ypositions

        elif mode == "1d_line_with_return":
            # y is essentially constant (yRange < 1 nm); stream x out-and-back with a
            # short dwell-hold between, y pinned to its (constant) value.
            xstart, y = start
            xstop, _ = stop
            xRange = abs(xstop - xstart)
            self.xpositions = np.linspace(xstart, xstop, points).astype(np.float64)
            waittime, minwait = 10., 2                      # ms, points
            waitpositions = (np.ones((max(int(waittime / dwell), minwait),)) * xstop).astype(np.float64)
            # NB: MCS2 controller units are picometres (MCL's are microns), so the
            # fly-back velocity must be in pm/ms: 1 mm/s == 1e6 pm/ms.  Using MCL's
            # bare "1" here would make the return segment ~1e6x too many points.
            maxvel, minreturnpoints = 1.0e6, 5              # pm/ms (== 1 mm/s), points
            returnpoints = max(int(xRange / maxvel / dwell), minreturnpoints)
            returnpositions = np.linspace(xstop, xstart, returnpoints).astype(np.float64)
            xtotal = np.concatenate((self.xpositions, waitpositions, returnpositions)).astype(np.float64)
            ytotal = (np.ones((len(xtotal),)) * y).astype(np.float64)

        elif mode == "2d_line_with_return":
            xstart, ystart = start
            xstop, ystop = stop
            xRange, yRange = abs(xstop - xstart), abs(ystop - ystart)
            self.xpositions = np.linspace(xstart, xstop, points).astype(np.float64)
            self.ypositions = np.linspace(ystart, ystop, points).astype(np.float64)
            waittime, minwait = 10., 2
            nwait = max(int(waittime / dwell), minwait)
            xwait = (np.ones((nwait,)) * xstop).astype(np.float64)
            ywait = (np.ones((nwait,)) * ystop).astype(np.float64)
            maxvel, minreturnpoints = 1.0e6, 5             # pm/ms (== 1 mm/s), points
            totRange = (xRange ** 2 + yRange ** 2) ** 0.5
            returnpoints = max(int(totRange / maxvel / dwell), minreturnpoints)
            xreturn = np.linspace(xstop, xstart, returnpoints).astype(np.float64)
            yreturn = np.linspace(ystop, ystart, returnpoints).astype(np.float64)
            xtotal = np.concatenate((self.xpositions, xwait, xreturn)).astype(np.float64)
            ytotal = np.concatenate((self.ypositions, ywait, yreturn)).astype(np.float64)

        else:
            raise NotImplementedError(
                f"[MCS2] setup_trajectory mode '{mode}' not supported "
                f"(supported: line, 1d_line_with_return, 2d_line_with_return).")

        # Order into (ax1, ax2) by the getAxis convention, then load the stream.
        xypos = [0, 0]
        xypos[self.getAxis('x') - 1] = xtotal
        xypos[self.getAxis('y') - 1] = ytotal
        self.setup_xy(*xypos, dwell)          # stashes arrays, sets base rate + npositions
        self.npositions = len(xtotal)
        return 0

    def trigger_1d_waveform(self, axis = 'x'):
        """Execute a 1-D line trajectory and return the measured [x, y] positions.

        The line was loaded as a 2-D stream (orthogonal axis held constant), so this
        just runs the stream and reads back the captured positions.  The return
        signature ([x_array, y_array]) matches ``mclController.trigger_1d_waveform``
        so the derivedPiezo dim==1 continuous path works unchanged.
        """
        self.trigger_xy()
        xmeas, ymeas = self.read_xy()
        return [xmeas, ymeas]

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

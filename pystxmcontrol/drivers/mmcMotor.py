# -*- coding: utf-8 -*-
"""Micronix MMC axis driver (point-to-point + constant-velocity fly lines).

Lock-agnostic: the IOC layer's per-controller io_lock serializes all link
I/O. Software-timed fly lines (line_trigger = "IMM"): the MMC has no
trigger output, so the DAQ free-runs during the constant-velocity move.
"""
import time

from pystxmcontrol.controller.motor import motor, SoftwareLimitError
from pystxmcontrol.drivers.mmcController import MMCError

_AXIS_NUMBERS = {"x": 1, "y": 2, "z": 3}
_STATUS_STOPPED_BIT = 0x08  # STA? bit 3: axis stopped (legacy idle 8/136)


class mmcMotor(motor):

    #: DAQ trigger source for fly lines (fly_ioc reads this; the MMC has no
    #: hardware trigger output, so lines are software-timed by default).
    #: "IMM" is the 53230A TRIG:SOUR mnemonic for an immediate/internal
    #: (free-run) trigger; the instrument accepts IMM|EXT|BUS only.
    line_trigger = "IMM"

    def __init__(self, controller=None, config=None):
        self.controller = controller
        self.config = config
        self.simulation = False
        self.axis = None
        self._axis = 1
        self.moving = False
        self.velocity = 0.0
        # fly interface (duck-typed; see iocs/fly_ioc.py _run_line)
        self.lineMode = "raster"
        self.trajectory_start = (0.0, 0.0)
        self.trajectory_stop = (0.0, 0.0)
        self.trajectory_pixel_count = 10
        self.trajectory_pixel_dwell = 1.0  # ms per pixel
        self.npositions = 10
        self.line_velocity = 0.0
        self._line_start = 0.0
        self._line_stop = 0.0
        self._poll = 0.005
        # prepareLine()/moveLine() split state (see prepareLine docstring)
        self._prepared = False
        self._cruise_velocity = 0.0

    # ---- helpers -------------------------------------------------------
    def _to_controller(self, pos):
        return round((pos - self.config["offset"]) / self.config["units"], 3)

    def _from_controller(self, pos):
        return pos * self.config["units"] + self.config["offset"]

    # ---- point-to-point interface --------------------------------------
    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs:
            self.logger = kwargs["logger"]
        self.simulation = self.controller.simulation
        self.axis = axis
        self._axis = int(self.config.get("controller_index",
                                         _AXIS_NUMBERS.get(axis, 1)))
        self.setServo(True)
        return True

    def checkLimits(self, pos):
        lo, hi = self.config["minValue"], self.config["maxValue"]
        if pos < lo:
            raise SoftwareLimitError(self.axis, pos, lo, limit_type="lower")
        if pos > hi:
            raise SoftwareLimitError(self.axis, pos, hi, limit_type="upper")
        return True

    def getStatus(self, **kwargs):
        if self.simulation:
            return self.moving
        status = int(self.controller.query(self._axis, "STA?"))
        self.moving = not (status & _STATUS_STOPPED_BIT)
        return self.moving

    def getPos(self):
        if self.simulation:
            return self._from_controller(
                self.controller.positions.get(self._axis, 0.0))
        payload = self.controller.query(self._axis, "POS?")
        # closed-loop reply: "<theoretical>,<encoder>"; use the encoder
        # (last) field, which is also correct for single-field replies.
        return self._from_controller(float(payload.split(",")[-1]))

    def moveTo(self, pos):
        self.checkLimits(pos)
        if self.simulation:
            self.controller.positions[self._axis] = \
                (pos - self.config["offset"]) / self.config["units"]
            self.moving = False
            return
        self.controller.command(self._axis, f"MVA{self._to_controller(pos)}")
        timeout = float(self.config.get("timeout", 10))
        t0 = time.time()
        while self.getStatus():
            if time.time() - t0 > timeout:
                self.stop()
                raise MMCError(
                    f"MMC axis {self.axis} move to {pos} timed out after "
                    f"{timeout}s; controller errors: "
                    f"{self.controller.get_errors(self._axis)!r}")
            time.sleep(self._poll)

    def moveBy(self, step):
        self.moveTo(self.getPos() + step)

    def stop(self):
        if not self.simulation:
            self.controller.command(self._axis, "STP")
        self.moving = False

    def setAxisParams(self, velocity):
        self.velocity = round(float(velocity), 3)
        if self.simulation:
            self.controller.velocities[self._axis] = self.velocity
        else:
            self.controller.command(self._axis, f"VEL{self.velocity}")

    def get_velocity(self):
        if self.simulation:
            return self.controller.velocities.get(self._axis, self.velocity)
        payload = self.controller.query(self._axis, "VEL?")
        self.velocity = float(payload.split(",")[-1])
        return self.velocity

    def setServo(self, servo=True):
        if not self.simulation:
            self.controller.command(self._axis, f"FBK{3 if servo else 0}")

    def home(self):
        if not self.simulation:
            self.controller.command(self._axis, "HOM")

    def configure_home(self, direction=0):
        if not self.simulation:
            self.controller.command(self._axis, f"HCG{int(direction)}")

    # ---- fly interface (duck-typed; driven by iocs/fly_ioc.py) ---------
    def update_trajectory(self, direction="forward", include_return=False):
        """Compute the constant velocity for a software-timed fly line.

        The MMC flies one axis at constant velocity; the fast axis is
        whichever trajectory slot varies (fly_ioc holds the other constant).
        """
        x0, y0 = self.trajectory_start
        x1, y1 = self.trajectory_stop
        if abs(x1 - x0) >= abs(y1 - y0):
            start, stop = x0, x1
        else:
            start, stop = y0, y1
        if direction == "backward":
            start, stop = stop, start
        if stop == start:
            raise MMCError("fly line has zero span (start == stop)")
        line_time = self.trajectory_pixel_count * self.trajectory_pixel_dwell / 1000.0
        if line_time <= 0:
            raise MMCError("fly line has non-positive duration")
        velocity = abs(stop - start) / line_time / abs(self.config["units"])
        max_v = self.config.get("max velocity")
        if max_v and velocity > float(max_v):
            raise MMCError(
                f"fly line needs {velocity:.3f} units/s > max velocity "
                f"{max_v}; increase dwell or shorten the line")
        self._line_start, self._line_stop = start, stop
        self.line_velocity = velocity
        self.npositions = self.trajectory_pixel_count

    def prepareLine(self):
        """Pre-position for a fly line WITHOUT starting it.

        Splits moveLine so fly_ioc can pre-position before arming the DAQ:
        with an IMM (free-run) trigger, initLine starts acquisition
        immediately, so the (blocking) move to the line start must happen
        first. Stashes the cruise velocity, moves to the line start, and
        sets the line velocity; a following moveLine() then only issues the
        constant-velocity move. Runs under fly_ioc's io_lock in an executor
        thread.
        """
        if self.simulation:
            self._prepared = True
            return
        # Abort window: if the line is aborted between prepareLine and
        # moveLine (e.g. during the DAQ arm or beam-open stage), the axis is
        # left at line velocity with _prepared still True until the next
        # completed line's finally restores cruise. Only stash cruise when
        # not already prepared, so a re-prepare after such an abort reuses
        # the ORIGINAL cruise velocity instead of stashing the still-set
        # line velocity and losing the operator's setting.
        if not self._prepared:
            self._cruise_velocity = self.get_velocity()
        self.moveTo(self._line_start)
        self.setAxisParams(velocity=self.line_velocity)
        self._prepared = True

    def moveLine(self, **kwargs):
        """Blocking constant-velocity line move (runs under fly_ioc's
        io_lock in an executor thread). DAQ acquisition free-runs
        concurrently (line_trigger = "IMM").

        Self-contained when called cold; after prepareLine() it skips the
        re-positioning/velocity setup and only commands the line move."""
        line_time = self.trajectory_pixel_count * self.trajectory_pixel_dwell / 1000.0
        if self.simulation:
            self._prepared = False
            time.sleep(min(line_time, 0.1))
            self.controller.positions[self._axis] = \
                (self._line_stop - self.config["offset"]) / self.config["units"]
            return
        if self._prepared:
            cruise = self._cruise_velocity
        else:
            cruise = self.get_velocity()
            self.moveTo(self._line_start)
            self.setAxisParams(velocity=self.line_velocity)
        try:
            self.controller.command(
                self._axis, f"MVA{self._to_controller(self._line_stop)}")
            deadline = time.time() + max(5.0, line_time * 4.0 + 5.0)
            while self.getStatus():
                if time.time() > deadline:
                    self.stop()
                    raise MMCError(
                        f"MMC fly line on axis {self.axis} stalled "
                        f"(no completion within {line_time * 4 + 5:.1f}s)")
                time.sleep(self._poll)
        finally:
            self._prepared = False
            try:
                self.setAxisParams(velocity=cruise)
            except Exception as e:
                # Never mask the original line error with a restore failure.
                print(f"MMC axis {self.axis}: cruise velocity restore "
                      f"failed: {e}", flush=True)

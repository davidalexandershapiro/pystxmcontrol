from pystxmcontrol.drivers.mcsController import mcsController, STAGE_STICK_SLIP
from time import sleep, time
import smaract.ctl as ctl


class mcsRelativeController(mcsController):
    """MCS2 controller variant for the one instrument whose positioner only honors
    RELATIVE moves.

    Background
    ----------
    On every other SmarAct MCS2 beamline ``ctl.Move(dev, axis, target, 0)`` lands at
    the absolute target.  On this one instrument the positioner has no usable absolute
    reference, so an absolute command goes to the wrong physical location; only
    relative moves behave correctly.  Rather than branch the canonical
    :class:`mcsController` (which now also carries the spiral trajectory-streaming
    feature) with a per-instrument flag, this outlier is isolated in its own driver.

    The ONLY behavioural difference is :meth:`move`: an absolute target is translated
    into a relative delta from the current position before it is sent to the
    controller.  All other behaviour — trajectory streaming, status polling, sensor
    control, ``getPos`` — is inherited unchanged, so bug fixes to the canonical driver
    propagate here automatically.

    Wiring
    ------
    Select this variant purely from the instrument's ``motor.json`` — keep
    ``"driver": "mcsMotor"`` and set ``"controller": "mcsRelativeController"`` on that
    instrument's axes.  No code elsewhere needs to change.

    Note on determinism
    -------------------
    This reproduces the field-tested behaviour, which relies on the controller's
    *persisted* move mode already being relative.  To make it self-contained instead
    of depending on persisted hardware state, set ``force_relative_mode = True`` (see
    :meth:`setup_axis`); leave it ``False`` until the explicit ``MOVE_MODE`` write has
    been confirmed on the hardware.
    """

    #: When True, explicitly program each channel to CL_RELATIVE at setup instead of
    #: trusting the controller's persisted move mode.  Opt-in until verified on the box.
    force_relative_mode = False

    def setup_axis(self, axis, stage_type=STAGE_STICK_SLIP):
        super().setup_axis(axis, stage_type=stage_type)
        if self.force_relative_mode:
            # Program the channel to interpret Move() values as relative deltas.
            ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.MOVE_MODE,
                                ctl.MoveMode.CL_RELATIVE)

    def move(self, axis, position):
        """Move *axis* to the absolute *position* (controller units, picometres) by
        issuing the equivalent RELATIVE move."""
        self.moving = True
        t0 = time()
        # Translate the absolute target into a delta from where we are now.
        delta = int(round(position - self.getPos(axis)))
        ctl.Move(self._deviceID, axis, delta, 0)
        while self.moving:
            self.getStatus(axis)
            sleep(0.005)
            if (time() - t0) > self._timeout:
                print("[MCS] Timeout exceeded on move. Stopping axis %i." % axis)
                self.stop(axis)
                self.moving = False
                return

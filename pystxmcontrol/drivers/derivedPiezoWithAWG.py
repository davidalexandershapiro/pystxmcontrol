"""
Derived piezo motor whose trajectories are played by a Keysight 33500B AWG as
RELATIVE motion, while static positioning stays on the nPoint digital interface.

Motivation
----------
Bench testing showed the nPoint piezo controller treats the AWG analogue waveform as
an *offset added to its current commanded position*, not an absolute position command.
So a spiral cannot be executed by baking the scan centre into the AWG waveform (the
relative-summing nPoint would double-count it).  Instead:

  * the nPoint DIGITAL interface (``nptMotor``/``nptController``) moves the stage to the
    absolute scan-region CENTRE, and
  * the AWG (``keysightAWGController``) plays a ZERO-CENTRED dither that the nPoint sums
    onto that held centre.

This driver encapsulates exactly that split so the EXISTING ``derived_spiral_image``
fly-scan routine drives it unchanged.  For simple moves it behaves identically to
``derivedPiezo`` (digital nPoint fine + coarse); only ``lineMode == 'arbitrary'``
trajectories use the AWG.

Axis wiring (motor.json)
------------------------
    SampleX: {type: derived, driver: derivedPiezoWithAWG,
              axes: {axis1: nptFineX, axis2: CoarseX, axis3: AWGFineX}}

  * axis1 = nPoint digital fine (``nptMotor``) -> keeps ALL inherited position/move
    methods correct (moveTo/getPos/decompose_range/coarse tiling) with no override.
  * axis2 = coarse (``xpsMotor``).
  * axis3 = AWG (``keysightAWGMotor``) -> trajectory dither only.

The AWG leaf (axis3) MUST be configured ``units=1.0``/``offset=0.0`` so the fine centre
read from the shared nPoint controller and the trajectory arrays live in the same micron
frame; likewise the nPoint leaves should be ``units=1.0``/``offset=0.0``.  The AWG spiral
is stage-master (the AWG emits its own start pulse), so the scan config must set
``daq_master=False``.
"""

import numpy as np

from pystxmcontrol.drivers.derivedPiezo import derivedPiezo


class derivedPiezoWithAWG(derivedPiezo):

    def __init__(self, controller=None, simulation=False):
        super().__init__(controller=controller, simulation=simulation)
        # Fine centre (micron) the nPoint is holding for the current trajectory; captured
        # in update_trajectory and used to reconstruct absolute fallback positions.
        self._awg_center = (0.0, 0.0)

    # ------------------------------------------------------------------ #
    #  Trajectory (arbitrary/AWG) -- everything else inherited from derivedPiezo
    # ------------------------------------------------------------------ #
    def update_trajectory(self, direction="forward", include_return=False):
        """Arbitrary mode: play the trajectory as a zero-centred AWG dither about the
        nPoint-held centre.  All other line modes fall through to the base nPoint path."""
        if self.lineMode != 'arbitrary':
            return super().update_trajectory(direction=direction,
                                             include_return=include_return)

        awg = self.axes["axis3"]                       # keysightAWGMotor
        nc = self.axes["axis1"].controller             # shared nptController
        tx = np.asarray(self.trajectory_x_positions, dtype=float)
        ty = np.asarray(self.trajectory_y_positions, dtype=float)

        # Fine-only centre the nPoint is holding (the scan's moveMotor put it there before
        # the chunk loop).  Read from the shared controller so BOTH x and y come from the
        # same micron frame -- self.getPos() would add the coarse position and bias the
        # dither, and self (the X derived motor) does not hold the Y fine centre at all.
        if awg.simulation:
            cx = cy = 0.0                              # no device read in simulation
        else:
            cx = nc.getPos(axis=nc.getAxis('x'))
            cy = nc.getPos(axis=nc.getAxis('y'))
        self._awg_center = (cx, cy)
        self.npositions = len(tx)
        self.trajectory_trigger = tx[0], ty[0]
        if awg.simulation:
            return

        # Zero-centred dither (microns); AWG leaf is units=1/offset=0 so this passes
        # straight through to the controller frame.
        relx = tx - cx
        rely = ty - cy
        axc = awg.controller
        order = [axc.getAxis('x') - 1, axc.getAxis('y') - 1]
        ax1pos, ax2pos = [[relx, rely][i] for i in order]

        # FIXED normalization: offset (0,0) => pure zero-DC dither the nPoint sums onto its
        # held centre; a fixed full-scale amplitude keeps every chunk of a split spiral on
        # one centre and gain so the segments stitch into a continuous figure.  (16-bit arb
        # -> a small dither on the full scale still resolves finely.)
        fs = abs(float(awg.config["maxValue"]))
        axc.setup_xy(ax1pos, ax2pos, self.trajectory_pixel_dwell,
                     amplitude=(fs, fs), offset=(0.0, 0.0))
        return

    def moveLine(self, **kwargs):
        """Arbitrary mode: fire the AWG and reconstruct absolute fallback positions.
        Other line modes fall through to the base nPoint path."""
        if self.lineMode != 'arbitrary':
            return super().moveLine(**kwargs)

        offset = kwargs.get("coarse_offset", [0, 0])
        awg = self.axes["axis3"]
        cx, cy = self._awg_center
        if not awg.simulation:
            # acquire_xy returns the RELATIVE commanded dither (microns); absolute =
            # dither + fine centre + coarse offset.  This fallback only matters when no
            # position-readback DAQ is attached -- otherwise dataHandler.getLine overwrites
            # line_positions from the USB-1808X aux_data.
            acq = awg.controller.acquire_xy()
            self.positions = (np.asarray(acq[0], dtype=float) + cx + offset[0],
                              np.asarray(acq[1], dtype=float) + cy + offset[1])
        else:
            self.positions = (np.asarray(self.trajectory_x_positions, dtype=float) + offset[0],
                              np.asarray(self.trajectory_y_positions, dtype=float) + offset[1])
        return

    # ------------------------------------------------------------------ #
    #  Trigger -- force the nPoint PIN6 position trigger OFF during an AWG spiral
    # ------------------------------------------------------------------ #
    def setPositionTriggerOn(self, pos, debug=False):
        if self.lineMode == 'arbitrary':
            # AWG spiral: timing comes SOLELY from the AWG start pulse (rear Trig Out ->
            # DAQ), so the nPoint position-compare output must stay OFF.
            #
            # Why actively disarm rather than just skip arming: with the MCL fine motor
            # setPositionTriggerOn is effectively a stub, but on the nPoint it writes real
            # PIN6 hardware registers -- and a *prior* nPoint digital (raster/line) scan
            # may have left PIN6 armed.  During the spiral the AWG dither physically sweeps
            # the stage through the compare position, so a stale armed trigger would emit
            # spurious edges that could race the AWG's start pulse.  Forcing it off here
            # guarantees the AWG is the only trigger source, independent of scan history.
            self._disarm_npoint_trigger()
            return
        return super().setPositionTriggerOn(pos, debug)

    def setPositionTriggerOff(self):
        if self.lineMode == 'arbitrary':
            # Keep PIN6 disarmed in arbitrary mode (idempotent; see setPositionTriggerOn).
            self._disarm_npoint_trigger()
            return
        return super().setPositionTriggerOff()

    def _disarm_npoint_trigger(self):
        """Turn the nPoint PIN6 position-compare trigger OFF (no-op in simulation).

        Delegates to the nPoint fine leaf (axis1), whose setPositionTriggerOff writes the
        device 'off' registers on the shared nptController.  Used only in the arbitrary/AWG
        path -- see setPositionTriggerOn for why the trigger is forced off there.
        """
        self.axes["axis1"].setPositionTriggerOff()

    # ------------------------------------------------------------------ #
    #  DAQ-master streaming is not supported by the AWG (no arm_xy/finish_xy)
    # ------------------------------------------------------------------ #
    def armLine(self, **kwargs):
        raise RuntimeError(
            "[derivedPiezoWithAWG] the daq_master streaming path (armLine) is not "
            "supported for the AWG spiral; set daq_master=False in the scan config. "
            "The AWG is stage-master (it emits its own start pulse).")

    def finishLine(self, **kwargs):
        raise RuntimeError(
            "[derivedPiezoWithAWG] the daq_master streaming path (finishLine) is not "
            "supported for the AWG spiral; set daq_master=False in the scan config.")

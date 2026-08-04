"""Bench test for the MCS2 DAQ-master (externally-clocked) trajectory scheme.

This exercises the full DAQ-master path end to end: the Keysight 53230A is the
pixel-clock MASTER — it self-paces and emits its gate TTL — and the SmarAct MCS2
stream is the SLAVE, advancing exactly one trajectory frame per gate edge and
capturing the measured sensor position for each.  It is the hardware counterpart of
the ``daq_master`` scan path (mcsController.arm_xy/finish_xy + EXTERNAL_SYNC +
keysight53230A GATE_OUT).

    set_stream_clock('external') -> arm_xy()  [open EXTERNAL_SYNC, wait for gate]
    53230A GATE_OUT starts pulsing (initLine)
    finish_xy()  [stream drains one frame per gate edge; read capture buffer]

REQUIRED HARDWARE WIRING:
    53230A gate/output TTL  ->  MCS2 digital input #STREAM_TRIGGER_INPUT
Without that cable the stream never advances: finish_xy() times out and the test
reports it (a useful negative result that isolates the wiring).

What it verifies:
  1. The stream does NOT advance without the DAQ clock (armed-and-waiting), and the
     capture buffer does not fill on its own — i.e. capture is gated to the frames.
  2. Once the 53230A pulses, the stream drains and the stage sweeps the whole
     trajectory (measured positions span the requested range).
  3. Exactly one DAQ count comes back per streamed frame (len(daq_data) == N_POINTS).
  4. The measured (captured) positions differ from the commanded ones (real sensor).

Two modes (choose on the command line; edit the CONFIG block for serials/channels/
VISA address/trigger input):

    python scripts/testMCScapture.py                 # internal: MCS2 clocks itself,
                                                     #   run the stream + read capture
    python scripts/testMCScapture.py --daq-master    # DAQ-master: 53230A gate drives
                                                     #   the stream (requires wiring)
"""
import argparse
import asyncio
import time
import numpy as np
from pystxmcontrol.drivers.mcsController import mcsController, STAGE_PIEZO
import smaract.ctl as ctl

# ---------------------------- CONFIG -------------------------------------
SERIAL   = 12959          # MCS2 controller serial number (the "port" arg)
ADDRESS  = '192.168.168.200'
CH_X     = 0              # MCS2 channel driving the fine X axis
CH_Y     = 1              # MCS2 channel driving the fine Y axis
N_POINTS = 1000           # trajectory length (== stream frames == expected DAQ counts)
RADIUS_UM = 5.0           # spiral radius, microns (keep inside the stage range!)
DWELL_MS = 1.0            # per-point dwell -> nominal gate rate = 1000/DWELL_MS Hz
UM_TO_PM = 1_000_000.0

# --- DAQ-master mode only (used with --daq-master) ---
DAQ_ADDRESS = "USB::0x0957::0x1907::INSTR"   # Keysight 53230A VISA address
DAQ_CHANNEL = 1                              # counter input channel
STREAM_TRIGGER_INPUT = 0                     # MCS2 digital input the 53230A gate is wired to
# -------------------------------------------------------------------------


def make_spiral(n, radius_pm):
    """Archimedean spiral: n points from centre out to radius_pm."""
    t = np.linspace(0.0, 1.0, n)
    theta = 2.0 * np.pi * np.sqrt(t) * 6.0   # ~6 turns
    r = radius_pm * np.sqrt(t)
    return r * np.cos(theta), r * np.sin(theta)


def capture_sizes(c):
    """Current CAPTURE_BUFFER_SIZE (samples captured so far) for both axes."""
    sizes = {}
    for label, idx in (('x', c._capture_buffer_index['x']),
                       ('y', c._capture_buffer_index['y'])):
        try:
            sizes[label] = ctl.GetProperty_i32(c._deviceID, idx,
                                               ctl.Property.CAPTURE_BUFFER_SIZE)
        except Exception as e:
            sizes[label] = f"err({e})"
    return sizes


def report_positions(xm, ym, xcmd, ycmd, c):
    """Common measured-vs-commanded reporting (following error + sensor check)."""
    for label, idx in (('x', c._capture_buffer_index['x']),
                       ('y', c._capture_buffer_index['y'])):
        try:
            size = ctl.GetProperty_i32(c._deviceID, idx, ctl.Property.CAPTURE_BUFFER_SIZE)
            print(f"[test] capture buffer {label} (idx {idx}): size = {size}")
        except Exception as e:
            print(f"[test] could not read capture size for {label}: {e}")

    used_measured = c._meas_x is not None and c._meas_y is not None
    print(f"[test] read_xy returned {'MEASURED (sensor)' if used_measured else 'COMMANDED (fallback!)'} positions")
    if not used_measured:
        print("[test] FALLBACK path taken — capture buffer unavailable/short. Check the "
              "[MCS2] messages above; if size < N the hardware buffer is smaller than the "
              "trajectory (chunk it, as derived_spiral_scan does for MCL).")
        return

    dx, dy = xm - xcmd, ym - ycmd
    print(f"[test] following error X: mean {dx.mean():+.1f} pm, rms {np.sqrt((dx**2).mean()):.1f} pm, "
          f"max |{np.abs(dx).max():.1f}| pm")
    print(f"[test] following error Y: mean {dy.mean():+.1f} pm, rms {np.sqrt((dy**2).mean()):.1f} pm, "
          f"max |{np.abs(dy).max():.1f}| pm")
    span = max(np.ptp(xm), np.ptp(ym))
    print(f"[test] measured position span = {span/UM_TO_PM:.3f} um "
          f"(requested ~{2*RADIUS_UM:.3f} um across the spiral)")
    if np.allclose(xm, xcmd) and np.allclose(ym, ycmd):
        print("[test] WARNING: measured == commanded exactly. Either the stage tracks "
              "perfectly or capture returned commanded data — verify the sensor is on.")
    else:
        print("[test] OK: measured positions differ from commanded (real sensor readback).")


def run_internal(c, xcmd, ycmd):
    """Internal-clock (DIRECT) capture check — the MCS2 clocks itself, no DAQ."""
    print(f"[test] INTERNAL clock: streaming {N_POINTS} points at {int(round(1000.0/DWELL_MS))} Hz")
    c.setup_xy(xcmd, ycmd, dwell=DWELL_MS)
    xm, ym = c.acquire_xy()
    report_positions(np.asarray(xm, float), np.asarray(ym, float), xcmd, ycmd, c)


def run_daq_master(c, xcmd, ycmd):
    """Full DAQ-master test: the 53230A gate clocks the MCS2 stream."""
    from pystxmcontrol.drivers.keysight53230A import keysight53230A

    print(f"[test] DAQ-MASTER: 53230A gate ({int(round(1000.0/DWELL_MS))} Hz) -> MCS2 input "
          f"{STREAM_TRIGGER_INPUT}, {N_POINTS} frames")

    # --- 53230A as the pixel-clock master (self-paced, gate output ON) ---
    daq = keysight53230A(address=DAQ_ADDRESS)
    daq.meta["channel"] = DAQ_CHANNEL
    daq.start()
    # trigger="GATE_OUT" -> self-paced source + OUTP:STAT ON (one gate pulse/frame).
    daq.config(dwell=DWELL_MS, count=N_POINTS, samples=1, trigger="GATE_OUT")

    # --- MCS2 as the slave stream, waiting for the gate edges ---
    c.set_stream_clock("external", input_index=STREAM_TRIGGER_INPUT)
    c.setup_xy(xcmd, ycmd, dwell=DWELL_MS)
    c.arm_xy()                     # open EXTERNAL_SYNC, push frames, wait for gate

    # (1) prove the stream is gated: armed & waiting, not advancing on its own.
    armed_streaming = c.is_streaming(CH_X)
    sizes0 = capture_sizes(c)
    time.sleep(0.5)                # deliberately do NOT start the DAQ yet
    sizesA = capture_sizes(c)
    print(f"[test] after arm, NO clock yet: is_streaming={armed_streaming}, "
          f"capture size {sizes0['x']} -> {sizesA['x']} over 0.5 s")
    grew = isinstance(sizesA['x'], int) and isinstance(sizes0['x'], int) \
        and (sizesA['x'] - sizes0['x'] > 5)
    if grew:
        print("[test] NOTE: capture grew with no gate pulses -> capture is NOT frame-gated "
              "(alignment concern: measured positions may not line up with DAQ samples).")
    else:
        print("[test] OK: no frames advanced without the DAQ clock (stream is externally gated).")

    # (2) start the gate train; the stream should now drain one frame per pulse.
    print("[test] starting 53230A gate clock ...")
    daq.initLine()
    t0 = time.time()
    xm, ym = c.finish_xy()
    elapsed = time.time() - t0
    drained = not c.is_streaming(CH_X)
    expected_s = N_POINTS * DWELL_MS / 1000.0
    print(f"[test] finish_xy in {elapsed:.2f} s (expected ~{expected_s:.2f} s), drained={drained}")
    if not drained:
        print("[test] FAIL: stream did not drain — the DAQ gate is not reaching the MCS2 "
              f"input {STREAM_TRIGGER_INPUT}, or the edge/condition is wrong. Check the cable.")

    # (3) one DAQ count per streamed frame.
    try:
        data = np.asarray(asyncio.run(daq.getLine()), dtype=float)
        print(f"[test] DAQ returned {data.size} counts (expected {N_POINTS}) — "
              f"{'OK' if data.size == N_POINTS else 'MISMATCH: gate pulses != frames'}")
        print(f"[test] DAQ counts: min {data.min():.0f}, mean {data.mean():.1f}, max {data.max():.0f}")
    except Exception as e:
        print(f"[test] could not read DAQ line: {e}")
    finally:
        daq.stop()

    # (4) measured-vs-commanded following error + real-sensor check.
    report_positions(np.asarray(xm, float), np.asarray(ym, float), xcmd, ycmd, c)


def main():
    parser = argparse.ArgumentParser(
        description="MCS2 trajectory bench test: internal-clock capture, or "
                    "DAQ-master (53230A gate drives the stream).")
    parser.add_argument("--daq-master", action="store_true",
                        help="drive the MCS2 stream from the 53230A gate clock "
                             "(requires gate -> MCS2 input wiring); default is the "
                             "internal-clock capture check (no DAQ needed).")
    args = parser.parse_args()

    c = mcsController(address=ADDRESS, port=SERIAL)
    c.initialize()
    c.register_axis('x', CH_X, stage_type=STAGE_PIEZO)
    c.register_axis('y', CH_Y, stage_type=STAGE_PIEZO)
    c.setup_axis(CH_X, stage_type=STAGE_PIEZO)
    c.setup_axis(CH_Y, stage_type=STAGE_PIEZO)

    xcmd, ycmd = make_spiral(N_POINTS, RADIUS_UM * UM_TO_PM)
    try:
        if args.daq_master:
            run_daq_master(c, xcmd, ycmd)
        else:
            run_internal(c, xcmd, ycmd)
    finally:
        c.disconnect()


if __name__ == "__main__":
    main()

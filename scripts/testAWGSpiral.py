"""
Bench test: play a spiral trajectory through the Keysight 33500B AWG and read the
achieved positions back with the USB-1808X, then plot commanded vs acquired.

This exercises exactly the fly-scan seam without the full controller/dataHandler
stack:

  1. build a spiral (spiralcreator) centered at (0, 0) for a requested field size and
     pixel count -- the same generator derived_spiral_image uses;
  2. download it to the AWG as a 2-channel arbitrary waveform (keysightAWGController
     .setup_xy), which also arms the single Trig Out start pulse;
  3. arm the USB-1808X for an EXT-triggered synchronous "adc+counter" scan
     (mccUSB1808X), so the two nPoint position-monitor voltages are latched on the
     same pacer clock the trajectory plays out on;
  4. fire the AWG (trigger_xy) -- the start pulse launches the DAQ; the trajectory
     plays; both block until done;
  5. read the DAQ line: photon counts come back as the primary, the X/Y monitor
     voltages ride on daq.aux_data; convert those volts to microns and plot them over
     the commanded spiral.

Requires the hardware (AWG on VISA, USB-1808X + uldaq).  Run:

    python scripts/testAWGSpiral.py --range 10 --pixels 60 --dwell 0.5

The DAQ scan is count = (number of commanded motor points), one window per point, so
the acquired arrays line up 1:1 with the commanded spiral.
"""

import argparse
import asyncio

import numpy as np
import matplotlib.pyplot as plt

from pystxmcontrol.controller.spiral import spiralcreator
from pystxmcontrol.drivers.keysightAWGController import keysightAWGController
from pystxmcontrol.drivers.mccUSB1808X import mccUSB1808X

# ---- hardware wiring (edit for your bench) -------------------------------- #
AWG_ADDRESS = "USB::0x0957::0x2807::INSTR"   # Keysight 33500B VISA resource
AWG_X_CHANNEL = 1                            # AWG output -> nPoint X
AWG_Y_CHANNEL = 2                            # AWG output -> nPoint Y

DAQ_SERIAL = None                            # None -> first USB-1808X found
XMON_AI_CH = 0                               # AI channel reading the nPoint X monitor
YMON_AI_CH = 1                               # AI channel reading the nPoint Y monitor
CTR_CHANNEL = 0                              # photon-counting counter (unused on bench)
INPUT_MODE = "differential"                  # or "single-ended"
VOLTAGE_RANGE = 10.0                         # +/- V full scale
ADC_MAX_RATE = 200000.0                      # S/s aggregate ceiling of the 1808X

# nPoint analog monitor sensitivity: 10 V full scale == 100 um  ->  10 um/V.
POSITION_CAL_UM_PER_V = 100.0 / 10.0
XMON_OFFSET_V = 0.0                          # monitor volts at X = 0 um
YMON_OFFSET_V = 0.0                          # monitor volts at Y = 0 um

# ---- spiral generation constants (mirror derived_spiral_image) ------------ #
F_MAX_HZ = 100.0                             # max XY scanner frequency
IN_RATIO = 0.05                              # fraction of points in the return spiral
LOOP_OVERSAMPLE = 1.2                        # loops per (pixels/2)
MAX_TRAJ_POINTS = 5000                       # AWG single-trajectory point ceiling
# -------------------------------------------------------------------------- #


def build_spiral(range_um, n_pixels, motor_dwell_ms):
    """Return (x, y) micron arrays for a spiral centered at (0, 0).

    Chooses a loop count and a trajectory duration the same way the real spiral scan
    does, then pads/truncates to an exact point count so the DAQ line lines up 1:1.
    """
    radius = range_um / 2.0
    num_loops = max(1, int(n_pixels * LOOP_OVERSAMPLE / 2.0))

    # Requested time from dwell * area-in-pixels; floored by the scanner frequency
    # limit (a spiral needs at least ~num_loops/fMax*2 seconds to stay feasible).
    num_total_pixels = n_pixels * n_pixels * np.pi / 4.0
    req_scan_time = motor_dwell_ms * num_total_pixels / 1000.0
    min_time = num_loops / F_MAX_HZ * 2.0
    scan_time = max(req_scan_time, min_time)

    sampling_frequency = 1000.0 / motor_dwell_ms                 # Hz
    n_points = int(round(scan_time * sampling_frequency))        # motor points
    if n_points > MAX_TRAJ_POINTS:
        n_points = MAX_TRAJ_POINTS
        scan_time = n_points / sampling_frequency

    # spiralcreator returns (x, y); derived_spiral_image unpacks it (y, x) -- keep its
    # convention so "x"/"y" match the real scan's channel assignment.
    y_spiral, x_spiral = spiralcreator(
        samplingfrequency=sampling_frequency, scantime=scan_time,
        numloops=num_loops, clockwise=True, spiralscantype="InstrumentLimits",
        inratio=IN_RATIO, scanradius=radius, maxFreqXY=F_MAX_HZ)

    # exact length so the DAQ count matches (spiralcreator rounds internally)
    if len(x_spiral) < n_points:
        x_spiral = np.pad(x_spiral, (0, n_points - len(x_spiral)), mode="edge")
        y_spiral = np.pad(y_spiral, (0, n_points - len(y_spiral)), mode="edge")
    else:
        x_spiral = x_spiral[:n_points]
        y_spiral = y_spiral[:n_points]

    print(f"[spiral] range={range_um} um  pixels={n_pixels}  loops={num_loops}")
    print(f"[spiral] {n_points} motor points  dwell={motor_dwell_ms} ms  "
          f"scan_time={n_points * motor_dwell_ms / 1000.0:.3f} s")
    return x_spiral, y_spiral


def make_daq(count, dwell_ms):
    """Configure an EXT-triggered USB-1808X for a synchronous adc+counter line scan."""
    daq = mccUSB1808X(simulation=False)
    daq.simulation = False
    daq.meta = {
        "ndim": 0, "type": "point", "name": "MCC USB-1808X",
        "mode": "adc+counter",
        "channel": XMON_AI_CH,
        "ai_channels": [XMON_AI_CH, YMON_AI_CH],   # aux_data order = [xmon, ymon]
        "ctr_channel": CTR_CHANNEL,
        "primary": "counter",                      # counts -> data, positions -> aux_data
        "input_mode": INPUT_MODE,
        "voltage_range": VOLTAGE_RANGE,
        "adc_max_rate": ADC_MAX_RATE,
        "serial": DAQ_SERIAL,
        "gate": False,
        "position_readback": True,
        "simulation": False,
    }
    daq.start()                                    # connect the device
    daq.config(dwell_ms, count=count, samples=1, trigger="EXT", output="OFF")
    return daq


async def run_scan(controller, daq, x_spiral, y_spiral, dwell_ms):
    """Arm the DAQ, fire the AWG, and return the acquired X/Y monitor volts."""
    # Download the waveform + arm the AWG start trigger (does not fire yet).
    controller.setup_xy(x_spiral, y_spiral, dwell_ms)

    # Arm the EXT-triggered DAQ scan so it is already waiting on the AWG start pulse.
    daq.initLine()

    # Fire the AWG: emits the Trig Out start pulse (launches the DAQ) and plays the
    # trajectory; blocks until it has played out.
    controller.trigger_xy()

    # Reduce the DAQ buffer: counts on .data, [xmon, ymon] volts on .aux_data.
    counts = await daq.getLine()
    xmon_v, ymon_v = daq.aux_data
    print(f"[daq] acquired {len(xmon_v)} position samples, "
          f"{len(np.asarray(counts))} counter windows")
    return np.asarray(xmon_v, dtype=float), np.asarray(ymon_v, dtype=float)


def volts_to_um(v, offset_v):
    return (np.asarray(v, dtype=float) - offset_v) * POSITION_CAL_UM_PER_V


def plot(x_cmd, y_cmd, x_meas, y_meas, out_path):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    ax = axes[0]
    ax.plot(x_cmd, y_cmd, "-", lw=0.8, color="C0", label="commanded")
    ax.plot(x_meas, y_meas, ".", ms=2, color="C3", alpha=0.6, label="acquired")
    ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
    ax.set_aspect("equal", "box")
    ax.set_title("spiral trajectory")
    ax.legend(loc="upper right")

    n = np.arange(len(x_cmd))
    ax = axes[1]
    ax.plot(n, x_cmd, "-", lw=0.8, color="C0", label="X commanded")
    ax.plot(np.arange(len(x_meas)), x_meas, ".", ms=2, color="C3",
            alpha=0.6, label="X acquired")
    ax.set_xlabel("sample index"); ax.set_ylabel("X (um)")
    ax.set_title("X vs sample")
    ax.legend(loc="upper right")

    ax = axes[2]
    ax.plot(n, y_cmd, "-", lw=0.8, color="C0", label="Y commanded")
    ax.plot(np.arange(len(y_meas)), y_meas, ".", ms=2, color="C3",
            alpha=0.6, label="Y acquired")
    ax.set_xlabel("sample index"); ax.set_ylabel("Y (um)")
    ax.set_title("Y vs sample")
    ax.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    print(f"[plot] saved {out_path}")
    plt.show()


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--range", type=float, default=10.0,
                   help="full field size in microns (spiral diameter)")
    p.add_argument("--pixels", type=int, default=60,
                   help="pixels across the field (sets loop count / point count)")
    p.add_argument("--dwell", type=float, default=0.5,
                   help="motor point dwell in ms (AWG sample period)")
    p.add_argument("--out", default="awg_spiral_test.png", help="output plot path")
    args = p.parse_args()

    x_spiral, y_spiral = build_spiral(args.range, args.pixels, args.dwell)

    controller = keysightAWGController(address=AWG_ADDRESS, simulation=False)
    controller.connect()
    controller.setup_axis(AWG_X_CHANNEL)
    controller.setup_axis(AWG_Y_CHANNEL)
    controller.register_axis("x", AWG_X_CHANNEL)
    controller.register_axis("y", AWG_Y_CHANNEL)

    daq = make_daq(count=len(x_spiral), dwell_ms=args.dwell)

    try:
        xmon_v, ymon_v = await run_scan(controller, daq, x_spiral, y_spiral, args.dwell)
    finally:
        daq.stop()
        controller.disconnect()

    x_meas = volts_to_um(xmon_v, XMON_OFFSET_V)
    y_meas = volts_to_um(ymon_v, YMON_OFFSET_V)

    plot(x_spiral, y_spiral, x_meas, y_meas, args.out)


if __name__ == "__main__":
    asyncio.run(main())

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
import time
from contextlib import contextmanager

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


def make_daq(count, dwell_ms, no_trigger=False):
    """Configure a USB-1808X for a synchronous adc+counter line scan.

    Default is EXT triggering: the scan waits on the AWG start pulse wired into
    the 1808X TRIG pin.  With no_trigger=True the DAQ is BUS-triggered and started
    in software (see run_scan) for a USB-only bench smoke test with no cable — the
    DAQ and AWG starts are then not hardware-synced, so samples carry a small,
    variable time offset from the commanded trajectory."""
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
    daq.config(dwell_ms, count=count, samples=1,
               trigger="BUS" if no_trigger else "EXT", output="OFF")
    return daq


@contextmanager
def time_block(store, key):
    """Record the wall time (ms) of the wrapped block into store[key]."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        store[key] = (time.perf_counter() - t0) * 1e3


def _stats_ms(samples):
    a = np.asarray(samples, dtype=float)
    return a.mean(), a.min(), a.max(), (a.std() if a.size > 1 else 0.0)


def characterize_awg(controller, x, y, dwell, iters):
    """Profile the AWG configure/communicate overhead over `iters` repetitions.

    Times the host-side waveform build, each device SCPI phase (with the setWaveform
    sub-blocks the driver records when profiling), and the raw per-command USB
    round-trip latency.  Reports mean/min/max ms so per-line fly-scan dead time is
    quantified.  Leaves the AWG configured + armed on the last iteration.
    """
    dev = controller.device
    dev.profile = True
    srate = 1000.0 / float(dwell)

    tb = {}
    with time_block(tb, "build"):
        maxAmp, offset, waveform = controller._build_waveform(x, y)
    # actual bytes pushed over USB for the arb payload (2*N ASCII DAC codes)
    codes = np.clip(np.round(np.asarray(waveform) * 32767.0), -32767, 32767).astype(np.int32)
    dac_bytes = len("DATA:ARB2:DAC stxm," + ",".join(str(c) for c in codes))

    # bare per-command USB round-trip latency (a query = write + read)
    lat = []
    for _ in range(max(10, iters)):
        t0 = time.perf_counter()
        dev.session.ask("*OPC?")
        lat.append((time.perf_counter() - t0) * 1e3)

    sub_keys = ["setwf_setup_scpi", "setwf_encode", "setwf_dac_write",
                "setwf_select_func", "setwf_amplitude", "setwf_err_query"]
    acc = {k: [] for k in sub_keys}
    setwf, cfg, start = [], [], []
    for _ in range(iters):
        t0 = time.perf_counter()
        dev.setWaveform(waveform, maxAmplitude=maxAmp, offset=offset, srate=srate)
        setwf.append((time.perf_counter() - t0) * 1e3)
        for k in sub_keys:
            acc[k].append(dev.timings.get(k, float("nan")))
        t0 = time.perf_counter()
        dev.configStartTrigger(slope="POS")
        cfg.append((time.perf_counter() - t0) * 1e3)
        t0 = time.perf_counter()
        dev.start()
        start.append((time.perf_counter() - t0) * 1e3)
    dev.profile = False

    lat_mean = float(np.mean(lat))
    print("\n" + "=" * 66)
    print("AWG configure/communicate overhead  (iters=%d, N=%d arb points)"
          % (iters, len(x)))
    print("  per-command USB round-trip (*OPC?): %.2f ms avg" % lat_mean)
    print("  arb DAC payload: %d bytes  ->  %.1f KB/s during dac_write"
          % (dac_bytes, dac_bytes / 1e3 / (np.mean(acc["setwf_dac_write"]) / 1e3)))
    print("  host waveform build: %.2f ms" % tb["build"])
    print("-" * 66)
    print("  %-26s %8s %8s %8s %8s" % ("phase", "mean", "min", "max", "std"))

    def row(label, samples):
        m, lo, hi, sd = _stats_ms(samples)
        print("  %-26s %8.2f %8.2f %8.2f %8.2f" % (label, m, lo, hi, sd))

    row("setWaveform TOTAL", setwf)
    for k in sub_keys:
        row("  " + k.replace("setwf_", ""), acc[k])
    row("configStartTrigger", cfg)
    row("output on (start)", start)
    total = np.mean(setwf) + np.mean(cfg) + np.mean(start)
    print("-" * 66)
    print("  %-26s %8.2f ms  (AWG reconfigure per line, excl. 50 ms settle)"
          % ("SUM", total))
    print("=" * 66)


async def run_scan(controller, daq, x_spiral, y_spiral, dwell_ms, timings=None):
    """Arm the DAQ, fire the AWG, and return the acquired X/Y monitor volts.

    Precondition: controller.setup_xy() has ALREADY been called (once, up front) so
    the arb is downloaded and the outputs are armed.  The arb download + *RST glitch
    the AWG Trig Out line with transient pulses, so it is deliberately done before the
    DAQ exists; by the time the DAQ is armed here the line is quiet and it latches only
    the real *TRG start edge.

    If `timings` (a dict) is passed, per-phase wall times (ms) are recorded into it.
    """
    tmap = timings if timings is not None else {}

    # Arm the DAQ scan so it is already waiting on the AWG start pulse.
    with time_block(tmap, "daq_initLine"):
        daq.initLine()

    # No-cable bench mode: start the internally-paced scan in software right before
    # firing the AWG (loose, non-hardware sync).  For EXT triggering this is a no-op
    # and the AWG start pulse launches the scan instead.
    if daq.trigger == "BUS":
        daq.bus_trigger()

    # Fire the AWG: emits the Trig Out start pulse (launches the DAQ) and plays the
    # trajectory; blocks until it has played out.  (This wall time is dominated by the
    # trajectory playback itself, not overhead.)
    with time_block(tmap, "awg_trigger_xy"):
        controller.trigger_xy()

    # Reduce the DAQ buffer: counts on .data, [xmon, ymon] volts on .aux_data.
    with time_block(tmap, "daq_getLine"):
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
    p.add_argument("--no-trigger", action="store_true",
                   help="USB-only bench smoke test: software-start the DAQ instead of "
                        "waiting on the AWG hardware trigger (loose sync, no cable needed)")
    p.add_argument("--timing", action="store_true",
                   help="characterize AWG/DAQ configure + communicate overhead and "
                        "print a per-phase breakdown (still runs the scan + plot)")
    p.add_argument("--timing-iters", type=int, default=10,
                   help="repetitions for the --timing AWG-config averaging")
    args = p.parse_args()

    T = {}
    x_spiral, y_spiral = build_spiral(args.range, args.pixels, args.dwell)

    controller = keysightAWGController(address=AWG_ADDRESS, simulation=False)
    with time_block(T, "connect"):
        controller.connect()
    controller.setup_axis(AWG_X_CHANNEL)
    controller.setup_axis(AWG_Y_CHANNEL)
    controller.register_axis("x", AWG_X_CHANNEL)
    controller.register_axis("y", AWG_Y_CHANNEL)

    # Repeated AWG-config profiling (leaves the AWG configured + armed).
    if args.timing:
        characterize_awg(controller, x_spiral, y_spiral, args.dwell, args.timing_iters)

    # Download the arb + arm the outputs ONCE, up front -- before the DAQ even exists.
    # This is the *RST/arb-download step that glitches the Trig Out line; doing it here
    # lets those transients settle (during DAQ connect below) so that when the scan
    # arms the DAQ it sees only the real *TRG start edge.
    with time_block(T, "setup_xy"):
        controller.setup_xy(x_spiral, y_spiral, args.dwell)

    # Demonstrate the arb-reuse cache: a second setup_xy with the SAME trajectory must
    # skip the reload (linear fly-scan reuse) -- expect this to be ~instant + silent.
    if args.timing:
        with time_block(T, "setup_xy_cached"):
            controller.setup_xy(x_spiral, y_spiral, args.dwell)

    with time_block(T, "make_daq"):
        daq = make_daq(count=len(x_spiral), dwell_ms=args.dwell, no_trigger=args.no_trigger)

    try:
        xmon_v, ymon_v = await run_scan(controller, daq, x_spiral, y_spiral,
                                        args.dwell, timings=T)
    finally:
        daq.stop()
        controller.disconnect()

    if args.timing:
        traj_ms = len(x_spiral) * args.dwell        # nominal trajectory playback
        print("\nend-to-end phase wall times (single acquisition):")
        for k in ("connect", "setup_xy", "setup_xy_cached", "make_daq",
                  "daq_initLine", "awg_trigger_xy", "daq_getLine"):
            print("  %-16s %9.2f ms" % (k, T.get(k, float("nan"))))
        print("  (of awg_trigger_xy, ~%.1f ms is trajectory playback)" % traj_ms)
        overhead = sum(T.get(k, 0.0) for k in
                       ("setup_xy", "make_daq", "daq_initLine", "daq_getLine")) \
            + (T.get("awg_trigger_xy", 0.0) - traj_ms)
        print("  => non-playback overhead this line: %.1f ms" % overhead)

    x_meas = volts_to_um(xmon_v, XMON_OFFSET_V)
    y_meas = volts_to_um(ymon_v, YMON_OFFSET_V)

    plot(x_spiral, y_spiral, x_meas, y_meas, args.out)


if __name__ == "__main__":
    asyncio.run(main())

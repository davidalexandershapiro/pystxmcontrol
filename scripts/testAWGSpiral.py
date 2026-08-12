"""
Bench test: play a spiral trajectory through the Keysight 33500B AWG and read the
achieved positions back with the USB-1808X, then plot commanded vs acquired.

This exercises exactly the fly-scan seam without the full controller/dataHandler
stack, mirroring the derivedPiezoWithAWG split: the nPoint DIGITAL interface holds the
absolute scan CENTRE while the AWG plays a ZERO-CENTRED dither the nPoint sums onto it.

  0. move the nPoint fine stage (X and Y nptMotor) to the requested centre positions and
     hold them there (closed loop) for the duration of the scan;
  1. build a spiral (spiralcreator) centered at (0, 0) for a requested field size and
     pixel count -- the same generator derived_spiral_image uses.  The spiral centre is
     ALWAYS 0: it is a pure offset the nPoint adds onto its held centre, so the absolute
     commanded position is (nPoint centre + spiral);
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

The DAQ scan is count = (number of commanded motor points) with `--oversample` N
windows per point (default N=1); positions and counts are acquired together at the DAQ
rate, so they line up 1:1 with each other and (for N=1) with the commanded spiral.

Full imaging test (regrid measured positions + counts into an image, mirroring
dataHandler.interpolate_points):

    python scripts/testAWGSpiral.py --range 10 --pixels 60 --dwell 0.5 --oversample 4
    python scripts/testAWGSpiral.py --range 10 --pixels 60 --sim-sample rings  # no beam
"""

import argparse
import asyncio
import time
from contextlib import contextmanager

import numpy as np
import scipy.signal
import matplotlib.pyplot as plt

from pystxmcontrol.controller.spiral import spiralcreator
from pystxmcontrol.drivers.keysightAWGController import keysightAWGController
from pystxmcontrol.drivers.mccUSB1808X import mccUSB1808X
from pystxmcontrol.drivers.nptController import nptController
from pystxmcontrol.drivers.nptMotor import nptMotor

# ---- hardware wiring (edit for your bench) -------------------------------- #
AWG_ADDRESS = "USB::0x0957::0x2807::INSTR"   # Keysight 33500B VISA resource
AWG_X_CHANNEL = 1                            # AWG output -> nPoint X
AWG_Y_CHANNEL = 2                            # AWG output -> nPoint Y

# nPoint digital interface: holds the absolute scan CENTRE while the AWG plays a
# zero-centred dither summed onto it (see derivedPiezoWithAWG).  axis 'x' -> 1, 'y' -> 2.
NPT_ADDRESS = "7340015A"                      # nPoint controller FTDI device ID
NPT_MIN_UM = -50.0                           # fine-stage software travel limits
NPT_MAX_UM = 50.0

DAQ_SERIAL = None                            # None -> first USB-1808X found
XMON_AI_CH = 0                               # AI channel reading the nPoint X monitor
YMON_AI_CH = 1                               # AI channel reading the nPoint Y monitor
CTR_CHANNEL = 0                              # photon-counting counter (unused on bench)
INPUT_MODE = "differential"                  # or "single-ended"
VOLTAGE_RANGE = 10.0                         # +/- V full scale
ADC_MAX_RATE = 200000.0                      # S/s aggregate ceiling of the 1808X

# nPoint analog monitor sensitivity.  Cross-checking the monitor against the (accurate)
# digital encoder showed the monitor reads 2x the true position: the 100 um travel spans
# +/-10 V (20 V total) -> 5 um/V, NOT the 10 um/V (0-10 V == 100 um) originally assumed.
# The digital moveTo/getPos path is correct on this 100 um stage, so ONLY the monitor cal
# used for the DAQ readback needed halving.
POSITION_CAL_UM_PER_V = 100.0 / 20.0
XMON_OFFSET_V = 0.0                          # monitor volts at X = 0 um
YMON_OFFSET_V = 0.0                          # monitor volts at Y = 0 um

# ---- spiral generation constants (mirror derived_spiral_image) ------------ #
F_MAX_HZ = 20.0                             # max XY scanner frequency
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


def make_npt_motors(center_x, center_y, address=NPT_ADDRESS):
    """Connect the nPoint fine stage and move X/Y to their requested centres.

    Returns (controller, xMotor, yMotor).  Both leaves share one nptController and one
    micron frame (units=1, offset=0) so the held centre and the AWG dither add cleanly.
    The stage is left holding the centre (closed loop) -- the AWG then plays a
    zero-centred spiral that the nPoint sums onto this position.
    """
    controller = nptController(address=address, simulation=False)
    controller.initialize(simulation=False)

    motors = {}
    for axis, center in (("x", center_x), ("y", center_y)):
        m = nptMotor(controller=controller)
        m.controller = controller
        m.config = {
            "simulation": False,
            "offset": 0.0,
            "units": 1.0,
            "minValue": NPT_MIN_UM,
            "maxValue": NPT_MAX_UM,
        }
        m.connect(axis=axis)
        m.servoState(True)                 # closed loop so it holds the centre under dither
        m.moveTo(center)
        motors[axis] = m

    time.sleep(0.05)                       # let the fine stage settle at centre
    xpos, ypos = motors["x"].getPos(), motors["y"].getPos()
    print(f"[npt] centre commanded=({center_x:.3f}, {center_y:.3f}) um  "
          f"measured=({xpos:.3f}, {ypos:.3f}) um")
    return controller, motors["x"], motors["y"]


def make_daq(count, dwell_ms, oversample=1, no_trigger=False):
    """Configure a USB-1808X for a synchronous adc+counter line scan.

    Default is EXT triggering: the scan waits on the AWG start pulse wired into
    the 1808X TRIG pin.  With no_trigger=True the DAQ is BUS-triggered and started
    in software (see run_scan) for a USB-only bench smoke test with no cable — the
    DAQ and AWG starts are then not hardware-synced, so samples carry a small,
    variable time offset from the commanded trajectory.

    ``oversample`` (N) requests N counter+position measurements per motor point:
    the DAQ collects ``count * N`` windows at ``dwell/N`` each, so the total scan
    time still equals the trajectory playback (``count * dwell``) and the samples
    stay phase-locked to the AWG.  N>1 densifies the spiral track so fewer image
    pixels are left empty (the AWG plays the SAME arb points; only the DAQ samples
    faster).  This mirrors the DAQsamples/oversampling the real spiral scan applies
    for the MCL + Keysight-counter path."""
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
    daq.config(dwell_ms / oversample, count=count, samples=oversample,
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
    counts = np.asarray(counts, dtype=float)
    xmon_v = np.asarray(daq.aux_data[0], dtype=float)
    ymon_v = np.asarray(daq.aux_data[1], dtype=float)
    print(f"[daq] acquired {len(xmon_v)} position samples, "
          f"{counts.size} counter windows  "
          f"(counts min/max/sum = {counts.min():.3g}/{counts.max():.3g}/{counts.sum():.3g})")
    # Raw monitor volts BEFORE any volts->um scaling: the driver returns raw volts, so
    # this is the ground truth for backing out the true um/V (see main()).  A ~0 span
    # (std~0) here means the ADC isn't reading real position -> dead readback.
    print(f"[daq] raw monitor volts  X span={xmon_v.max()-xmon_v.min():.4f} V "
          f"(min={xmon_v.min():.4f} max={xmon_v.max():.4f} std={xmon_v.std():.4f})  "
          f"Y span={ymon_v.max()-ymon_v.min():.4f} V "
          f"(min={ymon_v.min():.4f} max={ymon_v.max():.4f} std={ymon_v.std():.4f})")
    return (np.asarray(xmon_v, dtype=float),
            np.asarray(ymon_v, dtype=float),
            counts)


def volts_to_um(v, offset_v):
    return (np.asarray(v, dtype=float) - offset_v) * POSITION_CAL_UM_PER_V


# ===========================================================================
#  Regridding (the "interpolation" step) -- imaging test
# ===========================================================================
# The two functions below are a FAITHFUL copy of the spiral regridding the live
# stack runs in dataHandler.interpolate_points (the "continuousSpiral" branch)
# and dataHandler.fill2d.  They are duplicated here -- rather than imported --
# so this script reproduces exactly what turns spiral (position, counts) samples
# into an image, and so we can revise the algorithm here in isolation before
# touching the live dataHandler.  Kept single-segment (trajnum=0,
# position_index=0, no cross-segment accumulation): the bench scan is one
# trajectory, which is the degenerate case of the real accumulating code.

def fill2d(im):
    """Fill single empty (zero) pixels from a 3x3 median -- copy of
    dataHandler.fill2d."""
    newim = np.copy(im)
    fim = scipy.signal.medfilt2d(im)                    # default 3x3 kernel
    peakIndices = np.where(np.logical_and(im == 0, fim != 0))
    newim[peakIndices] = fim[peakIndices]
    return newim


def interpolate_spiral(xReq, yReq, xMeas, yMeas, raw_data,
                       motorDwell, DAQDwell, DAQOversample=2.0,
                       multiTrigger=True):
    """Regrid scattered spiral samples (xMeas, yMeas, raw_data) onto the
    requested image grid (xReq, yReq).  Verbatim single-segment port of
    dataHandler.interpolate_points, continuousSpiral branch.

    Returns (image, xInterp, yInterp, xBins, yBins) so the caller can inspect the
    per-sample interpolated positions and the bin edges alongside the image.
    """
    xReq = np.asarray(xReq, dtype=float)
    yReq = np.asarray(yReq, dtype=float)
    xMeas = np.asarray(xMeas, dtype=float)
    yMeas = np.asarray(yMeas, dtype=float)
    data = np.asarray(raw_data, dtype=float)

    # requested grid bin edges (assumes an evenly spaced grid)
    dx = (xReq[-1] - xReq[0]) / (len(xReq) - 1)
    dy = (yReq[-1] - yReq[0]) / (len(yReq) - 1)
    xBins = np.append(xReq - dx / 2, xReq[-1] + dx / 2)
    yBins = np.append(yReq - dy / 2, yReq[-1] + dy / 2)

    trajnum = 0                                         # single segment

    # motor / DAQ time coordinates (dataHandler uses these offsets, determined by
    # testing; kept identical so timing behaviour matches the live stack)
    motDwellOffset = 0.0
    DAQDwellOffset = 0.0 if multiTrigger else 0.002275
    DAQdelay = 0.0
    Motdelay = 0.0
    actMotDwell = motorDwell + motDwellOffset
    actDAQDwell = DAQDwell + DAQDwellOffset

    if multiTrigger:
        xytraj = np.arange(len(xMeas)) * actMotDwell + Motdelay
        DAQsamples = int(len(data) / len(xMeas))
        DAQtraj = np.array([np.arange(DAQsamples) * actDAQDwell + val + actDAQDwell * 0.5
                            for val in xytraj]).flatten()
    else:
        xytraj = np.arange(len(xMeas)) * actMotDwell + Motdelay
        DAQtraj = np.arange(len(data)) * actDAQDwell + DAQdelay

    endpoint = max(xytraj[-1], DAQtraj[-1])
    xy_tVals = np.array([xytraj + endpoint * i for i in range(trajnum + 1)]).flatten()
    DAQ_tVals = np.array([DAQtraj + endpoint * i for i in range(trajnum + 1)]).flatten()

    xInterp = np.interp(DAQ_tVals, xy_tVals, xMeas)
    yInterp = np.interp(DAQ_tVals, xy_tVals, yMeas)
    nEvents, _, _ = np.histogram2d(yInterp, xInterp, bins=[yBins, xBins])
    binCounts, _, _ = np.histogram2d(yInterp, xInterp, bins=[yBins, xBins], weights=data)

    with np.errstate(divide='ignore', invalid='ignore'):
        avCounts = binCounts / nEvents * DAQOversample
    avCounts[np.isinf(avCounts)] = 0
    avCounts[np.isnan(avCounts)] = 0

    image = fill2d(avCounts)
    return image, xInterp, yInterp, xBins, yBins


def sim_counts(x_um, y_um, kind, center_x, center_y, range_um):
    """Synthesize a per-sample counter signal at the MEASURED positions so the
    regridding geometry can be validated with no beam.  If the reconstructed
    image reproduces this pattern, the position -> image path is correct; if it
    still collapses to one pixel, the fault is in the positions, not the counts.

    Patterns are defined in the frame centred on (center_x, center_y).
    """
    x = np.asarray(x_um, dtype=float) - center_x
    y = np.asarray(y_um, dtype=float) - center_y
    r = np.hypot(x, y)
    theta = np.arctan2(y, x)
    base = 1000.0
    if kind == "rings":
        period = range_um / 6.0
        sig = 0.5 * (1.0 + np.cos(2 * np.pi * r / period))
    elif kind == "star":
        spokes = 12
        sig = 0.5 * (1.0 + np.cos(spokes * theta))
    elif kind == "gauss":
        w = range_um / 5.0
        sig = np.exp(-(r ** 2) / (2 * w ** 2))
    else:
        raise ValueError(f"unknown sim sample '{kind}'")
    # zero outside the field so the spiral's outer excursions don't smear
    sig = np.where(r <= range_um / 2.0, sig, 0.0)
    return base * sig


def plot(x_cmd, y_cmd, x_meas, y_meas, t_cmd, t_meas, out_path):
    """Commanded vs measured, with the two time-series panels on a common TIME
    axis (ms).  Commanded (motor points at motorDwell) and measured (DAQ windows
    at motorDwell/oversample) have different sample counts but span the same
    trajectory duration, so plotting X/Y against time overlays them directly --
    a residual horizontal shift between the curves is the AWG->ADC timing lag."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    ax = axes[0]
    ax.plot(x_cmd, y_cmd, "-", lw=0.8, color="C0", label="commanded")
    ax.plot(x_meas, y_meas, ".", ms=2, color="C3", alpha=0.6, label="acquired")
    ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
    ax.set_aspect("equal", "box")
    ax.set_title("spiral trajectory")
    ax.legend(loc="upper right")

    ax = axes[1]
    ax.plot(t_cmd, x_cmd, "-", lw=0.8, color="C0", label="X commanded")
    ax.plot(t_meas, x_meas, ".", ms=2, color="C3", alpha=0.6, label="X acquired")
    ax.set_xlabel("time (ms)"); ax.set_ylabel("X (um)")
    ax.set_title("X vs time")
    ax.legend(loc="upper right")

    ax = axes[2]
    ax.plot(t_cmd, y_cmd, "-", lw=0.8, color="C0", label="Y commanded")
    ax.plot(t_meas, y_meas, ".", ms=2, color="C3", alpha=0.6, label="Y acquired")
    ax.set_xlabel("time (ms)"); ax.set_ylabel("Y (um)")
    ax.set_title("Y vs time")
    ax.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    print(f"[plot] saved {out_path}")


def plot_image(image, xInterp, yInterp, counts, xBins, yBins, out_path):
    """Show the reconstructed image next to the raw scatter it was built from.

    Left: the regridded image (interpolate_spiral output).  Right: every DAQ
    sample scattered at its interpolated position, coloured by counts -- this is
    the ground truth the histogram bins.  If the scatter shows a real spiral but
    the image is one pixel, the bug is in the regridding; if the scatter itself
    collapses to a point, the bug is in the positions.
    """
    extent = [xBins[0], xBins[-1], yBins[0], yBins[-1]]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))

    ax = axes[0]
    im = ax.imshow(image, origin="lower", extent=extent, aspect="equal",
                   cmap="viridis")
    nz = int(np.count_nonzero(image))
    ax.set_title(f"reconstructed image ({nz}/{image.size} px nonzero)")
    ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    ax = axes[1]
    sc = ax.scatter(xInterp, yInterp, c=counts, s=6, cmap="viridis")
    ax.set_xlim(xBins[0], xBins[-1]); ax.set_ylim(yBins[0], yBins[-1])
    ax.set_aspect("equal", "box")
    ax.set_title("DAQ samples at interpolated positions")
    ax.set_xlabel("X (um)"); ax.set_ylabel("Y (um)")
    fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.04)

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    print(f"[plot] saved {out_path}")


def report_positions(tag, x, y):
    """Print size/min/max/std of a position array -- a constant (std ~ 0) array
    is exactly what collapses the whole image into one pixel."""
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    print(f"[{tag}] X size={x.size} min={x.min():.4f} max={x.max():.4f} "
          f"std={x.std():.4f}   Y min={y.min():.4f} max={y.max():.4f} "
          f"std={y.std():.4f}")


def diagnose_alignment(x_cmd, y_cmd, x_meas, y_meas, cal):
    """Separate a constant DC OFFSET (fixable with monitor_offset) from a TIMING
    LAG (not fixable with any offset) between commanded and measured positions.

    Returns (dcx, dcy) -- the measured-minus-commanded centroid offset in microns
    -- so the caller can optionally subtract it.  Prints:
      * the DC offset in microns AND volts, with the exact config values to null
        it in both the live path (monitor_offset_x/y, um, added AFTER scaling) and
        this script (XMON/YMON_OFFSET_V, volts, subtracted BEFORE scaling);
      * a coarse sample-lag scan: if the shape matches far better at a nonzero lag,
        the residual is a delay between AWG output and ADC sampling, and NO
        constant offset will fix it.
    """
    x_cmd = np.asarray(x_cmd, float); y_cmd = np.asarray(y_cmd, float)
    x_meas = np.asarray(x_meas, float); y_meas = np.asarray(y_meas, float)

    dcx = float(np.mean(x_meas) - np.mean(x_cmd))
    dcy = float(np.mean(y_meas) - np.mean(y_cmd))
    print(f"[align] DC offset (measured-commanded centroid): "
          f"X={dcx:+.4f} um  Y={dcy:+.4f} um")
    print(f"[align]   null it live:   monitor_offset_x={-dcx:+.4f}, "
          f"monitor_offset_y={-dcy:+.4f}  (um, added after scaling)")
    print(f"[align]   null it here:   XMON_OFFSET_V={dcx/cal:+.5f}, "
          f"YMON_OFFSET_V={dcy/cal:+.5f}  (V, subtracted before scaling)")

    # Resample commanded onto the measured sample grid, then scan integer lags.
    n = len(x_meas)
    idx = np.linspace(0, len(x_cmd) - 1, n)
    xc = np.interp(idx, np.arange(len(x_cmd)), x_cmd) - np.mean(x_cmd)
    yc = np.interp(idx, np.arange(len(y_cmd)), y_cmd) - np.mean(y_cmd)
    xm = x_meas - np.mean(x_meas); ym = y_meas - np.mean(y_meas)
    rms0 = float(np.sqrt(np.mean((xm - xc) ** 2 + (ym - yc) ** 2)))
    max_lag = max(1, n // 20)
    best_lag, best_rms = 0, rms0
    for lag in range(-max_lag, max_lag + 1):
        r = float(np.sqrt(np.mean((xm - np.roll(xc, lag)) ** 2
                                  + (ym - np.roll(yc, lag)) ** 2)))
        if r < best_rms:
            best_lag, best_rms = lag, r
    print(f"[align] DC-removed shape RMS vs commanded: {rms0:.4f} um at lag 0; "
          f"best {best_rms:.4f} um at lag {best_lag} samples "
          f"({best_lag / n * 100:+.1f}% of trajectory)")
    if best_lag != 0 and best_rms < 0.9 * rms0:
        print("[align]   -> TIMING LAG dominates (AWG output vs ADC sampling delay); "
              "a constant monitor_offset will NOT fix this.")
    return dcx, dcy


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--range", type=float, default=10.0,
                   help="full field size in microns (spiral diameter)")
    p.add_argument("--pixels", type=int, default=60,
                   help="pixels across the field (sets loop count / point count)")
    p.add_argument("--dwell", type=float, default=0.5,
                   help="motor point dwell in ms (AWG sample period)")
    p.add_argument("--center-x", type=float, default=0.0,
                   help="nPoint X centre in microns (spiral is a zero-centred offset on it)")
    p.add_argument("--center-y", type=float, default=0.0,
                   help="nPoint Y centre in microns (spiral is a zero-centred offset on it)")
    p.add_argument("--out", default="awg_spiral_test.png", help="output trajectory plot path")
    p.add_argument("--image-out", default="awg_spiral_image.png",
                   help="output reconstructed-image plot path")
    p.add_argument("--oversample", type=int, default=1,
                   help="counter+position measurements per motor point (N): the DAQ "
                        "samples N x faster than the AWG plays arb points, densifying "
                        "the spiral track so fewer image pixels are empty")
    p.add_argument("--zero-offset", action="store_true",
                   help="subtract the measured-vs-commanded DC centroid offset from the "
                        "measured positions before imaging (isolates a timing lag from a "
                        "constant offset)")
    p.add_argument("--sim-sample", choices=["none", "rings", "star", "gauss"],
                   default="none",
                   help="synthesize the counter signal from a test pattern at the "
                        "MEASURED positions (validate regridding geometry with no beam) "
                        "instead of using the real DAQ counts")
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

    # Move the nPoint fine stage to the requested centre and hold it there (closed loop).
    # The spiral stays centred at 0; the nPoint sums the AWG dither onto this held centre,
    # so the absolute commanded position is (centre + spiral).
    with time_block(T, "npt_center"):
        npt, npt_x, npt_y = make_npt_motors(args.center_x, args.center_y)

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
        daq = make_daq(count=len(x_spiral), dwell_ms=args.dwell,
                       oversample=args.oversample, no_trigger=args.no_trigger)

    try:
        xmon_v, ymon_v, counts = await run_scan(controller, daq, x_spiral, y_spiral,
                                                args.dwell, timings=T)
    finally:
        daq.stop()
        controller.disconnect()
        # Return the fine stage to 0 so it does not sit parked at the scan centre.
        npt_x.moveTo(0.0)
        npt_y.moveTo(0.0)

    if args.timing:
        traj_ms = len(x_spiral) * args.dwell        # nominal trajectory playback
        print("\nend-to-end phase wall times (single acquisition):")
        for k in ("connect", "npt_center", "setup_xy", "setup_xy_cached", "make_daq",
                  "daq_initLine", "awg_trigger_xy", "daq_getLine"):
            print("  %-16s %9.2f ms" % (k, T.get(k, float("nan"))))
        print("  (of awg_trigger_xy, ~%.1f ms is trajectory playback)" % traj_ms)
        overhead = sum(T.get(k, 0.0) for k in
                       ("setup_xy", "make_daq", "daq_initLine", "daq_getLine")) \
            + (T.get("awg_trigger_xy", 0.0) - traj_ms)
        print("  => non-playback overhead this line: %.1f ms" % overhead)

    x_meas = volts_to_um(xmon_v, XMON_OFFSET_V)
    y_meas = volts_to_um(ymon_v, YMON_OFFSET_V)

    # Absolute commanded position = nPoint held centre + zero-centred spiral dither.
    x_cmd = args.center_x + x_spiral
    y_cmd = args.center_y + y_spiral

    # ---- imaging test: regrid (positions, counts) onto the requested grid ---- #
    report_positions("cmd ", x_cmd, y_cmd)
    report_positions("meas", x_meas, y_meas)

    # Is the commanded-vs-measured offset a constant (fixable) or a timing lag?
    dcx, dcy = diagnose_alignment(x_cmd, y_cmd, x_meas, y_meas, POSITION_CAL_UM_PER_V)
    if args.zero_offset:
        x_meas = x_meas - dcx
        y_meas = y_meas - dcy
        print("[align] subtracted DC offset from measured positions (--zero-offset).")

    # Common time axis (ms): commanded points are spaced args.dwell apart; measured
    # DAQ windows are args.dwell/oversample apart.  Both span the same total time, so
    # the X/Y-vs-time panels overlay (any residual shift is the AWG->ADC lag).
    t_cmd = np.arange(len(x_cmd)) * args.dwell
    t_meas = np.arange(len(x_meas)) * (args.dwell / args.oversample)
    plot(x_cmd, y_cmd, x_meas, y_meas, t_cmd, t_meas, args.out)

    # Back out the TRUE monitor calibration empirically: commanded micron span over the
    # raw-volt span the ADC read.  Compare this to POSITION_CAL_UM_PER_V (this script)
    # and to monitor_um_per_volt in the live daq config -- they must agree.
    vx_span = float(np.ptp(xmon_v)); vy_span = float(np.ptp(ymon_v))
    cx_span = float(np.ptp(x_cmd));  cy_span = float(np.ptp(y_cmd))
    if vx_span > 1e-6 and vy_span > 1e-6:
        print(f"[cal] empirical um/V:  X={cx_span/vx_span:.4f}  Y={cy_span/vy_span:.4f}  "
              f"(script POSITION_CAL_UM_PER_V={POSITION_CAL_UM_PER_V:.4f})")
    else:
        print("[cal] raw monitor volt span ~0 -> ADC not reading position (dead "
              "readback); cannot back out um/V.")

    # The counter signal: real DAQ counts, or a synthetic pattern sampled at the
    # measured positions (lets us validate the regridding with no beam).
    if args.sim_sample != "none":
        signal = sim_counts(x_meas, y_meas, args.sim_sample,
                            args.center_x, args.center_y, args.range)
        print(f"[image] using synthetic '{args.sim_sample}' counts "
              f"(min/max = {signal.min():.3g}/{signal.max():.3g})")
    else:
        signal = counts
        print(f"[image] using real DAQ counts "
              f"(min/max/sum = {signal.min():.3g}/{signal.max():.3g}/{signal.sum():.3g})")

    # Requested image grid: the field the spiral covers, centred on the nPoint centre.
    xReq = np.linspace(args.center_x - args.range / 2,
                       args.center_x + args.range / 2, args.pixels)
    yReq = np.linspace(args.center_y - args.range / 2,
                       args.center_y + args.range / 2, args.pixels)

    # motor dwell == AWG sample period; DAQ dwell = motor dwell / oversample
    # (N DAQ windows per motor point).  Positions and counts are measured together
    # at the DAQ rate, so the regridder sees them 1:1 regardless of N.
    image, xInterp, yInterp, xBins, yBins = interpolate_spiral(
        xReq, yReq, x_meas, y_meas, signal,
        motorDwell=args.dwell, DAQDwell=args.dwell / args.oversample,
        DAQOversample=2.0, multiTrigger=True)

    report_positions("interp", xInterp, yInterp)
    inx = int(np.count_nonzero((xInterp >= xBins[0]) & (xInterp <= xBins[-1])))
    iny = int(np.count_nonzero((yInterp >= yBins[0]) & (yInterp <= yBins[-1])))
    print(f"[image] samples in-grid: X {inx}/{xInterp.size}  Y {iny}/{yInterp.size}")
    print(f"[image] reconstructed {image.shape} image, "
          f"{int(np.count_nonzero(image))}/{image.size} pixels nonzero")

    plot_image(image, xInterp, yInterp, signal, xBins, yBins, args.image_out)

    plt.show()


if __name__ == "__main__":
    asyncio.run(main())

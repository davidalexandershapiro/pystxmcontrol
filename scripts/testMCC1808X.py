"""
Bench overhead test for the MCC USB-1808X DAQ driver.

Measures the fixed timing overhead of point and line acquisitions in both counter
and ADC modes, then prints suggested daq.json timing keys derived from the numbers:

    minimum_dwell   -- floor the requested per-pixel dwell is clamped up to (ms)
    dwell_pad       -- fixed per-pixel overhead budget, subtracted from the max
                       motor dwell (ms)
    time_resolution -- dwell is quantized to a whole multiple of this (ms); for the
                       ADC it is the sample period (1 / adc_max_rate)

See base_scan.calculate_actual_dwell for exactly how those three feed the scan.

The test drives the low-level ``usb1808x`` wrapper directly with BUS (software)
triggering, so scans self-complete without the motion controller emitting hardware
pulses -- it isolates driver/USB overhead, not motion.  EXT-triggered timing is
best characterised from a real fly scan.

Requires the hardware + uldaq.  Run:  python scripts/testMCC1808X.py
"""
import asyncio
import time
import numpy as np
from pystxmcontrol.drivers.usb1808x import usb1808x

# ---- edit for your setup -------------------------------------------------- #
# (mode, channel) pairs to characterise.  Counter numbers and AI channels are
# separate numbering spaces, so give each mode its own channel.
TARGETS = [
    ("counter", 0),
    ("adc", 0),
]
SERIAL = None                 # None -> first USB-1808X found
INPUT_MODE = "differential"   # adc only
VOLTAGE_RANGE = 10.0          # adc only, +/- V
ADC_MAX_RATE = 200000.0       # adc only, S/s
DWELLS_MS = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0]
POINT_REPEATS = 50            # getPoint() calls averaged per dwell
LINE_PIXELS = 100             # windows per getLine() line
# -------------------------------------------------------------------------- #


def _stats(times_ms):
    a = np.asarray(times_ms, dtype="float")
    return a.mean(), np.median(a), a.std()


def _new_device(mode, channel):
    dev = usb1808x()
    dev.mode = mode
    dev.channel = channel
    dev.serial = SERIAL
    dev.input_mode = INPUT_MODE
    dev.voltage_range_volts = VOLTAGE_RANGE
    dev.adc_max_rate = ADC_MAX_RATE
    return dev


async def _measure_point(dev, mode, channel, dwell):
    dev.config(dwell, count=1, samples=1, trigger="BUS", channel=channel, mode=mode)
    await dev.getPoint()                       # warm-up, discarded
    ts = []
    for _ in range(POINT_REPEATS):
        t0 = time.perf_counter()
        await dev.getPoint()
        ts.append((time.perf_counter() - t0) * 1e3)
    return ts


async def _measure_line(dev, mode, channel, dwell, pixels):
    dev.config(dwell, count=pixels, samples=1, trigger="BUS",
               channel=channel, mode=mode)
    dev.initLine()
    t0 = time.perf_counter()
    dev.bus_trigger()
    data = await dev.getLine()
    elapsed = (time.perf_counter() - t0) * 1e3
    return elapsed, len(np.asarray(data))


async def _characterise(mode, channel):
    print("\n" + "=" * 68)
    print(f" mode = {mode!r}   channel = {channel}")
    print("=" * 68)

    dev = _new_device(mode, channel)
    dev.connect(serial=SERIAL)

    # -- point overhead ---------------------------------------------------- #
    print("\n POINT overhead (BUS, {} reps/dwell)".format(POINT_REPEATS))
    print(f" {'dwell':>7} {'meas':>8} {'overhead':>9} {'median':>8} {'std':>7}  (ms)")
    point_oh = []
    for d in DWELLS_MS:
        mean, med, sd = _stats(await _measure_point(dev, mode, channel, d))
        point_oh.append(mean - d)
        print(f" {d:7.3f} {mean:8.3f} {mean - d:9.3f} {med:8.3f} {sd:7.3f}")

    # -- line overhead ----------------------------------------------------- #
    print("\n LINE overhead (BUS, {} px)".format(LINE_PIXELS))
    print(f" {'dwell':>7} {'meas':>9} {'ideal':>9} {'overhead':>9} {'per-px(us)':>11}  (ms)")
    line_oh = []
    perpx_us = []
    for d in DWELLS_MS:
        elapsed, n = await _measure_line(dev, mode, channel, d, LINE_PIXELS)
        ideal = d * LINE_PIXELS
        line_oh.append(elapsed - ideal)
        perpx_us.append((elapsed - ideal) / LINE_PIXELS * 1e3)
        print(f" {d:7.3f} {elapsed:9.3f} {ideal:9.3f} {elapsed - ideal:9.3f} {perpx_us[-1]:11.1f}")

    dev.disconnect()

    # -- suggested config keys --------------------------------------------- #
    med_point_oh = float(np.median(point_oh))
    med_perpx_us = float(np.median(perpx_us))
    if mode == "adc":
        time_res = round(1.0 / ADC_MAX_RATE * 1e3, 4)          # sample period, ms
    else:
        # counter has no averaging clock; quantize finely and let dwell dominate
        time_res = 0.001
    # per-pixel fixed overhead, in ms, floored at 0
    dwell_pad = round(max(0.0, med_perpx_us / 1e3), 3)
    # smallest dwell where overhead stays a modest fraction of the dwell itself
    minimum_dwell = round(max(0.1, med_point_oh), 3)

    print("\n suggested daq.json keys for this mode:")
    print(f'   "minimum_dwell": {minimum_dwell},      # ms; ~point overhead / 100us floor')
    print(f'   "dwell_pad": {dwell_pad},           # ms; median per-pixel line overhead')
    print(f'   "time_resolution": {time_res}     # ms; {"ADC sample period" if mode == "adc" else "quantization step"}')
    return {"mode": mode, "minimum_dwell": minimum_dwell,
            "dwell_pad": dwell_pad, "time_resolution": time_res}


async def main():
    results = []
    for mode, channel in TARGETS:
        try:
            results.append(await _characterise(mode, channel))
        except Exception as e:
            print(f"\n [{mode}] FAILED: {type(e).__name__}: {e}")

    if results:
        print("\n" + "=" * 68)
        print(" summary (copy the block matching the mode you will run)")
        print("=" * 68)
        for r in results:
            print(f"  {r['mode']:>8}: minimum_dwell={r['minimum_dwell']}  "
                  f"dwell_pad={r['dwell_pad']}  time_resolution={r['time_resolution']}")


if __name__ == "__main__":
    asyncio.run(main())

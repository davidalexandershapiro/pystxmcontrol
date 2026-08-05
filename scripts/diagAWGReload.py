"""Test click-free per-chunk arb reload for chunked-spiral mode.

Result of the first attempt: DATA:ARB2:DAC to an EXISTING name is rejected (no
in-place overwrite -> old data kept playing + a beep per try).  So new data requires
clear + reload + re-select, which normally re-runs the amplitude reset that switches
the output attenuator relay (the CLICK).

This version locks the output range first (`VOLTage:RANGe:AUTO OFF`), so amplitude
changes no longer switch the relay, THEN reloads each chunk with a real
clear+DAC+select (the driver's setWaveform).  Hypothesis: reloads are now click-free
AND beep-free, amplitude/points stay put, and each new segment actually plays.

All chunks are the SAME length and normalized to the SAME scan-global amplitude, so
per step only the raw data changes -- isolating click/amplitude from burst-period.

Run directly in your terminal (it pauses for you to listen + watch the scope):
    python diagAWGReload.py
"""
import numpy as np

from testAWGSpiral import build_spiral, AWG_ADDRESS, AWG_X_CHANNEL, AWG_Y_CHANNEL
from pystxmcontrol.drivers.keysightAWGController import keysightAWGController

K_CHUNKS = 4
DWELL_MS = 0.5


def equal_chunks(x, y, k):
    """Split the spiral into k EQUAL-length chunks, each normalized to the SAME
    scan-global amplitude/centre (so the AWG amplitude never needs to change)."""
    xc, yc = float(np.mean(x)), float(np.mean(y))
    xa = max(float(np.max(np.abs(x - xc))), 1e-6)
    ya = max(float(np.max(np.abs(y - yc))), 1e-6)
    L = len(x) // k
    wfs = []
    for i in range(k):
        sl = slice(i * L, (i + 1) * L)
        wfs.append(np.concatenate([(x[sl] - xc) / xa, (y[sl] - yc) / ya]))
    return wfs, (xa, ya), (xc, yc), L


def report(dev):
    for label, scpi in (("arb name", "SOURce1:FUNCtion:ARBitrary?"),
                        ("arb points", "SOURce1:FUNCtion:ARBitrary:POINts?"),
                        ("volt (Vpp)", "SOURce1:VOLTage?"),
                        ("volt offset", "SOURce1:VOLTage:OFFSet?")):
        print("    %-12s %-40s -> %s" % (label, scpi, dev.session.ask(scpi).strip()))
    for _ in range(4):
        e = dev.session.ask("SYST:ERR?").strip()
        print("    %-12s %-40s -> %s" % ("syst err", "SYST:ERR?", e))
        if e.startswith(("+0", "0")):
            break


def pause(msg):
    input("\n>>> %s\n    (listen for CLICK/BEEP, watch scope, then press Enter) " % msg)


def main():
    x, y = build_spiral(10.0, 60, DWELL_MS)
    wfs, maxAmp, offset, L = equal_chunks(x, y, K_CHUNKS)
    srate = 1000.0 / DWELL_MS
    vpp = 2.0 * maxAmp[0]

    c = keysightAWGController(address=AWG_ADDRESS, simulation=False)
    c.connect()
    c.setup_axis(AWG_X_CHANNEL)
    c.setup_axis(AWG_Y_CHANNEL)
    c.register_axis("x", AWG_X_CHANNEL)
    c.register_axis("y", AWG_Y_CHANNEL)
    dev = c.device
    exp_vpp = vpp * dev._voltage_calibration
    print("[diag] %d chunks x %d pts, global amplitude -> expect Vpp ~= %.4f V on every step"
          % (K_CHUNKS, L, exp_vpp))

    # --- one-time full prepare with chunk 0: arb select + amplitude + burst. ---
    dev.setWaveform(wfs[0], maxAmplitude=maxAmp, offset=offset, srate=srate)
    dev.configStartTrigger(slope="POS")
    dev.start()
    print("\n[prepare] chunk 0 full setup (auto-range):")
    report(dev)
    pause("prepared -- baseline. Vpp should read ~%.4f V." % exp_vpp)

    # --- per-chunk real reload (clear+DAC+select via setWaveform), NORMAL auto-range.
    #     Expectation: amplitude back to correct, NO -222/-221-offset beeps, data
    #     actually changes.  A relay click per chunk is expected + acceptable (only a
    #     few reloads per scan; linear mode never reloads at all). ---
    for i in range(1, K_CHUNKS):
        dev.setWaveform(wfs[i], maxAmplitude=maxAmp, offset=offset, srate=srate)
        print("\n[chunk %d] full reload, auto-range (one click expected, amplitude OK):" % i)
        report(dev)
        dev.fire()                            # play it so you can confirm new data on scope
        pause("chunk %d loaded + fired. Vpp back to ~%.4f V? errors clean? scope = new segment?"
              % (i, exp_vpp))

    dev.stop()
    c.disconnect()
    print("\ndone.")


if __name__ == "__main__":
    main()

"""Diagnostic: download the spiral arb, then ask the AWG what it actually loaded.

Read-only after the normal setup_xy download -- it only *queries* the instrument's
own view of the arb (point count, sample rate, function, burst config, output
levels, ARB2 format) so we can tell whether the DATA:ARB2:DAC / AABB download
parsed as a 2827-point-per-channel 1.41 s chirp on each channel, or got truncated
/ mis-split / replayed.
"""
from testAWGSpiral import build_spiral, AWG_ADDRESS, AWG_X_CHANNEL, AWG_Y_CHANNEL
from pystxmcontrol.drivers.keysightAWGController import keysightAWGController


def main():
    x, y = build_spiral(10.0, 60, 0.5)
    print(f"[diag] commanded points: {len(x)}   expected srate: {1000.0/0.5:.0f} Sa/s"
          f"   expected duration: {len(x) * 0.5 / 1000.0:.3f} s")

    c = keysightAWGController(address=AWG_ADDRESS, simulation=False)
    c.connect()
    c.setup_axis(AWG_X_CHANNEL)
    c.setup_axis(AWG_Y_CHANNEL)
    c.register_axis("x", AWG_X_CHANNEL)
    c.register_axis("y", AWG_Y_CHANNEL)

    c.setup_xy(x, y, 0.5)          # downloads the arb + arms the burst (no motion)

    s = c.device.session
    queries = [
        ("volatile catalog",   "DATA:VOLatile:CATalog?"),
        ("arb2 format",        "DATA:ARBitrary2:FORMat?"),
        ("--- ch1 (X) ---",    None),
        ("arb name",           "SOURce1:FUNCtion:ARBitrary?"),
        ("arb points",         "SOURce1:FUNCtion:ARBitrary:POINts?"),
        ("arb srate",          "SOURce1:FUNCtion:ARBitrary:SRATe?"),
        ("function",           "SOURce1:FUNCtion?"),
        ("burst state",        "SOURce1:BURSt:STATe?"),
        ("burst mode",         "SOURce1:BURSt:MODE?"),
        ("burst ncycles",      "SOURce1:BURSt:NCYCles?"),
        ("volt (Vpp)",         "SOURce1:VOLTage?"),
        ("volt offset",        "SOURce1:VOLTage:OFFSet?"),
        ("volt high",          "SOURce1:VOLTage:HIGH?"),
        ("volt low",           "SOURce1:VOLTage:LOW?"),
        ("--- ch2 (Y) ---",    None),
        ("arb name",           "SOURce2:FUNCtion:ARBitrary?"),
        ("arb points",         "SOURce2:FUNCtion:ARBitrary:POINts?"),
        ("arb srate",          "SOURce2:FUNCtion:ARBitrary:SRATe?"),
        ("function",           "SOURce2:FUNCtion?"),
        ("burst ncycles",      "SOURce2:BURSt:NCYCles?"),
        ("volt (Vpp)",         "SOURce2:VOLTage?"),
        ("volt offset",        "SOURce2:VOLTage:OFFSet?"),
    ]
    for label, q in queries:
        if q is None:
            print(f"  {label}")
            continue
        try:
            print(f"    {label:<16s} {q:<42s} -> {s.ask(q).strip()}")
        except Exception as e:
            print(f"    {label:<16s} {q:<42s} -> ERROR {e}")

    print("  --- error queue ---")
    for _ in range(6):
        err = s.ask("SYST:ERR?").strip()
        print(f"    SYST:ERR? -> {err}")
        if err.startswith(("+0", "0")):
            break

    c.disconnect()


if __name__ == "__main__":
    main()

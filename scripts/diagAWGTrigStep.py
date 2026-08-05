"""Interactive trigger isolator: step through the AWG arm/fire sequence one SCPI
operation at a time, pausing so you can watch the Trig Out line on the scope and
report exactly which step emits the extraneous trigger pulses.

Set the scope to trigger normally (or infinite persistence) on the Trig Out line,
run this, and after each prompt note whether NEW pulse(s) appeared, then press Enter.
"""
from testAWGSpiral import build_spiral, AWG_ADDRESS, AWG_X_CHANNEL, AWG_Y_CHANNEL
from pystxmcontrol.drivers.keysightAWGController import keysightAWGController


def pause(step, msg):
    input("\n[%s] %s\n     -> watch Trig Out, then press Enter to continue... " % (step, msg))


def main():
    x, y = build_spiral(10.0, 60, 0.5)
    dwell = 0.5
    srate = 1000.0 / dwell

    c = keysightAWGController(address=AWG_ADDRESS, simulation=False)
    c.connect()
    c.setup_axis(AWG_X_CHANNEL)
    c.setup_axis(AWG_Y_CHANNEL)
    c.register_axis("x", AWG_X_CHANNEL)
    c.register_axis("y", AWG_Y_CHANNEL)
    dev = c.device
    maxAmp, offset, waveform = c._build_waveform(x, y)

    pause("0 baseline", "connected + *RST done; nothing armed. Expect NO pulses at all.")

    dev.setWaveform(waveform, maxAmplitude=maxAmp, offset=offset, srate=srate)
    pause("1 setWaveform", "arb loaded + amplitude set; burst/TrigOut NOT yet configured.")

    dev.configStartTrigger(slope="POS")
    pause("2 configStartTrigger", "burst armed on BOTH ch, Trig Out enabled. Pulses here?")

    dev.session.write('OUTPut1 ON')
    pause("3 OUTPut1 ON", "channel 1 output enabled. Pulses here?")

    dev.session.write('OUTPut2 ON')
    pause("4 OUTPut2 ON", "channel 2 output enabled. Pulses here?")

    dev.session.write('*TRG')
    pause("5 *TRG", "software trigger sent. Expect exactly ONE pulse WITH the waveform.")

    dev.stop()
    c.disconnect()
    print("\ndone.")


if __name__ == "__main__":
    main()

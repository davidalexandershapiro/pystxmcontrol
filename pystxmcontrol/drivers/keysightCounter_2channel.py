"""
Low-level SCPI driver for the Keysight 53230A in dual-channel timed-totalize mode.

Key differences from keysightCounter.py
----------------------------------------
* Uses the ``SENS`` command layer instead of ``CONF:TOT:TIM`` so multiple
  channels can be set up in a single config pass without resetting each other.
* ``config()`` accepts a *channels* tuple and configures every listed channel
  in one go.
* ``getLine()`` / ``getPoint()`` accept a *channels* tuple and issue a single
  ``FETC? (@1,2)`` (or whichever channels are requested), returning a dict
  keyed by channel number.

Interleaving note
-----------------
When the 53230A collects N samples across K channels it returns K*N readings
in this order::

    sample_0_ch1,  sample_0_ch2,  sample_1_ch1,  sample_1_ch2, …

i.e. results are interleaved per *sample*, not per *channel*.
Use ``values[i::K]`` to extract channel ``i`` (0-based index into *channels*).

This ordering has been confirmed in the 53230A User's Guide (Keysight
document U1050-90006, chapter "FETCH?" command notes).  If your firmware
behaves differently (channel-sequential instead of sample-interleaved) swap
to ``values[i*N:(i+1)*N]``; that alternative is shown in comments below.
"""

import usbtmc
import asyncio
from numpy import array


class counter_2channel:
    """
    Thin SCPI wrapper around a single Keysight 53230A instrument connection.

    Intended to be used as a *shared* backend by one or more
    ``keysight53230A_2channel`` DAQ instances (see keysight53230A_2channel.py).
    Callers are responsible for serialising access; no internal locking is
    provided.
    """

    def __init__(self):
        self.visa_address = "USB::0x0957::0x1907::INSTR"
        self.session = None
        self.channels = (1,)    # channels configured in last config() call
        self.dwell = 1.0        # ms

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, visa_address: str = None):
        if visa_address is not None:
            self.visa_address = visa_address
        self.session = usbtmc.Instrument(self.visa_address)
        self.session.write("*RST")
        idn = self.session.ask("*IDN?")
        print(f"[counter_2channel] Connected: {idn}")

    def disconnect(self):
        if self.session is not None:
            self.session.close()
            self.session = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def config(self, dwell: float, channels=(1, 2),
               count: int = 1, samples: int = 1,
               trigger: str = "BUS", output: str = "OFF"):
        """
        Configure one or more channels for timed-totalize using the SENS layer.

        Unlike ``CONF:TOT:TIM`` (which resets the instrument and configures a
        single channel, destroying any other channel settings), ``SENS:FUNC``
        preserves the settings for channels not explicitly mentioned.

        :param dwell:    Gate time in **milliseconds**.
        :param channels: Tuple of channel numbers to configure, e.g. ``(1,)``,
                         ``(2,)`` or ``(1, 2)``.
        :param count:    TRIG:COUN — how many trigger events per INIT:IMM.
        :param samples:  SAMP:COUN — samples collected per trigger event.
        :param trigger:  Trigger source (``"BUS"`` or ``"EXT"``).
        :param output:   Gate-output state (``"ON"`` or ``"OFF"``).
        """
        self.dwell = dwell
        self.count = count
        self.trigger = trigger
        self.channels = tuple(channels)

        self.session.write("*RST")
        self.session.write("DISP ON")

        for ch in channels:
            self.session.write(f"SENS:FUNC 'TOT:TIM',(@{ch})")
            self.session.write(f"SENS:TOT:TIM:GATE:TIME {dwell / 1000.0},(@{ch})")

        self.session.write(f"TRIG:COUN {count}")
        self.session.write(f"SAMP:COUN {samples}")
        self.session.write("TRIG:DEL 0")
        self.session.write("TRIG:SLOP POS")
        self.session.write(f"OUTP:STAT {output}")
        self.session.write(f"TRIG:SOUR {trigger}")

        # Block until the instrument has finished processing the config.
        # CONF? does not write anything but causes the instrument to return
        # its current configuration string — useful as a synchronisation point.
        self.session.ask("CONF?")

    # ------------------------------------------------------------------
    # Trigger control (used by line scans)
    # ------------------------------------------------------------------

    def initLine(self):
        """Arm the instrument (INIT:IMM) ready for the next trigger."""
        self.session.write("INIT:IMM")

    def busTrigger(self):
        """Issue a software trigger (*TRG)."""
        self.session.write("*TRG")

    # ------------------------------------------------------------------
    # Data acquisition helpers
    # ------------------------------------------------------------------

    def _fetch(self, channels: tuple) -> dict:
        """
        Issue ``FETC? (@ch…)`` and return a dict mapping channel → np.array.

        The 53230A returns readings interleaved across channels::

            s0_ch1, s0_ch2, s1_ch1, s1_ch2, …

        so channel ``i`` (0-based) is extracted as ``values[i::n_channels]``.

        If you ever see *channel-sequential* ordering (all ch1 samples followed
        by all ch2 samples) use ``values[i*N:(i+1)*N]`` instead.
        """
        ch_str = "(" + ",".join(f"@{c}" for c in channels) + ")"
        raw = self.session.ask(f"FETC? {ch_str}")
        values = array(raw.split(","), dtype="float")
        n = len(channels)
        return {ch: values[i::n] for i, ch in enumerate(channels)}
        # Alternative (channel-sequential):
        # N = len(values) // n
        # return {ch: values[i * N:(i + 1) * N] for i, ch in enumerate(channels)}

    async def getPoint(self, channels: tuple = (1,)) -> dict:
        """
        Arm, trigger, and fetch a single point from *channels*.

        Used for point-mode scans.  Returns ``{ch: array([value])}`` per channel.
        """
        self.session.write("INIT:IMM")
        self.session.write("*TRG")
        return self._fetch(channels)

    async def getLine(self, channels: tuple = (1,)) -> dict:
        """
        Fetch a full line's worth of samples from *channels*.

        The instrument must have been armed via ``initLine()`` and triggered via
        ``busTrigger()`` before this is called.  Returns
        ``{ch: array([s0, s1, …])}`` per channel.
        """
        return self._fetch(channels)

"""
Low-level SCPI driver for the Keysight 53230A in dual-channel timed-totalize mode.

Key differences from keysightCounter.py
----------------------------------------
* ``config()`` accepts a *channels* tuple and uses the ``SENS`` command layer
  to configure every listed channel in a single pass, without the implicit
  instrument reset that ``CONF:TOT:TIM`` performs on every call.

  With one channel:   equivalent to the original ``CONF:TOT:TIM`` path.
  With two channels:  both counters are armed simultaneously.

* ``_fetch()`` always issues plain ``FETC?`` (no channel specifier).
  Using ``FETC? (@N)`` is measurably slower and can produce USB timeouts —
  the instrument expects the unqualified form and returns readings for every
  channel that was configured, in channel order.

* ``getLine()`` / ``getPoint()`` return a ``{channel: np.array}`` dict so the
  calling DAQ layer can slice out the correct channel without an extra round-trip.

Data ordering
-------------
When the instrument is configured for K channels and SAMP:COUN = S, ``FETC?``
returns K*S values **interleaved per sample**::

    s0_ch1, s0_ch2, s1_ch1, s1_ch2, …

so channel index ``i`` (0-based within the sorted channel list) is extracted
with ``values[i::K]``.

For a single channel ``FETC?`` returns S plain values with no interleaving.
"""

import usbtmc
import asyncio
from numpy import array


class counter_2channel:
    """
    Thin SCPI wrapper around a single Keysight 53230A connection.

    Intended to be used as a *shared* backend by one or more
    ``keysight53230A_2channel`` DAQ instances (see keysight53230A_2channel.py).
    Callers are responsible for serialising access; no internal locking is
    provided because the asyncio event loop already guarantees sequential
    execution between tasks that have no real suspension points.
    """

    def __init__(self):
        self.visa_address = "USB::0x0957::0x1907::INSTR"
        self.session = None
        self.configured_channels = ()   # set in config()

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

    def config(self, dwell: float, channels: tuple = (1,),
               count: int = 1, samples: int = 1,
               trigger: str = "BUS", output: str = "OFF"):
        """
        Configure one or more channels for timed-totalize.

        Uses ``*RST`` followed by ``SENS:FUNC`` / ``SENS:TOT:TIM:GATE:TIME``
        for each channel.  This is equivalent to ``CONF:TOT:TIM`` for a single
        channel, and extends naturally to two simultaneous channels.

        :param dwell:    Gate time in **milliseconds**.
        :param channels: Sorted tuple of channel numbers, e.g. ``(1,)``,
                         ``(2,)`` or ``(1, 2)``.
        :param count:    ``TRIG:COUN`` — trigger events per ``INIT:IMM``.
        :param samples:  ``SAMP:COUN`` — samples per trigger event.
        :param trigger:  ``"BUS"`` or ``"EXT"``.
        :param output:   Gate-output state ``"ON"`` / ``"OFF"``.
        """
        self.configured_channels = tuple(channels)

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

        # CONF? blocks until the instrument has finished processing the
        # configuration — used here purely as a synchronisation barrier.
        self.session.ask("CONF?")

    # ------------------------------------------------------------------
    # Trigger control (line-scan path)
    # ------------------------------------------------------------------

    def initLine(self):
        """Arm the instrument (``INIT:IMM``) ready for the next trigger."""
        self.session.write("INIT:IMM")

    def busTrigger(self):
        """Issue a software trigger (``*TRG``)."""
        self.session.write("*TRG")

    # ------------------------------------------------------------------
    # Data acquisition
    # ------------------------------------------------------------------

    def _fetch(self, channels: tuple) -> dict:
        """
        Issue plain ``FETC?`` and parse the response into a
        ``{channel: np.array}`` dict.

        The unqualified ``FETC?`` command is used deliberately — the
        ``FETC? (@N)`` form is significantly slower and can cause USB
        timeouts on this instrument.

        ``FETC?`` returns readings for every *configured* channel in channel
        order, interleaved per sample::

            s0_ch1, s0_ch2, s1_ch1, s1_ch2, …

        For a single channel the response is a plain comma-separated list
        with no interleaving.
        """
        raw = self.session.ask("FETC?")
        values = array(raw.split(","), dtype="float")
        n = len(channels)
        if n == 1:
            # Single channel: the whole response belongs to channels[0]
            return {channels[0]: values}
        # Multi-channel: interleaved — channel i is at positions i, i+n, i+2n, …
        return {ch: values[i::n] for i, ch in enumerate(channels)}

    async def getPoint(self, channels: tuple = (1,)) -> dict:
        """
        Arm, trigger, and fetch a single point.

        Returns ``{ch: array([value])}`` for each channel in *channels*.
        """
        self.session.write("INIT:IMM")
        self.session.write("*TRG")
        return self._fetch(channels)

    async def getLine(self, channels: tuple = (1,)) -> dict:
        """
        Fetch a complete line of samples.

        The instrument must have been armed via ``initLine()`` and triggered
        via ``busTrigger()`` before this is called.

        Returns ``{ch: array([s0, s1, …])}`` for each channel in *channels*.
        """
        return self._fetch(channels)

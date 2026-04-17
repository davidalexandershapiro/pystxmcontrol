"""
Low-level SCPI driver for the Keysight 53230A, supporting single-channel
totalize or single/dual-channel frequency measurements.

Why two measurement modes?
--------------------------
Per the Keysight 53230A programmer's guide:

* **Totalize** (``TOT:TIM``) is a *single-channel* function.  Attempting
  ``SENS:FUNC 'TOT:TIM'`` on a second channel while the first is configured
  produces a SCPI command / settings-conflict error.

* **Frequency** (``FREQ``) is the only function that can be configured on
  both channels at the same time.  Both front-end counters run in parallel
  during each gate; ``FETC?`` returns readings interleaved per sample.

To preserve the behaviour of the original single-channel driver while adding
dual-channel support, this module exposes a ``measurement_mode`` switch:

* ``"TOT"`` (default for single channel): same SCPI sequence as
  ``keysightCounter.py``; fast and proven.
* ``"FREQ"``: used automatically whenever more than one channel is
  configured, and available for single-channel use if preferred.  Frequency
  readings are converted back to counts by multiplying by the gate time,
  so the downstream data units match what TOT produces.

SCPI sequence
-------------
The first channel is always set up with ``CONF:<func> …,(@<n>)``, which
establishes the measurement function and resets the instrument to a known
state.  Additional channels are added with ``SENS:FUNC "FREQ",(@<m>)``
without resetting the first.

Data ordering
-------------
When K channels are configured and ``SAMP:COUN = S``, ``FETC?`` returns K*S
values interleaved per sample::

    s0_ch1, s0_ch2, s1_ch1, s1_ch2, …

so channel index ``i`` (0-based within the sorted channel list) is extracted
with ``values[i::K]``.  A single-channel response is a plain list with no
interleaving.
"""

import usbtmc
import asyncio
from numpy import array


class counter_2channel:
    """
    Thin SCPI wrapper around one Keysight 53230A connection, shared by the
    ``keysight53230A_2channel`` DAQ layer.
    """

    def __init__(self):
        self.visa_address = "USB::0x0957::0x1907::INSTR"
        self.session = None
        self.configured_channels = ()
        self.mode = "TOT"      # "TOT" or "FREQ"; set by config()
        self.dwell = 1.0       # ms; used for FREQ → counts conversion
        # When True, SYST:ERR? is polled after each SCPI write during config()
        # so we can see exactly which command the instrument rejects.
        self.debug_scpi = True

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
    # Low-level SCPI helpers
    # ------------------------------------------------------------------

    def _check_error(self, context: str = ""):
        """
        Poll ``SYST:ERR?`` and print the first non-zero error.  Used during
        ``config()`` when ``self.debug_scpi`` is True to identify exactly
        which command the instrument rejected.
        """
        try:
            resp = self.session.ask("SYST:ERR?")
        except Exception as exc:
            print(f"[counter_2channel] SYST:ERR? failed ({context}): {exc}")
            return
        # Response format: '<code>,"<message>"'
        code_str = resp.split(",", 1)[0].strip()
        try:
            code = int(code_str)
        except ValueError:
            code = -1
        if code != 0:
            print(f"[counter_2channel] SCPI error after {context!r}: {resp}")

    def _write(self, cmd: str):
        """Write a SCPI command; poll error queue if debug_scpi is on."""
        self.session.write(cmd)
        if self.debug_scpi:
            self._check_error(cmd)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def config(self, dwell: float, channels: tuple = (1,),
               count: int = 1, samples: int = 1,
               trigger: str = "BUS", output: str = "OFF",
               mode: str = "TOT"):
        """
        Configure the instrument.

        :param dwell:    Gate time in **milliseconds**.
        :param channels: Sorted tuple of channels to enable, e.g. ``(1,)``,
                         ``(2,)`` or ``(1, 2)``.
        :param count:    ``TRIG:COUN`` — trigger events per ``INIT:IMM``.
        :param samples:  ``SAMP:COUN`` — samples per trigger event.
        :param trigger:  ``"BUS"`` or ``"EXT"``.
        :param output:   Gate-output state, ``"ON"`` or ``"OFF"``.
        :param mode:     ``"TOT"`` or ``"FREQ"``.  ``"TOT"`` is single-channel
                         only; any request with more than one channel is
                         silently upgraded to ``"FREQ"``.
        """
        mode = mode.upper()
        if len(channels) > 1 and mode != "FREQ":
            # TOT can't handle two channels — force FREQ.
            mode = "FREQ"

        self.mode = mode
        self.dwell = dwell
        self.configured_channels = tuple(channels)

        self._write("*RST")
        self._write("DISP ON")

        if mode == "TOT":
            # Single-channel timed totalize (matches original driver exactly)
            ch = channels[0]
            self._write(f"CONF:TOT:TIM {dwell / 1000.0},(@{ch})")

        elif mode == "FREQ":
            # Set up the first channel with CONF (which establishes the
            # measurement function and applies default gate source = TIME),
            # then add any additional channels with SENS:FUNC.
            #
            # Notes:
            #   * ``SENS:FUNC`` takes the function name in *double* quotes
            #     per the 53230A programmer's guide; single quotes produce
            #     a SCPI syntax error on this firmware.
            #   * No space is placed before ``(@N)`` in channel lists.
            #   * ``SENS:FREQ:GATE:SOUR TIME`` is the default after ``*RST``
            #     and ``CONF:FREQ``, so we don't re-send it.
            #   * ``SENS:FREQ:GATE:TIME`` does NOT accept a channel list on
            #     this instrument (adding one raises -108 "Parameter not
            #     allowed").  The gate time is a single global setting that
            #     applies to every channel configured for FREQ — both
            #     channels share the multiplexed gate window.
            first = channels[0]
            self._write(f"CONF:FREQ (@{first})")

            for ch in channels[1:]:
                self._write(f'SENS:FUNC "FREQ",(@{ch})')

            self._write(f"SENS:FREQ:GATE:TIME {dwell / 1000.0}")

        else:
            raise ValueError(f"counter_2channel: unknown mode {mode!r}")

        self._write(f"TRIG:COUN {count}")
        self._write(f"SAMP:COUN {samples}")
        self._write("TRIG:DEL 0")
        self._write("TRIG:SLOP POS")
        self._write(f"OUTP:STAT {output}")
        self._write(f"TRIG:SOUR {trigger}")

        # CONF? is used here as a synchronisation barrier — it blocks until
        # the instrument has finished processing the preceding config.
        self.session.ask("CONF?")
        if self.debug_scpi:
            self._check_error("end of config()")

    # ------------------------------------------------------------------
    # Trigger control (line-scan path)
    # ------------------------------------------------------------------

    def initLine(self):
        """Arm the instrument (``INIT:IMM``)."""
        self.session.write("INIT:IMM")

    def busTrigger(self):
        """Issue software trigger (``*TRG``)."""
        self.session.write("*TRG")

    # ------------------------------------------------------------------
    # Data acquisition
    # ------------------------------------------------------------------

    def _fetch(self, channels: tuple) -> dict:
        """
        Issue plain ``FETC?`` and parse into ``{channel: np.array}``.

        Using the unqualified ``FETC?`` (no ``(@N)`` channel list) is both
        the fastest and most reliable form on this instrument — the
        qualified form has been observed to cause USB timeouts.

        In ``FREQ`` mode readings come back in Hz; they are multiplied by the
        gate time in seconds to yield counts, matching the units the
        original TOT-based driver produces.
        """
        raw = self.session.ask("FETC?")
        print(raw)
        values = array(raw.split(","), dtype="float")

        if self.mode == "FREQ":
            # Hz × gate_seconds = counts
            values = values * (self.dwell / 1000.0)

        n = len(channels)
        if n == 1:
            return {channels[0]: values}
        return {ch: values[i::n] for i, ch in enumerate(channels)}

    async def getPoint(self, channels: tuple = (1,)) -> dict:
        """Arm, trigger, fetch a single point.  Returns ``{ch: array([v])}``."""
        self.session.write("INIT:IMM")
        self.session.write("*TRG")
        return self._fetch(channels)

    async def getLine(self, channels: tuple = (1,)) -> dict:
        """
        Fetch a line of samples.  ``initLine()`` and ``busTrigger()`` must
        have been called first.  Returns ``{ch: array([s0, s1, …])}``.
        """
        return self._fetch(channels)

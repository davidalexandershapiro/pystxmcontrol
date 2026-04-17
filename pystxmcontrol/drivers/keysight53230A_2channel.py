"""
DAQ driver for the Keysight 53230A universal counter — dual-channel variant.

Overview
--------
Two entries in ``daq.json`` can point at the same USB address with different
``"channel"`` values (1 or 2).  This module ensures they share one physical
instrument connection and that each line/point cycle issues exactly **one**
``INIT:IMM``, one ``*TRG``, and one ``FETC?``, collecting data from both
hardware counters simultaneously.

How sharing works
-----------------
* A **class-level registry** (``_shared``) maps each instrument address to a
  ``_SharedCounter`` that owns the ``counter_2channel`` connection, the
  per-channel config records, and a result cache for the current
  line/point.

* ``config()`` stores per-channel parameters in the shared record and
  reconfigures the physical instrument for **all channels that have had
  config() called on them** in the current scan setup.  Channels that are
  registered (``start()`` was called) but have not yet been configured are
  excluded — this correctly handles the case where only one channel is in
  the scan's ``daq_list``.

* **First-caller-fetches** pattern: the first ``getLine()`` or ``getPoint()``
  to execute (within an ``asyncio.gather`` call) finds an empty result cache,
  fetches all configured channels in a single ``FETC?``, and stores the
  result.  Subsequent callers find the cache populated and just extract their
  own channel's slice.  No explicit "primary" bookkeeping is required because
  asyncio coroutines with no internal suspension points run to completion
  before any sibling task starts.

* ``initLine()`` and ``bus_trigger()`` should only be called once per line;
  the scan code currently calls them on ``controller.daq["default"]``.  Each
  method guards against double-execution with an ``_is_primary`` check
  (lowest registered channel number = primary).

Measurement mode
----------------
Each daq.json entry accepts an optional ``"measurement_mode"`` key:

* ``"TOT"`` — single-channel timed totalize (matches the original
  ``keysight53230A`` driver byte-for-byte).  This is the default and should
  be used for single-channel configurations to preserve the fast SCPI path.
* ``"FREQ"`` — frequency measurement; the only mode that supports both
  channels simultaneously on this instrument.  Readings are internally
  converted from Hz back to counts (Hz × gate_time) so scan data still
  carries counts-per-pixel semantics.

Whenever two channels end up in the same scan's ``daq_list`` the driver
silently upgrades the mode to ``"FREQ"`` regardless of what ``daq.json``
says, because ``TOT:TIM`` physically cannot run on both channels.

daq.json example
----------------
::

    "counter_ch1": {
        "index": 0,
        "name": "Counter Ch1",
        "type": "point",
        "driver": "keysight53230A_2channel",
        "address": "USB::0x0957::0x1907::INSTR",
        "port": 5025,
        "channel": 1,
        "measurement_mode": "FREQ",
        "oversampling_factor": 1,
        "ndim": 0,
        "gate": true,
        "gate address": "/dev/arduino",
        "minimum dwell": 1,
        "dwell pad": 0,
        "time resolution": 1,
        "record": true,
        "simulation": false
    },
    "counter_ch2": {
        "index": 1,
        "name": "Counter Ch2",
        "type": "point",
        "driver": "keysight53230A_2channel",
        "address": "USB::0x0957::0x1907::INSTR",
        "port": 5025,
        "channel": 2,
        "measurement_mode": "FREQ",
        "oversampling_factor": 1,
        "ndim": 0,
        "gate": false,
        "minimum dwell": 1,
        "dwell pad": 0,
        "time resolution": 1,
        "record": true,
        "simulation": false
    }

Single-channel use
------------------
List only one entry in ``daq_list`` and set ``"measurement_mode": "TOT"``.
Only that channel is configured; ``FETC?`` returns one value per sample;
the code path is identical to the original driver.
"""

import threading
import asyncio

from numpy import array
from numpy.random import poisson

from pystxmcontrol.controller.daq import daq
from pystxmcontrol.drivers.keysightCounter_2channel import counter_2channel
from pystxmcontrol.drivers.shutter import shutter


# ---------------------------------------------------------------------------
# Internal shared-state helper
# ---------------------------------------------------------------------------

class _SharedCounter:
    """
    Holds the single ``counter_2channel`` connection shared by all
    ``keysight53230A_2channel`` instances that target the same address.
    """

    def __init__(self):
        self.counter = counter_2channel()
        self.ref_count = 0
        # channel → config dict; empty dict means registered but not yet configured
        self.channel_configs: dict = {}
        # result cache populated by the first getLine/getPoint caller;
        # None means stale (needs a fresh fetch)
        self.result_cache: dict = None
        # Channels that have already read from the current result_cache.  When
        # this set covers every configured channel the cache is auto-cleared
        # so the next getPoint/getLine triggers a fresh fetch.  Order-
        # independent: works regardless of which coroutine asyncio schedules
        # first.
        self.cache_consumers: set = set()

    def register(self, channel: int):
        self.channel_configs.setdefault(channel, {})
        self.ref_count += 1

    def unregister(self, channel: int):
        self.channel_configs.pop(channel, None)
        self.ref_count = max(0, self.ref_count - 1)

    def clear_cache(self):
        self.result_cache = None
        self.cache_consumers = set()

    def consume(self, channel: int):
        """
        Mark ``channel`` as having read from the current cache.  Once every
        configured channel has consumed, the cache is cleared so the next
        acquisition cycle fetches fresh data.
        """
        self.cache_consumers.add(channel)
        if self.cache_consumers >= set(self.get_configured_channels()):
            self.clear_cache()

    def get_configured_channels(self) -> tuple:
        """
        Sorted tuple of channels whose ``config()`` has been called in the
        current scan setup (non-empty config dict).

        Channels that are registered but not yet configured (empty dict from
        ``setdefault``) are excluded.  This ensures ``FETC?`` is only asked
        for channels that are actually armed.
        """
        return tuple(sorted(ch for ch, cfg in self.channel_configs.items() if cfg))

    @property
    def all_channels(self) -> tuple:
        """All registered channel numbers (regardless of config state)."""
        return tuple(sorted(self.channel_configs.keys()))


# ---------------------------------------------------------------------------
# DAQ driver
# ---------------------------------------------------------------------------

class keysight53230A_2channel(daq):
    """
    DAQ driver for one channel of the Keysight 53230A.

    Two instances targeting the same address cooperate via a class-level
    registry to share one USB connection and one ``FETC?`` call per
    acquisition cycle.  See module docstring for full details.
    """

    # Class-level registry: instrument address → _SharedCounter
    _shared: dict = {}
    _registry_lock = threading.Lock()

    def __init__(self, address="USB::0x0957::0x1907::INSTR",
                 port=None, simulation=False):
        self.address = address
        self.simulation = simulation
        self.meta = {
            "ndim": 0,
            "x": [],
            "type": "point",
            "name": "Keysight 53230A (2ch)",
            "channel": 1,
            "gate": False,
            "minimum dwell": 1,
            "dwell pad": 0,
            "time resolution": 1,
            # "TOT" (single-channel totalize, fast) or "FREQ" (dual-channel
            # capable; auto-selected whenever 2 channels are active).
            "measurement_mode": "TOT",
        }
        self.dwell = 1.0
        self.count = 1
        self.samples = 1
        self.trigger = "BUS"
        self.gate = None
        self._state: _SharedCounter = None  # set in start()

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def channel(self) -> int:
        return int(self.meta.get("channel", 1))

    def _is_primary(self) -> bool:
        """
        True if this channel has the lowest number among all *registered*
        channels for this instrument.  Used to elect one instance to issue
        ``INIT:IMM`` and ``*TRG`` (scan code currently calls these on a single
        hard-coded DAQ key; this guard prevents double-arming if that ever
        changes).
        """
        channels = self._state.all_channels if self._state else (self.channel,)
        return (not channels) or channels[0] == self.channel

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Connect (if first instance for this address) and register channel."""
        with keysight53230A_2channel._registry_lock:
            if self.address not in keysight53230A_2channel._shared:
                state = _SharedCounter()
                if not self.simulation:
                    state.counter.connect(self.address)
                keysight53230A_2channel._shared[self.address] = state
            state = keysight53230A_2channel._shared[self.address]
            state.register(self.channel)
            self._state = state

        if self.meta.get("gate"):
            self.gate = shutter(address=self.meta["gate address"])
            self.gate.connect(simulation=self.simulation)
            self.gate.setStatus(softGATE=0)

    def stop(self):
        """Unregister; disconnect the instrument when the last instance exits."""
        with keysight53230A_2channel._registry_lock:
            if self._state is not None:
                self._state.unregister(self.channel)
                if self._state.ref_count == 0:
                    if not self.simulation:
                        self._state.counter.disconnect()
                    keysight53230A_2channel._shared.pop(self.address, None)
                self._state = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_dwell(self, dwell: float):
        self.dwell = dwell

    def config(self, dwell, count: int = 1, samples: int = 1,
               trigger: str = "BUS", output: str = "OFF"):
        """
        Store this channel's configuration and push to the instrument.

        The instrument is (re)configured for **all channels that have had
        config() called** in this scan setup.  When ``config_daqs()`` iterates
        through the daq_list and calls config() on each entry, the last call
        sets the definitive instrument state with all participating channels.

        Channels that are registered but not in the current daq_list will
        never have config() called, so they stay out of
        ``get_configured_channels()`` and are excluded from FETC?.
        """
        if isinstance(dwell, list):
            self.dwell = dwell[0]
        else:
            self.dwell = dwell
        self.count = count
        self.samples = samples
        self.trigger = trigger

        # Mark this channel as configured in the shared record
        self._state.channel_configs[self.channel] = {
            "dwell": self.dwell,
            "count": count,
            "samples": samples,
            "trigger": trigger,
            "output": output,
        }

        if not self.simulation:
            channels = self._state.get_configured_channels()
            # Read requested mode from meta; the counter itself auto-upgrades
            # to "FREQ" whenever more than one channel is configured (TOT can
            # only operate on a single channel).
            mode = str(self.meta.get("measurement_mode", "TOT")).upper()
            self._state.counter.config(
                dwell=self.dwell,
                channels=channels,
                count=count,
                samples=samples,
                trigger=trigger,
                output=output,
                mode=mode,
            )
            if self.meta.get("gate") and self.gate is not None:
                self.setGateDwell(0, 0)

    # ------------------------------------------------------------------
    # Gate / shutter helpers
    # ------------------------------------------------------------------

    def autoGateOpen(self, shutter: int = 1):
        if self.gate is not None:
            self.gate.setStatus(softGATE=1, shutterMASK=shutter)

    def autoGateClosed(self):
        if self.gate is not None:
            self.gate.setStatus(softGATE=0)

    def setGateDwell(self, dwell1: float, dwell2: float = 0):
        if self.gate is not None:
            self.gate.dwell1 = dwell1
            self.gate.dwell2 = dwell2
            self.gate.setStatus()

    # ------------------------------------------------------------------
    # Trigger control  (line-scan path)
    # ------------------------------------------------------------------

    def initLine(self):
        """
        Clear the result cache and arm the instrument (``INIT:IMM``).

        The cache clear is unconditional so that the next getLine() call
        always performs a fresh fetch.  The INIT:IMM is guarded by
        ``_is_primary`` so only one instance arms the instrument even if
        this method is called on multiple DAQ objects.
        """
        self._state.clear_cache()
        if self._is_primary() and not self.simulation:
            self._state.counter.initLine()

    def bus_trigger(self):
        """Issue ``*TRG`` (primary instance only)."""
        if self._is_primary() and not self.simulation:
            self._state.counter.busTrigger()

    # ------------------------------------------------------------------
    # Data acquisition
    # ------------------------------------------------------------------

    async def getLine(self):
        """
        Fetch one full line of count data for this channel.

        First caller within an ``asyncio.gather`` group: finds an empty cache,
        calls ``FETC?`` for all configured channels, stores the result dict,
        and extracts its own channel's array.

        Subsequent callers: find the cache already populated and just extract
        their channel's array without touching the instrument.
        """
        if self.simulation:
            self.data = poisson(1e7 * self.dwell / 1000., self.count * self.samples)
            await asyncio.sleep(self.dwell / 1000. * self.count * self.samples)
            return self.data

        if self._state.result_cache is None:
            channels = self._state.get_configured_channels()
            result = await self._state.counter.getLine(channels=channels)
            self._state.result_cache = result

        self.data = self._state.result_cache[self.channel]
        self._state.consume(self.channel)
        return self.data

    async def getPoint(self):
        """
        Acquire a single point.

        Same first-caller-fetches pattern as ``getLine``.  The primary also
        issues ``INIT:IMM`` and ``*TRG`` (unlike ``getLine`` where those are
        done externally by the scan code).
        """
        if self.simulation:
            await asyncio.sleep(self.dwell / 1000.)
            self.data = array([poisson(1e7 * self.dwell / 1000.)])
            return self.data

        if self._state.result_cache is None:
            channels = self._state.get_configured_channels()
            result = await self._state.counter.getPoint(channels=channels)
            self._state.result_cache = result

        self.data = self._state.result_cache[self.channel]
        self._state.consume(self.channel)
        return self.data

    # ------------------------------------------------------------------
    # Compatibility stub
    # ------------------------------------------------------------------

    def setGate(self, gate: bool):
        pass

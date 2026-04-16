"""
DAQ driver for the Keysight 53230A universal counter — dual-channel variant.

Overview
--------
Two entries in ``daq.json`` can both point at the same USB address but with
different ``"channel"`` values (1 or 2).  This module ensures they share a
single physical instrument connection and that each measurement cycle issues
exactly **one** ``INIT:IMM``, one ``*TRG``, and one ``FETC?`` call, collecting
data from both hardware counters simultaneously.

How it works
------------
* A **class-level registry** (``keysight53230A_2channel._shared``) maps each
  instrument address to a ``_SharedCounter`` object that holds the
  ``counter_2channel`` instance and a per-channel config/result cache.

* The instance with the **lowest channel number** among those currently
  registered for a given address is the *primary*.  Only the primary issues
  instrument-level commands (``initLine``, ``bus_trigger``, ``getLine`` /
  ``getPoint``).  All secondaries are no-ops for those commands and instead read
  from the result cache populated by the primary.

* Because ``asyncio.gather`` runs coroutines on the same event loop and the
  underlying ``usbtmc`` calls contain no real ``await`` points, the primary's
  coroutine always completes before the secondary's starts.  The simple
  dict-based cache is therefore safe without additional locking.

* When only one channel is in ``daq_list`` the driver degrades gracefully to
  single-channel operation with no behaviour change visible to the scan code.

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
        "oversampling_factor": 1,
        "ndim": 0,
        "gate": true,
        "gate address": "/dev/arduino",
        "record": true,
        "simulation": true,
        "minimum dwell": 1,
        "dwell pad": 0,
        "time resolution": 1
    },
    "counter_ch2": {
        "index": 1,
        "name": "Counter Ch2",
        "type": "point",
        "driver": "keysight53230A_2channel",
        "address": "USB::0x0957::0x1907::INSTR",
        "port": 5025,
        "channel": 2,
        "oversampling_factor": 1,
        "ndim": 0,
        "gate": false,
        "record": true,
        "simulation": true,
        "minimum dwell": 1,
        "dwell pad": 0,
        "time resolution": 1
    }

scan.json example
-----------------
Set ``"daq_list"`` per scan type to select which channels participate::

    "Image": {
        "daq_list": "counter_ch1,counter_ch2",
        ...
    }
"""

import threading
import asyncio
import time

from numpy import array
from numpy.random import poisson

from pystxmcontrol.controller.daq import daq
from pystxmcontrol.drivers.keysightCounter_2channel import counter_2channel
from pystxmcontrol.drivers.shutter import shutter


# ---------------------------------------------------------------------------
# Shared-state helper (internal to this module)
# ---------------------------------------------------------------------------

class _SharedCounter:
    """
    Holds the single physical ``counter_2channel`` connection shared by all
    ``keysight53230A_2channel`` instances that target the same instrument
    address.

    Attributes
    ----------
    counter :
        The ``counter_2channel`` (low-level SCPI) object.
    ref_count :
        Number of ``keysight53230A_2channel`` instances currently registered.
    channel_configs :
        Maps channel number → most recent config kwargs for that channel.
    result_cache :
        Maps channel number → np.array from the most recent fetch.
        Set by the primary after a fetch; read by all secondaries.
        Cleared by ``clear_cache()``.
    """

    def __init__(self):
        self.counter = counter_2channel()
        self.ref_count = 0
        self.channel_configs: dict = {}   # channel → {dwell, count, samples, …}
        self.result_cache: dict = None    # channel → np.array; None = stale

    def register(self, channel: int):
        self.channel_configs.setdefault(channel, {})
        self.ref_count += 1

    def unregister(self, channel: int):
        self.channel_configs.pop(channel, None)
        self.ref_count = max(0, self.ref_count - 1)

    def clear_cache(self):
        self.result_cache = None

    @property
    def active_channels(self) -> tuple:
        """Sorted tuple of channel numbers currently registered."""
        return tuple(sorted(self.channel_configs.keys()))


# ---------------------------------------------------------------------------
# DAQ driver
# ---------------------------------------------------------------------------

class keysight53230A_2channel(daq):
    """
    DAQ driver for a single channel of the Keysight 53230A, designed to work
    in concert with a second instance sharing the same instrument.

    See module docstring for usage details.
    """

    # Class-level registry: address string → _SharedCounter
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
        }
        self.dwell = 1.0
        self.count = 1
        self.samples = 1
        self.trigger = "BUS"
        self.gate = None
        self._state: _SharedCounter = None   # set in start()

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def channel(self) -> int:
        return int(self.meta.get("channel", 1))

    def _is_primary(self) -> bool:
        """
        True if this instance has the lowest channel number among those
        currently registered for this instrument.
        """
        channels = self._state.active_channels if self._state else (self.channel,)
        return channels[0] == self.channel if channels else True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """
        Register with the shared connection pool and connect if we are the
        first instance for this address.
        """
        with keysight53230A_2channel._registry_lock:
            if self.address not in keysight53230A_2channel._shared:
                keysight53230A_2channel._shared[self.address] = _SharedCounter()
                if not self.simulation:
                    keysight53230A_2channel._shared[self.address].counter.connect(
                        self.address
                    )
            state = keysight53230A_2channel._shared[self.address]
            state.register(self.channel)
            self._state = state

        # Gate / shutter — only the channel that has "gate": true needs one
        if self.meta.get("gate"):
            self.gate = shutter(address=self.meta["gate address"])
            self.gate.connect(simulation=self.simulation)
            self.gate.setStatus(softGATE=0)

    def stop(self):
        """
        Unregister from the shared pool.  Disconnect the instrument when the
        last reference is released.
        """
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
        Store this channel's configuration and push it to the instrument.

        The instrument is reconfigured for **all currently registered channels**
        on every call, so the final ``config()`` call in a ``config_daqs()``
        loop sets the definitive instrument state.  (Intermediate calls are
        harmless — the second call overwrites with the same parameters.)
        """
        if isinstance(dwell, list):
            self.dwell = dwell[0]
        else:
            self.dwell = dwell
        self.count = count
        self.samples = samples
        self.trigger = trigger

        # Record this channel's config in the shared state
        self._state.channel_configs[self.channel] = {
            "dwell": self.dwell,
            "count": count,
            "samples": samples,
            "trigger": trigger,
            "output": output,
        }

        if not self.simulation:
            # Reconfigure the instrument for ALL registered channels.
            # Using SENS:FUNC (not CONF:TOT:TIM) so both channels stay active.
            self._state.counter.config(
                dwell=self.dwell,
                channels=self._state.active_channels,
                count=count,
                samples=samples,
                trigger=trigger,
                output=output,
            )
            if self.meta.get("gate") and self.gate is not None:
                self.setGateDwell(0, 0)

    # ------------------------------------------------------------------
    # Gate / shutter helpers (unchanged from original driver)
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
    # Trigger control (line-scan path)
    # ------------------------------------------------------------------

    def initLine(self):
        """
        Arm the instrument for a line scan.

        Only the primary instance issues INIT:IMM; secondaries are no-ops.
        Also clears the result cache so the upcoming fetch is always fresh.
        """
        if self._is_primary():
            self._state.clear_cache()
            if not self.simulation:
                self._state.counter.initLine()

    def bus_trigger(self):
        """Issue *TRG (primary only)."""
        if self._is_primary() and not self.simulation:
            self._state.counter.busTrigger()

    # ------------------------------------------------------------------
    # Data acquisition
    # ------------------------------------------------------------------

    async def getLine(self):
        """
        Fetch one full line of count data for this channel.

        *Primary*: issues ``FETC? (@1,2)`` (or whichever channels are active),
        populates ``_state.result_cache``, then extracts its own channel.

        *Secondary*: reads directly from ``_state.result_cache`` which the
        primary already populated (safe because asyncio runs these coroutines
        sequentially when there are no real ``await`` points).
        """
        if self.simulation:
            self.data = poisson(1e7 * self.dwell / 1000., self.count * self.samples)
            await asyncio.sleep(self.dwell / 1000. * self.count * self.samples)
            return self.data

        if self._state.result_cache is None:
            # We are either the primary or the only channel — fetch all at once
            result = await self._state.counter.getLine(
                channels=self._state.active_channels
            )
            self._state.result_cache = result

        self.data = self._state.result_cache[self.channel]
        return self.data

    async def getPoint(self):
        """
        Acquire a single point.

        *Primary*: issues INIT:IMM + *TRG + ``FETC?``, caches result.
        *Secondary*: reads from cache.
        """
        if self.simulation:
            await asyncio.sleep(self.dwell / 1000.)
            self.data = array([poisson(1e7 * self.dwell / 1000.)])
            return self.data

        if self._is_primary():
            # Clear any stale cache from the previous point before fetching
            self._state.clear_cache()
            result = await self._state.counter.getPoint(
                channels=self._state.active_channels
            )
            self._state.result_cache = result

        self.data = self._state.result_cache[self.channel]
        return self.data

    # ------------------------------------------------------------------
    # Legacy / compatibility
    # ------------------------------------------------------------------

    def setGate(self, gate: bool):
        """Stub kept for API compatibility with base class callers."""
        pass

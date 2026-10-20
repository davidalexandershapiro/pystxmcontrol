"""DAQ IOC: keysight counter family behind gated-acquire PVs."""
from __future__ import annotations

import argparse
import asyncio
import functools

from pystxmcontrol.iocs import configure_ioc_logging, require_caproto

require_caproto()

from caproto import ChannelType  # noqa: E402
from caproto.server import PVGroup, pvproperty, run  # noqa: E402

from pystxmcontrol.iocs.config import read_slice  # noqa: E402

MAX_LINE = 16384


class DaqGroup(PVGroup):
    dwell = pvproperty(value=1.0, name=":DWELL", precision=3, doc="dwell per point, ms")
    mode = pvproperty(value=0, enum_strings=("point", "line"),
                      dtype=ChannelType.ENUM, name=":MODE")
    acquire = pvproperty(value=0, name=":ACQUIRE",
                         doc="write 1: acquire one point; put completes when done")
    counts = pvproperty(value=0.0, name=":COUNTS", read_only=True)
    counts_wf = pvproperty(value=[0.0], name=":COUNTS:WF", read_only=True,
                           max_length=MAX_LINE)
    rate = pvproperty(value=0.0, name=":RATE", read_only=True, doc="counts/s")

    def __init__(self, prefix, *, daq, daq_entry, **kwargs):
        super().__init__(prefix, **kwargs)
        self._daq = daq
        self._entry = daq_entry
        self._started = False

    async def _ensure_started(self):
        if not self._started:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._daq.start)
            self._started = True

    @mode.putter
    async def mode(self, instance, value):
        # caproto delivers the enum STRING to the putter (ChannelEnum.verify_value
        # maps a valid index write to its enum string first). Anything else --
        # an unknown string from a STRING-dtype write, or an out-of-range index
        # that verify_value passed through unmapped -- is rejected here.
        if value not in instance.enum_strings:
            raise ValueError(f"invalid MODE {value!r}; expected one of "
                             f"{instance.enum_strings}")
        return value

    @acquire.putter
    async def acquire(self, instance, value):
        if not value:
            return 0
        await self._ensure_started()
        loop = asyncio.get_running_loop()
        dwell_ms = self.dwell.value
        await loop.run_in_executor(
            None, functools.partial(self._daq.config, dwell_ms, count=1, samples=1))
        data = await self._daq.getPoint()  # coroutine on OUR loop
        c = float(data[0])
        await self.counts.write(c)
        await self.rate.write(c / (dwell_ms / 1000.0) if dwell_ms else 0.0)
        return 0

    async def write_line(self, line) -> None:
        """Publish a fly-line waveform (called in-process by the fly loop)."""
        await self.counts_wf.write([float(x) for x in line])
        if len(line):
            await self.counts.write(float(line[-1]))


def build_pvdb_for_entry(entry: dict, prefix: str):
    import pystxmcontrol.drivers as drv
    cls = getattr(drv, entry["driver"])
    daq = cls(address=entry["address"], port=entry.get("port", 0),
              simulation=entry["simulation"])
    daq.meta.update(entry)  # UPDATE not replace: keeps default 'gate' key
    group = DaqGroup(prefix, daq=daq, daq_entry=entry)
    return dict(group.pvdb), group


def build_pvdb_from_slice(s: dict) -> dict:
    if s["kind"] != "daq":
        raise ValueError(f"daq_ioc requires kind=daq, got {s['kind']!r}")
    pvdb, _ = build_pvdb_for_entry(s["entry"], s["prefix"])
    return pvdb


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    configure_ioc_logging()
    run(build_pvdb_from_slice(read_slice(args.slice)), log_pv_names=not args.quiet)


if __name__ == "__main__":
    main()

"""Shutter/gate IOC: MODE enum over David's shutter.setStatus semantics."""
from __future__ import annotations

import argparse
import asyncio

from pystxmcontrol.iocs import configure_ioc_logging, require_caproto

require_caproto()

from caproto import ChannelType  # noqa: E402
from caproto.server import PVGroup, pvproperty, run  # noqa: E402

from pystxmcontrol.iocs.config import read_slice  # noqa: E402

_MODE_MAP = {"OPEN": "open", "CLOSED": "close", "AUTO": "auto"}


class ShutterGroup(PVGroup):
    mode = pvproperty(value="AUTO", enum_strings=list(_MODE_MAP),
                      dtype=ChannelType.ENUM, name=":MODE")
    state = pvproperty(value="CLOSED", enum_strings=["CLOSED", "OPEN"],
                       dtype=ChannelType.ENUM, name=":STATE", read_only=True)

    def __init__(self, prefix, *, shutter, poll=0.5, **kwargs):
        super().__init__(prefix, **kwargs)
        self._shutter = shutter
        self._poll = poll

    @mode.putter
    async def mode(self, instance, value):
        loop = asyncio.get_running_loop()

        def apply():
            mode = _MODE_MAP[str(value)]
            self._shutter.mode = mode
            # OPEN forces the beam continuously open via the software gate
            # (softGATE=1): a continuous fly free-runs the counter with no
            # per-dwell hardware gate pulse, so the shutter must be HELD open
            # for the whole line (mirrors legacy autoGateOpen). CLOSED/AUTO
            # leave softGATE=0 so the shutter stays hardware-gated.
            self._shutter.softGATE = 1 if mode == "open" else 0
            self._shutter.setStatus()

        await loop.run_in_executor(None, apply)
        return value

    @state.scan(period=0.5)
    async def state(self, instance, async_lib):
        loop = asyncio.get_running_loop()
        is_open = await loop.run_in_executor(None, self._shutter.getStatus)
        await instance.write("OPEN" if is_open else "CLOSED")


def build_pvdb_from_slice(s: dict) -> dict:
    if s["kind"] != "shutter":
        raise ValueError(f"shutter_ioc requires kind=shutter, got {s['kind']!r}")
    from pystxmcontrol.drivers.shutter import shutter as Shutter
    sh = Shutter(address=s["address"])
    sh.connect(simulation=bool(s["simulation"]))
    return dict(ShutterGroup(s["prefix"], shutter=sh).pvdb)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    configure_ioc_logging()
    run(build_pvdb_from_slice(read_slice(args.slice)), log_pv_names=not args.quiet)


if __name__ == "__main__":
    main()

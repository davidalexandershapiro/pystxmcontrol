"""Derived-motor IOC support.

Co-located: derived driver composed IN-PROCESS inside the owning controller's
IOC (David's exact wiring). Cross-controller: this module's CLI runs a small
IOC whose derived driver composes the underlying axes VIA CA (CAMotorProxy),
so composition and physical IOCs restart independently.
"""
from __future__ import annotations

import argparse
import threading

from pystxmcontrol.iocs import configure_ioc_logging, require_caproto

require_caproto()

_AXIS_LETTER_TO_INDEX = {"x": 1, "y": 2, "z": 3}
_AXIS_INDEX_TO_LETTER = {"axis1": "x", "axis2": "y", "axis3": "z"}


def _ensure_controller_get_axis(controller) -> None:
    """Patch a ``getAxis(letter) -> int`` method onto a controller INSTANCE
    if its driver class doesn't define one.

    ``derivedPiezo.connect()`` unconditionally calls
    ``self.axes["axis1"].controller.getAxis(letter)`` (even in simulation
    mode) to map an 'x'/'y' axis letter to a 1-based controller axis index.
    Some controller drivers (e.g. ``xpsController``) never implement this --
    it looks like ``derivedPiezo`` was only ever paired with controllers that
    do (``mclController``, ``nptController``, ``xerController``). Since we
    must not modify David's driver source, we monkeypatch a minimal
    letter->index mapping onto the controller INSTANCE at IOC-build time
    (not the class), only when the method is missing. Anything outside the
    known x/y/z convention raises loudly rather than guessing.
    """
    if hasattr(controller, "getAxis"):
        return

    def getAxis(name, _map=_AXIS_LETTER_TO_INDEX):
        try:
            return _map[name.lower()]
        except KeyError:
            raise NotImplementedError(
                f"{controller!r} has no getAxis() and no known axis-letter "
                f"mapping for {name!r} (only {sorted(_map)} supported)"
            )

    controller.getAxis = getAxis


def build_derived_colocated(slice_dict: dict, motors_by_key: dict,
                            io_lock=None) -> dict:
    import pystxmcontrol.drivers as drv
    from pystxmcontrol.iocs.base import MotorRecordGroup

    pvdb: dict = {}
    for d in slice_dict.get("derived", []):
        entry = d["entry"]
        m = getattr(drv, entry["driver"])()
        for ax, underlying_key in entry["axes"].items():
            underlying = motors_by_key[underlying_key]
            controller = getattr(underlying, "controller", None)
            if controller is not None:
                _ensure_controller_get_axis(controller)
            m.axes[ax] = underlying
        setattr(m, "config", entry)
        m.connect(axis=d["key"])
        m.offset = entry["offset"]
        m.units = entry["units"]
        motors_by_key[d["key"]] = m
        # A co-located derived motor reads/writes its underlying axes on the
        # same controller, so it shares the controller's io_lock to serialize
        # with the primary axes' pollers on the shared link.
        group = MotorRecordGroup(d["pv"], driver=m, motor_config=entry,
                                 io_lock=io_lock)
        pvdb.update(group.pvdb)
    return pvdb


class _ProxyController:
    """Minimal controller stand-in for CA-proxied axes."""
    simulation = False

    def __init__(self):
        self.lock = threading.Lock()

    def getAxis(self, name):
        return 1


class CAMotorProxy:
    """pystxmcontrol motor-interface facade over a live EPICS motor record."""

    def __init__(self, pv: str, ctx, axis_label: str = "x"):
        self._pvs = dict(zip(
            ("val", "rbv", "movn", "stop", "hlm", "llm", "velo"),
            ctx.get_pvs(pv, pv + ".RBV", pv + ".MOVN", pv + ".STOP",
                        pv + ".HLM", pv + ".LLM", pv + ".VELO", timeout=30),
        ))
        self._pvs["val"].wait_for_connection(timeout=30)
        self.axis = axis_label
        self.simulation = False
        self.controller = _ProxyController()
        hlm = float(self._pvs["hlm"].read().data[0])
        llm = float(self._pvs["llm"].read().data[0])
        velo = float(self._pvs["velo"].read().data[0])
        self.config = {
            "minValue": llm, "maxValue": hlm, "offset": 0.0, "units": 1.0,
            "maxScanRange": hlm - llm, "max velocity": velo, "simulation": 0,
        }
        self.offset = 0.0
        self.units = 1.0
        self.moving = False

    def moveTo(self, pos, **kwargs):
        # MotorRecordGroup holds .VAL put-completion until the physical move
        # finishes (DMOV=1), so wait=True alone gives synchronous moveTo
        # semantics matching David's other motor drivers. One RBV read
        # afterwards refreshes the cached position for callers.
        self._pvs["val"].write(float(pos), wait=True, timeout=120)
        self.getPos()

    def moveBy(self, step, **kwargs):
        self.moveTo(self.getPos() + step)

    def getPos(self, **kwargs):
        return float(self._pvs["rbv"].read().data[0])

    def getStatus(self, **kwargs):
        return bool(self._pvs["movn"].read().data[0])

    def stop(self):
        self._pvs["stop"].write(1, wait=True, timeout=10)

    def checkLimits(self, pos):
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def setAxisParams(self, velocity=None, **kwargs):
        if velocity is not None:
            self._pvs["velo"].write(float(velocity), wait=True, timeout=10)

    def connect(self, axis=None, **kwargs):
        return True


def build_pvdb_from_slice(s: dict) -> dict:
    if s["kind"] != "derived_remote":
        raise ValueError(f"derived_ioc requires kind=derived_remote, got {s['kind']!r}")
    import pystxmcontrol.drivers as drv
    from caproto.threading.client import Context
    from pystxmcontrol.iocs.base import MotorRecordGroup

    ctx = Context()
    entry = s["entry"]
    m = getattr(drv, entry["driver"])()
    for ax, pv in s["axis_pvs"].items():
        # ``ax`` here is the derivedPiezo axes-dict KEY ("axis1"/"axis2"/...),
        # not a real motor axis letter -- CAMotorProxy.axis_label is only used
        # for display/getAxis, so map it to the conventional x/y/z letter by
        # position (axis1 -> x, axis2 -> y, axis3 -> z) for a readable label.
        # Anything beyond axis3 falls back to the raw key rather than guessing.
        letter = _AXIS_INDEX_TO_LETTER.get(ax, ax)
        m.axes[ax] = CAMotorProxy(pv, ctx, axis_label=letter)
    setattr(m, "config", entry)
    m.connect(axis=s["key"])
    m.offset = entry["offset"]
    m.units = entry["units"]
    group = MotorRecordGroup(s["prefix"], driver=m, motor_config=entry)
    return group.pvdb


def main(argv=None):
    from caproto.server import run
    from pystxmcontrol.iocs.config import read_slice
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", required=True)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    configure_ioc_logging()
    pvdb = build_pvdb_from_slice(read_slice(args.slice))
    run(pvdb, log_pv_names=not args.quiet)


if __name__ == "__main__":
    main()

"""Parse David's motor.json/daq.json into an IOC fleet model.

The JSON files remain the single source of truth; this module only READS them
(plus an optional per-entry "epics" sub-dict) and never mutates them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name.strip())


# Controller classes whose motors implement the IOC-side line-fly interface
# (update_trajectory/moveLine/trajectory_* + continuous lineMode). A controller
# group built from one of these is served by the fly IOC (motor records + a FLY
# PVGroup that absorbs the DAQ entries) instead of the plain motor IOC. Both
# supervisor.plan_fleet (routing) and fly_ioc.build_pvdb_from_slice (guard)
# read this set so the two stay in agreement.
FLY_CAPABLE_CONTROLLERS = {"E712Controller", "nptController", "mmcController"}


@dataclass
class MotorEntry:
    key: str
    entry: dict
    pv: str


@dataclass
class ControllerGroup:
    controller_id: str
    controller_cls: str
    label: str
    port: int
    simulation: bool
    motors: list[MotorEntry] = field(default_factory=list)
    derived: list[MotorEntry] = field(default_factory=list)


@dataclass
class DerivedRemoteGroup:
    key: str
    entry: dict
    prefix: str
    axis_pvs: dict[str, str]


@dataclass
class DaqEntry:
    key: str
    entry: dict
    prefix: str


@dataclass
class ShutterEntry:
    key: str
    address: str
    prefix: str
    simulation: bool


@dataclass
class FleetConfig:
    station: str
    controller_groups: list[ControllerGroup]
    derived_remote: list[DerivedRemoteGroup]
    daqs: list[DaqEntry]
    shutters: list[ShutterEntry]
    motor_pv: dict[str, str]
    skipped: list[tuple[str, str]]


def _label_for(cls_name: str) -> str:
    base = cls_name[: -len("Controller")] if cls_name.endswith("Controller") else cls_name
    return sanitize(base).upper()


def _driver_available(driver: str) -> bool:
    import pystxmcontrol.drivers as drv
    return hasattr(drv, driver)


def load_fleet(motor_json_path: str, daq_json_path: str, station: str = "SIM") -> FleetConfig:
    with open(motor_json_path) as f:
        motor_cfg = json.load(f)
    with open(daq_json_path) as f:
        daq_cfg = json.load(f)

    skipped: list[tuple[str, str]] = []
    motor_pv: dict[str, str] = {}
    groups: dict[str, ControllerGroup] = {}
    labels_used: dict[str, int] = {}

    def full_pv(key: str, entry: dict, label: str) -> str:
        override = entry.get("epics", {}).get("pv")
        return override if override else f"STXM{station}:{label}:{sanitize(key)}"

    # --- primaries ---
    for key, entry in motor_cfg.items():
        if entry.get("type") != "primary":
            continue
        driver = entry["driver"]
        if driver == "epicsMotor":
            skipped.append((key, "already an EPICS motor"))
            continue
        if not _driver_available(driver) or not _driver_available(entry["controller"]):
            skipped.append((key, f"driver {driver}/{entry['controller']} unavailable"))
            continue
        cid = entry["controllerID"]
        if cid not in groups:
            cls = entry["controller"]
            base = _label_for(cls)
            n = labels_used.get(base, 0) + 1
            labels_used[base] = n
            label = base if n == 1 else f"{base}_{n}"
            groups[cid] = ControllerGroup(
                controller_id=cid, controller_cls=cls, label=label,
                port=int(entry.get("port", 0)),
                simulation=bool(entry.get("simulation", 1)),
            )
        g = groups[cid]
        pv = full_pv(key, entry, g.label)
        g.motors.append(MotorEntry(key=key, entry=entry, pv=pv))
        motor_pv[key] = pv

    # --- derived ---
    derived_remote: list[DerivedRemoteGroup] = []
    for key, entry in motor_cfg.items():
        if entry.get("type") != "derived":
            continue
        driver = entry["driver"]
        if not _driver_available(driver):
            skipped.append((key, f"driver {driver} unavailable"))
            continue
        axes = entry["axes"]
        underlying = [motor_cfg.get(v) for v in axes.values()]
        if any(u is None for u in underlying) or any(
            axes_key not in motor_pv for axes_key in axes.values()
        ):
            skipped.append((key, "underlying axis missing or skipped"))
            continue
        cids = {u["controllerID"] for u in underlying if u.get("type") == "primary"}
        if len(cids) == 1 and (cid := next(iter(cids))) in groups:
            g = groups[cid]
            pv = full_pv(key, entry, g.label)
            g.derived.append(MotorEntry(key=key, entry=entry, pv=pv))
            motor_pv[key] = pv
        else:
            prefix = entry.get("epics", {}).get("pv") or f"STXM{station}:DERIVED:{sanitize(key)}"
            derived_remote.append(DerivedRemoteGroup(
                key=key, entry=entry, prefix=prefix,
                axis_pvs={ax: motor_pv[mk] for ax, mk in axes.items()},
            ))
            motor_pv[key] = prefix

    # --- daqs + shutters ---
    daqs: list[DaqEntry] = []
    shutters: list[ShutterEntry] = []
    seen_gate: dict[str, ShutterEntry] = {}
    for key, entry in daq_cfg.items():
        prefix = entry.get("epics", {}).get("pv") or f"STXM{station}:{sanitize(key).upper()}"
        daqs.append(DaqEntry(key=key, entry=entry, prefix=prefix))
        if entry.get("gate") and entry.get("gate address") and entry["gate address"] not in seen_gate:
            n = len(seen_gate) + 1
            seen_gate[entry["gate address"]] = ShutterEntry(
                key=f"shutter{n}", address=entry["gate address"],
                prefix=f"STXM{station}:SHUTTER{n}",
                simulation=bool(entry.get("simulation", True)),
            )
    shutters = list(seen_gate.values())

    return FleetConfig(
        station=station,
        controller_groups=list(groups.values()),
        derived_remote=derived_remote,
        daqs=daqs,
        shutters=shutters,
        motor_pv=motor_pv,
        skipped=skipped,
    )


# --- slice files handed to IOC subprocesses (Windows spawn-safe: path arg, not blob) ---

def write_slice(group, fleet: FleetConfig, path: str, daqs: list["DaqEntry"] | None = None) -> None:
    if isinstance(group, ControllerGroup):
        payload = {
            "kind": "controller",
            "station": fleet.station,
            "controller_id": group.controller_id,
            "controller_cls": group.controller_cls,
            "label": group.label,
            "port": group.port,
            "simulation": group.simulation,
            "motors": [{"key": m.key, "entry": m.entry, "pv": m.pv} for m in group.motors],
            "derived": [{"key": m.key, "entry": m.entry, "pv": m.pv} for m in group.derived],
            "motor_pv": fleet.motor_pv,
        }
        if daqs:
            payload["daqs"] = [{"key": d.key, "entry": d.entry, "prefix": d.prefix} for d in daqs]
        # gate address -> shutter :MODE PV prefix, so the fly IOC can drive the
        # beam shutter (owned by the shutter IOC) over CA during a line.
        payload["shutters"] = {sh.address: sh.prefix for sh in fleet.shutters}
    elif isinstance(group, DerivedRemoteGroup):
        payload = {
            "kind": "derived_remote",
            "station": fleet.station,
            "key": group.key,
            "entry": group.entry,
            "prefix": group.prefix,
            "axis_pvs": group.axis_pvs,
            "motor_pv": fleet.motor_pv,
        }
    elif isinstance(group, DaqEntry):
        payload = {"kind": "daq", "station": fleet.station, "key": group.key,
                   "entry": group.entry, "prefix": group.prefix, "motor_pv": fleet.motor_pv}
    elif isinstance(group, ShutterEntry):
        payload = {"kind": "shutter", "station": fleet.station, "key": group.key,
                   "address": group.address, "prefix": group.prefix,
                   "simulation": group.simulation, "motor_pv": fleet.motor_pv}
    else:  # pragma: no cover
        raise TypeError(f"unknown group type {type(group)!r}")
    with open(path, "w") as f:
        json.dump(payload, f, indent=1)


def read_slice(path: str) -> dict:
    with open(path) as f:
        return json.load(f)

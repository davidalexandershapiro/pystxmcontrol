"""Reading motor.json: which motors exist, how they group, and what to show.

Split out of ``mainwindow_dashboard``.  These are plain queries over the motor
config dictionary the server hands out (or the on-disk copy in placeholder
mode) — no Qt, no window state — so the rules about what appears where can be
checked directly.

Two visibility rules live here and are easy to confuse:

* ``display`` gates the **scan-axis dropdowns** in both modes.  A motor must opt
  in to be selectable as a scan axis.
* The **move/jog rail** shows every motor in Staff mode, and only ``display``
  motors in User mode.

So a motor with ``display: false`` can still be jogged by staff, but can never
be chosen as a scan axis.
"""

import json
import os
import sys

# Driver name → the short badge shown on a motor row.
DRIVER_KIND = {
    "derivedPiezo": "PIEZO", "inclinedDerivedPiezo": "PIEZO",
    "mclMotor": "MCL", "xpsMotor": "XPS", "xerMotor": "XERYON",
    "bcsMotor": "BCS", "derivedEnergy": "DERIVED", "epicsMotor": "EPICS",
}


def load_motor_info():
    """Motor config from the runtime file the server also reads
    (``sys.prefix/pystxmcontrol_cfg/motor.json``), falling back to the repo
    copy.  When connected, the live config from the controller is preferred."""
    candidates = [
        os.path.join(sys.prefix, "pystxmcontrol_cfg", "motor.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "motor.json"),
    ]
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def frac(val, lo, hi):
    """``val``'s position within ``lo``..``hi`` as 0..1, for the travel bar.
    An unusable range reads as mid-travel rather than raising."""
    try:
        return max(0.0, min(1.0, (val - lo) / (hi - lo)))
    except (TypeError, ZeroDivisionError):
        return 0.5


def group_of(d):
    """The motor's tab group, from motor.json's ``group`` field.  Falls back to
    the legacy ``panel`` field (for configs not yet migrated), then to
    ``beamline`` when a motor declares no group at all."""
    for key in ("group", "panel"):
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return "beamline"


def is_visible(d):
    """The ``display`` flag, tolerating the string forms configs use."""
    v = d.get("display", False)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return bool(v)


def motors_sorted(motor_info):
    """All motors, index-ordered.  Includes ``display: false`` ones — use
    :func:`visible_motors` for anything the user picks from."""
    return sorted(motor_info.items(), key=lambda kv: kv[1].get("index", 999))


def visible_motors(motor_info):
    """Motors selectable as a scan axis — the basis for every motor dropdown."""
    return [(n, d) for n, d in motors_sorted(motor_info) if is_visible(d)]


def motor_groups(motor_info):
    """Distinct motor groups, ordered by first appearance in index order — so
    each group ranks by its lowest-index motor.  One tab is built per group."""
    groups = []
    for _name, d in motors_sorted(motor_info):
        g = group_of(d)
        if g not in groups:
            groups.append(g)
    return groups


def motor_rows(motor_info, group, expert=False):
    """Row tuples ``(name, kind, pos, unit, frac, moving)`` for one group's
    move/jog rows.  Staff mode lists every motor; User mode hides
    ``display: false`` ones."""
    rows = []
    for name, d in motors_sorted(motor_info):
        if group_of(d) != group:
            continue
        if not expert and not is_visible(d):
            continue
        kind = DRIVER_KIND.get(d.get("driver"),
                               str(d.get("driver", "")).upper())
        val = float(d.get("last value", 0.0) or 0.0)
        rows.append((name, kind, f"{val:.2f}", d.get("unit", ""),
                     frac(val, d.get("minValue"), d.get("maxValue")), False))
    return rows


def jog_step(d):
    """A sensible per-axis nudge: the motor's configured scan step if positive,
    else 1% of its travel, else 1.0.  motor.json has no dedicated jog-step
    field, so one is derived."""
    try:
        step = float(d.get("last step:"))
    except (TypeError, ValueError):
        step = 0.0
    if step > 0:
        return step
    try:
        span = float(d.get("maxValue")) - float(d.get("minValue"))
        if span > 0:
            return span * 0.01
    except (TypeError, ValueError):
        pass
    return 1.0


def format_enum(v):
    """Format an allowed-value entry: an integer when whole, else compact."""
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f:g}"
    except (TypeError, ValueError):
        return str(v)

"""Saved energy definitions ("energy presets"), shared by the GUI and the agents.

A preset is JSON holding the same ``energy_regions`` structure a scan definition
uses, so the files the GUI writes and reads are exactly the files the agents see::

    {"energy_regions": {"EnergyRegion1": {"start": 280.0, "stop": 282.0,
                                          "step": 0.5, "n_energies": 5,
                                          "dwell": 1.0}, ...}}

A bare ``{"EnergyRegionN": {...}}`` dict (no wrapper key) is accepted too — that is
what ``mainwindow_mvc.open_energy_definition`` has always tolerated.

Two *named* sources are searched, so a preset can be referred to by name instead of
by path:

``favorites``
    The dashboard Favorites bar file, ``dashboard_energy_favorites.json``, whose
    entries carry an explicit ``alias``.
``presets directory``
    ``pystxmcontrol_cfg/energy_presets/*.json`` — the file stem is the name.  A
    definition saved there with the dashboard's "Save Preset" (or dropped in by
    hand) is immediately visible to both the GUI loader and the agents.

Both locations sit under ``sys.prefix/pystxmcontrol_cfg`` by default, which is right
for the GUI and for an MCP server launched from the same environment.  A deployment
that does not share that prefix — the container, whose ``sys.prefix`` is
``/usr/local`` and which reaches the beamline's config only through a bind mount —
points at them with ``PYSTXM_CFG_DIR`` (or the narrower ``PYSTXM_ENERGY_PRESETS_DIR``
/ ``PYSTXM_ENERGY_FAVORITES_JSON``); see the constants below.

Multiple regions with **per-region dwell** are preserved throughout: the server
honours them (``writeNX._extractEnergies`` builds a per-energy dwell array that the
scan drivers index), so a preset means the same thing whether it is applied from
the GUI or by an agent.
"""

import glob
import json
import os
import sys

# Directories searched for the runtime config, most-preferred first.  Mirrors the
# dashboard's original _favorites_file_path so an already-saved favorites file
# keeps its location.
_CONFIG_DIRS = (
    os.path.join(sys.prefix, "pystxmcontrol_cfg"),
    os.path.join(os.path.dirname(__file__), "..", "..", "config"),
)

# Environment overrides, for deployments where the presets are not next to the code
# or under this interpreter's sys.prefix — chiefly the MCP container, whose
# sys.prefix is /usr/local and which sees the beamline's config only through a bind
# mount.  Mirrors the PYSTXM_MAIN_JSON / PYSTXM_SERVER_HOST pattern used elsewhere:
# everything site-specific is injected at runtime.
#
#   PYSTXM_CFG_DIR              a pystxmcontrol_cfg-style directory (favorites file
#                               + energy_presets/ subdirectory)
#   PYSTXM_ENERGY_PRESETS_DIR   just the directory of *.json presets
#   PYSTXM_ENERGY_FAVORITES_JSON  just the favorites file
#
# The granular two exist so a site can share presets WITHOUT mounting the whole
# config directory, which also holds main.json and its staff-password secrets.
# An override is honoured even when the path does not exist, so a wrong path shows
# up verbatim in the "no presets found, they come from ..." message instead of
# silently falling back to somewhere else.
CFG_DIR_ENV = "PYSTXM_CFG_DIR"
PRESETS_DIR_ENV = "PYSTXM_ENERGY_PRESETS_DIR"
FAVORITES_ENV = "PYSTXM_ENERGY_FAVORITES_JSON"

FAVORITES_BASENAME = "dashboard_energy_favorites.json"
PRESETS_DIRNAME = "energy_presets"


def _env_path(name):
    """A non-empty environment override, or None."""
    value = (os.environ.get(name) or "").strip()
    return value or None


def _config_dir():
    """The runtime-config directory: ``PYSTXM_CFG_DIR`` if set, else the first of
    the standard locations that exists, else None."""
    override = _env_path(CFG_DIR_ENV)
    if override is not None:
        return override
    for d in _CONFIG_DIRS:
        if os.path.isdir(d):
            return d
    return None


def favorites_file_path():
    """Where the dashboard's energy favorites are persisted."""
    override = _env_path(FAVORITES_ENV)
    if override is not None:
        return override
    d = _config_dir()
    if d is not None:
        return os.path.join(d, FAVORITES_BASENAME)
    return os.path.join(os.path.expanduser("~"), ".pystxmcontrol_energy_favorites.json")


def presets_dir():
    """Directory scanned for ``*.json`` energy presets.

    Returned whether or not it exists, so callers can tell the user where to put
    files; ``list_presets`` simply finds nothing when it is missing.
    """
    override = _env_path(PRESETS_DIR_ENV)
    if override is not None:
        return override
    d = _config_dir()
    if d is not None:
        return os.path.join(d, PRESETS_DIRNAME)
    return os.path.join(os.path.expanduser("~"), ".pystxmcontrol_energy_presets")


# ── format ───────────────────────────────────────────────────────────────────

def read_energy_regions_json(path):
    """Read an energy-preset file.

    Accepts ``{"energy_regions": {...}}`` or a raw ``{"EnergyRegionN": {...}}``
    dict.  Returns the regions dict, or None if the file is unreadable, is not
    JSON, or holds no regions.
    """
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    regions = data.get("energy_regions", data)
    return regions if isinstance(regions, dict) and regions else None


def normalize_regions(regions):
    """Return ``regions`` as an ordered list of plain dicts, or None if malformed.

    Each entry has ``start``, ``stop``, ``step``, ``n_energies`` and ``dwell``.
    Regions are ordered by their ``EnergyRegionN`` index (dict order otherwise), so
    the sequence matches what the GUI's region strip shows and what the server will
    concatenate.  ``step`` is derived when absent — files written by hand often
    omit it.
    """
    if not isinstance(regions, dict) or not regions:
        return None

    def _index(item):
        key = str(item[0])
        digits = "".join(c for c in key if c.isdigit())
        return int(digits) if digits else 0

    out = []
    try:
        for _key, r in sorted(regions.items(), key=_index):
            if not isinstance(r, dict):
                return None
            start = float(r["start"])
            stop = float(r["stop"])
            n = int(r.get("n_energies", 1)) or 1
            dwell = float(r.get("dwell", 1.0))
            step = r.get("step")
            # A single-energy region has no meaningful step; for the rest, derive
            # it from the endpoints the same way the server's linspace does.
            step = float(step) if step is not None else (
                (stop - start) / (n - 1) if n > 1 else 0.0)
            out.append({"start": start, "stop": stop, "step": step,
                        "n_energies": n, "dwell": dwell})
    except (KeyError, TypeError, ValueError):
        return None
    return out or None


def regions_to_dict(regions):
    """Inverse of ``normalize_regions``: a list of regions → ``EnergyRegion1..N``."""
    return {
        f"EnergyRegion{i + 1}": {
            "start": r["start"], "stop": r["stop"], "step": r.get("step", 0.0),
            "n_energies": r["n_energies"], "dwell": r["dwell"],
        }
        for i, r in enumerate(regions)
    }


def total_energies(regions):
    """Number of energy points a region list produces."""
    return sum(int(r.get("n_energies", 1) or 1) for r in (regions or []))


def summarize_regions(regions):
    """One-line human/agent-readable summary of a region list."""
    parts = []
    for r in regions or []:
        n = int(r.get("n_energies", 1) or 1)
        if n <= 1:
            parts.append(f"{r['start']:g} eV · {r['dwell']:g} ms")
        else:
            parts.append(f"{r['start']:g}–{r['stop']:g} eV · {n} pts · "
                         f"{r.get('step', 0.0):g} eV step · {r['dwell']:g} ms")
    return "; ".join(parts)


# ── discovery ────────────────────────────────────────────────────────────────

def _favorites_presets():
    """Named presets from the dashboard Favorites file."""
    path = favorites_file_path()
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    favs = data.get("favorites", []) if isinstance(data, dict) else []
    out = []
    for fav in favs:
        if not isinstance(fav, dict):
            continue
        regions = normalize_regions(fav.get("energy_regions"))
        if regions is None:
            continue
        out.append({"name": str(fav.get("alias", "Preset")),
                    "source": "favorites", "path": path, "regions": regions})
    return out


def _directory_presets():
    """Named presets from the presets directory (file stem = name)."""
    out = []
    for path in sorted(glob.glob(os.path.join(presets_dir(), "*.json"))):
        regions = normalize_regions(read_energy_regions_json(path))
        if regions is None:
            continue
        out.append({"name": os.path.splitext(os.path.basename(path))[0],
                    "source": "directory", "path": path, "regions": regions})
    return out


def list_presets():
    """All named presets, favorites first, then the presets directory.

    A directory preset whose name collides with a favorite is dropped — the pinned
    favorite is what the operator sees in the GUI, so it wins.
    """
    presets = _favorites_presets()
    seen = {p["name"].strip().lower() for p in presets}
    for p in _directory_presets():
        if p["name"].strip().lower() not in seen:
            presets.append(p)
    return presets


def describe_presets():
    """``list_presets`` rendered for an agent: name, source, points, summary."""
    return [
        {
            "name": p["name"],
            "source": p["source"],
            "n_regions": len(p["regions"]),
            "n_energies": total_energies(p["regions"]),
            "summary": summarize_regions(p["regions"]),
        }
        for p in list_presets()
    ]


class PresetNotFound(ValueError):
    """Raised when a preset name matches no saved definition (or is ambiguous)."""


def resolve_preset(name_or_path):
    """Resolve a preset by name or by path → ``(name, regions)``.

    Matching is by exact name (case-insensitive) first, then by unique substring,
    so an agent can say "C 1s" for "C 1s stack" without the operator having typed
    the full name.  A path to a ``.json`` file is loaded directly, matching the
    GUI's Open Energy Definition.

    Raises ``PresetNotFound`` with the available names when nothing matches, when a
    substring is ambiguous, or when the named file holds no usable regions.
    """
    if not name_or_path or not str(name_or_path).strip():
        raise PresetNotFound("No preset name given.")
    key = str(name_or_path).strip()

    # A path wins over a name: it is unambiguous and mirrors the GUI's file dialog.
    if key.lower().endswith(".json") or os.path.sep in key:
        path = os.path.expanduser(key)
        if not os.path.isfile(path):
            raise PresetNotFound(f"No such energy definition file: {path}")
        regions = normalize_regions(read_energy_regions_json(path))
        if regions is None:
            raise PresetNotFound(f"No readable energy regions in {path}")
        return os.path.splitext(os.path.basename(path))[0], regions

    presets = list_presets()
    if not presets:
        raise PresetNotFound(
            "No saved energy definitions found. Presets come from the dashboard "
            f"Favorites bar ({favorites_file_path()}) or JSON files in "
            f"{presets_dir()}.")

    exact = [p for p in presets if p["name"].strip().lower() == key.lower()]
    if len(exact) == 1:
        return exact[0]["name"], exact[0]["regions"]

    partial = [p for p in presets if key.lower() in p["name"].strip().lower()]
    if len(partial) == 1:
        return partial[0]["name"], partial[0]["regions"]

    names = ", ".join(repr(p["name"]) for p in presets)
    if len(partial) > 1:
        matched = ", ".join(repr(p["name"]) for p in partial)
        raise PresetNotFound(
            f"Energy preset {key!r} is ambiguous — it matches {matched}. "
            "Use the full name.")
    raise PresetNotFound(
        f"No energy preset named {key!r}. Available presets: {names}.")

"""Reading the instrument's identity and its most recent scan file, for the
acquisition dashboard's startup image and window title.

Split out of ``mainwindow``: these are plain filesystem/HDF5 readers
with no Qt and no window state.  Server-side scan-file access lives separately
in ``pystxmcontrol.controller.scan_files`` — that one serves the client/agent
over the wire, while these read the same files directly for the local GUI.
"""

import os
import sys
import json

import numpy as np


# ── last recorded scan (startup image) ───────────────────────────────────────
def runtime_main_config():
    """The server's runtime main.json (sys.prefix copy first, repo copy as a
    fallback) — the same file the server and _maybe_connect_controller read."""
    for path in (os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json"),
                 os.path.join(os.path.dirname(__file__), "..", "..", "..", "config",
                              "main.json")):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def instrument_identity():
    """``(instrument, beamline)`` for the window title and the header, from main.json.

    Two different fields, deliberately: ``server.name`` is this instrument ("COSMIC
    STXM") and is what mainwindow_mvc already titles its window with, while
    ``source.name`` is the beamline it sits on ("7.0.1.2"). The header shows both.

    An optional ``source.energy_range`` is appended to the beamline line when set, which
    is what the placeholder text used to spell out. Missing values degrade to a bare
    "STXM Control" rather than showing someone else's beamline.
    """
    cfg = runtime_main_config()
    instrument = ((cfg.get("server") or {}).get("name") or "").strip()
    source = cfg.get("source") or {}
    beamline = (source.get("name") or "").strip()
    energy_range = (source.get("energy_range") or "").strip()
    if beamline and energy_range:
        beamline = f"{beamline} \u00b7 {energy_range}"
    return instrument, beamline


def window_title():
    """Title for the acquisition window, naming the instrument when configured."""
    instrument, _ = instrument_identity()
    return f"STXM Control \u2014 {instrument}" if instrument else "STXM Control \u2014 Acquisition"


# How many day folders to look back through before giving up.  The loop below
# only ever visits folders that exist, so this is a guard against a data root
# full of empty day folders, not a real limit on how stale the last scan may be.
_MAX_DAY_LOOKBACK = 400


def _numeric_subdirs(parent):
    """Immediate subdirectories of *parent* with all-digit names, newest first.

    The data hierarchy is ``YYYY/MM/YYMMDD`` — zero-padded numbers at every
    level — so sorting the names descending IS date order, and no ``stat`` is
    needed to rank them.  Non-numeric siblings are skipped."""
    try:
        with os.scandir(parent) as it:
            names = [e.name for e in it if e.name.isdigit() and e.is_dir()]
    except OSError:
        return []
    return [os.path.join(parent, n) for n in sorted(names, reverse=True)]


def _day_dirs_newest_first(data_dir):
    """Day folders under ``data_dir/YYYY/MM/YYMMDD``, newest first (lazily)."""
    seen = 0
    for year in _numeric_subdirs(data_dir):
        for month in _numeric_subdirs(year):
            for day in _numeric_subdirs(month):
                yield day
                seen += 1
                if seen >= _MAX_DAY_LOOKBACK:
                    return


def _newest_stxm_in(folder):
    """Newest ``.stxm`` directly inside *folder* by mtime, or None.

    One ``scandir`` plus a ``stat`` per data file in that one folder — the cost
    is a session's worth of files, not the whole archive."""
    try:
        with os.scandir(folder) as it:
            entries = [e for e in it if e.name.endswith(".stxm")
                       and "ccdframes" not in e.name]
    except OSError:
        return None
    if not entries:
        return None
    try:
        return max(entries, key=lambda e: e.stat().st_mtime).path
    except OSError:
        return None


def find_last_scan_file():
    """Newest ``.stxm`` data file under the server's ``data_dir`` (walking the
    YYYY/MM/YYMMDD hierarchy, then a flat fallback), or None when none exists.

    Resolved by descending the date hierarchy newest-first and stopping at the
    first day folder that holds a scan, rather than by ranking every file in the
    archive: this runs at GUI startup, and on a data root of any size over NFS a
    ``stat`` per file costs minutes.  The trade is that a file whose mtime
    disagrees with the day folder it sits in (a late copy into an old session)
    no longer wins — "the newest session's newest scan" is what we want here."""
    data_dir = (runtime_main_config().get("server") or {}).get("data_dir")
    if not data_dir or not os.path.isdir(data_dir):
        return None
    for day_dir in _day_dirs_newest_first(data_dir):
        newest = _newest_stxm_in(day_dir)
        if newest is not None:
            return newest
    return _newest_stxm_in(data_dir)      # flat data_dir (no date hierarchy)


def load_last_scan(path):
    """Read the primary 2-D image frame and its physical extent from a ``.stxm``
    file's default NXdata group.  Returns ``(arr2d, extent)`` where ``extent`` is
    ``(xCenter, yCenter, xRange, yRange)`` in µm (full-field, N*step) or None if
    the geometry is unavailable; returns None entirely if no image can be read."""
    try:
        import h5py
        with h5py.File(path, "r") as f:
            base = None
            for b in ("entry0/default", "entry0/counter0"):
                if b + "/data" in f:
                    base = b
                    break
            if base is None:
                return None
            arr = np.asarray(f[base + "/data"][()], dtype=float)
            if arr.ndim == 3:                    # (n_energies, ny, nx) → frame 0
                arr = arr[0]
            if arr.ndim != 2 or not arr.size:
                return None
            extent = None
            try:
                sx = np.asarray(f[base + "/sample_x"][()], dtype=float).ravel()
                sy = np.asarray(f[base + "/sample_y"][()], dtype=float).ravel()

                def _span_center(v):
                    lo, hi = float(v.min()), float(v.max())
                    step = (hi - lo) / (len(v) - 1) if len(v) > 1 else 0.0
                    return (hi - lo) + step, (lo + hi) / 2.0   # full-field, centre

                xr, xc = _span_center(sx)
                yr, yc = _span_center(sy)
                if xr > 0 and yr > 0:
                    extent = (xc, yc, xr, yr)
            except Exception:
                pass
            return arr, extent
    except Exception:
        return None


def read_scan_file(path):
    """Read the metadata a loaded ``.stxm`` scan needs to seed the Acquisition view:
    scan type, primary 2-D frame, physical extent, energy list and dwell.

    Returns a dict with keys ``scan_type`` (str or None), ``frame`` (2-D array),
    ``extent`` (``(xCenter, yCenter, xRange, yRange)`` µm full-field, or None),
    ``xPoints`` / ``yPoints`` (ints, present only with ``extent``), ``energies``
    (1-D array or None) and ``dwell`` (float).  Returns None if no image frame can
    be read.  Same NXdata group + full-field-extent conventions as load_last_scan."""
    try:
        import h5py
        with h5py.File(path, "r") as f:
            base = None
            for b in ("entry0/default", "entry0/counter0"):
                if b + "/data" in f:
                    base = b
                    break
            if base is None:
                return None
            info = {}
            scan_type = None
            if base + "/stxm_scan_type" in f:
                raw = f[base + "/stxm_scan_type"][()]
                # Stored as a length-1 list (writeNX), possibly bytes.
                v = raw[0] if (hasattr(raw, "__len__")
                               and not isinstance(raw, (bytes, str))) else raw
                scan_type = v.decode() if isinstance(v, (bytes, np.bytes_)) else str(v)
            info["scan_type"] = scan_type

            arr = np.asarray(f[base + "/data"][()], dtype=float)
            if arr.ndim == 3:                    # (n_energies, ny, nx) → frame 0
                arr = arr[0]
            if arr.ndim != 2 or not arr.size:
                return None
            info["frame"] = arr

            info["extent"] = None
            try:
                sx = np.asarray(f[base + "/sample_x"][()], dtype=float).ravel()
                sy = np.asarray(f[base + "/sample_y"][()], dtype=float).ravel()

                def _span_center(v):
                    lo, hi = float(v.min()), float(v.max())
                    step = (hi - lo) / (len(v) - 1) if len(v) > 1 else 0.0
                    return (hi - lo) + step, (lo + hi) / 2.0   # full-field, centre

                xr, xc = _span_center(sx)
                yr, yc = _span_center(sy)
                if xr > 0 and yr > 0:
                    info["extent"] = (xc, yc, xr, yr)
                    info["xPoints"] = len(sx)
                    info["yPoints"] = len(sy)
            except Exception:
                pass

            try:
                info["energies"] = np.asarray(
                    f[base + "/energy"][()], dtype=float).ravel()
            except Exception:
                info["energies"] = None
            try:
                ct = np.asarray(f[base + "/count_time"][()], dtype=float).ravel()
                info["dwell"] = float(ct[0]) if len(ct) else 1.0
            except Exception:
                info["dwell"] = 1.0
            return info
    except Exception:
        return None

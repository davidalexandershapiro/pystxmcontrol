"""Reading the instrument's identity and its most recent scan file, for the
acquisition dashboard's startup image and window title.

Split out of ``mainwindow_dashboard``: these are plain filesystem/HDF5 readers
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
                 os.path.join(os.path.dirname(__file__), "..", "..", "config",
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


def find_last_scan_file():
    """Newest ``.stxm`` data file under the server's ``data_dir`` (walking the
    YYYY/MM/YYMMDD hierarchy, then a flat fallback), or None when none exists."""
    import glob
    data_dir = (runtime_main_config().get("server") or {}).get("data_dir")
    if not data_dir or not os.path.isdir(data_dir):
        return None
    files = [f for f in glob.glob(os.path.join(data_dir, "*", "*", "*", "*.stxm"))
             if "ccdframes" not in os.path.basename(f)]
    if not files:
        files = [f for f in glob.glob(os.path.join(data_dir, "*.stxm"))
                 if "ccdframes" not in os.path.basename(f)]
    if not files:
        return None
    try:
        return max(files, key=os.path.getmtime)
    except OSError:
        return None


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

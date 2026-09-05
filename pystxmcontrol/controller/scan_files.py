"""Server-side access to completed scan files.

An agent (or a GUI) may run somewhere with no filesystem access to the data
directory — a container, another host, an MCP server beside a chat client. The
control server always has access, so it reads the files and returns the arrays over
the existing command connection.

This is not an MCP concession: ``data_browser_widget`` enumerates scans with
``os.listdir``/``glob`` today, so a remotely-run GUI has the same limitation.

Payloads are pickled numpy arrays over the command socket. A full stack is expected
to be fine on the high-bandwidth links these clients use, so *frames=None* means the
whole dataset; pass an int for the last N energy frames when that is all you need
(the two-energy element map needs two, not fifty).
"""

import os
import time

# Scan files carry this extension; the browser's day-directory layout is followed.
_SCAN_SUFFIX = ".stxm"

# dataHandler.getScanName saves to <data_dir>/<yyyy>/<mm>/<yymmdd>/, so the day directory
# is three levels down.  Bounded rather than unlimited so a data_dir that also holds
# analysis output or an archive is not walked end to end.
_MAX_DEPTH = 3

# A ptychography scan writes its CCD frames as <scan name>_ccdframes_<e>_<r>.stxm inside a
# directory beside the scan.  They are frames of a scan, not scans, and listing them would
# bury the scans themselves.
_FRAME_MARKER = "_ccdframes_"


def _iter_scan_files(data_dir: str):
    """Yield (path, mtime) for every scan file under *data_dir*, newest first."""
    found = []
    for root in _scan_dirs(data_dir):
        for name in _safe_listdir(root):
            if not name.endswith(_SCAN_SUFFIX) or _FRAME_MARKER in name:
                continue
            path = os.path.join(root, name)
            try:
                found.append((path, os.path.getmtime(path)))
            except OSError:
                continue
    found.sort(key=lambda item: item[1], reverse=True)
    return found


def _scan_dirs(data_dir: str):
    """*data_dir* and every directory beneath it, down to :data:`_MAX_DEPTH`."""
    level = [data_dir]
    for _ in range(_MAX_DEPTH + 1):
        if not level:
            return
        yield from level
        level = [os.path.join(parent, name)
                 for parent in level
                 for name in _safe_listdir(parent)
                 if not name.startswith(".") and os.path.isdir(os.path.join(parent, name))]


def _safe_listdir(path: str):
    try:
        return os.listdir(path)
    except OSError:
        return []


def list_scans(data_dir: str, limit: int = 20) -> list[dict]:
    """Recent scans under *data_dir*, newest first.

    Metadata only — no image arrays — so an agent can see what is available without
    moving any data. Reading each file's header is what makes energies and scan type
    available; a file that cannot be read is skipped rather than failing the listing,
    since one corrupt scan should not hide the rest.
    """
    from pystxm_core.io.stxm_reader import read_stxm_stack

    out = []
    for path, mtime in _iter_scan_files(data_dir)[:max(1, int(limit))]:
        record = {"scan_id": os.path.basename(path), "path": path, "timestamp": mtime}
        try:
            stack = read_stxm_stack(path)
            record.update({
                "scan_type": stack.metadata.get("scan_type", ""),
                "energies": [float(e) for e in stack.energies],
                "detectors": list(stack.metadata.get("detectors") or ["default"]),
                "shape": [int(n) for n in stack.shape],
            })
        except Exception as e:
            record.update({"scan_type": "", "energies": [], "detectors": [],
                           "unreadable": str(e)})
        out.append(record)
    return out


def read_scan(path: str, frames=None, detector: str = "default",
              region: int = 0) -> dict | None:
    """Read one scan file into the shape the agent tools expect.

    ``images`` maps detector -> a single (energy, y, x) array, which is exactly the
    ``interp_counts[daq][region]`` shape the analysis tools index, so a record built
    from this is interchangeable with one the GUI buffered from a live scan.

    *frames* selects along the energy axis: None for the whole dataset (the default),
    an int for the last N frames, or an explicit list of indices. ``energies`` is
    filtered to match, so index i of the array is always energies[i].

    *region* picks one scan region out of a multi-region file; the returned record holds
    that one, so a caller indexes it as region 0.
    """
    from pystxm_core.io.stxm_reader import read_stxm_stack

    if not os.path.isfile(path):
        return None
    stack = read_stxm_stack(path, region=int(region), detector=detector)
    # as_array is a METHOD on Stack, unlike the shape/nenergies properties beside it.
    array = stack.as_array()
    energies = [float(e) for e in stack.energies]

    indices = _frame_indices(frames, len(energies))
    if indices is not None:
        array = array[indices]
        energies = [energies[i] for i in indices]

    metadata = stack.metadata or {}
    return {
        "scan_id": os.path.basename(path),
        "path": path,
        "region": int(region),
        "scan_type": metadata.get("scan_type", ""),
        "energies": energies,
        "x_positions": [float(x) for x in (metadata.get("x_positions") or [])],
        "y_positions": [float(y) for y in (metadata.get("y_positions") or [])],
        "images": {detector: array},
        "n_frames_total": int(stack.nenergies),
        "timestamp": os.path.getmtime(path),
    }


def _frame_indices(frames, n_energies: int):
    """Energy-axis indices for *frames*, or None to keep every frame."""
    if frames is None:
        return None
    if isinstance(frames, int):
        if frames <= 0 or frames >= n_energies:
            return None                       # 0/negative or "more than there are"
        return list(range(n_energies - frames, n_energies))   # the last N
    indices = [int(i) for i in frames if 0 <= int(i) < n_energies]
    return indices or None

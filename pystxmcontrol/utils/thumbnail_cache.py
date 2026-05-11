"""
Lightweight SQLite thumbnail cache for .stxm data files.

Stores a small normalised uint8 preview image per file, keyed by absolute
path + file modification time, so stale entries are automatically bypassed.

No Qt dependency — safe to use from both the GUI and the controller/server.
"""

import os
import sqlite3
import zlib
from pathlib import Path

import numpy as np

THUMB_SIZE = 128

_DEFAULT_DB = Path.home() / ".cache" / "pystxmcontrol" / "thumbnails.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS thumbnails (
    path        TEXT    PRIMARY KEY,
    mtime       REAL    NOT NULL,
    scan_type   TEXT    NOT NULL DEFAULT '',
    start_time  TEXT    NOT NULL DEFAULT '',
    th          INTEGER NOT NULL DEFAULT 0,
    tw          INTEGER NOT NULL DEFAULT 0,
    arr_data    BLOB,
    x_range_um  REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_path ON thumbnails(path);
"""

_MIGRATE = "ALTER TABLE thumbnails ADD COLUMN x_range_um REAL NOT NULL DEFAULT 0"


# ─────────────────────────── array helpers ────────────────────────────────────

def _normalize(arr):
    """Normalise a 2-D array to uint8."""
    arr = arr.astype(np.float64)
    lo, hi = float(arr.min()), float(arr.max())
    if hi > lo:
        arr = (arr - lo) / (hi - lo) * 255.0
    else:
        arr = np.zeros_like(arr)
    return arr.astype(np.uint8)


def _downscale(arr, size=THUMB_SIZE):
    """Resample arr to exactly size×size using nearest-neighbour indexing."""
    h, w = arr.shape
    row_idx = np.round(np.linspace(0, h - 1, size)).astype(int)
    col_idx = np.round(np.linspace(0, w - 1, size)).astype(int)
    return arr[np.ix_(row_idx, col_idx)]


def make_thumbnail_array(raw):
    """
    Convert raw scan data to a normalised uint8 thumbnail array.

    *raw* may be 2-D (ny, nx) or 3-D (n_energies, ny, nx).
    Returns None if the data cannot be used.
    """
    if raw is None or raw.size == 0:
        return None
    if raw.ndim == 3:
        raw = raw[0]
    if raw.ndim != 2:
        return None
    return _downscale(_normalize(raw))


# ─────────────────────────── ThumbnailCache ───────────────────────────────────

class ThumbnailCache:
    """
    Thread-safe SQLite thumbnail cache.

    get(path) returns:
      - None                           — complete miss (not in DB or mtime stale)
      - (arr | None, scan_type, start_time) — cache hit (arr is None for scans
                                              without a 2-D image, e.g. line scans)

    put(path, raw, scan_type, start_time) accepts the raw (un-normalised) scan
    array and handles normalisation + compression internally.
    """

    def __init__(self, db_path=None):
        self.db_path = str(db_path or _DEFAULT_DB)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── internal ──────────────────────────────────────────────────────────────

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=10,
                              check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def _init_db(self):
        with self._connect() as con:
            con.executescript(_SCHEMA)
            # add x_range_um column to existing databases that predate it
            try:
                con.execute(_MIGRATE)
            except sqlite3.OperationalError:
                pass  # column already exists

    # ── public API ────────────────────────────────────────────────────────────

    def get(self, path):
        """
        Return a cache hit tuple (arr, scan_type, start_time) or None on miss.
        arr may itself be None for scans with no displayable 2-D image.
        """
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        try:
            with self._connect() as con:
                row = con.execute(
                    "SELECT mtime, scan_type, start_time, th, tw, arr_data, x_range_um "
                    "FROM thumbnails WHERE path = ?",
                    (path,),
                ).fetchone()
            if row is None:
                return None
            db_mtime, scan_type, start_time, th, tw, arr_data, x_range_um = row
            if abs(db_mtime - mtime) >= 1.0:
                return None                          # stale — treat as miss
            if th > 0 and tw > 0 and arr_data:
                raw = zlib.decompress(bytes(arr_data))
                arr = np.frombuffer(raw, dtype=np.uint8).reshape(th, tw).copy()
            else:
                arr = None                           # known non-image scan
            return arr, scan_type, start_time, float(x_range_um)
        except Exception:
            return None

    def put(self, path, raw, scan_type="", start_time="", x_range_um=0.0):
        """
        Store a thumbnail for *path*.  *raw* is the unprocessed 2-D or 3-D
        numpy array from the scan data (or None if unavailable).
        """
        try:
            mtime = os.path.getmtime(path)
            arr = make_thumbnail_array(raw)
            if arr is not None:
                th, tw = arr.shape
                blob = zlib.compress(arr.tobytes(), level=1)
            else:
                th, tw, blob = 0, 0, b""
            with self._connect() as con:
                con.execute(
                    "INSERT OR REPLACE INTO thumbnails "
                    "(path, mtime, scan_type, start_time, th, tw, arr_data, x_range_um) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (path, mtime, scan_type or "", start_time or "",
                     th, tw, blob, float(x_range_um)),
                )
        except Exception:
            pass

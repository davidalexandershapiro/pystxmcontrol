"""Rotation-orbit measurements: where each sample sat at each CoarseR angle.

The history the orbit model learns its instrument constant (GY) from, and the record of
each new sample's anchors and tracked positions.  A single SQLite file beside the
beamline-parameter database (``<data_dir>/pystxmcontrol_data/rotation_orbits.db``),
reached remotely through the server's ``orbit_db`` command by :class:`OrbitDatabaseClient`.

ZonePlateZ is stored as read, together with the zone-plate calibration (A0 - A1*E) at
the energy it was read at.  :meth:`OrbitDatabase.orbit_samples` hands it to the fit
relative to that calibration, so orbits measured at different edges are comparable.
Rows imported from the old CSV carry no energy and stay in raw motor units, which the
global fit tolerates because each sample has its own Z offset.

Anchors are deliberate measurements and are approved when written.  Tracked points —
positions the tilt-series tracker centred on — are written pending and only count
toward fits once the user approves them at the end of a run.
"""

import csv
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

POINT_KINDS = ("anchor", "tracked", "import")

# Point columns a caller may set (beyond sample_id), in table order.
POINT_FIELDS = ("angle", "coarse_y", "sample_x", "zone_plate_z", "energy",
                "zp_calibration", "zp_offset", "kind", "approved", "z_measured",
                "cc_confidence", "scan_file", "notes")


class OrbitDatabase:
    """Read/write interface to the rotation-orbit database."""

    def __init__(self, data_dir: str | None = None, db_path: str | None = None):
        if db_path is None:
            db_dir = os.path.join(data_dir or os.path.expanduser("~"), "pystxmcontrol_data")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "rotation_orbits.db")
        self.db_path = db_path
        self._create_tables()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _create_tables(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS samples (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    label       TEXT NOT NULL,
                    notes       TEXT,
                    created     TEXT,
                    created_by  TEXT
                );
                CREATE TABLE IF NOT EXISTS points (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id       INTEGER NOT NULL
                                    REFERENCES samples(id) ON DELETE CASCADE,
                    angle           REAL NOT NULL,   -- CoarseR, encoder degrees
                    coarse_y        REAL NOT NULL,   -- µm
                    sample_x        REAL NOT NULL,   -- µm
                    zone_plate_z    REAL NOT NULL,   -- µm, as read
                    energy          REAL,            -- eV at measurement
                    zp_calibration  REAL,            -- A0 - A1*E at that energy, µm
                    zp_offset       REAL,            -- ZonePlateZ motor offset then
                    kind            TEXT NOT NULL DEFAULT 'anchor',
                    approved        INTEGER NOT NULL DEFAULT 1,
                    z_measured      INTEGER NOT NULL DEFAULT 1,  -- 0: Z was predicted
                    cc_confidence   REAL,
                    scan_file       TEXT,
                    notes           TEXT,
                    created         TEXT
                );
                CREATE INDEX IF NOT EXISTS points_by_sample ON points(sample_id);
            """)

    # ------------------------------------------------------------------
    # samples
    # ------------------------------------------------------------------

    def create_sample(self, label: str, notes: str | None = None,
                      created_by: str = "staff") -> int:
        """Start a new sample's orbit; returns its id."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO samples (label, notes, created, created_by) VALUES (?, ?, ?, ?)",
                (label, notes, datetime.now().isoformat(), created_by))
            return int(cur.lastrowid)

    def get_sample(self, sample_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM samples WHERE id = ?", (sample_id,)).fetchone()
        return dict(row) if row else None

    def list_samples(self) -> list[dict]:
        """Every sample with its point counts (approved / pending) and angular span."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT s.*,
                       SUM(CASE WHEN p.approved = 1 THEN 1 ELSE 0 END) AS n_approved,
                       SUM(CASE WHEN p.approved = 0 THEN 1 ELSE 0 END) AS n_pending,
                       MIN(p.angle) AS angle_min, MAX(p.angle) AS angle_max
                FROM samples s LEFT JOIN points p ON p.sample_id = s.id
                GROUP BY s.id ORDER BY s.id
            """).fetchall()
        return [{**dict(r), "n_approved": r["n_approved"] or 0,
                 "n_pending": r["n_pending"] or 0} for r in rows]

    def delete_sample(self, sample_id: int) -> None:
        """Delete a sample and all its points."""
        with self._connect() as conn:
            conn.execute("DELETE FROM samples WHERE id = ?", (sample_id,))

    # ------------------------------------------------------------------
    # points
    # ------------------------------------------------------------------

    def add_point(self, sample_id: int, angle: float, coarse_y: float, sample_x: float,
                  zone_plate_z: float, kind: str = "anchor", approved: bool | None = None,
                  **fields) -> int:
        """Record one position; returns its id.

        *approved* defaults to True for anchors and imports and False for tracked
        points, which wait for :meth:`approve_points`.
        """
        if kind not in POINT_KINDS:
            raise ValueError(f"kind must be one of {POINT_KINDS}, got {kind!r}")
        unknown = set(fields) - set(POINT_FIELDS)
        if unknown:
            raise ValueError(f"unknown point fields: {sorted(unknown)}")
        if approved is None:
            approved = kind != "tracked"
        row = {"angle": angle, "coarse_y": coarse_y, "sample_x": sample_x,
               "zone_plate_z": zone_plate_z, "kind": kind, "approved": int(bool(approved)),
               **{k: (int(bool(v)) if k == "z_measured" else v) for k, v in fields.items()}}
        cols = ["sample_id", *row, "created"]
        vals = [sample_id, *row.values(), datetime.now().isoformat()]
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO points ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                vals)
            return int(cur.lastrowid)

    def get_points(self, sample_id: int | None = None, approved_only: bool = False,
                   kinds: list[str] | None = None) -> list[dict]:
        """Points ordered by sample then angle, optionally filtered."""
        where, args = [], []
        if sample_id is not None:
            where.append("sample_id = ?")
            args.append(sample_id)
        if approved_only:
            where.append("approved = 1")
        if kinds:
            where.append(f"kind IN ({', '.join('?' * len(kinds))})")
            args.extend(kinds)
        sql = "SELECT * FROM points"
        if where:
            sql += " WHERE " + " AND ".join(where)
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY sample_id, angle", args).fetchall()
        return [dict(r) for r in rows]

    def approve_points(self, sample_id: int, point_ids: list[int] | None = None) -> int:
        """Approve a sample's pending points (all of them, or just *point_ids*).

        Returns how many changed.
        """
        sql, args = "UPDATE points SET approved = 1 WHERE sample_id = ? AND approved = 0", \
            [sample_id]
        if point_ids is not None:
            if not point_ids:
                return 0
            sql += f" AND id IN ({', '.join('?' * len(point_ids))})"
            args.extend(point_ids)
        with self._connect() as conn:
            return conn.execute(sql, args).rowcount

    def discard_pending(self, sample_id: int) -> int:
        """Delete a sample's unapproved points; returns how many."""
        with self._connect() as conn:
            return conn.execute("DELETE FROM points WHERE sample_id = ? AND approved = 0",
                                (sample_id,)).rowcount

    def delete_point(self, point_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM points WHERE id = ?", (point_id,))

    # ------------------------------------------------------------------
    # what the orbit model consumes
    # ------------------------------------------------------------------

    def orbit_samples(self, approved_only: bool = True, sample_ids: list[int] | None = None,
                      exclude: list[int] | None = None, min_points: int = 3) -> dict:
        """``{sample_id: {angle, coarse_y, sample_x, zone_plate_z}}`` lists for the fit.

        zone_plate_z is relative to the zone-plate calibration where one was recorded.
        Samples with fewer than *min_points* points are left out: they cannot constrain
        an orbit.
        """
        out: dict = {}
        for p in self.get_points(approved_only=approved_only):
            sid = p["sample_id"]
            if (sample_ids is not None and sid not in sample_ids) or \
                    (exclude and sid in exclude):
                continue
            d = out.setdefault(sid, {"angle": [], "coarse_y": [], "sample_x": [],
                                     "zone_plate_z": []})
            d["angle"].append(p["angle"])
            d["coarse_y"].append(p["coarse_y"])
            d["sample_x"].append(p["sample_x"])
            d["zone_plate_z"].append(relative_z(p))
        return {k: v for k, v in out.items() if len(v["angle"]) >= min_points}

    # ------------------------------------------------------------------
    # migration
    # ------------------------------------------------------------------

    def import_csv(self, path: str, created_by: str = "import") -> list[int]:
        """Import the beamline's ``tomo_orbit_motors.csv``; returns the new sample ids.

        Columns: sample_id, sample_label, coarse_r_deg, coarse_y, sample_x, zone_plate_z
        (coarse_z is ignored).  Each CSV sample becomes one database sample; the rows
        carry no energy, so their Z stays raw.
        """
        groups: dict = {}
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            needed = {"sample_id", "coarse_r_deg", "coarse_y", "sample_x", "zone_plate_z"}
            missing = needed - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{os.path.basename(path)} is missing columns {sorted(missing)}")
            for row in reader:
                groups.setdefault(row["sample_id"], []).append(row)
        new_ids = []
        for csv_id, rows in groups.items():
            label = rows[0].get("sample_label") or f"sample {csv_id}"
            sid = self.create_sample(label, notes=f"imported from {os.path.basename(path)} "
                                                  f"(sample_id {csv_id})",
                                     created_by=created_by)
            for r in rows:
                self.add_point(sid, float(r["coarse_r_deg"]), float(r["coarse_y"]),
                               float(r["sample_x"]), float(r["zone_plate_z"]), kind="import")
            new_ids.append(sid)
        return new_ids


def relative_z(point: dict) -> float:
    """A point's ZonePlateZ relative to the calibration at its energy (raw if none)."""
    cal = point.get("zp_calibration")
    return point["zone_plate_z"] - cal if cal is not None else point["zone_plate_z"]


# Methods the server's orbit_db command may call.  Everything else stays server-side.
REMOTE_ACTIONS = ("create_sample", "get_sample", "list_samples", "delete_sample",
                  "add_point", "get_points", "approve_points", "discard_pending",
                  "delete_point", "orbit_samples")


def dispatch(db: OrbitDatabase, action: str, args: dict | None):
    """Run one remote *action* against *db* (the server side of ``orbit_db``)."""
    if action not in REMOTE_ACTIONS:
        raise ValueError(f"unknown orbit_db action {action!r}")
    result = getattr(db, action)(**(args or {}))
    if action == "orbit_samples":
        # JSON-safe keys for anything downstream that serialises the reply.
        return {int(k): v for k, v in result.items()}
    return result


class OrbitDatabaseClient:
    """Network proxy with :class:`OrbitDatabase`'s remote interface.

    Routes through the ZMQ ``orbit_db`` command so the agent, MCP and a GUI on another
    host never need the server's filesystem.
    """

    def __init__(self, client):
        self._client = client

    def _request(self, action: str, **args):
        response = self._client.send_message({"command": "orbit_db", "action": action,
                                              "args": args})
        if not response or not response.get("status"):
            err = (response or {}).get("error", "no response")
            raise RuntimeError(f"orbit_db {action} failed: {err}")
        return response.get("data")

    def __getattr__(self, name):
        if name in REMOTE_ACTIONS:
            return lambda **kwargs: self._request(name, **kwargs)
        raise AttributeError(name)


def main(argv=None):
    """``python -m pystxmcontrol.controller.orbit_database import CSV [--data-dir DIR]``"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Rotation-orbit database maintenance")
    sub = parser.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="import tomo_orbit_motors.csv")
    imp.add_argument("csv")
    lst = sub.add_parser("list", help="list samples")
    for p in (imp, lst):
        p.add_argument("--data-dir", help="defaults to main.json server.data_dir")
        p.add_argument("--db", help="explicit database path (overrides --data-dir)")
    a = parser.parse_args(argv)

    data_dir = a.data_dir
    if data_dir is None and a.db is None:
        import sys
        cfg = os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json")
        with open(cfg) as f:
            data_dir = json.load(f)["server"]["data_dir"]
    db = OrbitDatabase(data_dir=data_dir, db_path=a.db)
    if a.cmd == "import":
        ids = db.import_csv(a.csv)
        print(f"imported {len(ids)} samples into {db.db_path}: ids {ids}")
    for s in db.list_samples():
        print(f"{s['id']:>4}  {s['label']:<24} approved={s['n_approved']:<3} "
              f"pending={s['n_pending']:<3} angles {s['angle_min']}..{s['angle_max']}")


if __name__ == "__main__":
    main()

"""
Beamline parameter lookup table.

Stores measured/calibrated beamline settings keyed by desired photon energy.
Saved as a single persistent SQLite file alongside the operation-logger data.
"""

import sqlite3
import os
from datetime import datetime


# Human-readable column metadata: (db_column, display_label, dtype)
COLUMNS = [
    ("desired_energy",       "Desired Energy (eV)",             float),
    ("commanded_energy",     "Commanded Energy (eV)",           float),
    ("harmonic",             "Harmonic",                        int),
    ("grating",              "Grating",                         str),
    ("exit_slit_h_pos",      "Exit Slit Horizontal Position",   float),
    ("exit_slit_size",       "Exit Slit Size",                  float),
    ("m121_vertical_angle",  "M121 Vertical Angle",             float),
    ("feedback_offset",      "Feedback Offset",                 float),
    ("m101_angle",           "M101 Angle",                      float),
    ("epu_offset",           "EPU Offset",                      float),
]

# Column names only (for convenience)
COLUMN_NAMES = [c[0] for c in COLUMNS]


class BeamlineDatabase:
    """Read/write interface to the beamline parameter lookup table.

    Uses a single ``beamline_params.db`` file stored in the same directory
    as the operation-logger databases (``<data_dir>/pystxmcontrol_data/``).
    """

    def __init__(self, data_dir: str | None = None):
        if data_dir is None:
            data_dir = os.path.expanduser("~")
        db_dir = os.path.join(data_dir, "pystxmcontrol_data")
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, "beamline_params.db")
        self._create_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS beamline_settings (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                desired_energy      REAL    NOT NULL UNIQUE,
                commanded_energy    REAL,
                harmonic            INTEGER,
                grating             TEXT,
                exit_slit_h_pos     REAL,
                exit_slit_size      REAL,
                m121_vertical_angle REAL,
                feedback_offset     REAL,
                m101_angle          REAL,
                epu_offset          REAL,
                notes               TEXT,
                last_modified       TEXT,
                modified_by         TEXT
            )
        """)
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_all_entries(self) -> list[dict]:
        """Return all entries sorted by desired_energy ascending."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM beamline_settings ORDER BY desired_energy ASC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_entry(self, desired_energy: float) -> dict | None:
        """Return the entry for *desired_energy*, or None if not found."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM beamline_settings WHERE desired_energy = ?",
            (desired_energy,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_nearest_entry(self, energy: float) -> dict | None:
        """Return the entry whose desired_energy is closest to *energy*."""
        entries = self.get_all_entries()
        if not entries:
            return None
        return min(entries, key=lambda e: abs(e["desired_energy"] - energy))

    def get_desired_energies(self) -> list[float]:
        """Return sorted list of all stored desired-energy values."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT desired_energy FROM beamline_settings ORDER BY desired_energy ASC"
        ).fetchall()
        conn.close()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_entry(self, desired_energy: float, modified_by: str = "staff",
                     **kwargs) -> None:
        """Insert or update the entry for *desired_energy*.

        Any subset of the parameter columns may be supplied as keyword args.
        ``commanded_energy`` defaults to ``desired_energy`` on insert if omitted.
        """
        existing = self.get_entry(desired_energy)

        if existing is None:
            # New entry — commanded_energy defaults to desired_energy
            if "commanded_energy" not in kwargs:
                kwargs["commanded_energy"] = desired_energy
            cols = ["desired_energy"] + list(kwargs.keys()) + ["last_modified", "modified_by"]
            vals = [desired_energy] + list(kwargs.values()) + [
                datetime.now().isoformat(), modified_by
            ]
            placeholders = ", ".join("?" * len(cols))
            col_str = ", ".join(cols)
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                f"INSERT INTO beamline_settings ({col_str}) VALUES ({placeholders})",
                vals
            )
            conn.commit()
            conn.close()
        else:
            # Update only supplied fields
            if not kwargs:
                return
            set_parts = [f"{k} = ?" for k in kwargs]
            set_parts += ["last_modified = ?", "modified_by = ?"]
            vals = list(kwargs.values()) + [datetime.now().isoformat(), modified_by,
                                             desired_energy]
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                f"UPDATE beamline_settings SET {', '.join(set_parts)} "
                f"WHERE desired_energy = ?",
                vals
            )
            conn.commit()
            conn.close()

    def delete_entry(self, desired_energy: float) -> None:
        """Delete the entry for *desired_energy*."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "DELETE FROM beamline_settings WHERE desired_energy = ?",
            (desired_energy,)
        )
        conn.commit()
        conn.close()


class BeamlineDatabaseClient:
    """Network proxy with the same read/write interface as ``BeamlineDatabase``.

    Routes every operation through the stxm client/server ZMQ connection (the
    ``beamline_db`` command) so a GUI running on a different machine than the server
    does not need filesystem access to the server's ``beamline_params.db``.  It is a
    drop-in for the subset of ``BeamlineDatabase`` methods the GUI uses, so callers
    (e.g. ``BeamlinePanelWindow``) need no changes.
    """

    def __init__(self, client):
        self._client = client

    def _request(self, action: str, **kwargs):
        message = {"command": "beamline_db", "action": action}
        message.update(kwargs)
        response = self._client.send_message(message)
        if not response or not response.get("status"):
            err = (response or {}).get("error", "no response")
            raise RuntimeError(f"beamline_db {action} failed: {err}")
        return response.get("data")

    def get_desired_energies(self) -> list[float]:
        return self._request("list_energies") or []

    def get_entry(self, desired_energy: float) -> dict | None:
        return self._request("get_entry", energy=desired_energy)

    def upsert_entry(self, desired_energy: float, modified_by: str = "staff",
                     **kwargs) -> None:
        self._request("upsert_entry", energy=desired_energy,
                      modified_by=modified_by, fields=kwargs)

    def delete_entry(self, desired_energy: float) -> None:
        self._request("delete_entry", energy=desired_energy)

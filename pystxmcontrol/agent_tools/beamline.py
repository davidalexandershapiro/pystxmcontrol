"""The beamline-parameter database.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import json
import logging


from pystxmcontrol.controller.tool_registry import tool

from .common import _BEAMLINE_DB_MOTOR_MAP, _round_to_eV

log = logging.getLogger(__name__)


class BeamlineTools:
    """The beamline-parameter database."""

    @tool()
    def save_beamline_entry(self, desired_energy: float,
                            populate_from_current: bool = False,
                            commanded_energy: float | None = None,
                            harmonic: int | None = None,
                            grating: str | None = None,
                            exit_slit_h_pos: float | None = None,
                            exit_slit_size: float | None = None,
                            m121_vertical_angle: float | None = None,
                            feedback_offset: float | None = None,
                            m101_angle: float | None = None,
                            epu_offset: float | None = None,
                            notes: str | None = None,
                            modified_by: str = "task_agent") -> str:
        """Insert or update a beamline-parameter database entry for *desired_energy*.

        Writes to the server-side beamline DB over the network. Only the fields you pass
        are written; an existing entry keeps its other fields. When populate_from_current
        is True, the commanded_energy / harmonic / feedback_offset / epu_offset fields are
        filled from the current motor positions for any you did not pass explicitly — ideal
        right after tuning, when the live positions already hold the tuned result.


        The desired_energy key is rounded to the nearest whole eV (entries do not need
        sub-eV precision; commanded_energy keeps its precise value). After a tuning run,
        ASK the user before saving.
        Args:
            desired_energy: Photon energy in eV (the entry key).
            populate_from_current: Fill mappable fields from current motor positions for
                any not passed explicitly.
            modified_by: Who made the change (default 'task_agent').
        """
        from pystxmcontrol.controller.beamline_database import (
            BeamlineDatabaseClient, COLUMNS,
        )

        try:
            # Entries are keyed to whole-eV granularity; round the key (the
            # commanded_energy column keeps the precise live value).
            desired_energy = _round_to_eV(desired_energy)
        except (TypeError, ValueError):
            return f"Invalid desired_energy {desired_energy!r} — must be a number."

        fields = {
            "commanded_energy":    commanded_energy,
            "harmonic":            harmonic,
            "grating":             grating,
            "exit_slit_h_pos":     exit_slit_h_pos,
            "exit_slit_size":      exit_slit_size,
            "m121_vertical_angle": m121_vertical_angle,
            "feedback_offset":     feedback_offset,
            "m101_angle":          m101_angle,
            "epu_offset":          epu_offset,
        }
        if notes is not None:
            fields["notes"] = notes

        if populate_from_current:
            positions = self._refresh_positions()
            for col, axis in _BEAMLINE_DB_MOTOR_MAP.items():
                if fields.get(col) is None and positions.get(axis) is not None:
                    fields[col] = positions[axis]

        # Drop unset fields and coerce to the column dtype where known.
        dtype_map = {c: d for c, _label, d in COLUMNS}
        clean: dict = {}
        for key, val in fields.items():
            if val is None:
                continue
            dt = dtype_map.get(key)
            try:
                clean[key] = int(float(val)) if dt is int else (dt(val) if dt else val)
            except (TypeError, ValueError):
                clean[key] = val

        if not clean:
            return ("Nothing to save — pass at least one field, or "
                    "populate_from_current=True to capture the current beamline state.")

        try:
            db = BeamlineDatabaseClient(self._client)
            existed = db.get_entry(desired_energy) is not None
            db.upsert_entry(desired_energy, modified_by=modified_by, **clean)
        except Exception as e:
            return f"Failed to save beamline entry for {desired_energy} eV: {e}"

        return json.dumps({
            "status": "updated" if existed else "added",
            "desired_energy_eV": desired_energy,
            "fields_written": clean,
            "modified_by": modified_by,
        }, indent=2)

    @tool(mutates_hardware=True)
    def set_beamline_from_database(self, desired_energy: float) -> str:
        """Set the beamline from a stored database entry for *desired_energy*.

        Looks up the (exact) entry, applies its calibration knobs — harmonic, EPU offset,
        feedback offset — to the corresponding motors, then moves Energy to the entry's
        desired_energy (the desired→commanded mapping is handled at a lower level, so the
        high-level target is always the desired energy). Columns without a clean motor
        mapping (grating, exit slits, m121/m101 angles) are reported, not moved.
        Moving Energy can be a large move — confirm with the user first per the safety rules.


        The energy you pass is rounded to the nearest whole eV for the lookup (a live
        707.8 eV finds the 708 eV entry). If no entry exists this returns 'not_found'
        with the closest stored energy in 'nearest_energy_eV' — ASK the user whether to
        apply that nearest entry before calling again with it.
        Args:
            desired_energy: Photon energy in eV of the entry to apply.
        """
        from pystxmcontrol.controller.beamline_database import (
            BeamlineDatabaseClient, COLUMN_NAMES,
        )

        try:
            requested_energy = float(desired_energy)
        except (TypeError, ValueError):
            return f"Invalid desired_energy {desired_energy!r} — must be a number."
        # Entries are keyed to whole-eV granularity, so look up the rounded value
        # (e.g. a live energy of 707.8 eV finds the 708 eV entry).
        rounded_energy = _round_to_eV(requested_energy)

        db = BeamlineDatabaseClient(self._client)
        try:
            entry = db.get_entry(rounded_energy)
            if entry is None and rounded_energy != requested_energy:
                # Fall back to the exact requested value so a deliberately-passed
                # legacy/non-integer energy (e.g. a confirmed nearby entry) still matches.
                entry = db.get_entry(requested_energy)
        except Exception as e:
            return f"Failed to read beamline database: {e}"

        if entry is None:
            try:
                energies = db.get_desired_energies()
            except Exception:
                energies = []
            nearest = (min(energies, key=lambda e: abs(e - rounded_energy))
                       if energies else None)
            if nearest is not None:
                msg = (f"No beamline entry at {rounded_energy} eV. The closest stored entry is "
                       f"{nearest} eV. Ask the user whether to apply that entry; only if they "
                       f"agree, call set_beamline_from_database({nearest}). Do not apply it "
                       f"without confirmation.")
            else:
                msg = ("The beamline database is empty — create an entry with "
                       "save_beamline_entry().")
            return json.dumps({
                "status": "not_found",
                "requested_energy_eV": requested_energy,
                "rounded_energy_eV": rounded_energy,
                "available_energies": energies,
                "nearest_energy_eV": nearest,
                "message": msg,
            }, indent=2)

        # From here on use the matched entry's own desired_energy as the target.
        desired_energy = entry["desired_energy"]

        # Apply the calibration knobs first (so the harmonic/offset are in place before the
        # Energy move drives the EPU gap), then move Energy to the desired energy.
        knob_map = [("harmonic", "HARMONIC"),
                    ("epu_offset", "EPUOFFSET"),
                    ("feedback_offset", "FBKOFFSET")]
        moves, skipped, errors = [], [], []
        for col, axis in knob_map:
            val = entry.get(col)
            if val is None:
                skipped.append(col)
                continue
            res = self.move_motor(axis, float(val))
            if res.startswith("Successfully"):
                moves.append({"motor": axis, "value": float(val)})
            else:
                errors.append(f"{axis}: {res}")

        e_res = self.move_motor("Energy", desired_energy)
        if e_res.startswith("Successfully"):
            moves.append({"motor": "Energy", "value": desired_energy})
        else:
            errors.append(f"Energy: {e_res}")

        # Columns that have a stored value but no motor mapping — the operator sets these by hand.
        _handled = {"desired_energy", "commanded_energy", "harmonic", "epu_offset",
                    "feedback_offset"}
        not_applied = {
            col: entry[col]
            for col in COLUMN_NAMES
            if col not in _handled and entry.get(col) is not None
        }

        result = {
            "status": "applied" if not errors else "partial",
            "desired_energy_eV": desired_energy,
            "moves": moves,
            "skipped_empty_fields": skipped,
        }
        if not_applied:
            result["set_manually"] = not_applied  # no motor mapping — for operator awareness
        if errors:
            result["errors"] = errors
        return json.dumps(result, indent=2)

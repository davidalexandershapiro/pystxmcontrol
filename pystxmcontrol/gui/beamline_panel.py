"""Beamline Panel — staff view/edit widget for the beamline parameter database."""

from PySide6 import QtWidgets, QtCore

from pystxmcontrol.controller.beamline_database import COLUMNS


class BeamlinePanelWindow(QtWidgets.QDialog):
    """Modal dialog for viewing and (staff-only) editing beamline parameters.

    Parameters
    ----------
    db : BeamlineDatabase | BeamlineDatabaseClient
        Object exposing get_desired_energies / get_entry / upsert_entry / delete_entry.
        In the GUI this is a BeamlineDatabaseClient that talks to the server over the
        network; the local BeamlineDatabase has the same interface.
    is_staff : bool
        When True, edit fields and write buttons are enabled.
    parent : QWidget, optional
    """

    def __init__(self, db, is_staff: bool = False,
                 parent=None):
        super().__init__(parent)
        self._db = db
        self._is_staff = is_staff
        self._current_energy: float | None = None

        self.setWindowTitle("Beamline Panel")
        self.setMinimumWidth(480)
        self._build_ui()
        self._populate_combo()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(8)

        # ── Energy selector row ────────────────────────────────────────
        sel_row = QtWidgets.QHBoxLayout()
        sel_row.addWidget(QtWidgets.QLabel("Desired Energy:"))
        self._energy_combo = QtWidgets.QComboBox()
        self._energy_combo.setMinimumWidth(120)
        self._energy_combo.currentIndexChanged.connect(self._on_energy_selected)
        sel_row.addWidget(self._energy_combo)
        sel_row.addStretch()
        if self._is_staff:
            self._add_btn = QtWidgets.QPushButton("Add New Entry")
            self._add_btn.clicked.connect(self._on_add_entry)
            sel_row.addWidget(self._add_btn)
        root.addLayout(sel_row)

        root.addWidget(_hline())

        # ── Parameter grid ─────────────────────────────────────────────
        grid = QtWidgets.QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        # Header
        grid.addWidget(_bold_label("Parameter"), 0, 0)
        grid.addWidget(_bold_label("Current Value"), 0, 1)
        if self._is_staff:
            grid.addWidget(_bold_label("New Value"), 0, 2)

        self._current_labels: dict[str, QtWidgets.QLabel] = {}
        self._edit_fields:    dict[str, QtWidgets.QLineEdit] = {}

        for row_idx, (col, label, _dtype) in enumerate(COLUMNS, start=1):
            grid.addWidget(QtWidgets.QLabel(label), row_idx, 0)

            current_lbl = QtWidgets.QLabel("—")
            current_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            grid.addWidget(current_lbl, row_idx, 1)
            self._current_labels[col] = current_lbl

            if self._is_staff:
                edit = QtWidgets.QLineEdit()
                edit.setPlaceholderText("unchanged")
                grid.addWidget(edit, row_idx, 2)
                self._edit_fields[col] = edit

        root.addLayout(grid)
        root.addWidget(_hline())

        # ── Notes ──────────────────────────────────────────────────────
        notes_row = QtWidgets.QHBoxLayout()
        notes_row.addWidget(QtWidgets.QLabel("Notes:"))
        self._notes_label = QtWidgets.QLabel("—")
        self._notes_label.setWordWrap(True)
        notes_row.addWidget(self._notes_label, 1)
        if self._is_staff:
            self._notes_edit = QtWidgets.QLineEdit()
            self._notes_edit.setPlaceholderText("optional notes")
            notes_row.addWidget(self._notes_edit, 1)
        root.addLayout(notes_row)

        # Last-modified info
        self._modified_label = QtWidgets.QLabel("")
        self._modified_label.setStyleSheet("color: grey; font-size: 10px;")
        root.addWidget(self._modified_label)

        root.addWidget(_hline())

        # ── Action buttons ─────────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        if self._is_staff:
            self._save_btn = QtWidgets.QPushButton("Save Changes")
            self._save_btn.setEnabled(False)
            self._save_btn.clicked.connect(self._on_save)
            btn_row.addWidget(self._save_btn)

            self._delete_btn = QtWidgets.QPushButton("Delete Entry")
            self._delete_btn.setEnabled(False)
            self._delete_btn.setStyleSheet("color: red;")
            self._delete_btn.clicked.connect(self._on_delete)
            btn_row.addWidget(self._delete_btn)

        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Populate / refresh
    # ------------------------------------------------------------------

    def _populate_combo(self):
        self._energy_combo.blockSignals(True)
        self._energy_combo.clear()
        self._energy_combo.addItem("— select —", userData=None)
        for energy in self._db.get_desired_energies():
            self._energy_combo.addItem(f"{energy:.2f} eV", userData=energy)
        self._energy_combo.blockSignals(False)

    def _on_energy_selected(self, idx: int):
        energy = self._energy_combo.itemData(idx)
        if energy is None:
            self._clear_fields()
            self._current_energy = None
            return
        self._current_energy = energy
        entry = self._db.get_entry(energy)
        if entry is None:
            self._clear_fields()
            return
        for col, _label, _dtype in COLUMNS:
            val = entry.get(col)
            self._current_labels[col].setText("—" if val is None else str(val))
            if self._is_staff:
                self._edit_fields[col].clear()

        self._notes_label.setText(entry.get("notes") or "—")
        if self._is_staff:
            self._notes_edit.setText(entry.get("notes") or "")

        ts = entry.get("last_modified", "")
        by = entry.get("modified_by", "")
        if ts:
            self._modified_label.setText(f"Last modified: {ts[:19]}  by {by}")
        else:
            self._modified_label.setText("")

        if self._is_staff:
            self._save_btn.setEnabled(True)
            self._delete_btn.setEnabled(True)

    def _clear_fields(self):
        for lbl in self._current_labels.values():
            lbl.setText("—")
        if self._is_staff:
            for edit in self._edit_fields.values():
                edit.clear()
            self._notes_edit.clear()
            self._save_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
        self._notes_label.setText("—")
        self._modified_label.setText("")

    # ------------------------------------------------------------------
    # Staff actions
    # ------------------------------------------------------------------

    def _on_add_entry(self):
        energy_str, ok = QtWidgets.QInputDialog.getText(
            self, "Add Entry", "Desired Energy (eV):"
        )
        if not ok or not energy_str.strip():
            return
        try:
            energy = float(energy_str.strip())
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Input",
                                          "Please enter a numeric energy value.")
            return
        if self._db.get_entry(energy) is not None:
            QtWidgets.QMessageBox.warning(
                self, "Duplicate", f"An entry for {energy} eV already exists."
            )
            return
        self._db.upsert_entry(energy)
        self._populate_combo()
        # Select the new entry
        for i in range(self._energy_combo.count()):
            if self._energy_combo.itemData(i) == energy:
                self._energy_combo.setCurrentIndex(i)
                break

    def _on_save(self):
        if self._current_energy is None:
            return
        kwargs = {}
        for col, _label, dtype in COLUMNS:
            text = self._edit_fields[col].text().strip()
            if not text:
                continue
            try:
                kwargs[col] = dtype(text)
            except ValueError:
                QtWidgets.QMessageBox.warning(
                    self, "Invalid Value",
                    f"Could not parse '{text}' for {col}."
                )
                return

        notes = self._notes_edit.text().strip()
        if notes:
            kwargs["notes"] = notes

        if not kwargs:
            QtWidgets.QMessageBox.information(self, "No Changes",
                                              "No new values were entered.")
            return

        self._db.upsert_entry(self._current_energy, **kwargs)
        # Refresh display
        self._on_energy_selected(self._energy_combo.currentIndex())
        QtWidgets.QMessageBox.information(
            self, "Saved", f"Entry for {self._current_energy:.2f} eV updated."
        )

    def _on_delete(self):
        if self._current_energy is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Entry",
            f"Delete the entry for {self._current_energy:.2f} eV?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._db.delete_entry(self._current_energy)
        self._populate_combo()
        self._clear_fields()
        self._current_energy = None
        self._energy_combo.setCurrentIndex(0)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _bold_label(text: str) -> QtWidgets.QLabel:
    lbl = QtWidgets.QLabel(f"<b>{text}</b>")
    return lbl


def _hline() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return line

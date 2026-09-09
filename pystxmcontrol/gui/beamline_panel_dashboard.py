"""
Beamline Panel (dashboard style) — a floating staff view/edit window for the
beamline parameter database, styled to match ``mainwindow_dashboard``.

Ports the feature set of ``beamline_panel.BeamlinePanelWindow`` (energy selector,
current/new-value parameter grid, notes, add/save/delete) onto the dashboard's
bespoke dark theme (``dashboard_theme``): card frames, mono/sans type tokens,
and the segmented-well aesthetic.

The database object (``db``) is a ``BeamlineDatabase`` or ``BeamlineDatabaseClient``
exposing ``get_desired_energies`` / ``get_entry`` / ``upsert_entry`` /
``delete_entry``.  Edit fields and write buttons appear only when ``is_staff``.
"""

from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QComboBox, QLineEdit,
    QVBoxLayout, QHBoxLayout, QGridLayout, QInputDialog, QMessageBox,
)
from PySide6.QtCore import Qt

from pystxmcontrol.controller.beamline_database import COLUMNS
from pystxmcontrol.gui.dashboard_theme import build_stylesheet, mono_font
from pystxmcontrol.gui import dashboard_widgets as dw


class BeamlinePanelWindow(QDialog):
    """Non-modal, always-on-top beamline-parameter window in dashboard style.

    Parameters
    ----------
    db : BeamlineDatabase | BeamlineDatabaseClient
        Object exposing get_desired_energies / get_entry / upsert_entry /
        delete_entry.  In the GUI this is a ``BeamlineDatabaseClient`` that talks
        to the server over the network; the local ``BeamlineDatabase`` has the
        same interface.
    is_staff : bool
        When True, edit fields and write buttons are enabled.
    parent : QWidget, optional
    """

    def __init__(self, db, is_staff: bool = False, parent=None):
        super().__init__(parent)
        self._db = db
        self._is_staff = is_staff
        self._current_energy: float | None = None

        self.setWindowTitle("Beamline Panel")
        self.setMinimumWidth(560)
        self.setStyleSheet(build_stylesheet())
        # Float above the main window without blocking it.
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._populate_combo()

    # ── UI construction ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Energy selector ────────────────────────────────────────────────
        sel_card, sel_body = dw.card("Desired energy", padded=True)
        sel_row = QHBoxLayout()
        sel_row.setSpacing(10)
        self._energy_combo = QComboBox()
        self._energy_combo.setCursor(Qt.PointingHandCursor)
        self._energy_combo.setMinimumWidth(160)
        self._energy_combo.currentIndexChanged.connect(self._on_energy_selected)
        sel_row.addWidget(self._energy_combo, 1)
        if self._is_staff:
            self._add_btn = QPushButton("Add New Entry")
            self._add_btn.setProperty("role", "small")
            self._add_btn.setCursor(Qt.PointingHandCursor)
            self._add_btn.clicked.connect(self._on_add_entry)
            sel_row.addWidget(self._add_btn)
        sel_body.addLayout(sel_row)
        root.addWidget(sel_card)

        # ── Parameter grid ─────────────────────────────────────────────────
        grid_card, grid_body = dw.card("Parameters", padded=True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 0)

        # Header
        grid.addWidget(dw.label("PARAMETER", role="fieldLabel"), 0, 0)
        cur_hdr = dw.label("CURRENT", role="fieldLabel")
        cur_hdr.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(cur_hdr, 0, 1)
        if self._is_staff:
            grid.addWidget(dw.label("NEW VALUE", role="fieldLabel"), 0, 2)

        self._current_labels: dict[str, QLabel] = {}
        self._edit_fields: dict[str, QLineEdit] = {}

        for row_idx, (col, label, _dtype) in enumerate(COLUMNS, start=1):
            grid.addWidget(dw.label(label, role="mono"), row_idx, 0)

            current_lbl = dw.label("—", role="value")
            current_lbl.setFont(mono_font(12))
            current_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            current_lbl.setMinimumWidth(110)
            grid.addWidget(current_lbl, row_idx, 1)
            self._current_labels[col] = current_lbl

            if self._is_staff:
                edit = dw.field()
                edit.setPlaceholderText("unchanged")
                edit.setFixedWidth(130)
                grid.addWidget(edit, row_idx, 2)
                self._edit_fields[col] = edit

        grid_body.addLayout(grid)
        root.addWidget(grid_card)

        # ── Notes ──────────────────────────────────────────────────────────
        notes_card, notes_body = dw.card("Notes", padded=True)
        if self._is_staff:
            self._notes_edit = dw.field()
            self._notes_edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._notes_edit.setPlaceholderText("optional notes")
            notes_body.addWidget(self._notes_edit)
        self._notes_label = dw.label("—", role="monoFaint")
        self._notes_label.setWordWrap(True)
        notes_body.addWidget(self._notes_label)
        self._modified_label = dw.label("", role="monoFaint")
        notes_body.addWidget(self._modified_label)
        root.addWidget(notes_card)

        # ── Action buttons ─────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        if self._is_staff:
            self._save_btn = QPushButton("Save Changes")
            self._save_btn.setCursor(Qt.PointingHandCursor)
            self._save_btn.setEnabled(False)
            self._save_btn.clicked.connect(self._on_save)
            btn_row.addWidget(self._save_btn)

            self._delete_btn = QPushButton("Delete Entry")
            self._delete_btn.setObjectName("stopAll")
            self._delete_btn.setCursor(Qt.PointingHandCursor)
            self._delete_btn.setEnabled(False)
            self._delete_btn.clicked.connect(self._on_delete)
            btn_row.addWidget(self._delete_btn)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    # ── populate / refresh ──────────────────────────────────────────────────
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

    # ── staff actions ───────────────────────────────────────────────────────
    def _on_add_entry(self):
        energy_str, ok = QInputDialog.getText(
            self, "Add Entry", "Desired Energy (eV):"
        )
        if not ok or not energy_str.strip():
            return
        try:
            energy = float(energy_str.strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid Input",
                                "Please enter a numeric energy value.")
            return
        if self._db.get_entry(energy) is not None:
            QMessageBox.warning(
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
                QMessageBox.warning(
                    self, "Invalid Value",
                    f"Could not parse '{text}' for {col}."
                )
                return

        notes = self._notes_edit.text().strip()
        if notes:
            kwargs["notes"] = notes

        if not kwargs:
            QMessageBox.information(self, "No Changes",
                                    "No new values were entered.")
            return

        self._db.upsert_entry(self._current_energy, **kwargs)
        # Refresh display
        self._on_energy_selected(self._energy_combo.currentIndex())
        QMessageBox.information(
            self, "Saved", f"Entry for {self._current_energy:.2f} eV updated."
        )

    def _on_delete(self):
        if self._current_energy is None:
            return
        reply = QMessageBox.question(
            self, "Delete Entry",
            f"Delete the entry for {self._current_energy:.2f} eV?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._db.delete_entry(self._current_energy)
        self._populate_combo()
        self._clear_fields()
        self._current_energy = None
        self._energy_combo.setCurrentIndex(0)

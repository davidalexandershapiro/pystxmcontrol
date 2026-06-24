"""
LogbookWidget: the unified logbook view for the Agent tab's right panel.

Renders the active logbook's entries as cards (text, metadata, embedded snapshot) with
per-entry edit/delete links, an input line for free-form notes, and New/Open/Rename/Export
controls. A logbook is a self-contained directory (its name is the directory name); "Open"
just points the shared LogbookModel at a different directory.

The view is model-driven: it re-renders on LogbookModel.changed, so entries added by the
browser, the analysis widget, or the agent appear here live.
"""

import os
from datetime import datetime
from typing import Callable, Optional

from PySide6 import QtCore, QtWidgets

from pystxmcontrol.gui.models.logbook_model import LogbookModel


# Author → accent colour for the entry card's left border + header (no background fill,
# so the card sits on the theme background and follows light/dark).
_AUTHOR_COLOR = {
    "human":        "#42a5f5",   # blue
    "agent":        "#66bb6a",   # green
    "intelligence": "#4fc3f7",   # cyan
}
# Author → friendly source label shown in the header text.
_AUTHOR_LABEL = {
    "human":        "You",
    "agent":        "Agent",
    "intelligence": "Intelligence",
}
_DIM = "#888888"


def _fmt_ts(ts: str) -> str:
    """Render an ISO timestamp compactly; fall back to the raw string."""
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts or ""


def _looks_like_table_sep(line: str) -> bool:
    """A Markdown table separator row, e.g. |---|:--:|."""
    s = line.strip().strip("|").strip()
    return bool(s) and "-" in s and set(s) <= set("-: |")


def _normalize_tables(text: str) -> str:
    """Insert a blank line before a pipe-table header when a non-blank line directly
    precedes it. python-markdown only recognises a table when it's separated from the
    preceding paragraph by a blank line; this makes the common 'lead-in line then table'
    case render without the user having to remember the blank line (and matches the PDF)."""
    lines = text.split("\n")
    out: list = []
    for i, line in enumerate(lines):
        is_header = ("|" in line and i + 1 < len(lines)
                     and _looks_like_table_sep(lines[i + 1]))
        if is_header and out and out[-1].strip() != "":
            out.append("")
        out.append(line)
    return "\n".join(out)


def _md_to_html(text: str) -> str:
    """Render an entry body as Markdown (incl. pipe tables) to HTML. Degrades to escaped
    plain text with line breaks if the markdown package isn't installed."""
    try:
        import markdown as _markdown
        return _markdown.markdown(
            _normalize_tables(text), extensions=["tables", "fenced_code", "sane_lists"]
        )
    except Exception:
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return esc.replace("\n", "<br>")


class LogbookWidget(QtWidgets.QWidget):
    """Model-driven logbook view + controls for one active logbook directory."""

    def __init__(self, model: LogbookModel,
                 default_dir_provider: Optional[Callable[[], str]] = None,
                 parent=None):
        super().__init__(parent)
        self._model = model
        self._default_dir = default_dir_provider or (lambda: os.path.expanduser("~"))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── top bar: active logbook + controls ───────────────────────────────
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(4)
        self._name_label = QtWidgets.QLabel()
        self._name_label.setStyleSheet("color: #cccccc; font-size: 13px; font-weight: bold;")
        bar.addWidget(self._name_label)
        bar.addStretch()
        for text, slot, tip in (
            ("New",    self._on_new,    "Create a new logbook directory"),
            ("Open",   self._on_open,   "Open an existing logbook directory"),
            ("Rename", self._on_rename, "Rename the active logbook directory"),
            ("Export PDF", self._on_export, "Regenerate and open the logbook PDF"),
        ):
            btn = QtWidgets.QPushButton(text)
            btn.setStyleSheet(
                "QPushButton { background-color: #333333; color: #cccccc; "
                "border: 1px solid #555555; padding: 2px 8px; border-radius: 3px; font-size: 11px; }"
                "QPushButton:hover { background-color: #444444; }"
            )
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        layout.addLayout(bar)

        # ── entry list ───────────────────────────────────────────────────────
        self._browser = QtWidgets.QTextBrowser()
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_anchor_clicked)
        # No background/text colour here, so the view follows the light/dark theme palette.
        self._browser.setStyleSheet(
            "QTextBrowser { border: 1px solid #3a3a3a; font-size: 14px; }"
        )
        # Document-level CSS styles the tables/code that Markdown emits (QTextBrowser
        # ignores most inline CSS on those, but honours the default style sheet). Colours
        # are left to the theme; only borders use a mid-grey that reads on light or dark.
        self._browser.document().setDefaultStyleSheet(
            "table { border-collapse: collapse; margin: 4px 0; }"
            "th, td { border: 1px solid #888; padding: 3px 7px; }"
            "th { font-weight: bold; }"
            "code, pre { font-family: monospace; }"
        )
        layout.addWidget(self._browser, stretch=1)

        # ── note input row ───────────────────────────────────────────────────
        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(4)
        self._note_input = QtWidgets.QLineEdit()
        self._note_input.setPlaceholderText("Add a note to the logbook…")
        self._note_input.setStyleSheet(
            "QLineEdit { background-color: #2a2a2a; color: #e0e0e0; "
            "border: 1px solid #3a3a3a; padding: 4px; border-radius: 3px; font-size: 14px; }"
        )
        self._note_input.returnPressed.connect(self._on_add_note)
        input_row.addWidget(self._note_input, stretch=1)
        self._compose_btn = QtWidgets.QPushButton("Compose…")
        self._compose_btn.setStyleSheet(
            "QPushButton { background-color: #333333; color: #cccccc; "
            "border: 1px solid #555555; padding: 4px 8px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #444444; }"
        )
        self._compose_btn.setToolTip("Write a longer entry with Markdown / tables")
        self._compose_btn.clicked.connect(self._on_compose)
        input_row.addWidget(self._compose_btn)
        self._add_btn = QtWidgets.QPushButton("Add")
        self._add_btn.setFixedWidth(55)
        self._add_btn.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: #e3f2fd; "
            "border: none; padding: 4px 8px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #1976d2; }"
        )
        self._add_btn.clicked.connect(self._on_add_note)
        input_row.addWidget(self._add_btn)
        layout.addLayout(input_row)

        self._model.changed.connect(self._render)
        self._render()

    # ── rendering ─────────────────────────────────────────────────────────────
    def _render(self, *_):
        folder = self._model.folder
        if folder:
            self._name_label.setText(f"📓 {os.path.basename(folder)}")
        else:
            self._name_label.setText("📓 (no logbook open)")
        has_logbook = bool(folder)
        self._note_input.setEnabled(has_logbook)
        self._add_btn.setEnabled(has_logbook)
        self._compose_btn.setEnabled(has_logbook)

        entries = self._model.entries
        if not folder:
            self._browser.setHtml(
                f'<div style="color:{_DIM}; padding:12px;">No logbook open. '
                'Use <b>New</b> or <b>Open</b> to start one.</div>'
            )
            return
        if not entries:
            self._browser.setHtml(
                f'<div style="color:{_DIM}; padding:12px;">This logbook is empty. '
                'Add a note below, or add scans from the Browser / Analysis tabs.</div>'
            )
            return

        snaps_dir = os.path.join(folder, "logbook_snaps")
        cards = [self._render_card(i, e, snaps_dir) for i, e in enumerate(entries)]
        self._browser.setHtml("".join(cards))
        # Keep the newest entry in view.
        sb = self._browser.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _render_card(self, i: int, entry: dict, snaps_dir: str) -> str:
        author = entry.get("author", "human")
        accent = _AUTHOR_COLOR.get(author, _AUTHOR_COLOR["human"])
        source = _AUTHOR_LABEL.get(author, author.capitalize())
        eid = entry.get("id", "")
        ts = _fmt_ts(entry.get("timestamp", ""))
        title = entry.get("image_file", "") or "note"

        parts = [
            # No background fill — only the accent left border marks the source.
            f'<div style="border-left:3px solid {accent}; padding:6px 8px; margin:4px 1px;">',
            f'<span style="color:{accent}; font-size:12px; font-weight:bold;">'
            f'{source} - #{i + 1} &nbsp; {self._esc(title)}</span>'
            f'<span style="color:{_DIM}; font-size:11px;"> &nbsp; {ts}</span>'
            f' &nbsp; <a href="action://edit/{eid}" style="color:{_DIM}; font-size:11px;">edit</a>'
            f' &nbsp; <a href="action://delete/{eid}" style="color:{_DIM}; font-size:11px;">delete</a>'
            f'<br>',
        ]

        body = (entry.get("text", "") or "").strip()
        if body:
            # Render Markdown (incl. pipe tables) in a div so block elements nest correctly.
            # No explicit text colour, so it follows the theme.
            parts.append(f'<div>{_md_to_html(body)}</div>')

        snap = entry.get("snap_file", "")
        if snap:
            path = os.path.join(snaps_dir, snap)
            if os.path.isfile(path):
                # Qt rich text loads local images from a file:// URL. Cap the width so
                # large snapshots don't overflow the panel.
                url = QtCore.QUrl.fromLocalFile(path).toString()
                parts.append(f'<img src="{url}" width="360"><br>')

        comment = (entry.get("comment", "") or "").strip()
        if comment:
            parts.append(
                f'<span style="font-size:12px;">'
                f'<b>Comment:</b> {self._esc(comment)}</span><br>'
            )

        detail = (entry.get("detail_text", "") or "").strip()
        if detail:
            parts.append(
                f'<span style="color:{_DIM}; font-size:11px; font-family:monospace;">'
                f'{self._esc(detail).replace(chr(10), "<br>")}</span>'
            )

        parts.append("</div>")
        return "".join(parts)

    @staticmethod
    def _esc(text: str) -> str:
        return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    # ── actions ────────────────────────────────────────────────────────────────
    def _on_anchor_clicked(self, url: QtCore.QUrl):
        if url.scheme() != "action":
            return
        action = url.host()                       # "edit" or "delete"
        eid = url.path().lstrip("/")              # the entry id
        if action == "edit":
            self._edit_entry(eid)
        elif action == "delete":
            self._delete_entry(eid)

    def _on_add_note(self):
        text = self._note_input.text().strip()
        if not text or not self._model.folder:
            return
        self._note_input.clear()
        self._model.add(text=text, author="human")

    def _on_compose(self):
        """Open a multiline composer for longer entries (Markdown / tables)."""
        if not self._model.folder:
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Compose logbook entry")
        dlg.resize(580, 380)
        v = QtWidgets.QVBoxLayout(dlg)
        hint = QtWidgets.QLabel("Markdown supported, including | pipe | tables |.")
        hint.setStyleSheet("color:#888888;")
        v.addWidget(hint)
        editor = QtWidgets.QPlainTextEdit()
        # Monospace so table columns line up while typing; colours follow the theme.
        editor.setStyleSheet("font-family:monospace; font-size:13px;")
        v.addWidget(editor, stretch=1)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            text = editor.toPlainText().strip()
            if text:
                self._model.add(text=text, author="human")

    def _edit_entry(self, eid: str):
        entry = next((e for e in self._model.entries if e.get("id") == eid), None)
        if entry is None:
            return
        # Edit the free-form body for notes; the comment for snapshot entries.
        is_note = not entry.get("snap_file")
        field = "text" if is_note else "comment"
        current = entry.get(field, "")
        new, ok = QtWidgets.QInputDialog.getMultiLineText(
            self, "Edit entry", f"Edit {field}:", current
        )
        if ok:
            self._model.update(eid, **{field: new})

    def _delete_entry(self, eid: str):
        if QtWidgets.QMessageBox.question(
            self, "Delete entry", "Delete this logbook entry? This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        ) == QtWidgets.QMessageBox.Yes:
            self._model.delete(eid)

    def _on_new(self):
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New logbook", "Logbook name (becomes a directory name):"
        )
        if not ok or not name.strip():
            return
        safe = name.strip().replace("/", "_").replace("\\", "_")
        base = self._default_dir() or os.path.expanduser("~")
        path = os.path.join(base, safe)
        if os.path.exists(path):
            if not os.path.isdir(path):
                QtWidgets.QMessageBox.warning(self, "New logbook",
                                              f"A file named '{safe}' already exists here.")
                return
            # Existing directory — just open it.
        else:
            try:
                os.makedirs(path)
            except OSError as e:
                QtWidgets.QMessageBox.critical(self, "New logbook", f"Could not create:\n{e}")
                return
        self._model.set_folder(path)

    def _on_open(self):
        start = self._model.folder or self._default_dir() or os.path.expanduser("~")
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Open logbook directory", start
        )
        if path:
            self._model.set_folder(path)

    def _on_rename(self):
        folder = self._model.folder
        if not folder:
            return
        new, ok = QtWidgets.QInputDialog.getText(
            self, "Rename logbook", "New name:", text=os.path.basename(folder)
        )
        if not ok or not new.strip():
            return
        safe = new.strip().replace("/", "_").replace("\\", "_")
        new_path = os.path.join(os.path.dirname(folder), safe)
        if new_path == folder:
            return
        if os.path.exists(new_path):
            QtWidgets.QMessageBox.warning(self, "Rename logbook",
                                          f"'{safe}' already exists.")
            return
        try:
            os.rename(folder, new_path)
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "Rename logbook", f"Could not rename:\n{e}")
            return
        self._model.set_folder(new_path)

    def _on_export(self):
        path = self._model.export_pdf()
        if not path or not os.path.isfile(path):
            QtWidgets.QMessageBox.information(self, "Export PDF",
                                              "Nothing to export (logbook is empty).")
            return
        QtCore.QTimer.singleShot(
            0, lambda: QtCore.QProcess.startDetached("xdg-open", [path])
        )

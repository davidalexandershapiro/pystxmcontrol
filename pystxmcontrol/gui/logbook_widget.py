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

from PySide6 import QtCore, QtGui, QtWidgets

from pystxmcontrol.gui.models.logbook_model import LogbookModel
from pystxmcontrol.gui.markdown_render import md_to_html, TABLE_STYLESHEET


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

# Image file extensions accepted when dragging external files onto the panel.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
               ".webp", ".svg", ".ico"}


def _fmt_ts(ts: str) -> str:
    """Render an ISO timestamp compactly; fall back to the raw string."""
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts or ""




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
        # No text colour, so the label follows the light/dark theme palette.
        self._name_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        bar.addWidget(self._name_label)
        bar.addStretch()
        for text, slot, tip in (
            ("New",    self._on_new,    "Create a new logbook directory"),
            ("Open",   self._on_open,   "Open an existing logbook directory"),
            ("Rename", self._on_rename, "Rename the active logbook directory"),
            ("Export PDF", self._on_export, "Regenerate and open the logbook PDF"),
        ):
            btn = QtWidgets.QPushButton(text)
            # Colours come from the active theme's button style; only the
            # compact font size is pinned.
            btn.setStyleSheet("QPushButton { font-size: 11px; }")
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
        # ignores most inline CSS on those, but honours the default style sheet).
        self._browser.document().setDefaultStyleSheet(TABLE_STYLESHEET)
        layout.addWidget(self._browser, stretch=1)

        # ── note input row ───────────────────────────────────────────────────
        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(4)
        self._note_input = QtWidgets.QLineEdit()
        self._note_input.setPlaceholderText("Add a note to the logbook…")
        # No background/text colour, so the field follows the light/dark theme palette.
        self._note_input.setStyleSheet(
            "QLineEdit { padding: 4px; border-radius: 3px; font-size: 14px; }"
        )
        self._note_input.returnPressed.connect(self._on_add_note)
        input_row.addWidget(self._note_input, stretch=1)
        self._compose_btn = QtWidgets.QPushButton("Compose…")
        # Colours come from the active theme's button style; only the padding is
        # pinned to match the Add button height.
        self._compose_btn.setStyleSheet("QPushButton { padding: 4px 8px; }")
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

        # Drag external image files (or image data) onto the panel to add them as
        # entries. The read-only browser's viewport accepts drops itself, so filter
        # its events too — otherwise drops over the entry list wouldn't reach us.
        self.setAcceptDrops(True)
        self._browser.viewport().installEventFilter(self)

        # Entry ids whose (otherwise collapsed) "Motor positions" block is expanded.
        self._expanded_motors: set[str] = set()

        self._model.changed.connect(self._render)
        self._render()

    # ── rendering ─────────────────────────────────────────────────────────────
    def _render(self, *_, scroll_to_bottom: bool = True):
        # Toggling a collapsible block re-renders in place; in that case we keep the
        # current scroll position instead of jumping to the newest entry.
        prev_scroll = self._browser.verticalScrollBar().value()
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
        sb = self._browser.verticalScrollBar()
        if scroll_to_bottom:
            # Keep the newest entry in view.
            sb.setValue(sb.maximum())
        else:
            sb.setValue(prev_scroll)

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
            parts.append(f'<div>{md_to_html(body)}</div>')

        snap = entry.get("snap_file", "")
        if snap:
            path = os.path.join(snaps_dir, snap)
            if os.path.isfile(path):
                url = self._snap_resource(path, eid, width=self._snap_display_width(path))
                if url:
                    # Wrap the image in its own block <div> (like the body above) so it
                    # always starts on a new line. A bare <img> is inline, so QTextBrowser
                    # sometimes tucks it onto the end of the preceding text instead.
                    parts.append(f'<div><img src="{url}"></div>')

        comment = (entry.get("comment", "") or "").strip()
        if comment:
            parts.append(
                f'<span style="font-size:12px;">'
                f'<b>Comment:</b> {self._esc(comment)}</span><br>'
            )

        detail = (entry.get("detail_text", "") or "").strip()
        if detail:
            head, motors = self._split_motor_detail(detail)
            mono = (f'<span style="color:{_DIM}; font-size:11px; '
                    f'font-family:monospace;">%s</span>')
            if head:
                parts.append(mono % self._esc(head).replace(chr(10), "<br>"))
            if motors:
                expanded = eid in self._expanded_motors
                arrow = "▾" if expanded else "▸"
                n = sum(1 for ln in motors.split("\n") if ln.strip())
                # Collapsible toggle reuses the anchor-click → re-render path that
                # edit/delete use; QTextBrowser can't render HTML <details>.
                parts.append(
                    f'<br><a href="action://motors/{eid}" style="color:{_DIM}; '
                    f'font-size:11px; text-decoration:none;">'
                    f'{arrow} Motor positions ({n})</a>'
                )
                if expanded:
                    parts.append(
                        "<br>" + mono % self._esc(motors).replace(chr(10), "<br>")
                    )

        parts.append("</div>")
        return "".join(parts)

    @staticmethod
    def _split_motor_detail(detail: str) -> tuple[str, str]:
        """Split a detail block into (always-shown head, collapsible motor list).

        The browser-tab export writes scan parameters followed by a ``Motor positions:``
        header and one indented line per motor (see data_browser_widget). The motor list
        is the bulky part, so it folds away behind a toggle while the scan parameters stay
        visible. Entries without that header (notes, agent entries) keep their full text.
        """
        lines = detail.split("\n")
        for idx, line in enumerate(lines):
            if line.strip() == "Motor positions:":
                head = "\n".join(lines[:idx]).rstrip("\n")
                motors = "\n".join(lines[idx + 1:]).strip("\n")
                return head, motors
        return detail, ""

    def _snap_display_width(self, path: str, base: int = 360) -> int:
        """Choose a card display width (logical px) for a snapshot.

        Wide-aspect figures — e.g. the NNMF cluster-map-beside-cluster-spectra panel, which
        packs an image and a plot side by side — get up to double the base width so both
        halves stay legible; roughly-square scan snapshots keep the base width. The result is
        capped to the browser viewport so a wide figure never forces a horizontal scrollbar.
        """
        img = QtGui.QImage(path)
        if img.isNull() or img.height() == 0:
            return base
        if img.width() / img.height() < 1.6:      # square/portrait — normal width
            return base
        avail = self._browser.viewport().width() - 24   # minus the card border/padding
        return max(base, min(base * 2, avail)) if avail > base else base

    def _snap_resource(self, path: str, eid: str, width: int = 360) -> str | None:
        """Scale a snapshot and register it as a document image resource.

        Scan snapshots are stored at their native pixel resolution, so displaying
        them means UPSCALING to the card width. Use nearest-neighbour, snapped to an
        integer pixel factor, so the discrete scan pixels stay crisp and uniform —
        no interpolation / blur. Wider-than-the-card figures are instead DOWNSCALED
        with a smooth transform, which keeps their fine plot/axis text legible (the
        document's own width-attribute scaling is nearest-neighbour and would mangle
        that text, so we pre-scale and reference the image 1:1, dpr-tagged, with no
        width attribute). Registered before setHtml() so the document resolves it.
        """
        img = QtGui.QImage(path)
        if img.isNull():
            return None
        dpr = self._browser.devicePixelRatioF() or 1.0
        target_px = max(1, round(width * dpr))
        src_w = img.width()
        if target_px > src_w:                       # upscale → crisp, uniform pixels
            factor = max(1, target_px // src_w)     # floor: never exceed the card width
            img = img.scaledToWidth(src_w * factor, QtCore.Qt.FastTransformation)
        elif target_px < src_w:                     # downscale → keep figures legible
            img = img.scaledToWidth(target_px, QtCore.Qt.SmoothTransformation)
        img.setDevicePixelRatio(dpr)   # lay out at native logical px
        url = QtCore.QUrl(f"snap://{eid or os.path.basename(path)}")
        self._browser.document().addResource(
            QtGui.QTextDocument.ImageResource, url, img)
        return url.toString()

    @staticmethod
    def _esc(text: str) -> str:
        return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    # ── drag & drop (external images) ───────────────────────────────────────────
    @staticmethod
    def _dropped_image_paths(mime: QtCore.QMimeData) -> list:
        """Local image-file paths carried by a drag (empty list if none)."""
        if not mime.hasUrls():
            return []
        return [
            url.toLocalFile() for url in mime.urls()
            if url.isLocalFile()
            and os.path.splitext(url.toLocalFile())[1].lower() in _IMAGE_EXTS
        ]

    def _drag_has_image(self, mime: QtCore.QMimeData) -> bool:
        return mime.hasImage() or bool(self._dropped_image_paths(mime))

    def dragEnterEvent(self, event):
        event.acceptProposedAction() if self._drag_has_image(event.mimeData()) \
            else event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction() if self._drag_has_image(event.mimeData()) \
            else event.ignore()

    def dropEvent(self, event):
        event.acceptProposedAction() if self._add_dropped_images(event.mimeData()) \
            else event.ignore()

    def eventFilter(self, obj, event):
        # The browser viewport receives drops over the entry list; route them here.
        if obj is self._browser.viewport():
            et = event.type()
            if et in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove):
                if self._drag_has_image(event.mimeData()):
                    event.acceptProposedAction()
                    return True
            elif et == QtCore.QEvent.Drop:
                if self._add_dropped_images(event.mimeData()):
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(obj, event)

    def _add_dropped_images(self, mime: QtCore.QMimeData) -> bool:
        """Add dropped image file(s) / image data as logbook entries.

        Returns True if at least one image was added (the drop is then consumed).
        """
        if not self._drag_has_image(mime):
            return False
        if not self._model.folder:
            QtWidgets.QMessageBox.information(
                self, "No logbook open",
                "Open or create a logbook before dropping images.")
            return False

        added = 0
        paths = self._dropped_image_paths(mime)
        if paths:
            for path in paths:
                img = QtGui.QImage(path)
                if img.isNull():
                    continue
                meta = {"filename": os.path.basename(path),
                        "scan_type": "External Image"}
                self._model.add(img, meta=meta, author="human")
                added += 1
        else:
            data = mime.imageData()
            img = None
            if isinstance(data, QtGui.QImage):
                img = data
            elif isinstance(data, QtGui.QPixmap):
                img = data.toImage()
            if img is not None and not img.isNull():
                self._model.add(img, meta={"filename": "dropped_image",
                                           "scan_type": "External Image"},
                                author="human")
                added += 1

        if added == 0:
            QtWidgets.QMessageBox.warning(
                self, "Could not add image",
                "No readable image was found in the dropped item(s).")
            return False
        return True

    # ── actions ────────────────────────────────────────────────────────────────
    def _on_anchor_clicked(self, url: QtCore.QUrl):
        if url.scheme() != "action":
            return
        action = url.host()                       # "edit", "delete" or "motors"
        eid = url.path().lstrip("/")              # the entry id
        if action == "edit":
            self._edit_entry(eid)
        elif action == "delete":
            self._delete_entry(eid)
        elif action == "motors":
            # Toggle the motor-positions block for this entry and re-render in place.
            if eid in self._expanded_motors:
                self._expanded_motors.discard(eid)
            else:
                self._expanded_motors.add(eid)
            self._render(scroll_to_bottom=False)

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

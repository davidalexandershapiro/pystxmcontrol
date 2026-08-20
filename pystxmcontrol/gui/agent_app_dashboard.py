"""
Agent App (dashboard style) — a standalone task-agent console for the dashboard's
Agent tab.

Ports the working agent chat from ``intelligence_widget.py`` onto the dashboard's
bespoke dark theme (``dashboard_theme``): a live conversation of message bubbles
(operator / task agent / intelligence agent), streamed tool-activity traces, a
composer, intelligence anomaly/recommendation cards with action links, a
forward-looking plan-approval card, and a dashboard-themed logbook column wired
to the shared ``LogbookModel``.

Two classes:

``DashboardLogbookPanel``
    The right-hand logbook — model-driven and live (agent/browser/analysis writes
    appear instantly), reskinned onto the dashboard palette.  Card chrome
    (header + New/Open/Rename/Export + author filter pills + composer) around a
    themed ``QTextBrowser`` that renders each entry as a card (Markdown/tables,
    embedded snapshot, edit/delete/motors anchors, external-image drag-and-drop).

``AgentApp``
    The whole tab: a splitter with the conversation on the left and the logbook on
    the right.  Works both connected (``controller`` drives the task agent, the
    intelligence stream, and logbook writes) and standalone (``controller`` is
    ``None`` — the composer is disabled, but the logbook column still renders from
    a supplied/opened ``LogbookModel``), mirroring ``motor_panel_dashboard``.

The widget carries its own stylesheet so it works as a top-level window too; when
embedded in ``mainwindow_dashboard`` the window's stylesheet already applies, so
the re-set is a harmless no-op.
"""

import os
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit, QVBoxLayout, QHBoxLayout,
    QScrollArea, QButtonGroup, QSplitter, QTextBrowser, QCheckBox, QSizePolicy,
    QMessageBox, QInputDialog, QFileDialog, QDialog, QDialogButtonBox,
    QPlainTextEdit,
)
from PySide6.QtCore import Qt, Signal, QUrl, QEvent, QTimer, QProcess, QMimeData
from PySide6.QtGui import QFont, QImage, QTextDocument

from pystxmcontrol.gui.dashboard_theme import C, build_stylesheet, mono_font, sans_font
from pystxmcontrol.gui.markdown_render import md_to_html, TABLE_STYLESHEET


# ── author → (accent colour, friendly label) on the dashboard palette ────────
# Blue for the operator (no blue in the token table, so a soft one), teal accent
# for the task agent, amber for the hardware-side intelligence agent — matching
# the conversation bubble speakers below.
_AUTHOR = {
    "human":        ("#7aa2d6", "You"),
    "agent":        (C["accent"], "Agent"),
    "intelligence": (C["motion"], "Intelligence"),
}
# Logbook filter label → author key it selects ("All" ⇒ everything).
_LOG_FILTERS = [("All", None), ("You", "human"),
                ("Agent", "agent"), ("Intelligence", "intelligence")]

# Image file extensions accepted when dragging external files onto the logbook.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff",
               ".webp", ".svg", ".ico"}

# Anomaly type → [(button label, action id), ...] offered on an intelligence card.
_ANOMALY_ACTIONS = {
    "intensity_drop":  [("Open shutter", "open_shutter"),
                        ("Abort scan", "abort_scan"), ("Clear", "clear_alert")],
    "intensity_drift": [("Abort scan", "abort_scan"), ("Clear", "clear_alert")],
    "focus_decline":   [("Move to focus", "move_to_focus"), ("Clear", "clear_alert")],
    "daq_timeout":     [("Clear", "clear_alert")],
}


def _esc(text) -> str:
    """HTML-escape, coercing None/non-str so an empty body renders blank."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\n", "<br>"))


def _fmt_ts(ts: str) -> str:
    """Render an ISO timestamp compactly; fall back to the raw string."""
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts or ""


def _mk_label(text, role=None, font=None, color=None):
    """A QLabel that opts into the dashboard QSS via its ``role`` property."""
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if font:
        lbl.setFont(font)
    if color:
        lbl.setStyleSheet(f"color:{color};background:transparent;")
    return lbl


def _mk_card(title):
    """Return (card QFrame, body QVBoxLayout) — the dashboard's titled card.

    Body has no padding; callers add their own content.  ``card._header_layout``
    is exposed so extra header controls can be inserted, mirroring the helpers in
    ``mainwindow_dashboard`` / ``motor_panel_dashboard``.
    """
    card = QFrame()
    card.setObjectName("card")
    cl = QVBoxLayout(card)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(0)
    header = QFrame()
    header.setObjectName("cardHeader")
    hl = QHBoxLayout(header)
    hl.setContentsMargins(14, 11, 14, 11)
    h = _mk_label(title.upper())
    h.setObjectName("panelHeading")
    hl.addWidget(h)
    hl.addStretch(1)
    cl.addWidget(header)
    card._header_layout = hl
    return card, cl


def _small_btn(text, tip=""):
    b = QPushButton(text)
    b.setProperty("role", "small")
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


# ════════════════════════════════════════════════════════════════════════════
#  Logbook panel (dashboard style, model-driven)
# ════════════════════════════════════════════════════════════════════════════
class DashboardLogbookPanel(QWidget):
    """The active logbook rendered on the dashboard theme.

    Model-driven: re-renders on ``LogbookModel.changed`` so entries added by the
    browser, the analysis widget, or the agent appear live.  A logbook is a
    self-contained directory (its basename is its name); "Open" just points the
    shared model at a different directory.
    """

    def __init__(self, model, default_dir_provider=None, parent=None):
        super().__init__(parent)
        self._model = model
        self._default_dir = default_dir_provider or (lambda: os.path.expanduser("~"))
        self._filter = None                 # author key, or None for "All"
        self._expanded_motors: set[str] = set()

        card, body = _mk_card("Logbook")
        self._name_note = _mk_label("", role="monoFaint")
        card._header_layout.insertWidget(1, self._name_note)
        card._header_layout.insertSpacing(2, 10)
        for text, slot, tip in (
            ("New", self._on_new, "Create a new logbook directory"),
            ("Open", self._on_open, "Open an existing logbook directory"),
            ("Rename", self._on_rename, "Rename the active logbook directory"),
            ("Export", self._on_export, "Regenerate and open the logbook PDF"),
        ):
            b = _small_btn(text, tip)
            b.clicked.connect(slot)
            card._header_layout.addWidget(b)

        # ── author filter pills ────────────────────────────────────────────
        frow = QFrame()
        frow.setObjectName("filterRow")
        frow.setStyleSheet(f"QFrame#filterRow {{background:{C['panel_footer']};"
                           f"border:none;border-bottom:1px solid {C['border']};}}")
        fl = QHBoxLayout(frow)
        fl.setContentsMargins(14, 10, 14, 10)
        fl.setSpacing(6)
        self._filter_grp = QButtonGroup(self)
        self._filter_grp.setExclusive(True)
        for i, (label, key) in enumerate(_LOG_FILTERS):
            b = QPushButton(label)
            b.setProperty("role", "pill")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            if i == 0:
                b.setChecked(True)
            self._filter_grp.addButton(b, i)
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            fl.addWidget(b)
        fl.addStretch(1)
        body.addWidget(frow)

        # ── entry list (themed QTextBrowser) ───────────────────────────────
        self._browser = QTextBrowser()
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_anchor_clicked)
        self._browser.setStyleSheet(
            f"QTextBrowser{{background:{C['plot_ground']};border:none;"
            f"color:{C['text_2']};font-size:13px;padding:6px 8px;}}")
        self._browser.document().setDefaultStyleSheet(TABLE_STYLESHEET)
        body.addWidget(self._browser, 1)

        # ── composer footer ────────────────────────────────────────────────
        footer = QFrame()
        footer.setObjectName("cardFooter")
        fl2 = QHBoxLayout(footer)
        fl2.setContentsMargins(14, 11, 14, 11)
        fl2.setSpacing(8)
        self._note_input = QLineEdit()
        self._note_input.setPlaceholderText("Add a note to the logbook…")
        self._note_input.setFont(sans_font(11))
        self._note_input.returnPressed.connect(self._on_add_note)
        fl2.addWidget(self._note_input, 1)
        self._compose_btn = _small_btn("Compose…", "Write a longer entry with Markdown / tables")
        self._compose_btn.clicked.connect(self._on_compose)
        fl2.addWidget(self._compose_btn)
        self._add_btn = QPushButton("Add")
        self._add_btn.setObjectName("beginScan")
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add_note)
        fl2.addWidget(self._add_btn)
        body.addWidget(footer)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(card)

        # External image drag-and-drop, including over the read-only browser.
        self.setAcceptDrops(True)
        self._browser.viewport().installEventFilter(self)

        if self._model is not None:
            self._model.changed.connect(self._render)
        self._render()

    # ── rendering ───────────────────────────────────────────────────────────
    def _render(self, *_):
        folder = self._model.folder if self._model is not None else None
        entries = self._model.entries if self._model is not None else []
        shown = [e for e in entries
                 if self._filter is None or e.get("author", "human") == self._filter]

        name = os.path.basename(folder) if folder else "(no logbook open)"
        self._name_note.setText(f"{name} · {len(shown)} entries" if folder else name)
        has = bool(folder)
        for w in (self._note_input, self._add_btn, self._compose_btn):
            w.setEnabled(has)

        if not folder:
            self._browser.setHtml(
                f'<div style="color:{C["text_faint"]};padding:14px;">No logbook open. '
                'Use <b>New</b> or <b>Open</b> to start one.</div>')
            return
        if not shown:
            hint = ("This logbook is empty. Add a note below, or add scans from the "
                    "Browser / Analysis tabs.") if not entries else "No entries match this filter."
            self._browser.setHtml(
                f'<div style="color:{C["text_faint"]};padding:14px;">{hint}</div>')
            return

        snaps_dir = os.path.join(folder, "logbook_snaps")
        # chronological (oldest → newest); keep the newest entry in view.
        html = "".join(self._render_card(i, e, snaps_dir)
                       for i, e in enumerate(entries)
                       if self._filter is None or e.get("author", "human") == self._filter)
        self._browser.setHtml(html)
        sb = self._browser.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _render_card(self, i: int, entry: dict, snaps_dir: str) -> str:
        author = entry.get("author", "human")
        accent, source = _AUTHOR.get(author, (_AUTHOR["human"][0], author.capitalize()))
        eid = entry.get("id", "")
        ts = _fmt_ts(entry.get("timestamp", ""))
        title = entry.get("image_file", "") or "note"

        parts = [
            f'<div style="border-left:3px solid {accent};background:{C["panel"]};'
            f'padding:8px 11px;margin:5px 2px;">',
            f'<span style="color:{accent};font-size:12px;font-weight:bold;">'
            f'{source} · #{i + 1} &nbsp; {_esc(title)}</span>'
            f'<span style="color:{C["text_faint"]};font-size:11px;"> &nbsp; {ts}</span>'
            f' &nbsp; <a href="action://edit/{eid}" style="color:{C["text_faint"]};'
            f'font-size:11px;text-decoration:none;">edit</a>'
            f' &nbsp; <a href="action://delete/{eid}" style="color:{C["text_faint"]};'
            f'font-size:11px;text-decoration:none;">delete</a><br>',
        ]

        body = (entry.get("text", "") or "").strip()
        if body:
            parts.append(f'<div style="color:{C["text_2"]};">{md_to_html(body)}</div>')

        snap = entry.get("snap_file", "")
        if snap:
            path = os.path.join(snaps_dir, snap)
            if os.path.isfile(path):
                url = self._snap_resource(path, eid, self._snap_display_width(path))
                if url:
                    parts.append(f'<div><img src="{url}"></div>')

        comment = (entry.get("comment", "") or "").strip()
        if comment:
            parts.append(f'<span style="color:{C["text_2"]};font-size:12px;">'
                         f'<b>Comment:</b> {_esc(comment)}</span><br>')

        detail = (entry.get("detail_text", "") or "").strip()
        if detail:
            head, motors = self._split_motor_detail(detail)
            mono = (f'<span style="color:{C["text_faint"]};font-size:11px;'
                    f'font-family:monospace;">%s</span>')
            if head:
                parts.append(mono % _esc(head).replace("\n", "<br>"))
            if motors:
                expanded = eid in self._expanded_motors
                arrow = "▾" if expanded else "▸"
                n = sum(1 for ln in motors.split("\n") if ln.strip())
                parts.append(
                    f'<br><a href="action://motors/{eid}" style="color:{C["text_faint"]};'
                    f'font-size:11px;text-decoration:none;">{arrow} Motor positions ({n})</a>')
                if expanded:
                    parts.append("<br>" + mono % _esc(motors).replace("\n", "<br>"))

        parts.append("</div>")
        return "".join(parts)

    @staticmethod
    def _split_motor_detail(detail: str):
        """Split a detail block into (always-shown head, collapsible motor list),
        matching the browser-tab export's ``Motor positions:`` header convention."""
        lines = detail.split("\n")
        for idx, line in enumerate(lines):
            if line.strip() == "Motor positions:":
                return ("\n".join(lines[:idx]).rstrip("\n"),
                        "\n".join(lines[idx + 1:]).strip("\n"))
        return detail, ""

    def _snap_display_width(self, path: str, base: int = 360) -> int:
        """Card display width for a snapshot: wide figures get up to 2× base, capped
        to the viewport so they never force a horizontal scrollbar."""
        img = QImage(path)
        if img.isNull() or img.height() == 0:
            return base
        if img.width() / img.height() < 1.6:
            return base
        avail = self._browser.viewport().width() - 28
        return max(base, min(base * 2, avail)) if avail > base else base

    def _snap_resource(self, path: str, eid: str, width: int = 360):
        """Register a snapshot as a document image resource, scaled for display.

        Scan snapshots are stored at their native pixel resolution, so showing them
        means UPSCALING to the card width.  Use nearest-neighbour, snapped to an
        integer pixel factor, so the discrete scan pixels stay crisp and uniform —
        no interpolation / blur.  Wider-than-the-card figures are instead DOWNSCALED
        with a smooth transform, which keeps their fine axis text and lines legible
        (and avoids aliasing).  The document is handed a 1:1, dpr-tagged image either
        way, so its own nearest-neighbour width scaling never re-touches it.
        """
        img = QImage(path)
        if img.isNull():
            return None
        dpr = self._browser.devicePixelRatioF() or 1.0
        target_px = max(1, round(width * dpr))
        src_w = img.width()
        if target_px > src_w:                       # upscale → crisp, uniform pixels
            factor = max(1, target_px // src_w)     # floor: never exceed the card width
            img = img.scaledToWidth(src_w * factor, Qt.FastTransformation)
        elif target_px < src_w:                     # downscale → keep figures legible
            img = img.scaledToWidth(target_px, Qt.SmoothTransformation)
        img.setDevicePixelRatio(dpr)
        url = QUrl(f"snap://{eid or os.path.basename(path)}")
        self._browser.document().addResource(QTextDocument.ImageResource, url, img)
        return url.toString()

    # ── interaction ───────────────────────────────────────────────────────────
    def _set_filter(self, key):
        self._filter = key
        self._render()

    def _on_anchor_clicked(self, url: QUrl):
        if url.scheme() != "action":
            return
        action, eid = url.host(), url.path().lstrip("/")
        if action == "edit":
            self._edit_entry(eid)
        elif action == "delete":
            self._delete_entry(eid)
        elif action == "motors":
            self._expanded_motors.symmetric_difference_update({eid})
            self._render()

    def _on_add_note(self):
        text = self._note_input.text().strip()
        if not text or not self._model or not self._model.folder:
            return
        self._note_input.clear()
        self._model.add(text=text, author="human")

    def _on_compose(self):
        if not self._model or not self._model.folder:
            return
        dlg = QDialog(self)
        dlg.setStyleSheet(build_stylesheet())
        dlg.setWindowTitle("Compose logbook entry")
        dlg.resize(580, 380)
        v = QVBoxLayout(dlg)
        v.addWidget(_mk_label("Markdown supported, including | pipe | tables |.",
                              role="monoFaint"))
        editor = QPlainTextEdit()
        editor.setFont(mono_font(11))
        v.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        v.addWidget(buttons)
        if dlg.exec() == QDialog.Accepted:
            text = editor.toPlainText().strip()
            if text:
                self._model.add(text=text, author="human")

    def _edit_entry(self, eid: str):
        entry = next((e for e in self._model.entries if e.get("id") == eid), None)
        if entry is None:
            return
        # Notes edit their body; snapshot entries edit their comment.
        field = "text" if not entry.get("snap_file") else "comment"
        new, ok = QInputDialog.getMultiLineText(
            self, "Edit entry", f"Edit {field}:", entry.get(field, ""))
        if ok:
            self._model.update(eid, **{field: new})

    def _delete_entry(self, eid: str):
        if QMessageBox.question(
            self, "Delete entry", "Delete this logbook entry? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self._model.delete(eid)

    def _on_new(self):
        name, ok = QInputDialog.getText(
            self, "New logbook", "Logbook name (becomes a directory name):")
        if not ok or not name.strip():
            return
        safe = name.strip().replace("/", "_").replace("\\", "_")
        base = self._default_dir() or os.path.expanduser("~")
        path = os.path.join(base, safe)
        if os.path.exists(path):
            if not os.path.isdir(path):
                QMessageBox.warning(self, "New logbook",
                                    f"A file named '{safe}' already exists here.")
                return
        else:
            try:
                os.makedirs(path)
            except OSError as e:
                QMessageBox.critical(self, "New logbook", f"Could not create:\n{e}")
                return
        self._model.set_folder(path)

    def _on_open(self):
        start = (self._model.folder if self._model else None) \
            or self._default_dir() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Open logbook directory", start)
        if path:
            self._model.set_folder(path)

    def _on_rename(self):
        folder = self._model.folder if self._model else None
        if not folder:
            return
        new, ok = QInputDialog.getText(self, "Rename logbook", "New name:",
                                       text=os.path.basename(folder))
        if not ok or not new.strip():
            return
        safe = new.strip().replace("/", "_").replace("\\", "_")
        new_path = os.path.join(os.path.dirname(folder), safe)
        if new_path == folder:
            return
        if os.path.exists(new_path):
            QMessageBox.warning(self, "Rename logbook", f"'{safe}' already exists.")
            return
        try:
            os.rename(folder, new_path)
        except OSError as e:
            QMessageBox.critical(self, "Rename logbook", f"Could not rename:\n{e}")
            return
        self._model.set_folder(new_path)

    def _on_export(self):
        path = self._model.export_pdf() if self._model else None
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "Export PDF",
                                    "Nothing to export (logbook is empty).")
            return
        QTimer.singleShot(0, lambda: QProcess.startDetached("xdg-open", [path]))

    # ── external image drag-and-drop ────────────────────────────────────────
    @staticmethod
    def _dropped_image_paths(mime: QMimeData):
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls()
                if u.isLocalFile()
                and os.path.splitext(u.toLocalFile())[1].lower() in _IMAGE_EXTS]

    def _drag_has_image(self, mime: QMimeData) -> bool:
        return mime.hasImage() or bool(self._dropped_image_paths(mime))

    def dragEnterEvent(self, event):
        (event.acceptProposedAction() if self._drag_has_image(event.mimeData())
         else event.ignore())

    def dragMoveEvent(self, event):
        (event.acceptProposedAction() if self._drag_has_image(event.mimeData())
         else event.ignore())

    def dropEvent(self, event):
        (event.acceptProposedAction() if self._add_dropped_images(event.mimeData())
         else event.ignore())

    def eventFilter(self, obj, event):
        if obj is self._browser.viewport():
            et = event.type()
            if et in (QEvent.DragEnter, QEvent.DragMove) and \
                    self._drag_has_image(event.mimeData()):
                event.acceptProposedAction()
                return True
            if et == QEvent.Drop and self._add_dropped_images(event.mimeData()):
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    def _add_dropped_images(self, mime: QMimeData) -> bool:
        if not self._drag_has_image(mime):
            return False
        if not self._model or not self._model.folder:
            QMessageBox.information(self, "No logbook open",
                                    "Open or create a logbook before dropping images.")
            return False
        added = 0
        for path in self._dropped_image_paths(mime):
            img = QImage(path)
            if img.isNull():
                continue
            self._model.add(img, meta={"filename": os.path.basename(path),
                                       "scan_type": "External Image"}, author="human")
            added += 1
        if added == 0:
            data = mime.imageData()
            img = data if isinstance(data, QImage) else None
            if img is not None and not img.isNull():
                self._model.add(img, meta={"filename": "dropped_image",
                                           "scan_type": "External Image"}, author="human")
                added += 1
        if added == 0:
            QMessageBox.warning(self, "Could not add image",
                                "No readable image was found in the dropped item(s).")
            return False
        return True


# ════════════════════════════════════════════════════════════════════════════
#  Agent App (conversation + composer + logbook)
# ════════════════════════════════════════════════════════════════════════════
class AgentApp(QWidget):
    """Standalone task-agent console styled for the dashboard.

    Parameters
    ----------
    controller : MainController or None
        When present, drives the task agent (``send_agent_query`` / ``cancel_task``
        / ``reset_task_history``) and feeds the conversation from its
        ``task_agent_status`` / ``task_agent_done`` / ``task_agent_running`` /
        ``intelligence_suggestion_received`` signals.  When ``None`` (placeholder
        mode) the composer is disabled.
    logbook_model : LogbookModel or None
        The shared logbook model.  Falls back to ``controller.logbook_model``.
    default_dir_provider : callable or None
        Returns the base directory for New/Open logbook dialogs.
    """

    # Emitted when an intelligence action link is clicked, so a host window can
    # react (e.g. clear its alarm banner) in addition to the hardware action this
    # widget performs directly on the controller.
    action_requested = Signal(str)

    def __init__(self, controller=None, logbook_model=None,
                 default_dir_provider=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        model = logbook_model or getattr(controller, "logbook_model", None)
        self.setStyleSheet(build_stylesheet())

        self._task_running = False
        self._show_traces = True
        self._trace_blocks = []       # every trace container, for the toggle
        self._active_trace = None     # the turn's in-progress trace container

        self._build_ui(model, default_dir_provider)
        self._connect_controller()
        self._refresh_composer()

    # ── construction ────────────────────────────────────────────────────────
    def _build_ui(self, model, default_dir_provider):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_conversation())
        self.logbook = DashboardLogbookPanel(model, default_dir_provider, parent=self)
        split.addWidget(self.logbook)
        # 50/50 to start, and the handle stays draggable; equal stretch keeps the
        # split proportional as the window resizes.
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([800, 800])
        root.addWidget(split, 1)

    def _build_conversation(self):
        card, body = _mk_card("Conversation")
        # Header: tool-activity toggle + New topic.
        self._traces_check = QCheckBox("Tool activity")
        self._traces_check.setChecked(self._show_traces)
        self._traces_check.setToolTip("Show or hide the agent's tool-call trace lines")
        self._traces_check.toggled.connect(self._on_toggle_traces)
        card._header_layout.addWidget(self._traces_check)
        card._header_layout.addSpacing(6)
        new_topic = _small_btn("New topic", "Clear the conversation and start fresh")
        new_topic.clicked.connect(self._on_new_topic)
        card._header_layout.addWidget(new_topic)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll = scroll
        inner = QWidget()
        self._conv = QVBoxLayout(inner)
        self._conv.setContentsMargins(20, 18, 20, 18)
        self._conv.setSpacing(14)
        self._conv.addWidget(self._session_divider("session started"))
        self._conv.addStretch(1)
        scroll.setWidget(inner)
        body.addWidget(scroll, 1)
        body.addWidget(self._build_composer())
        return card

    def _build_composer(self):
        footer = QFrame()
        footer.setObjectName("cardFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(9)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Describe a goal for the task agent…")
        self._input.setFont(sans_font(11.5))
        self._input.returnPressed.connect(self._submit)
        row.addWidget(self._input, 1)
        self._send = QPushButton("Send")
        self._send.setObjectName("beginScan")
        self._send.setCursor(Qt.PointingHandCursor)
        self._send.clicked.connect(self._submit)
        row.addWidget(self._send)
        return footer

    def _session_divider(self, text):
        wrap = QWidget()
        div = QHBoxLayout(wrap)
        div.setContentsMargins(0, 0, 0, 0)
        div.addStretch(1)
        chip = _mk_label(f"{datetime.now().strftime('%H:%M')} · {text}", role="monoFaint")
        chip.setStyleSheet(
            f"color:{C['text_faint']};background:{C['panel_footer']};"
            f"border:1px solid {C['border']};border-radius:20px;padding:3px 12px;")
        div.addWidget(chip)
        div.addStretch(1)
        return wrap

    # ── controller wiring ─────────────────────────────────────────────────────
    def _connect_controller(self):
        c = self.controller
        if c is None:
            return
        c.task_agent_status.connect(self.add_task_status)
        c.task_agent_done.connect(self.add_task_result)
        c.task_agent_running.connect(self.set_task_running)
        if hasattr(c, "intelligence_suggestion_received"):
            c.intelligence_suggestion_received.connect(self.add_suggestion)
        if hasattr(c, "agent_confirmation_requested"):
            c.agent_confirmation_requested.connect(self._show_confirmation)

    def _refresh_composer(self):
        """Composer is live only with a controller (placeholder mode disables it),
        and while a task runs the Send button becomes Stop."""
        connected = self.controller is not None
        self._input.setEnabled(connected and not self._task_running)
        self._send.setEnabled(connected)
        if not connected:
            self._input.setPlaceholderText("Task agent unavailable (no server connection)")
        elif self._task_running:
            self._input.setPlaceholderText("Agent is running…")
        else:
            self._input.setPlaceholderText("Describe a goal for the task agent…")

    # ── conversation append helpers ───────────────────────────────────────────
    def _add_widget(self, w):
        """Insert a widget just before the trailing stretch, then scroll down."""
        self._conv.insertWidget(self._conv.count() - 1, w)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def add_user_message(self, text: str):
        self._add_widget(self._bubble("OP", _esc(text),
                                       datetime.now().strftime("%H:%M:%S")))

    def add_task_result(self, text: str):
        self._active_trace = None      # the turn's tool trace is complete
        self._add_widget(self._bubble("TA", md_to_html(text),
                                       datetime.now().strftime("%H:%M:%S")))

    # ── operator confirmation (driven by the request_confirmation tool) ───────
    def _show_confirmation(self, request: dict):
        """Render the confirmation card the agent is blocking on (see the controller's
        _agent_confirm).  Clicking Approve/Decline resolves the agent's tool call — so
        these buttons stay live while the task is 'running' (the agent is paused on them)."""
        self._active_trace = None
        self._add_widget(self._confirm_card(
            request.get("id"),
            request.get("summary", "Confirm this action?"),
            request.get("details", "")))

    def _confirm_card(self, req_id, summary, details):
        card = QFrame()
        card.setObjectName("confirmCard")
        card.setStyleSheet(f"QFrame#confirmCard{{background:#0b1116;"
                           f"border:1px solid {C['accent_brdr']};border-radius:7px;}}")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        head = QFrame()
        head.setObjectName("confirmHead")
        head.setStyleSheet(f"QFrame#confirmHead{{background:{C['panel_footer']};"
                           f"border:none;border-bottom:1px solid {C['border']};}}")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(13, 9, 13, 9)
        h = _mk_label("CONFIRMATION REQUIRED")
        h.setObjectName("panelHeading")
        hl.addWidget(h)
        hl.addStretch(1)
        state = _mk_label("AWAITING YOU")
        state.setStyleSheet(f"color:{C['motion']};background:transparent;font-size:11px;")
        hl.addWidget(state)
        cv.addWidget(head)

        bodyw = QWidget()
        bv = QVBoxLayout(bodyw)
        bv.setContentsMargins(13, 12, 13, 12)
        bv.setSpacing(8)
        s = QLabel(summary)
        s.setWordWrap(True)
        s.setStyleSheet(f"color:{C['text']};background:transparent;font-size:13px;")
        bv.addWidget(s)
        if details:
            d = QLabel(details)
            d.setWordWrap(True)
            d.setStyleSheet(f"color:{C['text_faint']};background:transparent;"
                            "font-family:monospace;font-size:11px;")
            bv.addWidget(d)
        cv.addWidget(bodyw)

        actions = QFrame()
        actions.setObjectName("confirmActions")
        actions.setStyleSheet(f"QFrame#confirmActions{{background:{C['panel_footer']};"
                              f"border:none;border-top:1px solid {C['border']};}}")
        al = QHBoxLayout(actions)
        al.setContentsMargins(13, 11, 13, 11)
        al.setSpacing(8)
        approve = QPushButton("Approve && proceed")
        approve.setObjectName("beginScan")
        approve.setCursor(Qt.PointingHandCursor)
        decline = QPushButton("Decline")
        decline.setObjectName("rejectBtn")
        decline.setCursor(Qt.PointingHandCursor)
        approve.clicked.connect(
            lambda: self._resolve_confirm(req_id, state, approve, decline, True))
        decline.clicked.connect(
            lambda: self._resolve_confirm(req_id, state, approve, decline, False))
        al.addWidget(approve)
        al.addStretch(1)
        al.addWidget(decline)
        cv.addWidget(actions)
        return card

    def _resolve_confirm(self, req_id, state_lbl, approve_btn, decline_btn, approved):
        approve_btn.setEnabled(False)
        decline_btn.setEnabled(False)
        if approved:
            state_lbl.setText(f"APPROVED {datetime.now().strftime('%H:%M:%S')}")
            state_lbl.setStyleSheet(f"color:{C['ok']};background:transparent;font-size:11px;")
        else:
            state_lbl.setText("DECLINED")
            state_lbl.setStyleSheet(
                f"color:{C['alert_text']};background:transparent;font-size:11px;")
        if self.controller is not None and hasattr(self.controller, "resolve_agent_confirmation"):
            self.controller.resolve_agent_confirmation(req_id, approved)

    def add_task_status(self, msg: str):
        """A streamed TaskAgent trace line (tool call / progress marker)."""
        if self._active_trace is None:
            self._begin_trace_block()
        self._trace_line(self._active_trace, msg)
        if self._show_traces:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def set_task_running(self, running: bool):
        self._task_running = running
        if running:
            self._send.setText("Stop")
            self._send.setObjectName("cancelScan")
        else:
            self._send.setText("Send")
            self._send.setObjectName("beginScan")
            self._active_trace = None
        # Re-polish so the objectName change repaints with the new QSS rule.
        self._send.style().unpolish(self._send)
        self._send.style().polish(self._send)
        self._refresh_composer()

    def add_suggestion(self, message: dict):
        """Display an intelligence-agent suggestion (anomaly / recommendation),
        an agent free-form answer, or a plan proposal."""
        mtype = message.get("type", "")
        if mtype == "plan_proposal":
            self.show_proposal(message.get("plan", message))
            return
        if mtype == "task_recommendation":
            self._add_widget(self._bubble("IA", self._recommendation_html(message),
                                          datetime.now().strftime("%H:%M:%S")))
            return
        anomaly = message.get("anomaly_type", "")
        text = message.get("suggestion") or ""
        if anomaly == "user_query":
            self.add_task_result(text)
        else:
            self._add_anomaly_card(anomaly, message.get("severity", "warn"), text)

    # ── message bubble ────────────────────────────────────────────────────────
    def _bubble(self, speaker, html, meta, extra=None):
        avatar = {"OP": ("#1d2833", "#8b97a3"), "TA": ("#0f2a2b", C["accent"]),
                  "IA": ("#2a2113", C["motion"])}[speaker]
        frame = {"OP": ("#161b21", "#2c3a48", C["text"]),
                 "TA": ("#101820", "#22303c", C["text_2"]),
                 "IA": ("#171410", "#3a2f1a", "#d8cbb3")}[speaker]
        max_w = 1440

        w = QWidget()
        g = QHBoxLayout(w)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(12)
        av = QLabel(speaker)
        av.setFixedSize(26, 26)
        av.setAlignment(Qt.AlignCenter)
        av.setFont(mono_font(10, QFont.DemiBold))
        av.setStyleSheet(f"background:{avatar[0]};color:{avatar[1]};border-radius:5px;")
        g.addWidget(av, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(5)
        col.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
        bubble.setObjectName("convBubble")
        bubble.setMaximumWidth(max_w)
        # objectName-scoped so the border can't leak onto child QLabels.
        bubble.setStyleSheet(f"QFrame#convBubble{{background:{frame[0]};"
                             f"border:1px solid {frame[1]};border-radius:8px;}}")
        bv = QVBoxLayout(bubble)
        bv.setContentsMargins(14, 12, 14, 12)
        bv.setSpacing(8)
        if speaker == "IA":
            adv = _mk_label("ADVISORY → TASK AGENT")
            adv.setStyleSheet(f"color:{C['motion']};background:transparent;"
                              "font-size:10px;letter-spacing:1px;")
            bv.addWidget(adv)
        text = QLabel(html)
        text.setTextFormat(Qt.RichText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # A word-wrapped QLabel reports a narrow preferred width, and the trailing
        # stretch below lets the bubble collapse to it — so max_w alone never widens
        # anything. Pin a minimum wrap column (~2× the old ~50-char hug width) so the
        # bubble opens up; max_w still caps long messages.
        text.setMinimumWidth(700)
        text.setMaximumWidth(max_w - 28)
        text.setStyleSheet(f"color:{frame[2]};background:transparent;font-size:13px;")
        bv.addWidget(text)
        if extra is not None:
            bv.addWidget(extra)

        # Bubble hugs its content width (word-wrapping within max_w) via a trailing
        # stretch; an AlignTop on the content column would suppress QLabel wrap.
        brow = QHBoxLayout()
        brow.setContentsMargins(0, 0, 0, 0)
        brow.addWidget(bubble)
        brow.addStretch(1)
        col.addLayout(brow)
        col.addWidget(_mk_label(meta, role="monoFaint"))
        cw = QWidget()
        cw.setLayout(col)
        g.addWidget(cw, 1)
        return w

    # ── tool-activity trace block ─────────────────────────────────────────────
    def _begin_trace_block(self):
        block = QFrame()
        block.setObjectName("traceBlock")
        block.setStyleSheet(
            f"QFrame#traceBlock{{background:{C['panel_footer']};"
            f"border:1px solid {C['border']};border-radius:6px;}}")
        v = QVBoxLayout(block)
        v.setContentsMargins(12, 9, 12, 9)
        v.setSpacing(3)
        head = _mk_label("TOOL ACTIVITY")
        head.setStyleSheet(f"color:{C['text_faint']};background:transparent;"
                           "font-size:9px;letter-spacing:1px;")
        v.addWidget(head)
        block._lines = v
        block.setVisible(self._show_traces)
        self._active_trace = block
        self._trace_blocks.append(block)
        self._add_widget(block)

    def _trace_line(self, block, msg: str):
        if msg.startswith("Tool:") or msg.startswith("Starting:"):
            color, icon = C["accent"], "⚙"
        elif msg.startswith("[Done"):
            color, icon = C["ok"], "✓"
        elif msg.startswith("[") and msg.endswith("]"):
            color, icon = C["motion"], "•"        # status markers (cancel/clear)
        else:
            color, icon = C["text_faint"], "→"
        line = QLabel(f"{icon}  {_esc(msg)}")
        line.setFont(mono_font(9.5))
        line.setWordWrap(True)
        line.setStyleSheet(f"color:{color};background:transparent;")
        block._lines.addWidget(line)

    def _on_toggle_traces(self, checked: bool):
        self._show_traces = checked
        for b in self._trace_blocks:
            b.setVisible(checked)

    # ── intelligence cards ────────────────────────────────────────────────────
    def _add_anomaly_card(self, anomaly_type: str, severity: str, text: str):
        sev = {"critical": C["alert"], "warn": C["motion"]}.get(severity, C["motion"])
        badge = "✖ CRITICAL" if severity == "critical" else "⚠ WARNING"
        html = (f'<span style="color:{sev};font-weight:bold;">{badge} · '
                f'{_esc(anomaly_type)}</span><br>{_esc(text)}')
        actions = _ANOMALY_ACTIONS.get(anomaly_type, [])
        extra = self._action_row(actions) if actions else None
        self._add_widget(self._bubble("IA", html,
                                      datetime.now().strftime("%H:%M:%S"), extra=extra))

    def _action_row(self, actions):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 0)
        h.setSpacing(7)
        for label, action in actions:
            b = _small_btn(label)
            b.clicked.connect(lambda _=False, a=action: self._do_action(a))
            h.addWidget(b)
        h.addStretch(1)
        return row

    def _do_action(self, action: str):
        """Perform an intelligence action link on the controller, and also emit
        ``action_requested`` so a host window can react (e.g. clear its banner)."""
        c = self.controller
        if c is not None:
            try:
                if action == "open_shutter":
                    c.set_gate("open")
                elif action == "close_shutter":
                    c.set_gate("closed")
                elif action == "abort_scan":
                    c.cancel_scan()
                elif action == "move_to_focus" and getattr(c, "client", None):
                    c.client.move_to_focus()
            except Exception as e:                       # surface, don't crash the GUI
                if hasattr(c, "error_occurred"):
                    c.error_occurred.emit(f"Agent action '{action}' failed: {e}")
        self.action_requested.emit(action)

    @staticmethod
    def _recommendation_html(message: dict) -> str:
        subtype = message.get("subtype", "recommendation")
        reason = message.get("reason", "")
        rec = message.get("recommended_center_um", {}) or {}
        offset = message.get("offset_um", {}) or {}
        region = message.get("region", "")
        label = f"💡 RECOMMEND · {subtype}" + (f" [{region}]" if region else "")
        parts = [f'<span style="color:{C["accent"]};font-weight:bold;">{_esc(label)}'
                 f'</span><br>{_esc(reason)}']
        detail = []
        if offset:
            detail.append(f"offset dx={offset.get('x', 0):+.2f}, dy={offset.get('y', 0):+.2f} µm")
        if rec:
            detail.append(f"centre ({rec.get('x', 0):.3f}, {rec.get('y', 0):.3f}) µm")
        if detail:
            parts.append(f'<br><span style="color:{C["text_faint"]};font-size:11px;">'
                         + " &nbsp;|&nbsp; ".join(_esc(d) for d in detail) + "</span>")
        return "".join(parts)

    # ── plan proposal card (forward-looking; see module notes) ────────────────
    def show_proposal(self, plan: dict):
        """Render a human-in-the-loop plan-approval card from structured plan data
        and append it as a task-agent turn.

        The current TaskAgent backend runs autonomously and does not yet emit
        plans, so nothing calls this during normal operation — it is the UI half
        of the "plan approval next" design.  To activate it later, have the agent
        publish ``{"type": "plan_proposal", "plan": {...}}`` through
        ``intelligence_suggestion_received`` (routed here by ``add_suggestion``),
        and implement ``controller.approve_agent_plan(plan)`` /
        ``controller.reject_agent_plan(plan)`` — the buttons already call them when
        present.

        ``plan`` keys: ``title`` (str), ``steps`` (list of {n, what, detail}),
        ``cost`` (str summary).
        """
        self._active_trace = None
        card = self._proposal_card(plan)
        wrap = self._bubble(
            "TA", _esc(plan.get("intro",
                       "Proposed plan below. Nothing has moved yet — the scan queue "
                       "is untouched until you approve.")),
            datetime.now().strftime("%H:%M:%S"), extra=card)
        self._add_widget(wrap)

    def _proposal_card(self, plan: dict):
        card = QFrame()
        card.setObjectName("proposalCard")
        card.setStyleSheet(f"QFrame#proposalCard{{background:#0b1116;"
                           f"border:1px solid {C['border_strong']};border-radius:7px;}}")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        head = QFrame()
        head.setObjectName("proposalHead")
        head.setStyleSheet(f"QFrame#proposalHead{{background:{C['panel_footer']};"
                           f"border:none;border-bottom:1px solid {C['border']};}}")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(13, 9, 13, 9)
        h = _mk_label(plan.get("title", "PROPOSED ACTION").upper())
        h.setObjectName("panelHeading")
        hl.addWidget(h)
        hl.addStretch(1)
        state = _mk_label("AWAITING APPROVAL")
        state.setStyleSheet(f"color:{C['motion']};background:transparent;font-size:11px;")
        hl.addWidget(state)
        cv.addWidget(head)

        bodyw = QWidget()
        bv = QVBoxLayout(bodyw)
        bv.setContentsMargins(13, 12, 13, 12)
        bv.setSpacing(9)
        for i, step in enumerate(plan.get("steps", []), start=1):
            row = QHBoxLayout()
            row.setSpacing(10)
            idx = _mk_label(str(step.get("n", i)), role="monoFaint")
            idx.setFixedWidth(18)
            row.addWidget(idx, 0, Qt.AlignTop)
            row.addWidget(_mk_label(step.get("what", ""), font=sans_font(11.5),
                                    color=C["text_2"]), 1)
            if step.get("detail"):
                d = _mk_label(step["detail"], role="monoFaint")
                row.addWidget(d, 0, Qt.AlignTop)
            bv.addLayout(row)
        if plan.get("cost"):
            rule = QFrame()
            rule.setFixedHeight(1)
            rule.setStyleSheet(f"background:{C['separator']};border:none;")
            bv.addWidget(rule)
            bv.addWidget(_mk_label(plan["cost"], role="monoFaint"))
        cv.addWidget(bodyw)

        actions = QFrame()
        actions.setObjectName("proposalActions")
        actions.setStyleSheet(f"QFrame#proposalActions{{background:{C['panel_footer']};"
                              f"border:none;border-top:1px solid {C['border']};}}")
        al = QHBoxLayout(actions)
        al.setContentsMargins(13, 11, 13, 11)
        al.setSpacing(8)
        approve = QPushButton("Approve && queue")
        approve.setObjectName("beginScan")
        approve.setCursor(Qt.PointingHandCursor)
        approve.clicked.connect(lambda: self._resolve_plan(plan, state, approve, reject, True))
        al.addWidget(approve)
        al.addStretch(1)
        reject = QPushButton("Reject")
        reject.setObjectName("rejectBtn")
        reject.setCursor(Qt.PointingHandCursor)
        reject.clicked.connect(lambda: self._resolve_plan(plan, state, approve, reject, False))
        al.addWidget(reject)
        cv.addWidget(actions)
        return card

    def _resolve_plan(self, plan, state_lbl, approve_btn, reject_btn, approved):
        approve_btn.setEnabled(False)
        reject_btn.setEnabled(False)
        c = self.controller
        if approved:
            state_lbl.setText(f"APPROVED {datetime.now().strftime('%H:%M:%S')}")
            state_lbl.setStyleSheet(f"color:{C['ok']};background:transparent;font-size:11px;")
            if c is not None and hasattr(c, "approve_agent_plan"):
                c.approve_agent_plan(plan)
        else:
            state_lbl.setText("REJECTED")
            state_lbl.setStyleSheet(f"color:{C['alert_text']};background:transparent;font-size:11px;")
            if c is not None and hasattr(c, "reject_agent_plan"):
                c.reject_agent_plan(plan)

    # ── composer / topic actions ──────────────────────────────────────────────
    def _submit(self):
        if self._task_running:
            if self.controller is not None:
                self.controller.cancel_task()
            return
        if self.controller is None:
            return
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.add_user_message(text)
        self.controller.send_agent_query(text)

    def _on_new_topic(self):
        # Clear the transcript widgets (keep the trailing stretch) and reset agent
        # history so the next query starts a fresh session.
        while self._conv.count() > 1:
            item = self._conv.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._trace_blocks.clear()
        self._active_trace = None
        self._conv.insertWidget(0, self._session_divider("new topic"))
        if self.controller is not None:
            self.controller.reset_task_history()

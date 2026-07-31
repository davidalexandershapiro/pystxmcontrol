"""
IntelligenceWidget — GUI panel for the AI agent.

Displays anomaly suggestions and agent responses in a chat-like history.
Each suggestion includes contextual action links that map to instrument commands.
A query input at the bottom lets the operator ask free-form questions.
"""

import time
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Signal, QUrl

from pystxmcontrol.gui.markdown_render import md_to_html, TABLE_STYLESHEET

# ---------------------------------------------------------------------------
# Actions suggested per anomaly type
# ---------------------------------------------------------------------------
_ANOMALY_ACTIONS = {
    "intensity_drop":  [("Open Shutter", "open_shutter"), ("Abort Scan", "abort_scan"), ("Clear Alert", "clear_alert")],
    "intensity_drift": [("Abort Scan", "abort_scan"), ("Clear Alert", "clear_alert")],
    "focus_decline":   [("Move to Focus", "move_to_focus"), ("Clear Alert", "clear_alert")],
    "daq_timeout":     [("Clear Alert", "clear_alert")],
}

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
_C = {
    "critical":      "#ef5350",
    "warn":          "#ffa726",
    "agent":         "#66bb6a",
    "user":          "#42a5f5",
    "recommend":     "#4fc3f7",
    "bg_critical":   "#2a1515",
    "bg_warn":       "#2a1e0a",
    "bg_agent":      "#0d1f0d",
    "bg_user":       "#0d1a2a",
    "bg_recommend":  "#0a1e2a",
    "border":        "#3a3a3a",
    "action_bg":     "#1565c0",
    "action_fg":     "#e3f2fd",
    "text":          "#e0e0e0",
    "ts":            "#888888",
}


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _is_light_theme() -> bool:
    """True when the app is running the light qdarktheme palette.

    The trace colours below are tuned for the dark theme; on a light background the
    pale teal/grey wash out. Detect the theme from the active palette's base-colour
    lightness so the light-theme shades can be darkened. Defaults to dark on failure.
    """
    try:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return False
        return app.palette().base().color().lightnessF() > 0.5
    except Exception:
        return False


# Tool-trace line colours, keyed by (icon, color) role. The dark values are the
# originals; the light values are darkened so they stay legible on a white background
# (the faint pale-teal "Tool:" lines were the reported problem).
_TRACE_COLORS_DARK = {"accent": "#80cbc4", "muted": "#757575", "faint": "#888888"}
_TRACE_COLORS_LIGHT = {"accent": "#00695c", "muted": "#4a4a4a", "faint": "#5a5a5a"}


def _trace_colors() -> dict:
    return _TRACE_COLORS_LIGHT if _is_light_theme() else _TRACE_COLORS_DARK


def _action_link(label: str, action: str) -> str:
    return (
        f'<a href="action://{action}" style="'
        f'color:{_C["action_fg"]}; text-decoration:none; '
        f'background-color:{_C["action_bg"]}; '
        f'padding:1px 7px; border-radius:2px; font-size:11px;">'
        f'{label}</a>'
    )


class IntelligenceWidget(QtWidgets.QWidget):
    """Chat-style panel showing agent suggestions and accepting operator queries.

    Signals
    -------
    query_submitted(str)
        Emitted when the operator submits a query via the input line.
    action_requested(str)
        Emitted when the operator clicks an action link.
        The string is the action identifier, e.g. ``"open_shutter"``.
    """

    query_submitted = Signal(str)
    action_requested = Signal(str)
    cancel_requested = Signal()
    clear_history_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._task_running = False
        self._proposal_active = False   # input is gated until a proposal is selected
        self._setup_ui()
        self._refresh_input_state()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header row: label + Clear button
        header_row = QtWidgets.QHBoxLayout()
        header_row.setSpacing(4)
        header = QtWidgets.QLabel("AI Agent")
        # No text colour, so the label follows the light/dark theme palette.
        header.setStyleSheet("font-size: 13px; font-weight: bold;")
        header_row.addWidget(header)
        header_row.addStretch()
        self._clear_btn = QtWidgets.QPushButton("New Topic")
        self._clear_btn.setFixedWidth(72)
        # Colours come from the active theme's button style; only the compact
        # font size is pinned so the label fits the fixed width.
        self._clear_btn.setStyleSheet("QPushButton { font-size: 10px; }")
        self._clear_btn.setToolTip("Clear conversation history and start a new topic")
        self._clear_btn.clicked.connect(self._on_clear)
        header_row.addWidget(self._clear_btn)
        layout.addLayout(header_row)

        # Message history
        self._browser = QtWidgets.QTextBrowser()
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_anchor_clicked)
        # No background/text colour, so the flow follows the light/dark theme palette.
        self._browser.setStyleSheet(
            "QTextBrowser { border: 1px solid #3a3a3a; font-size: 14px; }"
        )
        # Style the tables/code that Markdown-rendered agent responses emit.
        self._browser.document().setDefaultStyleSheet(TABLE_STYLESHEET)
        layout.addWidget(self._browser, stretch=1)

        # Query input row
        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(4)

        self._query_input = QtWidgets.QLineEdit()
        self._query_input.setPlaceholderText("Describe a goal for the agent…")
        # No background/text colour, so the field follows the light/dark theme palette.
        self._query_input.setStyleSheet(
            "QLineEdit { padding: 4px; border-radius: 3px; font-size: 14px; }"
        )
        self._query_input.returnPressed.connect(self._submit_query)
        input_row.addWidget(self._query_input, stretch=1)

        self._send_btn = QtWidgets.QPushButton("Send")
        self._send_btn.setFixedWidth(55)
        self._send_btn.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: #e3f2fd; "
            "border: none; padding: 4px 8px; border-radius: 3px; }"
            "QPushButton:hover { background-color: #1976d2; }"
            "QPushButton:pressed { background-color: #0d47a1; }"
        )
        self._send_btn.clicked.connect(self._submit_query)
        input_row.addWidget(self._send_btn)

        layout.addLayout(input_row)

    # ------------------------------------------------------------------
    # Public slots
    # ------------------------------------------------------------------

    def add_suggestion(self, message: dict) -> None:
        """Display an incoming agent suggestion (anomaly diagnosis or query response)."""
        msg_type = message.get("type", "")

        if msg_type == "task_recommendation":
            self._append_task_recommendation(message)
            return

        anomaly_type = message.get("anomaly_type", "")
        severity = message.get("severity", "warn")
        text = message.get("suggestion", "")

        if anomaly_type == "user_query":
            self._append_agent_response(text, message.get("query", ""))
        else:
            self._append_anomaly_suggestion(anomaly_type, severity, text)

    def set_proposal_active(self, active: bool) -> None:
        """Enable/disable the agent command input based on proposal selection.

        The input (and Send) are gated until a valid proposal is selected, mirroring the
        rest of the GUI's proposal activation.
        """
        self._proposal_active = bool(active)
        self._refresh_input_state()

    def _refresh_input_state(self) -> None:
        """Apply the combined proposal + running gates to the input and Send button."""
        self._query_input.setEnabled(self._proposal_active and not self._task_running)
        # Send must stay clickable while running (it acts as Stop); otherwise it follows
        # the proposal gate.
        self._send_btn.setEnabled(self._proposal_active or self._task_running)
        if self._task_running:
            self._query_input.setPlaceholderText("Agent is running…")
        elif not self._proposal_active:
            self._query_input.setPlaceholderText("Select a proposal to enable the agent…")
        else:
            self._query_input.setPlaceholderText("Describe a goal for the agent…")

    def set_task_running(self, running: bool) -> None:
        """Switch the Send button to Stop while a task is in flight."""
        self._task_running = running
        if running:
            self._send_btn.setText("Stop")
            self._send_btn.setStyleSheet(
                "QPushButton { background-color: #c62828; color: #ffcdd2; "
                "border: none; padding: 4px 8px; border-radius: 3px; }"
                "QPushButton:hover { background-color: #d32f2f; }"
                "QPushButton:pressed { background-color: #b71c1c; }"
            )
        else:
            self._send_btn.setText("Send")
            self._send_btn.setStyleSheet(
                "QPushButton { background-color: #1565c0; color: #e3f2fd; "
                "border: none; padding: 4px 8px; border-radius: 3px; }"
                "QPushButton:hover { background-color: #1976d2; }"
                "QPushButton:pressed { background-color: #0d47a1; }"
            )
        self._refresh_input_state()

    def add_task_status(self, msg: str) -> None:
        """Display a TaskAgent trace line (tool calls, results, progress)."""
        tc = _trace_colors()
        if msg.startswith("Starting:"):
            color, icon = tc["accent"], "▶"
        elif msg.startswith("Tool:"):
            color, icon = tc["accent"], "⚙"
        elif msg.startswith("  →"):
            color, icon = tc["muted"], ""
        elif msg.startswith("[Done"):
            color, icon = tc["faint"], "✓"
        else:
            color, icon = tc["faint"], ""
        prefix = f"{icon} " if icon else ""
        html = (
            f'<span style="color:{color}; font-size:11px; font-family:monospace;">'
            f'{prefix}{self._escape(msg)}</span>'
        )
        self._browser.append(html)
        self._scroll_to_bottom()

    def add_task_result(self, text: str) -> None:
        """Display the final TaskAgent response as a prominent agent message."""
        self._append_agent_response(text)

    def add_user_message(self, text: str) -> None:
        """Display the operator's query in the history before the response arrives."""
        html = (
            f'<br>'
            f'<div style="border-left:3px solid {_C["user"]}; '
            f'padding:6px 8px; margin:3px 1px;">'
            f'<span style="color:{_C["user"]}; font-size:12px; font-weight:bold;">'
            f'You &nbsp; {_ts()}</span><br>'
            f'<span>{self._escape(text)}</span>'
            f'</div>'
        )
        self._browser.append(html)
        self._scroll_to_bottom()

    # ------------------------------------------------------------------
    # Internal rendering helpers
    # ------------------------------------------------------------------

    def _append_anomaly_suggestion(self, anomaly_type: str, severity: str,
                                   text: str) -> None:
        sev_color = _C.get(severity, _C["warn"])
        badge = f"{'⚠' if severity == 'warn' else '✖'} {severity.upper()}"

        actions = _ANOMALY_ACTIONS.get(anomaly_type, [])
        action_html = ""
        if actions:
            links = "&nbsp;&nbsp;".join(
                _action_link(label, action) for label, action in actions
            )
            action_html = f'<div style="margin-top:5px;">{links}</div>'

        html = (
            f'<br>'
            f'<div style="border-left:3px solid {sev_color}; '
            f'padding:6px 8px; margin:3px 1px;">'
            f'<span style="color:{sev_color}; font-size:12px; font-weight:bold;">'
            f'{badge} &nbsp; {anomaly_type} &nbsp; {_ts()}</span><br>'
            f'<span>{self._escape(text)}</span>'
            f'{action_html}'
            f'</div>'
        )
        self._browser.append(html)
        self._scroll_to_bottom()

    def _append_task_recommendation(self, message: dict) -> None:
        subtype = message.get("subtype", "recommendation")
        reason  = message.get("reason", "")
        rec     = message.get("recommended_center_um", {})
        offset  = message.get("offset_um", {})
        region  = message.get("region", "")

        detail_parts = []
        if offset:
            detail_parts.append(
                f"offset: dx={offset.get('x', 0):+.2f}, "
                f"dy={offset.get('y', 0):+.2f} µm "
                f"(|{offset.get('magnitude', 0):.2f}| µm)"
            )
        if rec:
            detail_parts.append(
                f"recommended centre: ({rec.get('x', 0):.3f}, {rec.get('y', 0):.3f}) µm"
            )
        detail_html = (
            f'<br><span style="color:{_C["ts"]}; font-size:10px;">'
            + " &nbsp;|&nbsp; ".join(self._escape(p) for p in detail_parts)
            + "</span>"
        ) if detail_parts else ""

        label = f"💡 RECOMMEND  {subtype}"
        if region:
            label += f"  [{region}]"

        html = (
            f'<br>'
            f'<div style="border-left:3px solid {_C["recommend"]}; '
            f'padding:6px 8px; margin:3px 1px;">'
            f'<span style="color:{_C["recommend"]}; font-size:12px; font-weight:bold;">'
            f'{label} &nbsp; {_ts()}</span><br>'
            f'<span>{self._escape(reason)}</span>'
            f'{detail_html}'
            f'</div>'
        )
        self._browser.append(html)
        self._scroll_to_bottom()

    def _append_agent_response(self, text: str, query: str = "") -> None:
        html = (
            f'<br>'
            f'<div style="border-left:3px solid {_C["agent"]}; '
            f'padding:6px 8px; margin:3px 1px;">'
            f'<span style="color:{_C["agent"]}; font-size:12px; font-weight:bold;">'
            f'Agent &nbsp; {_ts()}</span><br>'
            f'<div>{md_to_html(text)}</div>'
            f'</div>'
        )
        self._browser.append(html)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        self._browser.verticalScrollBar().setValue(
            self._browser.verticalScrollBar().maximum()
        )

    @staticmethod
    def _escape(text: str) -> str:
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>"))

    # ------------------------------------------------------------------
    # Interaction handlers
    # ------------------------------------------------------------------

    def _on_clear(self) -> None:
        self._browser.clear()
        self.clear_history_requested.emit()

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() == "action":
            self.action_requested.emit(url.host())

    def _submit_query(self) -> None:
        if self._task_running:
            self.cancel_requested.emit()
            return
        if not self._proposal_active:
            return  # gated until a proposal is selected
        text = self._query_input.text().strip()
        if not text:
            return
        self._query_input.clear()
        self.add_user_message(text)
        self.query_submitted.emit(text)

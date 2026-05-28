"""
IntelligenceWidget — GUI panel for the AI agent.

Displays anomaly suggestions and agent responses in a chat-like history.
Each suggestion includes contextual action links that map to instrument commands.
A query input at the bottom lets the operator ask free-form questions.
"""

import time
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import Signal, QUrl

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
        self._setup_ui()

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
        header.setStyleSheet("color: #aaaaaa; font-size: 11px; font-weight: bold;")
        header_row.addWidget(header)
        header_row.addStretch()
        self._clear_btn = QtWidgets.QPushButton("New Topic")
        self._clear_btn.setFixedWidth(72)
        self._clear_btn.setStyleSheet(
            "QPushButton { background-color: #333333; color: #aaaaaa; "
            "border: 1px solid #555555; padding: 2px 6px; border-radius: 3px; font-size: 10px; }"
            "QPushButton:hover { background-color: #444444; color: #cccccc; }"
        )
        self._clear_btn.setToolTip("Clear conversation history and start a new topic")
        self._clear_btn.clicked.connect(self._on_clear)
        header_row.addWidget(self._clear_btn)
        layout.addLayout(header_row)

        # Message history
        self._browser = QtWidgets.QTextBrowser()
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_anchor_clicked)
        self._browser.setStyleSheet(
            "QTextBrowser { background-color: #1e1e1e; border: 1px solid #3a3a3a; "
            "color: #e0e0e0; font-size: 12px; }"
        )
        layout.addWidget(self._browser, stretch=1)

        # Query input row
        input_row = QtWidgets.QHBoxLayout()
        input_row.setSpacing(4)

        self._query_input = QtWidgets.QLineEdit()
        self._query_input.setPlaceholderText("Describe a goal for the agent…")
        self._query_input.setStyleSheet(
            "QLineEdit { background-color: #2a2a2a; color: #e0e0e0; "
            "border: 1px solid #3a3a3a; padding: 4px; border-radius: 3px; }"
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

    def set_task_running(self, running: bool) -> None:
        """Switch the Send button to Stop while a task is in flight."""
        self._task_running = running
        self._query_input.setEnabled(not running)
        if running:
            self._send_btn.setText("Stop")
            self._send_btn.setStyleSheet(
                "QPushButton { background-color: #c62828; color: #ffcdd2; "
                "border: none; padding: 4px 8px; border-radius: 3px; }"
                "QPushButton:hover { background-color: #d32f2f; }"
                "QPushButton:pressed { background-color: #b71c1c; }"
            )
            self._query_input.setPlaceholderText("Agent is running…")
        else:
            self._send_btn.setText("Send")
            self._send_btn.setStyleSheet(
                "QPushButton { background-color: #1565c0; color: #e3f2fd; "
                "border: none; padding: 4px 8px; border-radius: 3px; }"
                "QPushButton:hover { background-color: #1976d2; }"
                "QPushButton:pressed { background-color: #0d47a1; }"
            )
            self._query_input.setPlaceholderText("Describe a goal for the agent…")

    def add_task_status(self, msg: str) -> None:
        """Display a TaskAgent trace line (tool calls, results, progress)."""
        if msg.startswith("Starting:"):
            color, icon = "#80cbc4", "▶"
        elif msg.startswith("Tool:"):
            color, icon = "#80cbc4", "⚙"
        elif msg.startswith("  →"):
            color, icon = "#757575", ""
        elif msg.startswith("[Done"):
            color, icon = "#888888", "✓"
        else:
            color, icon = "#888888", ""
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
            f'<div style="background-color:{_C["bg_user"]}; '
            f'border-left:3px solid {_C["user"]}; '
            f'padding:6px 8px; margin:3px 1px;">'
            f'<span style="color:{_C["user"]}; font-size:10px; font-weight:bold;">'
            f'You &nbsp; {_ts()}</span><br>'
            f'<span style="color:{_C["text"]};">{self._escape(text)}</span>'
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
        bg_color = _C.get(f"bg_{severity}", _C["bg_warn"])
        badge = f"{'⚠' if severity == 'warn' else '✖'} {severity.upper()}"

        actions = _ANOMALY_ACTIONS.get(anomaly_type, [])
        action_html = ""
        if actions:
            links = "&nbsp;&nbsp;".join(
                _action_link(label, action) for label, action in actions
            )
            action_html = f'<div style="margin-top:5px;">{links}</div>'

        html = (
            f'<div style="background-color:{bg_color}; '
            f'border-left:3px solid {sev_color}; '
            f'padding:6px 8px; margin:3px 1px;">'
            f'<span style="color:{sev_color}; font-size:10px; font-weight:bold;">'
            f'{badge} &nbsp; {anomaly_type} &nbsp; {_ts()}</span><br>'
            f'<span style="color:{_C["text"]};">{self._escape(text)}</span>'
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
            f'<div style="background-color:{_C["bg_recommend"]}; '
            f'border-left:3px solid {_C["recommend"]}; '
            f'padding:6px 8px; margin:3px 1px;">'
            f'<span style="color:{_C["recommend"]}; font-size:10px; font-weight:bold;">'
            f'{label} &nbsp; {_ts()}</span><br>'
            f'<span style="color:{_C["text"]};">{self._escape(reason)}</span>'
            f'{detail_html}'
            f'</div>'
        )
        self._browser.append(html)
        self._scroll_to_bottom()

    def _append_agent_response(self, text: str, query: str = "") -> None:
        html = (
            f'<div style="background-color:{_C["bg_agent"]}; '
            f'border-left:3px solid {_C["agent"]}; '
            f'padding:6px 8px; margin:3px 1px;">'
            f'<span style="color:{_C["agent"]}; font-size:10px; font-weight:bold;">'
            f'Agent &nbsp; {_ts()}</span><br>'
            f'<span style="color:{_C["text"]};">{self._escape(text)}</span>'
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
        text = self._query_input.text().strip()
        if not text:
            return
        self._query_input.clear()
        self.add_user_message(text)
        self.query_submitted.emit(text)

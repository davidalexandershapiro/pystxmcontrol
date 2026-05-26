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
    "critical":   "#ef5350",
    "warn":       "#ffa726",
    "agent":      "#66bb6a",
    "user":       "#42a5f5",
    "bg_critical":"#2a1515",
    "bg_warn":    "#2a1e0a",
    "bg_agent":   "#0d1f0d",
    "bg_user":    "#0d1a2a",
    "border":     "#3a3a3a",
    "action_bg":  "#1565c0",
    "action_fg":  "#e3f2fd",
    "text":       "#e0e0e0",
    "ts":         "#888888",
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header label
        header = QtWidgets.QLabel("AI Agent")
        header.setStyleSheet("color: #aaaaaa; font-size: 11px; font-weight: bold;")
        layout.addWidget(header)

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
        self._query_input.setPlaceholderText("Ask the agent…")
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
        anomaly_type = message.get("anomaly_type", "")
        severity = message.get("severity", "warn")
        text = message.get("suggestion", "")

        if anomaly_type == "user_query":
            self._append_agent_response(text, message.get("query", ""))
        else:
            self._append_anomaly_suggestion(anomaly_type, severity, text)

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

    def _on_anchor_clicked(self, url: QUrl) -> None:
        if url.scheme() == "action":
            self.action_requested.emit(url.host())

    def _submit_query(self) -> None:
        text = self._query_input.text().strip()
        if not text:
            return
        self._query_input.clear()
        self.add_user_message(text)
        self.query_submitted.emit(text)

#!/usr/bin/env python3
"""
Standalone Browser + Analysis application.

Combines the data-file browser and the stack analysis widget in a single
window without requiring the full STXM control server.  Selecting a file
in the Browser tab automatically loads it in the Analysis tab.
"""

import sys
import os
import json

import qdarktheme
from PySide6 import QtWidgets, QtCore

from pystxmcontrol.gui.data_browser_widget import DataBrowserWidget
from pystxmcontrol.gui.analysis_widget import Analysis2Widget


def _load_gui_theme() -> str:
    try:
        cfg_path = os.path.join(sys.prefix, 'pystxmcontrol_cfg/main.json')
        with open(cfg_path) as f:
            cfg = json.load(f)
        return cfg.get("gui", {}).get("theme", "light")
    except Exception:
        return "light"


class BrowserAnalysisWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("STXM Browser & Analysis")
        self.resize(1400, 900)

        tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(tabs)

        # ── Browser tab ───────────────────────────────────────────────────────
        self.browser = DataBrowserWidget()
        tabs.addTab(self.browser, "Browser")

        # ── Analysis tab ─────────────────────────────────────────────────────
        self.analysis = Analysis2Widget(parent=self)
        tabs.addTab(self.analysis, "Analysis")

        self._tabs = tabs

        # When a file is selected in the browser, load it in the analysis tab.
        self.browser.file_selected.connect(self._on_file_selected)

    def _on_file_selected(self, filepath: str):
        self.analysis.load_file(filepath)
        self._tabs.setCurrentWidget(self.analysis)


def main():
    app = QtWidgets.QApplication(sys.argv)
    theme = _load_gui_theme()
    app.setStyleSheet(qdarktheme.load_stylesheet(theme))

    window = BrowserAnalysisWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

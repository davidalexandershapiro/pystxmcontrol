#!/usr/bin/env python3
"""
Application entry point using MVC architecture.
This demonstrates how to use the refactored MVC components.
"""

import sys
import os
import json
import faulthandler
faulthandler.enable()   # print Python traceback to stderr on SIGSEGV/SIGFPE

import qdarktheme
from PySide6.QtWidgets import QApplication
from pystxmcontrol.gui.mainwindow_mvc import MainWindowMVC


def _load_gui_theme():
    try:
        cfg_path = os.path.join(sys.prefix, 'pystxmcontrol_cfg/main.json')
        with open(cfg_path) as f:
            cfg = json.load(f)
        return cfg.get("gui", {}).get("theme", "light")
    except Exception:
        return "light"


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    app.setStyleSheet(qdarktheme.load_stylesheet(_load_gui_theme()))

    # Create and show the main window
    window = MainWindowMVC()
    window.show()

    # Start the application event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
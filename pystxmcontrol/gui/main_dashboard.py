#!/usr/bin/env python3
"""Standalone entry point for the acquisition dashboard main window.

Run with:

    python pystxmcontrol/gui/main_dashboard.py            # connect to server if present
    python pystxmcontrol/gui/main_dashboard.py --offline  # force placeholder mode

By default the window tries to connect to the live server (via MainController)
and subscribe to its signals; if no server answers on the command port it falls
back automatically to placeholder mode.  ``--offline`` skips the probe entirely.

The window carries its own stylesheet (dashboard_theme.build_stylesheet), so it
does NOT load qdarktheme — the design is a bespoke dark palette.
"""

import sys
import os
import argparse

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from pystxmcontrol.gui.mainwindow_dashboard import MainWindowDashboard

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")


def main():
    parser = argparse.ArgumentParser(description="STXM Control acquisition dashboard")
    parser.add_argument("--offline", action="store_true",
                        help="run in placeholder mode without contacting the server")
    args, _ = parser.parse_known_args()

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join(_ICONS_DIR, "pystxmcontrol_icon.png")))
    app.setApplicationName("STXM Control — Acquisition")
    window = MainWindowDashboard(live=not args.offline)
    window.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

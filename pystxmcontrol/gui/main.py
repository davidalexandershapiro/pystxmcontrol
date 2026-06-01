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
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt
from pystxmcontrol.gui.mainwindow_mvc import MainWindowMVC

_ICONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'icons'))


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
    app.setWindowIcon(QIcon(os.path.join(_ICONS_DIR, 'pystxmcontrol_icon.png')))
    app.setDesktopFileName('pystxmcontrol')

    splash = QSplashScreen(
        QPixmap(os.path.join(_ICONS_DIR, 'pystxmcontrol_splash.png')),
        Qt.WindowStaysOnTopHint,
    )
    splash.show()
    splash.raise_()
    for i in range(10000):
        app.processEvents()
    splash.repaint()

    window = MainWindowMVC()
    # Safety net: catches any exit path not covered by closeEvent (e.g. SIGTERM)
    app.aboutToQuit.connect(window.controller.cleanup)
    window.show()
    splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
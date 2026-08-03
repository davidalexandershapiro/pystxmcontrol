#!/usr/bin/env python3
"""
Application entry point using MVC architecture.
This demonstrates how to use the refactored MVC components.
"""

import sys
import os
import json
import logging
import faulthandler
faulthandler.enable()   # print Python traceback to stderr on SIGSEGV/SIGFPE

# Surface INFO-level logs (e.g. TaskAgent init diagnostics) to the terminal. Without this,
# the GUI process has no logging handler, so only WARNING+ reach stderr via lastResort.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

import qdarktheme
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QIcon, QPixmap, QFont
from PySide6.QtCore import Qt
from pystxmcontrol.gui.mainwindow_mvc import MainWindowMVC

_ICONS_DIR = os.path.join(os.path.dirname(__file__), 'icons')

# Concrete sans-serif families, most-preferred first.  We deliberately avoid the
# generic "Sans Serif"/"Arial" aliases: on some systems fontconfig resolves those
# to a serif face (e.g. FreeSerif), which is what makes the whole GUI look serif
# after a font/system update.  Naming real families sidesteps that mapping.
_SANS_FAMILIES = ["DejaVu Sans", "Noto Sans", "Liberation Sans",
                  "Cantarell", "Ubuntu", "Helvetica"]

# Default scale applied to the inherited default point size when the config
# does not specify one (0.85 == -15%).
_DEFAULT_FONT_SCALE = 0.85


def _apply_sans_font(app, scale=_DEFAULT_FONT_SCALE):
    """Force a sans-serif application font, overriding a broken generic alias.

    Widgets that set their own font (e.g. the monospace config/logbook editors)
    are unaffected — this only changes the inherited default.

    The default point size is scaled by ``scale``: after recent font/system
    changes the inherited size comes through abnormally large, cutting off some
    labels and button text.
    """
    font = app.font()
    size = font.pointSizeF()
    if size > 0:
        font.setPointSizeF(size * scale)
    elif font.pixelSize() > 0:                   # font defined in pixels
        font.setPixelSize(max(1, round(font.pixelSize() * scale)))
    font.setFamilies(_SANS_FAMILIES)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)


def _load_gui_cfg():
    """Return the ``gui`` section of the runtime main.json (empty on failure)."""
    try:
        cfg_path = os.path.join(sys.prefix, 'pystxmcontrol_cfg/main.json')
        with open(cfg_path) as f:
            cfg = json.load(f)
        return cfg.get("gui", {})
    except Exception:
        return {}


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    gui_cfg = _load_gui_cfg()
    app.setStyleSheet(qdarktheme.load_stylesheet(gui_cfg.get("theme", "light")))
    _apply_sans_font(app, gui_cfg.get("font_scale", _DEFAULT_FONT_SCALE))
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
    window.show()
    splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
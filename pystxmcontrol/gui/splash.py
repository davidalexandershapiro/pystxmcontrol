"""Startup splash screen, shared by both GUI entry points.

``main.py`` (the MVC main window) and ``main_dashboard.py`` (the acquisition
dashboard) both show the same splash while their main window is built — window
construction probes the control server, so there is a visible delay to cover.
"""

import os
import time

from PySide6.QtWidgets import QSplashScreen
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "icons")
_SPLASH_PNG = os.path.join(_ICONS_DIR, "pystxmcontrol_splash.png")

# How long to pump the event loop so the pixmap is actually on screen before the
# caller starts building its (slow, event-loop-blocking) main window.
_PAINT_SETTLE_SECONDS = 0.15


def show_splash(app):
    """Show the splash screen and return it, or None if the image is unavailable.

    Returns None rather than raising when the pixmap is missing — an absent icon
    (e.g. package data dropped by a non-editable install) must not stop the GUI
    from starting.  Callers pass the result straight to :func:`finish_splash`,
    which tolerates None.
    """
    pixmap = QPixmap(_SPLASH_PNG)
    if pixmap.isNull():
        return None

    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
    splash.show()
    splash.raise_()
    splash.repaint()

    # Building the main window blocks the event loop, so the splash must be fully
    # painted before we return.  A bounded spin does that deterministically.
    deadline = time.monotonic() + _PAINT_SETTLE_SECONDS
    while time.monotonic() < deadline:
        app.processEvents()
    return splash


def finish_splash(splash, window):
    """Close *splash* once *window* is up.  No-op when *splash* is None."""
    if splash is not None:
        splash.finish(window)

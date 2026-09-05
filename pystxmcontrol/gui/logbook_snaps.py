"""Sizing and registering logbook snapshots for a QTextBrowser card view.

Two panels render the same logbook into a QTextDocument — ``LogbookWidget`` (the MVC
main window) and ``DashboardLogbookPanel`` (the dashboard app) — and they had grown
independent copies of this logic, so a fix to one silently missed the other.  It lives
here once; the panels differ only in their card padding, which is a parameter.

A snapshot is one of two things, and they want opposite treatment:

* a SCAN image, stored at the scan's own resolution (xPoints x yPoints, so 100-500 px).
  It is a pixel grid with no text, and reaching the card width means upscaling it.
* a RENDERED FIGURE — a motor-position plot, the NNMF cluster map + spectra panel.
  Its axis labels and tick text were drawn to be read at 1:1, so downscaling attacks
  exactly the part that has to stay legible.

Native pixel width tells them apart: every figure this codebase saves is >= 640 px and
usually ~1200, and no scan grid comes close.  That is a safer test than aspect ratio,
which was the old proxy — it misread the two-panel motor plot (figsize 12x10) as a
square scan snapshot and showed it at a third of its size.
"""

import os

from PySide6 import QtCore, QtGui


# Native width (px) at or above which a snapshot is a figure rather than a scan image.
FIGURE_MIN_PX = 600


def snap_display_width(browser, path: str, base: int = 360, pad: int = 24) -> int:
    """Choose a card display width (logical px) for the snapshot at *path*.

    A figure is shown at its native width, a scan snapshot at *base* — except a
    wide-aspect one, which gets up to double so a long thin strip is not squeezed.
    Everything is capped to the browser viewport (less *pad* for the card border and
    padding) so nothing forces a horizontal scrollbar.
    """
    img = QtGui.QImage(path)
    if img.isNull() or img.height() == 0:
        return base
    avail = browser.viewport().width() - pad
    if img.width() >= FIGURE_MIN_PX:            # a figure: show its own pixels
        return max(base, min(img.width(), avail))
    if img.width() / img.height() < 1.6:        # square/portrait — normal width
        return base
    return max(base, min(base * 2, avail)) if avail > base else base


def snap_resource(browser, path: str, eid: str, width: int = 360) -> str | None:
    """Scale a snapshot to *width* and register it as a document image resource.

    Upscaling a scan grid uses nearest-neighbour snapped to an integer pixel factor, so
    the discrete scan pixels stay crisp and uniform — no interpolation / blur.  Anything
    wider than the card is instead downscaled with a smooth transform, which keeps fine
    plot and axis text legible.  A figure is never upscaled: on a hi-dpi screen the card
    width can exceed its pixels, and its text is sharpest left at 1:1 — the dpr tag then
    lays it out smaller than asked for, which snap_display_width's viewport cap already
    tolerates.

    The document is handed a 1:1, dpr-tagged image either way, so its own
    width-attribute scaling (nearest-neighbour, and it would mangle plot text) never
    re-touches it.  Call before setHtml() so the document resolves the URL.
    """
    img = QtGui.QImage(path)
    if img.isNull():
        return None
    dpr = browser.devicePixelRatioF() or 1.0
    target_px = max(1, round(width * dpr))
    src_w = img.width()
    if src_w < FIGURE_MIN_PX and target_px > src_w:   # upscale a scan grid → crisp pixels
        factor = max(1, target_px // src_w)     # floor: never exceed the card width
        img = img.scaledToWidth(src_w * factor, QtCore.Qt.FastTransformation)
    elif target_px < src_w:                     # downscale → keep figures legible
        img = img.scaledToWidth(target_px, QtCore.Qt.SmoothTransformation)
    img.setDevicePixelRatio(dpr)   # lay out at native logical px
    url = QtCore.QUrl(f"snap://{eid or os.path.basename(path)}")
    browser.document().addResource(QtGui.QTextDocument.ImageResource, url, img)
    return url.toString()

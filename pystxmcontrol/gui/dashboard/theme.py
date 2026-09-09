"""Design tokens, stylesheet, and small custom-painted widgets for the
acquisition dashboard main window (``mainwindow.py``).

The palette and typography here transcribe the design handoff in
``design_handoff_stxm_main_window/README.md`` verbatim.  Numbers are always
rendered in the monospace family — the design forbids the proportional face for
any numeric value.

Fonts: the design specifies IBM Plex Sans / IBM Plex Mono.  Those are not
installed on the target machines, so we fall back to DejaVu Sans / DejaVu Sans
Mono, which are present and metrically reasonable.  If IBM Plex is ever
installed the families below pick it up first.
"""

from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtWidgets import QWidget

import numpy as np


# ── Color tokens (README §"Design tokens") ─────────────────────────────────
C = {
    "canvas":       "#0b0d10",  # window background
    "panel":        "#12161b",  # cards, header
    "panel_footer": "#0f1317",  # card footers, right rail
    "well":         "#0d1116",  # inputs, segmented-control wells
    "plot_ground":  "#07090b",  # image area, plot backgrounds
    "border":       "#22282f",  # card + panel borders
    "border_strong":"#2c3a48",  # interactive control borders
    "separator":    "#191e24",  # list rows
    "text":         "#e6ebef",  # values, headings
    "text_2":       "#cbd5dd",  # button labels
    "text_muted":   "#8b97a3",  # panel headings, inactive tabs
    "text_dim":     "#7c8894",  # field labels
    "text_faint":   "#5f6b77",  # metadata, log
    "accent":       "#5fd4d6",  # active state, ROI, progress, spectrum
    "accent_fill":  "#144e50",  # begin-scan fill
    "accent_brdr":  "#2b7b7d",  # begin-scan border
    "ok":           "#8ee06a",  # shutter open, counter trace, healthy
    "motion":       "#ffc45e",  # motors in motion
    "warn":         "#ffc45e",
    "alert":        "#ff6b5e",  # live dot
    "alert_text":   "#ff9a90",  # destructive text
    "alert_fill":   "#2a1618",  # destructive fill
    "alert_brdr":   "#5c2a2c",  # destructive border
    "inactive_bar": "#3c4a58",  # settled motor travel bars
    "active_hi":    "#1d2833",  # active pill / tab bg
}

# Font families, most-preferred first.
SANS = "'IBM Plex Sans', 'DejaVu Sans', 'Noto Sans', 'Liberation Sans', sans-serif"
MONO = "'IBM Plex Mono', 'DejaVu Sans Mono', 'Liberation Mono', monospace"

# Concrete family names for QFont (stylesheet families don't reach QPainter).
SANS_FAMILY = "DejaVu Sans"
MONO_FAMILY = "DejaVu Sans Mono"


def mono_font(size_pt=10, weight=QFont.Normal):
    f = QFont(MONO_FAMILY)
    f.setPointSizeF(size_pt)
    f.setWeight(weight)
    return f


def sans_font(size_pt=10, weight=QFont.Normal):
    f = QFont(SANS_FAMILY)
    f.setPointSizeF(size_pt)
    f.setWeight(weight)
    return f


def build_stylesheet():
    """Return the application-wide QSS for the dashboard window.

    Widget roles are targeted by ``objectName`` (``#name``) and by dynamic
    ``property`` selectors (``[role="..."]``).  Keeping this in one place mirrors
    the single design-token table in the handoff.
    """
    return f"""
    /* ── base ─────────────────────────────────────────────── */
    QWidget {{
        background: {C['canvas']};
        color: {C['text']};
        font-family: {SANS};
        font-size: 13px;
    }}
    QToolTip {{
        background: {C['panel']}; color: {C['text']};
        border: 1px solid {C['border_strong']};
    }}

    /* ── cards & panels ───────────────────────────────────── */
    QFrame#card {{
        background: {C['panel']};
        border: 1px solid {C['border']};
        border-radius: 8px;
    }}
    QFrame#cardHeader {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {C['border']};
    }}
    QFrame#cardFooter {{
        background: {C['panel_footer']};
        border: none;
        border-top: 1px solid {C['border']};
    }}
    QLabel#panelHeading {{
        color: {C['text_muted']};
        font-size: 11px; font-weight: 600;
        letter-spacing: 2px;
    }}
    QLabel#panelNote {{
        color: {C['text_faint']};
        font-family: {MONO};
        font-size: 10px;
    }}
    QFrame#header {{
        background: {C['panel']};
        border: none;
        border-bottom: 1px solid {C['border']};
    }}
    QFrame#rowSep {{ background: transparent; border: none;
                     border-bottom: 1px solid {C['separator']}; }}

    /* ── labels ───────────────────────────────────────────── */
    QLabel[role="fieldLabel"] {{
        color: {C['text_dim']}; font-size: 10px; letter-spacing: 1px;
    }}
    QLabel[role="microLabel"] {{
        color: {C['text_dim']}; font-size: 9px; letter-spacing: 1px;
    }}
    QLabel[role="value"]      {{ font-family: {MONO}; color: {C['text']}; }}
    QLabel[role="valueBig"]   {{ font-family: {MONO}; color: {C['text']};
                                 font-size: 16px; font-weight: 500; }}
    QLabel[role="mono"]       {{ font-family: {MONO}; color: {C['text_2']}; }}
    QLabel[role="monoFaint"]  {{ font-family: {MONO}; color: {C['text_faint']};
                                 font-size: 10px; }}
    QLabel[role="accent"]     {{ font-family: {MONO}; color: {C['accent']}; }}
    QLabel[role="ok"]         {{ font-family: {MONO}; color: {C['ok']}; }}
    QLabel[role="motion"]     {{ font-family: {MONO}; color: {C['motion']}; }}

    /* ── inputs ───────────────────────────────────────────── */
    QLineEdit {{
        background: {C['well']};
        border: 1px solid {C['border_strong']};
        border-radius: 4px;
        padding: 6px 8px;
        font-family: {MONO}; font-size: 12px;
        color: {C['text']};
        selection-background-color: {C['accent']};
    }}
    QLineEdit:focus {{ border: 1px solid {C['accent']}; }}
    QLineEdit[derived="true"] {{
        border: 1px solid {C['border']};
        color: {C['text_muted']};
    }}
    QLineEdit[derived="true"]:focus {{ border: 1px solid {C['border']}; }}

    QComboBox {{
        background: {C['well']};
        border: 1px solid {C['border_strong']};
        border-radius: 5px;
        padding: 6px 9px;
        color: {C['text']};
        font-weight: 500;
    }}
    QComboBox:focus {{ border: 1px solid {C['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {C['well']};
        border: 1px solid {C['border_strong']};
        selection-background-color: {C['active_hi']};
        color: {C['text']};
    }}

    /* ── buttons ──────────────────────────────────────────── */
    QPushButton {{
        background: #161b21;
        border: 1px solid {C['border_strong']};
        border-radius: 5px;
        padding: 6px 11px;
        color: {C['text_2']};
        font-weight: 500; font-size: 12px;
    }}
    QPushButton:hover {{ border: 1px solid {C['accent']}; color: #ffffff; }}
    QPushButton:pressed {{ background: {C['active_hi']}; }}

    QPushButton#beginScan {{
        background: {C['accent_fill']};
        border: 1px solid {C['accent_brdr']};
        color: #d6fbfc;
        border-radius: 6px; padding: 11px; font-size: 13px; font-weight: 600;
    }}
    QPushButton#beginScan:hover {{ border: 1px solid {C['accent']}; color: #ffffff; }}
    QPushButton#cancelScan {{
        background: {C['alert_fill']};
        border: 1px solid {C['alert_brdr']};
        color: {C['alert_text']};
        border-radius: 6px; padding: 11px; font-size: 13px; font-weight: 600;
    }}
    QPushButton#cancelScan:hover {{ background: #3a1c1f; color: #ffb8b0; }}
    QPushButton#stopAll {{
        background: {C['alert_fill']};
        border: 1px solid {C['alert_brdr']};
        color: {C['alert_text']};
        font-weight: 600;
    }}
    QPushButton#stopAll:hover {{ background: #3a1c1f; color: #ffb8b0;
                                 border: 1px solid {C['alert_brdr']}; }}
    QPushButton[role="jog"] {{
        font-family: {MONO}; padding: 5px 0; font-size: 13px;
    }}

    /* proposal-card reject (destructive, outline) */
    QPushButton#rejectBtn {{
        background: transparent; border: 1px solid #3a2830;
        color: #e08b8b;
        border-radius: 6px; padding: 8px 16px; font-weight: 500;
    }}
    QPushButton#rejectBtn:hover {{ border: 1px solid #7d3b3b; color: #ffb4b4; }}

    /* segmented-control pill buttons (checkable) */
    QPushButton[role="pill"] {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 5px;
        padding: 5px 10px;
        color: {C['text_muted']};
        font-family: {MONO}; font-size: 11px; font-weight: 500;
    }}
    QPushButton[role="pill"]:hover {{ color: {C['text']}; border: 1px solid transparent; }}
    QPushButton[role="pill"]:checked {{
        background: {C['active_hi']};
        border: 1px solid {C['border_strong']};
        color: #ffffff;
    }}

    /* app-nav tab buttons in header */
    QPushButton[role="navtab"] {{
        background: transparent; border: 1px solid transparent;
        border-radius: 5px; padding: 7px 16px;
        color: {C['text_muted']}; font-size: 13px; font-weight: 500;
    }}
    QPushButton[role="navtab"]:hover {{ background: #161b21; color: {C['text']}; }}
    QPushButton[role="navtab"]:checked {{
        background: {C['active_hi']}; border: 1px solid {C['border_strong']};
        color: {C['text']};
    }}

    /* config sub-tabs (Spatial/Energy/Detector): underline style */
    QPushButton[role="subtab"] {{
        background: transparent; border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0px; padding: 8px 14px;
        color: {C['text_muted']}; font-size: 12px; font-weight: 500;
    }}
    QPushButton[role="subtab"]:hover {{ color: {C['text']}; }}
    QPushButton[role="subtab"]:checked {{
        background: {C['active_hi']};
        border-bottom: 2px solid {C['accent']};
        color: #ffffff;
    }}

    QPushButton[role="preset"] {{ padding: 6px 10px; font-size: 11px; }}
    QPushButton[role="small"]  {{ padding: 6px 11px; font-size: 11px; }}

    /* mode toggle in header */
    QPushButton#modeToggle {{
        background: {C['active_hi']}; border: 1px solid {C['border_strong']};
        color: {C['text_2']}; border-radius: 5px; padding: 6px 13px; font-size: 12px;
    }}
    QPushButton#modeToggle:hover {{ border: 1px solid #40566b; color: {C['text']}; }}

    /* ── checkboxes ───────────────────────────────────────── */
    QCheckBox {{ color: {C['text_2']}; font-size: 12px; spacing: 6px; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 3px;
        border: 1px solid {C['border_strong']}; background: {C['well']}; }}
    QCheckBox::indicator:checked {{ background: {C['accent']};
        border: 1px solid {C['accent']}; }}

    /* ── scrollbars ───────────────────────────────────────── */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {C['border_strong']};
        border-radius: 5px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: #3a4b5c; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    /* ── segmented well container ─────────────────────────── */
    QFrame[role="pillWell"] {{
        background: {C['well']};
        border: 1px solid {C['border']};
        border-radius: 5px;
    }}
    """


# ── colormaps (control points transcribed from the mock) ───────────────────
_CMAP_STOPS = {
    "gray":    [(0, 0, 0), (255, 255, 255)],
    "viridis": [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)],
    "inferno": [(0, 0, 4), (87, 16, 110), (188, 55, 84), (249, 142, 9), (252, 255, 164)],
}


def make_lut(name, n=256):
    """Return an (n, 3) uint8 LUT interpolated from the mock's colour stops."""
    stops = np.array(_CMAP_STOPS[name], dtype=float)
    xs = np.linspace(0, 1, len(stops))
    grid = np.linspace(0, 1, n)
    lut = np.stack([np.interp(grid, xs, stops[:, c]) for c in range(3)], axis=1)
    return lut.astype(np.uint8)


# ROI outline colours are picked to stand OUT from the image colormap (a hue the
# LUT itself never contains), so boxes stay legible on any background.  Returns
# (region_color, spectrum_color).
_ROI_COLORS = {
    "gray":    ("#ff3b30", "#37d7ff"),   # red + cyan on grayscale (red = default)
    "viridis": ("#ff5db1", "#ff6b3f"),   # magenta + red-orange (viridis has none)
    "inferno": ("#37d7ff", "#4dff9e"),   # cyan + spring-green (inferno has none)
}


def roi_colors(cmap):
    """(region_color, spectrum_color) that contrast the given colormap."""
    return _ROI_COLORS.get(cmap, _ROI_COLORS["gray"])


# ── small custom-painted widgets ───────────────────────────────────────────
class TravelBar(QWidget):
    """3px travel-range bar under a motor value.  ``frac`` in [0,1];
    amber when moving, else the settled inactive colour."""

    def __init__(self, frac=0.5, moving=False, parent=None):
        super().__init__(parent)
        self._frac = frac
        self._moving = moving
        self.setFixedHeight(3)

    def set_state(self, frac, moving):
        self._frac = max(0.0, min(1.0, frac))
        self._moving = moving
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C["well"]))
        fill = QColor(C["motion"] if self._moving else C["inactive_bar"])
        w = int(self.width() * self._frac)
        p.fillRect(0, 0, w, self.height(), fill)
        p.end()


class ProgressBar(QWidget):
    """8px progress bar: well track, accent fill, 1px border, radius 4."""

    def __init__(self, frac=0.0, parent=None):
        super().__init__(parent)
        self._frac = frac
        self.setFixedHeight(8)

    def set_frac(self, frac):
        self._frac = max(0.0, min(1.0, frac))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(QColor(C["border"]), 1))
        p.setBrush(QBrush(QColor(C["well"])))
        p.drawRoundedRect(r, 4, 4)
        if self._frac > 0:
            fr = QRectF(1, 1, (self.width() - 2) * self._frac, self.height() - 2)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(C["accent"])))
            p.drawRoundedRect(fr, 3, 3)
        p.end()


class EnergyRegionStrip(QWidget):
    """Energy-region strip: each region a translucent cyan band with a tick per
    energy point.  ``regions`` is a list of dicts: {start, stop, n, active}.

    Clicking a band emits ``region_clicked`` with the region's list index."""

    region_clicked = Signal(int)

    def __init__(self, regions=None, parent=None):
        super().__init__(parent)
        self._regions = regions or []
        self.setMinimumHeight(56)
        self.setCursor(Qt.PointingHandCursor)

    def set_regions(self, regions):
        self._regions = regions
        self.update()

    def _bounds(self):
        lo = min(r["start"] for r in self._regions)
        hi = max(r["stop"] for r in self._regions)
        return lo, hi, max(1e-9, hi - lo)

    def mousePressEvent(self, ev):
        if not self._regions:
            return
        lo, hi, span = self._bounds()
        w = self.width()
        e = lo + (ev.position().x() - 1) / max(1, w - 2) * span
        # nearest region whose [start, stop] contains e, else nearest by centre
        for i, r in enumerate(self._regions):
            if min(r["start"], r["stop"]) <= e <= max(r["start"], r["stop"]):
                self.region_clicked.emit(i)
                return
        i = min(range(len(self._regions)),
                key=lambda j: abs((self._regions[j]["start"]
                                   + self._regions[j]["stop"]) / 2 - e))
        self.region_clicked.emit(i)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(C["well"]))
        if not self._regions:
            p.end()
            return
        lo, hi, span = self._bounds()
        w, h = self.width(), self.height()

        def x_of(e):
            return (e - lo) / span * (w - 2) + 1

        for r in self._regions:
            x0, x1 = x_of(r["start"]), x_of(r["stop"])
            band = QColor(C["accent"])
            band.setAlphaF(0.14 if r.get("active") else 0.06)
            p.fillRect(QRectF(x0, 2, x1 - x0, h - 4), band)
            tick = QColor(C["accent"] if r.get("active") else "#3c7a7c")
            p.setPen(QPen(tick, 2))
            n = max(1, r["n"])
            for i in range(n):
                ex = r["start"] + (r["stop"] - r["start"]) * (i / max(1, n - 1))
                x = x_of(ex)
                p.drawLine(int(x), 4, int(x), h - 4)
        p.end()


class HistColorBar(QWidget):
    """Image right-rail: a right-to-left histogram beside a vertical colorbar
    rendered from the active LUT.  Static placeholder content for the skeleton."""

    def __init__(self, lut_name="gray", parent=None):
        super().__init__(parent)
        self._lut_name = lut_name
        rng = np.random.default_rng(3)
        h = np.exp(-((np.linspace(0, 1, 64) - 0.35) ** 2) / 0.04)
        h += 0.15 * rng.random(64)
        self._hist = h / h.max()

    def set_lut(self, name):
        self._lut_name = name
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        bar_w = 14
        gap = 6
        hist_w = w - bar_w - gap
        # histogram (bars drawn right-to-left, sqrt-scaled)
        p.fillRect(0, 0, hist_w, h, QColor(C["well"]))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["accent"]))
        n = len(self._hist)
        for i in range(n):
            v = np.sqrt(self._hist[i])
            bw = v * hist_w
            y0 = int(i / n * h)
            y1 = int((i + 1) / n * h)
            p.fillRect(int(hist_w - bw), y0, int(bw), max(1, y1 - y0), QColor(C["accent"]))
        # colorbar
        lut = make_lut(self._lut_name)
        x0 = hist_w + gap
        for row in range(h):
            t = 1 - row / max(1, h - 1)          # high value at top
            r, g, b = lut[int(t * 255)]
            p.setPen(QColor(int(r), int(g), int(b)))
            p.drawLine(x0, row, x0 + bar_w, row)
        p.setPen(QPen(QColor(C["border_strong"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(x0, 0, bar_w - 1, h - 1)
        p.end()

"""Small styled widget builders shared across the dashboard.

These are the repeated bits of chrome — a themed label, a titled card, a
right-aligned field, a segmented pill control — that every dashboard window
assembles its panels from.  They were methods on ``MainWindowDashboard`` and
hand-copied into the Motor and Beamline panels; keeping one copy here means a
styling change lands everywhere at once.

Plain functions, not methods: none of them read or write window state, and the
widget they return is the only thing the caller needs.  Import them namespaced
(``from pystxmcontrol.gui.dashboard import widgets as dw``) so ``dw.label`` and
``dw.card`` can't be shadowed by the local variables of the same name that the
callers use freely.

The actual look lives in ``theme.build_stylesheet``, which selects on
the ``role`` property and the object names set here.
"""

from PySide6.QtWidgets import (
    QFrame, QLabel, QLineEdit, QPushButton, QButtonGroup,
    QVBoxLayout, QHBoxLayout, QGridLayout,
)
from PySide6.QtCore import Qt

from pystxmcontrol.gui.dashboard.theme import C


def label(text, role=None, font=None, color=None):
    """A themed QLabel.  ``role`` selects a stylesheet rule; ``color`` overrides
    it outright for the few one-off tints."""
    lbl = QLabel(text)
    if role:
        lbl.setProperty("role", role)
    if font:
        lbl.setFont(font)
    if color:
        lbl.setStyleSheet(f"color:{color};background:transparent;")
    return lbl


def vline():
    """A one-pixel vertical rule, for separating header groups."""
    f = QFrame()
    f.setFixedWidth(1)
    f.setStyleSheet(f"background:{C['border']};border:none;")
    return f


def card(title, note=None, padded=False):
    """A titled card.  Returns ``(card frame, body layout)``.

    The body has no padding by default — panels that fill a card edge to edge
    (a plot, an image) add their own; pass ``padded=True`` for the inset body
    the floating utility windows use.

    The card carries two attributes for callers that need to reach back into the
    header: ``header_layout`` (to append extra controls) and ``note_label`` (the
    right-hand note, or None).  ``note_label`` is returned on the card rather
    than stashed on the caller, so one card's note can't overwrite another's.
    """
    frame = QFrame()
    frame.setObjectName("card")
    cl = QVBoxLayout(frame)
    cl.setContentsMargins(0, 0, 0, 0)
    cl.setSpacing(0)

    header = QFrame()
    header.setObjectName("cardHeader")
    hl = QHBoxLayout(header)
    hl.setContentsMargins(14, 11, 14, 11)
    h = label(title.upper())
    h.setObjectName("panelHeading")
    hl.addWidget(h)
    hl.addStretch(1)
    note_lbl = None
    if note is not None:
        note_lbl = label(note)
        note_lbl.setObjectName("panelNote")
        hl.addWidget(note_lbl)
    cl.addWidget(header)

    body = cl
    if padded:
        body = QVBoxLayout()
        body.setContentsMargins(14, 12, 14, 14)
        body.setSpacing(10)
        cl.addLayout(body)

    frame.header_layout = hl
    frame.note_label = note_lbl
    return frame, body


def field(value="", derived=False, align_right=True):
    """A single-line entry.  ``derived=True`` marks it read-only and styles it as
    a computed value (step sizes, totals) rather than an input."""
    e = QLineEdit(value)
    if derived:
        e.setProperty("derived", "true")
        e.setReadOnly(True)
    if align_right:
        e.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return e


def segmented(items, checked=0, role="pill"):
    """A segmented pill control inside a well.  Returns ``(well, [buttons])``;
    the exclusive QButtonGroup is on the well as ``well.group``."""
    well = QFrame()
    well.setProperty("role", "pillWell")
    wl = QHBoxLayout(well)
    wl.setContentsMargins(2, 2, 2, 2)
    wl.setSpacing(2)
    grp = QButtonGroup(well)
    grp.setExclusive(True)
    btns = []
    for i, name in enumerate(items):
        b = QPushButton(name)
        b.setProperty("role", role)
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        if i == checked:
            b.setChecked(True)
        grp.addButton(b, i)
        wl.addWidget(b)
        btns.append(b)
    well.group = grp
    return well, btns


def group_box(title, note=None, sep=True):
    """A group in a scrolling controls panel: title row + body layout."""
    w = QFrame()
    if sep:
        w.setObjectName("rowSep")
    v = QVBoxLayout(w)
    v.setContentsMargins(14, 12, 14, 12)
    v.setSpacing(9)
    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.addWidget(label(title.upper(), role="fieldLabel"))
    top.addStretch(1)
    if note:
        top.addWidget(label(note, role="monoFaint"))
    v.addLayout(top)
    return w, v


def grid4(specs):
    """A 4-column labelled-field grid.  ``specs`` = ``[(label, value, derived)]``.
    Returns ``(grid layout, [line edits])``."""
    g = QGridLayout()
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(6)
    g.setVerticalSpacing(4)
    edits = []
    for col, (lbl, val, derived) in enumerate(specs):
        g.addWidget(label(lbl, role="microLabel"), 0, col)
        e = field(val, derived=derived)
        g.addWidget(e, 1, col)
        edits.append(e)
    return g, edits


def style_plot(pw):
    """Apply the dashboard's plot chrome (ground, faint grid, themed axes)."""
    pw.setBackground(C["plot_ground"])
    pw.showGrid(x=True, y=True, alpha=0.15)
    for ax in ("bottom", "left"):
        pw.getAxis(ax).setPen(C["border"])
        pw.getAxis(ax).setTextPen(C["text_faint"])
    return pw

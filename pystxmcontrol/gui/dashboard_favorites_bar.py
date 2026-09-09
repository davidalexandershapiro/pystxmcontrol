"""The energy-region "favorites" bar and the wrapping layout it uses.

Split out of ``mainwindow_dashboard``: a self-contained drop target that emits
a path and lets the window decide what to do with it.
"""

from PySide6.QtWidgets import QFrame, QLayout, QSizePolicy
from PySide6.QtCore import Qt, QPoint, QRect, QSize, Signal


class FlowLayout(QLayout):
    """A left-to-right layout that wraps items onto new rows when they run out
    of horizontal space, growing the parent vertically instead of overflowing
    off-screen.  (Qt ships no wrapping layout; this is the canonical minimal
    implementation from the Qt docs, adapted for PySide6.)"""

    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def __del__(self):
        while self._items:
            self._items.pop()

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = eff.x(), eff.y()
        line_height = 0
        space = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if next_x - space > eff.right() and line_height > 0:
                x = eff.x()
                y = y + line_height + space
                next_x = x + hint.width() + space
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


class EnergyFavoritesBar(QFrame):
    """A drop target + button row for energy-region "favorites".

    Dropping a ``.json`` energy-preset file (from the OS file manager) onto the
    bar emits ``file_dropped(path)``; the owner then asks for an alias and adds a
    button.  Child buttons/labels don't accept drops, so drag events over them
    fall through to this bar — plus the trailing stretch is always an open drop
    zone.  Left-click / right-click behaviour is wired per button by the owner."""

    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("favoritesBar")
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self._row = FlowLayout(self, margin=0, spacing=6)

    def layout_row(self):
        return self._row

    @staticmethod
    def _json_urls(md):
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls()
                if u.toLocalFile().lower().endswith(".json")]

    def dragEnterEvent(self, ev):
        (ev.acceptProposedAction() if self._json_urls(ev.mimeData())
         else ev.ignore())

    def dragMoveEvent(self, ev):
        (ev.acceptProposedAction() if self._json_urls(ev.mimeData())
         else ev.ignore())

    def dropEvent(self, ev):
        paths = self._json_urls(ev.mimeData())
        if not paths:
            ev.ignore()
            return
        for p in paths:
            self.file_dropped.emit(p)
        ev.acceptProposedAction()

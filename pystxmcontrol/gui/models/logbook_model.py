"""
LogbookModel: a Qt front door to the logbook storage layer (utils/logbook.py).

It caches the entries for the *current* day folder and emits ``changed`` whenever the
logbook is mutated (by the browser, the analysis widget, the agent, or the logbook
input line), so any view can refresh from one signal.  The folder is settable because
the day directory follows the selected file / active proposal.

All mutations marshal cleanly across threads: the agent runs in a QThread and calls
``add()`` directly; the ``changed`` signal is delivered to GUI-thread slots via Qt's
queued connections, so views update on the GUI thread without extra plumbing.
"""

from PySide6.QtCore import QObject, Signal

from pystxmcontrol.utils import logbook


class LogbookModel(QObject):
    """In-memory cache of the current folder's logbook entries with a change signal."""

    # Emitted (with the active folder) after any load or mutation.
    changed = Signal(str)

    def __init__(self, folder: str | None = None):
        super().__init__()
        self._folder: str | None = None
        self._entries: list = []
        if folder:
            self.set_folder(folder)

    # ── folder management ────────────────────────────────────────────────────
    @property
    def folder(self) -> str | None:
        return self._folder

    def set_folder(self, folder: str) -> None:
        """Point the model at a day directory and (re)load its entries."""
        self._folder = folder
        self.reload()

    def reload(self) -> None:
        """Re-read entries from disk for the current folder and emit ``changed``."""
        self._entries = logbook.load_entries(self._folder) if self._folder else []
        self.changed.emit(self._folder or "")

    @property
    def entries(self) -> list:
        """The cached entry list (newest last). Returns a copy so callers can't mutate it."""
        return list(self._entries)

    # ── mutations ────────────────────────────────────────────────────────────
    def add(self, snap_qimage=None, meta: dict | None = None, comment: str = "",
            detail_text: str = "", text: str = "", author: str = "human",
            folder: str | None = None) -> int:
        """Add an entry. ``folder`` overrides/sets the active folder (the browser derives it
        per selected file). ``snap_qimage`` is optional for a text-only/agent note. ``author``
        is "human", "agent", or "intelligence" for relevance/trust weighting."""
        if folder and folder != self._folder:
            self._folder = folder
        if not self._folder:
            raise ValueError("LogbookModel.add(): no folder set")
        index = logbook.add_entry(self._folder, snap_qimage, meta or {},
                                  comment, detail_text, text, author)
        self.reload()
        return index

    def update(self, entry_id: str, *, comment=None, detail_text=None, text=None):
        """Edit an entry's text fields by id."""
        if not self._folder:
            return None
        result = logbook.update_entry(self._folder, entry_id, comment=comment,
                                      detail_text=detail_text, text=text)
        self.reload()
        return result

    def delete(self, entry_id: str) -> bool:
        """Delete an entry by id (and its snapshot)."""
        if not self._folder:
            return False
        ok = logbook.delete_entry(self._folder, entry_id)
        self.reload()
        return ok

    def export_pdf(self) -> str | None:
        """Regenerate the PDF and return its path."""
        if not self._folder:
            return None
        logbook.regenerate_pdf(self._folder, self._entries)
        return logbook._pdf_path(self._folder)

"""
Logbook storage layer for the data browser, analysis widget, and (eventually) the
task agent and the unified logbook view.

Each entry is a record in ``logbook.json`` in a day directory, with an optional PNG
snapshot in ``logbook_snaps/``.  ``logbook.pdf`` is regenerated from all entries on
every mutation so the document stays coherent.

This module is the pure storage layer (no Qt): it operates on a folder and a list of
entry dicts.  ``gui/models/logbook_model.py`` wraps it in a ``QObject`` that caches the
entries and emits a ``changed`` signal so views can refresh.

File layout inside the day directory::

    <day_dir>/
        logbook.json          ← list of entry dicts
        logbook_snaps/
            snap_<id>.png      ← PNG snapshot (only for entries that have an image)
            …
        logbook.pdf           ← regenerated on every mutation

Entry dict keys
---------------
id          : stable unique id (hex) — addressable for update/delete
author      : who created the entry — "human", "agent", or "intelligence".
              A relevance/trust signal for the agent: human observations outweigh the
              agent's own prior (possibly unverified) entries when reasoning.
timestamp   : ISO-8601 string
image_file  : basename of the .stxm source file (may be "")
scan_type   : e.g. "Image", "Double Motor" (may be "")
date        : date string from file metadata
time        : time string from file metadata
proposal    : proposal / ESAF string
source      : beamline source name
energy      : energy string e.g. "520.0 eV"
snap_file   : basename of the PNG snapshot, or "" for a text-only entry
text        : free-form entry body (text-only notes, agent-authored entries)
comment     : free-text comment attached to a scan snapshot
detail_text : full metadata block as shown in the browser
"""

import json
import os
import uuid
from datetime import datetime


def _snaps_dir(folder: str) -> str:
    return os.path.join(folder, "logbook_snaps")


def _json_path(folder: str) -> str:
    return os.path.join(folder, "logbook.json")


def _pdf_path(folder: str) -> str:
    return os.path.join(folder, "logbook.pdf")


def _new_id() -> str:
    """A short, collision-free entry id used both as the dict key and the snap filename."""
    return uuid.uuid4().hex[:12]


def load_entries(folder: str) -> list:
    """Return the entry list for ``folder``.

    Legacy entries written before stable ids existed are migrated in place (assigned an
    ``id`` and a ``text`` field) and persisted once, so addressability is stable afterwards.
    """
    path = _json_path(folder)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
    except Exception:
        return []

    migrated = False
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if not entry.get("id"):
            entry["id"] = _new_id()
            migrated = True
        if "text" not in entry:
            entry["text"] = ""
            migrated = True
        if "author" not in entry:
            entry["author"] = "human"   # all pre-author entries were user-created
            migrated = True
    if migrated:
        try:
            _save_entries(folder, data)
        except Exception:
            pass  # migration is best-effort; ids still hold for this session
    return data


# Backward-compatible alias for the previous private name.
_load_entries = load_entries


def _save_entries(folder: str, entries: list):
    with open(_json_path(folder), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def add_entry(folder: str, snap_qimage, meta: dict,
              comment: str = "", detail_text: str = "", text: str = "",
              author: str = "human") -> int:
    """Append a logbook entry and regenerate the PDF.

    ``snap_qimage`` (a ``QImage``) is optional — pass ``None`` for a text-only entry.
    ``meta`` is optional metadata (filename, scan_type, energy, …); pass ``{}`` or ``None``
    for a free-form note.  ``author`` records who created the entry ("human", "agent",
    "intelligence") for relevance/trust weighting.  Returns the new entry's 1-based position
    (for a human-readable "Entry N added" message); use the entry's ``id`` for update/delete.
    """
    meta = meta or {}
    entries = load_entries(folder)
    entry_id = _new_id()

    snap_name = ""
    if snap_qimage is not None:
        os.makedirs(_snaps_dir(folder), exist_ok=True)
        snap_name = f"snap_{entry_id}.png"
        snap_qimage.save(os.path.join(_snaps_dir(folder), snap_name), "PNG")

    entry = {
        "id":          entry_id,
        "author":      author or "human",
        "timestamp":   datetime.now().isoformat(timespec="seconds"),
        "image_file":  meta.get("filename", ""),
        "scan_type":   meta.get("scan_type", ""),
        "date":        meta.get("date", ""),
        "time":        meta.get("time", ""),
        "proposal":    meta.get("proposal", ""),
        "source":      meta.get("source", ""),
        "energy":      meta.get("energy", ""),
        "snap_file":   snap_name,
        "text":        (text or "").strip(),
        "comment":     (comment or "").strip(),
        "detail_text": detail_text or "",
    }
    entries.append(entry)
    _save_entries(folder, entries)
    regenerate_pdf(folder, entries)
    return len(entries)


def update_entry(folder: str, entry_id: str, *, comment=None,
                 detail_text=None, text=None) -> dict | None:
    """Edit an existing entry's text fields by id, then regenerate the PDF.

    Only the fields passed (non-None) are changed.  Returns the updated entry dict, or
    ``None`` if no entry with ``entry_id`` exists.
    """
    entries = load_entries(folder)
    target = next((e for e in entries if e.get("id") == entry_id), None)
    if target is None:
        return None
    if comment is not None:
        target["comment"] = comment.strip()
    if detail_text is not None:
        target["detail_text"] = detail_text
    if text is not None:
        target["text"] = text.strip()
    _save_entries(folder, entries)
    regenerate_pdf(folder, entries)
    return target


def delete_entry(folder: str, entry_id: str) -> bool:
    """Delete an entry by id, remove its snapshot file, and regenerate the PDF.

    Returns True if an entry was removed.  Other entries' ids and snapshot filenames are
    unaffected (ids decouple entries from list position).
    """
    entries = load_entries(folder)
    target = next((e for e in entries if e.get("id") == entry_id), None)
    if target is None:
        return False
    snap = target.get("snap_file", "")
    if snap:
        try:
            os.remove(os.path.join(_snaps_dir(folder), snap))
        except OSError:
            pass  # snapshot already gone — not fatal
    entries = [e for e in entries if e.get("id") != entry_id]
    _save_entries(folder, entries)
    regenerate_pdf(folder, entries)
    return True


def regenerate_pdf(folder: str, entries: list = None):
    """Regenerate ``logbook.pdf`` from all entries.  Removes the PDF when there are none."""
    if entries is None:
        entries = load_entries(folder)

    if not entries:
        # No entries left (e.g. last one deleted) — drop a stale PDF so it doesn't linger.
        try:
            os.remove(_pdf_path(folder))
        except OSError:
            pass
        return

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Image as RLImage, Paragraph,
        Spacer, HRFlowable, PageBreak, Table, TableStyle,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LogTitle",
        parent=styles["Heading2"],
        fontSize=13,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "LogBody",
        parent=styles["Normal"],
        fontSize=11,
        leading=15,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "LogMeta",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=8,
        leading=11,
        spaceAfter=4,
    )
    comment_style = ParagraphStyle(
        "LogComment",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.darkblue,
        spaceAfter=6,
        leading=14,
    )
    cell_style = ParagraphStyle(
        "LogCell",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
    )

    page_w, page_h = A4
    margin = 2 * cm
    usable_w = page_w - 2 * margin
    img_max_w = usable_w        # fill the full usable page width
    img_max_h = page_h * 0.75   # up to 75 % of page height

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _is_sep_row(line: str) -> bool:
        """A Markdown table separator row, e.g. |---|:--:|."""
        s = line.strip().strip("|").strip()
        return bool(s) and "-" in s and set(s) <= set("-: |")

    def _split_row(line: str) -> list:
        cells = line.strip().split("|")
        if cells and cells[0].strip() == "":
            cells = cells[1:]
        if cells and cells[-1].strip() == "":
            cells = cells[:-1]
        return [c.strip() for c in cells]

    def _make_table(header: list, rows: list):
        ncols = max([len(header)] + [len(r) for r in rows]) if rows else len(header)
        ncols = max(ncols, 1)
        pad = lambda r: r + [""] * (ncols - len(r))
        data = [[Paragraph(_esc(c), cell_style) for c in pad(header)]]
        for r in rows:
            data.append([Paragraph(_esc(c), cell_style) for c in pad(r)])
        col_w = usable_w / ncols
        t = Table(data, colWidths=[col_w] * ncols)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        return t

    def _body_flowables(text: str) -> list:
        """Split an entry body into paragraphs + Markdown pipe-tables (rendered as
        reportlab Tables). Non-table lines are emitted as plain (escaped) paragraphs."""
        out, para = [], []
        lines = text.split("\n")

        def flush():
            if para:
                out.append(Paragraph("<br/>".join(_esc(p) for p in para), body_style))
                para.clear()

        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if ("|" in line and i + 1 < n and "|" in lines[i + 1]
                    and _is_sep_row(lines[i + 1])):
                flush()
                header = _split_row(line)
                i += 2
                rows = []
                while i < n and lines[i].strip() and "|" in lines[i]:
                    rows.append(_split_row(lines[i]))
                    i += 1
                out.append(_make_table(header, rows))
            elif not line.strip():
                flush()
                i += 1
            else:
                para.append(line)
                i += 1
        flush()
        return out

    story = []
    snaps = _snaps_dir(folder)

    for i, entry in enumerate(entries):
        snap_path = os.path.join(snaps, entry.get("snap_file", "")) if entry.get("snap_file") else ""

        # ── header line ───────────────────────────────────────────────────────
        ts = entry.get("timestamp", "")
        fname = entry.get("image_file", "") or "note"
        author = entry.get("author", "human")
        byline = f" · {author}" if author and author != "human" else ""
        header_text = (f"Entry {i + 1} — {fname}"
                       f"   <font size='9' color='grey'>{ts}{byline}</font>")
        story.append(Paragraph(header_text, title_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 0.2 * cm))

        # ── free-form body text (notes / agent entries); Markdown pipe-tables ──
        body = (entry.get("text", "") or "").strip()
        if body:
            for fl in _body_flowables(body):
                story.append(fl)
                story.append(Spacer(1, 0.1 * cm))

        # ── snapshot image ────────────────────────────────────────────────────
        if snap_path and os.path.isfile(snap_path):
            from PIL import Image as PILImage
            with PILImage.open(snap_path) as pil_img:
                px_w, px_h = pil_img.size
            aspect = px_h / px_w if px_w > 0 else 1.0
            rl_w = img_max_w
            rl_h = rl_w * aspect
            if rl_h > img_max_h:
                rl_h = img_max_h
                rl_w = rl_h / aspect
            story.append(RLImage(snap_path, width=rl_w, height=rl_h))
            story.append(Spacer(1, 0.3 * cm))

        # ── metadata block ────────────────────────────────────────────────────
        detail = (entry.get("detail_text", "") or "").replace("\n", "<br/>")
        if detail:
            story.append(Paragraph(detail, meta_style))

        # ── comment ───────────────────────────────────────────────────────────
        comment = (entry.get("comment", "") or "").strip()
        if comment:
            story.append(Paragraph(f"<b>Comment:</b> {comment}", comment_style))

        # page break between entries (but not after the last one)
        if i < len(entries) - 1:
            story.append(PageBreak())

    doc = SimpleDocTemplate(
        _pdf_path(folder),
        pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
        title="Scan Logbook",
    )
    doc.build(story)

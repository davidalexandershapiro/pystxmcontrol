"""
Logbook utility for the data browser.

Each call to ``add_entry()`` appends a record to ``logbook.json`` in the
supplied folder and saves the image snapshot, then regenerates ``logbook.pdf``
from scratch so all entries appear in one coherent document.

File layout inside the day directory::

    <day_dir>/
        logbook.json          ← append-only list of entry dicts
        logbook_snaps/
            snap_0001.png
            snap_0002.png
            …
        logbook.pdf           ← regenerated on every add_entry() call

Entry dict keys
---------------
timestamp   : ISO-8601 string
image_file  : basename of the .stxm source file
scan_type   : e.g. "Image", "Double Motor"
date        : date string from file metadata
time        : time string from file metadata
proposal    : proposal / ESAF string
source      : beamline source name
energy      : energy string e.g. "520.0 eV"
snap_file   : basename of the PNG snapshot (relative to logbook_snaps/)
comment     : free-text comment entered by the user
detail_text : full metadata block as shown in the browser
"""

import json
import os
from datetime import datetime


def _snaps_dir(folder: str) -> str:
    return os.path.join(folder, "logbook_snaps")


def _json_path(folder: str) -> str:
    return os.path.join(folder, "logbook.json")


def _pdf_path(folder: str) -> str:
    return os.path.join(folder, "logbook.pdf")


def _load_entries(folder: str) -> list:
    path = _json_path(folder)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_entries(folder: str, entries: list):
    with open(_json_path(folder), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def add_entry(folder: str, snap_qimage, meta: dict,
              comment: str, detail_text: str) -> int:
    """
    Save ``snap_qimage`` (a ``QImage``) as a PNG snapshot, append a record to
    ``logbook.json``, and regenerate ``logbook.pdf``.

    Returns the 1-based entry index.
    """
    os.makedirs(_snaps_dir(folder), exist_ok=True)

    entries = _load_entries(folder)
    index = len(entries) + 1
    snap_name = f"snap_{index:04d}.png"
    snap_path = os.path.join(_snaps_dir(folder), snap_name)

    snap_qimage.save(snap_path, "PNG")

    entry = {
        "timestamp":   datetime.now().isoformat(timespec="seconds"),
        "image_file":  meta.get("filename", ""),
        "scan_type":   meta.get("scan_type", ""),
        "date":        meta.get("date", ""),
        "time":        meta.get("time", ""),
        "proposal":    meta.get("proposal", ""),
        "source":      meta.get("source", ""),
        "energy":      meta.get("energy", ""),
        "snap_file":   snap_name,
        "comment":     comment.strip(),
        "detail_text": detail_text,
    }
    entries.append(entry)
    _save_entries(folder, entries)
    regenerate_pdf(folder, entries)
    return index


def regenerate_pdf(folder: str, entries: list = None):
    """
    Regenerate ``logbook.pdf`` from all entries in ``logbook.json``.
    If ``entries`` is provided it is used directly (avoids a redundant read).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Image as RLImage, Paragraph,
        Spacer, HRFlowable, PageBreak,
    )
    from reportlab.platypus.flowables import KeepTogether

    if entries is None:
        entries = _load_entries(folder)

    if not entries:
        return

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LogTitle",
        parent=styles["Heading2"],
        fontSize=13,
        spaceAfter=4,
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

    page_w, page_h = A4
    margin = 2 * cm
    usable_w = page_w - 2 * margin
    # Image takes up to 60 % of the usable width; metadata fills the rest via text
    img_max_w = usable_w * 0.55
    img_max_h = page_h * 0.45

    story = []
    snaps = _snaps_dir(folder)

    for i, entry in enumerate(entries):
        snap_path = os.path.join(snaps, entry.get("snap_file", ""))

        # ── header line ───────────────────────────────────────────────────────
        ts = entry.get("timestamp", "")
        fname = entry.get("image_file", "")
        header_text = f"Entry {i + 1} — {fname}   <font size='9' color='grey'>{ts}</font>"
        story.append(Paragraph(header_text, title_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
        story.append(Spacer(1, 0.2 * cm))

        # ── snapshot image ────────────────────────────────────────────────────
        if os.path.isfile(snap_path):
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
        detail = entry.get("detail_text", "").replace("\n", "<br/>")
        if detail:
            story.append(Paragraph(detail, meta_style))

        # ── comment ───────────────────────────────────────────────────────────
        comment = entry.get("comment", "").strip()
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

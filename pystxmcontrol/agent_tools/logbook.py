"""Reading and writing the experiment logbook.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import json
import logging
import os

import numpy as np

from pystxmcontrol.controller.tool_registry import tool


log = logging.getLogger(__name__)


class LogbookTools:
    """Reading and writing the experiment logbook."""

    @tool(requires=('logbook',), hidden_params=("attach_last_scan",))
    def add_to_logbook(self, text: str, attach: str = "scan", daq: str = "default",
                       image_path: str = "", attach_last_scan: bool | None = None) -> str:
        """Add an entry to the active logbook on the user's behalf.

        Use this to record an observation, a result, or an intelligence recommendation —
        e.g. after a scan completes, summarise what was done and attach the image. The entry
        is stamped author='agent'. Requires a logbook to be open in the Logbook tab; if none
        is open, ask the user to open or create one.


        Only add entries the user asked for, or that clearly document the work just done
        — do not spam the logbook.
        Args:
            attach: which image to embed (grayscale, autoscaled):
                "scan"     — the most recent live scan image (default);
                "computed" — the most recent image produced by a calculation tool, e.g. the
                             two-energy elemental/difference map from count_element_particles
                             or the NNMF cluster map + spectra figure from analyze_energy_stack.
                             Use this to save a computed result, not a raw scan;
                "file"     — an image file from disk, named by image_path. Use this for a
                             figure a tool saved, e.g. the PNG returned by
                             plot_motor_positions; unlike "computed" it is not overwritten
                             by a later calculation, so it works turns after the fact;
                "none"     — text-only entry, no image.
            daq:    detector channel for the "scan" image (default 'default').
            image_path: path to the image file for attach="file" (PNG, JPEG, TIFF, ...).
                A bad path is refused outright rather than silently logged text-only.
            attach_last_scan: deprecated — True maps to attach="scan", False to attach="none".
            text: The entry body — the observation, result, or recommendation.
        """
        model = self._logbook_model
        if model is None:
            return "Logbook is not available in this session."
        if not getattr(model, "folder", None):
            return ("No logbook is open. Ask the user to open or create one in the Logbook "
                    "tab (New/Open), then try again.")
        if not (text or "").strip():
            return "Refusing to add an empty logbook entry — provide text."

        # Backward compatibility with the old boolean parameter.
        if attach_last_scan is not None:
            attach = "scan" if attach_last_scan else "none"
        attach = (attach or "scan").lower()
        if attach not in ("scan", "computed", "file", "none"):
            return (f"Unknown attach mode '{attach}'. Use 'scan', 'computed', 'file', "
                    "or 'none'.")

        # Best-effort metadata from the current scan context.
        meta = {}
        scan_type = self._image_model.get('scan_type', '')
        energy = self._image_model.get('current_energy')
        if scan_type:
            meta['scan_type'] = scan_type
        if energy is not None:
            meta['energy'] = f"{float(energy):.1f} eV"

        qimg = None
        attach_desc = ""
        snap_note = ""
        if attach == "computed":
            comp = self._last_computed_image
            # A pre-rendered figure (e.g. the NNMF cluster map + spectra) is embedded as-is;
            # only raw arrays go through _array_to_qimage's grayscale autoscale below.
            pre_qimg = comp.get('qimage') if isinstance(comp, dict) else None
            fallback_reason = ""
            if pre_qimg is not None:
                qimg = pre_qimg
                meta.update(comp.get('meta') or {})
                attach_desc = f" with the {comp.get('label', 'computed image')}"
            else:
                arr = comp.get('array') if isinstance(comp, dict) else None
                if not isinstance(arr, np.ndarray):
                    # Nothing cached (e.g. the count came from the intelligence module, which
                    # can't ship the map array): build the two-energy map from the buffered scan.
                    built, info = self._latest_two_energy_map()
                    if isinstance(built, np.ndarray):
                        self._remember_computed_image(built, "two-energy elemental map", info)
                        comp = self._last_computed_image
                        arr = comp.get('array')
                    else:
                        fallback_reason = info
                if isinstance(arr, np.ndarray):
                    qimg = self._array_to_qimage(arr)
                    meta.update(comp.get('meta') or {})
                    attach_desc = f" with the {comp.get('label', 'computed image')}"
            if qimg is None:
                snap_note = (f" (no computed image was available to attach — {fallback_reason}; "
                             "run a calculation such as count_element_particles first)"
                             if fallback_reason else
                             " (no computed image was available to attach — run a "
                             "calculation such as count_element_particles first)")
        elif attach == "file":
            # The operator named a specific file, so a bad path is a mistake to report, not
            # something to paper over with a text-only entry the way a missing scan frame is.
            qimg, err = self._qimage_from_file(image_path)
            if qimg is None:
                return f"Did not add the entry — could not attach the image: {err}."
            name = os.path.basename(os.path.expanduser(os.path.expandvars(image_path.strip())))
            meta.setdefault('filename', name)   # add_entry stores this as the entry title
            attach_desc = f" with {name}"
        elif attach == "scan":
            all_images = self._image_model.get('all_detector_images')
            image = all_images.get(daq) if isinstance(all_images, dict) else None
            if image is None and isinstance(all_images, dict):
                image = all_images.get('default')
            if isinstance(image, np.ndarray):
                qimg = self._array_to_qimage(image)
                attach_desc = " with the last scan image"
            if qimg is None:
                snap_note = " (no scan image was available to attach)"

        try:
            index = model.add(snap_qimage=qimg, meta=meta, text=text, author="agent")
        except Exception as e:
            return f"Failed to add logbook entry: {e}"
        return (f"Added logbook entry #{index} to '{os.path.basename(model.folder)}'"
                f"{attach_desc}{snap_note}.")

    def _logbook_entries_for_context(self, authors=None) -> list:
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return []
        entries = model.entries
        if authors:
            entries = [e for e in entries if e.get("author", "human") in authors]
        return entries

    def logbook_index(self, max_entries: int = 50, authors=None) -> str | None:
        """Compact one-line-per-entry index for auto-injection at task start.

        Returns None when no logbook is open or it has no (matching) entries. Entries keep
        their absolute #number so they line up with the full logbook and with citations.
        """
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return None
        entries = model.entries
        idx = list(enumerate(entries))                       # (0-based position, entry)
        if authors:
            idx = [(i, e) for i, e in idx if e.get("author", "human") in authors]
        if not idx:
            return None
        shown = idx[-max_entries:] if max_entries and len(idx) > max_entries else idx
        lines = []
        for i, e in shown:
            snippet = (e.get("text") or e.get("comment") or "").strip().replace("\n", " ")
            if len(snippet) > 90:
                snippet = snippet[:87] + "…"
            title = e.get("image_file") or "note"
            lines.append(f"#{i + 1} [{e.get('author', 'human')}] {e.get('timestamp', '')} "
                         f"{title} (id={e.get('id', '')}): {snippet}")
        header = f"Logbook '{os.path.basename(model.folder)}' — {len(entries)} entries"
        if len(shown) < len(idx):
            header += f" (showing last {len(shown)})"
        return header + "\n" + "\n".join(lines)

    @tool(requires=('logbook',), feature="logbook_context")
    def search_logbook(self, query: str = "", author: str = "", limit: int = 20) -> str:
        """Search the active logbook. Substring match (case-insensitive) over the entry text,
        comment, metadata, and filename; optionally filter by author ('human'/'agent'/
        'intelligence'). Returns compact hits (id, #, author, timestamp, title, snippet) —
        call get_logbook_entry(id) for the full text.


        Human-authored entries are the operator's own observations — weight them above
        your own prior agent entries.
        Args:
            query: Search text; empty lists recent entries.
            author: Optional: restrict to one author.
            limit: Max hits (default 20, most recent).
        """
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return "No logbook is open."
        q = (query or "").lower().strip()
        hits = []
        for i, e in enumerate(model.entries):
            if author and e.get("author", "human") != author:
                continue
            hay = " ".join([e.get("text", ""), e.get("comment", ""),
                            e.get("detail_text", ""), e.get("image_file", "")]).lower()
            if q and q not in hay:
                continue
            snippet = (e.get("text") or e.get("comment") or "").strip().replace("\n", " ")
            hits.append({"id": e.get("id"), "n": i + 1, "author": e.get("author", "human"),
                         "timestamp": e.get("timestamp"),
                         "title": e.get("image_file") or "note",
                         "snippet": snippet[:120]})
        hits = hits[-limit:]   # most recent matches if capped
        return json.dumps({"count": len(hits), "entries": hits}, indent=2)

    @tool(requires=('logbook',), feature="logbook_context")
    def get_logbook_entry(self, entry_id: str) -> str:
        """Return the full text/metadata of one logbook entry by id (image not included;
        has_image flags whether a snapshot exists).

        Args:
            entry_id: The entry id.
        """
        model = self._logbook_model
        if model is None or not getattr(model, "folder", None):
            return "No logbook is open."
        e = next((x for x in model.entries if x.get("id") == entry_id), None)
        if e is None:
            return f"No logbook entry with id '{entry_id}'."
        out = {k: e.get(k) for k in ("id", "author", "timestamp", "image_file",
                                     "scan_type", "energy", "text", "comment", "detail_text")}
        out["has_image"] = bool(e.get("snap_file"))
        return json.dumps(out, indent=2)

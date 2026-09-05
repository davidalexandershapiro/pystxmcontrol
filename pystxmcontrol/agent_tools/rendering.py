"""Turning arrays and figures into logbook snapshots.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import logging
import os

import numpy as np

from pystxmcontrol.controller.tool_registry import tool


log = logging.getLogger(__name__)


class RenderTools:
    """Turning arrays and figures into logbook snapshots."""

    # Largest image file add_to_logbook(attach="file") will embed.  Every entry's snapshot
    # is re-embedded when logbook.add_entry regenerates the PDF, so an oversized one is
    # paid for again on every later entry, not just its own.
    MAX_ATTACH_BYTES = 8 * 1024 * 1024

    @classmethod
    def _qimage_from_file(cls, path: str):
        """Load an image file from disk into a QImage for a logbook snapshot.

        Returns ``(qimage, error)``: on failure qimage is None and error says why in terms
        the agent can act on.  Any format Qt's image plugins read is accepted (PNG, JPEG,
        TIFF, ...) — the snapshot is re-encoded as PNG by logbook.add_entry either way.
        """
        try:
            from PySide6.QtGui import QImage
        except ImportError:
            return None, "PySide6 is not installed, so an image file cannot be loaded"
        if not (path or "").strip():
            return None, "no image_path was given"
        p = os.path.expanduser(os.path.expandvars(path.strip()))
        if not os.path.isfile(p):
            return None, f"no file at '{p}'"
        try:
            size = os.path.getsize(p)
        except OSError as e:
            return None, f"cannot read '{p}': {e}"
        if size > cls.MAX_ATTACH_BYTES:
            return None, (f"'{os.path.basename(p)}' is {size / 1e6:.1f} MB, over the "
                          f"{cls.MAX_ATTACH_BYTES / 1e6:.0f} MB attachment limit")
        qimg = QImage(p)
        if qimg.isNull():
            return None, f"'{os.path.basename(p)}' is not an image Qt can read"
        return qimg, ""

    def _remember_computed_image(self, arr, label: str, meta: dict | None = None) -> None:
        """Cache an image produced by a calculation tool for later logbook attachment.

        Calculation results (e.g. the two-energy difference map) never enter
        ``_image_model['all_detector_images']`` (which the GUI fills with live scan
        frames), so without this the agent has no way to embed them in the logbook.
        """
        try:
            a = np.asarray(arr, dtype=float)
        except (ValueError, TypeError):
            return
        if a.ndim >= 2 and a.size:
            self._last_computed_image = {
                "array": a,
                "label": label,
                "meta": dict(meta or {}),
            }

    @staticmethod
    def _array_to_qimage(arr):
        """Render a 2-D detector array to an autoscaled 8-bit grayscale QImage for a logbook
        snapshot. Returns None if rendering isn't possible. QImage construction is thread-safe
        (no widgets), so this is fine on the agent's worker thread."""
        try:
            from PySide6.QtGui import QImage
        except ImportError:
            return None
        a = np.asarray(arr, dtype=float)
        if a.ndim > 2:
            a = a.reshape(a.shape[0], a.shape[1])
        if a.ndim != 2 or a.size == 0:
            return None
        finite = a[np.isfinite(a)]
        if finite.size == 0:
            return None
        lo, hi = float(finite.min()), float(finite.max())
        scaled = (a - lo) / (hi - lo) * 255.0 if hi > lo else np.zeros_like(a)
        buf = np.ascontiguousarray(np.clip(scaled, 0, 255).astype(np.uint8))
        h, w = buf.shape
        qimg = QImage(buf.data, w, h, w, QImage.Format_Grayscale8)
        return qimg.copy()   # copy so the QImage owns its pixels (buf is local)

    def _render_nmf_figure(self, stk, title: str | None = None):
        """Render a combined NMF figure (colour cluster map + cluster OD spectra) to a
        QImage for a logbook snapshot.  Uses matplotlib's Agg canvas directly (no pyplot,
        no GUI backend) so it is safe on the agent's worker thread.  Returns None on failure."""
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
        except ImportError:
            return None
        try:
            rgb = stk.rgbClusterMap()
            energies = np.asarray(stk.energies, dtype=float)
            # ~2:1 landscape (image + plot side by side) so the logbook renders it double-width;
            # tall enough that the square cluster map fills its half rather than letterboxing.
            fig = Figure(figsize=(10.0, 5.0), dpi=120)
            FigureCanvasAgg(fig)
            ax_map = fig.add_subplot(1, 2, 1)
            ax_spec = fig.add_subplot(1, 2, 2)
            ax_map.imshow(rgb)
            ax_map.set_title("Cluster map")
            ax_map.set_xticks([])
            ax_map.set_yticks([])
            for i, spec in enumerate(stk.clusterSpectra):
                c = np.asarray(stk.penColors[i], dtype=float)
                if c.size >= 3 and c.max() > 1:   # 0-255 ints -> 0-1 for matplotlib
                    c = c / 255.0
                ax_spec.plot(energies, np.asarray(spec, dtype=float),
                             color=tuple(c[:3]), label=f"Cluster {i}")
            ax_spec.set_xlabel("Energy (eV)")
            ax_spec.set_ylabel("Optical density")
            ax_spec.set_title("Cluster spectra")
            ax_spec.legend(fontsize="small", loc="best")
            if title:
                fig.suptitle(title, fontsize="medium")
            fig.tight_layout()
            return self._figure_to_qimage(fig)
        except Exception as e:
            log.warning("[ToolSet] _render_nmf_figure failed: %s", e)
            return None

    def _render_particle_map(self, image, regions, extent, title=None):
        """Render a background image with a numbered box around each found particle region,
        to a QImage for a logbook snapshot.  Uses matplotlib's Agg canvas directly (no pyplot,
        no GUI backend) so it is safe on the agent's worker thread.  Returns None on failure.

        ``extent`` is (left, right, bottom, top) in µm, mapping array col 0 → left, row 0 →
        bottom (origin='lower').  It must use the SAME pixel→µm convention that produced the
        region boxes so every box lands on the feature it was measured from; passing the raw
        scan-direction endpoints (which may run high→low) keeps the picture faithful to the
        acquisition while the boxes, in absolute µm data coordinates, stay aligned."""
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from matplotlib.patches import Rectangle
        except ImportError:
            return None
        try:
            a = np.asarray(image, dtype=float)
            if a.ndim > 2:
                a = a.reshape(a.shape[0], a.shape[1])
            if a.ndim != 2 or a.size == 0:
                return None
            left, right, bottom, top = (float(v) for v in extent)
            fig = Figure(figsize=(6.5, 6.0), dpi=120)
            FigureCanvasAgg(fig)
            ax = fig.add_subplot(1, 1, 1)
            ax.imshow(a, cmap='gray', origin='lower',
                      extent=[left, right, bottom, top], aspect='equal')
            for i, r in enumerate(regions):
                rxc = float(r['xCenter']); ryc = float(r['yCenter'])
                rxr = float(r['xRange']);  ryr = float(r['yRange'])
                color = self._MAP_BOX_COLORS[i % len(self._MAP_BOX_COLORS)]
                ax.add_patch(Rectangle((rxc - rxr / 2.0, ryc - ryr / 2.0), rxr, ryr,
                                       fill=False, edgecolor=color, linewidth=1.5))
                # Number at the box's top-left (y increases upward with origin='lower').
                ax.text(rxc - rxr / 2.0, ryc + ryr / 2.0, str(i + 1),
                        color='black', fontsize=8, va='bottom', ha='left',
                        bbox=dict(facecolor=color, edgecolor='none', pad=1.0))
            ax.set_xlabel("X (µm)")
            ax.set_ylabel("Y (µm)")
            ax.set_title(title or f"{len(regions)} particle region(s)")
            fig.tight_layout()
            return self._figure_to_qimage(fig)
        except Exception as e:
            log.warning("[ToolSet] _render_particle_map failed: %s", e)
            return None

    @staticmethod
    def _figure_to_qimage(fig):
        """Convert a drawn matplotlib Figure to an RGBA QImage.  Thread-safe (no widgets)."""
        try:
            from PySide6.QtGui import QImage
        except ImportError:
            return None
        fig.canvas.draw()
        w, h = fig.canvas.get_width_height()
        buf = np.ascontiguousarray(np.asarray(fig.canvas.buffer_rgba()))
        qimg = QImage(buf.data, w, h, 4 * w, QImage.Format_RGBA8888)
        return qimg.copy()   # copy so the QImage owns its pixels (buf is local)

    def _remember_computed_figure(self, qimage, label: str, meta: dict | None = None) -> None:
        """Cache a pre-rendered figure (QImage) from a calculation tool so
        add_to_logbook(attach='computed') can embed it directly.  Used for colour/composite
        results (e.g. the NNMF cluster map + spectra) that _array_to_qimage cannot render."""
        if qimage is None:
            return
        self._last_computed_image = {
            "array": None,
            "qimage": qimage,
            "label": label,
            "meta": dict(meta or {}),
        }

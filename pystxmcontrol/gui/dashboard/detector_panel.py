"""The Live-detector panel: one tab per configured detector.

Split out of ``mainwindow``.  Point and spectrum detectors get a
trace plot; image detectors get a 2-D viewer with an interactive contrast
control.  Which detectors exist, and in what order, comes entirely from the DAQ
config, so this panel adapts to whatever server the window connected to.

Live values arrive through ``on_daq_value`` and ``on_monitor_data``, which the
window connects to the controller's signals.  The panel reads the controller's
image model for frames but never commands anything, so it stays a display.
"""

import numpy as np
import pyqtgraph as pg

from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QStackedWidget, QSizePolicy,
)

from pystxmcontrol.gui.dashboard import widgets as dw
from pystxmcontrol.gui.dashboard.theme import C, make_lut, mono_font
from pystxmcontrol.gui.dashboard.image_area import SciAxis, exp_str


def _diffraction(n=256, seed=2):
    """Log-scaled speckle with a central beamstop and centre-column gap."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:n, 0:n] - n / 2
    r = np.hypot(x, y)
    base = np.exp(-r / 42.0)
    speckle = base * (0.4 + rng.random((n, n)))
    speckle += 0.02 * rng.random((n, n))
    speckle[r < 14] = 0                      # beamstop
    speckle[:, n // 2 - 1:n // 2 + 1] = 0    # fCCD centre gap
    return np.log1p(speckle * 4000)


def _spectrum():
    e = np.linspace(700, 730, 121)
    od = 0.25 + 0.05 * np.sin(e / 3)
    od += 0.9 * np.exp(-((e - 709) ** 2) / 1.5)     # L3
    od += 0.4 * np.exp(-((e - 722) ** 2) / 2.0)     # L2
    return e, od


class DetectorPanel(QWidget):
    """The Live-detector card.  ``daq_info`` is the DAQ config; ``controller``
    may be None (placeholder mode) and is replaced by ``set_controller`` when
    the window goes live."""

    def __init__(self, daq_info, controller=None, parent=None):
        super().__init__(parent)
        self.daq_info = dict(daq_info or {})
        self.controller = controller
        self._det_keys = []
        self._det_pages = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._build())
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def set_controller(self, controller):
        self.controller = controller

    def _daqs_sorted(self):
        """Detectors as ``(key, cfg)`` tuples, ordered by the config ``index``
        field (missing → last).  Python's stable sort preserves insertion order
        within equal indices; the ``default`` key naturally sorts first (index 0)."""
        return sorted(self.daq_info.items(),
                      key=lambda kv: kv[1].get("index", 999))

    def pulse(self, phase):
        """Animate the header's live dot.  Driven by the window's timer so the
        panel owns no timer of its own."""
        op = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(phase * 3))
        self.live_dot.setStyleSheet(
            f"color:{C['alert']};background:transparent;font-size:10px;"
            f"opacity:{op:.2f};")

    def scroll_placeholder_trace(self):
        """Advance the dummy trace of the active point detector.  Placeholder
        mode only — with a controller, real monitor data drives the curve."""
        p = self._det_pages.get(self.active_key())
        if p and p.get("type") == "point" and p.get("trace") is not None:
            p["trace"] = np.roll(p["trace"], -1)
            p["trace"][-1] = 1 + (np.random.random() - .5) * .004
            p["curve"].setData(p["trace"])
            p["value"].setText(f"{p['trace'][-1]:.4f}")

    def _build(self):
        card, body = dw.card("Live detector")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # Live status + pulse dot live in the header, right-aligned.
        self.live_dot = QLabel("●")
        self.live_dot.setStyleSheet(f"color:{C['alert']};background:transparent;font-size:10px;")
        card.header_layout.addWidget(self.live_dot)
        self.det_status = dw.label("", role="mono")
        self.det_status.setFont(mono_font(10))
        card.header_layout.addWidget(self.det_status)

        # One tab + one page per configured detector.  Point/spectrum detectors
        # get a trace/spectrum plot; image detectors get a 2-D viewer with an
        # interactive contrast (histogram) control.  Keyed by DAQ config key.
        self._det_keys = [k for k, _ in self._daqs_sorted()]
        self._det_pages = {}
        names = [cfg.get("name", k) for k, cfg in self._daqs_sorted()]
        default_idx = self._det_keys.index("default") if "default" in self._det_keys else 0

        wrap = QWidget()
        wrap.setFixedHeight(400)          # taller than before; motors compress
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(14, 14, 14, 14)
        wl.setSpacing(10)

        det_well, _ = dw.segmented(names or ["—"], default_idx)
        wl.addWidget(det_well)

        self.det_stack = QStackedWidget()
        for key, cfg in self._daqs_sorted():
            if cfg.get("type") == "image":
                pagew = self._image_detector_page(key, cfg)
            else:
                pagew = self._trace_detector_page(key, cfg)
            self.det_stack.addWidget(pagew)
        wl.addWidget(self.det_stack, 1)
        body.addWidget(wrap)

        det_well.group.idClicked.connect(self._switch_detector)
        if self._det_keys:
            self.det_stack.setCurrentIndex(default_idx)
            self._update_det_status(default_idx)
        return card

    def _switch_detector(self, i):
        self.det_stack.setCurrentIndex(i)
        self._update_det_status(i)

    def _update_det_status(self, i):
        """Header status line for the selected detector: name · type."""
        if not (0 <= i < len(self._det_keys)):
            return
        cfg = self.daq_info.get(self._det_keys[i], {})
        self.det_status.setText(
            f"{cfg.get('name', self._det_keys[i])} · {cfg.get('type', 'point')}")

    def active_key(self):
        """DAQ config key of the currently displayed detector tab, or None."""
        i = self.det_stack.currentIndex() if hasattr(self, "det_stack") else -1
        return self._det_keys[i] if 0 <= i < len(self._det_keys) else None

    def _image_detector_page(self, key, cfg):
        """A 2-D viewer for an image-type detector: pyqtgraph image on the left,
        an interactive contrast control (HistogramLUTWidget) on the right.  No
        statistics chips — a compact dims/sum caption sits below the image."""
        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(6)
        glw = pg.GraphicsLayoutWidget()
        glw.setBackground("#000000")
        vb = glw.addViewBox()
        vb.setAspectLocked(True)
        vb.invertY(True)
        # Seeded with a placeholder frame; replaced by live area-detector frames
        # (see _refresh_ccd) once a scan with an image-type DAQ is running.
        img = pg.ImageItem(_diffraction())
        img.setLookupTable(make_lut("inferno"))
        vb.addItem(img)
        vb.autoRange(padding=0)
        left.addWidget(glw, 1)
        cap = QHBoxLayout()
        dims_lbl = dw.label("256² · log", role="monoFaint")
        sum_lbl = dw.label("Σ 1.9e6", role="monoFaint")
        cap.addWidget(dims_lbl)
        cap.addStretch(1)
        cap.addWidget(sum_lbl)
        left.addLayout(cap)
        h.addLayout(left, 1)

        # Contrast control: the same draggable levels + gradient editor the main
        # image uses, bound directly to this detector's ImageItem.
        hist = pg.HistogramLUTWidget()
        hist.setBackground(C["panel_footer"])
        hist.setImageItem(img)
        hist.gradient.loadPreset("inferno")
        hist.setFixedWidth(120)
        try:
            hist.axis.setPen(C["border"])
            hist.axis.setTextPen(C["text_faint"])
        except Exception:
            pass
        h.addWidget(hist)

        self._det_pages[key] = {
            "type": "image", "name": cfg.get("name", key),
            "img": img, "vb": vb, "hist": hist,
            "dims_lbl": dims_lbl, "sum_lbl": sum_lbl, "seeded": False}
        return page

    def _trace_detector_page(self, key, cfg):
        """A trace/spectrum plot for a point- or spectrum-type detector.  Point
        detectors show a scrolling monitor trace; spectrum detectors show the
        latest full spectrum.  Live data arrives per-key via _on_monitor_data."""
        dtype = cfg.get("type", "point")
        name = cfg.get("name", key)
        driver = cfg.get("driver", "")
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(9)
        top = QHBoxLayout()
        title = f"{name} monitor" + (f" · {driver}" if driver else "")
        top.addWidget(dw.label(title, role="fieldLabel"))
        top.addStretch(1)
        value_lbl = dw.label("—", role="ok")
        value_lbl.setFont(mono_font(11))
        top.addWidget(value_lbl)
        v.addLayout(top)

        # Exponent shown once above the plot (SciAxis reports it) so the y tick
        # labels stay a compact one-decimal mantissa instead of full magnitudes.
        exp_row = QHBoxLayout()
        exp_row.setContentsMargins(0, 0, 0, 0)
        exp_lbl = dw.label("", role="monoFaint")
        exp_row.addWidget(exp_lbl)
        exp_row.addStretch(1)
        v.addLayout(exp_row)

        left_axis = SciAxis(orientation="left")
        left_axis.on_exp_changed = lambda e, lbl=exp_lbl: lbl.setText(exp_str(e))
        plot = pg.PlotWidget(axisItems={"left": left_axis})
        plot.setBackground(C["plot_ground"])
        plot.showGrid(x=False, y=True, alpha=0.2)
        plot.enableAutoRange("y", True)
        pi = plot.getPlotItem()
        # Full bounding box: draw all four axes; only left/bottom carry tick values.
        pi.showAxis("top"); pi.showAxis("right")
        pi.getAxis("top").setStyle(showValues=False)
        pi.getAxis("right").setStyle(showValues=False)
        for ax in ("left", "bottom", "top", "right"):
            pi.getAxis(ax).setPen(C["border"])
            pi.getAxis(ax).setTextPen(C["text_faint"])

        if dtype == "spectrum":
            e, od = _spectrum()
            curve = plot.plot(e, od, pen=pg.mkPen(C["ok"], width=1.4))
            plot.setLabel("bottom", cfg.get("x label", "Energy (eV)"))
            trace = None
        else:
            trace = 1 + (np.random.default_rng(4).random(220) - .5) * .004
            curve = plot.plot(trace, pen=pg.mkPen(C["ok"], width=1.4))
        v.addWidget(plot, 1)

        self._det_pages[key] = {
            "type": dtype, "name": name, "plot": plot, "curve": curve,
            "value": value_lbl, "exp_lbl": exp_lbl, "trace": trace}
        return page

    def refresh_ccd(self):
        """Update every image-type detector page with its latest area-detector
        frame.

        Idle: the controller stashes each idle-monitor frame under
        'latest_monitor_frames' (the trace only keeps the scalar sum).
        Scanning: the per-detector frames live under 'all_detector_images'.
        """
        if self.controller is None or not getattr(self, "_det_pages", None):
            return
        try:
            im = self.controller.get_image_model()
            mon = im.get("latest_monitor_frames") or {}
            allimg = im.get("all_detector_images") or {}
        except Exception:
            return
        for key, p in self._det_pages.items():
            if p.get("type") != "image":
                continue
            frame = mon.get(key)
            if not (isinstance(frame, np.ndarray) and frame.ndim >= 2):
                frame = allimg.get(key)
            if not (isinstance(frame, np.ndarray) and frame.ndim >= 2):
                continue
            # Log-scale for display (diffraction has huge dynamic range), as the
            # classic viewer does; autorange levels on the first real frame.
            disp = np.log1p(np.clip(frame.astype(float), 0, None))
            p["img"].setImage(disp, autoLevels=not p["seeded"])
            p["seeded"] = True
            # Caption reflects the real frame: dimensions + total counts.
            h, w = frame.shape[:2]
            p["dims_lbl"].setText(f"{h}² · log" if h == w else f"{h}×{w} · log")
            p["sum_lbl"].setText(f"Σ {float(np.sum(frame)):.1e}")

    def on_daq_value(self, value):
        """Selected-channel scalar → the active (point/spectrum) detector's
        current-value readout."""
        p = self._det_pages.get(self.active_key()) if getattr(
            self, "_det_pages", None) else None
        if p and p.get("type") != "image" and p.get("value") is not None:
            p["value"].setText(f"{value:.4f}")

    def on_monitor_data(self):
        """Refresh every point/spectrum detector trace from the image model's
        monitor buffer (keyed by DAQ config key, with a name fallback)."""
        try:
            data = self.controller.get_image_model().get("monitor_data") or {}
        except Exception:
            data = {}
        for key, p in (getattr(self, "_det_pages", {}) or {}).items():
            if p.get("type") == "image":
                continue
            series = data.get(key)
            if series is None:
                series = data.get(p.get("name"))
            if series is None:
                continue
            try:
                arr = np.asarray(series, dtype=float).ravel()
            except Exception:
                continue
            if not arr.size:
                continue
            p["curve"].setData(arr)
            if p.get("type") != "spectrum" and p.get("value") is not None:
                p["value"].setText(f"{arr[-1]:.4f}")
        # Idle CCD frames also arrive on this signal (the trace keeps only the sum).
        self.refresh_ccd()

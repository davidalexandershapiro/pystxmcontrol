"""
IntelligenceModule — passive server-side observer that computes image quality
metrics, detects anomalies, and calls an AI agent for diagnosis.

Enable/disable via main_config["intelligence"]["enabled"].
Hook into dataHandler by setting dataHandler.intelligence = IntelligenceModule(...).

EventRecorder uses named channels:
    "events"  — scan lifecycle + anomalies + agent suggestions  (default max 500)
    "metrics" — per-line mean, per-point value                  (default max 200)

Anomaly rules (all configurable via main_config["intelligence"]["anomaly"]):
    intensity_drop  — z-score of current line mean vs rolling baseline
    intensity_drift — negative slope across recent N line means
    focus_decline   — focus score drops > threshold % between regions

Agent call (requires main_config["intelligence"]["agent"]["enabled"] = true
and ANTHROPIC_API_KEY env var):
    Triggered on anomaly, debounced by cooldown_seconds.
    Runs non-blocking via asyncio.create_task / run_in_executor.
    Result stored in EventRecorder and published via publish_fn callback.
"""

from collections import deque
import asyncio
import time
import numpy as np

_DEFAULT_CHANNELS = {
    "events": 500,
    "metrics": 200,
}

_SYSTEM_PROMPT = """\
You are an expert scientist monitoring a scanning transmission X-ray microscopy \
(STXM) instrument at a synchrotron beamline. Your role is to diagnose anomalies \
and suggest corrective actions based on instrument events."""


# ---------------------------------------------------------------------------
# EventRecorder
# ---------------------------------------------------------------------------

class EventRecorder:
    """Named-channel rolling log of semantic session events.

    Each channel is an independent deque with its own maxlen.  When a channel
    is full the oldest entry is silently dropped.

    Parameters
    ----------
    channels : dict[str, int]
        Mapping of channel name → maximum number of entries to retain.
    """

    def __init__(self, channels: dict | None = None):
        cfg = channels if channels is not None else dict(_DEFAULT_CHANNELS)
        self._channels: dict[str, deque] = {
            name: deque(maxlen=maxlen) for name, maxlen in cfg.items()
        }

    def record(self, channel: str, event_type: str, **kwargs) -> None:
        if channel not in self._channels:
            self._channels[channel] = deque()
        event = {"type": event_type, "timestamp": time.time()}
        event.update(kwargs)
        self._channels[channel].append(event)

    def recent(self, channel: str, n: int = 30) -> list:
        buf = self._channels.get(channel, deque())
        events = list(buf)
        return events[-n:]

    def all(self, channel: str) -> list:
        return list(self._channels.get(channel, deque()))

    def channel_names(self) -> list:
        return list(self._channels.keys())

    def clear(self, channel: str | None = None) -> None:
        if channel is None:
            for buf in self._channels.values():
                buf.clear()
        elif channel in self._channels:
            self._channels[channel].clear()

    def __len__(self) -> int:
        return sum(len(buf) for buf in self._channels.values())

    def len(self, channel: str) -> int:
        return len(self._channels.get(channel, deque()))


# ---------------------------------------------------------------------------
# Image metrics helpers
# ---------------------------------------------------------------------------

def _laplacian_variance(image: np.ndarray) -> float:
    """Focus score: variance of discrete Laplacian. Higher = sharper."""
    if image.ndim != 2 or image.size == 0:
        return 0.0
    lap = (
        np.roll(image, 1, 0) + np.roll(image, -1, 0)
        + np.roll(image, 1, 1) + np.roll(image, -1, 1)
        - 4.0 * image
    )
    return float(np.var(lap))


def _focus_crispness(image: np.ndarray, line_smooth: float = 1.0) -> np.ndarray:
    """Per-row (per-ZonePlateZ) sharpness via Tenengrad (gradient energy) along the line.

    A focus-scan image is rows = ZonePlateZ, cols = position along the scanned line. The
    feature (OSA edge) is sharp at focus → large Σ(∇I)². Validated on real OSA-focus data
    (scripts/test_focus_scan.py): Tenengrad gives a clean unimodal peak at the focus row.
    """
    from scipy.ndimage import gaussian_filter1d
    a = np.asarray(image, dtype=float)
    sm = gaussian_filter1d(a, line_smooth, axis=1) if line_smooth > 0 else a
    grad = np.gradient(sm, axis=1)
    return np.sum(grad ** 2, axis=1)


def analyze_focus(image: np.ndarray, zvals: np.ndarray,
                  line_smooth: float = 1.0, row_smooth: float = 1.0,
                  edge_margin: int = 1, falloff_frac: float = 0.35) -> dict | None:
    """Find the focus ZonePlateZ from a focus-scan image (rows=Z, cols=line).

    Returns {focus_z, focus_row, confidence, in_range, edge_hint} or None. The focus is the
    smooth peak of the crispness-vs-Z curve; ``confidence`` (0-1) is how cleanly it turns
    over on both sides (see below).

    in_range distinguishes a genuine in-window focus from one whose optimum lies beyond the
    scanned Z. A true in-range focus rises to a peak and FALLS OFF on both sides; an
    out-of-range focus has its maximum pinned near a boundary with the curve still trending
    up to that edge (no falloff on that side). Detecting only a near-edge argmax is not
    enough — on real data the noisy peak can land a few rows shy of the boundary yet the
    curve never turns over. So in_range requires a peak that is both interior AND descends by
    at least ``falloff_frac`` of its dynamic range on each side; otherwise edge_hint names the
    side to extend the scan toward.
    """
    from scipy.ndimage import gaussian_filter1d
    a = np.asarray(image, dtype=float)
    if a.ndim != 2 or a.shape[0] < 3:
        return None
    z = np.asarray(zvals, dtype=float).ravel()
    n = a.shape[0]
    if z.size != n:
        return None

    curve = _focus_crispness(a, line_smooth=line_smooth)
    cs = gaussian_filter1d(curve, row_smooth) if row_smooth > 0 else curve
    i = int(np.argmax(cs))

    di = 0.0
    if 0 < i < n - 1:
        lo, mid, hi = cs[i - 1], cs[i], cs[i + 1]
        denom = lo - 2 * mid + hi
        if denom != 0:
            di = float(np.clip(0.5 * (lo - hi) / denom, -1.0, 1.0))
    pos = i + di

    # Bilateral-falloff test for out-of-range focus. Use a more heavily smoothed curve so
    # row-to-row noise can't masquerade as a turnover. The peak's dynamic range is its rise
    # above the curve's floor; on each side measure how far the curve drops back down.
    trend = gaussian_filter1d(curve, max(row_smooth, n * 0.05))
    ti = int(np.argmax(trend))
    floor = float(trend.min())
    rise = float(trend[ti]) - floor
    if rise <= 1e-12:
        left_drop = right_drop = 0.0
    else:
        left_drop = (float(trend[ti]) - float(trend[: ti + 1].min())) / rise
        right_drop = (float(trend[ti]) - float(trend[ti:].min())) / rise
    falls_low = left_drop >= falloff_frac    # curve descends toward the low-Z end
    falls_high = right_drop >= falloff_frac   # curve descends toward the high-Z end

    # Confidence is the smaller of the two side-falloffs (0-1): how cleanly the crispness
    # turns over into a real peak on BOTH sides. This is essentially the peak's topographic
    # prominence normalized by its dynamic range. It replaces the old MAD z-score
    # "prominence", which conflated noise level and the overall trend and so didn't track
    # focus quality (an out-of-range ramp could outscore a genuine in-range peak). ~0.5+ is
    # a clear peak; 0 means no turnover (focus at/beyond an edge).
    confidence = min(left_drop, right_drop)

    margin = max(edge_margin, int(round(0.05 * n)))
    interior = bool(margin <= i <= n - 1 - margin)
    in_range = bool(interior and falls_low and falls_high)

    if in_range:
        edge_hint = None
    elif not falls_high:
        edge_hint = "high-Z end"   # focus is at/beyond the high-Z edge — extend that way
    elif not falls_low:
        edge_hint = "low-Z end"
    else:
        edge_hint = "low-Z end" if i <= n // 2 else "high-Z end"

    focus_z = float(np.interp(pos, np.arange(n), z))

    return {"focus_z": focus_z, "focus_row": float(pos),
            "confidence": round(confidence, 2), "in_range": in_range,
            "edge_hint": edge_hint}


# ---------------------------------------------------------------------------
# AnomalyDetector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """Stateful anomaly checker for STXM scan metrics.

    Checks three rules in order of immediacy:
    1. intensity_drop  — current line mean is > zscore_threshold sigma below
                         the rolling baseline (sudden events: beam dump, shutter)
    2. intensity_drift — linear slope of last drift_window means is more
                         negative than drift_threshold (fractional per line)
    3. focus_decline   — focus score drops > focus_decline_pct % vs previous
                         region (thermal drift of zone plate / stage)

    All thresholds are configurable via the ``anomaly`` config dict.
    """

    def __init__(self, cfg: dict):
        self.zscore_threshold = cfg.get("zscore_threshold", 3.0)
        self.zscore_window = cfg.get("zscore_window", 20)
        self.drift_window = cfg.get("drift_window", 15)
        self.drift_threshold = cfg.get("drift_threshold", -0.05)
        self.focus_decline_pct = cfg.get("focus_decline_pct", 30.0)
        self.pct_threshold = cfg.get("pct_threshold", 0.10)

        self._baseline: deque = deque(maxlen=self.zscore_window)
        self._prev_focus: float | None = None

    def check_line(self, line_mean: float) -> dict | None:
        """Check a new line mean. Returns anomaly dict or None."""
        self._baseline.append(line_mean)

        min_baseline = max(5, self.zscore_window // 2)
        if len(self._baseline) < min_baseline + 1:
            return None

        history = np.array(list(self._baseline)[:-1])
        mu = float(np.mean(history))
        sigma = float(np.std(history))

        if sigma < 1e-9:
            return None

        z = (line_mean - mu) / sigma

        pct_drop = (mu - line_mean) / mu if mu > 0 else 0.0
        if z < -self.zscore_threshold and pct_drop >= self.pct_threshold:
            severity = "critical" if z < -self.zscore_threshold * 1.5 else "warn"
            return {
                "type": "intensity_drop",
                "severity": severity,
                "line_mean": round(line_mean, 4),
                "baseline_mean": round(mu, 4),
                "baseline_std": round(sigma, 4),
                "z_score": round(z, 2),
            }

        if len(self._baseline) >= self.drift_window:
            recent = np.array(list(self._baseline)[-self.drift_window:])
            x = np.arange(len(recent), dtype=float)
            slope = float(np.polyfit(x, recent, 1)[0])
            if mu > 0 and (slope / mu) < self.drift_threshold:
                return {
                    "type": "intensity_drift",
                    "severity": "warn",
                    "slope_per_line": round(slope, 6),
                    "fractional_slope": round(slope / mu, 4),
                    "baseline_mean": round(mu, 4),
                }

        return None

    def check_focus(self, focus_score: float) -> dict | None:
        """Check focus score after a region completes. Returns anomaly or None."""
        if self._prev_focus is None or self._prev_focus < 1e-9:
            self._prev_focus = focus_score
            return None

        prev = self._prev_focus
        pct_change = (focus_score - prev) / prev * 100.0
        self._prev_focus = focus_score

        if pct_change < -self.focus_decline_pct:
            return {
                "type": "focus_decline",
                "severity": "warn",
                "focus_score": round(focus_score, 4),
                "prev_focus_score": round(prev, 4),
                "pct_change": round(pct_change, 1),
            }
        return None

    def reset(self) -> None:
        self._baseline.clear()
        self._prev_focus = None


# ---------------------------------------------------------------------------
# AgentInterface
# ---------------------------------------------------------------------------

class AgentInterface:
    """Async interface to a configurable LLM API for anomaly diagnosis.

    Calls are:
    - Debounced: at most one call per ``cooldown_seconds``
    - Non-blocking: uses asyncio.create_task + run_in_executor
    - Context-aware: receives recent events from EventRecorder

    Supported providers (set via main_config["intelligence"]["agent"]["provider"]):
      "anthropic"  — Anthropic Claude API (requires ANTHROPIC_API_KEY or api_key_env)
      "openai"     — OpenAI or any compatible endpoint; set base_url for local LLMs
                     (requires OPENAI_API_KEY or api_key_env)
    """

    _PROVIDER_DEFAULT_ENV = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai":    "OPENAI_API_KEY",
    }

    def __init__(self, main_config: dict):
        cfg = main_config.get("intelligence", {}).get("agent", {})
        self.model = cfg.get("model", "claude-haiku-4-5-20251001")
        self.cooldown_seconds = cfg.get("cooldown_seconds", 60)
        self.max_context_events = cfg.get("max_context_events", 30)
        self.provider = cfg.get("provider", "anthropic")
        self.base_url = cfg.get("base_url", None)
        default_env = self._PROVIDER_DEFAULT_ENV.get(self.provider, "OPENAI_API_KEY")
        self._api_key_env = cfg.get("api_key_env", default_env)
        self._last_call_time = 0.0
        self._client = None

    def _get_client(self):
        import os
        if self._client is not None:
            return self._client
        api_key = os.environ.get(self._api_key_env) if self._api_key_env else None
        if self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
        else:
            import openai
            kwargs = {}
            if api_key:
                kwargs["api_key"] = api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.OpenAI(**kwargs)
        return self._client

    def in_cooldown(self) -> bool:
        return time.time() - self._last_call_time < self.cooldown_seconds

    async def dispatch(self, anomaly: dict, recent_events: list,
                       publish_fn=None) -> dict | None:
        """Call the agent asynchronously. Returns suggestion dict or None."""
        if self.in_cooldown():
            return None
        self._last_call_time = time.time()

        prompt = self._format_prompt(anomaly, recent_events)
        loop = asyncio.get_event_loop()
        try:
            text = await loop.run_in_executor(None, self._call_api, prompt)
        except Exception as exc:
            text = f"[Agent unavailable: {exc}]"
        # The API can return None/empty content; keep 'suggestion' a string so every
        # consumer (GUI display, task-agent alarm queue) is safe.
        if not text:
            text = "[Agent returned no diagnosis text]"

        suggestion = {
            "type": "intelligence_suggestion",
            "anomaly_type": anomaly.get("type"),
            "severity": anomaly.get("severity"),
            "suggestion": text,
            "timestamp": time.time(),
        }

        if publish_fn is not None:
            try:
                publish_fn(suggestion)
            except Exception:
                pass

        return suggestion

    def _call_api(self, prompt: str) -> str:
        client = self._get_client()
        if self.provider == "anthropic":
            msg = client.messages.create(
                model=self.model,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        else:
            msg = client.chat.completions.create(
                model=self.model,
                max_tokens=256,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
            )
            return msg.choices[0].message.content

    async def query(self, text: str, recent_events: list,
                    publish_fn=None) -> dict | None:
        """Handle a free-form operator query. Not subject to cooldown."""
        prompt = self._format_query_prompt(text, recent_events)
        loop = asyncio.get_event_loop()
        try:
            response_text = await loop.run_in_executor(None, self._call_api, prompt)
        except Exception as exc:
            response_text = f"[Agent unavailable: {exc}]"

        result = {
            "type": "intelligence_suggestion",
            "anomaly_type": "user_query",
            "query": text,
            "suggestion": response_text,
            "timestamp": time.time(),
        }
        if publish_fn is not None:
            try:
                publish_fn(result)
            except Exception:
                pass
        return result

    def _format_query_prompt(self, text: str, recent_events: list) -> str:
        event_lines = []
        t0 = recent_events[0].get("timestamp", 0) if recent_events else 0
        for e in recent_events[-self.max_context_events:]:
            elapsed = f"+{e.get('timestamp', t0) - t0:.1f}s"
            etype = e.get("type", "?")
            details = {k: v for k, v in e.items() if k not in ("type", "timestamp")}
            detail_str = "  ".join(f"{k}={v}" for k, v in details.items())
            event_lines.append(f"  {elapsed:>8}  [{etype}]  {detail_str}")

        events_text = "\n".join(event_lines) if event_lines else "  (none)"
        return (
            f"Recent session events (oldest first):\n{events_text}\n\n"
            f"Operator question: {text}\n\n"
            f"Please answer concisely based on the event history and your "
            f"knowledge of STXM instrumentation."
        )

    def _format_prompt(self, anomaly: dict, recent_events: list) -> str:
        event_lines = []
        for e in recent_events[-self.max_context_events:]:
            ts = e.get("timestamp", 0)
            elapsed = f"+{ts - recent_events[0].get('timestamp', ts):.1f}s" if recent_events else ""
            etype = e.get("type", "?")
            details = {k: v for k, v in e.items() if k not in ("type", "timestamp")}
            detail_str = "  ".join(f"{k}={v}" for k, v in details.items())
            event_lines.append(f"  {elapsed:>8}  [{etype}]  {detail_str}")

        events_text = "\n".join(event_lines) if event_lines else "  (none)"
        anomaly_lines = "\n".join(f"  {k}: {v}" for k, v in anomaly.items())

        return (
            f"Anomaly detected during scan:\n{anomaly_lines}\n\n"
            f"Recent session events (oldest first):\n{events_text}\n\n"
            f"What is the most likely cause and what corrective action should "
            f"the operator take? Respond in 2-3 sentences, being specific about "
            f"the likely cause given the event history."
        )


# ---------------------------------------------------------------------------
# IntelligenceModule
# ---------------------------------------------------------------------------

class IntelligenceModule:
    """Passive observer attached to dataHandler.

    Responsibilities
    ----------------
    - Compute per-line and per-frame image quality metrics
    - Detect anomalies via AnomalyDetector
    - Dispatch agent calls via AgentInterface when anomalies occur
    - Record all events and metrics in EventRecorder

    Usage
    -----
    Instantiate once and attach to the dataHandler::

        dh.intelligence = IntelligenceModule(main_config, event_recorder, publish_fn)

    publish_fn receives suggestion dicts and should forward them via ZMQ.
    """

    def __init__(self, main_config: dict, event_recorder: EventRecorder | None = None,
                 publish_fn=None):
        cfg = main_config.get("intelligence", {})
        self.enabled: bool = bool(cfg.get("enabled", False))
        self._recorder = (
            event_recorder if event_recorder is not None
            else EventRecorder(channels=cfg.get("channels", _DEFAULT_CHANNELS))
        )
        self._detector = AnomalyDetector(cfg.get("anomaly", {}))
        agent_cfg = cfg.get("agent", {})
        self._agent = AgentInterface(main_config) if agent_cfg.get("enabled", False) else None
        self._publish_fn = publish_fn
        self._line_means: list[float] = []
        self._current_scan_type: str | None = None
        # Geometry cached from on_scan_start for use in on_region_complete
        self._scan_regions: dict = {}
        # COM offset threshold as a fraction of the smaller FOV dimension
        recom_cfg = cfg.get("recommendations", {})
        self._offcenter_threshold_fov: float = float(
            recom_cfg.get("offcenter_threshold_fov", 0.2)
        )
        # Low-SNR feature-detection conditioning for the Otsu COM (see image_com /
        # otsu_absorption_mask).  Tunable per beamline via the recommendations config.
        self._com_smooth_sigma: float = float(recom_cfg.get("com_smooth_sigma", 2.0))
        self._com_despike: bool = bool(recom_cfg.get("com_despike", True))
        self._com_min_separation: float = float(recom_cfg.get("com_min_separation", 0.0))
        # Two-energy elemental-map analysis (e.g. Fe edge / pre-edge particle finding).
        self._two_energy_enabled: bool = bool(recom_cfg.get("two_energy_analysis", True))
        # Focus-scan analysis (OSA / sample focus): find the focus ZonePlateZ by per-row crispness.
        self._focus_enabled: bool = bool(recom_cfg.get("focus_analysis", True))
        self._fe_smooth_sigma: float = float(recom_cfg.get("fe_smooth_sigma", 2.0))
        self._fe_min_separation: float = float(recom_cfg.get("fe_min_separation", 3.0))
        self._fe_min_area: int = int(recom_cfg.get("fe_min_area", 4))
        self._fe_max_particles: int = int(recom_cfg.get("fe_max_particles", 20))

    @property
    def recorder(self) -> EventRecorder:
        return self._recorder

    # ------------------------------------------------------------------
    # Hooks called from dataHandler
    # ------------------------------------------------------------------

    def on_scan_start(self, scan: dict) -> None:
        self._line_means = []
        self._current_scan_type = scan.get("scan_type")
        self._scan_regions = scan.get("scan_regions", {})
        self._detector.reset()
        self._recorder.record(
            "events", "scan_start",
            scan_type=self._current_scan_type,
            scan_id=scan.get("file_name"),
        )

    def on_scan_data(self, scanInfo: dict) -> None:
        mode = scanInfo.get("mode", "")
        metrics: dict = {}
        if mode == "continuousLine":
            metrics = self._line_metrics(scanInfo)
            if metrics:
                anomaly = self._detector.check_line(metrics["line_mean"])
                if anomaly:
                    self._handle_anomaly(anomaly, scanInfo)
        elif mode in ("continuousSpiral", "point", "ptychographyGrid", "ptychographySpiral"):
            metrics = self._point_metrics(scanInfo)

        if metrics:
            self._recorder.record(
                "metrics", "scan_data",
                mode=mode,
                region=scanInfo.get("scanRegion"),
                energy_index=scanInfo.get("energyIndex"),
                line_index=scanInfo.get("lineIndex"),
                **metrics,
            )
            scanInfo["intelligence"] = metrics

    def on_region_complete(self, image: np.ndarray, scan_type: str,
                           region: str, energy_index: int) -> None:
        if image is None or image.size == 0:
            return
        arr = np.asarray(image, dtype=float)
        metrics = {
            "frame_mean": float(np.mean(arr)),
            "frame_min": float(np.min(arr)),
            "frame_max": float(np.max(arr)),
            "frame_std": float(np.std(arr)),
            "focus_score": _laplacian_variance(arr),
        }
        if self._line_means:
            metrics["line_mean_trend"] = self._line_means.copy()
            self._line_means = []

        self._recorder.record(
            "events", "region_complete",
            scan_type=scan_type,
            region=region,
            energy_index=energy_index,
            **metrics,
        )

        focus_anomaly = self._detector.check_focus(metrics["focus_score"])
        if focus_anomaly:
            self._handle_anomaly(focus_anomaly)

        # Focus scans: find the focus ZonePlateZ and post a calibration recommendation.
        if self._focus_enabled and "Focus" in (scan_type or "") and arr.ndim == 2:
            self._analyze_focus(arr, scan_type, region)
            return  # a focus image is not a feature image — skip the centering check

        # Centering check on the first energy frame of each region.
        # Subsequent frames of a stack are not re-checked to avoid spam.
        if energy_index == 0:
            self._check_centering(arr, region)

    def on_region_stack(self, stack: np.ndarray, energies, scan_type: str,
                        region: str) -> None:
        """Full multi-energy region stack hook (shape (nE, ny, nx)).

        For a two-energy scan (the typical 'find iron particles' intent) this computes the
        edge/pre-edge elemental map and runs particle finding, then reports the result.
        """
        if not self._two_energy_enabled:
            return
        arr = np.asarray(stack, dtype=float)
        if arr.ndim != 3 or arr.shape[0] != 2:
            return  # only two-energy handled for now; multi-energy RGB maps are future work
        # Defensive: skip until every energy frame holds data.  endOfRegion fires once per
        # energy pass, so an early call would see later frames still zero-filled.
        if any(not np.any(arr[i]) for i in range(arr.shape[0])):
            return
        try:
            self._analyze_two_energy(arr, energies, scan_type, region)
        except Exception as exc:  # analysis must never break the scan pipeline
            err = {
                "type": "task_recommendation",
                "subtype": "two_energy_error",
                "region": region,
                "reason": f"Two-energy analysis failed in {region}: {exc!r}",
                "timestamp": time.time(),
            }
            self._recorder.record("events", "task_recommendation", **err)
            if self._publish_fn is not None:
                try:
                    self._publish_fn(err)
                except Exception:
                    pass

    def on_scan_complete(self, scan_id: str | None = None) -> None:
        self._recorder.record("events", "scan_complete", scan_id=scan_id)
        self._line_means = []

    def on_scan_aborted(self, scan_id: str | None = None) -> None:
        self._recorder.record("events", "scan_aborted", scan_id=scan_id)
        self._line_means = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pixel_to_um(self, row: float, col: float, ny: int, nx: int,
                     geom: dict) -> tuple[float, float]:
        """Map a pixel (row, col) to motor coordinates (µm) using the region geometry."""
        x_center = float(geom.get("xCenter", 0.0))
        y_center = float(geom.get("yCenter", 0.0))
        x_range = float(geom.get("xRange", 1.0))
        y_range = float(geom.get("yRange", 1.0))
        x = x_center + (col / max(nx - 1, 1) - 0.5) * x_range
        y = y_center + (row / max(ny - 1, 1) - 0.5) * y_range
        return x, y

    def _analyze_two_energy(self, stack: np.ndarray, energies, scan_type: str,
                            region: str) -> None:
        """Compute the edge/pre-edge map, find particles, and report (no scan action yet)."""
        from pystxmcontrol.utils.image import (
            two_energy_map, otsu_absorption_mask, find_feature_boxes,
        )

        # Orient frames by energy: pre-edge = lower energy, edge = higher energy.
        e = np.asarray(energies, dtype=float) if energies is not None else None
        if e is not None and e.size == 2 and e[0] > e[1]:
            pre, edge = stack[1], stack[0]
            e_pre, e_edge = float(e[1]), float(e[0])
        else:
            pre, edge = stack[0], stack[1]
            e_pre = float(e[0]) if e is not None and e.size == 2 else None
            e_edge = float(e[1]) if e is not None and e.size == 2 else None

        diff, valid = two_energy_map(pre, edge)
        mask = otsu_absorption_mask(
            diff, dark=False, valid=valid,
            smooth_sigma=self._fe_smooth_sigma,
            min_separation=self._fe_min_separation,
        )
        boxes = find_feature_boxes(
            mask, min_area=self._fe_min_area, max_features=self._fe_max_particles,
        )

        ny, nx = diff.shape
        geom = self._scan_regions.get(region, {})
        x_range = float(geom.get("xRange", 1.0))
        y_range = float(geom.get("yRange", 1.0))
        particles = []
        for b in boxes:
            x, y = self._pixel_to_um(b["centroid_row"], b["centroid_col"], ny, nx, geom)
            # physical extent of the particle bounding box (so follow-up scans can be sized to it)
            w_um = (b["maxc"] - b["minc"]) * x_range / max(nx, 1)
            h_um = (b["maxr"] - b["minr"]) * y_range / max(ny, 1)
            particles.append({
                "center_um": {"x": round(x, 3), "y": round(y, 3)},
                "size_um": {"x": round(w_um, 3), "y": round(h_um, 3)},
                "area_px": b["area_px"],
                "bbox_px": [b["minr"], b["minc"], b["maxr"], b["maxc"]],
            })

        result = {
            # Published as a task_recommendation so it flows through the existing GUI/agent
            # routing (main_controller -> pending_recommendations -> get_intelligence_recommendations
            # and the intelligence widget).  The subtype distinguishes it from recentre recs.
            "type": "task_recommendation",
            "subtype": "two_energy_particles",
            "scan_type": scan_type,
            "region": region,
            "edge_energy_eV": round(e_edge, 2) if e_edge is not None else None,
            "preedge_energy_eV": round(e_pre, 2) if e_pre is not None else None,
            "particle_count": len(particles),
            "particles": particles,
            "reason": (
                f"Two-energy map ("
                + (f"edge {e_edge:.1f} eV / pre-edge {e_pre:.1f} eV" if e_edge is not None
                   else "edge / pre-edge")
                + f") in {region}: found {len(particles)} candidate particle(s)."
                + (f" Largest at x={particles[0]['center_um']['x']:.2f}, "
                   f"y={particles[0]['center_um']['y']:.2f} µm." if particles else "")
            ),
            "timestamp": time.time(),
        }

        self._recorder.record("events", "task_recommendation", **result)
        if self._publish_fn is not None:
            try:
                self._publish_fn(result)
            except Exception:
                pass

    def _analyze_focus(self, image: np.ndarray, scan_type: str, region: str) -> None:
        """Find the focus ZonePlateZ and publish a focus-calibration recommendation.

        image is a focus frame (rows = ZonePlateZ steps, cols = position along the line). The
        correction is the DELTA of the measured focus from the scan centre (the assumed-correct
        Z): delta = focus_z - z_center. This delta is frame-independent (any A0 shift is constant
        on both terms and cancels), so the agent applies it directly to the ZonePlateZ offset
        (new_offset = current_offset - delta), no A0 bookkeeping needed.
        """
        geom = self._scan_regions.get(region)
        if geom is None:
            return
        z_start = geom.get("zStart")
        z_stop = geom.get("zStop")
        z_points = int(geom.get("zPoints", image.shape[0]) or image.shape[0])
        z_center = geom.get("zCenter")
        if z_start is None or z_stop is None or z_points < 3:
            return
        if z_center is None:
            z_center = (float(z_start) + float(z_stop)) / 2.0

        zvals = np.linspace(float(z_start), float(z_stop), z_points)
        if zvals.size != image.shape[0]:
            return  # geometry/image mismatch — don't guess

        res = analyze_focus(image, zvals)
        if res is None:
            return

        delta = res["focus_z"] - float(z_center)
        recommendation = {
            "type": "task_recommendation",
            "subtype": "focus",
            "scan_type": scan_type,
            "region": region,
            "focus_z": round(res["focus_z"], 4),
            "scan_center_z": round(float(z_center), 4),
            # Apply to ZonePlateZ: new_offset = current_offset - delta_z (frame-independent).
            "delta_z": round(delta, 4),
            "correction_magnitude_um": round(abs(delta), 4),
            "confidence": res["confidence"],
            "in_range": res["in_range"],
            "edge_hint": res["edge_hint"],
            "reason": (
                f"Focus found at ZonePlateZ={res['focus_z']:.3f} "
                f"({delta:+.3f} µm from the scan centre {float(z_center):.3f}); "
                f"confidence {res['confidence']:.2f} (0-1, ~0.5+ is a clear peak)." +
                ("" if res["in_range"] else
                 f" WARNING: focus is at the {res['edge_hint']} of the scan — it may be outside "
                 f"the Z range; rescan shifted that way before trusting this.")
            ),
            "timestamp": time.time(),
        }
        self._recorder.record("events", "task_recommendation", **recommendation)
        if self._publish_fn is not None:
            try:
                self._publish_fn(recommendation)
            except Exception:
                pass

    def _check_centering(self, image: np.ndarray, region: str) -> None:
        """Compute Otsu-mask COM and publish a recentre recommendation if off-centre."""
        geom = self._scan_regions.get(region)
        if geom is None:
            return

        x_center = float(geom.get("xCenter", 0.0))
        y_center = float(geom.get("yCenter", 0.0))
        x_range  = float(geom.get("xRange",  1.0))
        y_range  = float(geom.get("yRange",  1.0))
        ny, nx = image.shape[:2]

        from pystxmcontrol.utils.image import image_com
        result = image_com(
            image, x_center, y_center, x_range, y_range,
            smooth_sigma=self._com_smooth_sigma,
            despike=self._com_despike,
            min_separation=self._com_min_separation,
        )
        if result is None:
            return
        com_x, com_y = result

        dx = com_x - x_center
        dy = com_y - y_center
        offset_mag = float(np.sqrt(dx ** 2 + dy ** 2))

        fov_ref = min(x_range, y_range)
        if fov_ref <= 0 or offset_mag < self._offcenter_threshold_fov * fov_ref:
            return

        recommendation = {
            "type": "task_recommendation",
            "subtype": "recentre",
            "scan_type": self._current_scan_type,
            "region": region,
            "current_center_um": {"x": round(x_center, 3), "y": round(y_center, 3)},
            "recommended_center_um": {"x": round(com_x, 3), "y": round(com_y, 3)},
            "offset_um": {
                "x": round(dx, 3),
                "y": round(dy, 3),
                "magnitude": round(offset_mag, 3),
            },
            "reason": (
                f"Feature centre-of-mass is {offset_mag:.1f} µm from the scan centre "
                f"(dx={dx:+.1f}, dy={dy:+.1f} µm). "
                f"Suggest updating x_center to {com_x:.3f} and y_center to {com_y:.3f}."
            ),
            "timestamp": time.time(),
        }

        self._recorder.record("events", "task_recommendation", **recommendation)

        if self._publish_fn is not None:
            try:
                self._publish_fn(recommendation)
            except Exception:
                pass

    def _handle_anomaly(self, anomaly: dict, scanInfo: dict | None = None) -> None:
        self._recorder.record(
            "events", "anomaly",
            scan_type=self._current_scan_type,
            region=scanInfo.get("scanRegion") if scanInfo else None,
            energy_index=scanInfo.get("energyIndex") if scanInfo else None,
            anomaly=anomaly,
        )
        if self._agent and not self._agent.in_cooldown():
            recent = self._recorder.recent("events", 30)
            asyncio.create_task(
                self._agent.dispatch(anomaly, recent, publish_fn=self._publish_fn)
            )

    def _line_metrics(self, scanInfo: dict) -> dict:
        data = scanInfo.get("data", {}).get("default")
        if data is None:
            return {}
        arr = np.asarray(data, dtype=float)
        mean = float(np.mean(arr))
        self._line_means.append(mean)
        return {"line_mean": mean}

    def _point_metrics(self, scanInfo: dict) -> dict:
        data = scanInfo.get("data", {}).get("default")
        if data is None:
            return {}
        arr = np.asarray(data)
        val = float(arr.flat[0]) if arr.size else 0.0
        return {"point_value": val}

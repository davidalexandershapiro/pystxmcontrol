# Intelligence Module

The intelligence module adds passive anomaly monitoring and AI-assisted diagnosis to
a running STXM session.  It lives entirely on the server side and is opt-in: nothing
runs unless `intelligence.enabled = true` in `config/main.json`.

---

## Architecture overview

```
dataHandler
    │
    ├─ on_scan_start()     ──►  EventRecorder  ("events" channel)
    ├─ on_scan_data()      ──►  AnomalyDetector  ──►  EventRecorder ("metrics")
    │                               │
    │                         anomaly detected?
    │                               │
    │                               ▼
    │                          AgentInterface  (async, non-blocking)
    │                               │
    │                               ▼
    │                         LLM API call  (Anthropic or OpenAI-compatible)
    │                               │
    │                               ▼
    ├─ on_region_complete() ──►  EventRecorder ("events")  +  ZMQ publish
    └─ on_scan_complete()   ──►  EventRecorder ("events")
```

The `IntelligenceModule` is attached to `dataHandler` at startup in `controller.py`:

```python
self.dataHandler.intelligence = IntelligenceModule(
    self.main_config,
    self._event_recorder,
    publish_fn=self.dataHandler.zmq_publisher.publish_stxm_data,
)
```

Agent suggestions arrive at the GUI as ZMQ messages on the existing data channel and
are routed by `main_controller._handle_monitor_message` to `IntelligenceWidget`.

---

## Components

### EventRecorder

A two-channel rolling log:

| Channel   | Default max | Contents |
|-----------|-------------|----------|
| `events`  | 500         | Scan lifecycle, anomalies, agent suggestions, motor moves, shutter changes |
| `metrics` | 200         | Per-line mean, per-point value |

Named channels avoid the problem of high-frequency per-line metrics crowding out
sparse lifecycle events in a single queue.

Key methods:

```python
recorder.record("events", "shutter_changed", mode="auto", during_scan=True)
recorder.recent("events", n=30)   # last 30 events, oldest first
recorder.len("events")
recorder.clear()
```

Events recorded automatically include: `scan_start`, `scan_complete`, `scan_aborted`,
`region_complete`, `anomaly`, `intelligence_suggestion`, `shutter_changed`,
`motor_moved`, `daq_timeout`, `scan_cancelled`, `scan_paused`, `scan_resumed`,
`manual_motor_move`, `manual_measurement`.

### AnomalyDetector

Three rules checked in order:

1. **`intensity_drop`** — z-score of current line mean vs rolling baseline.
   Fires when the current line is more than `zscore_threshold` σ below the
   preceding `zscore_window` lines.  Severity is `critical` if the drop exceeds
   1.5× the threshold, `warn` otherwise.

2. **`intensity_drift`** — linear slope across the last `drift_window` line means,
   normalised by the baseline mean.  Fires when the fractional slope falls below
   `drift_threshold` (negative = downward trend).

3. **`focus_decline`** — Laplacian variance of the completed region image compared
   to the previous region.  Fires when the focus score drops more than
   `focus_decline_pct` percent.

All thresholds are configurable (see [Configuration](#configuration)).

### AgentInterface

Wraps a blocking LLM API call in `asyncio.run_in_executor` so it never stalls the
scan event loop.  Anomaly calls are debounced by `cooldown_seconds`; operator queries
bypass the cooldown entirely.

Two entry points:

- `dispatch(anomaly, recent_events, publish_fn)` — called automatically on anomaly
  detection.  Formats a prompt including the anomaly details and the last
  `max_context_events` session events, then publishes the response.

- `query(text, recent_events, publish_fn)` — called from the `agent_query` server
  command when the operator types a question in the Agent tab.

### IntelligenceModule

Thin coordinator.  Implements the four hooks called by `dataHandler`:

| Hook | When called |
|------|-------------|
| `on_scan_start(scan)` | Scan thread begins; resets detector baseline |
| `on_scan_data(scanInfo)` | Each line/point complete; runs anomaly checks |
| `on_region_complete(image, ...)` | Region saved; computes frame metrics and focus check |
| `on_scan_complete(scan_id)` | Scan thread exits |

---

## GUI integration

`IntelligenceWidget` is added as an "Agent" tab in the right-hand tab widget.  It
displays a scrolling chat-style history and a query input line.

**Action links** — each anomaly suggestion includes clickable inline buttons that map
to instrument commands:

| Anomaly type      | Available actions |
|-------------------|------------------|
| `intensity_drop`  | Open Shutter, Abort Scan, Clear Alert |
| `intensity_drift` | Abort Scan, Clear Alert |
| `focus_decline`   | Move to Focus, Clear Alert |
| `daq_timeout`     | Clear Alert |

**Alarm banner** — when a `critical` anomaly arrives, the proposal status banner
turns red with a short label ("Beam Lost", "Signal Drifting", etc.).  Clicking
"Clear Alert" in the Agent tab restores the banner to its normal proposal state.

---

## Configuration

All settings live under `intelligence` in `config/main.json`.

```json
"intelligence": {
    "enabled": false,
    "channels": {
        "events": 500,
        "metrics": 200
    },
    "anomaly": {
        "zscore_threshold": 3.0,
        "zscore_window": 20,
        "drift_window": 15,
        "drift_threshold": -0.05,
        "focus_decline_pct": 30.0
    },
    "agent": {
        "enabled": false,
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "base_url": null,
        "api_key_env": "ANTHROPIC_API_KEY",
        "cooldown_seconds": 60,
        "max_context_events": 30
    }
}
```

Set `intelligence.enabled = true` to activate event recording and anomaly detection.
Set `intelligence.agent.enabled = true` additionally to enable LLM calls.

### Anomaly parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `zscore_threshold` | 3.0 | Sigma threshold for intensity drop detection |
| `zscore_window` | 20 | Number of preceding lines used to build the baseline |
| `drift_window` | 15 | Lines used to fit the drift slope |
| `drift_threshold` | -0.05 | Fractional slope per line below which drift fires |
| `focus_decline_pct` | 30.0 | % drop in focus score between regions to trigger alert |

### API providers

**Anthropic (default)**

```json
"provider": "anthropic",
"model": "claude-haiku-4-5-20251001",
"api_key_env": "ANTHROPIC_API_KEY"
```

**OpenAI**

```json
"provider": "openai",
"model": "gpt-4o-mini",
"base_url": null,
"api_key_env": "OPENAI_API_KEY"
```

**Local LLM (Ollama, LM Studio, or any OpenAI-compatible server)**

```json
"provider": "openai",
"model": "llama3",
"base_url": "http://localhost:11434/v1",
"api_key_env": null
```

`api_key_env` names the environment variable that holds the API key.  Set it to
`null` for local endpoints that require no authentication.  `base_url` overrides the
default endpoint; leave it `null` to use the provider's official API.

---

## Operational events wired into the recorder

Beyond the automatic scan-lifecycle events, the following operations record into the
`events` channel to give the agent useful context:

| Source | Event type | Key fields |
|--------|-----------|------------|
| `server.setGate` | `shutter_changed` | `mode` (open/close/auto), `during_scan` |
| `server.cancel` | `scan_cancelled` | — |
| `server.pause` | `scan_paused` / `scan_resumed` | — |
| `server.moveMotor` (idle) | `manual_motor_move` | `motor`, `target` |
| `server.get_data` | `manual_measurement` | `daq`, `dwell`, `shutter` |
| `scan_utils.doFlyscanLine` (timeout) | `daq_timeout` | `line_index` |
| `controller.moveMotor` (Energy, ZonePlateZ, SampleZ) | `motor_moved` | `motor`, `target`, `actual`, `during_scan` |

---

## Adding a new anomaly rule

1. Add detection logic to `AnomalyDetector` returning a dict with at least
   `{"type": "<name>", "severity": "warn"|"critical", ...}`.
2. Call it from `IntelligenceModule.on_scan_data` or `on_region_complete`.
3. Add an entry to `_ANOMALY_ACTIONS` in `intelligence_widget.py` to provide
   clickable remediation actions in the GUI.
4. Optionally add a label to `_ALARM_TEXT` in `mainwindow_mvc.py` for the
   critical alarm banner.

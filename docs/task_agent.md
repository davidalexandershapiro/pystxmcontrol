# Task Agent

The task agent is a goal-directed instrument controller powered by an
OpenAI-compatible LLM.  Unlike the [Intelligence Module](intelligence.md), which
passively monitors a running scan and reacts to anomalies, the task agent actively
plans and executes multi-step workflows in response to high-level user goals entered
in natural language.

Enable it by setting `task_agent.enabled = true` in `config/main.json`.

---

## Contrast with the Intelligence Module

| | Intelligence Module | Task Agent |
|---|---|---|
| **Role** | Passive monitor | Active controller |
| **Trigger** | Anomaly or operator question | Explicit user goal |
| **LLM calls** | One call per anomaly/question | Iterative tool-use loop |
| **State** | Stateless per call | Persistent conversation history |
| **GUI input** | Single-line query box | Same widget, multi-turn chat |
| **Typical use** | "Why did signal drop?" | "Find a particle and image it at the Fe edge" |

---

## Architecture

```
IntelligenceWidget (GUI)
    │  user types goal / "Stop" / "New Topic"
    │
    ▼
MainController
    │  run_task(goal)
    │
    ▼
TaskAgentThread  (QThread)
    │  runs agent.run() off the Qt main thread
    │  emits: task_agent_status, task_agent_done, task_agent_running
    │
    ▼
TaskAgent.run()
    │
    ├─ append user message to _messages
    │
    └─ loop (max_iterations):
           │
           ├─ LLM call  (OpenAI-compatible API)
           │       model sees: system prompt + full conversation history + tool schemas
           │
           ├─ finish_reason == "tool_calls"?
           │       │
           │       └─ ToolSet.dispatch(name, args)
           │               │
           │               ├─ get_safety_instructions / get_config
           │               ├─ get_motor_position / move_motor
           │               ├─ update_scan / start_scan
           │               ├─ get_scan_status / get_last_scan_stats
           │               ├─ find_particles / start_multiregion_scan
           │               └─ read_daq
           │
           └─ finish_reason == "stop"  →  return final text
```

The loop runs entirely in `TaskAgentThread` so it never blocks the Qt event loop.
Status lines and the final response are delivered back to the GUI via Qt signals.

---

## Components

### TaskAgent (`controller/task_agent/agent.py`)

Owns the conversation history and the LLM client.  One instance persists for the
lifetime of the application; its `_messages` list accumulates across `run()` calls
so multi-turn goals work naturally.

Key methods:

| Method | Purpose |
|--------|---------|
| `run(goal, publish_fn)` | Blocking tool-use loop.  Call in a worker thread. |
| `cancel()` | Sets a threading event; loop exits between LLM calls. |
| `reset_history()` | Clears `_messages`; next `run()` starts a fresh session. |

**Silent tools** — `get_safety_instructions` and `get_config` are called at session
start but suppressed from the GUI trace to reduce noise.  All other tool calls and
their truncated results are streamed to the GUI as status lines.

### ToolSet (`controller/task_agent/tools.py`)

All instrument-control logic lives here.  Each public method is one tool the LLM can
call.  `ToolSet` holds shared session state: the current scan definition, cached motor
and scan-type config, and particle regions from the last `find_particles()` call.

At construction, `_seed_from_client()` eagerly populates the scan definition from
`client.main_config["lastScan"]` so `update_scan` works correctly even if the LLM
skips `get_config()` because the results are already in its conversation history.

### TaskAgentThread (`gui/controllers/main_controller.py`)

A `QThread` subclass that calls `agent.run()` and bridges its output back to Qt:

```python
class TaskAgentThread(QThread):
    message       = Signal(str)   # streaming trace line
    finished_text = Signal(str)   # final LLM response

    def run(self):
        result = self._agent.run(self._goal,
                                 publish_fn=lambda msg: self.message.emit(msg))
        self.finished_text.emit(result)
```

### GUI integration

The task agent shares `IntelligenceWidget` with the Intelligence Module.  Behaviour
changes based on whether a task is running:

| State | Send button | Input |
|-------|------------|-------|
| Idle | Blue "Send" | Active — type a goal |
| Running | Red "Stop" | Disabled — shows "Agent is running…" |

**New Topic** button calls `reset_history()` and clears the display, starting a
fresh session without restarting the application.

Tool calls appear as monospace trace lines in the chat.  The final LLM response
is rendered in a green box.

---

## Tool reference

### Session setup (silent)

| Tool | Description |
|------|-------------|
| `get_safety_instructions()` | Returns motor safety rules and recommended workflows.  Called once at the start of every session. |
| `get_config()` | Fetches motor list, positions, and scan type configurations from the server.  Populates ToolSet caches. |

### Motors

| Tool | Key arguments | Description |
|------|--------------|-------------|
| `get_motor_position(axis)` | `axis` — motor name | Returns current position in µm (or degrees). |
| `move_motor(axis, pos)` | `axis`, `pos` | Moves the named motor to the target position.  Server enforces software limits. |

### Scan definition

| Tool | Key arguments | Description |
|------|--------------|-------------|
| `update_scan(**kwargs)` | See table below | Updates the pending scan definition.  Call with no arguments to inspect the current config. |
| `start_scan()` | — | Submits the current scan definition and starts acquisition. |
| `get_scan_status()` | — | Returns `"scanning"` or `"idle"`.  When idle and an image is available, hints to call `get_last_scan_stats()`. |
| `read_daq(daq, dwell, shutter)` | `dwell` ms | Takes a single-point intensity reading without a full scan.  Useful for checking beam before committing. |

**`update_scan` parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `scan_type` | string | Scan type name.  Common aliases are resolved automatically (see [Scan type aliases](#scan-type-aliases)). |
| `x_center`, `y_center` | number | Scan centre in µm |
| `x_range`, `y_range` | number | Scan extent in µm |
| `x_points`, `y_points` | integer | Pixel count |
| `dwell` | number | ms per pixel |
| `energy_start`, `energy_stop` | number | eV |
| `energy_points` | integer | |
| `energy_list` | array | Explicit energy list in eV (overrides start/stop/points) |
| `autofocus` | boolean | |
| `sample_description`, `comment` | string | |
| `proposal`, `experimenters` | string | |

### Image analysis

| Tool | Key arguments | Description |
|------|--------------|-------------|
| `get_last_scan_stats(daq)` | `daq` channel | Mean, std, contrast, darkest-pixel position, and dark-region centroid in µm.  The centroid is a good re-centre target for a zoom scan. |
| `find_particles(max_particles, daq)` | optional cap | Otsu thresholding + connected-component analysis on the last image to locate absorbing particles.  Returns per-particle scan regions in µm and stores them for `start_multiregion_scan()`. |
| `start_multiregion_scan()` | — | Submits one Image scan whose `scan_regions` are the particle regions found by `find_particles()`.  Inherits energy and dwell from the current scan definition. |

### Diagnostics

| Tool | Description |
|------|-------------|
| `get_toolset_debug()` | Dumps ToolSet internal state (cached scan types, current scan parameters).  Use when scan parameters look wrong. |

---

## Scan type aliases

Users routinely refer to multi-energy image scans as "stacks".  The agent resolves
these aliases automatically when `update_scan(scan_type=...)` is called:

| User phrase | Resolved scan type |
|-------------|-------------------|
| `"Image Stack"` | `"Image"` |
| `"STXM Stack"` | `"Image"` |
| `"Ptychography Stack"` | `"Ptychography Image"` |
| `"Ptycho Stack"` | `"Ptychography Image"` |

Add new aliases to `_SCAN_TYPE_ALIASES` in `tools.py`.

---

## Typical workflows

### Find and image a particle

```
User:  "Run a 50×50 µm overview scan at 710 eV, find any particles, 
        then run a high-resolution stack at the Fe L-edge on each one."

Agent: update_scan(x_range=50, y_range=50, energy_start=710, energy_stop=710,
                   energy_points=1, dwell=1)
       start_scan()
       get_scan_status()          # polls until idle
       find_particles()           # locates N regions
       update_scan(energy_start=700, energy_stop=730, energy_points=31, dwell=2)
       start_multiregion_scan()   # images all N particles as one scan
```

### Zoom in on the darkest feature

```
User:  "Scan the current area then zoom in on the darkest spot."

Agent: start_scan()
       get_scan_status()
       get_last_scan_stats()      # returns dark_region_centroid_um
       update_scan(x_center=<cx>, y_center=<cy>, x_range=5, y_range=5)
       start_scan()
```

### Move to a new sample position

```
User:  "Move SampleX to 10 µm and SampleY to -5 µm."

Agent: move_motor(axis="SampleX", pos=10)
       move_motor(axis="SampleY", pos=-5)
```

---

## Configuration

All settings live under `task_agent` in `config/main.json`:

```json
"task_agent": {
    "enabled": false,
    "model": "claude-opus-4-7",
    "max_iterations": 20,
    "provider": {
        "base_url": null,
        "api_key_env": "OPENAI_API_KEY"
    }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `false` | Set `true` to activate the task agent |
| `model` | `"claude-opus-4-7"` | Model identifier passed to the API |
| `max_iterations` | `20` | Maximum tool-call rounds before the agent gives up |
| `provider.api_key_env` | `"OPENAI_API_KEY"` | Environment variable holding the API key |
| `provider.base_url` | `null` | Override endpoint for local or alternative providers |

The task agent uses the OpenAI Python client with `base_url` override, so any
OpenAI-compatible server (Anthropic via the OpenAI adapter, Ollama, LM Studio, etc.)
works without code changes.

---

## Simulation

The test sample generator (`utils/test_sample.py`) supports a `"particles"` sample
type for end-to-end agent testing without beam.  Set `simulation.sample_type` in
`config/main.json`:

```json
"simulation": {
    "sample_type": "particles"
}
```

The particle world is a 500×500 µm field containing ~50 000 particles (0.5 µm
diameter, ~2.2 µm mean spacing) at deterministic positions seeded from a fixed RNG.
Half are material A and half material B, each with energy-dependent absorption read
from reference spectra in `utils/data/material_A.csv` and `material_B.csv`
(columns: energy eV, β, δ).  Panning and zooming always reveal the same particles at
the same absolute positions, so the agent's `move_motor` + `start_scan` workflow
produces spatially consistent results.

---

## Adding a new tool

1. Add a method to `ToolSet` in `tools.py`.  The method must accept only plain Python
   types and return a `str`.

2. Add an entry to `TOOL_SCHEMAS` following the OpenAI function-calling format.

3. If the tool should not appear in the GUI trace (e.g. it is setup/plumbing), add its
   name to `_SILENT_TOOLS` in `agent.py`.

The `dispatch` method in `ToolSet` resolves tool names to methods by name via
`getattr`, so no registration step is required beyond the two items above.

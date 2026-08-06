# AWG relative-motion spiral (`derivedPiezoWithAWG`)

## Why this exists

Bench testing (`scripts/testAWGSpiral.py`) showed the nPoint piezo controller treats the
Keysight 33500B AWG analogue waveform as a **relative offset added to its current commanded
position**, not an absolute position command. The existing spiral fly-scan
(`derived_spiral_image`) builds an *absolute* trajectory and lets the AWG driver bake the
trajectory centre into a DC bias — which the relative-summing nPoint then double-counts.

`derivedPiezoWithAWG` fixes this **without a new scan routine**. The *existing*
`derived_spiral_image` routine drives it unchanged. Two control paths reach the same
physical piezo:

- **nPoint digital** (`nptMotor`/`nptController`) sets the absolute scan-region **centre**.
- **AWG** (`keysightAWGController`) plays a **zero-centred dither** the nPoint sums onto that
  held centre.

For simple moves the driver behaves exactly like `derivedPiezo`. Only
`lineMode == "arbitrary"` trajectories use the AWG.

## How it works (code)

- `derivedPiezoWithAWG` subclasses `derivedPiezo`. Axis wiring:
  `axis1 = nPoint fine`, `axis2 = coarse`, `axis3 = AWG`. Keeping the nPoint as `axis1`
  means every inherited move/position method (`moveTo`, `getPos`, `decompose_range`, coarse
  tiling) is correct with no override.
- `update_trajectory` (arbitrary): reads the fine-only centre the nPoint is holding from the
  shared `nptController` (`getPos('x')`/`getPos('y')`), subtracts it to get the zero-centred
  dither, and calls `keysightAWGController.setup_xy(..., amplitude=(fs,fs), offset=(0,0))`.
- `keysightAWGController.setup_xy` accepts optional `amplitude`/`offset` that **fix** the
  normalization instead of deriving it per call. This is required so a spiral that
  `derived_spiral_image` splits into chunks (`totalSplit > 1`) keeps one centre and gain
  across chunks and stitches into a continuous figure; `offset=(0,0)` makes the AWG emit a
  pure zero-DC dither. The fixed full-scale amplitude is `axis3.config["maxValue"]` (µm);
  the 16-bit arb resolves a small dither on the full scale finely.
- `moveLine` (arbitrary): fires the AWG and reconstructs absolute fallback positions
  (`dither + fine_centre + coarse_offset`). When a USB-1808X position-readback DAQ is
  attached, `dataHandler.getLine` overwrites `line_positions` with the achieved positions
  from `aux_data`, so this fallback only matters without one.
- `setPositionTriggerOn/Off` **force the nPoint PIN6 position trigger OFF** in arbitrary mode
  (the DAQ is clocked solely by the AWG start pulse). They don't merely skip arming it — they
  actively disarm, so a stale trigger left by a prior nPoint digital scan can't emit spurious
  edges while the AWG dither sweeps the stage through the compare position. Ordinary nPoint
  line/raster flyscans on the same motor still arm PIN6 normally.
- `armLine`/`finishLine` raise — the AWG is **stage-master** (it emits its own start pulse),
  so the scan config **must** set `daq_master = false`.

## Required config

The repo's `config/motor.json` is the live MCL beamline config and is **not** modified. To
enable the AWG relative spiral, wire the following (leaf `units=1.0`/`offset=0.0` is required
so the nPoint centre and the trajectory arrays share one micron frame).

### `motor.json`

nPoint digital fine leaves:

```json
"nptFineX": {"type":"primary","axis":"x","driver":"nptMotor","controller":"nptController",
             "controllerID":"<nPoint FTDI address>","port":0,
             "units":1.0,"offset":0.0,"minValue":-50.0,"maxValue":50.0,
             "maxScanRange":90,"simulation":0},
"nptFineY": {"type":"primary","axis":"y","driver":"nptMotor","controller":"nptController",
             "controllerID":"<nPoint FTDI address>","port":0,
             "units":1.0,"offset":0.0,"minValue":-50.0,"maxValue":50.0,
             "maxScanRange":90,"simulation":0},
```

AWG dither leaves (share one `keysightAWGController`; `maxValue` = the dither full-scale, µm):

```json
"AWGFineX": {"type":"primary","axis":"x","driver":"keysightAWGMotor",
             "controller":"keysightAWGController",
             "controllerID":"USB::0x0957::0x2807::INSTR","port":0,
             "controller_index":1,"stage_type":"piezo",
             "units":1.0,"offset":0.0,"minValue":-50.0,"maxValue":50.0,"simulation":0},
"AWGFineY": {"type":"primary","axis":"y","driver":"keysightAWGMotor",
             "controller":"keysightAWGController",
             "controllerID":"USB::0x0957::0x2807::INSTR","port":0,
             "controller_index":2,"stage_type":"piezo",
             "units":1.0,"offset":0.0,"minValue":-50.0,"maxValue":50.0,"simulation":0},
```

Sample motors (derived, three axes each):

```json
"SampleX": {"type":"derived","driver":"derivedPiezoWithAWG",
            "axes":{"axis1":"nptFineX","axis2":"CoarseX","axis3":"AWGFineX"},
            "reset_after_move":false,"relax_time":0.5,"acceleration_distance":20,
            "units":1.0,"offset":0.0,"minValue":-5000.0,"maxValue":5000.0,
            "display":true,"simulation":0},
"SampleY": {"type":"derived","driver":"derivedPiezoWithAWG",
            "axes":{"axis1":"nptFineY","axis2":"CoarseY","axis3":"AWGFineY"},
            "reset_after_move":false,"relax_time":0.5,"acceleration_distance":20,
            "units":1.0,"offset":0.0,"minValue":-5000.0,"maxValue":5000.0,
            "display":true,"simulation":0},
```

`CoarseX`/`CoarseY` (xpsMotor) are reused unchanged. `nptController` and
`keysightAWGController` are auto-created from the leaves' `controllerID`.

### `scan.json`

```json
"Spiral Image": {"driver":"derived_spiral_image","type":"image","mode":"continuousSpiral",
                 "x_motor":"SampleX","y_motor":"SampleY","energy_motor":"Energy",
                 "daq_list":["USB1808X"],"daq_master":false,"trigger_mode":"line",
                 "spiral":true,"display":true}
```

`daq_master:false` is required (the AWG is stage-master).

### `daq.json` — USB-1808X position-readback DAQ

The synchronous "adc+counter" DAQ reads the nPoint monitor voltages (achieved X/Y positions)
paired with photon counts on one pacer clock (mirrors `scripts/testAWGSpiral.py:make_daq`):

```json
"USB1808X": {"index":1,"name":"MCC USB-1808X","type":"point","ndim":0,
             "driver":"mccUSB1808X","mode":"adc+counter",
             "channel":0,"ai_channels":[0,1],"ctr_channel":0,"primary":"counter",
             "input_mode":"differential","voltage_range":10.0,"adc_max_rate":200000.0,
             "serial":null,"gate":false,"position_readback":true,
             "minimum_dwell":0.001,"dwell_pad":0.0,"time_resolution":0.001,
             "record":true,"simulation":0}
```

`ai_channels:[xmon, ymon]` and `position_readback:true` are what route the achieved positions
into `scanInfo["line_positions"]`.

## Verification

1. **Sim** — construct `SampleX = derivedPiezoWithAWG` in simulation; confirm `moveTo`/`getPos`
   are identical to `derivedPiezo`, and that an arbitrary trajectory produces a zero-centred
   dither with correct absolute reconstruction. (Covered by the driver's unit smoke tests.)
2. **AWG driver** — `setup_xy(..., amplitude=(fs,fs), offset=(0,0))` emits a zero-DC dither of
   fixed gain (scope / `testAWGSpiral.py` readback); omitting the args preserves prior behavior.
3. **Chunk stitching** — force `totalSplit > 1` (large field / long dwell); consecutive chunks
   form one continuous spiral about the nPoint centre.
4. **End-to-end** — run "Spiral Image" with the config above + the USB-1808X; the reconstructed
   image is centred at the requested position and `aux_data` matches the commanded spiral.
5. **Regression** — an ordinary nPoint line/raster flyscan on the same motor still arms PIN6.

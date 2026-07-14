# pystxmcontrol

pystxmcontrol includes a GUI (with underlying client), server which executes various functions controlling hardware devices and several device drivers common to scanning microscopes at the Advanced Light Source. Devices which do not have currently supported drivers can be accessed via EPICS by implementing a pseudo driver providing the correct MOTOR interface.

# Main features
- Rich graphical interface for scan definition and data visualization
- Separation of graphical interface and control layer.  Scans can proceed without the GUI or by script
- ZMQ interface to imaging detectors or analysis pipelines for live visualization
- Hardware controlled piezo trajectories for fast scanning
- Low scan overhead
- Microsecond shutter timing and synchronization using an Arduino Due microcontroller
- Full integration of ptychography scanning
- Logging of motor positions, moves and scans

# Currently supported devices
- [Mad City Labs](https://www.madcitylabs.com/nanodrive.html) Nano-Drive controller
- [nPoint](https://npoint.com/) LC.400 piezo controller
- [Newport XPS](https://www.newport.com/c/xps-universal-multi-axis-motion-controller) motor controller
- Keysight 53230A frequency counter
- Keysight A33500B arbitrary waveform generator
- Keysight U2356A multi-channel ADC
- SmarAct MCS/MCS2 controlled stages
- Xeryon controlled stages
- Arduino Due
- Micronix MMC controller
- PI E-712 controller
- Quantum Detectors Xpress 3
- Aerotech XR3

# Dependencies 
Ubuntu requires this package to be installed in some cases for PySide6 to function properly.
```
sudo apt install  libxcb-cursor0
```

### Automatically installed by pip

- Numpy
- Scipy
- Scikit-Image
- python-usbtmc
- pylibftdi
- pyvisa-py
- pyepics
- pyserial
- pyzmq
- matplotlib
- pyside6 = 6.8.2
- pyqtgraph
- pyqtdarktheme
- python-dotenv
- PIPython

# Environment setup and installation using miniconda3 and pip
- On both Windows, Mac or LInux install [miniconda3](https://docs.conda.io/en/latest/miniconda.html) and activate the base environment
- Create a conda environment with Python version <=3.12
```
conda create -n [my_env_name] python=3.12
conda activate [my_env_name]
```
- Clone pystxmcontrol and install
```
git clone https://[username]@bitbucket.org/dashapiro/pystxmcontrol.git
cd pystxmcontrol
pip install .
```

# Running pystxmcontrol
- edit [path_to_conda_env]/pystxmcontrol_cfg/main.json
  - change "server/host" to localhost for local operation or the IP of the machine on which the server will run (if you wish to use a remote GUI)
  - change "server/data_dir" to an existing location for saving data on the server.  On Windows double rather than single backslashes must be used in the path
- edit [path_to_conda_env]/pystxmcontrol_cfg/motor.json as needed for your motor system.  This is described further in the documentation.
- In one terminal (or Anaconda Powershell on Windows) enter: stxmserver
- In another terminal enter: stxmcontrol

# Remote GUI (stxmcontrol-remote)

The `stxmcontrol-remote` console script provides a Qt-based GUI for the pystxmcontrol client wired to a Lightfall RemoteBackend, enabling remote control of STXM experiments via a running Lightfall instance with the remote-control service enabled.

## Installation

Install the remote-GUI extra dependencies:

```
pip install pystxmcontrol[remote]
```

This installs: `nats-py`, `tiled`, `caproto>=1.1`, and `netifaces`.

## Configuration

The GUI uses a JSON config file to connect to Lightfall's remote-control service via NATS. The config is loaded from a packaged default (`pystxmcontrol/remote/remote.json`) but may be overridden:

```
stxmcontrol-remote [--config /path/to/remote.json]
```

Config file structure (JSON):

```json
{
    "nats_url": "nats://127.0.0.1:4222",
    "prefix": "als.stxm",
    "app_name": "pystxmcontrol-remote"
}
```

- `nats_url`: NATS server URL (default: local NATS at port 4222)
- `prefix`: NATS subject prefix for device/control channels (default: `als.stxm`)
- `app_name`: Client identifier sent to Lightfall (default: `pystxmcontrol-remote`)

## Prerequisites

- A running Lightfall instance with the remote-control service enabled (spec #1)
- For demo/testing: the spec #2 stxm-iocs simulator fleet running
- Network access to the Lightfall NATS broker and Tiled server
- Environment variable `OPHYD_CONTROL_LAYER=caproto` (set automatically by RemoteBackend)

## Transport Mechanisms

The remote GUI uses three separate transports for different control/monitoring needs:

1. **NATS (Control):** Orchestrates scan lifecycle (plan run/abort) and manual device moves via Lightfall's capability-channel protocol
2. **Direct CA (Motor Readback Monitoring):** Subscribes to caproto monitors for real-time motor positions without roundtrip latency
3. **Tiled (Live Scan Images):** Streams live image data via RunStreamer for on-GUI visualization

## v1 Scan-Mode Scope

The initial remote GUI implementation supports:

- Fly raster scans
- Energy stack scans

Other scan modes will be rejected with an `UnsupportedScanMode` error.

## Disabled Features in Remote Mode

The following features are disabled when controlling via the remote GUI (limitations of the remote backend or deferred to spec follow-ups):

- `set_gate` (shutter control)
- `move_to_focus` (focus-mode motions)
- Motor configuration editing
- `query_motor_history` (motor move logs)
- CCD and ptychography data monitors
- Scan-state inference from data (state is driven by explicit run lifecycle events)

# Contact us

For questions, bug reports, feature requests, or if you want to collaborate with us, contact dashapiro@lbl.gov

# Copyright Notice

Python STXM Control (pystxmcontrol) Copyright (c) 2025, The Regents of the
University of California, through Lawrence Berkeley National Laboratory (subject to receipt of any required approvals from the U.S. Dept. of Energy). All rights reserved.

If you have questions about your rights to use or distribute this software,
please contact Berkeley Lab's Intellectual Property Office at
IPO@lbl.gov.

NOTICE.  This Software was developed under funding from the U.S. Department
of Energy and the U.S. Government consequently retains certain rights.  As
such, the U.S. Government has been granted for itself and others acting on
its behalf a paid-up, nonexclusive, irrevocable, worldwide license in the
Software to reproduce, distribute copies to the public, prepare derivative 
works, and perform publicly and display publicly, and to permit others to do so.

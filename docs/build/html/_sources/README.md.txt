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

# Currently supported devices
- [nPoint](https://npoint.com/) piezo controller
- [Newport XPS](https://www.newport.com/c/xps-universal-multi-axis-motion-controller) motor controller
- Keysight 53230A timer/counter
- Keysight A33500B arbitrary waveform generator
- Keysight U2356A multi-channel ADC
- SmarAct MCS/MCS2 controlled stages (via EPICS)
- Xeryon controlled stages
- Arduino Due

# Dependencies 
#### automatically installed by pip

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
- qdarkstyle
- pyqt5
- pyqtgraph

# Environment setup and installation using miniconda3 and pip
- On both Windows, Mac or LInux install [miniconda3](https://docs.conda.io/en/latest/miniconda.html) and activate the base environment
- Create a conda environment with Python version 3.6 or later
```
conda create -n my_env_name python=3.9.12
conda activate my_env_name
```

- Clone the repository
```
git clone https://[username]@bitbucket.org/dashapiro/pystxmcontrol.git
cd pystxmcontrol
```
- Install the repo in your environment using pip
```
pip install .
```

# Running pystxmcontrol
- edit [path_to_conda_env]/pystxmcontrol_cfg/main.json
- change "server/ip" to localhost for local operation or the IP of the machine on which the server will run
- change "dataDir" to an appropriate location for saving data on the server.  On Windows double rather than single backslashes must be used in the path
- edit [path_to_conda_env]/pystxmcontrol_cfg/motorConfig.json

In one terminal (or Anaconda Powershell on Windows):
```
python pystxmcontrol/server/stxmServer.py --simulation 1
```
In another terminal:
```
python pystxmcontrol/stxmcontrol.py
```

# Contact us

For questions, bug reports, feature requests, or if you want to collaborate with us, contact dashapiro@lbl.gov

# Notice

This Software was developed under funding from the U.S. Department
of Energy and the U.S. Government consequently retains certain rights.  As
such, the U.S. Government has been granted for itself and others acting on
its behalf a paid-up, nonexclusive, irrevocable, worldwide license in the
Software to reproduce, distribute copies to the public, prepare derivative
works, and perform publicly and display publicly, and to permit other to do
so.

# Guard each optional driver import: a missing hardware SDK or heavy optional
# dependency (epics, pylibftdi, scipy, matplotlib, usbtmc, h5py, SmarAct,
# Aerotech, ...) should not prevent importing the drivers that ARE available
# on this host. This mirrors the existing try/except pattern already used for
# the SmarAct and Aerotech drivers below.

try:
    from pystxmcontrol.drivers.bcsMotor import bcsMotor
except Exception as _e:
    print(f"pystxmcontrol.drivers.bcsMotor not available: {_e}")

try:
    from pystxmcontrol.drivers.nptMotor import nptMotor
except Exception as _e:
    print(f"pystxmcontrol.drivers.nptMotor not available: {_e}")

try:
    from pystxmcontrol.drivers.mmcMotor import mmcMotor
except Exception as _e:
    print(f"pystxmcontrol.drivers.mmcMotor not available: {_e}")

try:
    from pystxmcontrol.drivers.epicsMotor import epicsMotor
except Exception as _e:
    print(f"pystxmcontrol.drivers.epicsMotor not available: {_e}")

try:
    from pystxmcontrol.drivers.nptController import nptController
except Exception as _e:
    print(f"pystxmcontrol.drivers.nptController not available: {_e}")

try:
    from pystxmcontrol.drivers.bcsController import bcsController
except Exception as _e:
    print(f"pystxmcontrol.drivers.bcsController not available: {_e}")

try:
    from pystxmcontrol.drivers.mmcController import mmcController
except Exception as _e:
    print(f"pystxmcontrol.drivers.mmcController not available: {_e}")

try:
    from pystxmcontrol.drivers.epicsController import epicsController
except Exception as _e:
    print(f"pystxmcontrol.drivers.epicsController not available: {_e}")

try:
    from pystxmcontrol.drivers.keysight53230A import keysight53230A
except Exception as _e:
    print(f"pystxmcontrol.drivers.keysight53230A not available: {_e}")

try:
    from pystxmcontrol.drivers.keysight53230A_2channel import keysight53230A_2channel
except Exception as _e:
    print(f"pystxmcontrol.drivers.keysight53230A_2channel not available: {_e}")

try:
    from pystxmcontrol.drivers.keysightU2356A import keysightU2356A
except Exception as _e:
    print(f"pystxmcontrol.drivers.keysightU2356A not available: {_e}")

try:
    from pystxmcontrol.drivers.fccd_control import fccd_control
except Exception as _e:
    print(f"pystxmcontrol.drivers.fccd_control not available: {_e}")

try:
    from pystxmcontrol.drivers.shutter import shutter
except Exception as _e:
    print(f"pystxmcontrol.drivers.shutter not available: {_e}")

try:
    from pystxmcontrol.drivers.xerMotor import xerMotor
except Exception as _e:
    print(f"pystxmcontrol.drivers.xerMotor not available: {_e}")

try:
    from pystxmcontrol.drivers.xerController import xerController
except Exception as _e:
    print(f"pystxmcontrol.drivers.xerController not available: {_e}")

try:
    from pystxmcontrol.drivers.derivedEnergy import derivedEnergy
except Exception as _e:
    print(f"pystxmcontrol.drivers.derivedEnergy not available: {_e}")

try:
    from pystxmcontrol.drivers.derivedEnergy_SGM import derivedEnergy_SGM
except Exception as _e:
    print(f"pystxmcontrol.drivers.derivedEnergy_SGM not available: {_e}")

try:
    from pystxmcontrol.drivers.mclController import mclController
except Exception as _e:
    print(f"pystxmcontrol.drivers.mclController not available: {_e}")

try:
    from pystxmcontrol.drivers.mclMotor import mclMotor
except Exception as _e:
    print(f"pystxmcontrol.drivers.mclMotor not available: {_e}")

try:
    from pystxmcontrol.drivers.derivedPiezo import derivedPiezo
except Exception as _e:
    print(f"pystxmcontrol.drivers.derivedPiezo not available: {_e}")

try:
    from pystxmcontrol.drivers.inclinedDerivedPiezo import inclinedDerivedPiezo
except Exception as _e:
    print(f"pystxmcontrol.drivers.inclinedDerivedPiezo not available: {_e}")

try:
    from pystxmcontrol.drivers.inclinedSampleDerivedPiezo import inclinedSampleDerivedPiezo
except Exception as _e:
    print(f"pystxmcontrol.drivers.inclinedSampleDerivedPiezo not available: {_e}")

try:
    from pystxmcontrol.drivers.areaDetector import areaDetector
except Exception as _e:
    print(f"pystxmcontrol.drivers.areaDetector not available: {_e}")

try:
    from pystxmcontrol.drivers.xpsController import xpsController
except Exception as _e:
    print(f"pystxmcontrol.drivers.xpsController not available: {_e}")

try:
    from pystxmcontrol.drivers.xpsMotor import xpsMotor
except Exception as _e:
    print(f"pystxmcontrol.drivers.xpsMotor not available: {_e}")

try:
    from pystxmcontrol.drivers.E712Controller import E712Controller
except Exception as _e:
    print(f"pystxmcontrol.drivers.E712Controller not available: {_e}")

try:
    from pystxmcontrol.drivers.E712Motor import E712Motor
except Exception as _e:
    print(f"pystxmcontrol.drivers.E712Motor not available: {_e}")

try:
    from pystxmcontrol.drivers.xspress3 import xspress3
except Exception as _e:
    print(f"pystxmcontrol.drivers.xspress3 not available: {_e}")

try:
    from pystxmcontrol.drivers.zmqFrameReaderDAQ import zmq_frame_reader
except Exception as _e:
    print(f"pystxmcontrol.drivers.zmqFrameReaderDAQ not available: {_e}")


__all__ = ['bcsServer', 'bcsMotor', 'nptMotor', 'mmcMotor', 'epicsMotor',
    'nptController', 'bcsController', 'mmcController', 'keysight53230A', 'keysight53230A_2channel',
           'epicsController', 'shutter', 'keysightU2356A', 'fccd_control', 'xerMotor',
           'xerController', 'derivedEnergy', 'mclMotor', 'mclController', 'derivedPiezo',
           'areaDetector', 'xpsMotor', 'xpsController', 'derivedEnergy_SGM', 'E712Controller', 'E712Motor',
            'xspress3', 'inclinedDerivedPiezo', 'inclinedSampleDerivedPiezo', 'zmq_frame_reader']

try:
    from pystxmcontrol.drivers.mcsController import mcsController
    from pystxmcontrol.drivers.mcsMotor import mcsMotor
except Exception:
    print("SmarAct SDK not installed.")
else:
    __all__.append('mcsMotor')
    __all__.append('mcsController')

try:
    from pystxmcontrol.drivers.aerotechController import aerotechController
    from pystxmcontrol.drivers.aerotechMotor import aerotechMotor
except Exception:
    print("Aerotech SDK not installed.")
else:
    __all__.append('aerotechMotor')
    __all__.append('aerotechController')

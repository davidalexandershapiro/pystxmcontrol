from pystxmcontrol.drivers.bcsMotor import bcsMotor
from pystxmcontrol.drivers.nptMotor import nptMotor
from pystxmcontrol.drivers.mmcMotor import mmcMotor
from pystxmcontrol.drivers.epicsMotor import epicsMotor
from pystxmcontrol.drivers.nptController import nptController
from pystxmcontrol.drivers.bcsController import bcsController
from pystxmcontrol.drivers.mmcController import mmcController
from pystxmcontrol.drivers.epicsController import epicsController
from pystxmcontrol.drivers.keysight53230A import keysight53230A
from pystxmcontrol.drivers.keysightU2356A import keysightU2356A
from pystxmcontrol.drivers.fccd_control import fccd_control
from pystxmcontrol.drivers.shutter import shutter
from pystxmcontrol.drivers.xerMotor import xerMotor
from pystxmcontrol.drivers.xerController import xerController
from pystxmcontrol.drivers.derivedEnergy import derivedEnergy
from pystxmcontrol.drivers.derivedEnergy_SGM import derivedEnergy_SGM
from pystxmcontrol.drivers.mclController import mclController
from pystxmcontrol.drivers.mclMotor import mclMotor
from pystxmcontrol.drivers.derivedPiezo import derivedPiezo
from pystxmcontrol.drivers.areaDetector import areaDetector
from pystxmcontrol.drivers.xpsController import xpsController
from pystxmcontrol.drivers.xpsMotor import xpsMotor
from pystxmcontrol.drivers.E712Controller import E712Controller
from pystxmcontrol.drivers.E712Motor import E712Motor
from pystxmcontrol.drivers.xspress3 import xspress3


__all__ = ['bcsServer', 'bcsMotor', 'nptMotor', 'mmcMotor', 'epicsMotor',\
    'nptController', 'bcsController', 'mmcController','keysight53230A',\
           'epicsController', 'shutter', 'keysightU2356A', 'fccd_control', 'xerMotor', \
           'xerController','derivedEnergy','mclMotor', 'mclController','derivedPiezo',\
           'areaDetector','xpsMotor','xpsController','derivedEnergy_SGM','E712Controller','E712Motor',\
            'xspress3']

try:
    from pystxmcontrol.drivers.mcsController import mcsController
    from pystxmcontrol.drivers.mcsMotor import mcsMotor
except:
    print("SmarAct SDK not installed.")
else:
    __all__.append('mcsMotor')
    __all__.append('mcsController')
try:
    from pystxmcontrol.drivers.aerotechController import aerotechController
    from pystxmcontrol.drivers.aerotechMotor import aerotechMotor
except:
    print("Aerotech SDK not installed.")
else:
    __all__.append('aerotechMotor')
    __all__.append('aerotechController')

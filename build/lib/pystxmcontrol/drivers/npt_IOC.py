from caproto.server import PVGroup, get_pv_pair_wrapper, conversion, pvproperty, ioc_arg_parser, run
from nptMotor import nptMotor
from nptController import nptController
from keysight53230A import keysight53230A
import sys, time
from textwrap import dedent
import logging
from optparse import OptionParser
import numpy as np

##this all interferes with the caproto options stuff below.  need to figure that out
#parser = OptionParser()
#parser.add_option("-s", "--simulation", dest = "SIMULATION", default = 0, help = "Use simulation mode. 1 for simulation and 0 for real")
#parser.add_option("-n", "--npoint", dest = "NPOINT_ADDRESS", default = '7340010', help = "Npoint controller address")
#parser.add_option("-k", "--keysight", dest = "KEYSIGHT_ADDRESS", default = 'USB::0x0957::0x1907::INSTR', help = "Keysight counter address")
#(options, args) = parser.parse_args()
#options = vars(options)

#SIMULATION = bool(options["SIMULATION"])
#NPOINT_ADDRESS = options["NPOINT_ADDRESS"]
#KEYSIGHT_ADDRESS = options["KEYSIGHT_ADDRESS"]

SIMULATION = False
NPOINT_ADDRESS = '7340010'
KEYSIGHT_ADDRESS = 'USB::0x0957::0x1907::INSTR'
logger = logging.getLogger('caproto')
pvproperty_with_rbv = get_pv_pair_wrapper(setpoint_suffix='',readback_suffix='.RBV')

##Initialize nPoint 2-axis motor controller
motorController = nptController(address = NPOINT_ADDRESS, port = None)
motorController.initialize(simulation = SIMULATION)
xMotor = nptMotor(controller = motorController)
xMotor.connect(axis = 'x')
yMotor = nptMotor(controller = motorController)
yMotor.connect(axis = 'y')

##initialize Keysight Counter
counter = keysight53230A(visa_address = KEYSIGHT_ADDRESS, simulation = SIMULATION)
counter.start()
counter.config(10, count = 1, trigger = 'EXT')

class nPoint_IOC(PVGroup):
    """
    IOC for Lakeshore Model 336 IOC for Temperture Control
    see manual for commands:
    https://www.lakeshore.com/docs/default-source/product-downloads/336_manual.pdf?sfvrsn=fa4e3a80_5
    """

    dwellTime = pvproperty_with_rbv(dtype = float, doc = "Dwell Time in milliseconds at each position", value = 10.0, precision = 3)
    waitTimeXMotor = pvproperty_with_rbv(dtype = float, doc = "Wait Time in milliseconds after each move", value = 5.0, precision = 3)
    waitTimeYMotor = pvproperty_with_rbv(dtype = float, doc = "Wait Time in milliseconds after each move", value = 5.0, precision = 3)
    linePixelSize = pvproperty_with_rbv(dtype = float, doc = "Pixel size in microns for linescan", value = 0.1, precision = 3)
    linePixelCount = pvproperty_with_rbv(dtype = int, doc = "Number of steps in a X line scan", value = 21)
    linePixelDwellTime = pvproperty_with_rbv(dtype = float, doc = \
        "Dwell Time in milliseconds at each pixel position for linescan", value = 10.0, precision = 3)
    lineDwellTime = pvproperty_with_rbv(dtype = float, doc = \
        "Dwell Time in milliseconds at each line for linescan", value = 0.1, precision = 3)
    pulseOffsetTime = pvproperty_with_rbv(dtype = float, doc = \
        "Offset time before pulse at each pixel position for linescan", value = 0.01, precision = 3)
    imageLineCount = pvproperty_with_rbv(dtype = int, doc = "Number of lines per image for linescan", value = 1)
    numYPoints = pvproperty_with_rbv(dtype = int, doc = "Number of steps in a Y line scan", value = 1)
    lineCenterXPosition = pvproperty_with_rbv(dtype=float, doc="Center X Motor Position for a linescan", value=0.)
    lineCenterYPosition = pvproperty_with_rbv(dtype=float, doc="Center Y Motor Position for a linescan", value=0.)
    moveToXPosition = pvproperty_with_rbv(dtype = float, doc = "Move X Motor to Position", value = 0., precision=6)
    moveToYPosition = pvproperty_with_rbv(dtype = float, doc="Move Y Motor to Position", value = 0.,precision=6)

    rasterLineX = pvproperty(dtype=float, doc="Execute raster linescan in X direction", value=np.zeros(2000))
    lineMode = pvproperty_with_rbv(dtype=str, doc="Configure the counter for linescan mode: raster or fly", value="raster")
#    moveLineX = pvproperty_with_rbv(dtype = str, doc="Execute linescan in X direction", value = 'raster')
    currentXPosition = pvproperty(dtype = float, doc = "Current X Motor Position")
    currentYPosition = pvproperty(dtype=float, doc = "Current Y Motor Position")
    count = pvproperty(dtype = int, doc = "Integrated detector counts")
    x_motor_status = pvproperty_with_rbv(dtype=bool, doc="check if x motor is moving")
    y_motor_status = pvproperty_with_rbv(dtype=bool, doc="check if y motor is moving")
    random = pvproperty(value = [0.,0.,0.])

    @x_motor_status.readback.getter
    async def x_motor_status(obj, instance):
        return xMotor.get_status

    @y_motor_status.readback.getter
    async def y_motor_status(obj, instance):
        return yMotor.get_status

    @random.getter
    async def random(obj, instance):
        return np.random.rand(3)

    @count.getter
    async def count(obj, instance):
        return float(counter.getPoint())

    @dwellTime.setpoint.putter
    async def dwellTime(obj, instance, value):
        counter.config(value, points=1)

    @dwellTime.setpoint.getter
    async def dwellTime(obj, instance):
        return counter.dwell

    # TODO: remove currentPosition PVs since they are redundant to moveToPosition readback PVs
    @currentXPosition.getter
    async def currentXPosition(obj, instance):
        return float(xMotor.getPos())

    @currentYPosition.getter
    async def currentYPosition(obj, instance):
        return float(yMotor.getPos())

    @moveToXPosition.setpoint.putter
    async def moveToXPosition(obj, instance, value):
        xMotor.moveTo(value)

    @moveToXPosition.readback.getter
    async def moveToXPosition(obj, instance):
        return float(xMotor.getPos())

    @moveToYPosition.setpoint.putter
    async def moveToYPosition(obj, instance, value):
        yMotor.moveTo(value)

    @moveToYPosition.readback.getter
    async def moveToYPosition(obj, instance):
        return float(yMotor.getPos())

    @waitTimeXMotor.setpoint.putter
    async def waitTimeXMotor(obj, instance, value):
        xMotor.waitTime = value

    @waitTimeXMotor.readback.getter
    async def waitTimeXMotor(obj, instance):
        return float(xMotor.waitTime)

    @waitTimeYMotor.setpoint.putter
    async def waitTimeYMotor(obj, instance, value):
        yMotor.waitTime = value

    @waitTimeYMotor.readback.getter
    async def waitTimeYMotor(obj, instance):
        return float(yMotor.waitTime)

    ###linescan PVs
    @lineCenterXPosition.setpoint.putter
    async def lineCenterXPosition(obj, instance, value):
        xMotor.lineCenterX = value
        yMotor.lineCenterX = value

    @lineCenterXPosition.readback.getter
    async def lineCenterXPosition(obj, instance):
        return float(xMotor.lineCenterX)

    @lineCenterYPosition.setpoint.putter
    async def lineCenterYPosition(obj, instance, value):
        yMotor.lineCenterY = value
        xMotor.lineCenterY = value

    @lineCenterYPosition.readback.getter
    async def lineCenterYPosition(obj, instance):
        return float(yMotor.lineCenterY)

    @linePixelSize.setpoint.putter
    async def linePixelSize(obj, instance, value):
        xMotor.linePixelSize = value

    @linePixelSize.readback.getter
    async def linePixelSize(obj, instance):
        return float(xMotor.linePixelSize)

    @linePixelCount.setpoint.putter
    async def linePixelCount(obj, instance, value):
        xMotor.linePixelCount = value

    @linePixelCount.readback.getter
    async def linePixelCount(obj, instance):
        return float(xMotor.linePixelCount)

    @linePixelDwellTime.setpoint.putter
    async def linePixelDwellTime(obj, instance, value):
        xMotor.linePixelDwellTime = value

    @linePixelDwellTime.readback.getter
    async def linePixelDwellTime(obj, instance):
        return float(xMotor.linePixelDwellTime)

    @lineDwellTime.setpoint.putter
    async def lineDwellTime(obj, instance, value):
        xMotor.lineDwellTime = value

    @lineDwellTime.readback.getter
    async def lineDwellTime(obj, instance):
        return float(xMotor.lineDwellTime)

    @pulseOffsetTime.setpoint.putter
    async def pulseOffsetTime(obj, instance, value):
        xMotor.pulseOffsetTime = value

    @pulseOffsetTime.readback.getter
    async def pulseOffsetTime(obj, instance):
        return float(xMotor.pulseOffsetTime)

    @imageLineCount.setpoint.putter
    async def imageLineCount(obj, instance, value):
        xMotor.imageLineCount = value

    @imageLineCount.readback.getter
    async def imageLineCount(obj, instance):
        return float(xMotor.imageLineCount)

    @rasterLineX.getter
    async def rasterLineX(obj, instance):
        counter.initLine()
        xMotor.moveLine()
        return counter.getLine()

    @lineMode.readback.getter
    async def lineMode(obj, instance):
        return xMotor.lineMode

    @lineMode.setpoint.putter
    async def lineMode(obj, instance, value):
        xMotor.lineMode = value
        yMotor.lineMode = value
        counter.config(counter.dwell, count=xMotor.linePixelCount, trigger='EXT')

    # @moveLineX.setpoint.putter
    # async def moveLineX(obj, instance, value):
    #     xMotor.moveLine(mode = value)

def main():
    """Console script for nPoint_IOC."""

    ioc_options, run_options = ioc_arg_parser(
        default_prefix='ES7012:npoint:',
        desc=dedent(nPoint_IOC.__doc__))
    ioc = nPoint_IOC(**ioc_options)
    run(ioc.pvdb, **run_options)

    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover

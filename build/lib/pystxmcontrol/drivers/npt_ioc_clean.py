import numpy as np
import logging
import sys, time
from textwrap import dedent

from caproto.server import PVGroup, get_pv_pair_wrapper, conversion, pvproperty, ioc_arg_parser, run
from caproto.sync.client import write, read


#FIXME remove copy and decide on one implementation
from nptMotor_jr2 import nptMotor
from nptController import nptController
from keysight53230A import keysight53230A


SIMULATION = False
NPOINT_ADDRESS = '7340010'
KEYSIGHT_ADDRESS = 'USB::0x0957::0x1907::INSTR'
logger = logging.getLogger('caproto')
pvproperty_with_rbv = get_pv_pair_wrapper(setpoint_suffix='', readback_suffix='_RBV')

##Initialize nPoint 2-axis motor controller
motorController = nptController(address=NPOINT_ADDRESS, port=None)
motorController.initialize(simulation=SIMULATION)
xMotor = nptMotor(controller=motorController)
xMotor.connect(axis='x')
yMotor = nptMotor(controller=motorController)
yMotor.connect(axis='y')

##initialize Keysight Counter
counter = keysight53230A(visa_address=KEYSIGHT_ADDRESS, simulation=SIMULATION)
counter.start()
counter.config(dwell=1, count=1, samples=100, trigger='EXT')
com_lock = None

class nPoint_IOC(PVGroup):
    """
    IOC with all PVs for npt motor and controller
    """

    pos_x = pvproperty_with_rbv(dtype=float, doc="X Motor Position", value=0., precision=6)
    pos_y = pvproperty(dtype=float, doc="Y Motor Position", value=0., precision=6)

    line_mode_int = pvproperty_with_rbv(dtype=int, doc="Configure the counter for linescan mode: 0 = raster or 1 = fly",
                                        value=1)
    init_line = pvproperty(dtype=int)
    move_line = pvproperty_with_rbv(dtype = int, doc="Execute linescan in X direction", value=1)
    get_line = pvproperty(dtype=float, doc="read data from for line", max_length=200)
    #config_counter = pvproperty()
    
    trajectory_start = pvproperty_with_rbv(dtype=float, doc="Trajectory start value", max_length=2)
    trajectory_stop = pvproperty_with_rbv(dtype=float, doc="Trajectory stop value", max_length=2)
    trajectory_pixel_count = pvproperty_with_rbv(dtype=int, doc="Trajectory pixel count is the integer number of pixels"
                                                                "in a trajectory", value=10)
    trajectory_pixel_dwell = pvproperty_with_rbv(dtype=int, doc="Trajectory pixel dwell", value=1)
    update_trajectory = pvproperty(dtype=bool, value=False)

    #FIXME make sure string input is supported
    set_counter_trigger = pvproperty(dtype=str, value='EXT')
    pad_x = pvproperty(dtype=float, value=1.)
    pad_y = pvproperty(dtype=float, value=1.)

    


    #@pos_x.readback.scan(0.1)
    #async def pos_x(obj, instance, asyn_lib):
    #    await instance.write(float(xMotor.getPos()))

    @pos_y.scan(0.1)
    async def pos_y(obj, instance, asyn_lib):
        await instance.write(float(yMotor.getPos()))

    @pos_x.setpoint.putter
    async def pos_x(obj, instance, value):
        xMotor.moveTo(value)

    @pos_x.readback.getter
    async def pos_x(obj, instance):
        return float(xMotor.getPos())

    @pos_y.putter
    async def pos_y(obj, instance, value):
        yMotor.moveTo(value)

    @pos_y.getter
    async def pos_y(obj, instance):
        return float(yMotor.getPos())

    @line_mode_int.readback.getter
    async def line_mode_int(obj, instance):
        return xMotor.lineMode

    @line_mode_int.setpoint.putter
    async def line_mode_int(obj, instance, value):
        xMotor.lineMode = value
        yMotor.lineMode = value

    @init_line.putter
    async def init_line(obj, instance, value):
        # if value:
        # raise ValueError
        # instance.acquire.set(value)
        async with com_lock:
            counter.initLine()

    @move_line.setpoint.putter
    async def move_line(obj, instance, value):
        # using xMotor here, since x and y values are given to either Motor 
        # instance, it does not matter which one to use, but it's not a clean 
        # separation of devices --> could be improved in future implementations
        xMotor.moveLine(direction=value)

    #FIXME get_line is not yet getting the actual data from the counter
    #@get_line.readback.getter
    #async def get_line(obj, instance):
    #    return counter.getLine()
    
    #TODO need to config the counter

    @get_line.getter
    async def get_line(obj, instance):
        async with com_lock:
            counter.initLine()
            try:
                line = counter.getLine()
                #await instance.write(counter.getLine())
                print("LINE:", line)
                return line
            except:
                print('FAILED at get_line')

    @get_line.startup
    async def get_line(self, instance, async_lib):
        global com_lock
        self.async_lib = async_lib
        com_lock = async_lib.library.locks.Lock()
       
    @trajectory_start.readback.getter
    async def trajectory_start(obj, instance):
        return xMotor.trajectory_start

    @trajectory_start.setpoint.putter
    async def trajectory_start(obj, instance, value):
        xMotor.trajectory_start = value

    @trajectory_stop.readback.getter
    async def trajectory_stop(obj, instance):
        return xMotor.trajectory_stop

    @trajectory_stop.setpoint.putter
    async def trajectory_stop(obj, instance, value):
        xMotor.trajectory_stop = value

    @trajectory_pixel_count.readback.getter
    async def trajectory_pixel_count(obj, instance):
        return xMotor.trajectory_pixel_count

    @trajectory_pixel_count.setpoint.putter
    async def trajectory_pixel_count(obj, instance, value):
        xMotor.trajectory_pixel_count = value

    @update_trajectory.getter
    async def update_trajectory(obj, instance):
        yMotor.update_trajectory
        xMotor.update_trajectory

    #@set_counter_trigger.putter
    #async def set_counter_trigger(obj, instance, value):
    #    counter.config(counter.dwell, count=xMotor.linePixelCount, trigger=value)

    @pad_x.getter
    async def pad_x(obj, instance):
        return xMotor.xpad

    @pad_y.getter
    async def pad_y(obj, instance):
        return xMotor.xpad


def main():
    """Console script for nPoint_IOC."""

    ioc_options, run_options = ioc_arg_parser(
        default_prefix='CLEAN:npoint:',
        desc=dedent(nPoint_IOC.__doc__))
    ioc = nPoint_IOC(**ioc_options)
    run(ioc.pvdb, **run_options)

    return 0


if __name__ == "__main__":
    sys.exit(main())

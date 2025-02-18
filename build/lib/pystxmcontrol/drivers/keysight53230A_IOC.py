from caproto.server import PVGroup, get_pv_pair_wrapper, conversion, pvproperty, ioc_arg_parser, run
from keysight53230A import keysight53230A

import sys
from textwrap import dedent
import logging
logger = logging.getLogger('caproto')

pvproperty_with_rbv = get_pv_pair_wrapper(setpoint_suffix='',
                                          readback_suffix='_RBV')

counter = keysight53230A(visa_address = "USB::0x0957::0x1907::INSTR", simulation = False)
counter.start()
counter.config(10, points = 1)

class Keysight53230A_IOC(PVGroup):
    """
    IOC for Lakeshore Model 336 IOC for Temperture Control
    see manual for commands:
    https://www.lakeshore.com/docs/default-source/product-downloads/336_manual.pdf?sfvrsn=fa4e3a80_5
    """

    dwellTime = pvproperty_with_rbv(dtype = float, doc = "Dwell Time in milliseconds", value = 10.0, precision = 3)
    numPoints = pvproperty_with_rbv(dtype = int, doc = "numPoints", value = 1)
    count = pvproperty(dtype = int, doc = "Integrated detector counts")

    @count.getter
    async def count(obj, instance):
        return float(counter.getPoint())

    @dwellTime.setpoint.putter
    async def dwellTime(obj, instance, value):
        counter.config(value, points=1)

    @dwellTime.setpoint.getter
    async def dwellTime(obj, instance):
        return counter.dwell

def main():
    """Console script for lakeshore336_ioc."""

    ioc_options, run_options = ioc_arg_parser(
        default_prefix='ES7012:Counter:',
        desc=dedent(Keysight53230A_IOC.__doc__))
    ioc = Keysight53230A_IOC(**ioc_options)
    run(ioc.pvdb, **run_options)

    return 0


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover

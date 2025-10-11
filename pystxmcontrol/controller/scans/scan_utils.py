from time import time,sleep
import numpy as np
import traceback
import asyncio

def getLoopMotorPositions(scan):
    r = scan["outerLoop"]["range"]
    center = scan["outerLoop"]["center"]
    points = scan["outerLoop"]["points"]
    start = center - r / 2
    stop = center + r / 2
    return np.linspace(start, stop, points)

async def terminateFlyscan(controller, dataHandler, scan, axis, message):
    await dataHandler.dataQueue.put('endOfScan')
    controller.motors[scan[axis]]["motor"].setPositionTriggerOff()
    while not controller.scanQueue.empty():
        try:
            controller.scanQueue.get_nowait()
        except asyncio.QueueEmpty:
            break
    print(message)
    return False


def executeReturnTrajectory(self, motor, xStart, xStop, yStart, yStop):
    maxSpeed = 2.0  # um/ms or mm/s
    minpoints = 5
    motor.trajectory_start = (xStop, yStop)
    motor.trajectory_stop = (xStart, yStart)
    xyRange = ((xStop - xStart) ** 2 + (yStop - yStart) ** 2) ** 0.5
    dwell = 0.301  # ms. Unimportant I think.
    xyPoints = int(max(xyRange / (maxSpeed * dwell), minpoints))
    motor.trajectory_pixel_count = xyPoints
    motor.trajectory_pixel_dwell = dwell
    motor.update_trajectory()
    motor.moveLine()


async def doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime, axes=[1,]):
    # try:
    controller.daq["default"].initLine()
    controller.daq["default"].autoGateOpen()
    for daq in scanInfo["daq list"]:
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            controller.daq[daq].ready()
    #Wait time I assume for initializing detector. Without it, spiral scan doesn't work.
    if scan["spiral"]:
        sleep(0.02)
    if "offset" not in scanInfo.keys():
        scanInfo["offset"] = 0,0
    controller.motors[scan["x_motor"]]["motor"].moveLine(coarse_offset = \
        scanInfo["offset"], coarse_only = scan["coarse_only"],axes=axes)
    scanInfo["line_positions"] = controller.motors[scan["x_motor"]]["motor"].positions
    controller.daq["default"].autoGateClosed()
    try: 
        #this will timeout if there is a missed trigger.  That can happen at the start of
        #big scans or some reason.
        await dataHandler.getLine(scanInfo.copy())
    except Exception as e:
        traceback.print_exc()
        return False
    return True

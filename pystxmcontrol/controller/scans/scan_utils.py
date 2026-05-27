from time import time,sleep
import numpy as np
import traceback
import asyncio


async def async_check_pause(controller, queue) -> bool:
    """Wait while paused.  Returns True to continue, False to terminate.

    On cancel-during-pause: consumes the cancel message and returns False.
    On timeout: clears controller.pause, injects a sentinel so handle_abort
    style callers can call queue.get() without deadlocking, and returns False.
    """
    if not controller.pause:
        return True
    timeout = getattr(controller, 'pause_timeout_seconds', 120)
    pause_start = getattr(controller, '_pause_start_time', None) or time()
    while controller.pause:
        if not queue.empty():
            await queue.get()
            controller.pause = False
            return False
        if time() - pause_start > timeout:
            print(f"[scan] Pause timeout ({timeout}s) — terminating scan.")
            controller.pause = False
            await queue.put("pause_timeout")
            return False
        await asyncio.sleep(0.1)
    return True

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
    for daq in scanInfo["daq_list"]:
        controller.daq[daq].initLine()
    controller.daq["default"].autoGateOpen()
    #Wait time I assume for initializing detector. Without it, spiral scan doesn't work.
    if scan["spiral"]:
        sleep(0.02)
    if "offset" not in scanInfo.keys():
        scanInfo["offset"] = 0,0
    await asyncio.sleep(waitTime)
    controller.motors[scan["x_motor"]]["motor"].moveLine(coarse_offset = \
        scanInfo["offset"], coarse_only = scan["coarse_only"],axes=axes)
    scanInfo["line_positions"] = controller.motors[scan["x_motor"]]["motor"].positions
    controller.daq["default"].autoGateClosed()
    try:
        #this will timeout if there is a missed trigger.  That can happen at the start of
        #big scans or some reason.
        await dataHandler.getLine(scanInfo.copy())
    except Exception as e:
        #by default, if a trigger is missed we end up here, restart the daq and return False.  The scan routine
        #can decide if it wants to retry.
        print("[scan utils] DAQ timeout.  Restarting DAQ and moving on.")
        dataHandler.record_event(
            "daq_timeout",
            line_index=scanInfo.get("lineIndex"),
            region=scanInfo.get("scanRegion"),
            energy_index=scanInfo.get("energyIndex"),
            error=str(e),
        )
        controller.daq["default"].stop()
        controller.daq["default"].start()
        controller.config_daqs(dwell = scanInfo["dwell"],
                               count = scanInfo["trigger_count"],
                               samples = scanInfo["trigger_samples"],
                               trigger = "EXT",
                               daq_list=scanInfo["daq_list"])
        return False
    return True

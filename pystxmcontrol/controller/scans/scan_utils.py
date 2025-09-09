from time import time,sleep
import numpy as np

def getLoopMotorPositions(scan):
    r = scan["outerLoop"]["range"]
    center = scan["outerLoop"]["center"]
    points = scan["outerLoop"]["points"]
    start = center - r / 2
    stop = center + r / 2
    return np.linspace(start, stop, points)

def terminateFlyscan(controller, dataHandler, scan, axis, message):
    dataHandler.dataQueue.put('endOfScan')
    controller.motors[scan[axis]]["motor"].setPositionTriggerOff()
    controller.scanQueue.queue.clear()
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


def doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime):
    # try:
    controller.daq["default"].initLine()
    controller.daq["default"].autoGateOpen()
    #Wait time I assume for initializing detector. Without it, spiral scan doesn't work.
    sleep(0.02)
    if "offset" not in scanInfo.keys():
        scanInfo["offset"] = 0,0
    controller.motors[scan["x_motor"]]["motor"].moveLine(coarse_offset = scanInfo["offset"])
    scanInfo["line_positions"] = controller.motors[scan["x_motor"]]["motor"].positions
    controller.daq["default"].autoGateClosed()
    if not dataHandler.getLine(scanInfo.copy()):
        raise Exception('mismatched array lengths')
    return True

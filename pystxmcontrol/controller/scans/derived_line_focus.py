from pystxmcontrol.controller.scans.scan_utils import *
from numpy import ones
from time import sleep, time

def derived_line_focus(scan, dataHandler, controller, queue):
    energies = dataHandler.data.energies
    scanInfo = {"mode": "continuousLine"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["type"]
    xPos, yPos, zPos = dataHandler.data.xPos[0], dataHandler.data.yPos[0], dataHandler.data.zPos[0]
    energyRegion = "EnergyRegion1"
    scanRegion = "Region1"
    scanInfo["energy"] = energies[0]
    scanInfo["energyRegion"] = energyRegion
    scanInfo["energyIndex"] = 0
    scanInfo["dwell"] = scan["energyRegions"][energyRegion]["dwell"]
    scanInfo["scanRegion"] = scanRegion
    xStart, xStop = scan["scanRegions"][scanRegion]["xStart"], scan["scanRegions"][scanRegion]["xStop"]
    yStart, yStop = scan["scanRegions"][scanRegion]["yStart"], scan["scanRegions"][scanRegion]["yStop"]
    zStart, zStop = scan["scanRegions"][scanRegion]["zStart"], scan["scanRegions"][scanRegion]["zStop"]
    xPoints = scan["scanRegions"][scanRegion]["xPoints"]
    zPoints = scan["scanRegions"][scanRegion]["zPoints"]
    scanInfo["xPoints"] = xPoints
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo["xVal"] = xPos
    scanInfo["yVal"] = yPos
    scanInfo['totalSplit'] = None
    scanInfo["include_return"] = True
    controller.motors[scan["x"]]["motor"].include_return = scanInfo["include_return"]
    coarse_only = scan["coarse_only"]  # this needs to be set properly if a coarse scan is possible
    coarse_offset = 20.
    if scan["oversampling_factor"] > 1:
        scanInfo["interpolate"] = True
    else:
        scanInfo["interpolate"] = False

    controller.getMotorPositions()
    dataHandler.data.motorPositions[0] = controller.allMotorPositions

    # Move to start position
    controller.moveMotor(scan["z"], zStart)

    waitTime = 0.005 + xPoints * 0.0001  # 0.005 + xRange * 0.02
    nxblocks, xcoarse, xStart_fine, xStop_fine = \
        controller.motors[scan["x"]]["motor"].decompose_range(xStart, xStop)
    nyblocks, ycoarse, yStart_fine, yStop_fine = \
        controller.motors[scan["y"]]["motor"].decompose_range(yStart, yStop)
    scanInfo["offset"] = xcoarse, ycoarse

    # first need to move the coarse motor to the correct position
    # this is annoying because it doesn't use the controllers moveMotor command.
    # this is done because we have to ensure it is the coarse motor that moves
    # but, first check for the correct coarseXY coordinates, it may not be needed if requested scan is within fine range
    # this function only moves the coarse motors if needed
    controller.motors[scan["x"]]["motor"].move_coarse_to_fine_range(xStart, xStop)
    controller.motors[scan["y"]]["motor"].move_coarse_to_fine_range(yStart, yStop)

    controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints * scanInfo["oversampling_factor"]
    controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = dataHandler.data.dwells[0] / scanInfo[
        "oversampling_factor"]
    controller.motors[scan["x"]]["motor"].lineMode = "continuous"
    if not (coarse_only):
        # needs to be in piezo units
        # this should be changed to global units and then have the driver convert
        controller.motors[scan["x"]]["motor"].trajectory_start = (xStart_fine, yStart_fine)
        controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop_fine, yStop_fine)
        controller.motors[scan["x"]]["motor"].update_trajectory()
    else:
        start_position_x = xStart - coarse_offset
        start_position_y = yStart
        # a "coarse_only" move will leave the servo off when done, otherwise will turn it back on
        controller.moveMotor(scan["x"], xcoarse + start_position_x, coarse_only=True)
        controller.moveMotor(scan["y"], xcoarse + start_position_y)
        controller.motors[scan["x"]]["motor"].trajectory_start = (xStart, yPos_fine)
        controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop, yPos_fine)
        controller.motors[scan["x"]]["motor"].update_trajectory()
        controller.motors[scan["x"]]["motor"].trajectory_trigger = coarse_offset, coarse_offset

    #numMotorPoints should be the total number of motor position measurements expected
    #numDAQPoints should be equal to xPoints * oversampling
    numLineMotorPoints = controller.motors[scan["x"]]["motor"].npositions #this configures the DAQ for one line
    numLineDAQPoints = controller.motors[scan["x"]]["motor"].npositions * scan["oversampling_factor"]
    scanInfo['numMotorPoints'] = numLineMotorPoints * zPoints #total number of motor points configures the full data structrure
    scanInfo['numDAQPoints'] = scanInfo['numMotorPoints'] * scan["oversampling_factor"]
    dataHandler.data.updateArrays(0, scanInfo)
    controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, \
                                            samples=numLineDAQPoints, trigger="EXT")

    start_position_x = controller.motors[scan["x"]]["motor"].trajectory_start[0] - \
                       controller.motors[scan["x"]]["motor"].xpad
    start_position_y = controller.motors[scan["x"]]["motor"].trajectory_start[1] - \
                       controller.motors[scan["x"]]["motor"].ypad
    scanInfo["start_position_x"] = start_position_x
    scanInfo["start_position_y"] = start_position_y
    controller.moveMotor(scan["x"], xcoarse + start_position_x)
    controller.moveMotor(scan["y"], ycoarse + start_position_y)
    controller.moveMotor(scan["z"], zPos[0])
    sleep(1)

    # turn on position trigger
    trigger_axis = controller.motors[scan["x"]]["motor"].trigger_axis
    trigger_position = controller.motors[scan["x"]]["motor"].trajectory_trigger[trigger_axis - 1]
    if trigger_axis == 1:
        axis = 'x'
    elif trigger_axis == 2:
        axis = 'y'
    controller.motors[scan[axis]]["motor"].setPositionTriggerOn(pos=trigger_position)
    scanInfo["trigger_axis"] = trigger_axis
    scanInfo["xpad"] = controller.motors[scan["x"]]["motor"].xpad
    scanInfo["ypad"] = controller.motors[scan["x"]]["motor"].ypad

    for i in range(len(zPos)):
        controller.moveMotor(scan["x"], xcoarse + start_position_x)
        controller.moveMotor(scan["y"], ycoarse + start_position_y)
        controller.moveMotor(scan["z"], zPos[i])
        controller.getMotorPositions()
        dataHandler.data.motorPositions[0] = controller.allMotorPositions
        scanInfo["motorPositions"] = controller.allMotorPositions
        scanInfo["index"] = i * numLineDAQPoints
        scanInfo["lineIndex"] = i
        scanInfo["zIndex"] = 0
        if queue.empty():
            if not doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime,axes=[1,2]):
                return terminateFlyscan(controller, dataHandler, scan, "x", "Data acquisition failed for flyscan line!")
        else:
            queue.get()
            dataHandler.data.saveRegion(0)
            return terminateFlyscan(controller, dataHandler, scan, "x", "Flyscan aborted.")
    dataHandler.dataQueue.put('endOfRegion')
    terminateFlyscan(controller, dataHandler, scan, "x", "Flyscan completed.")
from pystxmcontrol.controller.scans.scan_utils import *
from numpy import ones
from time import sleep, time

def derived_line_spectrum(scan, dataHandler, controller, queue):
    energies = dataHandler.data.energies
    scanInfo = {"mode": "continuousLine"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["type"]
    xPos, yPos, zPos = dataHandler.data.xPos[0], dataHandler.data.yPos[0], dataHandler.data.zPos[0]
    energyRegion = "EnergyRegion1"
    scanRegion = "Region1"
    scanInfo["energyRegion"] = energyRegion
    scanInfo["energyIndex"] = 0
    scanInfo["dwell"] = scan["energyRegions"][energyRegion]["dwell"]
    scanInfo["scanRegion"] = scanRegion
    xStart, xStop = scan["scanRegions"][scanRegion]["xStart"], scan["scanRegions"][scanRegion]["xStop"]
    yStart, yStop = scan["scanRegions"][scanRegion]["yStart"], scan["scanRegions"][scanRegion]["yStop"]
    zStart, zStop = scan["scanRegions"][scanRegion]["zStart"], scan["scanRegions"][scanRegion]["zStop"]
    xPoints = scan["scanRegions"][scanRegion]["xPoints"]
    scanInfo["xPoints"] = xPoints
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo["xVal"] = xPos
    scanInfo["yVal"] = yPos
    scanInfo['totalSplit'] = None
    scanInfo["include_return"] = True
    controller.motors[scan["x"]]["motor"].include_return = scanInfo["include_return"]
    coarseOnly = False  # this needs to be set properly if a coarse scan is possible

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
    if not (coarseOnly):
        # needs to be in piezo units
        # this should be changed to global units and then have the driver convert
        controller.motors[scan["x"]]["motor"].trajectory_start = (xStart_fine, yStart_fine)
        controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop_fine, yStart_fine)
        controller.motors[scan["x"]]["motor"].update_trajectory()
    else:
        start_position_x = xStart - coarseOffset
        start_position_y = yStart
        # a "coarseONly" move will leave the servo off when done, otherwise will turn it back on
        controller.moveMotor(scan["x"], xcoarse + start_position_x, coarseOnly=True)
        controller.moveMotor(scan["y"], xcoarse + start_position_y)
        controller.motors[scan["x"]]["motor"].trajectory_start = (xStart, yPos_fine)
        controller.motors[scan["x"]]["motor"].trajectory_stop = (xStop, yPos_fine)
        controller.motors[scan["x"]]["motor"].update_trajectory()
        controller.motors[scan["x"]]["motor"].trajectory_trigger = coarseOffset, coarseOffset

    scanInfo['nPoints'] = controller.motors[scan["x"]]["motor"].npositions
    dataHandler.data.updateArrays(0, scanInfo['nPoints'])
    controller.daq["default"].config(scanInfo["dwell"] / scanInfo["oversampling_factor"], count=1, \
                                          samples=scanInfo['nPoints'], trigger="EXT")
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
    scanInfo["trigger_axis"] = trigger_axis
    scanInfo["xpad"] = controller.motors[scan["x"]]["motor"].xpad
    scanInfo["ypad"] = controller.motors[scan["x"]]["motor"].ypad

    for energy in energies:
        scanInfo["energy"] = energy
        scanInfo["energyIndex"] = energyIndex
        scanInfo["dwell"] = dataHandler.data.dwells[energyIndex]
        controller.moveMotor("Energy", energy)
        controller.getMotorPositions()
        dataHandler.data.motorPositions[0] = controller.allMotorPositions
        scanInfo["motorPositions"] = controller.allMotorPositions
        scanInfo["scanRegion"] = scanRegion
        scanInfo["index"] = 0
        scanInfo["xVal"] = xPos[0]
        scanInfo["yVal"] = yPos[0]
        if queue.empty():
            while controller.pause:
                if not (queue.empty()):
                    queue.get()
                    dataHandler.dataQueue.put('endOfScan')
                    print("Terminating grid scan")
                    return False
                time.sleep(0.1)
            scanInfo["direction"] = "forward"
            if not doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime):
                return terminateFlyscan(controller, dataHandler, scan, "x", "Data acquisition failed for flyscan line!")
        else:
            queue.get()
            dataHandler.data.saveRegion(0)
            return terminateFlyscan(controller, dataHandler, scan, "x", "Flyscan aborted.")
        # dataHandler.data.saveRegion(0)
        dataHandler.dataQueue.put('endOfRegion')
        energyIndex += 1
    terminateFlyscan(controller, dataHandler, scan, "x", "Flyscan completed.")
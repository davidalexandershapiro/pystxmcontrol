from pystxmcontrol.controller.scans.scan_utils import *
from numpy import ones
from time import sleep

def derived_line_image(scan, dataHandler, controller, queue):
    """
    Image scan in continuous flyscan mode.  Uses linear trajectory function on the controller
    What this driver does: it will move the coarse motors to the center of the scan range and then execute a fine scan
    which is smaller than the max scan range.  It will also execute a multi region scan where each region is smaller than
    the max scan range.
    What this driver does not do: it will not chop up a larger scan into smaller scans or execute a large coarse scan. This
    needs to be done by an external function.  For now, the function decompose_range() in derivedPiezo() will chop up a large
    scan into appropriately sized smaller scan regions, i.e. turn one large scan into a multi-region scan where each region is
    the piezo range or smaller.  decompose_range() is called in dataHandler if the tiled_scan flag is set by the gui.
    :param scan:
    :return:
    """
    energies = dataHandler.data.energies
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    scanInfo = {"mode": "continuousLine"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["type"]
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo['totalSplit'] = None
    energyIndex = 0
    nScanRegions = len(xPos)
    coarseOnly = False #this needs to be set properly if a coarse scan is possible
    if "outerLoop" in scan.keys():
        loopMotorPos = getLoopMotorPositions(scan)
    for energy in energies:
        ##scanInfo is what gets passed with each data transmission
        scanInfo["energy"] = energy
        scanInfo["energyIndex"] = energyIndex
        scanInfo["dwell"] = dataHandler.data.dwells[energyIndex]
        if len(energies) > 1:
            controller.moveMotor(scan["energy"], energy)
        else:
            pass
            if scanInfo['scan']['refocus']:
                controller.moveMotor("ZonePlateZ",
                                          controller.motors["ZonePlateZ"]["motor"].calibratedPosition)

        for j in range(nScanRegions):
            if "outerLoop" in scan.keys():
                controller.moveMotor(scan["outerLoop"]["motor"], loopMotorPos[j])
            x, y = xPos[j], yPos[j]
            scanInfo["scanRegion"] = "Region" + str(j + 1)
            xStart, xStop = x[0], x[-1]
            yStart, yStop = y[0], y[-1]
            xRange, yRange = xStop - xStart, yStop - yStart
            xPoints, yPoints = len(x), len(y)
            xStep, yStep = xRange / (xPoints - 1), yRange / (yPoints - 1)
            # I'm putting all of these into scanINfo so the GUI knows where to put the data for a script scan
            scanInfo["xPoints"] = xPoints
            scanInfo["xStep"] = xStep
            scanInfo["xStart"] = xStart
            scanInfo["xCenter"] = xStart + xRange / 2.
            scanInfo["xRange"] = xRange
            scanInfo["yPoints"] = yPoints
            scanInfo["yStep"] = yStep
            scanInfo["yStart"] = yStart
            scanInfo["yCenter"] = yStart + yRange / 2.
            scanInfo["yRange"] = yRange
            waitTime = 0.005 + xPoints * 0.0001  # 0.005 + xRange * 0.02
            nxblocks, xcoarse, xStart_fine, xStop_fine = \
                controller.motors[scan["x"]]["motor"].decompose_range(xStart, xStop)
            nyblocks, ycoarse, yStart_fine, yStop_fine = \
                controller.motors[scan["y"]]["motor"].decompose_range(yStart, yStop)
            scanInfo["offset"] = xcoarse,ycoarse

            #first need to move the coarse motor to the correct position
            #this is annoying because it doesn't use the controllers moveMotor command.
            #this is done because we have to ensure it is the coarse motor that moves
            #but, first check for the correct coarseXY coordinates, it may not be needed if requested scan is within fine range
            #this function only moves the coarse motors if needed
            controller.motors[scan["x"]]["motor"].move_coarse_to_fine_range(xStart,xStop)
            controller.motors[scan["y"]]["motor"].move_coarse_to_fine_range(yStart,yStop)

            controller.motors[scan["x"]]["motor"].trajectory_pixel_count = xPoints * scan["oversampling_factor"]
            controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = dataHandler.data.dwells[
                                                                                    energyIndex] / scan[
                                                                                    "oversampling_factor"]
            controller.motors[scan["x"]]["motor"].lineMode = "continuous"
            if not (coarseOnly):
                #needs to be in piezo units
                #this should be changed to global units and then have the driver convert
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
            if energy == energies[0]:
                dataHandler.data.updateArrays(j, scanInfo['nPoints'])
            controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, \
                                                  samples=scanInfo['nPoints'], trigger="EXT")
            start_position_x = controller.motors[scan["x"]]["motor"].trajectory_start[0] - \
                               controller.motors[scan["x"]]["motor"].xpad
            start_position_y = controller.motors[scan["x"]]["motor"].trajectory_start[1] - \
                               controller.motors[scan["x"]]["motor"].ypad
            scanInfo["start_position_x"] = start_position_x
            # needs to be in global units but start_position is generated in piezo units so add coarse.
            controller.moveMotor(scan["x"], xcoarse + start_position_x)
            controller.moveMotor(scan["y"], ycoarse + start_position_y)
            sleep(0.1)

            # turn on position trigger
            trigger_axis = controller.motors[scan["x"]]["motor"].trigger_axis
            scanInfo["trigger_axis"] = trigger_axis
            scanInfo["xpad"] = controller.motors[scan["x"]]["motor"].xpad
            scanInfo["ypad"] = controller.motors[scan["x"]]["motor"].ypad

            for i in range(len(y)):
                controller.moveMotor(scan["y"],y[i])
                controller.getMotorPositions()
                dataHandler.data.motorPositions[j] = controller.allMotorPositions
                scanInfo["motorPositions"] = controller.allMotorPositions
                scanInfo["index"] = i  # *scanInfo['nPoints']

                ##need to also be able to request measured positions
                scanInfo["xVal"], scanInfo["yVal"] = x, y[i] * ones(len(x))
                if queue.empty():
                    if not doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime):
                        return terminateFlyscan(controller, dataHandler, scan, "x", "Data acquisition failed for flyscan line!")
                else:
                    queue.get()
                    dataHandler.data.saveRegion(j)
                    return terminateFlyscan(controller, dataHandler, scan, "x", "Flyscan aborted.")
            dataHandler.dataQueue.put('endOfRegion')
        energyIndex += 1
    terminateFlyscan(controller, dataHandler, scan, "x", "Flyscan completed.")

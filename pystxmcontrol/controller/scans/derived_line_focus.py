from pystxmcontrol.controller.scans.scan_utils import *
from numpy import ones
from time import sleep, time
import asyncio

async def derived_line_focus(scan, dataHandler, controller, queue):

    await scan["synch_event"].wait()
    energies = dataHandler.data.energies["default"]
    scanInfo = {"mode": "continuousLine"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["scan_type"]
    xPos, yPos, zPos = dataHandler.data.xPos[0], dataHandler.data.yPos[0], dataHandler.data.zPos[0]
    energyRegion = "EnergyRegion1"
    scanRegion = "Region1"
    scanInfo["energy"] = energies[0]
    scanInfo["energyRegion"] = energyRegion
    scanInfo["energyIndex"] = 0
    scanInfo["dwell"] = scan["energy_regions"][energyRegion]["dwell"]
    scanInfo["scanRegion"] = scanRegion
    xStart, xStop = scan["scan_regions"][scanRegion]["xStart"], scan["scan_regions"][scanRegion]["xStop"]
    yStart, yStop = scan["scan_regions"][scanRegion]["yStart"], scan["scan_regions"][scanRegion]["yStop"]
    zStart, zStop = scan["scan_regions"][scanRegion]["zStart"], scan["scan_regions"][scanRegion]["zStop"]
    xPoints = scan["scan_regions"][scanRegion]["xPoints"]
    zPoints = scan["scan_regions"][scanRegion]["zPoints"]
    scanInfo["xPoints"] = xPoints
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo["xVal"] = xPos
    scanInfo["yVal"] = yPos
    scanInfo['totalSplit'] = None
    scanInfo["include_return"] = True
    scanInfo["direction"] = "forward"
    
    controller.motors[scan["x_motor"]]["motor"].include_return = scanInfo["include_return"]
    coarse_only = scan["coarse_only"]  # this needs to be set properly if a coarse scan is possible
    coarse_offset = 20.
    scanInfo['daq list'] = scan['daq list']
    scanInfo["rawData"] = {}
    for daq in scanInfo["daq list"]:
        scanInfo["rawData"][daq]={"meta":controller.daq[daq].meta,"data": None}
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(scanInfo["rawData"][daq]["meta"]["x"])
        else:
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)
        if controller.daq[daq].meta["oversampling_factor"] > 1 or scanInfo["include_return"]:
            scanInfo["rawData"][daq]["interpolate"] = True
        else:
            scanInfo["rawData"][daq]["interpolate"] = False

    controller.getMotorPositions()
    dataHandler.data.motorPositions[0] = controller.allMotorPositions

    # Move to start position
    controller.moveMotor(scan["z_motor"], zStart)

    waitTime = 0.005 + xPoints * 0.0001  # 0.005 + xRange * 0.02
    nxblocks, xcoarse, xStart_fine, xStop_fine = \
        controller.motors[scan["x_motor"]]["motor"].decompose_range(xStart, xStop)
    nyblocks, ycoarse, yStart_fine, yStop_fine = \
        controller.motors[scan["y_motor"]]["motor"].decompose_range(yStart, yStop)
    scanInfo["offset"] = xcoarse, ycoarse

    # first need to move the coarse motor to the correct position
    # this is annoying because it doesn't use the controllers moveMotor command.
    # this is done because we have to ensure it is the coarse motor that moves
    # but, first check for the correct coarseXY coordinates, it may not be needed if requested scan is within fine range
    # this function only moves the coarse motors if needed
    controller.motors[scan["x_motor"]]["motor"].move_coarse_to_fine_range(xStart, xStop)
    controller.motors[scan["y_motor"]]["motor"].move_coarse_to_fine_range(yStart, yStop)

    controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_count = xPoints * scanInfo["oversampling_factor"]
    controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_dwell = dataHandler.data.dwells[0] / scanInfo[
        "oversampling_factor"]
    controller.motors[scan["x_motor"]]["motor"].lineMode = "continuous"
    if not (coarse_only):
        # needs to be in piezo units
        # this should be changed to global units and then have the driver convert
        controller.motors[scan["x_motor"]]["motor"].trajectory_start = (xStart_fine, yStart_fine)
        controller.motors[scan["x_motor"]]["motor"].trajectory_stop = (xStop_fine, yStop_fine)
        controller.motors[scan["x_motor"]]["motor"].update_trajectory(include_return = scanInfo["include_return"])
    else:
        start_position_x = xStart - coarse_offset
        start_position_y = yStart
        # a "coarse_only" move will leave the servo off when done, otherwise will turn it back on
        controller.moveMotor(scan["x_motor"], xcoarse + start_position_x, coarse_only=True)
        controller.moveMotor(scan["y_motor"], xcoarse + start_position_y)
        controller.motors[scan["x_motor"]]["motor"].trajectory_start = (xStart, yPos_fine)
        controller.motors[scan["x_motor"]]["motor"].trajectory_stop = (xStop, yPos_fine)
        controller.motors[scan["x_motor"]]["motor"].update_trajectory()
        controller.motors[scan["x_motor"]]["motor"].trajectory_trigger = coarse_offset, coarse_offset

    #numMotorPoints should be the total number of motor position measurements expected
    #numDAQPoints should be equal to xPoints * oversampling
    numLineMotorPoints = controller.motors[scan["x_motor"]]["motor"].npositions #this configures the DAQ for one line
    numLineDAQPoints = controller.motors[scan["x_motor"]]["motor"].npositions * scan["oversampling_factor"]
    scanInfo['numMotorPoints'] = numLineMotorPoints * zPoints #total number of motor points configures the full data structrure
    scanInfo['numDAQPoints'] = scanInfo['numMotorPoints'] * scan["oversampling_factor"]
    dataHandler.data.updateArrays(0, scanInfo)
    controller.config_daqs(dwell = scanInfo["dwell"], count = 1, samples = numLineDAQPoints, trigger = "EXT")
    # controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, \
    #                                         samples=numLineDAQPoints, trigger="EXT")

    start_position_x = controller.motors[scan["x_motor"]]["motor"].trajectory_start[0] - \
                       controller.motors[scan["x_motor"]]["motor"].xpad
    start_position_y = controller.motors[scan["x_motor"]]["motor"].trajectory_start[1] - \
                       controller.motors[scan["x_motor"]]["motor"].ypad
    scanInfo["start_position_x"] = start_position_x
    scanInfo["start_position_y"] = start_position_y
    controller.moveMotor(scan["x_motor"], xcoarse + start_position_x)
    controller.moveMotor(scan["y_motor"], ycoarse + start_position_y)
    controller.moveMotor(scan["z_motor"], zPos[0])
    sleep(1)

    # turn on position trigger
    trigger_axis = controller.motors[scan["x_motor"]]["motor"].trigger_axis
    trigger_position = controller.motors[scan["x_motor"]]["motor"].trajectory_trigger[trigger_axis - 1]
    if trigger_axis == 1:
        axis = 'x_motor'
    elif trigger_axis == 2:
        axis = 'y_motor'
    controller.motors[scan[axis]]["motor"].setPositionTriggerOn(pos=trigger_position)
    scanInfo["trigger_axis"] = trigger_axis
    scanInfo["xpad"] = controller.motors[scan["x_motor"]]["motor"].xpad
    scanInfo["ypad"] = controller.motors[scan["x_motor"]]["motor"].ypad

    for i in range(len(zPos)):
        controller.moveMotor(scan["x_motor"], xcoarse + start_position_x)
        controller.moveMotor(scan["y_motor"], ycoarse + start_position_y)
        controller.moveMotor(scan["z_motor"], zPos[i])
        controller.getMotorPositions()
        dataHandler.data.motorPositions[0] = controller.allMotorPositions
        scanInfo["motorPositions"] = controller.allMotorPositions
        scanInfo["index"] = i * numLineDAQPoints
        scanInfo["lineIndex"] = i
        scanInfo["zIndex"] = 0
        if queue.empty():
            if not await doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime,axes=[1,2]):
                return await terminateFlyscan(controller, dataHandler, scan, "x_motor", "Data acquisition failed for flyscan line!")
        else:
            await queue.get()
            dataHandler.data.saveRegion(0)
            return await terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan aborted.")
    await dataHandler.dataQueue.put('endOfRegion')
    await terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan completed.")
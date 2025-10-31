from pystxmcontrol.controller.scans.scan_utils import *
from numpy import ones
from time import sleep
import asyncio

async def derived_line_image(scan, dataHandler, controller, queue):
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

    await scan["synch_event"].wait()
    energies = dataHandler.data.energies["default"]
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    scanInfo = {"mode": "continuousLine"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["scan_type"]
    scanInfo["oversampling_factor"] = controller.daq["default"].meta["oversampling_factor"]
    scanInfo['totalSplit'] = None
    scanInfo["direction"] = "forward"

    energyIndex = 0
    nScanRegions = len(xPos)
    scanInfo["coarse_only"] = scan["coarse_only"]
    coarse_only = scan["coarse_only"] #this needs to be set properly if a coarse scan is possible
    scanInfo["include_return"] = controller.scanConfig["scans"][scan["scan_type"]]["include_return"]
    coarse_offset = 20
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

    # Find minimum dwell, dwell padding, and worst time resolution for attached daqs.
    minDAQDwell = max([float(scanInfo["rawData"][daq]["meta"]["minimum dwell"]) for daq in scanInfo["daq list"] if not \
                      scanInfo["rawData"][daq]["meta"]["simulation"]]+[0.001])

    DAQDwellPad = max([float(scanInfo["rawData"][daq]["meta"]["dwell pad"]) for daq in scanInfo["daq list"] if not \
                      scanInfo["rawData"][daq]["meta"]["simulation"]]+[0.0])

    DAQTimeResolution = max([float(scanInfo["rawData"][daq]["meta"]["time resolution"]) for daq in scanInfo["daq list"] if not \
                      scanInfo["rawData"][daq]["meta"]["simulation"]]+[0.001])

    for energy in energies:
        #Handle motor and daq timing minimum/maximum values
        minMotorDwell = 0.12  # ms needs to be in config probably.
        maxMotorDwell = 5  # ms Ditto

        reqDwell = dataHandler.data.dwells[energyIndex]

        reqDAQDwell = min(maxMotorDwell - DAQDwellPad, max(minDAQDwell, minMotorDwell, reqDwell))
        actDAQDwell = np.floor(reqDAQDwell / DAQTimeResolution) * DAQTimeResolution
        actMotorDwell = actDAQDwell + DAQTimeResolution

        ##scanInfo is what gets passed with each data transmission
        scanInfo["energy"] = energy
        scanInfo["energyIndex"] = energyIndex
        scanInfo["dwell"] = actDAQDwell
        if len(energies) > 1:
            controller.moveMotor(scan["energy_motor"], energy)
        else:
            if scanInfo['scan']['autofocus']:
                controller.moveMotor("ZonePlateZ",
                                          controller.motors["Energy"]["motor"].calibratedPosition)

        for j in range(nScanRegions):
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
            scanInfo["yCenter"] = yStart - yRange / 2.
            scanInfo["yRange"] = yRange
            waitTime = 0.005 + xPoints * 0.0001  # 0.005 + xRange * 0.02

            #at this level nxblocks is always 1 because the decision to tile is higher up.  Need to put an option
            #there to untile and use the coarse motor

            #first need to move the coarse motor to the correct position
            #this is annoying because it doesn't use the controllers moveMotor command.
            #this is done because we have to ensure it is the coarse motor that moves
            #but, first check for the correct coarseXY coordinates, it may not be needed if requested scan is within fine range
            #this function only moves the coarse motors if needed
            controller.motors[scan["x_motor"]]["motor"].move_coarse_to_fine_range(xStart,xStop)
            controller.motors[scan["y_motor"]]["motor"].move_coarse_to_fine_range(yStart,yStop)
            controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_count = xPoints #* scanInfo["oversampling_factor"]
            controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_dwell = actMotorDwell / scanInfo[
                                                                                    "oversampling_factor"]
            controller.motors[scan["x_motor"]]["motor"].lineMode = "continuous"

            nxblocks, xcoarse, xStart_fine, xStop_fine = \
                controller.motors[scan["x_motor"]]["motor"].decompose_range(xStart, xStop)
            nyblocks, ycoarse, yStart_fine, yStop_fine = \
                controller.motors[scan["y_motor"]]["motor"].decompose_range(yStart, yStop)

            if coarse_only:
                xcoarse,ycoarse = 0.,0.
            scanInfo["offset"] = xcoarse,ycoarse

            if not (coarse_only):
                #needs to be in piezo units
                #this should be changed to global units and then have the driver convert
                controller.motors[scan["x_motor"]]["motor"].trajectory_start = (xStart_fine, yStart_fine)
                controller.motors[scan["x_motor"]]["motor"].trajectory_stop = (xStop_fine, yStart_fine)
                controller.motors[scan["x_motor"]]["motor"].update_trajectory(include_return = scanInfo["include_return"])
            else:
                start_position_x = xStart - coarse_offset
                start_position_y = yStart
                # a "coarse_oNly" move will leave the servo off when done, otherwise will turn it back on
                controller.motors[scan["x_motor"]]["motor"].trajectory_start = (xStart - coarse_offset, y[0])
                controller.motors[scan["x_motor"]]["motor"].trajectory_stop = (xStop + coarse_offset, y[0])
                controller.motors[scan["x_motor"]]["motor"].update_trajectory(include_return = False)
                controller.motors[scan["x_motor"]]["motor"].trajectory_trigger = coarse_offset, coarse_offset

            #numMotorPoints should be the total number of motor position measurements expected
            #numDAQPoints should be equal to xPoints * oversampling
            numLineMotorPoints = controller.motors[scan["x_motor"]]["motor"].npositions #this configures the DAQ for one line
            scanInfo["numLineDAQPoints"] = controller.motors[scan["x_motor"]]["motor"].npositions * scanInfo["oversampling_factor"]
            scanInfo['numMotorPoints'] = numLineMotorPoints * yPoints #total number of motor points configures the full data structrure
            scanInfo['numDAQPoints'] = scanInfo['numMotorPoints'] * scanInfo["oversampling_factor"]
            if energy == energies[0]:
                #this needs to have info per daq, but it doesn't currently
                dataHandler.data.updateArrays(j, scanInfo)

            controller.config_daqs(dwell = scanInfo["dwell"], count = 1, samples = scanInfo["numLineDAQPoints"], trigger = "EXT")
            start_position_x = controller.motors[scan["x_motor"]]["motor"].trajectory_start[0] - \
                               controller.motors[scan["x_motor"]]["motor"].xpad
            start_position_y = controller.motors[scan["x_motor"]]["motor"].trajectory_start[1] - \
                               controller.motors[scan["x_motor"]]["motor"].ypad
            scanInfo["start_position_x"] = start_position_x
            # needs to be in global units but start_position is generated in piezo units so add coarse.
            # Force both moves to use coarse to reset both piezos for large scans
            controller.moveMotor(scan["x_motor"], xcoarse + start_position_x, coarse_only = coarse_only)
            controller.moveMotor(scan["y_motor"], ycoarse + start_position_y, coarse_only = coarse_only)
            sleep(0.1)

            # turn on position 
            trigger_axis = controller.motors[scan["x_motor"]]["motor"].trigger_axis
            trigger_position = controller.motors[scan["x_motor"]]["motor"].trajectory_trigger[trigger_axis - 1]
            controller.motors[scan["x_motor"]]["motor"].setPositionTriggerOn(pos=trigger_position)
            scanInfo["trigger_axis"] = trigger_axis

            scanInfo["xpad"] = controller.motors[scan["x_motor"]]["motor"].xpad
            scanInfo["ypad"] = controller.motors[scan["x_motor"]]["motor"].ypad

            for i in range(len(y)):
                controller.moveMotor(scan["x_motor"], xcoarse + start_position_x)
                # Force the vertical move to use coarse motors for large scans
                controller.moveMotor(scan["y_motor"], y[i], coarse_only = coarse_only)
                controller.getMotorPositions()
                dataHandler.data.motorPositions[j] = controller.allMotorPositions
                scanInfo["motorPositions"] = controller.allMotorPositions
                scanInfo["index"] = i * numLineMotorPoints
                scanInfo["lineIndex"] = i
                scanInfo["zIndex"] = 0 #need to pass a zIndex to the dataHandler
                ##need to also be able to request measured positions
                scanInfo["xVal"], scanInfo["yVal"] = x, y[i] * ones(len(x))
                if queue.empty():
                    if not await doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime):
                        #this will just skip lines with a failed trigger, putting 0's in the data file
                        #this could instead loop through a few tries
                        pass
                else:
                    await queue.get()
                    dataHandler.data.saveRegion(j)
                    return await terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan aborted.")
            await dataHandler.dataQueue.put('endOfRegion') #this forces a saveRegion() in dataHandler
        energyIndex += 1
    await terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan completed.")

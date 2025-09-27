from pystxmcontrol.controller.scans.scan_utils import *
from pystxmcontrol.controller.spiral import spiralcreator
from numpy import ones
from time import sleep

def derived_spiral_image(scan, dataHandler, controller, queue):
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
    energies = dataHandler.data.energies["default"]
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    scanInfo = {"mode": "continuousSpiral"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["type"]
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo['totalSplit'] = None
    scanInfo['multiTrigger'] = True
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
            scanInfo['xVal'] = x
            scanInfo['yVal'] = y
            waitTime = 0.005 + xPoints * 0.0001  # 0.005 + xRange * 0.02
            nxblocks, xcoarse, xStart_fine, xStop_fine = \
                controller.motors[scan["x"]]["motor"].decompose_range(xStart, xStop)
            nyblocks, ycoarse, yStart_fine, yStop_fine = \
                controller.motors[scan["y"]]["motor"].decompose_range(yStart, yStop)
            scanInfo["offset"] = xcoarse,ycoarse
            scanInfo["xFineCenter"] = (xStart_fine + xStop_fine) / 2.
            scanInfo["yFineCenter"] = (yStart_fine + yStop_fine) / 2.

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
            controller.motors[scan["x"]]["motor"].lineMode = "arbitrary"

            # The spiral scan makes a circular spiral. We need to scale it to get an oval if the y and x range are different
            radius = max(xRange, yRange) / 2.
            aspectRatio = xRange / yRange

            # The dwell time plus the number of pixels sets the overall scan time.
            # This is multiplied by the DAQ oversampling factor.
            # Because this time is treated as a minimum, physical constraints can cause this time to increase.
            # Setting dwell to 0 will run the scan as fast as possible.
            DAQOversample = 2.  # Average number of DAQ measurements per pixel. Doesn't affect scan time.
            reqDwell = dataHandler.data.dwells[energyIndex]
            numTotalPixels = xPoints * yPoints * np.pi / 4  # float
            reqScanTime = reqDwell * numTotalPixels / 1000  # seconds

            # number of loops is given by half the number of pixels (max of x and y).
            # Loop oversampling multiplies this number to reduce number of pixels without any loops, but makes it slower.
            # Number of loops is (probably) the limiting speed factor for small scans so don't set this too high.
            loopOversample = 1.2
            numLoops = int(max(xPoints, yPoints) * loopOversample / 2.)

            # There's a maximal frequency at which the scan can be performed.
            # We end up scanning at a constant linear velocity for larger scans, so I am unsure how to set this without
            # changing how the spiral is generated. There's a fudge factor of 2 here because the inner spiral is faster.
            fMax = 100.  # Hz
            minTime = numLoops / fMax * 2.
            minFreqScanTime = max(minTime, reqScanTime)

            # We also can't have more than 5000 points per motor trajectory.
            # The number of corners per loop sets how circular they are. Setting this larger shouldn't affect speed too much.
            # We also limit the motor positions based on the dwell allowed by the MCL controller.
            # The original script also had a maximal speed. We ignore that here.
            numCorners = 50  # minimum average corners per loop
            minMotorDwell = 0.12  # ms
            maxMotorDwell = 10.  # ms

            # minimal time allowed for motor movements (many loops)
            minLoopMotorPoints = numCorners * numLoops
            minLoopMotorScanTime = minLoopMotorPoints * minMotorDwell / 1000

            # total scan time is now determined
            totScanTime = max(minFreqScanTime, minLoopMotorScanTime)

            # Another case to look at is when the dwell is very long.
            minDwellMotorPoints = totScanTime / maxMotorDwell

            # The total time for a single trajectory cannot be larger than 2.5 or MCL will crash.
            # We fix this by separating into multiple trajectories if necessary.
            maxTrajTime = 2.5  # seconds
            timeSplit = int(np.ceil(max(1, totScanTime / maxTrajTime)))

            # We also may need to split it based on motor points if there are a large number of loops or a long dwell.
            maxTrajPoints = 5000  # points
            reqMotorPoints = max(minDwellMotorPoints, minLoopMotorPoints)
            motorSplit = int(np.ceil(max(1, reqMotorPoints / maxTrajPoints)))

            # Now we know the total number of times the scan has to be split and we can set up the trajectories.
            totalSplit = max(timeSplit, motorSplit)
            totalTrajTime = totScanTime / totalSplit

            # The number of motor points can be set to maximum unless this makes the dwell too short.
            # These are the desired number of points, but we have to adjust them again to round to the nearest 0.01 ms.
            motorTimeResolution = 0.001  # ms (based off old manual. Likely correct though.)
            # Here we set the dwell to the value for 5000 motor points in a trajectory.
            if totalTrajTime / maxTrajPoints >= minMotorDwell / 1000.:
                desMotorDwell = totalTrajTime / maxTrajPoints * 1000.
                # Round to nearest dwell time. Ceiling so we don't have > 5000 points
                actMotorDwell = np.ceil(desMotorDwell / motorTimeResolution) * motorTimeResolution
                numTrajMotorPoints = int(totalTrajTime / actMotorDwell * 1000.)
            # If we can't, we instead set the dwell to the minimum
            else:
                actMotorDwell = minMotorDwell
                numTrajMotorPoints = int(totalTrajTime / actMotorDwell * 1000.)

            # scanTime might be slightly different than the prior estimate
            scanTime = numTrajMotorPoints * actMotorDwell * totalSplit / 1000.  # s

            # The spiral construction needs the sampling frequency and some of the future calculations need the total number of positions.
            samplingFrequency = 1 / actMotorDwell * 1000.  # Hz
            nPosSamples = numTrajMotorPoints * totalSplit

            # The DAQ dwell time is set by the number of pixels requested and the actual scan time
            # Resolution for the DAQ is 1 us.
            DAQTimeResolution = 0.001  # ms (based on keysight manual and reading out CONF? command)
            trajPixels = int(numTotalPixels / totalSplit * DAQOversample)
            reqDAQDwell = totalTrajTime / trajPixels * 1000.
            actDAQDwell = int(reqDAQDwell / DAQTimeResolution) * DAQTimeResolution
            numTrajDAQPoints = int(totalTrajTime / actDAQDwell * 1000.)

            scanInfo['motorDwell'] = actMotorDwell
            scanInfo['DAQDwell'] = actDAQDwell
            scanInfo['DAQOversample'] = DAQOversample
            scanInfo['totalSplit'] = totalSplit

            dataHandler.updateDwells(scanInfo)

            # Generates a spiral based on parameters given.
            ySpiral, xSpiral = spiralcreator(samplingfrequency=samplingFrequency, scantime=scanTime, numloops=numLoops,
                                             clockwise=True, \
                                             spiralscantype="InstrumentLimits", inratio=0.05, scanradius=radius,
                                             maxFreqXY=fMax)

            # Readjust these points to shrink the appropriate dimension and add the center back in.
            if aspectRatio > 1:
                ySpiral = ySpiral / aspectRatio
            else:
                xSpiral = xSpiral * aspectRatio

            xSpiral += scanInfo['xFineCenter']
            ySpiral += scanInfo['yFineCenter']

            # Wait time (50 ms, test this)
            waitTime = 0.05

            # enforce the correct size of these arrays to avoid off by one errors.
            if len(xSpiral) < nPosSamples:
                xSpiral = np.pad(xSpiral, (0, nPosSamples - len(xSpiral)), mode='edge')
                ySpiral = np.pad(ySpiral, (0, nPosSamples - len(xSpiral)), mode='edge')
            elif len(xSpiral) > nPosSamples:
                xSpiral = xSpiral[:nPosSamples]
                ySpiral = ySpiral[:nPosSamples]

            # Split the list according to the number of splits identified previously.
            xList = xSpiral.reshape(totalSplit, int(nPosSamples / totalSplit))
            yList = ySpiral.reshape(totalSplit, int(nPosSamples / totalSplit))

            # Set up DAQ acquisition
            DAQcount = numTrajMotorPoints
            DAQsamples = int(np.ceil(numTrajDAQPoints / DAQcount))
            numTrajDAQPoints = DAQsamples * DAQcount
            # we pad the dwell time so that the daq is done collecting by the time the motor has moved on to the next position.
            # May have to make this dependent on the motor dwell time? 4 us is a total guess.
            dwellPad = 0.005 * DAQsamples
            actDAQDwell = int(
                np.floor((actMotorDwell - dwellPad) / DAQsamples / DAQTimeResolution)) * DAQTimeResolution

            #print('Configuring DAQ: {} ms dwell, {} count, {} samples, "EXT" trigger'.format(actDAQDwell,DAQcount,DAQsamples))
            # controller.daq["default"].config(actDAQDwell, count=DAQcount, samples=DAQsamples, trigger="EXT")
            controller.config_daqs(dwell = actDAQDwell, count = DAQcount, samples = DAQSamples, trigger = "EXT")

            # Move to first position
            controller.moveMotor(scan["x"], xcoarse + scanInfo['xFineCenter'])
            controller.moveMotor(scan["y"], ycoarse + scanInfo['yFineCenter'])
            sleep(0.2)

            # Fix raw data sizes in writeNX (only first energy)
            if energy == energies[0]:
                scanInfo["lineIndex"] = 0
                scanInfo['numMotorPoints'] = numTrajMotorPoints * totalSplit
                scanInfo['numDAQPoints'] = numTrajDAQPoints * totalSplit
                dataHandler.data.updateArrays(j, scanInfo)
                # params = {}
                # params['numTrajMotorPoints'] = numTrajMotorPoints
                # params['numTraj'] = totalSplit
                # params['numTrajDAQPoints'] = numTrajDAQPoints
                # dataHandler.data.updateArrays(j, params)

            # MCL "position" trigger does not need a position. I am unsure whether this is the pixel triggering mode.
            controller.motors[scan["x"]]["motor"].axes["axis1"].controller.setPositionTrigger(pos = 0, axis = 1, mode = 'on')

            for i in range(len(xList)):

                controller.getMotorPositions()
                dataHandler.data.motorPositions[j] = controller.allMotorPositions
                scanInfo["motorPositions"] = controller.allMotorPositions
                scanInfo["index"] = i  # *scanInfo['nPoints']

                # Do flyscan line?
                if queue.empty():
                    while controller.pause:
                        if not (queue.empty()):
                            queue.get()
                            dataHandler.dataQueue.put('endOfScan')
                            print("Terminating grid scan")
                            return False
                        sleep(0.1)
                    scanInfo["direction"] = "forward"

                    # Set up motor trajectory
                    xMotorPos = xList[i]
                    yMotorPos = yList[i]
                    controller.motors[scan["x"]]["motor"].trajectory_pixel_count = len(xMotorPos)
                    controller.motors[scan["x"]]["motor"].trajectory_pixel_dwell = actMotorDwell
                    controller.motors[scan["x"]]["motor"].lineMode = "arbitrary"
                    controller.motors[scan["x"]]["motor"].trajectory_x_positions = xMotorPos
                    controller.motors[scan["x"]]["motor"].trajectory_y_positions = yMotorPos
                    controller.motors[scan["x"]]["motor"].update_trajectory()
                    #print('Configuring Motor Controller: {} dwell, {} points'.format(actMotorDwell,len(xMotorPos)))

                    # If we ever have a position trigger, we will need this.
                    # trigger_axis = controller.motors[scan["x"]]["motor"].trigger_axis
                    # trigger_position = controller.motors[scan["x"]]["motor"].trajectory_trigger[trigger_axis-1]
                    # controller.motors[scan["x"]]["motor"].setPositionTriggerOn(pos = trigger_position)

                    if not doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime):
                        return terminateFlyscan(controller, dataHandler, scan, "x", "Data acquisition failed for flyscan line!")
                else:
                    queue.get()
                    dataHandler.data.saveRegion(j, nt=totalSplit)
                    return terminateFlyscan(controller, dataHandler, scan, "x", "Flyscan aborted.")
            dataHandler.dataQueue.put('endOfRegion')
        energyIndex += 1
    terminateFlyscan(controller, dataHandler, scan, "x", "Flyscan completed.")

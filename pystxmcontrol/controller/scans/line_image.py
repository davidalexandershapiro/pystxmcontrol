from pystxmcontrol.controller.scans.scan_utils import *
from numpy import ones
from time import time

def line_image(scan, dataHandler, controller, queue):
    """
    Image scan in continuous flyscan mode.  Uses linear trajectory function on the controller
    :param scan:
    :return:
    """
    try:
        #this only works on Nanosurveyor
        controller.moveMotor("Detector Y", 0)
    except:
        pass
    energies = dataHandler.data.energies
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    scanInfo = {"mode": "continuousLine"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["scan_type"]
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo['totalSplit'] = None
    energyIndex = 0
    nScanRegions = len(xPos)
    energy = energies[0]
    if not scanInfo['scan']['autofocus']:
        currentZonePlateZ = controller.motors['ZonePlateZ']['motor'].getPos()
    for energy in energies:
        ##scanInfo is what gets passed with each data transmission
        scanInfo["energy"] = energy
        scanInfo["energyIndex"] = energyIndex
        scanInfo["dwell"] = dataHandler.data.dwells[energyIndex]
        if len(energies) > 1:
            controller.moveMotor(scan["energy_motor"], energy)
            if not scanInfo['scan']['autofocus']:
                if energy == energies[0]:
                    scanInfo['refocus_offset'] = currentZonePlateZ - controller.motors['ZonePlateZ'][
                        'motor'].calibratedPosition
                    print('calculated offset: {}'.format(scanInfo['refocus_offset']))
                controller.moveMotor('ZonePlateZ',
                                          controller.motors['Energy']['motor'].calibratedPosition + scanInfo[
                                              'refocus_offset'])
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
            scanInfo["yCenter"] = yStart + yRange / 2.
            scanInfo["yRange"] = yRange
            waitTime = 0.005 + xPoints * 0.0001  # 0.005 + xRange * 0.02
            controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_count = xPoints * scan["oversampling_factor"]
            controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_dwell = dataHandler.data.dwells[
                                                                                    energyIndex] / scan[
                                                                                    "oversampling_factor"]
            controller.motors[scan["x_motor"]]["motor"].lineMode = "continuous"
            controller.motors[scan["x_motor"]]["motor"].trajectory_start = (xStart, yStart)
            controller.motors[scan["x_motor"]]["motor"].trajectory_stop = (xStop, yStart)
            controller.motors[scan["x_motor"]]["motor"].update_trajectory()

            #numMotorPoints should be the total number of motor position measurements expected
            #numDAQPoints should be equal to xPoints * oversampling
            numLineMotorPoints = controller.motors[scan["x_motor"]]["motor"].npositions #this configures the DAQ for one line
            numLineDAQPoints = controller.motors[scan["x_motor"]]["motor"].npositions * scan["oversampling_factor"]
            scanInfo['numMotorPoints'] = numLineMotorPoints * yPoints #total number of motor points configures the full data structrure
            scanInfo['numDAQPoints'] = scanInfo['numMotorPoints'] * scan["oversampling_factor"]
            if energy == energies[0]:
                dataHandler.data.updateArrays(j, scanInfo)
            controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, \
                                                  samples=numLineDAQPoints, trigger="EXT")
            
            start_position_x = controller.motors[scan["x_motor"]]["motor"].trajectory_start[0] - \
                               controller.motors[scan["x_motor"]]["motor"].xpad
            start_position_y = controller.motors[scan["x_motor"]]["motor"].trajectory_start[1] - \
                               controller.motors[scan["x_motor"]]["motor"].ypad
            scanInfo["start_position_x"] = start_position_x
            # move to start
            controller.moveMotor(scan["x_motor"], start_position_x)
            controller.moveMotor(scan["y_motor"], start_position_y)

            # turn on position trigger
            trigger_axis = controller.motors[scan["x_motor"]]["motor"].trigger_axis
            trigger_position = controller.motors[scan["x_motor"]]["motor"].trajectory_trigger[trigger_axis - 1]
            #controller.motors[scan["x"]]["motor"].setPositionTriggerOn(pos=trigger_position)
            scanInfo["trigger_axis"] = trigger_axis
            scanInfo["xpad"] = controller.motors[scan["x_motor"]]["motor"].xpad
            scanInfo["ypad"] = controller.motors[scan["x_motor"]]["motor"].ypad
            for i in range(len(y)):
                controller.moveMotor(scan['y_motor'], y[i])
                controller.getMotorPositions()
                dataHandler.data.motorPositions[j] = controller.allMotorPositions
                scanInfo["motorPositions"] = controller.allMotorPositions
                scanInfo["index"] = i * numLineDAQPoints
                scanInfo["lineIndex"] = i
                scanInfo["zIndex"] = 0 #need to pass a zIndex to the dataHandler
                ##need to also be able to request measured positions
                scanInfo["xVal"], scanInfo["yVal"] = x, y[i] * ones(len(x))
                if queue.empty():
                    if not doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime):
                        return terminateFlyscan(controller, dataHandler, scan, "x_motor", "Data acquisition failed for flyscan line!")
                else:
                    queue.get()
                    dataHandler.data.saveRegion(j)
                    return terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan aborted.")
            dataHandler.dataQueue.put('endOfRegion') #this forces a saveRegion() in dataHandler
        energyIndex += 1
    terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan completed.")
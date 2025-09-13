import time

def osa_focus_scan(scan, dataHandler, controller, queue):
    """
    This is a point mode focus line scan where the line is defined by OSAX and OSAY and the focus axis is ZonePlateZ.
    It is done with the OSA in focus so the Z positions are shifted negative by A0
    :param scan:
    :return:
    """
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    energies = dataHandler.data.energies
    scanInfo = {"mode": "point"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["scan_type"]
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo["zIndex"] = 0
    energyIndex = 0

    ##scanInfo is what gets passed with each data transmission
    regionNum = 0
    scanInfo["energyIndex"] = 0
    scanInfo["energy"] = energies[energyIndex]
    scanInfo["dwell"] = dataHandler.data.dwells[energyIndex]

    #move the zone plate to be focused on the OSA
    A0 = controller.motors["Energy"]["motor"].config["A0"]
    controller.moveMotor("ZonePlateZ",controller.motors["Energy"]["motor"].calibratedPosition-A0)

    x, y, z = xPos[regionNum], yPos[regionNum], zPos[regionNum]
    scanInfo["scanRegion"] = "Region" + str(regionNum + 1)
    xStart, xStop = x[0], x[-1]
    yStart, yStop = y[0], y[-1]
    xRange, yRange = xStop - xStart, yStop - yStart
    xPoints, yPoints = len(x), len(y)
    xStep, yStep = xRange / (xPoints - 1), yRange / (yPoints - 1)

    #these into scanINfo so the GUI knows where to put the data for a script scan
    scanInfo["xPoints"] = xPoints
    scanInfo["xStep"] = xStep
    scanInfo["xStart"] = xStart
    scanInfo["xCenter"] = xStart + xRange / 2.
    scanInfo["xRange"] = xRange
    scanInfo["yPoints"] = 1
    scanInfo["yStep"] = 0
    scanInfo["yStart"] = yStart
    scanInfo["yCenter"] = yStart
    scanInfo["yRange"] = 0
    controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, samples=1)

    #Since this is a line scan, we don't want to loop over all X-Y positions, but rather just one move each.
    for i in range(len(z)):
        controller.moveMotor("ZonePlateZ", z[i]-A0)
        controller.getMotorPositions()
        dataHandler.data.motorPositions[0] = controller.allMotorPositions
        scanInfo["motorPositions"] = controller.allMotorPositions
        for j in range(len(x)):
            controller.moveMotor(scan["y_motor"], yPos[0][j])
            controller.moveMotor(scan["x_motor"], xPos[0][j])
            # controller.getMotorPositions()
            # dataHandler.data.motorPositions[0] = controller.allMotorPositions
            # scanInfo["motorPositions"] = controller.allMotorPositions
            scanInfo["lineIndex"] = i
            scanInfo["columnIndex"] = j
            scanInfo["index"] = i * len(z) + j
            if queue.empty():
                controller.daq["default"].autoGateOpen(shutter=True)
                dataHandler.getPoint(scanInfo)
                controller.daq["default"].autoGateClosed()
            else:
                queue.get()
                dataHandler.data.saveRegion(0)
                dataHandler.dataQueue.put('endOfScan')
                return
    dataHandler.data.saveRegion(0)
    dataHandler.dataQueue.put('endOfScan')
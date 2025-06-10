
def single_motor_scan(scan, dataHandler, controller, queue):
    """
    Single motor point scan
    :param scan:
    :return:
    """
    regionNum = 0
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    energies = dataHandler.data.energies
    scanInfo = {"mode": "point"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["type"]
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo["lineIndex"] = 0
    scanInfo["zIndex"] = 0
    if len(energies) > 1:
        scanInfo["scanMotor"] = "Energy"
    else:
        scanInfo["scanMotor"] = scan["x"]
    energyIndex = 0

    if not scanInfo['scan']['refocus']:
        currentZonePlateZ = controller.motors['ZonePlateZ']['motor'].getPos()
    for energy in energies:
        ##scanInfo is what gets passed with each data transmission
        scanInfo["energy"] = energy
        scanInfo["energyIndex"] = energyIndex
        scanInfo["dwell"] = dataHandler.data.dwells[energyIndex]
        if len(energies) > 1:
            controller.moveMotor(scan["energy"], energy)
            if not scanInfo['scan']['refocus']:
                if energy == energies[0]:
                    scanInfo['refocus_offset'] = currentZonePlateZ - controller.motors['ZonePlateZ'][
                        'motor'].calibratedPosition
                    print('calculated offset: {}'.format(scanInfo['refocus_offset']))
                controller.moveMotor('ZonePlateZ',
                                          controller.motors['ZonePlateZ']['motor'].calibratedPosition + scanInfo[
                                              'refocus_offset'])
        else:
            if scanInfo['scan']['refocus']:
                controller.moveMotor("ZonePlateZ",
                                          controller.motors["ZonePlateZ"]["motor"].calibratedPosition)
        x, y = xPos[regionNum], yPos[regionNum]
        scanInfo["scanRegion"] = "Region" + str(regionNum + 1)
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
        scanInfo["yPoints"] = 1
        scanInfo["yStep"] = 0
        scanInfo["yStart"] = yStart
        scanInfo["yCenter"] = yStart
        scanInfo["yRange"] = 0
        controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, samples=1, trigger="EXT")
        for i in range(len(xPos[0])):
            if scanInfo["scanMotor"] == "Energy":
                scanInfo["scanMotorVal"] = energy
            else:
                scanInfo["scanMotorVal"] = xPos[0][i]
            scanInfo["index"] = i
            controller.moveMotor(scan["x"], xPos[0][i])
            if queue.empty():
                controller.daq["default"].autoGateOpen(shutter=True)
                dataHandler.getPoint(scanInfo)
                controller.daq["default"].autoGateClosed()
            else:
                queue.get()
                dataHandler.data.saveRegion(0)
                dataHandler.dataQueue.put('endOfScan')
                return
        energyIndex += 1
    dataHandler.data.saveRegion(0)
    dataHandler.dataQueue.put('endOfScan')
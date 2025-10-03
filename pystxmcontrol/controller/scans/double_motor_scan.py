import time
import asyncio

async def double_motor_scan(scan, dataHandler, controller, queue):
    """
    Double motor point scan
    :param scan:
    :return:
    """

    await scan["synch_event"].wait()
    regionNum = 0
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    energies = dataHandler.data.energies["default"]
    scanInfo = {"mode": "point"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["scan_type"]
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo["zIndex"] = 0
    energyIndex = 0
    scanInfo['daq list'] = scan['daq list']
    scanInfo["rawData"] = {}
    for daq in controller.daq.keys():
        scanInfo["rawData"][daq]={"meta":controller.daq[daq].meta,"data": None}
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(scanInfo["rawData"][daq]["meta"]["x"])
        else:
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)
        if controller.daq[daq].meta["oversampling_factor"] > 1:
            scanInfo["rawData"][daq]["interpolate"] = True
        else:
            scanInfo["rawData"][daq]["interpolate"] = False

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
        # controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, samples=1)
        controller.config_daqs(dwell = scanInfo["dwell"], count = 1, samples = 1, trigger = "BUS")

        for i in range(len(yPos[0])):
            controller.moveMotor(scan["y_motor"], yPos[0][i])
            #time.sleep(0.02)
            controller.getMotorPositions()
            dataHandler.data.motorPositions[0] = controller.allMotorPositions
            scanInfo["motorPositions"] = controller.allMotorPositions
            for j in range(len(xPos[0])):
                scanInfo["lineIndex"] = i
                scanInfo["columnIndex"] = j
                scanInfo["index"] = i * len(yPos[0]) + j
                controller.moveMotor(scan["x_motor"], xPos[0][j])
                if queue.empty():
                    controller.daq["default"].autoGateOpen(shutter=True)
                    await dataHandler.getPoint(scanInfo)
                    controller.daq["default"].autoGateClosed()
                else:
                    queue.get()
                    dataHandler.data.saveRegion(0)
                    await dataHandler.dataQueue.put('endOfScan')
                    return
        energyIndex += 1
    dataHandler.data.saveRegion(0)
    await dataHandler.dataQueue.put('endOfScan')
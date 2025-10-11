import time
import asyncio
import numpy as np

async def osa_focus_scan(scan, dataHandler, controller, queue):
    """
    This is a point mode focus line scan where the line is defined by OSAX and OSAY and the focus axis is ZonePlateZ.
    It is done with the OSA in focus so the Z positions are shifted negative by A0
    :param scan:
    :return:
    """

    await scan["synch_event"].wait()
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    energies = dataHandler.data.energies["default"]
    scanInfo = {}
    mode = scan["mode"]
    scanInfo["mode"] = mode
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
    scanInfo['daq list'] = scan['daq list']
    scanInfo["rawData"] = {}
    for daq in controller.daq.keys():
        scanInfo["rawData"][daq]={"meta":controller.daq[daq].meta,"data": None}
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(scanInfo["rawData"][daq]["meta"]["x"])
        else:
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)
        scanInfo["rawData"][daq]["interpolate"] = False

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
    if mode == "point":
        samples = 1
    elif mode == "continuousLine":
        samples = scanInfo["xPoints"]
        velocity = scanInfo["xStep"] / scanInfo["dwell"]
        controller.motors[scan["x_motor"]]["motor"].setAxisParams(velocity)
        # Update arrays for continuous line mode to ensure proper dimensionality
        scanInfo['numMotorPoints'] = samples * len(yPos[0])
        scanInfo['numDAQPoints'] = samples * len(yPos[0])
        for daq in controller.daq.keys():
            if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
                scanInfo["rawData"][daq]["meta"]["n_energies"] = len(scanInfo["rawData"][daq]["meta"]["x"])
            else:
                scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)
        dataHandler.data.updateArrays(0, scanInfo)
    controller.config_daqs(dwell=scanInfo["dwell"], count=1, samples=samples, trigger="BUS")

    #Since this is a line scan, we don't want to loop over all X-Y positions, but rather just one move each.
    for i in range(len(z)):
        controller.moveMotor("ZonePlateZ", z[i]-A0)
        controller.getMotorPositions()
        dataHandler.data.motorPositions[0] = controller.allMotorPositions
        scanInfo["motorPositions"] = controller.allMotorPositions
        scanInfo["lineIndex"] = i
        if mode == "point":
            for j in range(len(x)):
                controller.moveMotor(scan["y_motor"], yPos[0][j])
                controller.moveMotor(scan["x_motor"], xPos[0][j])
                scanInfo["columnIndex"] = j
                scanInfo["index"] = i * len(z) + j
                if queue.empty():
                    controller.daq["default"].autoGateOpen(shutter=True)
                    await dataHandler.getPoint(scanInfo)
                    controller.daq["default"].autoGateClosed()
                else:
                    queue.get()
                    dataHandler.data.saveRegion(0)
                    await dataHandler.dataQueue.put('endOfScan')
                    return
        elif mode == "continuousLine":
            scanInfo["index"] = i * len(yPos[0])
            controller.moveMotor(scan["x_motor"],xStart)
            if queue.empty():
                controller.daq["default"].initLine()
                controller.daq["default"].autoGateOpen()
                controller.daq["default"].bus_trigger()
                controller.moveMotor(scan["x_motor"],xStop)
                controller.daq["default"].autoGateClosed()
                scanInfo["line_positions"] = [np.linspace(xStart,xStop,samples),np.ones(samples)*yPos[0][i]]
                try:
                    await dataHandler.getLine(scanInfo.copy())
                except:
                    pass
            else:
                queue.get()
                dataHandler.data.saveRegion(0)
                await dataHandler.dataQueue.put('endOfScan')
                return
    dataHandler.data.saveRegion(0)
    await dataHandler.dataQueue.put('endOfScan')
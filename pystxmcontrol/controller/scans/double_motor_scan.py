import time
import asyncio
import numpy as np

async def double_motor_scan(scan, dataHandler, controller, queue):
    """
    Double motor point scan
    :param scan:
    :return:
    """

    xhome = controller.allMotorPositions[scan["x_motor"]]
    yhome = controller.allMotorPositions[scan["y_motor"]]
    def move_home():
        controller.moveMotor(scan["x_motor"],xhome)
        controller.moveMotor(scan["y_motor"],yhome)

    await scan["synch_event"].wait()
    regionNum = 0
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
    scanInfo["direction"] = "forward"
    scanInfo['daq list'] = scan['daq list']
    scanInfo["rawData"] = {}
    for daq in controller.daq.keys():
        scanInfo["rawData"][daq]={"meta":controller.daq[daq].meta,"data": None}
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(scanInfo["rawData"][daq]["meta"]["x"])
        else:
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)
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
        # I'm putting all of these into scanInfo so the GUI knows where to put the data for a script scan
        scanInfo["xPoints"] = xPoints
        scanInfo["xStep"] = xStep
        scanInfo["xStart"] = xStart
        scanInfo["xCenter"] = xStart + xRange / 2.
        scanInfo["xRange"] = xRange
        scanInfo["yPoints"] = yPoints
        scanInfo["yStep"] = yStep
        scanInfo["yStart"] = yStart
        scanInfo["yCenter"] = yStart
        scanInfo["yRange"] = yRange
        if mode == "point":
            samples = 1
        elif mode == "continuousLine":
            samples = scanInfo["xPoints"]
            velocity = scanInfo["xStep"]/scanInfo["dwell"]
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
        controller.config_daqs(dwell = scanInfo["dwell"], count = 1, samples = samples, trigger = "BUS")

        for i in range(len(yPos[0])):
            controller.moveMotor(scan["y_motor"], yPos[0][i])
            #time.sleep(0.02)
            controller.getMotorPositions()
            dataHandler.data.motorPositions[0] = controller.allMotorPositions
            scanInfo["motorPositions"] = controller.allMotorPositions
            scanInfo["lineIndex"] = i
            if mode == "point":
                for j in range(len(xPos[0])):
                    scanInfo["columnIndex"] = j
                    scanInfo["index"] = i * len(yPos[0]) + j
                    controller.moveMotor(scan["x_motor"], xPos[0][j])
                    if queue.empty():
                        controller.daq["default"].autoGateOpen()
                        await dataHandler.getPoint(scanInfo)
                        controller.daq["default"].autoGateClosed()
                    else:
                        await queue.get()
                        dataHandler.data.saveRegion(0)
                        move_home()
                        await dataHandler.dataQueue.put('endOfScan')
                        return
            elif mode == "continuousLine":
                scanInfo["index"] = i * len(yPos[0])
                try:
                    backlash = controller.motors[scan['x_motor']]['motor'].config['backlash']
                except:
                    backlash = 0.
                scanInfo["direction"] = "forward"
                controller.moveMotor(scan["x_motor"],xStart)
                target = xStop
                if queue.empty():
                    controller.daq["default"].initLine()
                    controller.daq["default"].autoGateOpen()
                    controller.daq["default"].bus_trigger()
                    controller.moveMotor(scan["x_motor"],target)
                    controller.daq["default"].autoGateClosed()
                    scanInfo["line_positions"] = [np.linspace(xStart,xStop,samples),np.ones(samples)*yPos[0][i]]
                    try: 
                        await dataHandler.getLine(scanInfo.copy())
                    except:
                        pass
                else:
                    await queue.get()
                    dataHandler.data.saveRegion(0)
                    move_home()
                    await dataHandler.dataQueue.put('endOfScan')
                    return
        energyIndex += 1
    dataHandler.data.saveRegion(0)
    move_home()
    await dataHandler.dataQueue.put('endOfScan')
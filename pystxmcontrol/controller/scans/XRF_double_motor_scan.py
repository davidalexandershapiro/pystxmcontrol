import time
import asyncio
import numpy as np
from pystxmcontrol.controller.scans.scan_utils import set_scan_energy

async def XRF_double_motor_scan(scan, dataHandler, controller, queue):
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
    scanInfo["zIndex"] = 0
    energyIndex = 0
    scanInfo["direction"] = "forward"
    scanInfo['daq_list'] = scan['daq_list']
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
        # Move energy motor (deadband for single-energy) and record actual energy.
        set_scan_energy(controller, scan, scanInfo, energy, energies)
        if len(energies) > 1:
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

        for daq in controller.daq.keys():
            if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
                scanInfo["rawData"][daq]["meta"]["n_energies"] = len(scanInfo["rawData"][daq]["meta"]["x"])
            else:
                scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)

        scanInfo["yRange"] = yRange
        samples = scanInfo["xPoints"]
        # Update arrays for continuous line mode to ensure proper dimensionality
        scanInfo['numMotorPoints'] = samples * len(yPos[0])
        scanInfo['numDAQPoints'] = samples * len(yPos[0])
        dataHandler.data.updateArrays(0, scanInfo)
        controller.config_daqs(dwell = scanInfo["dwell"], count = 1, samples = samples, trigger = "EXT", daq_list = scanInfo["daq_list"])

        for i in range(len(yPos[0])):
            controller.moveMotor(scan["y_motor"], yPos[0][i])
            #time.sleep(0.02)
            controller.getMotorPositions()
            dataHandler.data.motorPositions[0] = controller.allMotorPositions
            scanInfo["motorPositions"] = controller.allMotorPositions
            scanInfo["lineIndex"] = i
            # arm the daqs for a line of external triggers
            for daq in scanInfo["daq_list"]:
                controller.daq[daq].initLine()
            for j in range(len(xPos[0])):
                scanInfo["index"] = i * len(yPos[0])
                controller.moveMotor(scan["x_motor"], xPos[0][j])
                if queue.empty():
                    #autoGateOpen() sends a trigger to the shutter.  We need to connect that to all daqs
                    controller.daq["default"].autoGateOpen(shutter = 1)
                    await asyncio.sleep(scanInfo["dwell"]/1000.)
                    controller.daq["default"].autoGateClosed()
                else:
                    await queue.get()
                    dataHandler.data.saveRegion(0)
                    move_home()
                    await dataHandler.dataQueue.put('endOfScan')
                    return
            await dataHandler.getLine(scanInfo.copy())
        energyIndex += 1
    await dataHandler.dataQueue.put('endOfScan')
    await asyncio.sleep(0.1)
    dataHandler.data.saveRegion(0)
    move_home()
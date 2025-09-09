from pystxmcontrol.controller.scans.scan_utils import *
from numpy import ones
import time


def line_focus(scan, dataHandler, controller, queue):
    controller.moveMotor("Detector Y", 0)
    energies = dataHandler.data.energies
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
    scanInfo["xPoints"] = xPoints
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo["xVal"] = xPos
    scanInfo["yVal"] = yPos
    scanInfo['totalSplit'] = None

    scanInfo["include_return"] = True
    controller.motors[scan["x_motor"]]["motor"].include_return = scanInfo["include_return"]

    controller.getMotorPositions()
    dataHandler.data.motorPositions[0] = controller.allMotorPositions

    # Move to start position
    controller.moveMotor(scan["z_motor"], zStart)

    # for arbitrary line, xPoints and yPoints are the same
    controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_count = xPoints * scanInfo["oversampling_factor"]
    controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_dwell = dataHandler.data.dwells[0] / scanInfo[
        "oversampling_factor"]
    controller.motors[scan["x_motor"]]["motor"].lineMode = "continuous"
    controller.motors[scan["x_motor"]]["motor"].trajectory_start = (xStart, yStart)
    controller.motors[scan["x_motor"]]["motor"].trajectory_stop = (xStop, yStop)
    controller.motors[scan["x_motor"]]["motor"].include_return = scanInfo["include_return"]
    ##during the scan, the driver takes care of padding for the acceleration distance automagically but for the
    # move to start command it needs to be added manually I guess
    controller.motors[scan["x_motor"]]["motor"].update_trajectory()

    ne,ny,nx = dataHandler.data.interp_counts[0].shape
    dataHandler.data.interp_counts[0] = np.zeros((ne,ny,nx))
    numLineMotorPoints = controller.motors[scan["x_motor"]]["motor"].npositions #this configures the DAQ for one line
    numLineDAQPoints = controller.motors[scan["x_motor"]]["motor"].npositions * scan["oversampling_factor"]
    scanInfo['numMotorPoints'] = numLineMotorPoints * len(zPos) #total number of motor points configures the full data structrure
    scanInfo['numDAQPoints'] = numLineDAQPoints * len(zPos)

    dataHandler.data.updateArrays(0, scanInfo)
    controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, \
                                            samples=numLineDAQPoints, trigger="EXT")

    start_position_x = controller.motors[scan["x_motor"]]["motor"].trajectory_start[0] - \
                       controller.motors[scan["x_motor"]]["motor"].xpad
    start_position_y = controller.motors[scan["x_motor"]]["motor"].trajectory_start[1] - \
                       controller.motors[scan["x_motor"]]["motor"].ypad
    scanInfo["start_position_x"] = start_position_x
    scanInfo["start_position_y"] = start_position_y
    controller.moveMotor(scan["x_motor"], start_position_x)
    controller.moveMotor(scan["y_motor"], start_position_y)
    controller.moveMotor(scan["z_motor"], zPos[0])
    time.sleep(1)

    # turn on position trigger
    trigger_axis = controller.motors[scan["x_motor"]]["motor"].trigger_axis
    trigger_position = controller.motors[scan["x_motor"]]["motor"].trajectory_trigger[trigger_axis - 1]
    #controller.motors[scan["x_motor"]]["motor"].setPositionTriggerOn(pos=trigger_position)

    for i in range(len(zPos)):
        controller.getMotorPositions()
        scanInfo["motorPositions"] = controller.allMotorPositions
        scanInfo["index"] = i * numLineDAQPoints
        scanInfo["lineIndex"] = i
        if queue.empty():
            scanInfo["direction"] = "forward"
            controller.moveMotor(scan["z_motor"], zPos[i])
            if not doFlyscanLine(controller, dataHandler, scan, scanInfo, 0.05):
                return terminateFlyscan(controller, dataHandler, scan, "x_motor", "Data acquisition failed for flyscan line!")
        else:
            queue.get()
            dataHandler.data.saveRegion(0)
            return terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan aborted.")
    # dataHandler.data.saveRegion(0)
    dataHandler.dataQueue.put('endOfRegion')
    terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan completed.")
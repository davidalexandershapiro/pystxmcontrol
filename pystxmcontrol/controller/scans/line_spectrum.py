from pystxmcontrol.controller.scans.scan_utils import *
from numpy import ones

def line_spectrum(scan, dataHandler, controller, queue):
    """
    Image scan in continuous flyscan mode.  Uses linear trajectory function on the controller
    :param scan:
    :return:
    """

    controller.moveMotor("Detector Y", 0)
    energies = dataHandler.data.energies
    controller.moveMotor("Energy", energies[0])
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    x = xPos[0]
    y = yPos[0] * ones(len(x))
    scanInfo = {"mode": "continuousLine"}
    scanInfo["scan"] = scan
    scanInfo["type"] = scan["scan_type"]
    scanInfo["include_return"] = True
    scanRegion = "Region1"  # only single region scans for line spectrum
    scanInfo["oversampling_factor"] = scan["oversampling_factor"]
    scanInfo["dwell"] = dataHandler.data.dwells[0]

    xStart, xStop = scan["scan_regions"][scanRegion]["xStart"], scan["scan_regions"][scanRegion]["xStop"]
    yStart, yStop = scan["scan_regions"][scanRegion]["yStart"], scan["scan_regions"][scanRegion]["yStop"]
    xPoints = scan["scan_regions"][scanRegion]["xPoints"]
    scanInfo["xPoints"] = xPoints
    scanInfo['totalSplit'] = None
    controller.motors[scan["x_motor"]]["motor"].include_return = scanInfo["include_return"]

    ##THIS ONLY WORKS FOR HORIZONTAL SCANS.  NEED TO GENERALIZE
    # set the PID and fly wait time according to the range
    xRange = xStop - xStart
    if xRange <= 5.:
        iGain = 150.
        waitTime = 0.005
    elif xRange > 15.:
        iGain = 50.
        waitTime = 0.1
    else:
        iGain = 150. - (xRange - 5.) * 10.
        waitTime = 0.005 + (xRange - 5.) * 0.01

    # for arbitrary line, xPoints and yPoints are the same
    controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_count = xPoints * scanInfo["oversampling_factor"]
    controller.motors[scan["x_motor"]]["motor"].trajectory_pixel_dwell = dataHandler.data.dwells[0] / scanInfo[
        "oversampling_factor"]
    controller.motors[scan["x_motor"]]["motor"].lineMode = "continuous"
    controller.motors[scan["x_motor"]]["motor"].trajectory_start = (xStart, yStart)
    controller.motors[scan["x_motor"]]["motor"].trajectory_stop = (xStop, yStop)
    ##during the scan, the driver takes care of padding for the acceleration distance automagically but for the
    # move to start command it needs to be added manually I guess
    controller.motors[scan["x_motor"]]["motor"].update_trajectory()

    #interp_counts comes in as (ne,nz,ny,nz) where ne=1 and ny=nx but we want it to be (ne,nz,1,nx) so slice and update it here
    #to keep higher level code general
    ne,ny,nx = dataHandler.data.interp_counts[0].shape
    numLineMotorPoints = controller.motors[scan["x_motor"]]["motor"].npositions #this configures the DAQ for one line
    numLineDAQPoints = controller.motors[scan["x_motor"]]["motor"].npositions * scan["oversampling_factor"]
    scanInfo['numMotorPoints'] = numLineMotorPoints  #total number of motor points configures the full data structrure
    scanInfo['numDAQPoints'] = numLineDAQPoints
    dataHandler.data.updateArrays(0, scanInfo)
    controller.daq["default"].config(scanInfo["dwell"] / scan["oversampling_factor"], count=1, \
                                            samples=numLineDAQPoints, trigger="EXT")

    start_position_x = controller.motors[scan["x_motor"]]["motor"].trajectory_start[0] - \
                       controller.motors[scan["x_motor"]]["motor"].xpad
    start_position_y = controller.motors[scan["x_motor"]]["motor"].trajectory_start[1] - \
                       controller.motors[scan["x_motor"]]["motor"].ypad
    scanInfo["start_position_x"] = start_position_x
    scanInfo["start_position_y"] = start_position_y
    # move to start positions
    controller.moveMotor(scan["x_motor"], scanInfo["start_position_x"])
    controller.moveMotor(scan["y_motor"], scanInfo["start_position_y"])
    controller.moveMotor(scan["energy_motor"], energies[0])

    # turn on position trigger
    trigger_axis = controller.motors[scan["x_motor"]]["motor"].trigger_axis
    trigger_position = controller.motors[scan["x_motor"]]["motor"].trajectory_trigger[trigger_axis - 1]
    #controller.motors[scan["x_motor"]]["motor"].setPositionTriggerOn(pos=trigger_position)

    energyIndex = 0
    for energy in energies:
        ##scanInfo is what gets passed with each data transmission
        scanInfo["energy"] = energy
        scanInfo["energyIndex"] = energyIndex
        scanInfo["dwell"] = dataHandler.data.dwells[energyIndex]
        controller.moveMotor("Energy", energy)
        controller.getMotorPositions()
        dataHandler.data.motorPositions[0] = controller.allMotorPositions
        scanInfo["motorPositions"] = controller.allMotorPositions
        scanInfo["scanRegion"] = scanRegion
        scanInfo["index"] = 0
        scanInfo["zIndex"] = 0
        scanInfo["lineIndex"] = 0
        scanInfo["xVal"] = x
        scanInfo["yVal"] = y
        if queue.empty():
            while controller.pause:
                if not (queue.empty()):
                    queue.get()
                    dataHandler.dataQueue.put('endOfScan')
                    print("Terminating grid scan")
                    return False
                time.sleep(0.1)
            scanInfo["direction"] = "forward"

            if not doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime):
                return terminateFlyscan(controller, dataHandler, scan, "x_motor", "Data acquisition failed for flyscan line!")
        else:
            queue.get()
            dataHandler.data.saveRegion(0)
            return terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan aborted.")
        # dataHandler.data.saveRegion(0)
        dataHandler.dataQueue.put('endOfRegion')
        energyIndex += 1
    terminateFlyscan(controller, dataHandler, scan, "x_motor", "Flyscan completed.")
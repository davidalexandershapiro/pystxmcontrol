from pystxmcontrol.controller.scans.scan_utils import *
from pystxmcontrol.utils.writeNX import stxm
import numpy as np
import time, datetime
import asyncio, os

# Define this parameter if you're setting the sample angle to something
SAMPLE_ANGLE = 45

# All dated notes were modifications made by Dayne and Damian

def insertSTXMDetector(controller):
    controller.moveMotor("Detector Y", 0)
    #time.sleep(10)

def retractSTXMDetector(controller):
    controller.moveMotor("Detector Y", -6500)
    #time.sleep(10)

def getLoopMotorPositions(scan):
    r = scan["outerLoop"]["range"]
    center = scan["outerLoop"]["center"]
    motor = scan["outerLoop"]["motor"]
    points = scan["outerLoop"]["points"]
    start = center - r / 2
    stop = center + r / 2
    return np.linspace(start,stop,points)

async def pointLoopSquareGrid(scan, scanInfo, positionList, dataHandler, controller, queue, shutter=True,scanRegion="Region1"):

    xPos, yPos, zPos = positionList
    if shutter == True:
        n_repeats = scanInfo["n_repeats"]
    else:
        n_repeats = 1
    if scan["doubleExposure"]:
        dwell1 = round(scanInfo["dwell"] * 10.)
        dwell2 = round(scanInfo["dwell"])
    else:
        dwell1 = round(scanInfo["dwell"])
        dwell2 = 0
    controller.daq["default"].setGateDwell(dwell1, 0)
    if shutter:
        controller.daq["default"].gate.mode = "auto"
    else:
        controller.daq["default"].gate.mode = "close"

    ## NOTE DAYNE EDIT 20251014: I'm implementing some ZOnePlateZ motion correction for tilted samples
    # based on stuff in the 2025-05-21 logbook for reflection imaging

    ## Put angle correction setup code here. Calculate zPos
    ###########################################################
    #sample_tilt = np.deg2rad(46.11) # Convert degree to radian. You need to put your angle here.
    #y_initial = scan["scan_regions"][scanRegion]["yCenter"]#np.mean(yPos)
    #z_initial = -10744.4 # Hard coding the ZonePlateZ position #controller.motors['ZonePlateZ']['motor'].getPos()
    #zPos = (z_initial - (np.array(yPos) - y_initial) / np.tan(sample_tilt)).tolist()
    ###########################################################

    # END DAYNE EDIT

    frame_num = 0
    scanInfo["ccd_frame_num"] = frame_num
    for i in range(len(yPos)):
        if i % 50 == 0:  ##used to be every line, now looping through points so just do this periodically
            controller.getMotorPositions()
            dataHandler.data.motorPositions[0] = controller.allMotorPositions
        scanInfo["motorPositions"] = controller.allMotorPositions
        controller.moveMotor(scan["y_motor"], yPos[i])
        controller.moveMotor(scan["x_motor"], xPos[i])

        # NOTE DAYNE EDIT 20251014: The following line corrects ZonePlateZ motion for sample surface tilt angle

        #controller.moveMotor("ZonePlateZ", zPos[i])

        # END DAYNE EDIT

        xpts = scan["scan_regions"][scanRegion]["xPoints"]
        ypts = scan["scan_regions"][scanRegion]["yPoints"]

        scanInfo["index"] = i
        scanInfo["lineIndex"] = i // xpts
        scanInfo["columnIndex"] = i % xpts

        ##need to also be able to request measured positions
        scanInfo["xVal"], scanInfo["yVal"] = xPos[i], yPos[i] * np.ones(len(xPos))
        scanInfo['xPos'] = xPos[i]
        scanInfo['yPos'] = yPos[i]

        # NOTE DAYNE EDIT 20251014: Add scanInfo for ZonePlateZ

        #scanInfo['zPos'] = zPos[i]
        #print(f'SampleX: {xPos[i]}, SampleY: {yPos[i]}, ZonePlateZ: {zPos[i]}')

        # END DAYNE EDIT

        scanInfo['isDoubleExposure'] = scan['doubleExposure']


        if queue.empty():
            if scan["doubleExposure"]:
                scanInfo['dwell'] = dwell2
                controller.daq["ccd"].init()
                controller.daq["default"].setGateDwell(dwell2, 0)
                controller.daq["default"].autoGateOpen()
                time.sleep((dwell2 + 10.) / 1000.)
                await dataHandler.getPoint(scanInfo.copy())
                frame_num += 1
                scanInfo["ccd_frame_num"] = frame_num
                scanInfo['dwell'] = dwell1
                controller.daq["ccd"].init()
                controller.daq["default"].setGateDwell(dwell1, 0)
                controller.daq["default"].autoGateOpen()
                time.sleep((dwell1 + 10.) / 1000.)  ##shutter open dwell time
                if not await dataHandler.getPoint(scanInfo.copy()):
                    #queue.get(True)
                    # dataHandler.data.saveRegion(0)
                    print("Failed to receive a ccd frame.")
                    await dataHandler.dataQueue.put('endOfScan')
                    # self._logger.log("Terminating grid scan")
                    return False
                frame_num += 1
                scanInfo["ccd_frame_num"] = frame_num
            else:
                controller.daq["default"].setGateDwell(dwell1, 0)
                controller.daq["default"].autoGateOpen() #this opens the shutter and sends the trigger
                time.sleep((dwell1 + 10.) / 1000.)  ##shutter open dwell time
                #now get the data
                if not await dataHandler.getPoint(scanInfo.copy()):
                    #queue.get(True)
                    # dataHandler.data.saveRegion(0)
                    print("Failed to receive a ccd frame.")
                    await dataHandler.dataQueue.put('endOfScan')
                    # self._logger.log("Terminating grid scan")
                    return False
                frame_num += 1
                scanInfo["ccd_frame_num"] = frame_num
        else:
            await queue.get()
            # dataHandler.data.saveRegion(0)
            await dataHandler.dataQueue.put('endOfScan')
            #self._logger.log("Terminating grid scan")
            return False
    return True

async def derived_ptychography_image(scan, dataHandler, controller, queue):
    """
    Ptychography image scan
    :param scan:
    :return:
    """

    await scan["synch_event"].wait()
    scan["randomize"] = True
    energies = dataHandler.data.energies["default"]
    xPos, yPos, zPos = dataHandler.data.xPos, dataHandler.data.yPos, dataHandler.data.zPos
    scanInfo = {"mode": "ptychographyGrid"}
    scanInfo["type"] = scan["scan_type"]
    scanInfo["scan"] = scan
    energyIndex = 0
    nScanRegions = len(xPos)
    scanID = dataHandler.ptychoDir
    scanInfo["energyIndex"] = energyIndex
    scanInfo["dwell"] = dataHandler.data.dwells[energyIndex]
    scanInfo["doubleExposure"] = scan["doubleExposure"]
    scanInfo["n_repeats"] = scan["n_repeats"]
    scanInfo["oversampling_factor"] = 1
    scanInfo['totalSplit'] = None
    scanInfo['retract'] = scan['retract']
    scanInfo['daq list'] = scan['daq list']
    scanInfo["rawData"] = {}
    for daq in scanInfo["daq list"]:
        scanInfo["rawData"][daq]={"meta":controller.daq[daq].meta,"data": None}
        if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(scanInfo["rawData"][daq]["meta"]["x"])
        else:
            scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)
        if controller.daq[daq].meta["oversampling_factor"] > 1:
            scanInfo["rawData"][daq]["interpolate"] = True
        else:
            scanInfo["rawData"][daq]["interpolate"] = False

    print("starting ptychography scan: ", scanID)

    #EDIT 20251013: We're getting stuck at the if statement below. I think the diode is getting stuck?..
    #               The if statement will be temporarily commented out
    if scanInfo['retract']:
        retractSTXMDetector(controller)

    print('Done with retracting STXM diode')

    if scan["doubleExposure"]:
        dwell1 = scanInfo["dwell"] * 10.
        dwell2 = scanInfo["dwell"]
    else:
        dwell1 = scanInfo["dwell"]
        dwell2 = 0

    print('Done with double exposure statement')

    #numMotorPoints should be the total number of motor position measurements expected
    #numDAQPoints should be equal to xPoints * oversampling
    numLineMotorPoints = len(xPos) #this configures the DAQ for one line
    numLineDAQPoints = numLineMotorPoints * scan["oversampling_factor"]
    scanInfo['numMotorPoints'] = numLineMotorPoints * len(yPos) #total number of motor points configures the full data structrure
    scanInfo['numDAQPoints'] = scanInfo['numMotorPoints'] * scan["oversampling_factor"]
    controller.config_daqs(dwell = [dwell1 + 10.,dwell2 + 10.], count = 1, samples = 1, trigger = "BUS")
    # controller.daq["ccd"].start()
    # controller.daq["ccd"].config(dwell1 + 10., dwell2 + 10., scan["doubleExposure"])

    if "outerLoop" in scan.keys():
        loopMotorPos = getLoopMotorPositions(scan)
    print('Done with get loop motor positions')

    currentZonePlateZ = controller.motors['ZonePlateZ']['motor'].getPos()

    for energy in energies:
        ##scanInfo is what gets passed with each data transmission
        scanInfo["energy"] = energy
        scanInfo['energyIndex'] = energyIndex
        for j in range(nScanRegions):
            if energy == energies[0]:
                #this needs to have info per daq, but it doesn't currently
                dataHandler.data.updateArrays(j, scanInfo)
            scanRegion = "Region" + str(j + 1)
            if "outerLoop" in scan.keys():
                print("Moving %s motor to %.4f" % (scan["outerLoop"]["motor"], loopMotorPos[j]))
                controller.moveMotor(scan["outerLoop"]["motor"], loopMotorPos[j])
            scan["file_name"] = dataHandler.currentScanID.replace('.stxm', '_ccdframes_' + str(energyIndex) + '_' + str(
                j) + '.stxm')
            dataHandler.ptychodata = stxm(scan)
            dataHandler.ptychodata.start_time = str(datetime.datetime.now())
            controller.getMotorPositions()
            dataHandler.data.motorPositions[j] = controller.allMotorPositions  # all regions in one file
            dataHandler.ptychodata.motorPositions[
                0] = controller.allMotorPositions  # regions in separate files
            scanInfo["motorPositions"] = controller.allMotorPositions

            # move to focus without changing energy
            if len(energies) > 1:
                controller.moveMotor(scan["energy_motor"], energy)
                if not scanInfo['scan']['autofocus']:
                    if energy == energies[0]:
                        scanInfo['refocus_offset'] = currentZonePlateZ - controller.motors['ZonePlateZ'][
                            'motor'].calibratedPosition
                        print('calculated offset: {}'.format(scanInfo['refocus_offset']))

                    controller.moveMotor('ZonePlateZ',
                                              controller.motors['ZonePlateZ']['motor'].calibratedPosition +
                                              scanInfo['refocus_offset'])

            if scan["defocus"]:
                step = energies[0] / 700. * 15.
                print("Defocusing zone plate by %.4f microns" % step)
                controller.motors["ZonePlateZ"]["motor"].moveBy(step=step)
            scanMeta = {"header": dataHandler.currentScanID}
            for key in controller.main_config.keys():
                scanMeta[key] = controller.main_config[key]
            scanMeta["repetition"] = 1
            scanMeta["defocus"] = scan["defocus"]
            scanMeta["isDoubleExp"] = int(scan["doubleExposure"])
            scanMeta["pos_x"] = scan["scan_regions"][scanRegion]["xCenter"]
            scanMeta["pos_y"] = scan["scan_regions"][scanRegion]["yCenter"]
            scanMeta["step_size_x"] = scan["scan_regions"][scanRegion]["xStep"]
            scanMeta["step_size_y"] = scan["scan_regions"][scanRegion]["yStep"]
            scanMeta["num_pixels_x"] = scan["scan_regions"][scanRegion]["xPoints"]
            scanMeta["num_pixels_y"] = scan["scan_regions"][scanRegion]["yPoints"]
            scanMeta["background_pixels_x"] = 5
            scanMeta["background_pixels_y"] = 5
            scanMeta["dwell1"] = dwell1
            scanMeta["dwell2"] = dwell2
            scanMeta["energy"] = energy
            scanMeta["energyIndex"] = energyIndex  # ABE - I added this and the following line
            scanMeta["scanRegion"] = j
            scanMeta["dark_num_x"] = 5
            scanMeta["dark_num_y"] = 5
            scanMeta["exp_num_x"] = scanMeta["num_pixels_x"]
            scanMeta["exp_num_y"] = scanMeta["num_pixels_y"]
            scanMeta["exp_step_x"] = scanMeta["step_size_x"]
            scanMeta["exp_step_y"] = scanMeta["step_size_y"]
            scanMeta["double_exposure"] = bool(scanMeta["isDoubleExp"])
            scanMeta["exp_num_total"] = scanMeta["exp_num_x"] * scanMeta["exp_num_y"] * (
                        2 - int(not (scanMeta["double_exposure"])))
            xp, yp = np.meshgrid(xPos[j], yPos[j])
            xp, yp = xp.flatten(), yp.flatten()
            xStart,xStop = xp.min(),xp.max()
            yStart,yStop = yp.min(),yp.min()

            #first need to move the coarse motor to the correct position
            #this is annoying because it doesn't use the controllers moveMotor command.
            #this is done because we have to ensure it is the coarse motor that moves
            #but, first check for the correct coarseXY coordinates, it may not be needed if requested scan is within fine range
            #this function only moves the coarse motors if needed
            controller.motors[scan["x_motor"]]["motor"].move_coarse_to_fine_range(xStart,xStop)
            controller.motors[scan["y_motor"]]["motor"].move_coarse_to_fine_range(yStart,yStop)

            if scan["randomize"]:
                xp = xp + (np.random.rand(len(xp)) - 0.5) * scanMeta["step_size_x"] / 2.
                yp = yp + (np.random.rand(len(yp)) - 0.5) * scanMeta["step_size_y"] / 2.
            scanMeta["translations"] = [pos for pos in zip(yp, xp)]

            # NOTE Dayne EDIT 2025-02-11-1045: Define the ZonePlateZ values here
            #           2025-02-11-1310: The code is written within the comment block
            #           2025-02-11-1314: TODO: Consider how the ZonePlateZ tilt adjustment
            #                            needs to be further adjusted for spectromicroscopy
            #if abs(scanInfo['scan']['sampleAngle']) > 0.5:  # degrees
                #pass
            # Call calcTiltZPCorrection in scan_utils.py. This calculates the
            # ZonePlateZ tilt correction using the tilt angle stored in
            # scanInfo and the current SampleY and ZonePlateZ positions
            # (which is assumed to give the focus the user desires)

            # NOTE EDIT 20251014: Inserting the function for calcCorrectedZPTilt from scan_utils since the last
            #                     set of scan files we used dissappeared somewhere
            # Convert the sample angle to radian
            #sample_tilt = np.deg2rad(SAMPLE_ANGLE)

            # Grab the current ZonePlateZ and SampleY positions

            # Set the position to the center of the scan
            #y_initial = np.mean(yPos)
            # y_initial = controller.motors['SampleY']['motor'].getPos()
            #z_initial = controller.motors['ZonePlateZ']['motor'].getPos()

            # Calculate the tilt-corrected ZonePlateZ positions
            #zPos = z_initial - (np.array(yPos) - y_initial) / np.tan(sample_tilt)

            #zp = zPos.tolist()
            #print('zPos')
            #print(zp[0])
            #print(f"Length of zp: {len(zp)}")
            #print(f"Length of yp: {len(yp)}")
            # Run a test to make sure that zp has the correct positions
            #print('Printing corrected ZonePlateZ positions')
            #print(zp)
            #print('Ok nothing broke (yet)')
            ## END DAYNE EDIT

            scanMeta["n_repeats"] = scan["n_repeats"]
            #remove the asyncio.event so it can be serialized in the output file
            scan_copy = {k: v for k, v in scan.items() if k != "synch_event"}
            scanMeta["scan"] = scan_copy

            ##add ptychography metadata to main scanInfo for sending to Abe's processes
            # scanInfo["ptychoMeta"] = scanMeta # ABE - I remove this, and only send it with the start event
            # I also moved the start event to here, so that we can have the full scan metadata dictionary to send
            # dataHandler.zmq_start_event(scan, metadata=scanMeta)
            dataHandler.zmq_send({'event': 'start', 'data': scan, 'metadata': scanMeta})

            time.sleep(0.1)
            scanInfo["scanRegion"] = scanRegion
            xp_dark = np.linspace(xp.min(), xp.max(), 5)
            yp_dark = np.linspace(yp.min(), yp.max(), 5)

            # 20251013: THIS IS A DAYNE EDIT; REMOVE AFTER REFLECTION BEAM TIME
            #zp_dark = np.ones((5,)) * controller.motors['ZonePlateZ']['motor'].getPos()
            # END DAYNE EDIT

            scanInfo["ccd_mode"] = "dark"
            print("acquiring background")
            # NOTE 2025-02-11-1116: Replace zPos[j] with zp. The commented code below was the original if statement
            if await pointLoopSquareGrid(scan, scanInfo.copy(), (xp_dark, yp_dark, zPos[j]), dataHandler, controller, queue, shutter=False,scanRegion=scanRegion):
                await dataHandler.dataQueue.put('endOfRegion')
            else:
                dataHandler.zmq_send({'event': 'abort', 'data': None})
                if scanInfo['retract']:
                    insertSTXMDetector(controller)
                if scan["defocus"]:
                    controller.motors["ZonePlateZ"]["motor"].moveBy(step=-step)
                return
            scanInfo["ccd_mode"] = "exp"
            print("acquiring data")
            # NOTE 2025-02-11-1116: Replace zPos[j] with zp. The commented code below was the original if statement
            if await pointLoopSquareGrid(scan, scanInfo.copy(), (xp, yp, zPos[j]), dataHandler, controller, queue, shutter=True,scanRegion=scanRegion):

                #there is a race condition happening because apparently this is not thread safe
                #I need to wait after sending the 'endOfRegion' flag to ensure data makes it through
                await dataHandler.dataQueue.put('endOfRegion')
                while not dataHandler.dataQueue.empty():
                    await asyncio.sleep(0.1)
            else:
                print("Aborting scan...")
                dataHandler.zmq_send({'event': 'abort', 'data': None})
                if scanInfo['retract']:
                    insertSTXMDetector(controller)
                if scan["defocus"]:
                    controller.motors["ZonePlateZ"]["motor"].moveBy(step=-step)
                return
            while not dataHandler.regionComplete:
                print("Waiting...")
                time.sleep(1)
                # need to wait here until all the data has gone through the pipe
                pass
            print("Scan region complete, saving data...")
            dataHandler.ptychodata.addDict(scanMeta, "metadata")  # stuff needed by the preprocessor
            dataHandler.ptychodata.saveRegion(0)
            dataHandler.ptychodata.close()
            dataHandler.zmq_send_string(
                {'event': 'ccd_data', 'data': {"identifier": os.path.basename(dataHandler.ptychodata.file_name)}})
            dataHandler.data.end_time = str(datetime.datetime.now())
            dataHandler.zmq_send({'event': 'stop', 'data': None})
            print("Done!")
        energyIndex += 1
    await dataHandler.dataQueue.put('endOfScan')
    if scanInfo['retract']:
        insertSTXMDetector(controller)
    if scan["defocus"]:
        controller.motors["ZonePlateZ"]["motor"].moveBy(step=-step)
    print("Finished Grid Scan")
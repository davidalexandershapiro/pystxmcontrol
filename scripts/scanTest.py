from caproto.threading.client import Context
import numpy as np
import time, datetime, os, pickle
from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR
from pystxmcontrol.drivers.nptMotor import nptMotor
from pystxmcontrol.drivers.nptController import nptController
from caproto.sync.client import read

########################################################################
###SCAN PARAMETERS
waitTime = 10  # time to wait after moving the motor (1-10 ms), allows stabilization and CCD readout
dwellTime1 = 10  # detector integration time 1 (1-100 ms)
dwellTime2 = 100  # detector integration time 2 (1-100 ms)
c = 0., 0.  # motor position for center of the scan
r = 2., 2.  # range of the scan in microns
stepSize = 0.1, 0.1  # step size in y,x
doubleExposure = False
repetition = 1  # not implemented, frames per scan point
ptychoscan = False #make True to connect to cincontrol and save the CCD frames.  Otherwise, CCD is just triggered without saving
flyscan = True #doing this requires a special trigger cable connection.  doesn't work otherwise

########################################################################
###SYSTEM SETUP PARAMETERS
baseDir = '/cosmic-dtn/groups/cosmic/Data'  # base directory for saving
#baseDir = '/home/david/scratch/pystxmcontrolData'
filePrefix = 'NS'  # beamline name prefix for data files
cameraAddress = '131.243.73.179'  # hostname for the computer running the camera server, ptycho1
cameraPort = 8880  # port for the camera server connection

if ptychoscan:
    CCDREADOUTTIME = 20.
else:
    CCDREADOUTTIME = 0.

def getScanName():
    """
    Just looks in the current days directory and finds the latest file
    number.  Returns today's directory and the next scan name.
    """
    now = datetime.datetime.now()
    yr = str(now.year)
    mo = str(now.month)

    if len(mo) == 1: mo = '0' + mo
    dy = str(now.day)
    if len(dy) == 1: dy = '0' + dy
    dayStr = yr[-2:] + mo + dy
    if not os.path.exists(os.path.join(baseDir, yr)):
        os.mkdir(os.path.join(baseDir, yr))
    if not os.path.exists(os.path.join(baseDir, yr, mo)):
        os.mkdir(os.path.join(baseDir, yr, mo))
    if not os.path.exists(os.path.join(baseDir, yr, mo, dayStr)):
        os.mkdir(os.path.join(baseDir, yr, mo, dayStr))
    scanDir = os.path.join(baseDir, yr, mo, dayStr)
    scanList = np.sort([x for x in os.listdir(scanDir) if filePrefix in x])
    if len(scanList) == 0:
        return scanDir, filePrefix + "_" + dayStr + "000.hdr"
    else:
        lastScan = int(scanList[-1].split(filePrefix + '_')[1][6:9])
        if (lastScan + 1) < 10:
            nextScan = "00" + str(lastScan + 1)
        elif (lastScan + 1) < 100:
            nextScan = "0" + str(lastScan + 1)
        elif (lastScan + 1) < 1000:
            nextScan = str(lastScan + 1)
        return scanDir, filePrefix + "_" + dayStr + nextScan + '.hdr'

def generateDataDirs(scanType="ptychography"):
    """
    Generates the directories for saving ptychography data
    Saves the metadata into hdr and json files
    """
    scanDir, scanName = getScanName()
    if scanType == "ptychography":
        ptychoDir = scanName.strip('NS_').strip('.hdr')
        os.mkdir(os.path.join(scanDir, ptychoDir))
        darkDir = os.path.join(scanDir, ptychoDir, '001')
        expDir = os.path.join(scanDir, ptychoDir, '002')
        os.mkdir(darkDir)
        os.mkdir(expDir)
        hdrFile = open(os.path.join(scanDir, scanName), 'w')
        hdrFile.write("This is just a test file...")
        hdrFile.close()
    return darkDir, expDir, os.path.join(scanDir, scanName)

def getMessage(sock):
    """
    Gets the message back from cincontrol on the socket
    """
    return sock.recv(4096).decode().strip()

def sendMetaDataAsStr(sock, scanInfo):
    """
    The first command sends all meta data as a long string.  This generates and sends that string.
    """
    scanInfoStr = 'sendScanInfo '
    scanInfoStr += scanInfo['header']
    scanInfoStr += ', repetition %i' %scanInfo['repetition']
    scanInfoStr += ', isDoubleExp %i' %scanInfo['isDoubleExp']
    scanInfoStr += ', pos_x %i' %scanInfo['pos_x']
    scanInfoStr += ', pos_y %i' %scanInfo['pos_y']
    scanInfoStr += ', step_size_x %i' %scanInfo['step_size_x']
    scanInfoStr += ', step_size_y %i' %scanInfo['step_size_y']
    scanInfoStr += ', num_pixels_x %i' %scanInfo['num_pixels_x']
    scanInfoStr += ', num_pixels_y %i' %scanInfo['num_pixels_y']
    scanInfoStr += ', background_pixels_x %i' %scanInfo['background_pixels_x']
    scanInfoStr += ', background_pixels_y %i' %scanInfo['background_pixels_y']
    scanInfoStr += ', dwell1 %i' %scanInfo['dwell1']
    scanInfoStr += ', dwell2 %i' %scanInfo['dwell2']
    scanInfoStr += ', energy %i\n\r' %scanInfo['energy']
    sock.sendall(scanInfoStr.encode('utf-8'))
    print(getMessage(sock))

def configureScan(scanInfo, mode = "dark"):
    """
    This communicates the meta-data to cincontrol as separate commands.  Order is important.
    """
    if mode == "dark":
        sock.sendall(b"setCapturePath %s\n\r" %scanInfo["darkDir"].encode('utf-8'))
    elif mode == "exp":
        sock.sendall(b"setCapturePath %s\n\r" %scanInfo["expDir"].encode('utf-8'))
    print(getMessage(sock))
    sock.sendall(b"startCapture\n\r")
    print(getMessage(sock))
    sock.sendall(b"setExp %i\n\r" %scanInfo["dwell1"])
    print(getMessage(sock))
    sock.sendall(b"setExp2 %i\n\r" %scanInfo["dwell2"])
    print(getMessage(sock))
    sock.sendall(b"setDoubleExpCount %i\n\r" %scanInfo["isDoubleExp"])
    print(getMessage(sock))
    sock.sendall(b"resetCounter\n\r")
    print(getMessage(sock))

def serpentineScan(pos, counter, scanInfo):
    """
    Launches a serpentine grid scan from a set of xPositions and yPositions.
    Assumes they are on a rectangular grid
    Input: pos = (xPositionList,yPositionList)
    """
    m = 0
    xPos,yPos = pos
    for j in range(yPos.size):
        yP.write(yPos[j])
        for i in range(xPos.size):
            ##this index swapping is to make it a serpentine scan
            if j % 2 != 0:
                k = -1 - i
            else:
                k = i
            xP.write(xPos[k])
            if scanInfo["isDoubleExp"]:
                ##these repeated writes are BAD, need a better/faster way
                counter.read()  # reads the counter and sends a corresponding trigger to the CCD/shutter
                dt.write(scanInfo[dwell2])
                counter.read()
                dt.write(scanInfo[dwell1])
            else:
                counter.read()

def flyScan(pos, scanInfo):
    xPos,yPos = pos
    lcx.write(scanInfo["pos_x"], wait=False)  # write line center X position
    lps.write(scanInfo["step_size_x"], wait=False)  # write line pixel size
    lpc.write(scanInfo["num_pixels_x"], wait=False)  # write line pixel count
    lpdt.write(scanInfo["dwell1"] + CCDREADOUTTIME, wait=False)  # write line pixel dwell time, add CCD readout
    ldt.write(0.1, wait=False)  # write line dwell time, wait before line executes
    ilc.write(1, wait=False)  # write image line count. # of lines, just 1 for linescan
    lm.write("raster") #write the linescan mode to the npoint.
    for y in yPos:
        #yP.write(y)
        print("Line Y position: %.2f" %y)
        lcy.write(y)
        print(rlx.read())  # this executes the line motion and returns the array of counter data.
        #print(read('ES7012:npoint:rasterLineX'))
        #mlx.write('raster')

##set up scan positions for background and diffraction region
nSteps = int(r[0] / stepSize[0]) + 1, int(r[1] / stepSize[1]) + 1
xPositions = np.linspace(c[1] - r[1] / 2, c[1] + r[1] / 2, nSteps[1])
yPositions = np.linspace(c[0] - r[0] / 2, c[0] + r[0] / 2, nSteps[0])
xPositionsBKG = np.linspace(c[1] - r[1] / 2, c[1] + r[1] / 2, 5)
yPositionsBKG = np.linspace(c[0] - r[0] / 2, c[0] + r[0] / 2, 5)

#get the caproto context and PVs
ctx = Context()
if flyscan:
    # startup the epics interface and write the initial parameters
    dt, wtx, wty, xP, yP, ct = ctx.get_pvs("ES7012:npoint:dwellTime", "ES7012:npoint:waitTimeXMotor", "ES7012:npoint:waitTimeYMotor",\
                                     "ES7012:npoint:moveToXPosition", "ES7012:npoint:moveToYPosition",
                                     "ES7012:npoint:count")
    lcx, lcy, lps, lpc, lpdt, ldt, pot, ilc, yP, xP, rlx, lm = ctx.get_pvs("ES7012:npoint:lineCenterXPosition",
                                                                           "ES7012:npoint:lineCenterYPosition",
                                                                           "ES7012:npoint:linePixelSize",
                                                                           "ES7012:npoint:linePixelCount",
                                                                           "ES7012:npoint:linePixelDwellTime",
                                                                           "ES7012:npoint:lineDwellTime",
                                                                           "ES7012:npoint:pulseOffsetTime",
                                                                           "ES7012:npoint:imageLineCount",
                                                                           "ES7012:npoint:moveToYPosition",
                                                                           "ES7012:npoint:moveToXPosition",
                                                                           "ES7012:npoint:rasterLineX",
                                                                           "ES7012:npoint:lineMode")
    # lcx, lcy, lps, lpc, lpdt, ldt, pot, ilc, yP, xP, mlx = ctx.get_pvs("ES7012:npoint:lineCenterXPosition",
    #                                     "ES7012:npoint:lineCenterYPosition","ES7012:npoint:linePixelSize","ES7012:npoint:linePixelCount",\
    #                                     "ES7012:npoint:linePixelDwellTime","ES7012:npoint:lineDwellTime",\
    #                                     "ES7012:npoint:pulseOffsetTime","ES7012:npoint:imageLineCount", \
    #                                     "ES7012:npoint:moveToYPosition","ES7012:npoint:moveToXPosition", \
    #                                     "ES7012:npoint:moveLineX")
    xP.write([xPositions[0]], wait=False) #X start position
    yP.write([yPositions[0]], wait=False) #Y start position
else:
    # startup the epics interface and write the initial parameters
    dt, wtx, wty, xP, yP, ct = ctx.get_pvs("ES7012:npoint:dwellTime", "ES7012:npoint:waitTimeXMotor", "ES7012:npoint:waitTimeYMotor",\
                                     "ES7012:npoint:moveToXPosition", "ES7012:npoint:moveToYPosition",
                                     "ES7012:npoint:count")
    dt.write([dwellTime1], wait=False)  # just single exposure.  how to manage double exposure yet.  Repeated writes make overhead
    wtx.write([waitTime], wait=False) #for X motor
    wty.write([waitTime], wait=False) #same for Y motor
    xP.write([xPositions[0]], wait=False) #X start position
    yP.write([yPositions[0]], wait=False) #Y start position

# take a breather because the motors just moved a big distance
time.sleep(1)

#get the current scan name and generate data directories
darkDir, expDir, scanFile = generateDataDirs()

#generate the metadata dict
#this needs to be sent to cincontrol as a single string
scanInfo = {"header": scanFile}
scanInfo["repetition"] = repetition
scanInfo["isDoubleExp"] = int(doubleExposure)
scanInfo["pos_x"] = c[0]
scanInfo["pos_y"] = c[1]
scanInfo["step_size_x"] = stepSize[1]
scanInfo["step_size_y"] = stepSize[0]
scanInfo["num_pixels_x"] = nSteps[1]
scanInfo["num_pixels_y"] = nSteps[0]
scanInfo["background_pixels_x"] = 5
scanInfo["background_pixels_y"] = 5
scanInfo["dwell1"] = dwellTime1
scanInfo["dwell2"] = dwellTime2
scanInfo["darkDir"] = darkDir
scanInfo["expDir"] = expDir
scanInfo["energy"] = 500

#connect to cincontrol and send necessary commands
if ptychoscan:
    sock = socket(AF_INET, SOCK_STREAM)
    sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    sock.connect((cameraAddress, cameraPort))
    sendMetaDataAsStr(sock, scanInfo)
    configureScan(scanInfo, mode = "dark")

    #first launch the background scan
    if flyscan:
        flyScan((xPositionsBKG,yPositionsBKG), scanInfo)
    else:
        serpentineScan((xPositionsBKG,yPositionsBKG), ct, scanInfo)

#move back to first position for data scan
xP.write([xPositions[0]],wait=False)
yP.write([yPositions[0]],wait=False)

#take a breather because the motors just moved a big distance
time.sleep(1)

#configure and launch
if ptychoscan:
    configureScan(scanInfo, mode = "exp")
if flyscan:
    t0 = time.time()
    flyScan((xPositions,yPositions), scanInfo)
    print("Overhead per point: %.6f seconds" %((time.time() - t0)/(len(xPositions)*len(yPositions))-dwellTime1/1000.))
else:
    serpentineScan((xPositions,yPositions), ct, scanInfo)

#some delay is needed here I think to empty the buffer.  Not sure why
time.sleep(2)

if ptychoscan:
    sock.sendall(b"stopCapture\n\r")
    print(getMessage(sock))
    sock.close()

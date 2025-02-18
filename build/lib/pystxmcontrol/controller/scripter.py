from pystxm_core.io.writeNX import stxm
import matplotlib.pyplot as plt
import time, sys, zmq, os, json, traceback, datetime
import numpy as np
from matplotlib.widgets import Button


BASEPATH = sys.prefix
MAINCONFIGFILE = os.path.join(BASEPATH,'pystxmcontrol_cfg/main.json')
config = json.loads(open(MAINCONFIGFILE).read())
SCANCONFIGFILE = os.path.join(BASEPATH,'pystxmcontrol_cfg/scans.json')
scans = json.loads(open(SCANCONFIGFILE).read())["scans"]
context = zmq.Context()
sock = context.socket(zmq.REQ)
sock.connect("tcp://%s:%s" %(config["server"]["host"],config["server"]["command_port"]))

def moveMotor(axis=None, pos=None):
    if axis not in list(MOTORS.keys()):
        print("Bad motor name. Available motors are:")
        for m in list(MOTORS.keys()):
            print(m)
        return
    message = {"command": "moveMotor", "axis": axis, "pos": pos}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if response is not None: return response["status"]
    else: return False

def get_config():
    message = {"command": "get_config"}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if response is not None: return response["data"]
    else: return False

def read_daq(daq,dwell, shutter = True):
    message = {"command":"getData","daq":daq,"dwell":dwell, "shutter":shutter}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if response is not None: return response["data"]
    else: return False

def stop_monitor():
    message = {"command": "stop_monitor"}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if response is not None: return response["status"]
    else: return False

def start_monitor():
    message = {"command": "start_monitor"}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if response is not None: return response["status"]
    else: return False

def ptychography_scan(meta):
    xstart = meta['xcenter'] - meta['xrange'] / 2.
    xstop = meta['xcenter'] + meta['xrange'] / 2.
    xstep = np.round((xstop - xstart) / (meta["xpoints"] - 1), 3)
    x_range = xstop - xstart
    xcenter = x_range / 2. + xstart
    ystart = meta['ycenter'] - meta['yrange'] / 2.
    ystop = meta['ycenter'] + meta['yrange'] / 2.
    ystep = np.round((ystop - ystart) / (meta["ypoints"] - 1), 3)
    y_range = ystop - ystart
    ycenter = y_range / 2. + ystart
    energyStep = (meta["energyStop"] - meta["energyStart"]) / meta["energyPoints"]
    scan = {"type": "Ptychography Image", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nxFileVersion": meta["nxFileVersion"],
            "sample": meta["Sample"],
            "x": "SampleX",
            "y": "SampleY",
            "energy": "Energy",
            "doubleExposure": meta["doubleExposure"],
            "n_repeats": 1,
            "defocus": meta["defocus"],
            "refocus": meta["refocus"],
            "oversampling_factor": 1,
            "mode": "ptychographyGrid",
            "spiral": False,
            "retract": meta["retract"],
            "tiled": False,
            "driver": scans["Ptychography Image"]["driver"], #"ptychography_image",
            "scanRegions": {"Region1": {"xStart": xstart,
                                        "xStop": xstop,
                                        "xPoints": meta['xpoints'],
                                        "xStep": xstep,
                                        "xRange": x_range,
                                        "xCenter": xcenter,
                                        "yStart": ystart,
                                        "yStop": ystop,
                                        "yPoints": meta['ypoints'],
                                        "yStep": ystep,
                                        "yRange": y_range,
                                        "yCenter": ycenter,
                                        "zStart": 0,
                                        "zStop": 0,
                                        "zPoints": 0}},
            "energyRegions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                "start": meta["energyStart"],
                                                "stop": meta["energyStop"],
                                                "step": energyStep,
                                                "nEnergies": meta["energyPoints"]}}
            }
    if "energyList" in meta.keys():
        scan["energy_list"] = meta["energyList"]
        scan["dwell"] = meta["dwell"]
    message = {"command": "scan", "scan": scan}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if not response["status"]:
        return False
    status = False
    while not status:
        time.sleep(1)
        sock.send_pyobj({"command":"getStatus"})
        response = sock.recv_pyobj()
        status = response["status"]
    return status

def stxm_scan(meta):
    # s = connect(ADDRESS, PORT)
    xstart = meta['xcenter'] - meta['xrange'] / 2.
    xstop = meta['xcenter'] + meta['xrange'] / 2.
    xstep = np.round((xstop - xstart) / (meta["xpoints"] - 1), 3)
    x_range = xstop - xstart
    xcenter = x_range / 2. + xstart
    ystart = meta['ycenter'] - meta['yrange'] / 2.
    ystop = meta['ycenter'] + meta['yrange'] / 2.
    ystep = np.round((ystop - ystart) / (meta["ypoints"] - 1), 3)
    y_range = ystop - ystart
    ycenter = y_range / 2. + ystart
    energyStep = (meta["energyStop"] - meta["energyStart"]) / meta["energyPoints"]
    scan = {"type": "Image", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nxFileVersion": meta["nxFileVersion"],
            "sample": meta["Sample"],
            "x": "SampleX",
            "y": "SampleY",
            "energy": "Energy",
            "doubleExposure": False,
            "n_repeats": 1,
            "defocus": False,
            "refocus": meta["refocus"],
            "oversampling_factor": 3,
            "mode": "continuousLine",
            "spiral": meta["spiral"],
            "tiled": False,
            "scanRegions": {"Region1": {"xStart": xstart,
                                        "xStop": xstop,
                                        "xPoints": meta['xpoints'],
                                        "xStep": xstep,
                                        "xRange": x_range,
                                        "xCenter": xcenter,
                                        "yStart": ystart,
                                        "yStop": ystop,
                                        "yPoints": meta['ypoints'],
                                        "yStep": ystep,
                                        "yRange": y_range,
                                        "yCenter": ycenter,
                                        "zStart": 0,
                                        "zStop": 0,
                                        "zPoints": 0}},
            "energyRegions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                "start": meta["energyStart"],
                                                "stop": meta["energyStop"],
                                                "step": energyStep,
                                                "nEnergies": meta["energyPoints"]}}
            }
    if "energyList" in meta.keys():
        scan["energy_list"] = meta["energyList"]
        scan["dwell"] = meta["dwell"]
    if meta["spiral"]:
        scan["driver"] = scans["Spiral Image"]["driver"] #"spiral_image"
        scan["type"] = 'Spiral Image'
    else:
        scan["driver"] = scans["Image"]["driver"] #"line_image"
    message = {"command": "scan", "scan": scan}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if not response["status"]:
        return False
    status = False
    while not status:
        time.sleep(1)
        sock.send_pyobj({"command":"getStatus"})
        response = sock.recv_pyobj()
        status = response["status"]
    return status

def multi_region_ptychography_scan(meta, scanRegList):
    energyStep = (meta["energyStop"] - meta["energyStart"]) / meta["energyPoints"]
    scan = {"type": "Ptychography Image", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nxFileVersion": meta["nxFileVersion"],
            "sample": meta["Sample"],
            "x": "SampleX",
            "y": "SampleY",
            "energy": "Energy",
            "doubleExposure": meta["doubleExposure"],
            "n_repeats": 1,
            "defocus": meta["defocus"],
            "refocus": meta["refocus"],
            "oversampling_factor": 1,
            "mode": "ptychographyGrid",
            "spiral": meta["spiral"],
            "retract": meta["retract"],
            "energyRegions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                "start": meta["energyStart"],
                                                "stop": meta["energyStop"],
                                                "step": energyStep,
                                                "nEnergies": meta["energyPoints"]}}
            }
    scan["scanRegions"] = {}
    i = 1
    for region in scanRegList:
        xstart, xstop, ystart, ystop = region
        x_range = xstop - xstart
        xcenter = xstart + x_range / 2.
        xpoints = int(x_range / meta["xstep"])
        y_range = ystop - ystart
        ycenter = ystart + y_range / 2.
        ypoints = int(y_range / meta["ystep"])
        scan["scanRegions"]["Region" + str(i)] = {"xStart": xstart,
                                    "xStop": xstop,
                                    "xPoints": xpoints,
                                    "xStep": meta["xstep"],
                                    "xRange": x_range,
                                    "xCenter": xcenter,
                                    "yStart": ystart,
                                    "yStop": ystop,
                                    "yPoints": ypoints,
                                    "yStep": meta["ystep"],
                                    "yRange": y_range,
                                    "yCenter": ycenter,
                                    "zStart": 0,
                                    "zStop": 0,
                                    "zPoints": 0}
        i += 1
    message = {"command": "doScan", "scan": scan}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if not response["status"]:
        return False
    status = False
    while not status:
        time.sleep(1)
        sock.send_pyobj({"command":"getStatus"})
        response = sock.recv_pyobj()
        status = response["status"]
    return status

def multi_region_stxm_scan(meta, scanRegList):
    # s = connect(ADDRESS, PORT)
    energyStep = (meta["energyStop"] - meta["energyStart"]) / meta["energyPoints"]
    scan = {"type": meta["type"], "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nxFileVersion": meta["nxFileVersion"],
            "sample": meta["Sample"],
            "x": "SampleX",
            "y": "SampleY",
            "energy": "Energy",
            "doubleExposure": False,
            "n_repeats": 1,
            "defocus": False,
            "refocus": meta["refocus"],
            "oversampling_factor": 1,
            "mode": meta["mode"],
            "spiral": meta["spiral"],
            "energyRegions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                "start": meta["energyStart"],
                                                "stop": meta["energyStop"],
                                                "step": energyStep,
                                                "nEnergies": meta["energyPoints"]}}
            }
    scan["scanRegions"] = {}
    i = 1
    for region in scanRegList:
        xstart, xstop, ystart, ystop = region
        x_range = xstop - xstart
        xcenter = xstart + x_range / 2.
        xpoints = int(x_range / meta["xstep"])
        y_range = ystop - ystart
        ycenter = ystart + y_range / 2.
        ypoints = int(y_range / meta["ystep"])
        scan["scanRegions"]["Region" + str(i)] = {"xStart": xstart,
                                    "xStop": xstop,
                                    "xPoints": xpoints,
                                    "xStep": meta["xstep"],
                                    "xRange": x_range,
                                    "xCenter": xcenter,
                                    "yStart": ystart,
                                    "yStop": ystop,
                                    "yPoints": ypoints,
                                    "yStep": meta["ystep"],
                                    "yRange": y_range,
                                    "yCenter": ycenter,
                                    "zStart": 0,
                                    "zStop": 0,
                                    "zPoints": 0}
        i += 1
    message = {"command": "doScan", "scan": scan}
    sock.send_pyobj(message)
    response = sock.recv_pyobj()
    if not response["status"]:
        return False
    status = False
    while not status:
        time.sleep(1)
        sock.send_pyobj({"command":"getStatus"})
        response = sock.recv_pyobj()
        status = response["status"]
    return status

def decimate(stxm_file, step_size, max_size = None, min_size = 1000, pad_size=0):
    """
    This is a particle finding routine.  It takes as input a large overview scan and then
    attempts to locate the particles.  It also defines a bounding box around each particle
    which can be used as a STXM scan region.  The list of scan regions is the output.
    """
    from pystxm_core.io.writeNX import stxm
    from skimage.morphology import erosion, dilation
    from skimage.measure import label, regionprops
    from skimage.filters import threshold_otsu
    from skimage.segmentation import clear_border
    from skimage.morphology import closing, square
    def multi_dil(im, num):
        for i in range(num):
            im = dilation(im)
        return im
    def multi_ero(im, num):
        for i in range(num):
            im = erosion(im)
        return im
    datafile = stxm_file
    s = stxm(stxm_file=datafile)
    im = s.data['entry0']['counts'][0]
    sh = im.shape
    im = im <  0.8 * im.max() #threshold_otsu(im)
    im = multi_dil(im, 2)
    im = multi_ero(im, 1)
    im = clear_border(im)
    label_im = label(im)
    scanList = []
    for i in regionprops(label_im):
        minr, minc, maxr, maxc = i.bbox
        xoffset,yoffset = 0,0
        xstart = s.data['entry0']['xpos'][minc] - pad_size + xoffset
        xstop = s.data['entry0']['xpos'][maxc] + pad_size + xoffset
        ystart = (s.data['entry0']['ypos'][minr] - pad_size) + yoffset
        ystop = (s.data['entry0']['ypos'][maxr] + pad_size) + yoffset
        nx = (xstop-xstart)/step_size-1
        ny = (ystop-ystart)/step_size-1
        npoints=nx*ny
        if max_size:
            if (npoints <= max_size) and (npoints >= min_size):
                scanList.append([xstart, xstop, ystart, ystop])
        else:
            scanList.append([xstart, xstop, ystart, ystop])
    return scanList

def singleMotorScan(meta):

    def exit_function(event):
        data.saveRegion(0)
        sys.exit()

    xstart = meta['xcenter'] - meta['xrange'] / 2.
    xstop = meta['xcenter'] + meta['xrange'] / 2.
    xstep = np.round((xstop - xstart) / (meta["xpoints"] - 1), 3)
    x_range = xstop - xstart
    xcenter = x_range / 2. + xstart
    ystart = 0
    ystop = 0
    ystep = 0
    y_range = 0
    ycenter = 0
    energyStep = (meta["energyStop"] - meta["energyStart"]) / meta["energyPoints"]
    scan = {"type": "Single Motor", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nxFileVersion": meta["nxFileVersion"],
            "sample": meta["Sample"],
            "x": meta["motor"],
            "y": None,
            "energy": "Energy",
            "doubleExposure": False,
            "n_repeats": 1,
            "defocus": False,
            "refocus": meta["refocus"],
            "oversampling_factor": 3,
            "mode": "point",
            "spiral": meta["spiral"],
            "scanRegions": {"Region1": {"xStart": xstart,
                                        "xStop": xstop,
                                        "xPoints": meta['xpoints'],
                                        "xStep": xstep,
                                        "xRange": x_range,
                                        "xCenter": xcenter,
                                        "yStart": ystart,
                                        "yStop": ystop,
                                        "yPoints": meta['xpoints'],
                                        "yStep": ystep,
                                        "yRange": y_range,
                                        "yCenter": ycenter,
                                        "zStart": 0,
                                        "zStop": 0,
                                        "zPoints": meta['xpoints']}},
            "energyRegions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                "start": meta["energyStart"],
                                                "stop": meta["energyStop"],
                                                "step": energyStep,
                                                "nEnergies": meta["energyPoints"]}}
            }
    data = stxm(scan)
    sock.send_pyobj({"command": "getScanID"})
    data.file_name = sock.recv_pyobj()["data"]
    data.start_time = str(datetime.datetime.now())
    data.startOutput()
    sock.send_pyobj({"command": "getMotorPositions"})
    data.motors = sock.recv_pyobj()["data"]
    plt.ion()
    # here we are creating sub plots
    figure, ax = plt.subplots(figsize=(10, 8))
    # setting title
    plt.title(meta["motor"] + " Scan: %s" %data.file_name, fontsize=10)
    # setting x-axis label and y-axis label
    plt.xlabel(meta["motor"] + ' (microns)')
    plt.ylabel(meta["daq"])
    ssize = np.linspace(xstart, xstop, meta["xpoints"])

    line1, = ax.plot(ssize, data.counts[0][0][0], 'ro-', mfc='white')
    ax_button = plt.axes([0.01, 0.01, 0.15, 0.05])
    abort_button = Button(ax_button, "Abort")
    abort_button.on_clicked(exit_function)
    t0 = time.time()
    i = 0
    for slit in ssize:
        moveMotor(meta["motor"], slit)
        data.counts[0][0][0][i] = read_daq(meta["daq"], meta["dwell"])
        # updating data values
        line1.set_xdata(ssize)
        line1.set_ydata(data.counts[0][0][0])
        ax.relim()
        ax.autoscale_view()
        # drawing updated values
        figure.canvas.draw()
        # This will run the GUI event
        # loop until all UI events
        # currently waiting have been processed
        figure.canvas.flush_events()
        i += 1
    data.saveRegion(0)
    print("Single motor scan took %.2f seconds" % ((time.time() - t0)))
    return data.file_name

def getMotorPosition(motor):
    sock.send_pyobj({"command": "getMotorPositions"})
    response = sock.recv_pyobj()
    return response['data'][motor]

def twoMotorScan(motors,daq,dwell,start,stop,npoints):
    plt.ion()
    # here we are creating sub plots
    fig = plt.figure()
    ax = fig.gca()
    # setting title
    plt.title("Two Motor Scan: %s and %s" %(motors[0],motors[1]), fontsize=20)
    # setting x-axis label and y-axis label
    plt.xlabel(motors[0] + ' (microns)')
    plt.ylabel(motors[1] + ' (microns)')
    x = np.linspace(start[0], stop[0], npoints[0])
    y = np.linspace(start[1], stop[1], npoints[1])
    data = np.zeros((npoints))
    im = ax.imshow(data, extent = (start[0],stop[0],start[1],stop[1]), interpolation = None)
    t0 = time.time()
    moveMotor(motors[1], y[0])
    moveMotor(motors[0], x[0])
    time.sleep(1)
    for i in range(npoints[1]):
        moveMotor(motors[1],y[i])
        for j in range(npoints[0]):
            moveMotor(motors[0],x[j])
            data[i,j] = read_daq(daq,dwell)
            im.set_data(data)
            im.set_clim(vmin = data[data > 0.].min(), vmax = data.max())
            fig.canvas.draw()
            #plt.draw()
            plt.pause(1e-3)
    print("Two motor scan took %.2f seconds" % ((time.time() - t0)))
    return data

meta = {"proposal": "BLS-000001", "experimenters":"Shapiro", "nxFileVersion":2.1}
meta["xcenter"] = 0
meta["xrange"] = 5
meta["xpoints"] = 50
meta["ycenter"] = 0
meta["yrange"] = 5
meta["ypoints"] = 50
meta["energyStart"] = 605
meta["energyStop"] = 700
meta["energyPoints"] = 20
meta["dwell"] = 10.
meta["defocus"] = False
meta["doubleExposure"] = False
meta["spiral"] = False
meta["refocus"] = True
MOTORS,SCANS,DUMMY,DAQS = get_config()


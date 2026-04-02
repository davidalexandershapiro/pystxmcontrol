from pystxmcontrol.utils.writeNX import stxm
import matplotlib.pyplot as plt
import matplotlib as mpl
import sys, zmq, os, json, traceback, datetime, asyncio
import numpy as np
from matplotlib.widgets import Button
from time import time, sleep
import zmq.asyncio


class scripter:
    def __init__(self,host: str = "127.0.0.1", port: int = 9999):
        """
        """

        context = zmq.asyncio.Context()
        self.sock = context.socket(zmq.REQ)
        self.sock.connect("tcp://%s:%s" %(host,port))

        ##This is just a default metadata dictionary created when scripter is imported
        ##MOTORS from the last line is used as a check in the move_motor command.  This isn't needed otherwise
        self.meta = {"proposal": "BLS-000001", "experimenters":"Shapiro", "nx_file_version":3}
        self.meta["xcenter"] = 0
        self.meta["xrange"] = 5
        self.meta["xpoints"] = 50
        self.meta["ycenter"] = 0
        self.meta["yrange"] = 5
        self.meta["ypoints"] = 50
        self.meta["energyStart"] = 605
        self.meta["energyStop"] = 700
        self.meta["energyPoints"] = 20
        self.meta["dwell"] = 10.
        self.meta["defocus"] = False
        self.meta["doubleExposure"] = False
        self.meta["spiral"] = False
        self.meta["autofocus"] = True
        self.meta["daq_list"] = ["default"]
        self.meta["comment"] = ""
        self.meta["loop_scan"] = False
        self.meta["sample_description"] = None
        self.MOTORS,self.SCANS,self.POSITIONS,self.DAQS,self.CONFIG = asyncio.run(self.get_config())

    async def move_motor(self, axis=None, pos=None):
        if axis not in list(self.MOTORS.keys()):
            print("Bad motor name. Available motors are:")
            for m in list(self.MOTORS.keys()):
                print(m)
            return
        message = {"command": "moveMotor", "axis": axis, "pos": pos}
        self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if response is not None: return response["status"]
        else: return False

    async def get_config(self):
        message = {"command": "get_config"}
        self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if response is not None: return response["data"]
        else: return False

    async def read_daq(self, daq,dwell, shutter = True):
        message = {"command":"get_data","daq":daq,"dwell":dwell, "shutter":shutter}
        self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if response is not None: return response["data"]
        else: return False

    async def stop_monitor(self):
        message = {"command": "stop_monitor"}
        self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if response is not None: return response["status"]
        else: return False

    async def start_monitor(self):
        message = {"command": "start_monitor"}
        self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if response is not None: return response["status"]
        else: return False

    async def ptychography_scan(self, meta):
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
        scan = {"scan_type": "Ptychography Image", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nx_file_version": 3,
                "sample": meta["sample_description"],
                "x_motor": "SampleX",
                "y_motor": "SampleY",
                "energy_motor": "Energy",
                "doubleExposure": meta["doubleExposure"],
                "n_repeats": 1,
                "defocus": meta["defocus"],
                "autofocus": meta["autofocus"],
                "oversampling_factor": 1,
                "mode": 'ptychographyGrid',
                "coarse_only": False,
                "spiral": False,
                "retract": meta["retract"],
                "tiled": False,
                "daq_list": meta["daq_list"],
                "comment": meta["comment"],
                "coarse_only": False,
                "loop_scan": meta["loop_scan"],
                "driver": self.SCANS["Ptychography Image"]["driver"], #"ptychography_image",
                "scan_regions": {"Region1": {"xStart": xstart,
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
                                            "zPoints": 1}},
                "energy_regions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                    "start": meta["energyStart"],
                                                    "stop": meta["energyStop"],
                                                    "step": energyStep,
                                                    "n_energies": meta["energyPoints"]}}
                }
        if "energyList" in meta.keys():
            scan["energy_list"] = meta["energyList"]
            scan["dwell"] = meta["dwell"]
        message = {"command": "scan", "scan": scan}
        await self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if not response["status"]:
            return False
        file_name = response["data"]
        status = False
        while not status:
            await asyncio.sleep(1)
            await self.sock.send_pyobj({"command":"getStatus"})
            response = await self.sock.recv_pyobj()
            status = response["status"]
        return file_name

    async def stxm_scan(self, meta):
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
        scan = {"scan_type": "Image", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nx_file_version": 3,
                "sample": meta["sample_description"],
                "x_motor": "SampleX",
                "y_motor": "SampleY",
                "energy_motor": "Energy",
                "doubleExposure": False,
                "n_repeats": 1,
                "defocus": False,
                "autofocus": meta["autofocus"],
                "oversampling_factor": 3,
                "mode": "continuousLine",
                "coarse_only": False,
                "spiral": meta["spiral"],
                "tiled": False,
                "daq_list": meta["daq_list"],
                "comment": meta["comment"],
                "coarse_only": False,
                "loop_scan": meta["loop_scan"],
                "scan_regions": {"Region1": {"xStart": xstart,
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
                                            "zPoints": 1}},
                "energy_regions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                    "start": meta["energyStart"],
                                                    "stop": meta["energyStop"],
                                                    "step": energyStep,
                                                    "n_energies": meta["energyPoints"]}}
                }
        if "energyList" in meta.keys():
            scan["energy_list"] = meta["energyList"]
            scan["dwell"] = meta["dwell"]
        if meta["spiral"]:
            scan["driver"] = self.SCANS["Spiral Image"]["driver"] #"spiral_image"
            scan["scan_type"] = 'Spiral Image'
        else:
            scan["driver"] = self.SCANS["Image"]["driver"] #"line_image"
        message = {"command": "scan", "scan": scan}
        await self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if not response["status"]:
            return False
        file_name = response["data"]
        status = False
        while not status:
            await asyncio.sleep(1)
            await self.sock.send_pyobj({"command":"getStatus"})
            response = await self.sock.recv_pyobj()
            status = response["status"]
        return file_name

    async def multi_region_ptychography_scan(self, meta, scanRegList):
        energyStep = (meta["energyStop"] - meta["energyStart"]) / meta["energyPoints"]
        scan = {"scan_type": "Ptychography Image", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nx_file_version": 3,
                "sample": meta["Sample"],
                "x_motor": "SampleX",
                "y_motor": "SampleY",
                "energy_motor": "Energy",
                "doubleExposure": meta["doubleExposure"],
                "n_repeats": 1,
                "defocus": meta["defocus"],
                "autofocus": meta["autofocus"],
                "oversampling_factor": 1,
                "mode": "ptychographyGrid",
                "coarse_only": False,
                "spiral": meta["spiral"],
                "retract": meta["retract"],
                "daq_list": meta["daq_list"],
                "comment": meta["comment"],
                "coarse_only": False,
                "loop_scan": meta["loop_scan"],
                "driver": self.SCANS["Ptychography Image"]["driver"],
                "energy_regions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                    "start": meta["energyStart"],
                                                    "stop": meta["energyStop"],
                                                    "step": energyStep,
                                                    "n_energies": meta["energyPoints"]}}
                }
        scan["scan_regions"] = {}
        i = 1
        for region in scanRegList:
            xstart, xstop, ystart, ystop = region
            x_range = xstop - xstart
            xcenter = xstart + x_range / 2.
            xpoints = int(x_range / meta["xstep"])
            y_range = ystop - ystart
            ycenter = ystart + y_range / 2.
            ypoints = int(y_range / meta["ystep"])
            scan["scan_regions"]["Region" + str(i)] = {"xStart": xstart,
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
        self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if not response["status"]:
            return False
        file_name = response["data"]
        status = False
        while not status:
            sleep(1)
            self.sock.send_pyobj({"command":"getStatus"})
            response = await self.sock.recv_pyobj()
            status = response["status"]
        return file_name

    async def multi_region_stxm_scan(self, meta, scanRegList):
        # s = connect(ADDRESS, PORT)
        energyStep = (meta["energyStop"] - meta["energyStart"]) / meta["energyPoints"]
        scan = {"scan_type": meta["scan_type"], "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nx_file_version": 3,
                "sample": meta["Sample"],
                "x_motor": "SampleX",
                "y_motor": "SampleY",
                "energy_motor": "Energy",
                "doubleExposure": False,
                "n_repeats": 1,
                "defocus": False,
                "autofocus": meta["autofocus"],
                "oversampling_factor": 1,
                "mode": meta["mode"],
                "coarse_only": False,
                "spiral": meta["spiral"],
                "daq_list": meta["daq_list"],
                "comment": meta["comment"],
                "coarse_only": False,
                "loop_scan": meta["loop_scan"],
                "energy_regions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                    "start": meta["energyStart"],
                                                    "stop": meta["energyStop"],
                                                    "step": energyStep,
                                                    "n_energies": meta["energyPoints"]}}
                }
        scan["scan_regions"] = {}
        i = 1
        for region in scanRegList:
            xstart, xstop, ystart, ystop = region
            x_range = xstop - xstart
            xcenter = xstart + x_range / 2.
            xpoints = int(x_range / meta["xstep"])
            y_range = ystop - ystart
            ycenter = ystart + y_range / 2.
            ypoints = int(y_range / meta["ystep"])
            scan["scan_regions"]["Region" + str(i)] = {"xStart": xstart,
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
        if "energyList" in meta.keys():
            scan["energy_list"] = meta["energyList"]
            scan["dwell"] = meta["dwell"]
        if meta["spiral"]:
            scan["driver"] = self.SCANS["Spiral Image"]["driver"] #"spiral_image"
            scan["scan_type"] = 'Spiral Image'
        else:
            scan["driver"] = self.SCANS["Image"]["driver"] #"line_image"
        message = {"command": "doScan", "scan": scan}
        self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if not response["status"]:
            return False
        file_name = response["data"]
        status = False
        while not status:
            sleep(1)
            self.sock.send_pyobj({"command":"getStatus"})
            response = await self.sock.recv_pyobj()
            status = response["status"]
        return file_name

    async def decimate(self, stxm_file, step_size, max_size = None, min_size = 1000, pad_size=0):
        """
        This is a particle finding routine.  It takes as input a large overview scan and then
        attempts to locate the particles.  It also defines a bounding box around each particle
        which can be used as a STXM scan region.  The list of scan regions is the output.
        """
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

    async def get_motor_position(self, motor):
        self.sock.send_pyobj({"command": "getMotorPositions"})
        response = await self.sock.recv_pyobj()
        return response['data'][motor]

    async def single_motor_scan(self, meta):
        running = {'value': True}

        def exit_function(event):
            running['value'] = False
            plt.close(figure)

        def stop_function(event):
            data.interp_counts["default"] = data.counts["default"].copy()
            data.saveRegion(0)
            data.close()
            self.start_monitor()
            while running['value']:
                figure.canvas.flush_events()

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
        scan = {"scan_type": "Single Motor", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nx_file_version": 3,
                "sample": meta["Sample"],
                "x_motor": meta["xmotor"],
                "y_motor": None,
                "energy_motor": "Energy",
                "doubleExposure": False,
                "n_repeats": 1,
                "defocus": False,
                "autofocus": meta["autofocus"],
                "oversampling_factor": 1,
                "mode": "point",
                "coarse_only": False,
                "spiral": meta["spiral"],
                "daq_list": meta["daq_list"],
                "comment": meta["comment"],
                "scan_regions": {"Region1": {"xStart": xstart,
                                            "xStop": xstop,
                                            "xPoints": meta['xpoints'],
                                            "xStep": xstep,
                                            "xRange": x_range,
                                            "xCenter": xcenter,
                                            "yStart": ystart,
                                            "yStop": ystop,
                                            "yPoints": 1,
                                            "yStep": ystep,
                                            "yRange": y_range,
                                            "yCenter": ycenter,
                                            "zStart": 0,
                                            "zStop": 0,
                                            "zPoints": 1}},
                "energy_regions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                    "start": meta["energyStart"],
                                                    "stop": meta["energyStop"],
                                                    "step": energyStep,
                                                    "n_energies": meta["energyPoints"]}}
                }
        scan["main_config"] = self.CONFIG
        data = stxm(scan) #create the data structure
        self.sock.send_pyobj({"command": "getScanID"}) #get the next file name from the server
        data.file_name = await self.sock.recv_pyobj()["data"]
        data.start_time = str(datetime.datetime.now())
        data.startOutput() #allocate the data in the file
        self.move_motor("Energy",data.energies["default"][0])
        self.sock.send_pyobj({"command": "getMotorPositions"}) #get the current motor positions
        data.motorPositions = [await self.sock.recv_pyobj()["data"]]

        plt.ion()
        # here we are creating sub plots
        figure, ax = plt.subplots(figsize=(10, 8))
        figure.canvas.mpl_connect('close_event', exit_function)
        # setting title
        plt.title(meta["xmotor"] + " Scan: %s" %data.file_name, fontsize=10)
        # setting x-axis label and y-axis label
        plt.xlabel(meta["xmotor"] + ' (microns)')
        plt.ylabel(meta["daq"])
        mpts = np.linspace(xstart, xstop, meta["xpoints"])

        line1, = ax.plot(mpts, data.counts["default"][0][0,:], 'ro-', mfc='white')
        ax_button = plt.axes([0.01, 0.01, 0.15, 0.05])
        stop_button = Button(ax_button, "Stop")
        stop_button.on_clicked(stop_function)
        ax_button2 = plt.axes([0.17,0.01,0.15,0.05])
        close_button = Button(ax_button2, "Close")
        close_button.on_clicked(exit_function)

        self.stop_monitor()
        i = 0
        for m in mpts:
            self.move_motor(meta["xmotor"], m)
            data.counts["default"][0][0,i] = self.read_daq(meta["daq"], meta["dwell"])
            line1.set_xdata(mpts)
            line1.set_ydata(data.counts["default"][0][0,:])
            ax.relim()
            ax.autoscale_view()
            figure.canvas.draw()
            data.end_time = str(datetime.datetime.now())
            figure.canvas.flush_events()
            i += 1
        data.interp_counts["default"] = data.counts["default"].copy()
        data.saveRegion(0)
        self.start_monitor()

        while running['value']:
            figure.canvas.flush_events()
        return data.file_name

    async def two_motor_scan(self, meta):
        running = {'value': True}

        def exit_function(event):
            running['value'] = False
            plt.close(figure)

        def stop_function(event):
            data.interp_counts["default"] = data.counts["default"].copy()
            data.saveRegion(0)
            data.close()
            self.start_monitor()
            while running['value']:
                figure.canvas.flush_events()

        xstart = meta['xcenter'] - meta['xrange'] / 2.
        xstop = meta['xcenter'] + meta['xrange'] / 2.
        xstep = np.round((xstop - xstart) / (meta["xpoints"] - 1), 3)
        x_range = xstop - xstart
        xcenter = x_range / 2. + xstart
        xpoints = meta['xpoints']
        ystart = meta['ycenter'] - meta['yrange'] / 2.
        ystop = meta['ycenter'] + meta['yrange'] / 2.
        ystep = np.round((ystop - ystart) / (meta["ypoints"] - 1), 3)
        y_range = ystop - ystart
        ycenter = y_range / 2. + ystart
        ypoints = meta['ypoints']
        energyStep = (meta["energyStop"] - meta["energyStart"]) / meta["energyPoints"]
        scan = {"scan_type": "Two Motor Image", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nx_file_version": 3,
                "sample": meta["Sample"],
                "x_motor": meta["xmotor"],
                "y_motor": meta["ymotor"],
                "energy_motor": "Energy",
                "doubleExposure": False,
                "n_repeats": 1,
                "defocus": False,
                "autofocus": meta["autofocus"],
                "oversampling_factor": 1,
                "mode": "point",
                "coarse_only": False,
                "spiral": meta["spiral"],
                "daq_list": meta["daq_list"],
                "comment": meta["comment"],
                "scan_regions": {"Region1": {"xStart": xstart,
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
                                            "zPoints": 1}},
                "energy_regions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                    "start": meta["energyStart"],
                                                    "stop": meta["energyStop"],
                                                    "step": energyStep,
                                                    "n_energies": meta["energyPoints"]}}
                }
        scan["main_config"] = self.CONFIG
        data = stxm(scan) #create the data structure
        self.sock.send_pyobj({"command": "getScanID"}) #get the next file name from the server
        data.file_name = await self.sock.recv_pyobj()["data"]
        data.start_time = str(datetime.datetime.now())
        data.startOutput() #allocate the data in the file
        self.sock.send_pyobj({"command": "getMotorPositions"}) #get the current motor positions
        data.motorPositions = [await self.sock.recv_pyobj()["data"]]

        plt.ion()
        # here we are creating sub plots
        figure, ax = plt.subplots(figsize=(8, 8))
        figure.canvas.mpl_connect('close_event', exit_function)
        # setting title
        plt.suptitle("Two Motor Scan: %s and %s" %(meta["xmotor"],meta["ymotor"]), fontsize=14)
        plt.title(data.file_name, fontsize=12)
        # setting x-axis label and y-axis label
        plt.xlabel(meta["xmotor"] + ' (microns)')
        plt.ylabel(meta["ymotor"] + ' (microns)')
        start = xstart,ystart
        stop = xstop,ystop
        npoints = meta["xpoints"],meta["ypoints"]
        x = np.linspace(start[0], stop[0], npoints[0])
        y = np.linspace(start[1], stop[1], npoints[1])

        im = ax.imshow(np.reshape(data.counts["default"][0][0,:],npoints), extent = (start[1],stop[1],start[0],stop[0]), interpolation = None,cmap=mpl.colormaps[meta["cmap"]])
        self.move_motor(meta["ymotor"], y[0])
        self.move_motor(meta["xmotor"], x[0])

        ax_button = plt.axes([0.01, 0.01, 0.15, 0.05])
        stop_button = Button(ax_button, "Stop")
        stop_button.on_clicked(stop_function)
        ax_button2 = plt.axes([0.17,0.01,0.15,0.05])
        close_button = Button(ax_button2, "Close")
        close_button.on_clicked(exit_function)
        self.stop_monitor()
        for i in range(npoints[1]):
            self.move_motor(meta["ymotor"],y[i])
            for j in range(npoints[0]):
                self.move_motor(meta["xmotor"],x[j])
                k = j + i * npoints[0]
                data.counts["default"][0][0,k] = self.read_daq(meta["daq"],meta["dwell"])
                im.set_data(np.reshape(data.counts["default"][0][0,:],npoints))
                im.set_clim(vmin = data.counts["default"][0][data.counts["default"][0] > 0.].min(), vmax = data.counts["default"][0].max())
                ax.relim()
                ax.autoscale_view()
                # drawing updated values
                figure.canvas.draw()
                data.end_time = str(datetime.datetime.now())
                figure.canvas.flush_events()
        data.interp_counts["default"] = data.counts["default"].copy()
        data.saveRegion(0)
        self.start_monitor()
        while running['value']:
            figure.canvas.flush_events()
        return data.file_name

    async def andor_ptychography_scan(self, meta):
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
        scan = {"scan_type": "Andor Ptychography Image", "proposal": meta["proposal"], "experimenters": meta["experimenters"], "nx_file_version": 3,
                "sample": meta["Sample"],
                "x_motor": "SampleX",
                "y_motor": "SampleY",
                "energy_motor": "Energy",
                "doubleExposure": meta["doubleExposure"],
                "n_repeats": 1,
                "defocus": meta["defocus"],
                "autofocus": meta["autofocus"],
                "oversampling_factor": 1,
                "mode": 'ptychographyGrid',
                "spiral": False,
                "retract": meta["retract"],
                "tiled": False,
                "coarse_only": False,
                "daq_list": meta["daq_list"],
                "comment": meta["comment"],
                "driver": self.SCANS["Ptychography Image"]["driver"],
                "scan_regions": {"Region1": {"xStart": xstart,
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
                "energy_regions": {"EnergyRegion1": {"dwell": meta["dwell"],
                                                    "start": meta["energyStart"],
                                                    "stop": meta["energyStop"],
                                                    "step": energyStep,
                                                    "n_energies": meta["energyPoints"]}}
                }
        if "energyList" in meta.keys():
            scan["energy_list"] = meta["energyList"]
            scan["dwell"] = meta["dwell"]
        message = {"command": "scan", "scan": scan}
        self.sock.send_pyobj(message)
        response = await self.sock.recv_pyobj()
        if not response["status"]:
            return False
        status = False
        while not status:
            sleep(1)
            self.sock.send_pyobj({"command":"getStatus"})
            response = await self.sock.recv_pyobj()
            status = response["status"]
        return status




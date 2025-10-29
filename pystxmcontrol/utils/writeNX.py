import numpy as np
import h5py, datetime,json
from pystxmcontrol.utils.general import rebinLine

NXD_DEFAULT = 'default'
NXD_FILE_NAME = 'file_name'
NXD_FILE_TIME = 'file_time'
NXD_DATA = 'data'

class stxm:
    def __init__(self, scan_dict = None, stxm_file = None):
        """
        energies = array, single array since energies are the same for each scan region
        xPos = list, each element is an array for each scan region
        yPos = same as xPos
        channels = list, text description of each channel
        counts = nested list, each element for each scan region has an array for each channel
        :param scan_dict:
        """
        if scan_dict is not None:
            self.scan_dict = scan_dict
            self.dwells = None
            self.NXfile = None #this will be the h5py.File object
            self._nx_writer = None
            self._nx_reader = None
            if "start_time" in scan_dict.keys():
                self.start_time = self.scan_dict["start_time"]
            else:
                self.start_time = ""
            self.end_time = ""
            self.angle = 0.
            self.polarization = 0.
            self.nScanRegions = len(self.scan_dict["scan_regions"].keys())
            self._scanRegions = self.scan_dict["scan_regions"].keys()
            self.channels = ["diode"]  #this should come through from the DAQ config somehow
            self.nChannels = len(self.channels)
            self._extractEnergies(self.scan_dict)
            self._extractPositions(self.scan_dict)
            self.motorPositions = []
            self.DAQdwell = None
            self.motdwell = None
            for i in range(self.nScanRegions):
                self.motorPositions.append({})
            if "file_name" in self.scan_dict.keys():
                self.file_name = self.scan_dict["file_name"]
                self.startOutput()
        elif stxm_file is not None:
            self.data = {}
            self.meta = {}
            self.readNexus(stxm_file)

    def readNexus(self, stxm_file):
        try:
            self._nx_reader = h5py.File(stxm_file,'r')
        except:
            print("Failed to open file: %s" %stxm_file)
            return
        self.nRegions = len(list(self._nx_reader))
        self.meta["file_name"] = stxm_file

        #this is looking for the version information in the file but it's location and name has changed.  It used to be
        #called "definition" but that is not nexus compliant so now it is called "version" whereas "definition" now
        #refers to the nexus definition NXstxm.  Also, our original files did not have this at all.
        if self._nx_reader["entry0/definition"][()] == b"NXstxm":
            self.meta["version"] = self._nx_reader["entry0/version"][()]
        else:
            try:
                self.meta["version"] = float(self._nx_reader["entry0/definition"][()])
            except:
                try:
                    self.meta["version"] = float(self._nx_reader["entry0/definition"].attrs["version"].decode())
                except:
                    self.meta["version"] = 0

        #Version 3 brought a major revision in the names of the various entries.  Names were mostly consistent before that.
        if self.meta["version"] < 3:
            self.meta["start_time"] = self._nx_reader["entry0/start_time"][()][0].decode()
            self.meta["end_time"] = self._nx_reader["entry0/end_time"][()][0].decode()
            self.meta["experimenters"] = self._nx_reader["entry0/experimenters"][()][0].decode()
            self.meta["sample_description"] = self._nx_reader["entry0/sample_description"][()].decode()
            self.meta["proposal"] = self._nx_reader["entry0/proposal"][()].decode()
            self.meta["scan_type"] = self._nx_reader["entry0/counter0/stxm_scan_type"][()].decode()
        else:
            self.meta["start_time"] = self._nx_reader["entry0/start_time"][()].decode()
            self.meta["end_time"] = self._nx_reader["entry0/end_time"][()].decode()
            self.meta["experimenters"] = self._nx_reader["entry0/experimenters"][()].decode()
            self.meta["sample_description"] = self._nx_reader["entry0/sample/description"][()].decode()
            self.meta["proposal"] = self._nx_reader["entry0/title"][()].decode()
            self.meta["scan_type"] = self._nx_reader["entry0/default/stxm_scan_type"][0].decode()
            self.meta["daq_list"] = []
            for daq in list(self._nx_reader[f"entry0/instrument"]):
                if "type" in self._nx_reader[f"entry0/instrument/{daq}"].attrs.keys():
                    if self._nx_reader[f"entry0/instrument/{daq}"].attrs["type"].decode() == "photon":
                        self.meta["daq_list"].append(daq)

        #Version 2 was the first major change in how data was represented in the file.  This brought the separation between
        #raw data and interpolated data in the file.
        if self.meta["version"] == 2.0:
            #Code for using verion 2:
            for i in range(self.nRegions):
                entryStr = "entry" + str(i)
                self.data[entryStr] = {}
                self.data[entryStr]["motors"] = {}
                for item in list(self._nx_reader[entryStr + "/motors"]):
                    self.data[entryStr]["motors"][item] = self._nx_reader[entryStr + "/motors/" + item][()]
                self.data[entryStr]["energy"] = self._nx_reader[entryStr + "/counter0/energy"][()].astype("float64")
                #Could switch this to be actual dwell time for each pixel.
                self.data[entryStr]["dwell"] = self._nx_reader[entryStr + "/counter0/count_time"][()].astype("float64")
                xMeas = np.array(self._nx_reader[entryStr + "/counter0/sample_x"][()]).astype("float64")
                yMeas = np.array(self._nx_reader[entryStr + "/counter0/sample_y"][()]).astype("float64")
                xReq = np.array(self._nx_reader[entryStr+"/requested_values/sample_x"][()]).astype('float64')
                yReq = np.array(self._nx_reader[entryStr+"/requested_values/sample_y"][()]).astype('float64')
                rawCounts = self._nx_reader[entryStr + "/counter0/data"][()].astype("float64")
                
                #Define the new shape of the counts to line up with the requested values.
                #This is the same as the shape of rawCounts except that the x values are fewer.
                newShape = (rawCounts.shape[0],rawCounts.shape[1], len(xReq))
                newCounts = np.zeros(newShape)
                
                if self.meta["scan_type"] == "Ptychography Image":
                    newCounts = rawCounts
                else:
                #First axis is energy. Each item is an "image" regardless of count
                    for i, image in enumerate(newCounts):
                        #Second axis is line in image.
                        #TODO: Check with focus scan.
                        for j, line in enumerate(image):
                            xLine = xMeas[i,j]
                            yLine = yMeas[i,j]
                            if self.meta["scan_type"] == "Image":
                                yVals = np.ones(xLine.shape)*yReq[j]
                            else:
                                yVals = yReq
                            countsLine = rawCounts[i,j]
                            newCounts[i,j] = rebinLine(xReq,yVals,xLine,yLine,countsLine)
                       
                self.data[entryStr]["counts"] = newCounts
                self.data[entryStr]["xpos"] = xReq
                #I don't think this is right for non-image scans
                self.data[entryStr]["ypos"] = yReq
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/(xpos.size - 1)
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/(ypos.size - 1)

        #yet another revision in how the raw data and interpolated data are represented
        elif self.meta["version"] == 2.1:
            #code for using version 2.1:
            for i in range(self.nRegions):
                entryStr = 'entry' + str(i)
                self.data[entryStr] = {}
                self.data[entryStr]["motors"] = {}
                for item in list(self._nx_reader[entryStr + "/motors"]):
                    self.data[entryStr]["motors"][item] = self._nx_reader[entryStr + "/motors/" + item][()]
                self.data[entryStr]["energy"] = self._nx_reader[entryStr + "/counter0/energy"][()].astype("float64")
                self.data[entryStr]["dwell"] = self._nx_reader[entryStr + "/counter0/count_time"][()].astype("float64")
                self.data[entryStr]["counts"] = self._nx_reader[entryStr + "/binned_values/data"][()].astype("float64")
                self.data[entryStr]["xpos"] = np.array(self._nx_reader[entryStr + "/binned_values/sample_x"][()]).astype("float64")
                self.data[entryStr]["ypos"] = np.array(self._nx_reader[entryStr + "/binned_values/sample_y"][()]).astype("float64")
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/(xpos.size - 1)
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/(ypos.size - 1)

        #major revision in the entry names and data structure to make this nexus compliant
        elif self.meta["version"] == 3.0:
             for i in range(self.nRegions):
                entryStr = 'entry' + str(i)
                self.data[entryStr] = {}
                self.data[entryStr]["motors"] = {}
                for item in list(self._nx_reader[entryStr + "/instrument/motors"]):
                    self.data[entryStr]["motors"][item] = self._nx_reader[entryStr + "/instrument/motors/" + item][()]
                self.data[entryStr]["energy"] = self._nx_reader[entryStr + "/instrument/monochromator/energy"][()].astype("float64")
                self.data[entryStr]["dwell"] = self._nx_reader[entryStr + "/default/count_time"][()].astype("float64")
                self.data[entryStr]["counts"] = {}
                for daq in self.meta["daq_list"]:
                    self.data[entryStr]["counts"][daq] = self._nx_reader[entryStr + f"/{daq}/data"][()].astype("float64") #data at user requested positions
                self.data[entryStr]["xpos"] = np.array(self._nx_reader[entryStr + "/default/sample_x"][()]).astype("float64")
                self.data[entryStr]["ypos"] = np.array(self._nx_reader[entryStr + "/default/sample_y"][()]).astype("float64")
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/(xpos.size - 1)
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/(ypos.size - 1)
                try:
                    self.meta["x_motor"] = self._nx_reader[entryStr + "/data/motor_name_x"][()].decode()
                    self.meta["y_motor"] = self._nx_reader[entryStr + "/data/motor_name_y"][()].decode()
                except:
                    pass

        #the original data format
        else:
            #Code for reading files with version <2.
            #Includes files without a version (as version 0).
            for i in range(self.nRegions):
                entryStr = "entry" + str(i)
                self.data[entryStr] = {}
                self.data[entryStr]["motors"] = {}
                for item in list(self._nx_reader[entryStr + "/motors"]):
                    self.data[entryStr]["motors"][item] = self._nx_reader[entryStr + "/motors/" + item][()]
                self.data[entryStr]["energy"] = self._nx_reader[entryStr + "/counter0/energy"][()].astype("float64")
                self.data[entryStr]["dwell"] = self._nx_reader[entryStr + "/counter0/count_time"][()].astype("float64")
                self.data[entryStr]["counts"] = self._nx_reader[entryStr + "/counter0/data"][()].astype("float64")
                self.data[entryStr]["xpos"] = np.array(self._nx_reader[entryStr + "/counter0/sample_x"][()]).astype("float64")
                self.data[entryStr]["ypos"] = np.array(self._nx_reader[entryStr + "/counter0/sample_y"][()]).astype("float64")
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/xpos.size
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/ypos.size

    def _extractEnergies(self, scan):
        ##get energies
        self.daq_list = scan["daq list"]
        self.dwells = np.array(())
        self.energies = {daq: [] for daq in self.daq_list}
        if scan.get("energy_list") is None:
            for energy_region in scan["energy_regions"].keys():
                start = scan["energy_regions"][energy_region]["start"]
                stop = scan["energy_regions"][energy_region]["stop"]
                n_energies = scan["energy_regions"][energy_region]["n_energies"]
                self.energies["default"] = np.concatenate((self.energies["default"],np.round(np.linspace(start, stop, n_energies), 2)))
                self.dwells = np.concatenate((self.dwells,np.ones(n_energies) * scan["energy_regions"][energy_region]["dwell"]))
        else:
            self.energies["default"] = np.array(scan["energy_list"])
            self.dwells = np.ones(self.energies["default"].size) * scan["dwell"]

    def _extractPositions(self, scan):
        self.xPos, self.yPos, self.zPos = [], [], []
        self.xMeasured, self.yMeasured, self.zMeasured = [], [], []
        self.xstepsize = []
        self.ystepsize = []
        self.daq_list = scan["daq list"]
        self.counts = {daq: [] for daq in self.daq_list}
        self.interp_counts = {daq: [] for daq in self.daq_list} 

        for region in scan["scan_regions"].keys():
            self.xPos.append(np.linspace(scan["scan_regions"][region]["xStart"], \
                               scan["scan_regions"][region]["xStop"], \
                               scan["scan_regions"][region]["xPoints"]))
            self.yPos.append(np.linspace(scan["scan_regions"][region]["yStart"], \
                               scan["scan_regions"][region]["yStop"], \
                               scan["scan_regions"][region]["yPoints"]))
            self.zPos.append(np.linspace(scan["scan_regions"][region]["zStart"], \
                               scan["scan_regions"][region]["zStop"], \
                               scan["scan_regions"][region]["zPoints"]))
            self.xstepsize.append(scan["scan_regions"][region]["xStep"])
            self.ystepsize.append(scan["scan_regions"][region]["yStep"])

            #nPos are the number of positions commanded by the user
            #nPixels are the number of measurements made by the control system
            nxPos = self.xPos[-1].size
            nyPos = self.yPos[-1].size
            nzPos = self.zPos[-1].size
            nxPixels = nxPos
            nyPixels = nyPos
            nzPixels = nzPos
            nPixels_m = nxPixels * nyPixels #total number of measured pixels
            nPixels_r = nxPos * nyPos #total number of requested pixels, shown for clarity

            if "Focus" in scan["scan_type"]:
                #hack because out data structure doesn't have the Z positions needed for a focus scan
                nyPos = nzPos

            self.xMeasured.append(np.zeros(nPixels_m))
            self.yMeasured.append(np.zeros(nPixels_m))
            self.zMeasured.append(np.zeros(nPixels_m))
            for daq in scan["daq list"]:
                self.counts[daq].append(np.zeros((self.energies["default"].size,nPixels_m))) #this is a long vector of measured positions
                self.interp_counts[daq].append(np.zeros((self.energies["default"].size,nyPos,nxPos))) #this is a matrix of requested positions
  
            
    def updateArrays(self,region,scanInfo):
        #doing things this way requires the scan driver to correctly provide the number of points for each line and image
        #but this is much much cleaner
        #self.counts should the long vector of (I,Z,Y,X) points whereas self.interp_counts will be (Z,Y,X) matrix
        #self.interp_counts does not need to be updated here because its shape doesn't depend on the calculated trajectories
        motorLength = scanInfo['numMotorPoints']
        DAQLength = scanInfo['numDAQPoints']
        for daq in self.daq_list:
            n_energies = scanInfo["rawData"][daq]["meta"]["n_energies"]
            self.counts[daq][region] = np.zeros((n_energies,DAQLength))
        self.xMeasured[region] = np.zeros((self.energies["default"].size,motorLength))
        self.yMeasured[region] = np.zeros((self.energies["default"].size,motorLength))
        self.zMeasured[region] = np.zeros((self.energies["default"].size,motorLength))
        self.saveRegion(region)

    def startOutput(self):
        """
        Adapted from Matthew Marcus version in pystxm....
        This is the routine which writes a Pixelator-style NXstxm file.  I have NOT
        tried it with anything but stacks - no linescans or point scans or...
        """
        print("Starting output of file %s" %self.file_name)
        self._nx_writer = h5py.File(self.file_name,'w',libver='latest')
        n_scan_regions = len(self.xPos)
        for i in range(n_scan_regions):
            self.saveRegion(i)
        self._nx_writer.swmr_mode = True
        
    def addDict(self,d,name):
        self._nx_writer.create_dataset(name=name, data=json.dumps(d))

    def saveRegion(self,i, nt = None):
        # Check if file is still open before attempting to save
        if self._nx_writer is None:
            return

        try:
            # Attempt to list entries - will fail if file is closed
            entries = list(self._nx_writer)

            if (f"entry{i}") in entries:
                self.updateEntry(i)
            else:
                self.createEntry(i)
                self.updateEntry(i)
            self.end_time = datetime.datetime.now().isoformat()
            self._nx_writer[f'entry{i}/end_time'][...] = str(self.end_time).encode("UTF_8")

        except Exception:
            # File is closed or invalid - silently skip save
            pass

    def updateEntry(self,i):

        #I'm not sure that this works for spiral scans where the data size is actually increased by the
        #motor driver. The initial array size at creation is just an estimate but gets revised.  May have to delete
        #and re-create?
        for daq in self.daq_list:
            del self._nx_writer[f'entry{i}/instrument/{daq}/data']
            self._nx_writer[f'entry{i}/instrument/{daq}'].create_dataset("data", data = self.counts[daq][i])
            del self._nx_writer[f'entry{i}/{daq}/data']
            self._nx_writer[f'entry{i}/{daq}'].create_dataset("data", data = self.interp_counts[daq][i])
            self._nx_writer[f'entry{i}/instrument/{daq}/data'].flush()
            self._nx_writer[f'entry{i}/{daq}/data'].flush()
            self._nx_writer[f'entry{i}/instrument/{daq}/data'].attrs["energies"] = self.energies[daq]
        #add the measured motor positions
        del self._nx_writer[f'entry{i}/instrument/sample_x/data']
        self._nx_writer[f'entry{i}/instrument/sample_x'].create_dataset("data", data = self.xMeasured[i])
        del self._nx_writer[f'entry{i}/instrument/sample_y/data']
        self._nx_writer[f'entry{i}/instrument/sample_y'].create_dataset("data", data = self.yMeasured[i])
        for motor in self.motorPositions[i].keys():
            try:
                self._nx_writer[f'entry{i}/instrument/motors'].create_dataset(motor.replace(" ","_").lower(), data = self.motorPositions[i][motor])
            except:
                pass
        
    def addFrame(self,frame,framenum, mode="dark"):

        if mode == "dark":
            grp = self._nx_writer['entry0/ccd0/dark']
        if mode == "exp":
            grp = self._nx_writer['entry0/ccd0/exp']
        grp.create_dataset(name = str(framenum), data=frame, maxshape=None)

    def createEntry(self,i):
        nz_m,ny_m,nx_m = len(self.zMeasured[i]),len(self.yMeasured[i]),len(self.xMeasured[i])

        nxentry = self._nx_writer.create_group(f'entry{i}')
        nxentry.attrs["NX_class"] = np.bytes_("NXentry")
        nxentry.create_dataset("start_time", data=str(self.start_time).encode("UTF_8"))
        nxentry.create_dataset("end_time", data=str(self.end_time).encode("UTF_8"))
        nxentry.create_dataset("title", data=self.scan_dict["proposal"].encode("UTF_8"))
        nxentry.create_dataset("version", data=float(self.scan_dict["main_config"]["server"]["nx_file_version"]))
        nxentry.create_dataset("definition", data=["NXstxm".encode("UTF_8")])
        nxentry.create_dataset("experimenters", data=self.scan_dict["experimenters"].encode("UTF_8"))
        nxinstrument = nxentry.create_group("instrument")
        nxinstrument.attrs["NX_class"] = np.bytes_("NXinstrument")
        nxsource = nxinstrument.create_group("source")
        nxsource.attrs["NX_class"] = np.bytes_("NXsource")
        nxsource.create_dataset("type",data=self.scan_dict['main_config']['source']['type'])
        nxsource.create_dataset("name", data=self.scan_dict['main_config']['source']['name'])
        nxsource.create_dataset("probe", data=self.scan_dict['main_config']['source']['probe'])
        nxmono = nxinstrument.create_group("monochromator")
        nxmono.attrs["NX_class"] = np.bytes_("NXmonochromator")
        nxmono.create_dataset("energy",data=self.energies["default"]) #this is the incident energy of the beamline
        for daq in self.daq_list:
            nxdetector = nxinstrument.create_group(daq)
            nxdetector.attrs["NX_class"] = np.bytes_("NXdetector")
            nxdetector.attrs["type"] = np.bytes_("photon")
            dset = nxdetector.create_dataset("data",data=np.zeros_like(self.counts[daq][i]))
            dset.attrs["energies"] = self.energies[daq]
        measured_xgrp = nxinstrument.create_group("sample_x")
        measured_ygrp = nxinstrument.create_group("sample_y")
        measured_zgrp = nxinstrument.create_group("sample_z")
        measured_xgrp.attrs["NX_class"] = np.bytes_("NXdetector")
        measured_ygrp.attrs["NX_class"] = np.bytes_("NXdetector")
        measured_zgrp.attrs["NX_class"] = np.bytes_("NXdetector")
        measured_xgrp.create_dataset("data",data=np.zeros(nx_m))
        measured_ygrp.create_dataset("data", data=np.zeros(ny_m))
        measured_zgrp.create_dataset("data", data=np.zeros(nz_m))
        motors = nxinstrument.create_group("motors")
        motors.attrs["NX_class"] = np.bytes_("NXdetector")
        sample = nxentry.create_group("sample")
        sample.attrs["NX_class"] = np.bytes_("NXsample")
        sample.create_dataset("rotation_angle", data='')
        sample.create_dataset("description", data=self.scan_dict["sample"])
        sample.create_dataset("comment", data=self.scan_dict["comment"])
        for daq in self.daq_list:
            d = nxentry.create_group(daq)
            d.attrs["NX_class"] = np.bytes_("NXdata")
            d.attrs["axes"] = [np.bytes_("energy"),np.bytes_("sample_y"),np.bytes_("sample_x")]
            d.attrs["signal"] = "data"
            d.create_dataset("stxm_scan_type",data=[self.scan_dict["scan_type"]])
            d.create_dataset("data",data=np.zeros_like(self.interp_counts[daq][i]))
            energy = d.create_dataset("energy",data=self.energies["default"])
            energy.attrs["axis"] = 1
            d.create_dataset("count_time",data=self.dwells)
            sample_y = d.create_dataset("sample_y",data=self.yPos[i])
            sample_y.attrs["axis"] = 2
            sample_x = d.create_dataset("sample_x",data=self.xPos[i])
            sample_x.attrs["axis"] = 3
            d.create_dataset("motor_name_x",data=self.scan_dict["x_motor"])
            try:
                d.create_dataset("motor_name_y",data=self.scan_dict["y_motor"])
            except:
                d.create_dataset("motor_name_y", data="None")
        if self.scan_dict['scan_type'] == "Ptychography Image":
            ccd = nxentry.create_group('ccd0')
            ccd.create_group('dark')
            ccd.create_group('exp')
        self._nx_writer.flush()

    def close(self):
        if self._nx_writer is not None:
            try:
                self._nx_writer.close()
            except Exception:
                pass

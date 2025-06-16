import numpy as np
import h5py, datetime,json

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
        if stxm_file is None:
            self.scan_dict = scan_dict
            self.dwells = None
            self.file_name = None
            self.start_time = ""
            self.end_time = ""
            self.angle = 0.
            self.polarization = 0.
            self.nScanRegions = len(self.scan_dict["scanRegions"].keys())
            self._scanRegions = self.scan_dict["scanRegions"].keys()
            self.channels = ["diode"]  #this should come through from the DAQ config somehow
            self.nChannels = len(self.channels)
            self._extractEnergies(self.scan_dict)
            self._extractPositions(self.scan_dict)
            self.motorPositions = []
            self.DAQdwell = None
            self.motdwell = None
            for i in range(self.nScanRegions):
                self.motorPositions.append({})
        elif scan_dict is None:
            self.readNexus(stxm_file)
        else:
            pass

    def _rebinLine(self, xReq, yReq, xMeas, yMeas, rawCounts):
    
        #Returns a rebinning of the rawCounts into bins defined by xReq and yReq
        #For a single line only. rawCounts, xMeas and yMeas are all the same shape.
        xstart = xReq[0]
        xstop = xReq[-1]
        ystart = yReq[0]
        ystop = yReq[-1]
        
        #Define the oversampling factor for averaging later.
        oversampling_factor = len(xMeas)/len(xReq)
        
        #direction here is a unit vector in the direction of the scan.
        direction = np.array([xstop-xstart,ystop-ystart])
        direction = direction/np.linalg.norm(direction)
        #We need to convert the requested and measured positions to distances along this direction.
        distReq = np.array([(xReq[i]-xstart)*direction[0]+(yReq[i]-ystart)*direction[1] for i in range(len(xReq))])
        #TODO: FIX THIS
        distMeas = np.array([(xMeas[i]-xstart)*direction[0]+(yMeas[i]-ystart)*direction[1] for i in range(len(xMeas))])

        #This doesn't assume even spacing of positions which is probably overkill.
        #Generate bins for np.histogram function.
        distBins = (distReq[1:]+distReq[:-1])/2
        distBins = np.append(distBins,2*distReq[-1]-distBins[-1])
        distBins = np.insert(distBins,0,2*distReq[0]-distBins[0])
        
        
        try:
            cutoff = np.where(distMeas>ddistBins[-1])[0][0]
        except:
            cutoff = np.where(distMeas == max(distMeas))[0][0]
            
        distMeas = distMeas[:cutoff]
        
        rawCounts = rawCounts[:cutoff]

        #nEvents is just the number of times we had an x value in each of the bins. May be useful to track.
        nEvents,edges = np.histogram(distMeas,bins = distBins)
        #This is the total counts in each bin.
        binCounts,edges = np.histogram(distMeas,bins = distBins, weights = rawCounts)
        #Final counts are the counts per bin divided by the events.
        #The oversampling factor is put in here so that the count rate is independent of the oversampling factor.
        #For zero events in a bin, we replace the inf values with zero (and ignore error messages).
        with np.errstate(divide='ignore',invalid='ignore'):
            counts = binCounts/nEvents*oversampling_factor
        counts[np.isinf(counts)] = 0
        counts[np.isnan(counts)] = 0
        
        #Interpolate if the pixel is zero. 
        for i in range(len(counts)):
            if counts[i] == 0:
                if i != 0 and i != len(counts)-1:
                    if counts[i+1] != 0 and counts[i-1] != 0:
                        counts[i] = (counts[i+1]+counts[i-1])/2
                elif i == 0:
                    if counts[1] != 0:
                        counts[0] = counts[1]
                else:
                    if counts[-2] != 0:
                        counts[-1] = counts[-2]
        return(counts)

    def readNexus(self, stxm_file):
        # try:
        f = h5py.File(stxm_file,'r')
        self.NXfile = f
        # except:
        #     print("Failed to open file: %s" %stxm_file)
        #     return
        self.nRegions = len(list(f))
        self.data = {}
        self.meta = {}
        self.meta["file_name"] = stxm_file

        try:
            self.meta["version"] = float(f["entry0/definition"][()])
        except:
            try:
                self.meta["version"] = float(f["entry0/definition"].attrs["version"].decode())
            except:
                self.meta["version"] = 0

        if self.meta["version"] < 3:
            self.meta["start_time"] = f["entry0/start_time"][()][0].decode()
            self.meta["end_time"] = f["entry0/end_time"][()][0].decode()
            self.meta["experimenters"] = f["entry0/experimenters"][()][0].decode()
            self.meta["sample_description"] = f["entry0/sample_description"][()].decode()
            self.meta["proposal"] = f["entry0/proposal"][()].decode()
            self.meta["scan_type"] = f["entry0/counter0/stxm_scan_type"][()].decode()
        else:
            self.meta["start_time"] = f["entry0/start_time"][()].decode()
            self.meta["end_time"] = f["entry0/end_time"][()].decode()
            self.meta["experimenters"] = f["entry0/experimenters"][()].decode()
            self.meta["sample_description"] = f["entry0/sample/description"][()].decode()
            self.meta["proposal"] = f["entry0/title"][()].decode()
            self.meta["scan_type"] = f["entry0/data/stxm_scan_type"][()].decode()
        
        if self.meta["version"] == 2.0:
            #Code for using verion 2:
            for i in range(self.nRegions):
                entryStr = "entry" + str(i)
                self.data[entryStr] = {}
                self.data[entryStr]["motors"] = {}
                for item in list(f[entryStr + "/motors"]):
                    self.data[entryStr]["motors"][item] = f[entryStr + "/motors/" + item][()]
                self.data[entryStr]["energy"] = f[entryStr + "/counter0/energy"][()].astype("float64")
                #Could switch this to be actual dwell time for each pixel.
                self.data[entryStr]["dwell"] = f[entryStr + "/counter0/count_time"][()].astype("float64")
                xMeas = np.array(f[entryStr + "/counter0/sample_x"][()]).astype("float64")
                yMeas = np.array(f[entryStr + "/counter0/sample_y"][()]).astype("float64")
                xReq = np.array(f[entryStr+"/requested_values/sample_x"][()]).astype('float64')
                yReq = np.array(f[entryStr+"/requested_values/sample_y"][()]).astype('float64')
                rawCounts = f[entryStr + "/counter0/data"][()].astype("float64")
                
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
                            newCounts[i,j] = self._rebinLine(xReq,yVals,xLine,yLine,countsLine)
                       
                self.data[entryStr]["counts"] = newCounts
                self.data[entryStr]["xpos"] = xReq
                #I don't think this is right for non-image scans
                self.data[entryStr]["ypos"] = yReq
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/xpos.size
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/ypos.size

        elif self.meta["version"] == 2.1:
            #code for using version 2.1:
            for i in range(self.nRegions):
                entryStr = 'entry' + str(i)
                self.data[entryStr] = {}
                self.data[entryStr]["motors"] = {}
                for item in list(f[entryStr + "/motors"]):
                    #print(item)
                    self.data[entryStr]["motors"][item] = f[entryStr + "/motors/" + item][()]
                self.data[entryStr]["energy"] = f[entryStr + "/counter0/energy"][()].astype("float64")
                self.data[entryStr]["dwell"] = f[entryStr + "/counter0/count_time"][()].astype("float64")
                self.data[entryStr]["counts"] = f[entryStr + "/binned_values/data"][()].astype("float64")
                self.data[entryStr]["xpos"] = np.array(f[entryStr + "/binned_values/sample_x"][()]).astype("float64")
                self.data[entryStr]["ypos"] = np.array(f[entryStr + "/binned_values/sample_y"][()]).astype("float64")
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/xpos.size
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/ypos.size
        elif self.meta["version"] == 3.0:
             for i in range(self.nRegions):
                entryStr = 'entry' + str(i)
                self.data[entryStr] = {}
                self.data[entryStr]["motors"] = {}
                for item in list(f[entryStr + "/instrument/motors"]):
                    #print(item)
                    self.data[entryStr]["motors"][item] = f[entryStr + "/instrument/motors/" + item][()]
                self.data[entryStr]["energy"] = f[entryStr + "/instrument/monochromator/energy"][()].astype("float64")
                self.data[entryStr]["dwell"] = f[entryStr + "/data/count_time"][()].astype("float64")
                self.data[entryStr]["counts"] = f[entryStr + "/data/data"][()].astype("float64") #data at user requested positions
                self.data[entryStr]["xpos"] = np.array(f[entryStr + "/data/sample_x"][()]).astype("float64")
                self.data[entryStr]["ypos"] = np.array(f[entryStr + "/data/sample_y"][()]).astype("float64")
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/xpos.size
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/ypos.size           

        else:
            #Code for reading files with version <2.
            #Includes files without a version (as version 0).
            for i in range(self.nRegions):
                entryStr = "entry" + str(i)
                self.data[entryStr] = {}
                self.data[entryStr]["motors"] = {}
                for item in list(f[entryStr + "/motors"]):
                    #print(item)
                    self.data[entryStr]["motors"][item] = f[entryStr + "/motors/" + item][()]
                self.data[entryStr]["energy"] = f[entryStr + "/counter0/energy"][()].astype("float64")
                self.data[entryStr]["dwell"] = f[entryStr + "/counter0/count_time"][()].astype("float64")
                self.data[entryStr]["counts"] = f[entryStr + "/counter0/data"][()].astype("float64")
                self.data[entryStr]["xpos"] = np.array(f[entryStr + "/counter0/sample_x"][()]).astype("float64")
                self.data[entryStr]["ypos"] = np.array(f[entryStr + "/counter0/sample_y"][()]).astype("float64")
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/xpos.size
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/ypos.size

    def _extractEnergies(self, scan):
        ##get energies
        self.energies = np.array(())
        self.dwells = np.array(())
        if "energy_list" in scan.keys():
            self.energies = np.array(scan["energy_list"])
            self.dwells = np.ones(self.energies.size) * scan["dwell"]
        else:
            for energyRegion in scan["energyRegions"].keys():
                start = scan["energyRegions"][energyRegion]["start"]
                stop = scan["energyRegions"][energyRegion]["stop"]
                nEnergies = scan["energyRegions"][energyRegion]["nEnergies"]
                self.energies = np.concatenate((self.energies,np.round(np.linspace(start, stop, nEnergies), 2)))
                self.dwells = np.concatenate((self.dwells,np.ones(nEnergies) * scan["energyRegions"][energyRegion]["dwell"]))

    def _extractPositions(self, scan):

        self.xPos, self.yPos, self.zPos = [], [], []
        self.xMeasured, self.yMeasured, self.zMeasured = [], [], []
        self.xstepsize = []
        self.ystepsize = []
        self.counts = []
        self.interp_counts = []

        for region in scan["scanRegions"].keys():
            self.xPos.append(np.linspace(scan["scanRegions"][region]["xStart"], \
                               scan["scanRegions"][region]["xStop"], \
                               scan["scanRegions"][region]["xPoints"]))
            self.yPos.append(np.linspace(scan["scanRegions"][region]["yStart"], \
                               scan["scanRegions"][region]["yStop"], \
                               scan["scanRegions"][region]["yPoints"]))
            self.zPos.append(np.linspace(scan["scanRegions"][region]["zStart"], \
                               scan["scanRegions"][region]["zStop"], \
                               scan["scanRegions"][region]["zPoints"]))
            self.xstepsize.append(scan["scanRegions"][region]["xStep"])
            self.ystepsize.append(scan["scanRegions"][region]["yStep"])

            #nPos are the number of positions commanded by the user
            #nPixels are the number of measurements made by the control system
            nxPos = self.xPos[-1].size
            nyPos = self.yPos[-1].size
            nzPos = self.zPos[-1].size
            nxPixels = nxPos * scan["oversampling_factor"] #we only oversample in one dimension
            nyPixels = nyPos
            nzPixels = nzPos
            nPixels_m = nxPixels * nyPixels * nzPixels #total number of measured pixels
            nPixels_r = nxPos * nyPos * nzPos #total number of requested pixels, shown for clarity

            self.xMeasured.append(np.zeros(nPixels_m))
            self.yMeasured.append(np.zeros(nPixels_m))
            self.zMeasured.append(np.zeros(nPixels_m))
            self.counts.append(np.zeros((self.energies.size,nPixels_m))) #this is a long vector of measured positions
            self.interp_counts.append(np.zeros((self.energies.size,nzPos,nyPos,nxPos))) #this is a matrix of requested positions
            
    def updateArrays(self,region,scanInfo):
        #doing things this way requires the scan driver to correctly provide the number of points for each line and image
        #but this is much much cleaner
        #self.counts should the long vector of (I,Z,Y,X) points whereas self.interp_counts will be (Z,Y,X) matrix
        #self.interp_counts does not need to be updated here because its shape doesn't depend on the calculated trajectories
        motorLength = scanInfo['numMotorPoints']
        DAQLength = scanInfo['numDAQPoints']
        self.counts[region] = np.zeros((self.energies.size,DAQLength))
        self.xMeasured[region] = np.zeros((self.energies.size,motorLength))
        self.yMeasured[region] = np.zeros((self.energies.size,motorLength))
        self.zMeasured[region] = np.zeros((self.energies.size,motorLength))
        self.saveRegion(region)

    def startOutput(self):
        """
        Adapted from Matthew Marcus version in pystxm....
        This is the routine which writes a Pixelator-style NXstxm file.  I have NOT
        tried it with anything but stacks - no linescans or point scans or...
        """
        print("Starting output of file %s" %self.file_name)
        self.NXfile = h5py.File(self.file_name,'w',libver='latest')
        n_scan_regions = len(self.xPos)
        if self.scan_dict["type"] == "Ptychography Image":
            for i in range(n_scan_regions):
                self.saveRegion(i)
        self.NXfile.swmr_mode = True
        
    def addDict(self,d,name):
        self.NXfile.create_dataset(name=name, data=json.dumps(d))

    def saveRegion(self,i, nt = None):
        if ('entry' + str(i)) in list(self.NXfile):
            self.updateEntry(i)
        else:
            self.createEntry(i)
            self.updateEntry(i)

    def updateEntry(self,i):

        #The 0 index for counts is for channels which isn't implemented yet
        self.NXfile['entry%i/instrument/detector/data' %i][...] = self.counts[i]
        self.NXfile['entry%i/data/data' %i][...] = self.interp_counts[i]
        self.NXfile['entry%i/instrument/detector/data' % i].flush()
        self.NXfile['entry%i/data/data' % i].flush()
        
    def addFrame(self,frame,framenum, mode="dark"):

        if mode == "dark":
            grp = self.NXfile['entry0/ccd0/dark']
        if mode == "exp":
            grp = self.NXfile['entry0/ccd0/exp']
        grp.create_dataset(name = str(framenum), data=frame, maxshape=None)

    def createEntry(self,i):

        ne,nz_m,ny_m,nx_m = len(self.energies),len(self.zMeasured[i]),len(self.yMeasured[i]),len(self.xMeasured[i])
        nz_r,ny_r,nx_r = len(self.zPos[i]), len(self.yPos[i]), len(self.xPos[i])

        #self.NXfile["entry%i" %i] = NXentry()
        nxentry = self.NXfile.create_group("entry%i" %i)
        nxentry.attrs["NX_class"] = "NXentry"
        start_time = nxentry.create_dataset("start_time", data=self.start_time)
        end_time = nxentry.create_dataset("end_time", data=self.end_time)
        title = nxentry.create_dataset("title", data=self.scan_dict["proposal"])
        definition = nxentry.create_dataset("definition", data=float(self.scan_dict["main_config"]["server"]["nx_file_version"]))
        experimenters = nxentry.create_dataset("experimenters", data=self.scan_dict["experimenters"])
        nxinstrument = nxentry.create_group("instrument")
        nxsource = nxinstrument.create_group("source")
        t = nxsource.create_dataset("type",data=self.scan_dict['main_config']['source']['type'])
        n = nxsource.create_dataset("name", data=self.scan_dict['main_config']['source']['name'])
        p = nxsource.create_dataset("probe", data=self.scan_dict['main_config']['source']['probe'])
        nxmono = nxinstrument.create_group("monochromator")
        energy = nxmono.create_dataset("energy",data=self.energies)
        nxdetector = nxinstrument.create_group("detector")
        measured_data = nxdetector.create_dataset("data",data=np.zeros_like(self.counts[i])) #the 0 is for channel, need to fix this
        measured_xgrp = nxinstrument.create_group("sample_x")
        measured_ygrp = nxinstrument.create_group("sample_y")
        measured_zgrp = nxinstrument.create_group("sample_z")
        measured_x = measured_xgrp.create_dataset("data",data=np.zeros(nx_m))
        measured_y = measured_ygrp.create_dataset("data", data=np.zeros(ny_m))
        measured_z = measured_zgrp.create_dataset("data", data=np.zeros(nz_m))
        motors = nxinstrument.create_group("motors")
        for motor in self.motorPositions.keys():
            try:
                motors.create_dataset(motor,data=self.motorPositions[motor])
            except:
                #there's a dictionary of status strings in there that causes this to fail
                pass
        sample = nxentry.create_group("sample")
        sample.create_dataset("rotation_angle", data='')
        sample.create_dataset("description", data=self.scan_dict["sample"])
        d = nxentry.create_group("data")
        d.create_dataset("stxm_scan_type",data=self.scan_dict["type"])
        d.create_dataset("data",data=np.zeros_like(self.interp_counts[i]))
        d.create_dataset("energy",data=self.energies)
        d.create_dataset("count_time",data=self.dwells)
        d.create_dataset("sample_z",data=self.zPos[i])
        d.create_dataset("sample_y",data=self.yPos[i])
        d.create_dataset("sample_x",data=self.xPos[i])
        d.create_dataset("motor_name_x",data=self.scan_dict["x"])
        try:
            d.create_dataset("motor_name_y",data=self.scan_dict["y"])
        except:
            d.create_dataset("motor_name_y", data="None")
        if self.scan_dict['type'] == "Ptychography Image":
            ccd = nxentry.create_group('ccd0')
            ccd.create_group('dark')
            ccd.create_group('exp')
        self.NXfile.flush()

    def save(self):
        self.startOutput()
        n_scan_regions = len(self.xPos)
        for i in range(n_scan_regions):
            self.saveRegion(i)
        self.closeFile()

    def closeFile(self):
        self.NXfile.close()

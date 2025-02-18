import numpy as np
import h5py, datetime,json

NXD_DEFAULT = 'default'
NXD_FILE_NAME = 'file_name'
NXD_FILE_TIME = 'file_time'
NXD_DATA = 'data'

def _string_attr(nxgrp, name, sdata):
    if (nxgrp is None):
        return
    nxgrp.attrs[name] = np.string_(sdata)


def _list_attr(nxgrp, name, lstdata):
    if (nxgrp is None):
        return
    if (name in list(nxgrp.attrs.keys())):
        nxgrp.attrs[name][()] = lstdata
    else:
        nxgrp.attrs[name] = lstdata

def _group(nxgrp, name, nxdata_type):
    if (name == ''):
        return
        
    grp = nxgrp.create_group(name)
    _string_attr(grp, np.string_('NX_class'), nxdata_type)
    return (grp)

def _dset_arb_attr(nxgrp, name, data, u,target=None):
    unit = np.string_(u)
    if (type(data) == np.ndarray):
        grp = nxgrp.create_dataset(name=name, data=data, maxshape=None, compression="gzip")
    else:
        grp = nxgrp.create_dataset(name=name, data=data, maxshape=None)
    _string_attr(grp,np.string_('units'),unit)
    if not (target is None):
	    _string_attr(grp,np.string_('target'),target)


def _dataset(nxgrp, name, data, nxdata_type, nx_units='NX_ANY', dset={}):
    '''
    apply compression if the data is an array
    '''
    # grp = nxgrp.create_dataset(name=name, data=data, maxshape=None)
    if (type(data) == np.ndarray):
        grp = nxgrp.create_dataset(name=name, data=data, maxshape=None, compression="gzip")
    else:
        grp = nxgrp.create_dataset(name=name, data=data, maxshape=None)
    _string_attr(grp, 'NX_class', nxdata_type)
    if (type(nx_units) is dict):
        _string_attr(grp, 'NX_units', nx_units['units'])
    else:
        _string_attr(grp, 'NX_units', nx_units)
    if ('doc' in list(dset.keys())):
        _string_attr(grp, 'doc', dset['doc'])
    return (grp)

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
            self.start_time = None
            self.stop_time = None
            self.angle = 0.
            self.polarization = 0.
            self.nScanRegions = len(self.scan_dict["scanRegions"].keys())
            self._scanRegions = self.scan_dict["scanRegions"].keys()
            self.channels = ["diode"]  #this should come through from the DAQ config somehow
            self.nChannels = len(self.channels)
            self.energies = self._extractEnergies(self.scan_dict)
            self.xPos, self.yPos, self.zPos, self.xMeasured, self.yMeasured, self.zMeasured = self._extractPositions(self.scan_dict)
            self.motorPositions = []
            for i in range(self.nScanRegions):
                self.motorPositions.append({})
            self._allocateArrays()
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

        ##THIS IS NOT WORKING BECAUSE "DATA" IS NOT DEFINED
        # if len(data)>len(distMeas):
        #     data = data[:len(distMeas)]
        #
        # elif len(distMeas)>len(data):
        #     distMeas = distMeas[:len(data)]

        ##TRY USING "RAWCOUNTS" INSTEAD
        if len(rawCounts) > len(distMeas):
            rawCounts = rawCounts[:len(distMeas)]

        elif len(distMeas) > len(rawCounts):
            distMeas = distMeas[:len(rawCounts)]

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
        try:
            f = h5py.File(stxm_file,'r', swmr = True)
        except:
            print("Failed to open file: %s" %stxm_file)
            return
        self.meta = {}
        self.meta["experimenters"] = f["entry0/experimenters"][()][0].decode()
        self.meta["sample_description"] = f["entry0/sample_description"][()][0].decode()
        self.meta["proposal"] = f["entry0/proposal"][()][0].decode()
        self.meta["start_time"] = f["entry0/start_time"][()][0].decode()
        self.meta["end_time"] = f["entry0/end_time"][()][0].decode()
        self.meta["scan_type"] = f["entry0/counter0/stxm_scan_type"][()][0].decode()
        self.nRegions = len(list(f))
        self.data = {}
        
        try:
            self.meta["version"] = f["entry0/definition"].attrs["version"].decode()
        except:
            #If no version is in the file, assign it to version 2.
            self.meta["version"] = 0
        if self.meta["version"] == '2':
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
                
                
        elif self.meta["version"] == '2.1':
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
        energies = np.array(())
        self.dwells = np.array(())
        for energyRegion in scan["energyRegions"].keys():
            start = scan["energyRegions"][energyRegion]["start"]
            stop = scan["energyRegions"][energyRegion]["stop"]
            nEnergies = scan["energyRegions"][energyRegion]["nEnergies"]
            energies = np.concatenate((energies,np.round(np.linspace(start, stop, nEnergies), 2)))
            self.dwells = np.concatenate((self.dwells,np.ones(nEnergies) * scan["energyRegions"][energyRegion]["dwell"]))
        return energies

    def _extractPositions(self, scan):
        xPos, yPos, zPos = [], [], []
        xMeasured, yMeasured, zMeasured = [], [], []
        for region in scan["scanRegions"].keys():
            xPos.append(np.linspace(scan["scanRegions"][region]["xStart"], \
                               scan["scanRegions"][region]["xStop"], \
                               scan["scanRegions"][region]["xPoints"]))
            yPos.append(np.linspace(scan["scanRegions"][region]["yStart"], \
                               scan["scanRegions"][region]["yStop"], \
                               scan["scanRegions"][region]["yPoints"]))
            zPos.append(np.linspace(scan["scanRegions"][region]["zStart"], \
                               scan["scanRegions"][region]["zStop"], \
                               scan["scanRegions"][region]["zPoints"]))

            if "Image" in self.scan_dict["type"]:
                #nPixels = xPos[-1].size * yPos[-1].size * scan["oversampling_factor"]
                nPixels = xPos[-1].size * yPos[-1].size * scan["oversampling_factor"]
            elif "Focus" in self.scan_dict["type"]:
                nPixels = xPos[-1].size * zPos[-1].size * scan["oversampling_factor"]
            elif "Line Spectrum" in self.scan_dict["type"]:
                nPixels = xPos[-1].size * scan["oversampling_factor"]
            xMeasured.append(np.zeros((self.energies.size,nPixels)))
            yMeasured.append(np.zeros((self.energies.size,nPixels)))
            zMeasured.append(np.zeros((self.energies.size,nPixels)))
        return xPos, yPos, zPos, xMeasured, yMeasured, zMeasured

    def _allocateArrays(self):
        #Modified to include interpolated data. Right now that is not actually saved here, but is updated by the GUI.
        self.counts = []
        self.interp_counts = []
        #print(self.scan_dict["nPoints"])
        for i in range(self.nScanRegions):
            data = []
            interp_data = []
            if "Image" in self.scan_dict["type"]:
                #nPixels = self.xPos[i].size * self.yPos[i].size * self.scan_dict["oversampling_factor"]
                if self.scan_dict["type"] == "Ptychography Image":
                    nPixels = self.xPos[i].size * self.yPos[i].size * self.scan_dict["oversampling_factor"]
                else:
                    
                    nPixels = self.xMeasured[i].size
                nInterpPixels = self.xPos[i].size * self.yPos[i].size
            elif "Focus" in self.scan_dict["type"]:
                #nPixels = self.xPos[i].size * self.zPos[i].size * self.scan_dict["oversampling_factor"]
                nPixels = self.xMeasured[i].size
                nInterpPixels = self.xPos[i].size * self.zPos[i].size
            elif "Line Spectrum" in self.scan_dict["type"]:
                #nPixels = self.xPos[i].size * self.scan_dict["oversampling_factor"]
                nPixels = self.xMeasured[i].size
                nInterpPixels = self.xPos[i].size
            for channel in self.channels:
                data.append(np.zeros((self.energies.size,nPixels)))
                interp_data.append(np.zeros((self.energies.size,nInterpPixels)))
            self.counts.append(data)
            self.interp_counts.append(interp_data)


        if self.scan_dict["type"] == "Ptychography Image":
            self.ccd_frames = []
            self.acquired_ccd_frames = []
            self.dark_ccd_frames = []
            self.acquired_dark_ccd_frames = []
            
    def updateArrays(self,region,npoints):
    
        if "Image" in self.scan_dict["type"]:
            for i, channel in enumerate(self.channels):
                self.counts[region][i] = np.zeros((self.energies.size,npoints*self.yPos[region].size))
                self.xMeasured[region] = np.zeros((self.energies.size,npoints*self.yPos[region].size))
                self.yMeasured[region] = np.zeros((self.energies.size,npoints*self.yPos[region].size))
                self.zMeasured[region] = np.zeros((self.energies.size,npoints*self.yPos[region].size))
            
        elif "Focus" in self.scan_dict["type"]:
            for i,channel in enumerate(self.channels):
                self.counts[region][i] = np.zeros((self.energies.size,npoints*self.zPos[region].size))
                self.xMeasured[region] = np.zeros((self.energies.size,npoints*self.zPos[region].size))
                self.yMeasured[region] = np.zeros((self.energies.size,npoints*self.zPos[region].size))
                self.zMeasured[region] = np.zeros((self.energies.size,npoints*self.zPos[region].size))
                
        elif "Line" in self.scan_dict["type"]:
            for i,channel in enumerate(self.channels):
                self.counts[region][i] = np.zeros((self.energies.size,npoints))
                self.xMeasured[region] = np.zeros((self.energies.size,npoints))
                self.yMeasured[region] = np.zeros((self.energies.size,npoints))
                self.zMeasured[region] = np.zeros((self.energies.size,npoints))
        
        
        self.createEntry(region)
            

    def startOutput(self):
        """
        Adapted from Matthew Marcus version in pystxm....
        This is the routine which writes a Pixelator-style NXstxm file.  I have NOT
        tried it with anything but stacks - no linescans or point scans or...
        """

        self.NXfile = h5py.File(self.file_name,'w',libver='latest')
        n_scan_regions = len(self.xPos)
        if self.scan_dict["type"] == "Ptychography Image":
            for i in range(n_scan_regions):
                self.saveRegion(i)
        self.NXfile.swmr_mode = True
        
    def addDict(self,d,name):
        self.NXfile.create_dataset(name=name, data=np.string_(json.dumps(d)), maxshape=None)

    def saveRegion(self,i):
        if ('entry' + str(i)) in list(self.NXfile):
            self.updateEntry(i)
        else:
            self.createEntry(i)
            self.updateEntry(i)

    def updateEntry(self,i):
        grp = self.NXfile['entry' + str(i)]
        self.end_time = str(datetime.datetime.now())
        et = grp['end_time']
        et[...] = np.string_(self.end_time)
        et.flush()
        
        #Kind of a kludge, but this is adjusted for oversampling.
        if self.scan_dict["type"] == "Line Spectrum":
            newshape = (self.energies.size, 1, len(self.xMeasured[i][0]))
            procshape = (self.energies.size, 1, len(self.xPos[i]))
        elif "Image" in self.scan_dict["type"]:
            newshape = (self.energies.size, len(self.yPos[i]), int(len(self.xMeasured[i][0])/len(self.yPos[i])))
            procshape = (self.energies.size, len(self.yPos[i]), len(self.xPos[i]))
        elif "Focus" in self.scan_dict["type"]:
            newshape = (self.energies.size, len(self.zPos[i]), int(len(self.xMeasured[i][0])/len(self.zPos[i])))
            procshape = (self.energies.size, len(self.zPos[i]), len(self.xPos[i]))
            
        Counts = np.reshape(self.counts[i][0], newshape)
        data = grp['counter0/data']
        data[...] = Counts
        data.flush()
        rebinData = grp['binned_values/data']
        rebinData[...] = np.reshape(self.interp_counts[i][0], procshape)
        sample_x = grp['counter0/sample_x']
        sample_x[...] = np.reshape(self.xMeasured[i], newshape)
        sample_x.flush()
        sample_y = grp['counter0/sample_y']
        sample_y[...] = np.reshape(self.yMeasured[i], newshape)
        sample_y.flush()
        
        motor_grp = self.NXfile['entry' + str(i)+'/motors']
        for key in self.motorPositions[i].keys():
            if key != "status":
                if key in motor_grp:
                    data = motor_grp[key]
                    data[...] = self.motorPositions[i][key]
                    data.flush()
                else:
                    motor_grp.create_dataset(key, data=self.motorPositions[i][key])
        
    def addFrame(self,frame,framenum, mode="dark"):

        if mode == "dark":
            grp = self.NXfile['entry0/ccd0/dark']
        if mode == "exp":
            grp = self.NXfile['entry0/ccd0/exp']
        grp.create_dataset(name = str(framenum), data=frame, maxshape=None)
        

                        
    def createEntry(self,i):


        print("Creating Entry")
        #This includes f
        NXdata = np.string_('NXdata')
        NXmonitor = np.string_('NXmonitor')
        NXdetector = np.string_('NXdetector')
        NXinstrument = np.string_('NXinstrument')
        nxFileVersion = np.string_(self.scan_dict['nxFileVersion'])
        Title = np.string_(self.scan_dict['proposal'])
        Experimenters = np.string_(self.scan_dict['experimenters'])
        Sample = np.string_(self.scan_dict['sample'])
        ScanType = [np.string_(self.scan_dict['type'])]
        StartTime = np.string_(self.start_time)
        EndTime = StartTime
        motorPositions = self.motorPositions[i]
        #REDONE FOR WAVEFORM
        # x = self.xPos[i]
        # y = self.yPos[i]
        # z = self.zPos[i]
        # yPixels, xPixels, zPixels = len(y), len(x), len(z)
        # e = self.energies
        # nz = len(z)
        # nx = len(x)
        # ny = len(y)
        # ne = len(e)
        # if self.scan_dict['type'] == "Line Spectrum":
        #     yPixels = 1
        #     ny = 1
        
        # if "Focus" in self.scan_dict['type']:
        #     nx = nz
        #     xPixels = zPixels
        #     x = z
        # else:
        #     pass

        Stime = StartTime
        Etime = EndTime
        e = self.energies
        ne = len(e)
        #Measured Values, have the same dimension as the whole scan.
        x = self.xMeasured[i]
        y = self.yMeasured[i]
        z = self.zMeasured[i]
        #print(x.shape)
        #Requested Values, are used for interpolation/rebinning.
        xReq = self.xPos[i]
        yReq = self.yPos[i]
        zReq = self.zPos[i]
        
        
        
        #TODO: Write this in a way where this doesn't matter.
        #I don't buy that this works for focus scans.
        if "Image" in self.scan_dict["type"]:
            nx = int(len(x[0])/len(yReq))
            ny = len(self.yPos[i])
            nz = len(self.zPos[i])
            npx = len(self.xPos[i])
            dataShape = (ne, ny, nx)
            processedDataShape = (ne, ny, npx)
        elif "Focus" in self.scan_dict["type"]:
            nx = int(len(x[0])/len(zReq))
            ny = 1
            nz = len(self.zPos[i])
            npx = len(self.xPos[i])
            dataShape = (1, nz, nx)
            processedDataShape = (1, nz, npx)
        elif "Line Spectrum" in self.scan_dict["type"]:
            nx = len(x[0])
            ny = 1
            nz = len(self.zPos[i])
            npx = len(self.xPos[i])
            dataShape = (ne, 1, nx)
            processedDataShape = (ne, 1, npx)
            
        npt = np.prod(dataShape)
        Counts = np.reshape(self.counts[i][0], dataShape)  # 0 for channel number which isn't implemented yet
        processedCounts = np.reshape(self.interp_counts[i][0], processedDataShape)
        x = np.reshape(x, dataShape)
        y = np.reshape(y, dataShape)
        z = np.reshape(z, dataShape)
        Dwells = self.dwells
        Current = np.zeros((ne))
        Stime = StartTime
        Etime = EndTime
        E3D = [np.full((dataShape[1], dataShape[2]), e[ie]) for ie in range(ne)]
        E_unroll = np.reshape(E3D, npt)
        T_unroll = np.reshape([np.full((dataShape[1], dataShape[2]), Dwells[ie]) for ie in range(ne)], npt)
        Cu3D = [np.full((dataShape[1], dataShape[2]), Current[ie]) for ie in range(ne)]
        Cu_unroll = np.reshape(Cu3D, npt)
        X_unroll = x.flatten()
        Y_unroll = y.flatten()
        C_unroll = Counts.flatten()




        #
        #	The entry1 group and the first-level data.  The time strings probably need to be in a standard format
        #

        entry_nxgrp = _group(self.NXfile, 'entry' + str(i), np.string_(b'NXentry'))
        ds = entry_nxgrp.create_dataset(name='definition', data=np.string_('NXstxm'), maxshape=None)
        ds.attrs["version"] = nxFileVersion
        entry_nxgrp.create_dataset(name='title', data=Title, maxshape=None)
        entry_nxgrp.create_dataset(name='start_time', data=[Stime], maxshape=None)
        entry_nxgrp.create_dataset(name='end_time', data=[Etime], maxshape=None)
        entry_nxgrp.create_dataset(name='proposal', data=[Title], maxshape=None)
        entry_nxgrp.create_dataset(name='experimenters', data=[Experimenters], maxshape=None)
        entry_nxgrp.create_dataset(name='sample_description', data=[Sample], maxshape=None)
        motor_grp = _group(entry_nxgrp, 'motors', NXmonitor)

        #
        #	The control group
        #
        control_nxgrp = _group(entry_nxgrp, 'control', NXmonitor)
        _list_attr(control_nxgrp, 'axes', np.string_(['energy', 'sample_y', 'sample_x']))  # Attributes of entry1/control
        _list_attr(control_nxgrp, 'energy_indices', [0])
        _list_attr(control_nxgrp, 'sample_x_indices', [2])
        _list_attr(control_nxgrp, 'sample_y_indices', [1])
        _list_attr(control_nxgrp, 'signal', np.string_(['data']))

        #		The datasets under control
        _dset_arb_attr(control_nxgrp, 'data', Cu3D, 'mA')
        _dset_arb_attr(control_nxgrp, 'energy', e, 'eV', '/entry1/counter0/energy')
        _dset_arb_attr(control_nxgrp, 'sample_x', x, 'um', '/entry1/counter0/sample_x')
        _dset_arb_attr(control_nxgrp, 'sample_y', y, 'um', '/entry1/counter0/sample_y')
        _dset_arb_attr(control_nxgrp, 'sample_z', z, 'um', '/entry1/counter0/sample_z')
        #
        #	entry1/counter0 group, with attributes
        #
        c0_nxgrp = _group(entry_nxgrp, 'counter0', NXdata)
        _list_attr(c0_nxgrp, 'axes', np.string_(['energy', 'sample_y', 'sample_x']))
        _list_attr(c0_nxgrp, 'energy_indices', [0])
        _list_attr(c0_nxgrp, 'sample_x_indices', [2])
        _list_attr(c0_nxgrp, 'sample_y_indices', [1])
        _list_attr(c0_nxgrp, 'signal', np.string_(['data']))

        #		The datasets under entry1/counter0
        _dset_arb_attr(c0_nxgrp, 'data', Counts, '')
        _dset_arb_attr(c0_nxgrp, 'count_time', Dwells, 's')
        _dset_arb_attr(c0_nxgrp, 'energy', e, 'eV', '/entry1/counter0/energy')
        _dset_arb_attr(c0_nxgrp, 'sample_x', x, 'um', '/entry1/counter0/sample_x')
        _dset_arb_attr(c0_nxgrp, 'sample_y', y, 'um', '/entry1/counter0/sample_y')
        _dset_arb_attr(c0_nxgrp, 'sample_z', z, 'um', '/entry1/counter0/sample_z')
        c0_nxgrp.create_dataset(name='stxm_scan_type', data=ScanType, maxshape=None)

        if self.scan_dict['type'] == "Ptychography Image":
            ccd0_nxgrp = _group(entry_nxgrp, 'ccd0', NXdata)
            dark_nxgrp = _group(ccd0_nxgrp, 'dark', NXdata)
            exp_nxgrp = _group(ccd0_nxgrp, 'exp', NXdata)
            #ne = 2 - int(not(self.scan_dict["doubleExposure"]))
            #ccd0_nxgrp.create_dataset(name='dark', data=np.zeros((25*ne,1040,1152)), maxshape=(None,1040,1152))
            #ccd0_nxgrp.create_dataset(name='exp', data=np.zeros((nx*ny*ne,1040,1152)), maxshape=(None,1040,1152))
            #dark_nxgrp = _group(ccd0_nxgrp, 'dark', NXdata)
            #exp_nxgrp = _group(ccd0_nxgrp, 'exp', NXdata)
            #		The datasets under entry1/counter0
            #_dset_arb_attr(c0_nxgrp, 'ccdframes', np.array(self.ccd_frames), '')
            #_dset_arb_attr(c0_nxgrp, 'darkccdframes', np.array(self.dark_ccd_frames), '')

        #
        #	entry1/energy group, with attributes
        #
        e_nxgrp = _group(entry_nxgrp, 'energy', NXmonitor)
        _list_attr(e_nxgrp, 'axes', np.string_(['energy', 'sample_y', 'sample_x']))
        _list_attr(e_nxgrp, 'energy_indices', [0])
        _list_attr(e_nxgrp, 'sample_x_indices', [2])
        _list_attr(e_nxgrp, 'sample_y_indices', [1])
        _list_attr(e_nxgrp, 'signal', np.string_(['data']))
        #		The datasets under entry1/energy
        _dset_arb_attr(e_nxgrp, 'data', E3D, 'eV')
        _dset_arb_attr(e_nxgrp, 'energy', e, 'eV', 'entry1/counter0/energy')
        _dset_arb_attr(e_nxgrp, 'sample_x', x, 'um', 'entry1/counter0/sample_x')
        _dset_arb_attr(e_nxgrp, 'sample_y', y, 'um', 'entry1/counter0/sample_y')
        _dset_arb_attr(e_nxgrp, 'sample_z', z, 'um', 'entry1/counter0/sample_z')
        #
        #	entry1/instrument group
        #
        inst_nxgrp = _group(entry_nxgrp, 'instrument', NXinstrument)
        #		entry1/instrument/control group
        in_con_nxgrp = _group(inst_nxgrp, 'control', NXdetector)
        _dset_arb_attr(in_con_nxgrp, 'count_time', T_unroll, 's', '/entry1/instrument/counter0/count_time')
        _dset_arb_attr(in_con_nxgrp, 'data', Cu_unroll, 'mA')
        #		entry1/instrument/counter0 group
        c0_con_nxgrp = _group(inst_nxgrp, 'counter0', NXdetector)
        _dset_arb_attr(c0_con_nxgrp, 'count_time', T_unroll, 's', '/entry1/instrument/counter0/count_time')
        _dset_arb_attr(c0_con_nxgrp, 'data', Cu_unroll, 'mA')  # Ring current monitor
        #		entry1/instrument/energy group
        e_con_nxgrp = _group(inst_nxgrp, 'energy', NXdetector)
        _dset_arb_attr(e_con_nxgrp, 'count_time', T_unroll, 's', '/entry1/instrument/counter0/count_time')
        _dset_arb_attr(e_con_nxgrp, 'data', E_unroll, 'eV')
        #		entry1/instrument/sample_x group
        sx_inst_nxgrp = _group(inst_nxgrp, 'sample_x', NXdetector)
        _dset_arb_attr(sx_inst_nxgrp, 'count_time', T_unroll, 's', '/entry1/instrument/counter0/count_time')
        _dset_arb_attr(sx_inst_nxgrp, 'data', X_unroll, 'um')
        _dset_arb_attr(sx_inst_nxgrp, 'data_detail', np.stack([X_unroll, T_unroll], axis=1), '')
        #		entry1/instrument/sample_y group
        sx_inst_nxgrp = _group(inst_nxgrp, 'sample_y', NXdetector)
        _dset_arb_attr(sx_inst_nxgrp, 'count_time', T_unroll, 's', '/entry1/instrument/counter0/count_time')
        _dset_arb_attr(sx_inst_nxgrp, 'data', Y_unroll, 'um')
        _dset_arb_attr(sx_inst_nxgrp, 'data_detail', np.stack([Y_unroll, T_unroll], axis=1), '')
        #		entry1/instrument/source group
        src_inst_nxgrp = _group(inst_nxgrp, 'source', NXdetector)
        _dset_arb_attr(src_inst_nxgrp, 'current', Cu_unroll[0], 'mA')
        src_inst_nxgrp.create_dataset(name='name', data=b'ALS', maxshape=None)
        src_inst_nxgrp.create_dataset(name='probe', data=b'X-ray', maxshape=None)
        src_inst_nxgrp.create_dataset(name='type', data=b'Synchrotron X-ray Source', maxshape=None)
        #		entry1/instrument/time_detector group
        td_inst_nxgrp = _group(inst_nxgrp, 'time_detector', NXdetector)
        _dset_arb_attr(td_inst_nxgrp, 'count_time', T_unroll, 's', '/entry1/instrument/counter0/count_time')
        _dset_arb_attr(td_inst_nxgrp, 'data', C_unroll, '')
        #
        #	entry1/sample group
        #
        samp_nxgrp = _group(entry_nxgrp, 'sample', np.string_('NXsample'))
        _dataset(samp_nxgrp, 'rotation_angle', self.angle, np.string_('NX_FLOAT'), nx_units='deg')
        _dataset(samp_nxgrp, 'start_position', 0., np.string_('NX_FLOAT'), nx_units='um')
        
        #   entry1/request group
        req_nxgrp = _group(entry_nxgrp, 'binned_values', NXdetector)
        _dset_arb_attr(req_nxgrp,'data',processedCounts,'um')
        _dset_arb_attr(req_nxgrp,'sample_x',xReq,'um')
        _dset_arb_attr(req_nxgrp,'sample_y',yReq,'um')
        _dset_arb_attr(req_nxgrp,'sample_z',zReq,'um')

    def save(self):
        self.startOutput()
        n_scan_regions = len(self.xPos)
        for i in range(n_scan_regions):
            self.saveRegion(i)
        self.closeFile()

    def closeFile(self):
        self.NXfile.close()


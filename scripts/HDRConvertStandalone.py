#from pystxm_core.io.writeNX import *
import os
import numpy as np
import glob
import argparse
import h5py
from skimage.restoration import unwrap_phase
from errno import ENOENT
from scipy.io import loadmat
import scipy
# Does not work with mat files 07/25/25
# We have to import this specific function. Probably because it is not meant to be used really.
from skimage.registration._phase_cross_correlation import _upsampled_dft

__author__ = 'work'

# Default parameters
class Param(object):
    def __init__(self):
        self.param = {}
        self.param["process"] = '1' ##set 1 to pre-process the data
        self.param["reconstruct"] = '1' ##set 1 to perform the reconstruction
        self.param["removeOutliers"] = '1' ##set 1 to remove outlier diffraction patterns
        self.param["lowPassFilter"] = '1' ##set 1 to low pass filter the data
        self.param["file_prefix"] = '' ##prefix used in the the file names before auto-increment
        self.param["dataPath"] = '' ##path to the auto-incremented directory tree
        self.param["dataFile"] = '' ##CXI file to use if not using auto-incremented tree
        self.param["saveFile"] = '0'
        self.param["speFile"] = '' ##SPE file to use if not using auto-incremented tree
        self.param["scanDate"] = '' ##scan date
        self.param["scanNumber"] = '' ##scan number
        self.param["scanID"] = '' ##scan ID
        self.param["scanDir"] = ''
        self.param["fileName"] = ''
        self.param["outputFilename"] = ''
        self.param["bgScanDate"] = ''
        self.param["bgScanNumber"] = ''
        self.param["bgScanID"] = ''
        self.param["interferometer"] = '1' ##set to 1 to use interferometer positions
        self.param["xaxis"] = 'b' ##file code for x axis interferometer data
        self.param["yaxis"] = 'c' ##file code for y axis interferometer data
        self.param["xaxisNo"] = '0' ##file code for x axis interferometer data
        self.param["yaxisNo"] = '0' ##file code for y axis interferometer data
        self.param["pixnm"] = '7' ##requested pixel size in nm
        self.param["sh_sample_y"] = '256' ##final resampled grid size
        self.param["sh_sample_x"] = '256' ##final resampled grid size
        self.param["filter_width"] = '200' ##pixel width of the autocorrelation filter
        self.param['probeThreshold'] = '0.01' ##threshold to use for calculating probe from STXM brightfield
        self.param["ssx"] = '50' ##step size in the x dimension in nm
        self.param["ssy"] = '50' ##step size in the y dimension in nm
        self.param["ssn"] = '10' #number of pixels per scan step
        self.param["xpts"] = '20' ##number of scan points in the x dimension
        self.param["ypts"] = '20' ##number of scan points in the y dimension
        self.param["zd"] = '240' ##zone plate diameter in microns
        self.param["dr"] = '60' ##zone plate outer zone width
        self.param["e"] = '750' ##x-ray energy
        self.param["ccdp"] = '30' ##ccd pixel size in microns
        self.param["ccdz"] = '84.55' ##ccd distance from sample in mm
        self.param["nexp"] = '1' ##number of exposure times per point
        self.param["nl"] = '0.1' ##final lower threshold on the data
        self.param["xcenter"] = '' ##center x pixel in the raw data
        self.param["ycenter"] = '' ##center y pixel in the raw data
        self.param["t_long"] = '0' ##long exposure time
        self.param["t_short"] = '0' ##short exposure time
        self.param["s_threshold"] = '1000' ##upper threshold on saturated pixels
        self.param["nProcesses"] = '48' ##number of pre-processing processes to launch
        self.param["bl"] = 'ns' ##beamline tag                    p = Param()
        self.param["cxi"] = '1' ##set 1 to output to CXI file
        self.param["gpu"] = '1' ##set 1 to use the GPU
        self.param["nIterations"] = '500' ##number of iterations
        self.param["probeMask"] = '1' ##set 1 to use a fourier mask on the probe
        self.param["algorithm"] = 'raar' ##algorithm tag
        self.param["pR"] = '1' ##set 1 to use probe retrieval
        self.param["bR"] = '1' ##set 1 to use background retrieval
        self.param["useStxm"] = '0' ##set 1 to start from the STXM image
        self.param["version"] = '2' ##set 2
        self.param['bg_filename'] = '' ##SPE file with background data if not using auto-increment
        self.param['zpw'] = '100' ##width of the STXM brightfield annulus in pixel units in Fourier space
        self.param['short_filename'] = '0' ##SPE file with short exposures if recorded separately
        self.param['fCCD']='1' ##set 1 if using the fast CCD
        self.param['Year'] = ''
        self.param['Month'] = ''
        self.param['Day'] = ''
        self.param['Scientist'] = ''
        self.param['Sample'] = ''
        self.param['Comment1'] = ''
        self.param['Comment2'] = ''
        self.param['Id'] = ''
        self.param['beamstop'] = '5' ##thickness: 5,10,20
        self.param['useBeamstop'] = '0'
        self.param['processGPU'] = '0' ##set 1 to pre-process on the GPU
        self.param['fv'] = '0' ##set 1 to flip data vertically
        self.param['fh'] = '0' ##set 1 to flip data horizontally
        self.param['transpose'] = '0' ##set 1 to transpose the data
        self.param['sim'] = '0' ##set 1 if this is a simulation
        self.param['usePrevious'] = '0' ##set 1 to start from a previous reconstruction
        self.param['removePhasePlane'] = '1'
        self.param['beta'] = '0.5' #RAAR paramter: 0.5-1.0
        self.param["eta"] = '0.5' ##eta for background retrieval
        self.param['illuminationPeriod'] = '1' #Refine illumination every few iterations
        self.param['backgroundPeriod'] = '1'
        self.param['relaxedFourier'] = '0' #Relaxed Fourier Modulus constraints
        self.param['illuminationIntensities'] = '0' #Enforce illumination Fourier intensities
        self.param['illuminationMask'] = '1' #Enfornce mask on illumination intensities
        self.param['sh_crop'] = '960' #sub-matrix to use of the full fCCD RAW data
        self.param['paramFileName'] = '0'
        self.param['debug'] = '0'
        self.param['fCCD_version'] = '1' #1 for old and 2 for new
        self.param['loopSize'] = '10'
        self.param['nBlocks'] = '4'
        self.param['nGPU'] = '8'
        self.param['nCPU'] = '48'
        self.param['useCluster'] = '0'
        self.param['low_pass'] = '0' #switch to low pass the image because of strong scattering
        self.param['prtf'] = '0'
        self.param['beamStopTransmission'] = '0.015'
        self.param['itnGlobal'] = '0'
        self.param['logFile'] = 'ptychoLog.txt'
        self.param['finalError'] = '0'
        self.param['defocus'] = '0'
        self.param['iModes'] = '1'
        self.param['oModes'] = '1'
        self.param['probeFile'] = ''
        self.param['illuminationIntensitiesFile'] = ''
        self.param['beamstopXshift'] = '-3'
        self.param['beamstopYshift'] = '-5'
        self.param['hostfile'] = '/global/groups/cosmic/host_file'
        self.param['nNodes'] = '4'
        self.param['cpuPerNode'] = '8'
        self.param['gpuPerNode'] = '2'
        self.param['repetition'] = '1'
        self.param['nl_filter'] = '0'


# Method for obtaining a CXI STXM or mat file from a scan number (including energy and region)
def getCXIPath(data_path: str, scan : str, energy : int , region : int , stxm : bool = False, mat: bool = False):
    """
    Build the expected cxi path or stxm path from the scan id
    :param data_path: The top-level directory that contains the data. 
      Folder and file structure is expected to be data_path/YYYY/MM/YYMMDD/NS_YYMMDDNNN*
    :param scan: The scan id, expected to to be YYMMDDNNN where NNN is the scan number
    :param energy: Energy integer for the file (ignored if stxm is True)
    :param region: Region integer for the file (ignored if stxm is True)
    :param stxm: Optional boolean if a stxm_file is being loaded

    """
    scan = f"{scan}_{energy}_{region}"
    yr = scan[0:2]
    mo = scan[2:4]
    dy = scan[4:6]
    no = scan[6:9]
    nn = scan.split('_')[-2]
    nn2 = scan.split('_')[-1]
    
    stxmStr = 'NS_'+yr+mo+dy+no+'.stxm'
    cxiStr = stxmStr.replace('.stxm','_ccdframes_'+nn+'_'+nn2+'.cxi')
    matStr = cxiStr.replace('.cxi','_full.mat')
    
    if stxm:
        file_path = os.path.join(data_path,'20'+yr,mo,yr+mo+dy,stxmStr)
    elif mat:
        file_path = os.path.join(data_path,'20'+yr,mo,yr+mo+dy,matStr)
    else:
       file_path = os.path.join(data_path,'20'+yr,mo,yr+mo+dy,cxiStr)
    if os.path.isfile(file_path):
        return file_path
    else:
        raise ValueError(f"Could not find {file_path}")

class cxi(object):

    def __init__(self, cxiFile = None, loaddiff = True):

        self.beamline = 'COSMIC'
        self.facility = 'ALS'
        self.energy = 1000
        self.ccddata = 0
        self.probe = 0
        self.imageProbe = 0
        self.probemask = 0 ##Fourier mask
        self.probeRmask = 0 ##Real space mask
        self.illuminationIntensities = 0
        self.datamean = 0
        self.stxm = 0
        self.stxmInterp = 0
        self.xpixelsize = 0
        self.ypixelsize = 0
        self.translation = 0
        self.image = 0
        self.startImage = 0
        self.bg = 0
        self.beamstop = 0
        self.corner_x = 0
        self.corner_y = 0
        self.corner_z = 0
        self.process = 0
        self.time = 0
        self.indices = 0
        self.goodFrames = 0
        self.corner = 0
        self.indices = 0
        self.error = 0
        self.__delta = 0.0001

        if cxiFile == None:
            self.process = Param().param
        else:
            # try: f = h5py.File(cxiFile,'r')
            # except IOError:
            #     print("readCXI Error: no such file or directory")
            #     #return
            if not os.path.isfile(cxiFile):
                raise IOError(ENOENT, 'No such file', cxiFile)
            else:
                f = h5py.File(cxiFile,'r')
                print("Loading file contents...")
                try: self.beamline = f['entry_1/instrument_1/name'][()]
                except KeyError: self.beamline = None
                try: self.facility = f['entry_1/instrument_1/source_1/name'][()]
                except KeyError: self.facility = None
                try: self.energy = f['entry_1/instrument_1/source_1/energy'][()]
                except KeyError: self.energy = None
                if loaddiff:
                    try: self.ccddata = f['/entry_1/instrument_1/detector_1/data'][()]
                    except KeyError:
                        print("Could not locate CCD data!")
                        self.ccddata = None
                else: self.ccddata = None
                # try: self.imageProbe = f['entry_1/instrument_1/image_1/probe'][()]
                # except KeyError: self.imageProbe = None
                try: self.probemask = f['entry_1/instrument_1/detector_1/Probe Mask'][()]
                except:
                    try: self.probemask = f['entry_1/instrument_1/detector_1/probe_mask'][()]
                    except KeyError: self.probemask = None
                try: self.probeRmask = f['entry_1/instrument_1/detector_1/probe_Rmask'][()]
                except KeyError: self.probeRmask = None
                try: self.datamean = f['entry_1/instrument_1/detector_1/Data Average'][()]
                except KeyError: self.datamean = None
                try: self.stxm = f['entry_1/instrument_1/detector_1/STXM'][()]
                except KeyError: self.stxm = None
                try: self.stxmInterp = f['entry_1/instrument_1/detector_1/STXMInterp'][()]
                except KeyError: self.stxmInterp = None
                try: self.ccddistance = f['entry_1/instrument_1/detector_1/distance'][()]
                except KeyError: self.ccddistance = None
                try: self.xpixelsize = f['entry_1/instrument_1/detector_1/x_pixel_size'][()]
                except KeyError: self.xpixelsize = None
                try: self.ypixelsize = f['entry_1/instrument_1/detector_1/y_pixel_size'][()]
                except KeyError: self.ypixelsize = None
                try: self.translation = f['entry_1/instrument_1/detector_1/translation'][()]
                except KeyError: self.translation = None
                try: self.illuminationIntensities = f['entry_1/instrument_1/detector_1/illumination_intensities'][()]
                except KeyError: self.illuminationIntensities = None


                entryList = [str(e) for e in list(f['entry_1'])]
                currentImageNumber = str(len([e for e in list(f['entry_1']) if 'image' in e and 'latest' not in e]))

                # if 'image_latest' in entryList:
                #     image_offset = 2
                # else: image_offset = 0
                # try: currentImageNumber = str(max(loc for loc, val in enumerate(entryList) if not(val.rfind('image'))) - image_offset)
                # except:
                if currentImageNumber == '0':
                    print("Could not locate ptychography image data.")
                    self.image = None
                    try: self.probe = f['entry_1/instrument_1/detector_1/probe'][()]
                    except KeyError: self.probe = None
                    self.imageProbe = self.probe
                    self.bg = None
                else:
                    print("Found %s images" %(int(currentImageNumber)))
                    self.image = []
                    for i in range(1,int(currentImageNumber) + 1):
                        print("loading image: %s" %(i))
                        try:
                            #self.image.append(f['entry_1/image_' + str(i) + '/data_' + str(i) + '/data'][()])
                            self.image.append(f['entry_1/image_'+str(i)+'/data'][()])
                        except:
                            pass
                    try: self.probe = f['entry_1/image_' + currentImageNumber + '/process_1/final_illumination'][()]
                    except: self.probe = None
                    # except:
                    #     try: self.imageProbe = f['entry_1/instrument_1/detector_1/probe'][()]
                    #     except KeyError:
                    #         try: self.imageProbe = f['entry_1/instrument_1/detector_1/Probe'][()]
                    #         except KeyError:
                    #             self.imageProbe = None
                    try: self.bg = f['entry_1/image_' + currentImageNumber + '/process_1/final_background'][()]
                    except: self.bg = None
                    #self.imageProbe = f['entry_1/image_1/process_1/final_illumination'][()]
                    #self.probe = self.imageProbe.copy()
                    
                
                try: self.dataProbe = f['entry_1/instrument_1/source_1/data_illumination'][()]
                except KeyError: self.dataProbe = None
                try: self.startImage = f['entry_1/image_1/startImage'][()]
                except KeyError: self.startImage = None
                try: self.beamstop = f['entry_1/instrument_1/detector_1/Beamstop'][()]
                except KeyError: self.beamstop = None
                try:
                    self.corner_x,self.corner_y,self.corner_z = f['/entry_1/instrument_1/detector_1/corner_position'][()]
                except:
                    try:
                        self.corner_z = f['entry_1/instrument_1/detector_1/distance'][()]
                        self.corner_y = f['entry_1/instrument_1/detector_1/y_pixel_size'][()] * self.probe.shape[0] / 2.
                        self.corner_x = f['entry_1/instrument_1/detector_1/x_pixel_size'][()] * self.probe.shape[1] / 2.
                    except:
                        self.corner_x,self.corner_y,self.corner_z = None, None, None

                self.process = Param().param
                if 'entry_1/process_1/Param' in f:
                    for item in list(f['entry_1/process_1/Param']):
                        self.process[str(item)] = str(f['/entry_1/process_1/Param/'+str(item)][()])
                try: self.time = f['entry_1/start_time'][()]
                except KeyError: self.time = None
                try: self.indices = f['entry_1/process_1/indices'][()]
                except KeyError: self.indices = None
                try: self.goodFrames = f['entry_1/process_1/good frames'][()]
                except KeyError: self.goodFrames = None
                # if 'entry_1/image_latest' in f:
                #     self.probe = f['entry_1/image_latest/process_1/final_illumination/'] #f['entry_1/image_1/probe'][()]
                if '/entry_1/instrument_1/detector_1/corner_position' in f:
                    self.corner = f['/entry_1/instrument_1/detector_1/corner_position'][()]
                else: self.corner = None
                f.close()

    def help(self):
        print("Usage: cxi = readCXI(fileName)")
        print("cxi.beamline = beamline name")
        print("cxi.facility = facility name")
        print("cxi.energy = energy in joules")
        print("cxi.ccddata = stack of diffraction data")
        print("cxi.probe = current probe")
        print("cxi.dataProbe = probe estimated from the data")
        print("cxi.imageProbe = probe calculated from the reconstruction")
        print("cxi.probemask = probe mask calculated from diffraction data")
        print("cxi.datamean = average diffraction pattern")
        print("cxi.stxm = STXM image calculated from diffraction data")
        print("cxi.stxmInterp = STXM image interpolated onto the reconstruction grid")
        print("cxi.xpixelsize = x pixel size in meters")
        print("cxi.ypixelsize = y pixel size in meters")
        print("cxi.translation = list of sample translations in meters")
        print("cxi.image = reconstructed image")
        print("cxi.bg = reconstructed background")
        print("cxi.process = parameter list used by the pre-processor")
        print("cxi.time = time of pre-processing")
        print("cxi.indices = array of STXM pixel coordinates for each dataset")
        print("cxi.goodFrames = boolean array indicating good frames")
        print("cxi.startImage = image which started the iteration")
        print("cxi.corner_x/y/z = positions of the CCD corner")

    def generateSTXM(self, hdr = None, pts = None, threshold = 0.1, mode = 'roi', roi=(-100,-1,0,50)):
        if hdr is not None:
            hdr = Read_header(hdr)
            ypts, xpts = hdr['Region1']['nypoints'], hdr['Region1']['nxpoints']
            if mode == 'full':
                iPoints = (self.ccddata * (self.ccddata > threshold)).sum(axis = (1,2))
            elif mode == 'brightfield':
                mask = self.datamean > 0.1 * self.datamean.max()
                iPoints = (self.ccddata * mask).sum(axis = (1,2))
            elif mode == 'darkfield':
                mask = self.datamean < 0.1 * self.datamean.max()
                iPoints = (self.ccddata * mask).sum(axis = (1,2))
            elif mode == 'roi':
                mask = np.zeros(self.ccddata[0].shape)
                mask[roi[0]:roi[1],roi[2]:roi[3]] = 1
                iPoints = (self.ccddata * mask).mean(axis = (1,2))
            self.stxm = np.reshape(iPoints,(ypts,xpts))[::-1,:]
        elif pts is not None:
            ypts, xpts = pts
            if mode == 'full':
                iPoints = (self.ccddata * (self.ccddata > threshold)).sum(axis = (1,2))
            elif mode == 'brightfield':
                mask = self.datamean > 0.1 * self.datamean.max()
                iPoints = (self.ccddata * mask).sum(axis = (1,2))
            elif mode == 'darkfield':
                mask = self.datamean < 0.1 * self.datamean.max()
                iPoints = (self.ccddata * mask).sum(axis = (1,2))
            self.stxm = np.reshape(iPoints,(ypts,xpts))[::-1,:]
        else:
            print("Please input a header file for the ptychography scan")

    def pixnm(self):

        l = (1239.852 / (self.energy / 1.602e-19)) * 1e-9
        NA = np.sqrt(self.corner_x**2 + self.corner_y**2) / np.sqrt(2.) / self.corner_z
        return np.round(l / 2. / NA * 1e9,2)

    def ev(self):
        return np.round(self.energy * 6.242e18,2)

    def removeOutliers(self, sigma = 3):

        nPoints = len(self.translation)
        indx = self.indices
        ny, nx = self.stxm.shape
        gy, gx = np.gradient(self.stxm)

        gy = self.stxm - sc.ndimage.filters.gaussian_filter(self.stxm, sigma = 0.25)
        gy = gy[::-1,:].flatten()  ##puts it in the same ordering as ccddata, starting lower left
        delta = 8. * gy.std()
        badIndices = np.where(gy < (gy.mean() - delta))[0] ##the min Y gradient is one row below the bad pixel

        self.stxm = self.stxm[::-1,:].flatten()
        k = 0
        if len(badIndices) > 0:
            for item in badIndices:
                self.stxm[item] = (self.stxm[item + 1] + self.stxm[item - 1]) / 2.
                if indx[item] > 0:
                    indx[item] = 0
                    indx[item+1:nPoints] = indx[item+1:nPoints] - 1
                else: indx[item] = 0
                self.translation = np.delete(self.translation, item - k, axis = 0)
                self.ccddata = np.delete(self.ccddata, item - k, axis = 0)
                k += 1
        self.stxm = np.reshape(self.stxm,(ny,nx))[::-1,:]
        print("Removed %i bad frames." %(len(badIndices)))

    def imageShape(self):

        ny, nx = self.ccddata[0].shape
        pixm = self.pixnm() / 1e9
        y,x = np.array((self.translation[:,1], self.translation[:,0]))
        y = (y / pixm).round() + ny / 2
        x = (x / pixm).round() + nx / 2
        pPosVec = np.column_stack((y,x))

        dx = pPosVec[:,1].max() - pPosVec[:,1].min() + 2
        dy = pPosVec[:,0].max() - pPosVec[:,0].min() + 2

        return np.int(dy + ny), np.int(dx + nx)

    def pixelTranslations(self):

        pixm = self.pixnm() / 1e9
        ny, nx = self.ccddata[0].shape
        y,x = np.array((self.translation[:,1], self.translation[:,0]))
        y = (y / pixm).round() + ny / 2
        x = (x / pixm).round() + nx / 2
        return np.column_stack((y,x))

    def dataShape(self):

        return self.ccddata.shape

    def illumination(self):

        """
        Public function which computes the overlap from a stack of probes.  This is equivalent to the total illumination profile
        Input: Stack translation indices and the probe
        Output: Illumination profile
        """
        #TODO: verify that this is correct for multimode
        # isum = np.zeros(self.oSum.shape)
        # for k in range(self.oModes):
        #     for i in range(self.__nFrames):
        #         j = self.__indices[i]
        #         isum[k,j[0]:j[1],j[2]:j[3]] = isum[k,j[0]:j[1],j[2]:j[3]] + np.reshape(abs(self.probe.sum(axis = 1)), (self.ny, self.nx))
        # return isum
        qnorm = np.abs(self.QPH(self.QP(np.ones(self.ccddata.shape, complex))))
        print(qnorm.sum())
        return self.QH(qnorm/qnorm[0].sum()) + self.__delta**2

    def QP(self, o):

        """
        Private function which multiplies the frames by the probe
        Input: stack of frames
        Output: stack of frames times the probe
        """

        return o * self.probe

    def QPH(self, o):

        """
        Private function which multiplies the frames by the conjugate probe.
        Input: stack of frames
        Output: stack of frames times the conjugate probe
        """

        return o * self.probe.conjugate()

    def QH(self, ovec):

        """
        Private function which computes the overlap from stack of frames.
        Input: Stack translation indices and the stack of frames
        Output: Total object image
        """
        self.ny, self.nx = self.probe.shape
        self.__indices = []
        i = 0
        for p in self.pixelTranslations():
            x1 = np.int(p[1] - self.nx / 2.)
            x2 = np.int(p[1] + self.nx / 2.)
            y1 = np.int(p[0] - self.ny / 2.)
            y2 = np.int(p[0] + self.ny / 2.)
            self.__indices.append((y1,y2,x1,x2))
            i += 1

        osum = np.zeros(self.imageShape())  ##this is 3D, (oModes, oSizeY, oSizeX)

        for i in range(len(self.ccddata)):
            j = self.__indices[i]
            ##sum the oVec over the probe modes and then insert into the oSum maintaining separation
            ##of the object modes
            osum[j[0]:j[1], j[2]:j[3]] = osum[j[0]:j[1], j[2]:j[3]] + ovec[i,:,:]

        return osum

    def getod(self):
        """optical density"""
        mod = np.abs(self.image[-1])
        mask = self.getmask()
        IO = (mod * mask)[mask > 0].mean()
        self.od = convert2OD(mod, IO)
        return self.od

    def getpc(self, removeRamp = False, order = 1):
        """phase contrast"""
        self.pc = unwrap_phase(-np.log(self.image[-1]).imag)

        if removeRamp:
            mask = self.getmask()
            x,y = np.arange(0, self.pc.shape[1]),np.arange(0,self.pc.shape[0])
            xp,yp = np.meshgrid(x,y)
            xm,ym,zm = xp[mask], yp[mask], self.pc[mask]
            m = polyfit2d(xm,ym,zm,order = order)
            bgFit = polyval2d(xp.astype('float64'),yp.astype('float64'),m)
            self.pc = self.pc + bgFit

        self.pc -= self.pc.min()
        return self.pc

    def getsc(self, removeRamp = False, order = 1):
        """scattering contrast - just an estimate since it only really works for isolated particles"""
        """Need a smooth open background"""
        print("Calculation scattering contrast")
        self.pc = unwrap_phase(-np.log(self.image[-1]).imag) #self.getpc(removeRamp = removeRamp, order = order)
        self.od = self.getod()
        self.sc = np.sqrt(self.od**2 + self.pc**2)
        return self.sc

    def getmask(self, sigma = 3):

        self.mask = getIOMask(sc.ndimage.filters.gaussian_filter(np.abs(self.image[-1]) / np.abs(self.image[-1]).max(), sigma = sigma))
        return self.mask

def readCXI(cxiFile, loaddiff = False):

    cxiObj = cxi(cxiFile, loaddiff = loaddiff)

    return cxiObj

class stxm:

    def __init__(self, stxm_file = None):
        self.readNexus(stxm_file)
        
    def readNexus(self, stxm_file):
        try:
            f = h5py.File(stxm_file,'r', swmr = True)
            self.NXfile = f
        except:
            print("Failed to open file: %s" %stxm_file)
            return
        self.meta = {}
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
        self.nRegions = len(list(f))
        self.data = {}
        
        try:
            self.meta["version"] = f["entry0/definition"].attrs["version"].decode()
        except:
            #If no version is in the file, assign it to version 0.
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
                ##this ignores all daqs but default
                self.data[entryStr]["counts"] = self._nx_reader[entryStr + f"/default/data"][()].astype("float64")
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
                #Kludge for older files: Fill in missing motors.
                if 'Beamline Energy' not in self.data[entryStr]["motors"]:
                    self.data[entryStr]["motors"]['Beamline Energy'] = self.data[entryStr]["motors"]['Energy']
                if 'Dummy Motor' not in self.data[entryStr]["motors"]:
                    self.data[entryStr]["motors"]['Dummy Motor'] = 0
                if 'Detector Y' not in self.data[entryStr]["motors"]:
                    self.data[entryStr]["motors"]['Detector Y'] = 0
                self.data[entryStr]["energy"] = f[entryStr + "/counter0/energy"][()].astype("float64")
                self.data[entryStr]["dwell"] = f[entryStr + "/counter0/count_time"][()].astype("float64")
                self.data[entryStr]["counts"] = f[entryStr + "/counter0/data"][()].astype("float64")
                self.data[entryStr]["xpos"] = np.array(f[entryStr + "/counter0/sample_x"][()]).astype("float64")
                self.data[entryStr]["ypos"] = np.array(f[entryStr + "/counter0/sample_y"][()]).astype("float64")
                xpos = self.data[entryStr]["xpos"]
                ypos = self.data[entryStr]["ypos"]
                self.data[entryStr]["xstepsize"] = (xpos.max() - xpos.min())/xpos.size
                self.data[entryStr]["ystepsize"] = (ypos.max() - ypos.min())/ypos.size    

def find_paths(number):
    num = str(number)

    yy = num[0:2]
    yyyy = '20'+yy
    mm = num[2:4]
    dd = num[4:6]
    mid_path = os.path.join(yyyy, mm, yy+mm+dd)

    # For computer connected to cosmic-dtn
    if os.path.isdir('/cosmic-dtn/groups/cosmic/Data/'+mid_path):
        path = '/cosmic-dtn/groups/cosmic/Data/'+mid_path

    # For windows computer with data on network drive Z (can remove this later?):
    elif os.path.isdir('Z:\\Data\\Nanosurveyor\\'+mid_path):
        path = 'Z:\\Data\\Nanosurveyor\\'+mid_path

    # Can insert other cases here.

    else:
        print('No valid path detected for {}'.format(number))
        return

    # Probably too cute, but this will work if a single scan number (i.e. 9 digits) or a single date (6 digits)
    # is given. It may do weird things if more than 7 or 8 digits are given though.
    path_list = glob.glob(os.path.join(path,'*'+num+'*'+'.stxm'))
    # old data can occasionally have hdrs which work for stxm but not for ptychography.
    folder_list = glob.glob(os.path.join(path,'*'+num+'*/'))
    # This is to check if there is a second folder in there which is where the cxi files will be.
    folder_list = [folder for folder in folder_list if os.path.isdir(os.path.join(folder,folder[-10:]))]
    return path_list, folder_list, path


def num_from_path(path):

    fn = os.path.split(path)[1]
    #Current format is NS_#########.stxm
    return(fn.split('_')[1].split('.')[0])

def determine_en_regions(energies):

    diffs = energies[1:]-energies[:-1]

    uniques = []
    nums = []
    firsts =[]
    lasts = []
    for i,diff in enumerate(diffs):
        if len(uniques) == 0:
            uniques.append(diff)
            nums.append(2) # Extra value for first item which is never counted in diffs.
            firsts.append(energies[i])
        else:
            if diff != uniques[-1]:
                uniques.append(diff)
                nums.append(1)
                lasts.append(energies[i])
                firsts.append(energies[i+1])
            else:
                nums[-1] = nums[-1] + 1
    lasts.append(energies[-1])

    return(uniques,nums,firsts,lasts)

def readMat(filename):
    return(loadmat(filename))

def align_stack(abs_data,phase_data = None):
    shifts = []

    aligned_data = np.copy(abs_data)
    if phase_data is not None:
        aligned_phase_data = np.copy(phase_data)

    # This is a method actually following the paper mentioned in skimage: https://ieeexplore.ieee.org/document/6111478
    # No idea why this works beter then skimage but it does...
    newsize = np.max((abs_data[0].shape[0] + abs_data[0].shape[0] - 1,
                      abs_data[0].shape[1] + abs_data[0].shape[1] - 1))
    shp = (newsize, newsize)
    center = np.fix(np.array(shp) / 2)

    for i in range(len(abs_data)):
        if np.all(abs_data[i]==0):
            shifts.append(np.array([0,0]))
            continue
        if i == 0:
            shifts.append(np.array([0,0]))
            continue
        # We align to the previous image of the dataset.
        src_image = abs_data[i-1]
        src_im_pad = np.pad(src_image, [(0, newsize - src_image.shape[0]), (0, newsize - src_image.shape[1])])

        # We create an image showing where the original image is nonzero.
        src_mask_pad = np.pad(np.ones(src_image.shape),
                              [(0, newsize - src_image.shape[0]), (0, newsize - src_image.shape[1])])

        # we can calculate a few of the fourier transforms outside of the for loop.
        f2 = np.fft.fft2(src_im_pad).conj()
        m2 = np.fft.fft2(src_mask_pad).conj()
        image = abs_data[i]
        # The rest of the images and fourier transforms have to be calculated in the loop.
        dst_im_pad = np.pad(image, [(0, newsize - image.shape[0]), (0, newsize - image.shape[1])])
        dst_mask_pad = np.pad(np.ones(image.shape),
                              [(0, newsize - image.shape[0]), (0, newsize - image.shape[1])])

        f1 = np.fft.fft2(dst_im_pad)
        f21 = np.fft.fft2(dst_im_pad * dst_im_pad)
        f22 = np.fft.fft2(src_im_pad * src_im_pad).conj()
        m1 = np.fft.fft2(dst_mask_pad)

        # These are the pieces of the overall correlation. ovl is the overlap of the two masks and is used in several places.
        # This is required to be greater than 0.3 times its maximum to keep the correlation at reasonable pixel shifts.
        # Other inverse fourier transforms could be calculated once to make it faster probably.
        ovl = np.fft.ifft2(m1 * m2)
        ovl_req = 0.5

        num = np.fft.ifft2(f1 * f2) - (np.fft.ifft2(f1 * m2) * np.fft.ifft2(m1 * f2)) / ovl
        den1 = np.fft.ifft2(f21 * m2) - np.fft.ifft2(f1 * m2) ** 2 / ovl
        den2 = np.fft.ifft2(f22 * m1) - np.fft.ifft2(f2 * m1) ** 2 / ovl

        roughcc = np.where(ovl > np.max(ovl) * ovl_req, num / np.sqrt(den1 * den2), 0)

        # The shift is then the maximum of this cross correlation.
        roughshift = np.array(np.unravel_index(np.argmax(np.abs(roughcc)), shp))
        roughshift[roughshift > center] -= np.array(shp)[roughshift > center]

        #Add the shift obtained for the previous image
        roughshift = roughshift.astype(float)+ shifts[i-1]
        #print('rough: {}'.format(roughshift))
        upsample = 10
        upsampled_region_size = upsample * 2
        # This is to take into account the existing rough shift so we don't have to upsample the whole image.
        upsampled_shift = np.fix(upsampled_region_size / 2) - roughshift * upsample
        #print('upsampled: {}'.format(upsampled_shift))
        # Here is our upsampling function. I don't think this is slow to define this here?
        def upsampled_ifft2(im):
            return (_upsampled_dft(im.conj(), upsampled_region_size, upsample, upsampled_shift).conj())

        # We need to work with the first image now for the src_im.
        src_im_2 = abs_data[0]
        src_im_pad_2 = np.pad(src_im_2, [(0, newsize - src_im_2.shape[0]), (0, newsize - src_im_2.shape[1])])
        src_mask_pad_2 = np.pad(np.ones(src_im_2.shape),
                              [(0, newsize - src_im_2.shape[0]), (0, newsize - src_im_2.shape[1])])
        f2b = np.fft.fft2(src_im_pad_2).conj()
        m2b = np.fft.fft2(src_mask_pad_2).conj()

        f22b = np.fft.fft2(src_im_pad_2 * src_im_pad_2).conj()


        # This is all the same, just using the new inverse fft.
        fineovl = upsampled_ifft2(m1 * m2b)
        finenum = upsampled_ifft2(f1 * f2b) - (upsampled_ifft2(f1 * m2b) * upsampled_ifft2(m1 * f2b)) / fineovl
        fineden1 = upsampled_ifft2(f21 * m2b) - upsampled_ifft2(f1 * m2b) ** 2 / fineovl
        fineden2 = upsampled_ifft2(f22b * m1) - upsampled_ifft2(f2b * m1) ** 2 / fineovl

        # We don't worry about overlap here, assume that has been taken care of in the rough shift.
        finecc = finenum / np.sqrt(fineden1 * fineden2)
        fineshift = np.array(
            np.unravel_index(np.argmax(np.abs(finecc)), (upsampled_region_size, upsampled_region_size)))
        #print('fine: {}'.format(fineshift))
        # Finally we add back in the rough shift.
        totshift = (fineshift - upsampled_shift) / upsample
        #print('total: {}'.format(totshift))
        shifts.append(totshift)
    for i in range(len(aligned_data)):
        aligned_data[i] = scipy.ndimage.shift(aligned_data[i], -shifts[i], order=1)
        if phase_data is not None:
            aligned_phase_data[i] = scipy.ndimage.shift(aligned_phase_data[i], -shifts[i], order=1)

    # Finally, we trim the image based on the shifts calculated
    trim_right, trim_up = -np.floor(np.min(shifts, axis=0)).astype(int)
    trim_left, trim_down = -np.ceil(np.max(shifts, axis=0)).astype(int)
    if trim_left == 0:
        trim_left = None
    if trim_down == 0:
        trim_down = None
    aligned_data = aligned_data[:, trim_right:trim_left, trim_up:trim_down]
    if phase_data is not None:
        aligned_phase_data = aligned_phase_data[:, trim_right:trim_left, trim_up:trim_down]
    else: aligned_phase_data = None

    if np.any(aligned_data.shape == 0): return(None,None)

    return(aligned_data,aligned_phase_data)


def convert_file(filename, save_flag = True, save_path = None, verbose = False, align = False):

    # Reads in a .stxm file (filename) and outputs one or more .hdr and .xim files for use in other programs.
    # Figure out how to open the file. Filename can be a path to a .stxm file or a number or string of the date.

    if os.path.isfile(filename):
        pwd = os.path.dirname(filename)
        path_list = [filename]
        folder_list = []

    else:
        path_list, folder_list, pwd = find_paths(filename)
        
    for path in path_list:
        try:
            stxm_scan = stxm(stxm_file= path)
        except:
            print('No File Found')
            continue
        nRegions = stxm_scan.nRegions
        scan_type = stxm_scan.meta["scan_type"]
        nE = stxm_scan.data['entry0']['counts'].shape[0]
        scan_num = num_from_path(path)

        #If there are multiple regions, set up multiple scan numbers
        if nRegions>1:
            scan_nums = [scan_num+'_'+str(i) for i in range(nRegions)]
        else:
            scan_nums = [scan_num]
        print(scan_type)

        #Determine the scan type.
        if scan_type == "Line Spectrum":
            scan_flag = 'line'
        elif scan_type == "Image" or scan_type == 'Ptychography Image' or scan_type == 'Spiral Image':
            if nE == 1:
                scan_flag = 'image'
            elif nE > 1:
                scan_flag = 'batch_image'
        elif scan_type == "Focus":
            scan_flag = 'focus'
        else:
            if verbose:
                print('Scan {} does not have a defined scan type. Skipping'.format(path))
            continue

        if scan_type == 'Ptychography Image':
            ptycho_flag = True


        else:
            ptycho_flag = False

        if verbose:
            print('Processing scan {}'.format(path))
            print('Scan Type: {}'.format(scan_flag))

        for i in range(nRegions):

            entry_text = 'entry'+str(i)

            sample_x = stxm_scan.data[entry_text]['xpos']
            sample_y = stxm_scan.data[entry_text]['ypos']
            if scan_flag == 'focus':
                sample_z = stxm_scan.data[entry_text]['ypos']
            motordict = stxm_scan.data[entry_text]['motors']
            # Names to be used for motor positions in the hdr file. 'skip' indicates the motor is not recorded.
            # Not really sure how much of this is necessary for getting axis to work, but it's there.
            hdrnames = {
                'Beamline Energy':'skip',
                'DISPERSIVE_SLIT':'ExitVSlit',
                'NONDISPERSIVE_SLIT':'ExitHSlit',
                'HARMONIC':'Harmonics',
                'SampleX':'SampleFineX',
                'SampleY':'SampleFineY',
                'ZonePlateZ':'ZonePlateZ',
                'CoarseX':'AUX1',
                'CoarseY':'AUX2',
                'CoarseZ':'AUX3',
                'CoarseR':'AUX4',
                'EPUOFFSET':'AUX5',
                'M101PITCH':'AUX6',
                'FBKOFFSET':'AUX7',
                'Detector Y':'AUX8',
                'Dummy Motor':'AUX9',
                'EPU Gap':'EPUGap',
                'Energy':'Monochromator',
                'POLARIZATION':'EPU_Polarization',
            }
            dwell = stxm_scan.data[entry_text]['dwell'][0]
            energies = stxm_scan.data[entry_text]['energy']
            start_time = stxm_scan.meta['start_time']
            end_time = stxm_scan.meta['end_time']
            tot_time_delta = np.datetime64(end_time)-np.datetime64(start_time)
            # Estimate the times for each file writing by interpolating between the start and end.
            # Probably not necessary.
            if len(energies) == 1:
                all_times = [start_time]
            else:
                inc_time_delta = tot_time_delta/(len(energies)-1)
                all_times = np.arange(np.datetime64(start_time), np.datetime64(end_time),inc_time_delta)
                if len(all_times) != len(energies):
                    all_times = np.append(all_times,np.datetime64(end_time))

            # Set up the ptycho data and x and y values.
            if ptycho_flag:
                cxipathbase = path[:-5]+'_ccdframes'
                try:
                    cx0 = readCXI(cxipathbase+'_0_{}_cosmic2.cxi'.format(i))
                    test = cx0.image[-1]
                    cosmic2flag = True
                    cxiflag = True
                except:
                    try:

                        cx0 = readCXI(cxipathbase+'_0_{}.cxi'.format(i)) # i is region number
                        test = cx0.image[-1]
                        cosmic2flag = False
                        cxiflag = True
                    except:
                        cxiflag = False

                try:
                    mat0 = readMat(cxipathbase+'_0_{}.mat'.format(i))
                    oldmatflag = False
                    matflag = True
                    cxiflag = False
                except:
                    try:
                        mat0 = readMat(cxipathbase+'_0_{}_full.mat'.format(i))
                        oldmatflag = True
                        matflag = True
                        cxiflag = False
                    except:
                        matflag = False
                if not matflag and not cxiflag:
                    continue
                if cxiflag:
                    pxsize = cx0.pixnm() / 1e3 # change to um
                    nn = cx0.probe.shape[0]//2 # for trimming. Probe is square, so trim both axes equally.
                    data0 = np.abs(cx0.image[-1])[nn:-nn,nn:-nn]
                if matflag:
                    pxsize = -mat0['basis'][0,1] * 1e6
                    nn = mat0['probe'].shape[0]//2
                    data0 = np.abs(mat0['obj'])[nn:-nn,nn:-nn]



                nx, ny = data0.shape
                xcenter = np.mean(sample_x)
                ycenter = np.mean(sample_y)
                xpxsize = pxsize
                ypxsize = pxsize
                xmin = xcenter - nx / 2 * xpxsize
                ymin = ycenter - ny / 2 * ypxsize
                xmax = xcenter + nx / 2 * xpxsize
                ymax = ycenter + ny / 2 * ypxsize
                data = np.zeros((len(energies),nx,ny),dtype=float)
                phasedata = np.zeros((len(energies),nx,ny),dtype=float)

                sample_x = np.linspace(ymin, ymax, ny)  # These are switched for some reason.
                sample_y = np.linspace(xmin, xmax, nx)
                for j in range(len(energies)):
                    print('reading image {}'.format(j))
                    if j == 0: # avoid reading the first one twice. Speeds up single images probably.
                        if cxiflag:
                            cx = cx0
                        if matflag:
                            mat = mat0
                    else:
                        if cxiflag:
                            if cosmic2flag:
                                try:
                                    cx = readCXI(cxipathbase+'_{}_{}_cosmic2.cxi'.format(j,i))
                                    test = cx.image[-1]
                                except:
                                    continue
                            else:
                                try:
                                    cx = readCXI(cxipathbase+'_{}_{}.cxi'.format(j,i))
                                    test = cx.image[-1]
                                except:
                                    continue
                        if matflag:
                            if oldmatflag:
                                try:
                                    mat = readMat(cxipathbase+'_{}_{}_full.mat'.format(j,i))
                                except:
                                    continue
                            else:
                                try:
                                    mat = readMat(cxipathbase + '_{}_{}.mat'.format(j, i))
                                except:
                                    continue

                    # There are often off by 1 errors in the size of the images. This corrects for that.
                    if cxiflag:
                        xdiff, ydiff = np.array(cx0.image[-1].shape) - np.array(cx.image[-1].shape)
                        data[j] = np.abs(cx.image[-1])[nn:-nn+xdiff,nn:-nn+ydiff]
                        phasedata[j] = unwrap_phase(np.angle(cx.image[-1])[nn:-nn+xdiff,nn:-nn+ydiff])
                    if matflag:
                        matxdiff, matydiff = np.array(mat0['obj'].shape)-np.array(mat['obj'].shape)
                        data[j] = np.abs(mat['obj'])[nn:-nn+matxdiff,nn:-nn+matydiff]
                        phasedata[j] = unwrap_phase(np.angle(mat['obj'])[nn:-nn+matxdiff,nn:-nn+matydiff])

            else:
                data = stxm_scan.data[entry_text]['counts']
            if scan_flag == 'batch_image':
                # If requested, align images.

                if align:
                    if verbose: print('Aligning Images')
                    if ptycho_flag:
                        aln_data, aln_phasedata = align_stack(data, phasedata)
                        if aln_data is not None:
                            data = aln_data
                            phasedata = aln_phasedata
                        else:
                            if verbose: print('Image alignment resulted in zero size array')
                    else:
                        aln_data, _ = align_stack(data)
                        if aln_data is not None:
                            data = aln_data
                        else:
                            if verbose: print('Image alignment resulted in zero size array')
                    if verbose: print('Image Alignment Done')

                    nx, ny = data[0].shape
                    xcenter = np.mean(sample_x)
                    ycenter = np.mean(sample_y)
                    if not ptycho_flag:
                        xpxsize = (sample_x[1]-sample_x[0])
                        ypxsize = (sample_y[1]-sample_y[0])
                    else:
                        xpxsize = pxsize
                        ypxsize = pxsize
                    xmin = xcenter - nx / 2 * xpxsize
                    ymin = ycenter - ny / 2 * ypxsize
                    xmax = xcenter + nx / 2 * xpxsize
                    ymax = ycenter + ny / 2 * ypxsize

                    sample_x = np.linspace(ymin, ymax, ny)  # These are switched for some reason.
                    sample_y = np.linspace(xmin, xmax, nx)


            if save_flag:
                if save_path is None:
                    save_path = os.path.join(pwd,'sdf_output')
                if not os.path.exists(save_path):
                    if verbose:
                        print('Making output directory')
                    os.makedirs(save_path)

                # If a batch image, generate its own folder. This should maybe be changed if only a single scan is
                # specified.
                if scan_flag == 'batch_image':
                    out_path = os.path.join(save_path,'NS_'+scan_nums[i])
                    if not os.path.exists(out_path):
                        if verbose:
                            print('Making output directory for scan {}'.format(scan_nums[i]))
                        os.makedirs(out_path)
                    file = 'NS_'+scan_nums[i]+'.hdr'
                # If not, throw it in the savepath.
                else:
                    out_path = save_path
                file = 'NS_'+scan_nums[i]+'.hdr'

                # Every scan type needs a list of lines to write to the hdr.
                HDR_text_lines = []

                # The first line depends on the scan type. It has an open bracket which needs to be closed later.
                if scan_flag == 'batch_image':
                    HDR_text_lines.append(('ScanDefinition = {{ Label = {0}; Type = "NEXAFS Image Scan"; '\
                                          'Flags = "Image Stack"; Dwell = {1};').format(file, dwell))
                elif scan_flag == 'image':
                    HDR_text_lines.append(('ScanDefinition = {{ Label = {0}; Type = "Image Scan"; '\
                                          'Flags = "Image"; Dwell = {1};').format(file, dwell))

                elif scan_flag == 'line':
                    HDR_text_lines.append(('ScanDefinition = {{ Label = {0}; Type = "NEXAFS Line Scan"; '\
                                          'Flags = "Image"; Dwell = {1};').format(file, dwell))
                elif scan_flag == 'focus':
                    HDR_text_lines.append(('ScanDefinition = {{ Label = {0}; Type = "Focus Scan"; ' \
                                           'Flags = "Image"; Dwell = {1};').format(file, dwell))

                # Define the scan regions. For image scans, P and Q correspond to x and y. We separate regions to
                # different files, so the region number is only ever one.
                if scan_flag == 'batch_image' or scan_flag == 'image':

                    HDR_text_lines.append('\tRegions = (1,')

                    HDR_text_lines.append('{')
                    #X axis points
                    HDR_text_lines.append(('\t\t\tPAxis = {{ Name = "Sample X"; Unit = "um"; '\
                                           'Min = {0}; Max = {1}; Dir = 1;').format(sample_x.min(),sample_x.max()))

                    xstr = ', '.join(["{:.4f}".format(val) for val in sample_x]) # 4 decimals to match 1102.
                    xstr = str(len(sample_x)) + ', ' + xstr
                    HDR_text_lines.append('\t\t\t\tPoints = ('+xstr+');')
                    HDR_text_lines.append('};')

                    #Y axis points
                    HDR_text_lines.append(('\t\t\tQAxis = {{ Name = "Sample Y"; Unit = "um"; '\
                                           'Min = {0}; Max = {1}; Dir = 1;').format(sample_y.min(),sample_y.max()))
                    ystr = ', '.join(["{:.4f}".format(val) for val in sample_y]) # 4 decimals to match 1102.
                    ystr = str(len(sample_y)) + ', ' + ystr
                    HDR_text_lines.append('\t\t\t\tPoints = ('+ystr+');')
                    HDR_text_lines.append('};')

                    HDR_text_lines.append('});') #Close of region block.

                # For focus and linescans, one of the dimensions is the distance along the scan.
                if scan_flag == 'focus' or scan_flag == 'line':
                    distTravelled = abs(sample_x-sample_x[0])

                # For a focus scan, the P axis is the distance travelled and the Q axis is the zone plate position.
                if scan_flag == 'focus':

                    HDR_text_lines.append('\tRegions = (1,')

                    HDR_text_lines.append('{')
                    # X axis points
                    HDR_text_lines.append(('\t\t\tPAxis = {{ Name = "Length"; Unit = "um"; ' \
                                           'Min = {0}; Max = {1}; Dir = 1;'
                                           ).format(distTravelled.min(),distTravelled.max()))
                    diststr = ', '.join(["{:.4f}".format(val) for val in distTravelled])  # 4 decimals to match 1102.
                    diststr = str(len(sample_x)) + ', ' + diststr
                    HDR_text_lines.append('\t\t\t\tPoints = (' + diststr + ');')
                    HDR_text_lines.append('};')

                    # Y axis points
                    HDR_text_lines.append(('\t\t\tQAxis = {{ Name = "Zone Plate"; Unit = "um"; ' \
                                           'Min = {0}; Max = {1}; Dir = 1;').format(sample_z.min(), sample_z.max()))
                    zstr = ', '.join(["{:.4f}".format(val) for val in sample_z])  # 4 decimals to match 1102.
                    zstr = str(len(sample_z)) + ', ' + zstr
                    HDR_text_lines.append('\t\t\t\tPoints = (' + zstr + ');')
                    HDR_text_lines.append('};')

                    HDR_text_lines.append('});')  # Close of region block.

                # For a focus scan, the P axis is the distance travelled and the Q axis is the zone plate position.
                if scan_flag == 'line':

                    HDR_text_lines.append('\tRegions = (1,')

                    HDR_text_lines.append('{')
                    # X axis points
                    HDR_text_lines.append(('\t\t\tPAxis = {{ Name = "Energy"; Unit = "eV"; ' \
                                           'Min = {0}; Max = {1}; Dir = 1;'
                                           ).format(energies.min(),energies.max()))
                    enstr = ', '.join(["{:.4f}".format(val) for val in energies])  # 4 decimals to match 1102.
                    enstr = str(len(energies)) + ', ' + enstr
                    HDR_text_lines.append('\t\t\t\tPoints = (' + enstr + ');')
                    HDR_text_lines.append('};')

                    # Y axis points
                    HDR_text_lines.append(('\t\t\tQAxis = {{ Name = "Sample"; Unit = "um"; ' \
                                           'Min = {0}; Max = {1}; Dir = 1;'
                                           ).format(distTravelled.min(),distTravelled.max()))
                    diststr = ', '.join(["{:.4f}".format(val) for val in distTravelled])  # 4 decimals to match 1102.
                    diststr = str(len(sample_x)) + ', ' + diststr
                    HDR_text_lines.append('\t\t\t\tPoints = (' + diststr + ');')
                    HDR_text_lines.append('};')

                    HDR_text_lines.append('});')  # Close of region block.


                # Everthing from 11.0.2 has this, so I'll keep it in. Should work with just one energy.
                if scan_flag != 'line':
                    HDR_text_lines.append(('\tStackAxis = {{ Name = "Energy"; Unit = "eV"; '\
                                          'Min = {0}; Max = {1}; Dir = 1;').format(energies.min(),energies.max()))


                    Estr = ', '.join(["{:.3f}".format(val) for val in energies])
                    Estr = str(len(energies)) + ', ' + Estr
                    HDR_text_lines.append('\t\tPoints = ('+Estr+');')
                # Line scan is not a stack but has multiple energies, so we just lie about it.
                else:
                    HDR_text_lines.append(('\tStackAxis = {{ Name = "Energy"; Unit = "eV"; ' \
                                           'Min = {0}; Max = {1}; Dir = 1;').format(energies.min(), energies.min()))
                    HDR_text_lines.append('\t\tPoints = (1, {:.4f});'.format(energies.min()))

                HDR_text_lines.append('};') #Close of scan definition

                HDR_text_lines.append('\tChannels = (1,')
                HDR_text_lines.append('{ Name = "PD"; Unit = "counts";});')

                HDR_text_lines.append('};')

                HDR_text_lines.append((' Time = "{}"; BeamFeedback = true; '\
                        'ShutterAutomatic = true;\n').format(start_time))

                HDR_text_lines.append('')

                HDR_text_lines.append('Channels = (1,')
                HDR_text_lines.append('{ ID = 4; Type = 0; Name = "PD"; Controler = 0; DeviceNumber = 0; '\
                                      'UnitName = "counts"; LinearCoefficient = 1; ConstantCoefficient = 0;'\
                                      'ProcessString = "C2";});')

                for motor in hdrnames:
                    if hdrnames[motor] == 'skip':
                        continue
                    HDR_text_lines.append('')
                    HDR_text_lines.append(('{0} = {{ Name = "{1}"; LastPosition = {2};}};'
                                           ).format(hdrnames[motor],motor,motordict[motor]))

                HDR_text_lines.append((' StorageRingCurrent = 0; EPUPhase = 0; Polarization = {}; '\
                                       'PMT_CounterDivider = 1; A0 = 1;'
                                       ).format(motordict['POLARIZATION']))



                if scan_flag == 'batch_image':

                    HDR_text_lines.append('ImageScan = { ScanType = "Image (Line - unidirection)"; ' \
                                          'Stage = "Automatic"; Shutter = "Automatic"; Interferometry = "Off"; ' \
                                          'SingleEnergy = false; AutoShutterPointScan = true;')

                    ensteps,enpoints,enstarts,enstops = determine_en_regions(energies)
                    enranges = np.array(enstops)-np.array(enstarts)

                    HDR_text_lines.append('\tEnergyRegions = ({},'.format(len(ensteps)))

                    for j in range(len(ensteps)):
                        HDR_text_lines.append(('{{ StartEnergy = {0}; EndEnergy = {1}; Range = {2}; '\
                                              'Step = {3}; Points = {4}; DwellTime = {5};}},'
                                              ).format(enstarts[j],enstops[j],enranges[j],ensteps[j],
                                                       enpoints[j],dwell))
                        if j == len(ensteps)-1:
                            HDR_text_lines[-1] = HDR_text_lines[-1][:-1]+');'

                    HDR_text_lines.append(' Point Delay = 0.0; LineDelay = 50; AccelDist = 1; MultipleRegions = False;')

                if scan_flag == 'image':

                    HDR_text_lines.append('ImageScan = { ScanType = "Image (Line - unidirection)"; ' \
                                          'Stage = "Automatic"; Shutter = "Automatic"; Interferometry = "Off"; ' \
                                          'SingleEnergy = false; AutoShutterPointScan = true;')


                    HDR_text_lines.append('\tEnergyRegions = (1,')

                    HDR_text_lines.append(('{{ StartEnergy = {0}; EndEnergy = {1}; Range = 0; '\
                                          'Step = 1; Points = 1; DwellTime = {2};}});'
                                          ).format(energies[0],energies[0], dwell))

                    HDR_text_lines.append(' Point Delay = 0.0; LineDelay = 50; AccelDist = 1; MultipleRegions = False;')

                # Generate the scan definition for the batch image or image.
                if scan_flag == 'batch_image' or scan_flag == 'image':
                    HDR_text_lines.append('\tSpatialRegions = (1,')

                    Xcenter = (sample_x.min()+sample_x.max())/2
                    Ycenter = (sample_y.min()+sample_y.max())/2
                    Xrange = sample_x.max()-sample_x.min()
                    Yrange = sample_y.max()-sample_y.min()
                    Xstep = Xrange/(len(sample_x)-1)
                    Ystep = Yrange/(len(sample_y)-1)
                    Xpoints = len(sample_x)
                    Ypoints = len(sample_y)

                    scan_params = [Xcenter,Ycenter,Xrange,Yrange,Xstep,Ystep,Xpoints,Ypoints]

                    HDR_text_lines.append(('{{ CentreXPos = {0:.4f}; CentreYPos = {1:.4f}; XRange = {2:.4f}; '\
                                           'YRange = {3:.4f}; XStep = {4:.4f}; YStep = {5:.4f}; XPoints = {6}; '\
                                           'YPoints = {7}; SquareRegion = false; SquarePixels = false;}});'
                                           ).format(*scan_params))

                    HDR_text_lines.append('};')


                # For the focus scan, the scan definition is slightly different. We have to calculate a few things.

                if scan_flag == 'focus':

                    Xcenter = (sample_x.min()+sample_x.max())/2
                    Ycenter = (sample_y.min()+sample_y.max())/2
                    Length = ((sample_x.max()-sample_x.min())**2+(sample_y.max()-sample_y.min())**2)**0.5
                    Theta = np.arctan2(sample_y.max()-sample_y.min(),sample_x.max()-sample_y.min())*180/np.pi
                    nPoints = len(sample_x)
                    Step = Length/(nPoints-1)
                    ZPStartPos = sample_z[0]
                    ZPEndPos = sample_z[-1]
                    ZPRange = np.abs(ZPEndPos-ZPStartPos)
                    nZPoints = len(sample_z)
                    ZPStep = ZPRange/(nZPoints-1)

                    scan_params = [Xcenter,Ycenter,Length,Theta,nPoints,Step,ZPStartPos,ZPEndPos,ZPRange,
                                   nZPoints,ZPStep, dwell]

                    HDR_text_lines.append(('FocusScan = {{ CentreXPos = {0:.4f}; CentreYPos = {1:.4f}; '\
                                           'Length = {2:.4f}; Theta = {3:.2f}; nPoints = {4}; Step = {5:.4f}; '\
                                           'ZPStartPos = {6:.4f}; ZPEndPos = {7:.4f}; ZPRange = {8:.4f}; '\
                                           'nZPoints = {9}; ZPStep = {10:.4f}; DwellTime = {11}; AccelDist = 0;}};'
                                           ).format(*scan_params))

                # Line scan is again different.
                if scan_flag == 'line':

                    HDR_text_lines.append('ImageScan = { ScanType = "Line (Full Horiz. Line)"; ' \
                                          'Stage = "Automatic"; Shutter = "Automatic"; Interferometry = "Off"; ' \
                                          'SingleEnergy = false; AutoShutterPointScan = true;')

                    ensteps,enpoints,enstarts,enstops = determine_en_regions(energies)
                    enranges = np.array(enstops)-np.array(enstarts)

                    HDR_text_lines.append('\tEnergyRegions = ({},'.format(len(ensteps)))

                    for j in range(len(ensteps)):
                        HDR_text_lines.append(('{{ StartEnergy = {0}; EndEnergy = {1}; Range = {2}; '\
                                              'Step = {3}; Points = {4}; DwellTime = {5};}},'
                                              ).format(enstarts[j],enstops[j],enranges[j],ensteps[j],
                                                       enpoints[j],dwell))
                        if j == len(ensteps)-1:
                            HDR_text_lines[-1] = HDR_text_lines[-1][:-1]+');'

                    HDR_text_lines.append(' Point Delay = 0.0; LineDelay = 50; AccelDist = 1; MultipleRegions = False;')


                    HDR_text_lines.append('\tSpatialRegions = (1,')

                    Xcenter = (sample_x.min()+sample_x.max())/2
                    Ycenter = (sample_y.min()+sample_y.max())/2
                    Length = ((sample_x.max()-sample_x.min())**2+(sample_y.max()-sample_y.min())**2)**0.5
                    Theta = np.arctan2(sample_y.max()-sample_y.min(),sample_x.max()-sample_y.min())*180/np.pi
                    Step = Length/(len(sample_x)-1)
                    Points = len(sample_x)

                    scan_params = [Xcenter,Ycenter,Length,Theta,Step,Points]

                    HDR_text_lines.append(('{{ CentreXPos = {0:.4f}; CentreYPos = {1:.4f}; Length = {2:.4f}; '\
                                           'Theta = {3:.2f}; Step = {4:.4f}; Points = {5};}});'
                                           ).format(*scan_params))

                    HDR_text_lines.append('};')

                #Make a hdr file and images for the phase
                if ptycho_flag:
                    phase_text_lines = HDR_text_lines.copy()
                    if scan_type == 'batch_image':
                        phase_out_path = out_path + '_phase'
                    else:
                        phase_out_path = out_path
                    old_first_line = HDR_text_lines[0].split(file)
                    phasefile = 'NS_'+scan_nums[i]+'_phase.hdr'

                    phase_text_lines[0] = old_first_line[0]+phasefile+old_first_line[1]



                #The line scan needs x axis of energy, y axis of position.
                if scan_flag == 'line':
                    fn = os.path.join(out_path, 'NS_' + scan_nums[0] + '_a.xim')
                    if verbose:
                        print('saving image file {}'.format(fn))
                    img = data[:,0].T # linescan has shape (en, 1, position)
                    np.savetxt(fn,img,fmt = '%.d') #converts to integer. May need to be transposed
                    HDR_text_lines.append(('Image{0:03d}_0 = {{StorageRingCurrent = 0.00; Energy = {1:.3f}; '\
                                           'Time = {2}; ZP_dest = 0.0; ZP_error = 0.0;}};'
                                           ).format(i, energies[0], all_times[0]))

                # The batch image files need to be named with the number of the scan.
                elif scan_flag == 'batch_image':
                    for j, img in enumerate(data):
                        fn = os.path.join(out_path,'NS_'+scan_nums[i]+'_a{:03d}.xim'.format(j))
                        if verbose:
                            print('saving image file {}'.format(fn))
                        if ptycho_flag:
                            np.savetxt(fn,img,fmt='%.4f') #float for ptychography (log taken already?)
                            pfn = os.path.join(phase_out_path, 'NS_'+scan_nums[i]+'_phase_a{:03d}.xim'.format(j))
                            np.savetxt(pfn,phasedata[j],fmt='%.4f') #save the phase data in separate file.
                        else:
                            np.savetxt(fn,img,fmt = '%.d') #converts to integer. May need to be transposed
                        HDR_text_lines.append(('Image{0:03d}_0 = {{StorageRingCurrent = 0.00; Energy = {1:.3f}; '\
                                               'Time = {2}; ZP_dest = 0.0; ZP_error = 0.0;}};'
                                               ).format(j,energies[j],all_times[j]))
                        if ptycho_flag:
                            phase_text_lines.append(('Image{0:03d}_0 = {{StorageRingCurrent = 0.00; Energy = {1:.3f}; '\
                                                   'Time = {2}; ZP_dest = 0.0; ZP_error = 0.0;}};'
                                                   ).format(j, energies[j], all_times[j]))


                # Single image or focus scan.
                else:
                    fn = os.path.join(out_path, 'NS_' + scan_nums[0] + '_a.xim')
                    if verbose:
                        print('saving image file {}'.format(fn))
                    img = data[0] # These have shape (1, x, z)
                    if ptycho_flag:
                        np.savetxt(fn, img, fmt='%.4f')  # float for ptychography (log taken already?)
                        pfn = os.path.join(phase_out_path, 'NS_'+scan_nums[i]+'_phase_a.xim')
                        np.savetxt(pfn,phasedata[j],fmt='%.4f') #save the phase data in separate file.
                    else:
                        np.savetxt(fn, img, fmt='%.d')  # converts to integer. May need to be transposed
                    HDR_text_lines.append(('Image{0:03d}_0 = {{StorageRingCurrent = 0.00; Energy = {1:.3f}; '\
                                           'Time = {2}; ZP_dest = 0.0; ZP_error = 0.0;}};'
                                           ).format(i, energies[0], all_times[0]))
                    if ptycho_flag:
                        phase_text_lines.append(('Image{0:03d}_0 = {{StorageRingCurrent = 0.00; Energy = {1:.3f}; ' \
                                                 'Time = {2}; ZP_dest = 0.0; ZP_error = 0.0;}};'
                                                 ).format(j, energies[j], all_times[j]))


                # I forgot the \n character in these, so I'm adding them at the end.
                HDR_text_lines = [line+'\n' for line in HDR_text_lines]
                if ptycho_flag:
                    phase_text_lines = [line+'\n' for line in phase_text_lines]


                outputfile = os.path.join(out_path,'NS_'+scan_nums[i]+'.hdr')
                if ptycho_flag:
                    phaseoutputfile = os.path.join(phase_out_path,'NS_'+scan_nums[i]+'_phase.hdr')

                if verbose:
                    print('writing to output {}'.format(outputfile))

                with open(outputfile,'w') as f:
                    f.writelines(HDR_text_lines)

                if ptycho_flag:
                    if verbose:
                        print('writing to output {}'.format(phaseoutputfile))

                    with open(phaseoutputfile, 'w') as f:
                        f.writelines(phase_text_lines)
                        
    for folder in folder_list:
        #This will be where the files are read in for the old cxi files.
        
        pass


if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    parser.add_argument('number')

    parser.add_argument('-o', '--Output', help = 'Output path')

    parser.add_argument('-v','--Verbose',action='store_true', help = 'Show print statements')


    parser.add_argument('-a','--Align',action='store_true', help = 'Whether to do image alignment')

    args = parser.parse_args()

    convert_file(args.number,save_path=args.Output,verbose=args.Verbose,align=args.Align)

from pystxmcontrol.utils.writeNX import *
from pystxmcontrol.utils.image import *
from skimage.filters import sobel, gaussian
from skimage.registration import phase_cross_correlation as register_translation
from skimage.registration._phase_cross_correlation import _upsampled_dft
from skimage.restoration import denoise_nl_means, estimate_sigma
from scipy.signal import medfilt, medfilt2d, wiener
from scipy import ndimage, stats
import numpy as np
import scipy as sc
import cv2
from scipy.cluster.vq import kmeans2
from sklearn.decomposition import PCA
from sklearn.cluster import DBSCAN
import ntpath, calendar, time
from skimage.io import imsave
import scipy.misc
import matplotlib.pyplot as plt
from pystxmcontrol.utils.general import find_nearest
from sklearn.decomposition import NMF

class stack():

    def __init__(self, fileName = None, iRegion = 0):

        """
        This is the main analysis class for ALS STXM data.  It can be initialized by giving fileName
        an HDR file (with scan type "NEXAFS Image Scan") or it can be initialized empty and images
        can be added later with the addImageToStack method.  Some key attributes are:

        rawFrames: list of image objects loaded from HDR and XIM files
        processedFrames: 3D numpy array that is the result of the previous operation
        energies: 1D numpy array of x-ray energies
        angles: 1D numpy array of sample angles
        I0: 1D numpy array of I0 values.  Can be estimated or manually added
        odFrames: numpy array of frames converted to optical density.  estimates I0 if it doesn't exist
        lastFrames: 3D numpy array with values of processedFrames prior to the last operation
        pcaFrames: 3D numpy array with values of optical density filtered by PCA analysis
        darkField: float value to subtract from rawFrames for background correction
        filteredImages: can't remember
        rgbImage: 3D numpy array formatted with (NxNx3) dimensions to be displayed as RGB image.
        references: list of 1D numpy arrays (E,I) used as reference spectra
        eCalibration: float value to subtract from energies for a calibration shift
        imageChannel: default channel loaded from the HDR file
        """

        # set up the form class as a `ui` attribute
        self.targetSVDmaps = None
        self.I0 = None
        self.I0ext = None
        self.rois = []
        self.I0rois = []
        self.spectra = []
        self.spectraExternal = []
        self.rawFrames = []
        self.processedFrames = None
        self.energies = None
        self.angles = None
        self.odFrames = None
        self.lastFrames = None
        self.slope = 0.
        self.intercept = 0.
        self.pcaImages = None
        self.iRegion = iRegion
        self.darkField = 0.
        self.dataIsNormalized = False
        self.filteredImages = None
        self.rgbImage = None
        #get some random colors for the clusters and spectra plots
        self.penColors = [(1,0,0),(0,1,0),(0,0,1),(1,1,0),(1,0,1),(0,1,1)]
        totalColors = len(self.penColors)
        while totalColors <= 100:
            color = list(np.random.choice(range(256), size=3))
            if sum(color) / 3. > 80.:
                self.penColors.append(color)
                totalColors += 1
        self.references = {}
        self.eCalibration = 0.0
        self.imageChannel = 'V/F'
        self.normalizationChannels = ['PhotoDiode','LeftSlit']
        self.rMap = None
        self.nC = 1.6
        self.fileName = fileName
        if fileName != None:
            if '.hdr' in fileName:
                self.hdrFile = fileName
                self.openHDR()
            elif '.stxm' in fileName:
                self.nxFile = fileName
                self.openNX()
            elif '.cxi' in fileName:
                self.cxiFile = fileName
                self.hdrFile = self.cxiFile.replace('.cxi','.hdr')
                self.openCXI()

    def scaleBarLength(self, pixels = True):
        """
        This is used by the GUI to generate a scale bar for display in the images.
        """
        scaleBarLenMicrons = np.round(0.1 * self.xpixelsize * self.shape[-1], decimals = 1)
        if pixels: return int(scaleBarLenMicrons / self.xpixelsize)
        else: return scaleBarLenMicrons

    def spectraFromROIS(self, OD = False, removePreEdge = False, detrend = False):
        """
        This is used by the GUI to extract average spectra from a list of ROIs
        """
        ##need to transpose the image coordinates because pyqtgraph is so studid
        if OD: viewFrames = self.odFrames.copy()
        else: viewFrames = self.processedFrames.copy()
        self.spectra = []
        nE, nY, nX = self.processedFrames.shape
        dummy = np.ones((nX,nY,nE))
        for roi in self.rois:
            if roi['type'] == 'ellipse':
                self.spectra.append(roi['region'].getArrayRegion(np.transpose((viewFrames), axes = (2,1,0)), \
                    roi['image']).mean(axis = (0,1)) / (roi['region'].getArrayRegion(dummy, roi['image']).mean(axis = (0,1))))
            elif roi['type'] == 'point':
                row,col = roi['point']
                self.spectra.append(viewFrames[:,col,row])

        if detrend: removePreEdge = False
        if removePreEdge:
            for i in range(len(self.spectra)):
                self.spectra[i] = self.detrendSpectrum(self.spectra[i], order = 0)
        elif detrend:
            for i in range(len(self.spectra)):
                self.spectra[i] = self.detrendSpectrum(self.spectra[i], order = 1)
        else:
            self.slope = 0.
            self.intercept = 0.

    def updateI0(self):
        """
        This is used by the GUI to get average I0 from the I0 ROIs
        """
        if len(self.I0rois) == 0: self.I0 = None
        else: self.I0FromROIS()

    def I0FromROIS(self):
        """
        This is used by the GUI to get average I0 from the I0 ROIs
        """
        nROI = len(self.I0rois)
        I0 = np.zeros(len(self.energies))
        nE, nY, nX = self.processedFrames.shape
        dummy = np.ones((nX,nY,nE))
        for roi in self.I0rois:
            thisI0 = roi['region'].getArrayRegion(np.transpose(self.processedFrames,axes = (2,1,0)), roi['image'])
            I0 += thisI0.mean(axis = (0,1)) / float(nROI) / (roi['region'].getArrayRegion(dummy, roi['image']).mean(axis = (0,1)))
        self.I0 = np.reshape(I0, (len(I0),1,1))

    def addSpectrum(self, spectrum, tag = None):
        """
        Spectrum should have shape (2,nEnergies) with spectrum[0] = energies
        :param spectrum:
        :param tag:
        :return: spectrum list interpolated at energies
        """
        ##first, interpolate specgtrum onto same energy grid as image data
        f = sc.interpolate.interp1d(spectrum[0],spectrum[1])
        refSpec = np.array([f(energy) for energy in (self.energies + self.eCalibration)])
        nRefs = len(self.references.keys())
        if tag is None:
            tag = 'ref' + str(nRefs + 1)
        self.references[tag] = refSpec

    def addImageToStack(self, image, interpolate = False, crop = False, pad = False, normalizeToStack = True):
        """
        Add an image object to an existing stack.  It uses the image energy and pixel size data to
        determine the location and need to interpolate or crop
        :param image:
        :param interpolate:
        :param crop:
        :param pad:
        :param normalizeToStack:
        :return:
        """
        if self.rawFrames is None:
            self.rawFrames = [image]
            self.energies = np.array([frame.energy for frame in self.rawFrames])
        else:
            self.rawFrames.append(image)
            self.energies = np.array([frame.energy for frame in self.rawFrames])
            #sort images and energies in ascending order
            self.rawFrames = [self.rawFrames[i] for i in np.argsort(self.energies)]
        #self.reset(interpolate = interpolate, crop = crop, pad = pad)

    def deleteFrame(self, energy = None):
        """
        Deletes the rawFrame at the nearest energy and resets other arrays
        :param energy:
        :return:
        """
        if energy is None:
            return
        else:
            frameIdx = find_nearest(self.energies, energy)
            self.rawFrames.pop(frameIdx)
            self.reset()

    def indexFromEnergy(self, energy):
        return find_nearest(self.energies, energy)

    def reset(self, interpolate = False, crop = False, pad = False):
        """
        Resets all numpy arrays from list of rawFrames.  Executes pixel interpolation and cropping
        as needed.
        :param interpolate:
        :param crop:
        :param pad:
        :return:
        """
        self.energies = np.array([frame.energy for frame in self.rawFrames])
        pixelsize = [p.xpixelsize for p in self.rawFrames]
        pixelsize = min(pixelsize)

        if interpolate:
            for i in range(len(self.rawFrames)):
                self.rawFrames[i].resample(pixelSize = pixelsize)

        yMin = min([im.processedFrame.shape[0] for im in self.rawFrames])
        xMin = min([im.processedFrame.shape[1] for im in self.rawFrames])
        if crop:
            for i in range(len(self.rawFrames)):
                self.rawFrames[i].crop(shape = (yMin, xMin))
        elif pad:
            ##need to get the largest size in both directions then pad all frames
            xMax = max([im.data.shape[1] for im in self.rawFrames])
            yMax = max([im.data.shape[0] for im in self.rawFrames])
            for i in range(len(self.rawFrames)):
                self.rawFrames[i].pad(shape = (yMax,xMax))
        self.processedFrames = np.array([im.processedFrame for im in self.rawFrames])
        self.odFrames = None
        self.I0 = None

    def update(self):
        """
        This is executed prior to each operation.  Just saves current processedFrames into lastFrames
        to allow for undo()
        :return:
        """
        self.lastFrames = self.processedFrames.copy()

    def undo(self):
        """
        Copies lastFrames back into processedFrames to restore values before the last operation.
        :return:
        """
        self.processedFrames = self.lastFrames.copy()

    def calcROISpectra(self):
        """
        This does nothing.  Why is it here?
        :return:
        """
        if self.rois is not []:
            pass

    def removePreEdge(self):
        """
        This is the pre-edge subtraction for normalization.  First it calculates a filtered version of the data
        (filteredFrames) using PCA.  The filtered pre-edge frame is then subtracted from odFrames.  There's
        some protection against doing this more than once.
        :return:
        """
        self.calcPCA(nPC = 5, pcaOffset = 1, nClusters = 4)
        self.preEdgeFrame = self.filteredImages[0].copy()
        if not self.dataIsNormalized: self.odFrames -= self.preEdgeFrame
        else: print("The pre-edge frame has already been subtracted.")
        self.dataIsNormalized = True

    def addPreEdge(self):
        """
        This just undoes removePreEdge()
        :return:
        """
        if self.dataIsNormalized: self.odFrames += self.preEdgeFrame
        self.dataIsNormalized = False
        self.preEdgeFrame = 0.

    def subtractDarkField(self):
        """
        This subtracts the darkField value from the processedFrames
        :return:
        """
        self.processedFrames -= self.darkField

    def detrendSpectrum(self, spectrum, order = 1):
        """
        This doesn't work at all.  Don't use it.  It removes a linear trend from a spectrum.
        :param spectrum:
        :param order:
        :return:
        """
        self.slope, self.intercept, r_value, p_value, std_err = stats.linregress(self.energies,spectrum)
        if order == 0:
            self.slope = 0
            spectrum -= self.intercept
        elif order == 1:
            spectrum -= (self.intercept + self.slope * self.energies)
        self.intercept = spectrum.min()
        return spectrum - spectrum.min()

    def getINormalizationData(self):
        """
        Don't use this.  It looks for normalization channels in the form of additional XIM files.
        They're not there so this will fail.
        :return:
        """
        self.normFrames = []
        for channel in self.normalizationChannels:
            thisChannelFrames = []
            for i in range(len(self.rawFrames)):
                fileName = self.hdr['Region' + str(self.iRegion)][channel]['files'][i]
                im = image(data = readASCIIMatrix(fileName))
                im.energy = self.hdr['energies'][i]
                im.xpixelsize = self.hdr['Region0']['xstep']
                im.ypixelsize = self.hdr['Region0']['ystep']
                im.nypixels, im.nxpixels = im.data.shape
                thisChannelFrames.append(im)
            self.normFrames.append(thisChannelFrames)

    def calcINormalization(self):
        """
        If by some strange twist of fate there are normalization channels this function attempts a correction.
        Don't use this.
        :return:
        """
        from scipy.optimize import minimize
        from math import isnan
        self.lastFrames = self.processedFrames
        self.iNorm = np.zeros((self.processedFrames.shape))
        
        for i in range(len(self.rawFrames)):
            a = self.processedFrames[i]
            b = self.normFrames[0][i].data
            c = self.normFrames[1][i].data
            fun = lambda x: (a[0,:] / (1. + x[0] * (b[0,:] - c[0,:]) / (b[0,:] + c[0,:]))).std()
            self.nC = minimize(fun, (1,), method='CG').x[0]
            if isnan(self.nC): self.nC = 1.
            print(self.nC)
            self.iNorm[i] = (1. + self.nC * (c-b) / (b + c))
        self.processedFrames /= self.iNorm 
        self.processedFrames[self.processedFrames < 1.] = self.processedFrames.mean()

    def openHDR(self):
        """
        Load a header file, generated image objects for all of the frames and append them to rawFrames.
        Only accepts the file given at instantiation.
        :return:
        """
        self.hdr = Read_header(self.hdrFile)
        self.imageChannel = self.hdr['DefaultChannel']
        self.energies = np.array(self.hdr['energies'])
        self.rawFrames = []
        for i in range(len(self.hdr['Region' + str(self.iRegion)][self.imageChannel]['files'])):
            fileName = self.hdr['Region' + str(self.iRegion)][self.imageChannel]['files'][i]
            im = image(data = readASCIIMatrix(fileName))
            im.energy = self.hdr['energies'][i]
            im.xpixelsize = self.hdr['Region0']['xstep']
            im.ypixelsize = self.hdr['Region0']['ystep']
            im.nypixels, im.nxpixels = im.data.shape
            self.rawFrames.append(im)
        self.xpixelsize = im.xpixelsize
        self.ypixelsize = im.ypixelsize
        self.reset()
        self.shape = self.processedFrames.shape

    def openNX(self):
        self.nx = stxm(stxm_file = self.nxFile)
        entryStr = "entry" + str(self.iRegion)
        self.energies = self.nx.data[entryStr]["energy"]
        self.rawFrames = []
        sh = self.nx.data["entry" + str(self.iRegion)]["counts"]["default"].shape
        for i in range(sh[0]):
            im = image(data = self.nx.data[entryStr]["counts"]["default"][i])
            im.energy = self.nx.data[entryStr]["energy"][i]
            im.xpixelsize = self.nx.data[entryStr]["xstepsize"]
            im.ypixelsize = self.nx.data[entryStr]["ystepsize"]
            im.nypixels, im.nxpixels = im.data.shape
            self.rawFrames.append(im)
        self.xpixelsize = im.xpixelsize
        self.ypixelsize = im.ypixelsize
        self.reset()
        self.shape = self.processedFrames.shape

    def openCXI(self):
        """
        Load a data from a CXI file, generated image objects for all of the frames and append them to rawFrames.
        Only accepts the file given at instantiation.
        :return:
        """
        import h5py
        f = h5py.File(self.cxiFile,'r')
        entries = [x for x in list(f) if 'entry' in x]
        self.energies = []
        self.rawFrames = []
        for entry in entries:
            im = image(data = np.abs(f[entry + '/image_1/data'][()]))
            im.energy = f[entry + '/instrument_1/source_1/energy'][()] * 6.242e18
            corner_x, corner_y, corner_z = f[entry + '/instrument_1/detector_1/corner_position'][()]
            l = (1239.852 / (im.energy)) * 1e-9
            NA = np.sqrt(corner_x ** 2 + corner_y ** 2) / np.sqrt(2.) / corner_z
            pixnm = np.round(l / 2. / NA * 1e9, 2)
            im.xpixelsize = pixnm / 1000.
            im.ypixelsize = pixnm / 1000.
            im.nypixels, im.nxpixels = im.data.shape
            self.addImageToStack(im, interpolate=False, crop=True, pad=False, normalizeToStack=True)
            # self.rawFrames.append(im)
            # self.energies.append(im.energy)
        f.close()
        self.energies = np.array(self.energies)
        self.xpixelsize = im.xpixelsize
        self.ypixelsize = im.ypixelsize
        self.reset()
        self.shape = self.processedFrames.shape
        self.hdr = {'nRegions':1}
        self.shape = self.processedFrames.shape
        for im in self.rawFrames:
            print(im.data.shape)

    def alignFrames(self, sobelFilter = False, mode = 'translation', mask = False, threshold = 0., autocrop = True):
        """
        This is the top level call for aligning processedFrames.  It applies a sobel filter by default prior
        to alignment.
        :param sobelFilter: bool.  apply sobel filter prior to registration
        :param mode: "translation", "affine", "rigid" and "homographic".
        :param progressBar: no idea.
        :param autocrop: bool. crop out wrapped pixels.
        :return:
        """
        self.lastFrames = self.processedFrames.copy()
        self.processedFrames = self.registerFrameStack(self.processedFrames, \
            sobelFilter = sobelFilter, mode = mode, mask = mask, threshold = threshold, autocrop = autocrop)
        if mode != "translation":
            self.processedFrames = self.processedFrames[:,5:-5,5:-5]
        self.shape = self.processedFrames.shape
        self.nEnergies, self.nY, self.nX = self.processedFrames.shape

    def alignODFrames(self, sobelFilter = False, mode = 'translation', autocrop = True):
        """
        This is the top level call for aligning odFrames.  It applies a sobel filter by default prior
        to alignment.
        :param sobelFilter: bool.  apply sobel filter prior to registration
        :param mode: "translation", "affine", "rigid" and "homographic".
        :param progressBar: no idea.
        :param autocrop: bool. crop out wrapped pixels.
        :return:
        """
        self.lastFrames = self.processedFrames.copy()
        self.odFrames = self.registerFrameStack(self.odFrames, sobelFilter = sobelFilter, mode = mode, \
                                                         autocrop = autocrop)

    def _registerImages(self, dst_image, src_image, mode = 'translation', mask = False, threshold = 0., sobelFilter = False):
        """
        This is the main internal registration function.  It uses phase_cross_correlation from
        skimage.registration for a simple linear translation.  For more advanced registrations
        like affine, rigid or homographic it calls _ecc_align for the opencv code.
        :param dst_image: 2D numpy. image to align to
        :param src_image: 2D numpy. image to align
        :param mode: str. type of alignment
        :param sobelFilter: bool
        :return:
        """
        if mode == 'translation':
            if sobelFilter:
                a = sobel(dst_image)
                b = sobel(src_image)
                #shifts,a,b = register_translation(a, b, upsample_factor=100)
                shifts,c,d = register_translation(a, b, \
                                                    reference_mask = a > threshold, \
                                                    moving_mask = b > threshold)#upsample_factor=100)
            else:
                #shifts,a,b = register_translation(dst_image, src_image, upsample_factor=100)
                shifts,c,d = register_translation(dst_image, src_image, \
                                                    reference_mask = dst_image > threshold, \
                                                    moving_mask = src_image > threshold)#upsample_factor=100)
                #shifts = register_translation(dst_image, src_image, \
                #                              reference_mask=dst_image > threshold, \
                #                              moving_mask=src_image > threshold)
            temp = src_image.min()
            #src_image = ndimage.interpolation.shift(src_image, shifts, mode = 'wrap')
            src_image = np.roll(src_image, (round(shifts[0]),round(shifts[1])),axis = (0,1))
            self.warp_matrix = np.eye(2, 3, dtype=np.float32)
            self.warp_matrix[0,2],self.warp_matrix[1,2] = shifts
            
        elif mode == 'thresholded':
            dst_vals,dst_bins = np.histogram(dst_image,bins = 50)
            dst_thresh = dst_image>dst_bins[7]
            src_vals,src_bins = np.histogram(src_image,bins = 50)
            src_thresh = src_image>dst_bins[7]
            shifts, c, d = register_translation(dst_thresh,src_thresh,upsample_factor = 100)
            src_image = ndimage.shift(src_image,shifts)
            self.warp_matrix = np.eye(2, 3, dtype=np.float32)
            self.warp_matrix[0,2],self.warp_matrix[1,2] = shifts
            
        elif mode == 'manualtranslation':
            #Manual version of scipy phase cross correlation which allows for upsampling of masked images.
            #First do the rough translation.
            #Pad each image with zeros so you can shift them without losing pixels.
            newsize = np.max((dst_image.shape[0]+src_image.shape[0]-1,dst_image.shape[1]+src_image.shape[1]-1))
            shp = (newsize,newsize)
            center = np.fix(np.array(shp)/2)
            dst_im_pad = np.pad(dst_image,[(0,newsize-dst_image.shape[0]),(0,newsize-dst_image.shape[1])])
            src_im_pad = np.pad(src_image,[(0,newsize-src_image.shape[0]),(0,newsize-src_image.shape[1])])
            dst_mask_pad = dst_im_pad > 0
            src_mask_pad = src_im_pad > 0
            
            #These are the fourier transforms corresponding to the sums in 10.1109/TIP.2011.2181402
            
            f1 = np.fft.fft2(dst_im_pad)
            f2 = np.fft.fft2(src_im_pad).conj()
            f21 = np.fft.fft2(dst_im_pad*dst_im_pad)
            f22 = np.fft.fft2(src_im_pad*src_im_pad).conj()
            m1 = np.fft.fft2(dst_mask_pad)
            m2 = np.fft.fft2(src_mask_pad).conj()
            
            #These are the pieces of the overall correlation. ovl is the overlap of the two masks and is used in several places.
            #This is required to be greater than 0.5 times its maximum to keep the correlation at reasonable pixel shifts.
            #Other inverse fourier transforms could be calculated once to make it faster probably.
            ovl = np.fft.ifft2(m1*m2)
            ovl_req = 0.5
            
            num = np.fft.ifft2(f1*f2)-(np.fft.ifft2(f1*m2)*np.fft.ifft2(m1*f2))/ovl
            den1 = np.fft.ifft2(f21*m2)-np.fft.ifft2(f1*m2)**2/ovl
            den2 = np.fft.ifft2(f22*m1)-np.fft.ifft2(f2*m1)**2/ovl
            
            roughcc = np.where(ovl>np.max(ovl)*ovl_req,num/np.sqrt(den1*den2),0)
            
            #The shift is then the maximum of this cross correlation.
            roughshift = np.array(np.unravel_index(np.argmax(np.abs(roughcc)),shp))
            roughshift[roughshift>center] -= np.array(shp)[roughshift>center]
            
            #We are upsampling by 100 in this second part which just means we have to use the upsampled_dft from scipy to do the iffts.
            upsample = 100
            upsampled_region_size = upsample*2
            #This is to take into account the existing rough shift so we don't have to upsample the whole image.
            upsampled_shift = np.fix(upsampled_region_size/2)-roughshift*upsample
            #Here is our upsampling function. I don't think this is slow?
            def upsampled_ifft2(im):
                return(_upsampled_dft(im.conj(),upsampled_region_size,upsample,upsampled_shift).conj())
        
            #This is all the same, just using the new inverse fft.
            fineovl = upsampled_ifft2(m1*m2)
            finenum = upsampled_ifft2(f1*f2)-(upsampled_ifft2(f1*m2)*upsampled_ifft2(m1*f2))/fineovl
            fineden1 = upsampled_ifft2(f21*m2)-upsampled_ifft2(f1*m2)**2/fineovl
            fineden2 = upsampled_ifft2(f22*m1)-upsampled_ifft2(f2*m1)**2/fineovl
        
            #We don't worry about overlap here, assume that has been taken care of in the rough shift.
            finecc = finenum/np.sqrt(fineden1*fineden2)
            fineshift = np.array(np.unravel_index(np.argmax(np.abs(finecc)),(upsampled_region_size,upsampled_region_size)))
            #Finally we add back in the rough shift.
            totshift = (fineshift-upsampled_shift)/upsample
            
            #shp = dst_image.shape
            #center = np.fix(np.array(shp)/2)
            #prodim = np.fft.fft2(dst_image)*np.fft.fft2(src_image).conj()
            #roughshift = np.array(np.unravel_index(np.argmax(np.abs(np.fft.ifft2(prodim))),shp))
            #roughshift[roughshift > center] -= np.array(shp)[roughshift > center]
            #upsampled_region_size = upsample*2
            #upsampled_shift = np.fix(upsampled_region_size/2)-roughshift*upsample
            #a = _upsampled_dft(prodim.conj(),upsampled_region_size,upsample,upsampled_shift).conj()
            #maximum = np.unravel_index(np.argmax(a),(upsampled_region_size,upsampled_region_size))
            #shifts = (maximum-upsampled_shift)/upsample
            
            #All we have to do then is shift the image.
            src_image = ndimage.shift(src_image,totshift)
            self.warp_matrix = np.eye(2, 3, dtype=np.float32)
            self.warp_matrix[0,2],self.warp_matrix[1,2] = totshift
            
        else:
            src_image = self._ecc_align(dst_image, src_image, sobel = sobelFilter, mode = mode)
        return src_image

    def registerFrameStack(self, frames, sobelFilter = False, mode = 'translation', mask = False, threshold = 0., autocrop = True):
        """
        This is really just a management function.  It decides what to do based on the type of registration.
        The cropping for registrer_translation is different from ecc_align
        :param frames:  3D numpy. frame stack
        :param sobelFilter: bool
        :param mode: string
        :param progressBar: who knows
        :param autocrop: bool
        :return:
        """
        alignedFrames = frames.copy()
        shiftList = []

        contrast = np.zeros((self.processedFrames.shape[0]))
        i = 0
        for im in self.processedFrames:
            idx = im.nonzero()
            a = im[idx].max()
            b = im[idx].mean()
            contrast[i] = ((a - b) / (a + b))
            i += 1
        contrast_max_idx = np.argmax(contrast)
        reference_img = self.processedFrames[contrast_max_idx]

        if mode == 'translation':
            for i in range(len(frames)):
                # if i > 1:
                #     alignedFrames[i] = self._registerImages(alignedFrames[0:i - 1].mean(axis = 0), frames[i], \
                #                                             mask = mask, threshold = threshold,sobelFilter = sobelFilter)
                # else:
                #     alignedFrames[i] = self._registerImages(alignedFrames[i - 1], frames[i], \
                #                                             mask = mask, threshold = threshold, sobelFilter = sobelFilter)
                alignedFrames[i] = self._registerImages(reference_img, frames[i], \
                                                        mask=mask, threshold=threshold, sobelFilter=sobelFilter)
                shifts = self.warp_matrix[0,2],self.warp_matrix[1,2]
                shiftList.append(shifts)
            shifts = np.array(shiftList)
            maxY, minY = abs(int(round(shifts[:,0].min()))), abs(int(round(shifts[:,0].max())))
            maxX, minX = abs(int(round(shifts[:,1].min()))), abs(int(round(shifts[:,1].max())))
            if maxX == 0: maxX += 1
            if maxY == 0: maxY += 1
            if autocrop: alignedFrames = alignedFrames[:,minY:-maxY, minX:-maxX]
            self.shifts = shiftList
        elif mode == 'thresholded':
            for i in range(0,len(frames)):
                alignedFrames[i] = self._registerImages(frames[0],frames[i],sobelFilter = sobelFilter,mode = mode)
                shifts = self.warp_matrix[0, 2], self.warp_matrix[1, 2]
                shiftList.append(shifts)
            shifts = np.array(shiftList)
            maxY, minY = abs(int(round(shifts[:,0].min()))), abs(int(round(shifts[:,0].max())))
            maxX, minX = abs(int(round(shifts[:,1].min()))), abs(int(round(shifts[:,1].max())))
            if maxX == 0: maxX += 1
            if maxY == 0: maxY += 1
            if autocrop: alignedFrames = alignedFrames[:,minY:-maxY, minX:-maxX]
            self.shifts = shiftList

        else:
            frameMean = frames[0]
            for i in range(0,len(frames)):
                alignedFrames[i] = self._registerImages(frameMean, frames[i], sobelFilter = sobelFilter, mode = mode)
                frameMean = (frameMean + alignedFrames[i]) * (alignedFrames[i] > 0.) / 2.
        return alignedFrames

    def setZeros(self):
        for i,frame in enumerate(self.processedFrames):
            self.processedFrames[i] = np.where(frame == 0, self.I0[i][0][0],frame)

    def getIOMask(self,spiral = False):
        """
        This generates a mask based on a histogram of the data.  It attempts to find the region outside
        of the sample to get the I0.
        Spiral option is to deal with spiral scans so that I0 doesn't include particle drift. Also excludes spikes.
        :return:
        """
        if spiral:
            I0masks = []
            for frame in self.processedFrames:
                hist = np.histogram(frame,bins = 50)
                threshold = hist[1][-6]
                I0mask = frame>threshold
                I0masks.append(I0mask)
            self.mask = np.array(I0masks).all(axis = 0)
        else:

            aveFrame = self.processedFrames.mean(axis = 0)
            hist = np.histogram(aveFrame, bins = 5)
            threshold = hist[1][-2]
            self.mask = aveFrame > threshold

    def map(self):
        """
        This will calculate a difference map between two images.  Ideally one pre-edge and one on resonance
        image.  It just does an automatic process for a two frame stack.
        :return:
        """
        if len(self.processedFrames) == 2:
            self.despike()
            self.alignFrames(mode = 'translation')
            self.calcOD()
            self.alignODFrames(sobelFilter = False, mode = 'homographic')
            self.map = self.odFrames[1] - self.odFrames[0]

    def calcOD(self, replaceZeros = 'one',spiral = False):
        """
        This calculates the OD is -log(I/I0).  If I0 is not already set it will use getI0Mask to estimate it.
        :param replaceZeros: why would we have zeroes?  who knows.  Why 'one'?  I have no idea.
        :return:
        """
        if len(self.I0rois) == 0: self.I0 = None
        if self.I0 is None:
            self.getIOMask(spiral = spiral)
            self.I0 = (self.processedFrames * self.mask).sum(axis = (1,2)) / self.mask.sum()
            self.I0 = np.reshape(self.I0, (len(self.I0),1,1))
        # if replaceZeros == 'one':
        #     self.processedFrames[self.processedFrames == 0.] = 1.
        self.odFrames = -np.log(self.processedFrames / self.I0)
        self.odFrames[np.isinf(self.odFrames)] = 0.
        self.gotOD = True
        self.preEdgeFrame = self.odFrames[0].copy()

    def despike(self, sigma = 3., od = False):
        """
        FIXME: sigma doesn't seem to work so it's hard coded below and this doesn't operate on the OD
        This applies a despike algorithm which is quite good in my humble opinion.  It works great for single
        pixel or single line spikes.
        :return:
        """
        self.update()
        for i in range(len(self.energies)):
            if od:
                d = self.odFrames[i].copy()
                df = medfilt(d,kernel_size = 3)
                idx = np.where(np.abs(df-d)>15.*(df-d).std())
                d[idx] = df[idx]
                self.odFrames[i] = d
                
            else:
                d = self.processedFrames[i].copy()
                df = medfilt(d, kernel_size=5)
                idx = np.where(np.abs(df - d) > 3. * (df - d).std())
                d[idx] = df[idx]
                self.processedFrames[i] = d
            # peakIndices = np.where(np.abs(filteredFrames[i] - self.processedFrames[i]) > \
            #                        sigma * np.abs(filteredFrames[i] - self.processedFrames[i]).std())
            # self.processedFrames[i][peakIndices] = filteredFrames[i][peakIndices]
        self.processedFrames = self.processedFrames[:,1:-1,1:-1]
        self.shape = self.processedFrames.shape

    def denoise(self, mode = 'nl', weight = 0.05):
        """
        Why not try to remove noise?  This applies some basic denoising algorithms with variable results.
        :param mode: string. 'tv', 'wavelet' or 'nl'
        :param weight: float.  make a good guess.
        :return:
        """
        self.update()
        if mode == 'tv':
            self.processedFrame = denoise_tv_chambolle(self.processedFrame, weight = weight, multichannel = False)
        elif mode == 'wavelet':
            self.processedFrame = denoise_wavelet(self.processedFrame, multichannel = False)
        elif mode == 'nl':
            for i in range(len(self.processedFrames)):
                self.processedFrames[i] = denoise_nl_means(self.processedFrames[i], h = weight)
        else:
            pass

    def wienerFilter(self, size = 3, axis = 2):
        """
        Applies a Wiener filter in 1 or 2 dimensions
        :param size: int. kernel size
        :param axis: int. 0 for X, 1 for Y, 2 for X and Y
        :return:
        """
        self.lastFrames = self.processedFrames.copy()
        if size is None: size = 3
        if axis is None: axis = 0
        for i in range(len(self.processedFrames)):
            if axis == 0:
                c = self.processedFrames[i].transpose().flatten()
                self.processedFrames[i] = np.reshape(wiener(c, mysize = size), \
                    (self.shape[2],self.shape[1])).transpose()
            elif axis == 1:
                c = self.processedFrames[i].flatten()
                self.processedFrames[i] = np.reshape(wiener(c, mysize = size), \
                    self.shape[1:3])
            else:
                self.processedFrames[i] = wiener(self.processedFrames[i], mysize = size)

    def medianFilter(self, size = 5, axis = 2, frames = None):
        """
        Applies a median filter in 1 or 2 dimensions
        :param size: int. kernel size
        :param axis: int. 0 for X, 1 for Y, 2 for X and Y
        :return:
        """
        if size % 2 == 0: size += 1
        if frames is None:
            self.lastFrames = self.processedFrames.copy()
            for i in range(len(self.processedFrames)):
                if axis == 0:
                    c = self.processedFrames[i].transpose().flatten()
                    self.processedFrames[i] = np.reshape(medfilt(c, kernel_size = size), \
                        (self.shape[2],self.shape[1])).transpose()
                elif axis == 1:
                    c = self.processedFrames[i].flatten()
                    self.processedFrames[i] = np.reshape(medfilt(c, kernel_size = size), \
                        self.shape[1:3])
                else:
                    self.processedFrames[i] = medfilt2d(self.processedFrames[i], kernel_size = size)
            self.processedFrames[self.processedFrames == 0.] = self.processedFrames.mean()
        else:
            for i in range(len(frames)):
                sh = frames.shape
                if axis == 0:
                    c = frames[i].transpose().flatten()
                    frames[i] = np.reshape(medfilt(c, kernel_size = size), \
                        (sh[2],sh[1])).transpose()
                elif axis == 1:
                    c = frames[i].flatten()
                    frames[i] = np.reshape(medfilt(c, kernel_size = size), \
                        sh[1:3])
                else:
                    frames[i] = medfilt2d(frames[i], kernel_size = size)
            frames[frames == 0.] = frames.mean()
            return frames

    def linFitSpectra(self, imageData, targetSpectra):
        """
        This method uses Singular Value Decomposition to solve for the maps of chemical weights.
        :param imageData: 3D numpy array (nEnergiesxMxN)
        :param targetSpectra: list. Each element is 1D numpy (nEnergies,1)
        :return:
        """
        nSpectra = len(targetSpectra) #list of spectra
        targetSpectra = np.vstack(targetSpectra) #convert to matrix
        imageData = np.transpose(imageData,axes = (1,2,0))
        nY, nX, nEnergies = imageData.shape
        retries = 5
        while retries > 0:
            try:
                U, s, V = np.linalg.svd(targetSpectra, full_matrices = False)
            except np.linalg.LinAlgError:
                retries -= 1
            else:
                break
        muInverse = np.dot(np.dot(V.T, np.linalg.inv(np.diag(s))), U.T)
        self.targetSVDmaps = np.dot(imageData, muInverse)
        self.targetSVDmaps = np.transpose(np.reshape(self.targetSVDmaps, (nY, nX, nSpectra), order = 'F').real, axes=(2,0,1))
        self.targetSVDmaps *= self.targetSVDmaps > 0.
        self.targetInverseSpectra = muInverse
        self.targetSpectra = targetSpectra

    def lstsqFit(self, imageData, targetSpectra):
        """
        This method uses least squares to solve for the maps of chemical weights.
        :param imageData: 3D numpy array (nEnergiesxMxN)
        :param targetSpectra: list. Each element is 1D numpy (nEnergies,1)
        :return:
        """
        nSpectra = len(targetSpectra) #list of spectra
        targetSpectra = np.vstack(targetSpectra).T #convert to matrix
        imageData = np.transpose(imageData,axes = (1,2,0))
        nY, nX, nEnergies = imageData.shape
        imageData = np.reshape(imageData, (nY * nX, nEnergies)).T
        s = np.linalg.lstsq(targetSpectra, imageData)
        self.rMap = np.reshape(s[1], (nY,nX))
        self.targetSVDmaps = np.reshape(s[0], (nSpectra,nY,nX))
        self.targetSVDmaps *= self.targetSVDmaps > 0.
        self.targetSpectra = targetSpectra.T

    def nnls(self, imageData, targetSpectra):
        """
        This method uses non-negative least squares to solve for the maps of chemical weights.
        :param imageData: 3D numpy array (nEnergiesxMxN)
        :param targetSpectra: list. Each element is 1D numpy (nEnergies,1)
        :return:
        """
        nSpectra = len(targetSpectra) #list of spectra
        targetSpectra = np.vstack(targetSpectra).T #convert to matrix
        imageData = np.transpose(imageData,axes = (1,2,0))
        nY, nX, nEnergies = imageData.shape
        imageData = np.reshape(imageData, (nY * nX, nEnergies)).T
        X = np.zeros((nSpectra, imageData.shape[1]))
        resids_nnls = np.zeros(imageData.shape[1]) 

        for i in np.arange(imageData.shape[1]):
            X[:, i], resids_nnls[i] = scipy.optimize.nnls(targetSpectra, imageData[:, i])
        self.rMap = np.reshape(resids_nnls, (nY,nX))
        self.targetSVDmaps = np.reshape(X, (nSpectra,nY,nX))
        self.targetSpectra = targetSpectra.T

    def nlMeansFilter(self, frames = None):
        """
        Applies a non-local means filter in 2 dimensions
        :param frames: 3D numpy array (nEnergiesxMxN)
        :return:
        """
        if frames == None:
            self.lastFrames = self.processedFrames.copy()
            for i in range(len(self.rawFrames)):
                sigma_est = np.mean(estimate_sigma(self.processedFrames[i], multichannel=False))
                self.processedFrames[i] = denoise_nl_means(self.processedFrames[i], \
                    h=0.6 * sigma_est, sigma=sigma_est,
                    fast_mode=True)
        else:
            filteredFrames = frames.copy()
            for i in range(len(frames)):
                sigma_est = np.mean(estimate_sigma(filteredFrames[i], multichannel=False))
                filteredFrames[i] = denoise_nl_means(filteredFrames[i], \
                    h=0.6 * sigma_est, sigma=sigma_est,
                    fast_mode=True)
            return filteredFrames


    def sobelFilter(self, frames = None):
        """
        Applies a Sobel filter in 2 dimensions.  This is used during image registration.
        :param frames: 3D numpy array (nEnergiesxMxN)
        :return:
        """
        if frames == None:
            self.lastFrames = self.processedFrames.copy()
            for i in range(len(self.rawFrames)):
                self.processedFrames[i] = sobel(self.processedFrames[i])
        else:
            filteredFrames = frames.copy()
            for i in range(len(frames)):
                filteredFrames[i] = sobel(frames[i])
            return filteredFrames

    def _ecc_align(self, dst_image, src_image, sobel = False, mode = 'translation', num_iterations = 5000, eps = 1e-5):
        """
        This function is not working properly and needs to be fixed!
        ecc_align function performs either a translation (warp_mode = 0), rigid/euclidean (warp_mode = 1),
        affine (warp_mode = 2) or homographic (warp_mode = 3) alignment of a src_img with respect to
        a dst_img
        """

        if mode == 'translation': warp_mode = cv2.MOTION_TRANSLATION
        elif mode == 'rigid': warp_mode = cv2.MOTION_EUCLIDEAN
        elif mode == 'affine': warp_mode = cv2.MOTION_AFFINE
        elif mode == 'homographic': warp_mode = cv2.MOTION_HOMOGRAPHY

        src_image = src_image.astype('float32')
        dst_image = dst_image.astype('float32')
        mask = (dst_image > 0.).astype('uint8') #np.ones(src_image.shape).astype('uint8')

        # Define 2x3 or 3x3 matrices and initialize the matrix to identity
        if warp_mode == cv2.MOTION_HOMOGRAPHY:
            self.warp_matrix = np.eye(3, 3, dtype=np.float32)
        else:
            self.warp_matrix = np.eye(2, 3, dtype=np.float32)

        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, num_iterations, eps)
        try:
            (cc, self.warp_matrix) = cv2.findTransformECC(dst_image, src_image,\
                    self.warp_matrix, warp_mode, criteria, mask,3)
        except:
            print("CV2 findTransform failed.")

        if warp_mode == cv2.MOTION_HOMOGRAPHY:
            # Use warpPerspective for Homography
            src_image = cv2.warpPerspective(src_image, self.warp_matrix, dst_image.shape[::-1],
                                             flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
        else:
            # Use warpAffine for Translation, Euclidean and Affine
            src_image = cv2.warpAffine(src_image, self.warp_matrix, dst_image.shape[::-1],
                                        flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
        return src_image


    def calcPCA(self, nPC = 4, pcaOffset = 0, nClusters = 4, clustering = 'kmeans'):
        """
        This function calls pcaFilterImages which computes a representation of the odFrames using a
        reduced number of principal components (pca.inverse_transform(nPC)).  This is used to reduce noise.  It also generates pcaImages
        which is dot(odFrames,eigenVectors).  Clustering currently is performed on pcaImages but this
        should be changed to pcaFilteredImages to reduce impact of noise.  Alternatively, one could compute
        dot(odFrames, eigenVectors(nPC)) for clustering.
        :param nPC: int.  Number of principal components to include in the decomposition.
        :param pcaOffset: int.  0 or 1.  Set to 1 to ignore the first PC and reduce mass thickness effects
        :param nClusters: int.  Number of clusters to generate.  This fails for large numbers of clusters.
        :param clustering: string.  Clustering algorithm.  dbscan is not working yet.
        :return:
        """
        if self.odFrames is not None:
            self.pcaFilterImages(nPC = nPC)
            if clustering == 'kmeans':
                self.kmeansClusters(nClusters = nClusters, pcaOffset = pcaOffset)
            elif clustering == 'dbscan':
                self.dbscanClusters(nClusters = nClusters, pcaOffset = pcaOffset)
            self.nnls(self.filteredImages, self.clusterSpectra)
            self.calcRFactor()
            
    def calcNMF(self, iterations = 100000, nClusters = 4, clustering = 'kmeans'):
        self.nEnergies, self.nY, self.nX = self.odFrames.shape
        self.nPixels = self.nY * self.nX
        p = np.reshape(np.transpose(self.odFrames, axes = (1,2,0)), (self.nPixels, self.nEnergies), order = 'F')
        self.model = NMF(init='random', max_iter = 1000, random_state=0)
        self.W = self.model.fit_transform(X)
        self.H = self.model.components_
        
        self.nmfImages = np.transpose(np.reshape(np.dot(p, ),(self.nY, self.nX, self.nEnergies), order = 'F'), axes = (2,0,1))
        self.pca = PCA(n_components = nPC)
        self.pca.fit(p)
        c_pca = self.pca.transform(p)
        self.filteredImages = self.pca.inverse_transform(c_pca)
        self.filteredImages = np.transpose(np.reshape(self.filteredImages, (self.nY, self.nX, self.nEnergies), order = 'F'), axes = (2,0,1))
    		

    def kmeansClusters(self, nClusters = 3, pcaOffset = 0):
        """
        Execute the kmeans2 clustering algorithm on the pcaImages.  pcaImages is dot(odFrames, eigenVectors)
        :param nClusters: int.  Number of clusters to generate.  Fails for large number of clusters.
        :param pcaOffset: int. 0 or 1.  Set to 1 to ignore the first PC and reduce mass thickness effects
        :return:
        """
        if self.pcaImages is not None:
            self.clusters = np.zeros(self.nPixels)
            res, self.clusters = kmeans2(np.reshape(np.transpose(self.pcaImages, \
                axes = (1,2,0))[:,:,pcaOffset:nClusters + pcaOffset],(self.nPixels, \
                nClusters), order = 'F'), nClusters)
            self.clusters = np.reshape(self.clusters, (self.nY, self.nX), order = 'F')
            self.clusterSpectra = []
            for i in range(nClusters):
                thisClusterSpectrum = (self.odFrames * (self.clusters == i)).sum(axis = (1,2)) / (self.clusters == i).sum()
                thisClusterSpectrum[np.isnan(thisClusterSpectrum)] = 0.
                self.clusterSpectra.append(thisClusterSpectrum)

    def dbscanClusters(self, nClusters = 3, pcaOffset = 0):
        """
        Execute the dbscan clustering algorithm on the pcaImages. pcaImages is dot(odFrames, eigenVectors)
        :param nClusters: int.  Number of clusters to generate.  Fails for large number of clusters.
        :param pcaOffset: int. 0 or 1.  Set to 1 to ignore the first PC and reduce mass thickness effects
        :return:
        """
        if self.pcaImages is not None:
            X = np.reshape(np.transpose(self.pcaImages, axes = (1,2,0))[:,:,pcaOffset:nClusters + pcaOffset],(self.nPixels, \
                nClusters), order = 'F')
            #X = StandardScaler().fit_transform(X)
            db = DBSCAN(eps=0.3, min_samples=10).fit(X)
            core_samples_mask = np.zeros_like(db.labels_, dtype=bool)
            core_samples_mask[db.core_sample_indices_] = True
            labels = db.labels_
            self.clusters = np.reshape(labels, (self.nY, self.nX), order = 'F')
            self.clusterSpectra = []
            for i in range(nClusters):
                cnorm = (self.clusters == i).sum()
                thisClusterSpectrum = (self.odFrames * (self.clusters == i)).sum(axis = (1,2)) / cnorm
                self.clusterSpectra.append(thisClusterSpectrum)

    def pcaFilterImages(self, nPC = 5):
        """
        This uses the sklearn.decomposition.pca to compute eigenVectors and eigenVals from the odFrames.
        It then computes pcaImages which is dot(odFrames,eigenVectors) and pcaFilteredImages which
        is pca.inverse_transform(nPC).  filteredImages is a model of the data with noisy components
        removed.  pcaImages is a representation of all eigenVectors as (nEnergiesxMxN).
        :param nPC: int.  Number of components to use in pcaFilteredImages
        :return:
        """
        self.nEnergies, self.nY, self.nX = self.odFrames.shape
        self.nPixels = self.nY * self.nX
        p = np.reshape(np.transpose(self.odFrames, axes = (1,2,0)), (self.nPixels, self.nEnergies), order = 'F')
        self.pca = PCA(n_components = self.nEnergies)
        self.pca.fit(np.dot(p.T,p.conjugate()))
        perm = np.argsort(-np.abs(self.pca.explained_variance_))
        self.eigenVals = self.pca.explained_variance_[perm]
        self.eigenVecs = self.pca.components_[:,perm].T
        self.pcaImages = np.transpose(np.reshape(np.dot(p, self.eigenVecs),(self.nY, self.nX, self.nEnergies), order = 'F'), axes = (2,0,1))
        self.pca = PCA(n_components = nPC)
        self.pca.fit(p)
        c_pca = self.pca.transform(p)
        self.filteredImages = self.pca.inverse_transform(c_pca)
        self.filteredImages = np.transpose(np.reshape(self.filteredImages, (self.nY, self.nX, self.nEnergies), order = 'F'), axes = (2,0,1))

    def calcRFactor(self, mode = 'pca'):
        """
        Calculates the R-factor of PCA fit.  This is dumb.  This should calculate the R-factor of the
        spectral fit calculated by rgbMap.
        :param mode: string
        :return:
        """
        if mode == 'pca':
            self.rMap = np.sqrt(((self.filteredImages - self.odFrames)**2).sum(axis = 0)/(self.odFrames**2).sum(axis = 0))
            self.rMap = self.rMap.clip(min = 0, max = 0.1)
        elif mode == 'svd':
            pass

    def rgbMap(self, targetSpectra, rgb, mode = 'nnls'):
        """
        Uses the selected fitting routine to calculate a linear combination fit of targetSpectra to the
        filteredImages.
        :param targetSpectra: list of 1D numpy arrays of (nEnerges,1)
        :param rgb: length three list. (1,1,0) for red and green for examle.
        :param mode: string.  Fitting routine to use.
        :return:
        """
        nColors = sum(rgb)
        if len(targetSpectra) != nColors:
            return
        if nColors < 2:
            return
        if mode == 'svd':
            self.linFitSpectra(self.filteredImages, targetSpectra)
        elif mode == 'lstsq':
            self.lstsqFit(self.filteredImages, targetSpectra)
        elif mode == 'nnls':
            self.nnls(self.filteredImages, targetSpectra)
        self.rgbImage = np.zeros((self.nY, self.nX, 3), dtype = 'uint8')
        svdMaps = self.targetSVDmaps.copy()
        svdMaps = 255. * svdMaps / svdMaps.max()
        svdMaps = svdMaps.astype('uint8')
        if nColors == 3:
            for i in range(nColors): self.rgbImage[:,:,i] = svdMaps[i]
        else:
            if rgb[0] == 0:
                for i in range(nColors): self.rgbImage[:,:,i + 1] = svdMaps[i]
            elif rgb[1] == 0:
                self.rgbImage[:,:,0] = svdMaps[0]
                self.rgbImage[:,:,2] = svdMaps[1]
            else:
                self.rgbImage[:,:,0] = svdMaps[0]
                self.rgbImage[:,:,1] = svdMaps[1]

    def rgbClusterMap(self):
        """
        Creates an RGB image of the cluster map.
        :return:
        """
        ny, nx = self.clusters.shape
        nClusters = self.clusters.max() + 1
        rgbClusterImage = np.zeros((ny,nx,3))
        for i in range(nClusters):
            rgbClusterImage += 255.* np.transpose(np.ones((3,ny,nx)) * (self.clusters == i).astype('float32'), \
                axes = (1,2,0)) * self.penColors[i]
        return rgbClusterImage.astype('uint8')

    def writeHeader(self,f,fileHeader):
        """
        Writes some text into the top of the CSV file that contains the output spectra.
        :param f:
        :param fileHeader:
        :return:
        """
        for key in fileHeader.keys():
            f.write(key + ',' + str(fileHeader[key]) + '\n')

    def saveAll(self, filePrefix = ''):
        """
        Saves a bunch of stuff to the output directory.
        :param filePrefix:
        :return:
        """
        dataDir,dataFile = os.path.split(self.fileName)
        filePrefix = dataFile.split('.')[0] + '_%s' %filePrefix
        if self.targetSVDmaps is not None:
            saveDir = os.path.join(dataDir, filePrefix + '_pystxmOutput_' + str(calendar.timegm(time.gmtime())))
            os.mkdir(saveDir)
            spectrumCSVFile = os.path.join(saveDir,'SVDspectra.csv')
            clusterSpectraCSVFile = os.path.join(saveDir, 'ClusterSpectra.csv')
            fileHeader = {  'STXM File: ': dataFile, \
                            'Dark Field Offset: ': self.darkField, \
                            'Data type: ': 'Optical density',\
                            'Column Headings': 'Energy, I0, Target Spectra'}

            ##save the target spectra
            if self.targetSpectra is not None:
                f = open(spectrumCSVFile,'w')
                self.writeHeader(f,fileHeader)
                nEnergies, nSpectra = self.targetSpectra.shape
                for i in range(nEnergies):
                    thisStr = str(self.energies[i]) + ',' + str(self.I0[i])
                    for j in range(nSpectra):
                        thisStr += ',' + str(self.targetSpectra[i,j])
                    thisStr += '\n'
                    f.write(thisStr)#.encode('utf8'))
                f.close()

            ##save the cluster spectra
            I0 = np.reshape(self.I0, (len(self.I0),))
            if self.clusterSpectra is not None:
                f = open(clusterSpectraCSVFile,'w')
                self.writeHeader(f,fileHeader)
                nSpectra = len(self.clusterSpectra)
                nEnergies = len(self.clusterSpectra[0])
                for i in range(nEnergies):
                    thisStr = str(self.energies[i]) + ',' + str(I0[i])
                    for j in range(nSpectra):
                        thisStr += ',' + str(self.clusterSpectra[j][i])
                    thisStr += '\n'
                    f.write(thisStr)#.encode('utf8'))
                    #print(thisStr, I0[i], str(I0[i]))
                f.close()

            ##save the stack of aligned intensity frames
            stackFile = os.path.join(saveDir,"intenstyFrames.tif")
            imsave(stackFile, self.processedFrames.astype('float32'))

            if self.odFrames is not None:
                ##save the stack of OD frames
                stackFile = os.path.join(saveDir,"odFrames.tif")
                imsave(stackFile, self.odFrames.astype('float32'))

            if self.filteredImages is not None:
                ##save the stack of PCA filtered frames
                stackFile = os.path.join(saveDir,"pcaFrames.tif")
                imsave(stackFile, self.filteredImages.astype('float32'))

            if self.pcaImages is not None:
                ##save the stack of PCA components
                stackFile = os.path.join(saveDir,"pcaComponents.tif")
                imsave(stackFile, self.pcaImages.astype('float32'))

            if self.rMap is not None:
                rFile = os.path.join(saveDir,"rMap.tif")
                imsave(rFile, self.rMap.astype('float32'))

            if self.rgbImage is not None:
                ##save the RGB component map
                imsave(os.path.join(saveDir, 'rgbMap.jpg'), self.rgbImage)
                
            ##save the RGB cluster map
            imsave(os.path.join(saveDir, 'rgbClusterMap.jpg'), self.rgbClusterMap())

            ##save the component maps
            for i in range(len(self.targetSVDmaps)):
                imsave(os.path.join(saveDir, "map_" + str(i) + '.tif'), \
                    self.targetSVDmaps[i].astype('float32'))

            ##pyplot of all target spectra
            labels = []
            plt.figure()
            for i in range( self.clusters.max() + 1):
                plt.plot(self.energies, self.clusterSpectra[i], color = self.penColors[i])
                labels.append('Cluster %i' %i)
            plt.legend(labels)
            plt.xlabel('Energy (eV)')
            plt.ylabel('Optical Density')
            plt.title(self.fileName)
            plt.savefig(os.path.join(saveDir,'spectra.png'), dpi = 100)

            ##plot PCA eigenvalues
            plt.figure()
            plt.plot(np.log(self.eigenVals[:-1]),'bo')
            plt.xlabel('Component Number')
            plt.ylabel('Eigen Value')
            plt.title(self.fileName)
            plt.savefig(os.path.join(saveDir,'pcaEigenValues.png'), dpi = 100)
            plt.clf()

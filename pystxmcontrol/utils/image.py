import skimage as sk
from pystxmcontrol.utils.writeNX import *
from skimage.restoration import (denoise_tv_chambolle, denoise_bilateral,
                                 denoise_wavelet, estimate_sigma, denoise_nl_means, unwrap_phase)
import matplotlib.pyplot as plt
import cv2
import scipy as sc

def despike(image):
    filteredImage = medianFilter(image)
    peakIndices = np.where(np.abs(filteredImage - image) > 3. * np.abs(filteredImage - image).std())
    image[peakIndices] = filteredImage[peakIndices]
    return image[1:-1, 1:-1]

def medianFilter(image, size = 3, axis = 2):

    if size % 2 == 0: size += 1
    sh = image.shape
    if axis == 0:
        c = image.transpose().flatten()
        image = np.reshape(sc.signal.medfilt(c, kernel_size = size), sh).transpose()
    elif axis == 1:
        c = image.flatten()
        image = np.reshape(sc.signal.medfilt(c, kernel_size = size), sh)
    else:
        image = sc.signal.medfilt2d(image, kernel_size = size)
    image[image == 0.] = image.mean()
    return image

class image(object):

    def __init__(self, data = None, file = None, regNum = 0):

        self.hdr = None
        self.nC = 1.0
        self.regNum = regNum
        self.regStr = 'Region' + str(self.regNum)

        if data is None and file is None:
            self.data = sk.data.camera()
            self.energy = 700.0
            self.nypixels, self.nxpixels = self.data.shape
        elif file is not None:
            self.open(file)
        elif data is not None:
            self.data = data
            self.energy = 700.0
            self.angle = 0.
            self.nypixels, self.nxpixels = self.data.shape

        self.imageChannel = 'V/F'
        self.normalizationChannels = ['PhotoDiode','LeftSlit']

        self.initialize()

    def initialize(self):
        self.processedFrame = self.data.copy()
        self.lastFrame = self.processedFrame.copy()

    def open(self, fileName):
        if '.hdr' in fileName:
            self.hdr = Read_header(fileName)
            self.data = readASCIIMatrix(self.hdr[self.regStr][self.hdr['DefaultChannel']]['files'][0])
            self.energy = self.hdr[self.regStr]['energies'][0]
            self.pixnm = self.hdr[self.regStr]['xstep']
            self.xpixelsize = self.hdr[self.regStr]['xstep']
            self.ypixelsize = self.hdr[self.regStr]['ystep']
            self.dwell = self.hdr['dwell']
            self.nxpixels, self.nypixels = self.data.shape
            self.angle = self.hdr['angle']
            self.type = self.hdr['type']
        elif '.cxi' in fileName:
            pass
        elif '.stxm' in fileName:
            self.nx = stxm(stxm_file = fileName)
            self.data = self.nx.data["entry0"]["counts"]
            print(self.data.shape)
            nz,ny,nx = self.data.shape
            self.data = np.reshape(self.data[0],(ny,nx))
            self.energy = self.nx.data["entry0"]["energy"][0]
            self.xpixelsize = self.nx.data["entry0"]["xstepsize"]
            self.ypixelsize = self.nx.data["entry0"]["ystepsize"]
            self.nypixels, self.nxpixels = ny,nx
            self.dwell = self.nx.data["entry0"]["dwell"][0]
            self.type = self.nx.meta["scan_type"]
        else:
            print("Unsupported file type")

    def __getpc(self, frame):
        frame = unwrap_phase(-np.log(frame).imag)
        mask = self.getmask(frame)
        x,y = np.arange(0, frame.shape[1]),np.arange(0,frame.shape[0])
        xp,yp = np.meshgrid(x,y)
        xm,ym,zm = xp[mask], yp[mask], frame[mask]
        m = polyfit2d(xm,ym,zm,order = 2)
        bgFit = polyval2d(xp.astype('float64'),yp.astype('float64'),m)
        frame = frame + bgFit
        frame -= frame.min()
        return frame


    def magnitude(self):
        """
        Returns a new class instance representing the magnitude of the input
        :return:
        """
        newImage = image()
        newImage.__dict__ = self.__dict__.copy()
        newImage.data = np.abs(newImage.data)**2
        newImage.processedFrame = newImage.data.copy()
        return newImage

    def phase(self):
        """
        Returns a new class instance representing the phase of the input
        :return:
        """
        newImage = image()
        newImage.__dict__ = self.__dict__.copy()
        newImage.data = -np.log(newImage.data).imag #self.__getpc(newImage.data)
        newImage.processedFrame = newImage.data.copy()
        return newImage

    def scattering(self):
        newImage = image()
        newImage.__dict__ = self.__dict__.copy()
        pc = self.__getpc(newImage.data)
        od = self.estimateOD(np.abs(newImage.data))
        newImage.data = np.sqrt(pc**2 + od**2)
        return newImage

    def getmask(self, frame, sigma = 3):

        self.mask = getIOMask(sc.ndimage.filters.gaussian_filter(np.abs(frame) / np.abs(frame).max(), sigma = sigma))
        return self.mask

    def undo(self):
        self.processedFrame = self.lastFrame.copy()

    def readHDR(self, hdrFile):
        self.hdr = Read_header(hdrFile)
        #ximFile = a['files'][0][0]
        ximFile = self.hdr[self.regStr][imageChannel]['files'][0]
        self.data = readASCIIMatrix(ximFile)
        self.energy = a['energies'][0]
        self.nypixels, self.nxpixels = self.data.shape
        self.initialize()

    def update(self):
        self.lastFrame = self.processedFrame.copy()

    def despike(self):
        self.update()
        filteredFrame = self.medianFilter(frame = self.processedFrame.copy())
        peakIndices = np.where(np.abs(filteredFrame - self.processedFrame) > 3. * np.abs(filteredFrame - \
                                                                                         self.processedFrame).std())
        self.processedFrame[peakIndices] = filteredFrame[peakIndices]
        self.processedFrame = self.processedFrame[1:-1,1:-1]
        self.shape = self.processedFrame.shape

    def getIOMask(self):
        hist = np.histogram(self.processedFrame, bins = 5)
        threshold = hist[1][-2]
        self.mask = self.processedFrame > threshold

    def estimateOD(self, frame = None):
        if frame is None:
            self.update()
            self.getIOMask()
            self.I0 = (self.processedFrame * self.mask).sum() / self.mask.sum()
            self.processedFrame = -np.log(self.processedFrame / self.I0)
        else:
            self.getIOMask()
            self.I0 = (frame * self.mask).sum() / self.mask.sum()
            return -np.log(frame / self.I0)

    def wienerFilter(self, size = 3, axis = 2):
        self.update()
        if size is None: size = 3
        if axis is None: axis = 0
        sh = self.processedFrame.shape
        if axis == 0:
            c = self.processedFrame.transpose().flatten()
            self.processedFrame = np.reshape(sc.signal.wiener(c, mysize = size), sh).transpose()
        elif axis == 1:
            c = self.processedFrame.flatten()
            self.processedFrame = np.reshape(sc.signal.wiener(c, mysize = size), sh)
        else:
            self.processedFrame = sc.signal.wiener(self.processedFrame, mysize = size)

    def medianFilter(self, size = 3, axis = 2, frame = None):
        self.update()
        if size % 2 == 0: size += 1
        if frame is None:
            sh = self.processedFrame.shape
            if axis == 0:
                c = self.processedFrame.transpose().flatten()
                sh = self.processedFrame.transpose().shape
                self.processedFrame = np.reshape(sc.signal.medfilt(c, kernel_size = size), sh).transpose()
            elif axis == 1:
                c = self.processedFrame.flatten()
                self.processedFrame = np.reshape(sc.signal.medfilt(c, kernel_size = size), sh)
            else:
                self.processedFrame = sc.signal.medfilt2d(self.processedFrame, kernel_size = size)
            self.processedFrame[self.processedFrame == 0.] = self.processedFrame.mean()
        else:
            sh = frame.shape
            if axis == 0:
                c = frame.transpose().flatten()
                frame = np.reshape(sc.signal.medfilt(c, kernel_size = size), sh).transpose()
            elif axis == 1:
                c = frame.flatten()
                frame = np.reshape(sc.signal.medfilt(c, kernel_size = size), sh)
            else:
                frame = sc.signal.medfilt2d(frame, kernel_size = size)
            frame[frame == 0.] = frame.mean()
            return frame

    def highPassFilter(self, frame = None, fs = 500, order = 5, cutoff = 100):
        if frame is not None:
            sh = frame.shape
            nyq = 0.5 * fs
            normal_cutoff = cutoff / nyq
            b, a = sc.signal.butter(order, normal_cutoff, btype='high', analog=False)
            frame = np.reshape(sc.signal.filtfilt(b, a, frame.flatten()), sh)
            return frame
        else:
            self.update()
            sh = self.processedFrame.shape
            nyq = 0.5 * fs
            normal_cutoff = cutoff / nyq
            b, a = sc.signal.butter(order, normal_cutoff, btype='high', analog=False)
            self.processedFrame = np.reshape(sc.signal.filtfilt(b, a, self.processedFrame.flatten()), sh)

    def denoise(self, mode = 'nl', weight = 0.05):
        self.update()
        if mode == 'tv':
            self.processedFrame = denoise_tv_chambolle(self.processedFrame, weight = weight, multichannel = False)
        elif mode == 'wavelet':
            self.processedFrame = denoise_wavelet(self.processedFrame, multichannel = False)
        elif mode == 'nl':
            self.processedFrame = denoise_nl_means(self.processedFrame, h = weight)
        else:
            pass

    def display(self):
        plt.matshow(self.processedFrame);plt.colorbar();plt.show()

    def warpImage(self, warp_matrix, warp_mode = 'translation'):

        if warp_mode == 'translation': warp_mode = cv2.MOTION_TRANSLATION
        elif warp_mode == 'rigid': warp_mode = cv2.MOTION_EUCLIDEAN
        elif warp_mode == 'affine': warp_mode = cv2.MOTION_AFFINE
        elif warp_mode == 'homographic': warp_mode = cv2.MOTION_HOMOGRAPHY

        shape = self.processedFrame.shape

        if warp_mode == cv2.MOTION_TRANSLATION:
            shifts = warp_matrix[0,2], warp_matrix[1,2]
            src_image = ndimage.interpolation.shift(self.processedFrame, shifts, mode='wrap')

        elif warp_mode == cv2.MOTION_HOMOGRAPHY:
            # Use warpPerspective for Homography
            src_image = cv2.warpPerspective(self.processedFrame, warp_matrix, (shape[1], shape[0]),
                                             flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
        else:
            # Use warpAffine for Translation, Euclidean and Affine
            src_image = cv2.warpAffine(self.processedFrame, warp_matrix, (shape[1], shape[0]),
                                        flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)
        src_image[src_image == 0.] = src_image.mean()
        return src_image

    def resample(self, pixelSize = None):
        if pixelSize is None:
            print("Missing argument: pixelSize = micrometers.")
            return

        yr,xr = self.ypixelsize * (self.nypixels + 1), self.xpixelsize * (self.nxpixels + 1)
        x,y = np.meshgrid(np.linspace(0,xr,self.nxpixels+1),np.linspace(0,yr,self.nypixels+1))
        xScale, yScale = self.xpixelsize / pixelSize, self.ypixelsize / pixelSize
        xp,yp = np.meshgrid(np.linspace(0,xr, round(self.nxpixels * xScale)),\
                         np.linspace(0, yr, round(self.nypixels * yScale)))

        x0 = x[0,0]
        y0 = y[0,0]
        dx = x[0,1] - x0
        dy = y[1,0] - y0
        ivals = (xp - x0)/dx
        jvals = (yp - y0)/dy
        coords = np.array([jvals, ivals])

        self.processedFrame = sc.ndimage.map_coordinates(self.processedFrame, coords)
        self.xpixelsize, self.ypixelsize = pixelSize, pixelSize
        self.nypixels, self.nxpixels = self.processedFrame.shape
        self.update()

    def crop(self, shape = None, center = None):
        if shape is None:
            return
        if center is None:
            center = self.processedFrame.shape[0] // 2, self.processedFrame.shape[1] // 2
        ystart = center[0] - shape[0] // 2
        ystop = ystart + shape[0]
        xstart = center[1] - shape[1] // 2
        xstop = xstart + shape[1]
        sh = self.processedFrame.shape
        newData = np.ones(shape) * self.processedFrame.mean()
        ynstart,xnstart = 0,0
        ynstop, xnstop = newData.shape
        if xstart < 0:
            xnstart = -xstart
            xstart = 0
        if xstop > sh[1]:
            xnstop = -(xstop - sh[1])
            xstop = sh[1]
        if ystart < 0:
            ynstart = -ystart
            ystart = 0
        if ystop > sh[0]:
            ynstop = -(ystop - sh[0])
            ystop = sh[0]
        newData[ynstart:ynstop,xnstart:xnstop] = self.processedFrame[ystart:ystop,xstart:xstop]
        self.processedFrame = newData.copy()

    def pad(self, shape = None):
        if shape is None:
            return
        y,x = self.processedFrame.shape
        yn,xn = shape
        newData = np.zeros((yn,xn))
        xStart = xn // 2 - x // 2
        xStop = xStart + x
        yStart = yn // 2 - y // 2
        yStop = yStart + y
        newData[yStart:yStop,xStart:xStop] = self.processedFrame
        self.processedFrame = newData.copy()

    def getINormalizationData(self):
        self.normFrames = []
        for channel in self.normalizationChannels:
            fileName = self.hdr[self.regStr][channel]['files'][0]
            im = image(data = readASCIIMatrix(fileName))
            im.energy = self.hdr['energies'][0]
            im.xpixelsize = self.hdr[self.regStr]['xstep']
            im.ypixelsize = self.hdr[self.regStr]['ystep']
            im.nypixels, im.nxpixels = im.data.shape
            self.normFrames.append(im)

    def calcINormalization(self):
        if self.hdr is not None:
            from scipy.optimize import minimize
            from math import isnan
            self.lastFrame = self.processedFrame
            self.iNorm = np.zeros((self.processedFrame.shape))
            
            a = self.processedFrame
            b = self.normFrames[0].data
            c = self.normFrames[1].data
            fun = lambda x: (a[0,:] / (1. + x[0] * (b[0,:] - c[0,:]) / (b[0,:] + c[0,:]))).std()
            self.nC = minimize(fun, (1,), method='CG').x[0]
            if isnan(self.nC): self.nC = 1.
            print(self.nC)
            self.iNorm = (1. + self.nC * (b - c) / (b + c))
            self.processedFrame /= self.iNorm 
            self.processedFrame[self.processedFrame < 1.] = self.processedFrame.mean()




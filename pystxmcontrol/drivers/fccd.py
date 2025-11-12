"""Code specific to the FCCD detector, including scrambling/descrambling, masking, bad-pixels, etc..."""
import numpy as np
import scipy.special as special
import scipy.signal as signal
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm


class FCCD:
    """Detector corrections and pre-processing for the fCCD.
    
    This modules has been tested with data from the ALS.
    """

    def __init__(self, hnu=15, nbcol=12, nbpcol=10, nb=16, nmux=12, nrows=970, width=1940, height=1152,
                 croppedWidth=960, croppedHeight=960, frameWidth=256, frameHeight=256,
                 pixelsize=30e-6, beamstop_radius=1.83e-3, beamstop_transmission=1e-2,
                 beamstop_xshift=-5, beamstop_yshift=-2, rotate=True):
        """
        Initialize the detector object.

        Parameters
        ----------
        hnu : int
            Gain, default = 15
        nbcol : int
            Nr. of columns per block, default = 12
        nbpcol : int
            Nr. of physical columns per block, default = 10
        nb : int
            Nr. of blocks, default = 16
        nmux : int
            Nr. of mux, default = 12
        nrows : int
            Nr. of rows, default = 970
        width : int
            With of assembled image, default = 1940
        height : int
            Height of assembled image, default = 1152
        croppedWidth : int 
            With of cropped image, default = 960
        croppedHeight : int
            Height of cropped image, default = 960
        frameWidth : int
            Width of reduced (filtered) image, default = 256
        frameHeight : int
            Height of reduced (filtered) image, default = 256
        pixelsize : float
            Size of a pixel in [m], default = 30e-6
        beamtsop_radius : float
            Radius of beamstop in [m], default = 1.83e-3
        beamstop_transmission : float
            Transmission of beamstop, default = 1e-2
        """
        self._hnu = hnu  # Gain
        self._nbcol = nbcol  # Nr. of columns per block
        self._nbpcol = nbpcol  # Nr. of physical columns per block
        self._nb = nb  # Nr. of blocks
        self._nmux = nmux  # Nr. of mux
        self._nrows = nrows  # Nr. of rows
        self._width = width  # Width of assembled image
        self._height = height  # Height of assembled image

        # Derived detector dimensions
        self._nbmux = self._nb * self._nmux  # Nr. of ADC channels
        self._ncols = self._nbcol * self._nb * self._nmux  # Nr. of columns
        self._npcols = self._nbpcol * self._nb * self._nmux  # Nr. of physical columns

        # Initialize rawdata//bgstd with zeros
        self.rawdata = np.zeros((self._height * self._width // self._nbmux, self._nbmux))
        self.bgstd = np.zeros((self._height * self._width // self._nbmux, self._nbmux))

        # Clock
        self._tadc = np.arange(1, self._nbcol * self._nrows + 1).astype('float').reshape(
            (1, self._nbcol * self._nrows))

        # Index mapping
        q1 = np.arange(self._nbmux, dtype=np.int16)
        q2 = ((self._nbmux - q1 - 1) % self._nmux) * self._nb
        q3 = 4 * np.floor(q1 / (self._nmux * 4))
        q4 = np.floor((self._nbmux - q1 - 1) / self._nmux) % 4
        self._q = ((q2 + self._nb - q3) - q4).astype(np.int16) - 1
        self._iq = np.arange(self._q.shape[0])
        self._iq[self._q] = np.arange(self._q.shape[0])
        self._gii = (np.arange(self._npcols // 2) + np.floor((np.arange(self._npcols // 2)) / self._nbpcol) * 2).astype(
            np.intc)
        self._aii = (np.arange(self._ncols // 2) + np.floor(
            (np.arange(self._ncols // 2)) / (self._nbmux * self._nbcol)) * 2).astype(np.intc)

        # Bad pixel mask
        self._mskt = (self._tadc < ((self._nrows - 1) * self._nbcol + 1)) & (self._tadc > ((2) * self._nbcol))
        # self._mskt[0,7692] = False # This is a hack to remove some artefacts (there might be a better way to do this)
        # self._mskt[0,7694:7704] = False # This is a hack to remove some artefacts (there might be a better way to do this)
        # self._mskt[0,7705:7716] = False # This is a hack to remove some artefacts (there might be a better way to do this)
        self._mskadc = np.ones(self._nbmux).astype(np.bool_)
        # self._mskadc[82:96] = False
        # self._mskadc[104]   = False
        # self._mskadc[191]   = False
        # self._mskadc[96]    = False

        # Vandermonde filer 
        t1 = self._tadc - np.min(self._tadc)
        t1 = t1 / np.max(t1) - 0.5
        tt1 = 0.5 - t1
        toffset = 0.6
        tt2 = (tt1 - toffset) * (tt1 > toffset) * special.erf((tt1 - toffset) * 2)
        # vanderX = np.vstack([np.ones_like(t1), tt1, tt1**2, tt2, tt2**2])
        vanderX = np.vstack([np.ones_like(t1), tt1, tt1 ** 2])
        # vanderX = np.vstack([np.ones_like(t1)])
        msktoffset1 = (self._tadc > (2 * self._nbcol)) & (
                    ((self._tadc - 2) % self._nbcol) > 9)  # this is corret (mask only every 10th block)
        # msktoffset  = msktoffset1 & (self._tadc < ((self._nrows - 100)*self._nbcol))
        msktoffset = msktoffset1 & (self._tadc > (400 * self._nbcol)) & (
                    self._tadc < ((self._nrows - 80) * self._nbcol))
        VS = vanderX[:, msktoffset[0]]
        vanderfilterX = np.dot(vanderX.T, np.linalg.lstsq(np.dot(VS, VS.T), VS,rcond=None)[0])
        # vanderfilterX = np.dot(msktoffset.T, np.linalg.lstsq(np.dot(VS,VS.T), VS)[0])
        self.vanderfilter = lambda data: np.dot(vanderfilterX, data[msktoffset[0], :])

        # Non-physical pixel
        self._nmskadc = ~self._mskadc
        self._nmskadc = np.tile(self._nmskadc, (12, 1)).T.ravel()
        self._nmskadc_list = np.where(self._nmskadc)[0]
        a = (msktoffset1 & (self._tadc > self._nbcol * self._nrows * 3 // 4)).T
        self._mskbgf = lambda data: self._msktf(((data > -self._hnu * 1) & (data < self._hnu * 1)) | a)
        self._bgcolf = lambda data: np.sum(self._rowXclock(data * self._mskbgf(data)), axis=0) / np.sum(
            self._rowXclock(self._mskbgf(data)), axis=0)

        # Fourier matching
        self._filter = np.ones(5)
        self._mskbg2f = lambda data: self._msktf((data > -hnu * 3) & (data < hnu))
        self._powerspec = lambda data: np.sum(np.abs(np.fft.fft(self._mskbg2f(data) * data)), axis=1)
        self._mskFclock = lambda pspec: (
                    np.convolve(np.single((pspec - np.mean(pspec) > (pspec[0]) / 20.)), self._filter,
                                'same') > 0).reshape((pspec.shape[0], 1))

        # CCD Mask
        self._filter2 = np.ones((2, 2))
        self._mskccdf = lambda data: (signal.convolve2d(np.single(data > self._hnu), self._filter2, 'same') > 0) * data

        # Pixelsize
        self._pixelsize = pixelsize

        # Dimenstions for Cropping 
        self._Mx, self._My = (croppedWidth, croppedHeight)
        self._mx, self._my = (frameWidth, frameHeight)

        # Semi-transparent beamtop
        self._beamstop_radius = beamstop_radius
        self._beamstop_transmission = beamstop_transmission
        self._beamstop_xshift = beamstop_xshift
        self._beamstop_yshift = beamstop_yshift

        # A circular mask for smoothing
        x = np.arange(self._mx) - self._mx // 2 + 1
        y = np.arange(self._my) - self._my // 2 + 1
        xx, yy = np.meshgrid(x, y)
        r2 = (xx ** 2 + yy ** 2)
        self._msksmooth = (special.erf(((self._mx // 2) * 0.99 - 1.4 * np.sqrt(r2)) / 20) + 1) / 2

        # A filter for attenuation/deattenation of beamstop
        x = np.arange(self._Mx) - self._Mx // 2 + self._beamstop_xshift
        y = np.arange(self._My * 2) - self._My + self._beamstop_yshift
        xx, yy = np.meshgrid(x, y)
        r2 = (xx ** 2 + yy ** 2)
        self._filter_beamstop = (r2 > (self._beamstop_radius / self._pixelsize) ** 2) + (
                    r2 <= (self._beamstop_radius / self._pixelsize) ** 2) * self._beamstop_transmission

        # Preproc options
        self.rotate = rotate

    def _msktf(self, data):
        """Returns masked data"""
        return self._mskadc * (data * self._mskt.transpose())

    def adcmask(self, bgstd, adcthreshold=50):
        """Masking wrong adc values."""
        self.bgstd[:bgstd.shape[0] // self._nbmux, :] = bgstd.reshape((bgstd.shape[0] // self._nbmux, self._nbmux))
        adcstd = np.mean(self._clockXraw(self.bgstd), axis=0)
        badadc = adcstd < (np.median(adcstd) + adcthreshold)
        return badadc

    def _rowXclock(self, data):
        """Translates `clock` format to `row` format."""
        return np.reshape(np.transpose(np.reshape(data, (self._nbcol, self._nrows, self._nbmux), order='F'), [1, 0, 2]),
                          (self._nrows, self._nbmux * self._nbcol), order='F')

    def _ccdXrow(self, data):
        """Translates `row` format to `ccd` format."""
        # return np.vstack([data[5:5+960,self._ncols/2+self._gii+1], np.rot90(data[5:5+960,self._gii+1], 2)])
        off = 10
        return np.vstack([data[:-off, self._ncols // 2 + self._gii + 1], np.rot90(data[:-off, self._gii + 1], 2)])

    def _tifXrow(self, data):
        """Translates `row` format to `tif` format."""
        tif = np.vstack([data[:, self._ncols // 2 + self._aii], np.rot90(data[:, self._aii], 2)])
        return tif

    def _rowXccd(self, data):
        """Translates `ccd` format to `row` format."""
        out = np.zeros((self._nrows, self._ncols))
        off = 10  # This number should be deducted from the input, for example a discrepancey between `width` and `nrows`
        # out[off/2:-off/2,self._gii] = np.rot90(data[self._nrows-off:2*(self._nrows-off),:],2)
        out[:-off, self._gii] = np.rot90(data[self._nrows - off:2 * (self._nrows - off), :], 2)
        # out[off/2:-off/2,self._ncols/2 + self._gii] = data[:self._nrows-off,:]
        out[:-off, self._ncols // 2 + self._gii] = data[:self._nrows - off, :]
        return out
        # return np.hstack([np.rot90(data[self._nrows:,:],2), data[:self._nrows,:]])

    def _clockXrow(self, data):
        """Translates `row` format to `clock` format."""
        return np.reshape(np.transpose(np.reshape(data, (self._nrows, self._nbcol, self._nbmux), order='F'), [1, 0, 2]),
                          (self._nrows * self._nbcol, self._nbmux), order='F')

    def _rowXtif(self, data):
        """Translates `tif` format to `row` format."""
        return np.reshape(np.roll(np.reshape(self._rowXccd(data), (self._nrows, self._nbcol, self._nbmux)), -1, axis=2),
                          (self._nrows, self._nbcol * self._nbmux))

    def _clockXtif(self, data):
        """Translates `tif` format to `clock` format."""
        return self._clockXrow(self._rowXtif(data))

    def _clockXraw(self, data):
        """Translates `raw` format to `clock` format. This was the slowest operation in the descrambling process"""
        # return data.reshape((self._nbcol * self._nrows, self._nb*self._nmux)).transpose()[self._q,:].transpose()
        # return data.reshape((self._nbcol * self._nrows, self._nb*self._nmux))
        # return data.reshape((self._nbcol * self._nrows, self._nb*self._nmux), order='F')[:,self._q]
        return data.reshape((self._nbcol * self._nrows, self._nb * self._nmux))[:, self._q]

    def _rawXclock(self, data):
        """Translates `clock` format to `raw` format."""
        return data.reshape((self._nbcol * self._nrows, self._nb * self._nmux), order='F')[:, self._iq]

    def _cropimg(self, img, s, dx=0, dy=0):
        """Returns cropped image."""
        c0 = np.floor((img.shape[0] - s[0]) / 2 + dx)
        c1 = np.floor((img.shape[1] - s[1]) / 2 + dy)
        return img[c0:c0 + s[0], c1:c1 + s[1]]

    def _cropF(self, img):
        """Returns image cropped to (croppedWidth, croppedHeight)."""
        return self._cropimg(img, (self._My, self._Mx))

    def _cropframe(self, img):
        """Returns image cropped to (frameWidth, frameHeight)."""
        return self._cropimg(img, (self._my, self._mx), dx=self._beamstop_xshift, dy=self._beamstop_yshift)

    def _cropframe_smooth(self, img):
        """Returns image smoothed and cropped to (frameWidth, frameHeight)."""
        return self._cropframe(img) * self._msksmooth

    def downsample(self, frame):
        """Returns downsampled frame."""
        return np.abs(np.fft.fft2(self._cropframe_smooth(np.fft.fftshift(np.fft.ifft2(frame)))))

    def lowpass(self, frame):
        """Returns filtered frame."""
        return self.downsample(self._cropF(frame))

    def deattenuate(self, frame):
        """Returns frame with deattenuated beamstop area."""
        return frame / self._filter_beamstop

    def attenuate(self, frame):
        """Returns frame with attenuated beamstop area."""
        return frame * self._filter_beamstop

    def tif2raw(self, img):
        """Returns scrambled data, translating `tif` format to `raw` format."""
        clockdata = self._clockXtif(img)
        return self._rawXclock(clockdata)

    def descramble(self, rawdata, badadc_mask=None, mask=False):
        """Returns descrambled data, translating `raw` format to `clock` format."""
        self.rawdata[:rawdata.shape[0] // self._nbmux, :] = rawdata.reshape(
            (rawdata.shape[0] // self._nbmux, self._nbmux))
        if mask:
            clockdata = self._msktf(self._clockXraw(self.rawdata.reshape((self._height, self._width))))
        else:
            clockdata = self._clockXraw(self.rawdata.reshape((self._height, self._width)))
        if badadc_mask is not None:
            clockdata = clockdata * badadc_mask
        return clockdata

    def scramble(self, data):
        """Returns scrambled data, translating `ccd` format ro `raw` format."""
        clockdata = self._clockXrow(self._rowXccd(data))
        return self._rawXclock(clockdata)

    def preprocessing(self, data):
        """Returns clean data after removing of negative pixels, filtering (vandermonde), removing
        of non-physical pixels and more filtering (fourier)."""

        # 1. Removing negative pixels
        data[data < (-self._hnu * 5)] = 0.

        # 2. Remove polynomials (vandermonde filter)
        data = data - self.vanderfilter(data)

        # 3. Remove non-physical pixels
        bgcol = self._bgcolf(data)
        bgcol[self._nmskadc_list] = 0
        bgcol = self._clockXrow(
            np.vstack([np.zeros((2, self._ncols)), np.tile(bgcol, (self._nrows - 37, 1)), np.zeros((35, self._ncols))]))
        data = self._msktf(data - bgcol)

        # 4. Fourier filter
        bgfilt = np.zeros_like(data)
        for jj in range(2):
            bgfilt = self._mskbgf(data) * data + (~self._mskbgf(data)) * bgfilt
            bgfilt = np.real(np.fft.ifft(np.fft.fft(bgfilt) * self._mskFclock(self._powerspec(data))))
        data = data - bgfilt

        # 5. Downsample and low pass filter
        data = self.lowpass(self.deattenuate(self.assemble(data)))

        # 6. Rotate the image by 90 degress counter clockwise
        if self.rotate:
            data = np.rot90(data, -1)

        return data

    def assemble(self, clockdata):
        """Returns assembled data, translating 'clock' format to 'ccd' format."""
        return self._mskccdf(self._ccdXrow(self._rowXclock(clockdata)))

    def assemble_nomask(self, clockdata):
        """Returns assembled data, translating 'clock' format to 'ccd' format."""
        return self._ccdXrow(self._rowXclock(clockdata))

    def assemble2(self, clockdata):
        """Returns assembled data, translating 'clock' format to 'ccd' format."""
        return self._tifXrow(self._rowXclock(clockdata))

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


# ---------------------------------------------------------------------------
# Scan-image analysis utilities (used by intelligence module and task agent)
# ---------------------------------------------------------------------------

def otsu_absorption_mask(
    image: np.ndarray,
    smooth_sigma: float = 2.0,
    despike: bool = True,
    min_separation: float = 0.0,
    dark: bool = True,
    valid: np.ndarray | None = None,
) -> np.ndarray:
    """Return a binary mask of features isolated by Otsu thresholding.

    With ``dark=True`` (default) it finds *absorbing* (dark) features in a transmission
    image — the image is inverted so absorbers become bright, then Otsu-thresholded.
    With ``dark=False`` it finds *bright* features directly, which is what an elemental
    contrast map (e.g. a two-energy OD difference) needs.

    By default zero-valued pixels are excluded from both the threshold and the output mask
    so unscanned spiral corners don't bias the result.  Pass ``valid`` to supply an explicit
    validity mask (e.g. pixels measured at both energies of a two-energy map), which is
    required when feature values can legitimately be <= 0.

    To extend usable sensitivity below SNR~5 the image is conditioned before Otsu:

    * **despike** — isolated hot/dead pixels are replaced by their 3x3 median (the same
      median-residual > 3-sigma test as :func:`despike`, but adapted to be non-mutating,
      shape-preserving, and limited to *interior* valid pixels so the circular field-of-view
      edge isn't flagged as spikes by a median that straddles the zero corners).
    * **smooth_sigma** — an edge-aware (mask-normalised) Gaussian boosts SNR for spatially
      extended features without bleeding the zero corners into valid data.  ``0`` disables it.

    :param smooth_sigma:   Gaussian sigma in pixels for pre-smoothing (default 2; 0 = off).
    :param despike:        remove isolated hot/dead pixels before smoothing (default True).
    :param min_separation: detectability guard.  Below the SNR floor Otsu still returns a
                           threshold and will segment pure noise.  If > 0, the feature class
                           must exceed the background mean by at least this many background
                           std-devs, otherwise an empty mask is returned (no false detection).
                           ``0`` disables the guard.
    :param dark:           True = dark/absorbing features; False = bright features.
    :param valid:          optional explicit validity mask; defaults to ``image > 0``.

    Returns a bool array with the same 2-D shape as *image*, or an all-False
    array if there are no valid pixels or the guard rejects the result.
    """
    from skimage.filters import threshold_otsu
    from scipy.ndimage import gaussian_filter, median_filter, binary_erosion

    img = np.asarray(image, dtype=float)
    valid = (img > 0) if valid is None else np.asarray(valid, dtype=bool)
    if not valid.any():
        return np.zeros(img.shape[:2], dtype=bool)

    # 1. Despike isolated hot/dead pixels (interior only — see docstring).
    if despike:
        med = median_filter(img, size=3)
        resid = img - med
        interior = binary_erosion(valid)
        if interior.any():
            sigma_r = float(resid[interior].std())
            if sigma_r > 0:
                spikes = interior & (np.abs(resid) > 3.0 * sigma_r)
                img = img.copy()
                img[spikes] = med[spikes]

    # 2. Edge-aware (mask-normalised) Gaussian: averages only over valid pixels so the
    #    zero corners don't pull down the field-of-view edge.
    if smooth_sigma and smooth_sigma > 0:
        w = valid.astype(float)
        num = gaussian_filter(img * w, smooth_sigma)
        den = gaussian_filter(w, smooth_sigma)
        work = np.where(den > 0, num / den, 0.0)
    else:
        work = img

    # 3. Otsu on the "feature brightness" of the valid pixels: invert for dark features,
    #    use the signal directly (shifted non-negative) for bright features.
    feat = (work.max() - work) if dark else (work - work[valid].min())
    thresh = threshold_otsu(feat[valid])
    mask = valid & (feat > thresh)

    # 4. Detectability guard: reject results that don't separate from the background.
    if min_separation and min_separation > 0 and mask.any():
        bg = valid & ~mask
        bg_std = float(feat[bg].std()) if bg.any() else 0.0
        if bg.any() and bg_std > 0:
            separation = float(feat[mask].mean() - feat[bg].mean())
            if separation < min_separation * bg_std:
                return np.zeros(img.shape[:2], dtype=bool)

    return mask


def image_com(
    image: np.ndarray,
    x_center: float,
    y_center: float,
    x_range: float,
    y_range: float,
    smooth_sigma: float = 2.0,
    despike: bool = True,
    min_separation: float = 0.0,
) -> tuple | None:
    """Return the physical-space centre-of-mass (µm) of absorbing features.

    Uses :func:`otsu_absorption_mask` to isolate absorbing regions, then maps
    the unweighted pixel centroid into motor coordinates.  The ``smooth_sigma``,
    ``despike`` and ``min_separation`` arguments are forwarded to the mask function
    to extend usable sensitivity at low SNR (see :func:`otsu_absorption_mask`).

    Returns ``(com_x, com_y)`` in µm, or ``None`` if the mask is empty or an
    error occurs (e.g. skimage unavailable).
    """
    try:
        mask = otsu_absorption_mask(
            image, smooth_sigma=smooth_sigma, despike=despike,
            min_separation=min_separation,
        )
    except Exception:
        return None

    if not mask.any():
        return None

    ny, nx = image.shape[:2]
    row_idx, col_idx = np.indices((ny, nx), dtype=float)
    com_col = float(col_idx[mask].mean())
    com_row = float(row_idx[mask].mean())

    com_x = x_center + (com_col / max(nx - 1, 1) - 0.5) * x_range
    com_y = y_center + (com_row / max(ny - 1, 1) - 0.5) * y_range
    return com_x, com_y


def two_energy_map(frame_pre: np.ndarray, frame_edge: np.ndarray) -> tuple:
    """Elemental contrast map from two co-registered transmission frames.

    Computes ``diff = log(I_pre / I_edge)`` over pixels valid (positive) in both frames.
    This equals the analysis tab's OD difference ``OD_edge - OD_pre`` up to an additive
    constant (the per-energy I0 ratio), which is irrelevant for Otsu detection and relative
    contrast — so no explicit I0 estimate is needed.  Pixels that absorb more on the edge
    than the pre-edge (i.e. contain the element) are positive/high.

    The two frames are assumed already co-registered, which holds for a single scan: both
    energies are sampled on the same interpolated spatial grid, so no alignment is required.

    :param frame_pre:  pre-edge transmission frame (lower energy)
    :param frame_edge: edge transmission frame (higher energy)
    :return: ``(diff, valid)`` — the map (0 where invalid) and the bool validity mask.
    """
    pre = np.asarray(frame_pre, dtype=float)
    edge = np.asarray(frame_edge, dtype=float)
    valid = (pre > 0) & (edge > 0)
    diff = np.zeros(pre.shape, dtype=float)
    diff[valid] = np.log(pre[valid]) - np.log(edge[valid])
    return diff, valid


def find_feature_boxes(mask: np.ndarray, min_area: int = 4,
                       max_features: int | None = None) -> list[dict]:
    """Connected-component analysis of a boolean feature mask.

    Returns a list of components sorted by descending pixel area, each a dict with
    ``centroid_row``, ``centroid_col``, ``area_px`` and bounding box ``minr/minc/maxr/maxc``.
    Components smaller than *min_area* pixels are dropped (noise speckle).

    :param mask:         bool feature mask (e.g. from :func:`otsu_absorption_mask`)
    :param min_area:     drop components smaller than this many pixels
    :param max_features: optionally keep only the N largest
    """
    from skimage.measure import label, regionprops

    feats = []
    for r in regionprops(label(mask)):
        if r.area < min_area:
            continue
        cr, cc = r.centroid
        feats.append({
            "centroid_row": float(cr), "centroid_col": float(cc),
            "area_px": int(r.area),
            "minr": int(r.bbox[0]), "minc": int(r.bbox[1]),
            "maxr": int(r.bbox[2]), "maxc": int(r.bbox[3]),
        })
    feats.sort(key=lambda f: f["area_px"], reverse=True)
    if max_features is not None:
        feats = feats[:max_features]
    return feats


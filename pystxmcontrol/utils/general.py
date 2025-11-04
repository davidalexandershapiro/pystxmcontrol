import numpy as np
from .constants import constants
from scipy import ndimage, linalg, interpolate
import itertools
import skimage
import os, re, math
from scipy import misc, ndimage

p = constants()
c = p.p

def getCXIPath(base,scan):
    yr = scan[0:2]
    mo = scan[2:4]
    dy = scan[4:6]
    no = scan[6:9]
    nn = scan.split('_')[-2]
    nn2 = scan.split('_')[-1]

    stxmStr = 'NS_'+yr+mo+dy+no+'.stxm'
    cxiStr = stxmStr.replace('.stxm','_ccdframes_'+nn+'_'+nn2+'.cxi')
    print(os.path.join(base,'20'+yr,mo,yr+mo+dy,cxiStr))
    if os.path.isfile(os.path.join(base,'20'+yr,mo,yr+mo+dy,cxiStr)):
        return os.path.join(base,'20'+yr,mo,yr+mo+dy,cxiStr)

def rebinLine(self, xReq, yReq, xMeas, yMeas, rawCounts):

    # Returns a rebinning of the rawCounts into bins defined by xReq and yReq
    # For a single line only. rawCounts, xMeas and yMeas are all the same shape.
    xstart = xReq[0]
    xstop = xReq[-1]
    ystart = yReq[0]
    ystop = yReq[-1]

    # Define the oversampling factor for averaging later.
    oversampling_factor = len(xMeas) / len(xReq)

    # direction here is a unit vector in the direction of the scan.
    direction = np.array([xstop - xstart, ystop - ystart])
    direction = direction / np.linalg.norm(direction)
    # We need to convert the requested and measured positions to distances along this direction.
    distReq = np.array(
        [(xReq[i] - xstart) * direction[0] + (yReq[i] - ystart) * direction[1] for i in range(len(xReq))])
    # TODO: FIX THIS
    distMeas = np.array(
        [(xMeas[i] - xstart) * direction[0] + (yMeas[i] - ystart) * direction[1] for i in range(len(xMeas))])

    # This doesn't assume even spacing of positions which is probably overkill.
    # Generate bins for np.histogram function.
    distBins = (distReq[1:] + distReq[:-1]) / 2
    distBins = np.append(distBins, 2 * distReq[-1] - distBins[-1])
    distBins = np.insert(distBins, 0, 2 * distReq[0] - distBins[0])

    try:
        cutoff = np.where(distMeas > ddistBins[-1])[0][0]
    except:
        cutoff = np.where(distMeas == max(distMeas))[0][0]

    distMeas = distMeas[:cutoff]

    rawCounts = rawCounts[:cutoff]

    # nEvents is just the number of times we had an x value in each of the bins. May be useful to track.
    nEvents, edges = np.histogram(distMeas, bins=distBins)
    # This is the total counts in each bin.
    binCounts, edges = np.histogram(distMeas, bins=distBins, weights=rawCounts)
    # Final counts are the counts per bin divided by the events.
    # The oversampling factor is put in here so that the count rate is independent of the oversampling factor.
    # For zero events in a bin, we replace the inf values with zero (and ignore error messages).
    with np.errstate(divide='ignore', invalid='ignore'):
        counts = binCounts / nEvents * oversampling_factor
    counts[np.isinf(counts)] = 0
    counts[np.isnan(counts)] = 0

    # Interpolate if the pixel is zero.
    for i in range(len(counts)):
        if counts[i] == 0:
            if i != 0 and i != len(counts) - 1:
                if counts[i + 1] != 0 and counts[i - 1] != 0:
                    counts[i] = (counts[i + 1] + counts[i - 1]) / 2
            elif i == 0:
                if counts[1] != 0:
                    counts[0] = counts[1]
            else:
                if counts[-2] != 0:
                    counts[-1] = counts[-2]
    return (counts)

def find_nearest(array,value):
    idx = np.searchsorted(array, value, side="left")
    if idx > 0 and (idx == len(array) or math.fabs(value - array[idx-1]) < math.fabs(value - array[idx])):
        return idx-1
    else:
        return idx

def fixPath(path):
    return os.path.abspath(os.path.expanduser(path))

def getIOMask(intensityData):

    hist = np.histogram(intensityData, bins = 30)
    threshold = hist[1][0]
    print("Using IO threshold: %i" %threshold)
    return intensityData > threshold

def getPhaseMask(phaseData):

    return phaseData < skimage.filters.threshold_triangle(phaseData)

def getIOSpectrum(intensityData, mask):

    nz, ny, nx = intensityData.shape
    norm = nx * ny / mask.sum()
    IO = []
    for i in range(N_ENERGIES):
        IO.append((intensityData[i] * mask)[mask > 0].mean())
    return np.array(IO)

def convert2OD(intensityData, IO):

    OD = np.zeros(intensityData.shape)
    OD = -np.log(intensityData / IO)
    return OD

def getPhaseShift(phaseData, mask):

    phaseData = phaseData - (phaseData * mask)[mask > 0].mean()
    return phaseData

def polyfit2d(x, y, z, order=1):
    ncols = (order + 1)**2
    G = np.zeros((x.size, ncols))
    ij = itertools.product(range(order+1), range(order+1))
    for k, (i,j) in enumerate(ij):
        G[:,k] = x**i * y**j
    m, _, _, _ = np.linalg.lstsq(G, z)
    return m

def polyval2d(x, y, m):
    order = int(np.sqrt(len(m))) - 1
    ij = itertools.product(range(order+1), range(order+1))
    z = np.zeros_like(x)
    for a, (i,j) in zip(m, ij):
        z += a * x**i * y**j
    return z

def e2l(energy):
    """calling sequence: e2l(energy)
    Inputs: energy (eV)
    Outputs: wavelength (nm)
    """
    return c / energy

def l2e(wavelength):
    """calling sequence: l2e(wavelength)
    Inputs: wavelength (nm)
    Outputs: energy (eV)
    """
    return c / wavelength

def k2e(k, ee = None, lu = None):
    """calling sequence: k2e(k, ee = None, lu = None)
    Inputs: k = undulator K
            ee = electron energy (GeV)
            lu = undulator period (cm)
    Outputs: photon resonant energy (eV)
    """
    if ee == None: ee = 3.0
    if lu == None: lu = 4.9
    return np.round(0.95 * ee**2 / lu / (1. + 0.5 * k**2) * 1000.,decimals = 2)

def e2k(e, ee = None, lu = None):
    """calling sequence: e2k(e, ee = None, lu = None)
    Inputs: e = photon energy (eV)
            ee = electron energy (GeV)
            lu = undulator period (cm)
    Outputs: undulator K
    """
    if ee == None: ee = 3.0
    if lu == None: lu = 4.9
    return np.sqrt(2.*(950.*ee**2/lu/e-1.))

def l2sig(lp, lu = None):
    """calling sequence: l2sig(lp, lu = None)
    Inputs: lp = photon wavelength (nm)
            lu = undulator length (m)
    Outputs: photon source 1-sigma size
    """
    if lu == None: lu = 38. * 4.9e4
    else: lu *= 1e6
    return np.round(np.sqrt(lp * 1e-3 * lu / 2.) / pi,decimals = 2)

def e2sig(e, lu = None):
    """calling sequence: e2sig(e, lu = None)
    Inputs: e = photon energy (eV)
            lu = undulator length (m)
    Outputs: photon source 1-sigma size
    """
    if lu == None: lu = 38. * 4.9e4
    else: lu *= 1e6
    return np.round(np.sqrt(e2l(e) * 0.001 * lu / 2.) / pi,decimals = 2)

def l2sigp(lp, lu = None):
    """calling sequence: l2sig(lp, lu = None)
    Inputs: lp = photon wavelength (nm)
            lu = undulator length (m)
    Outputs: photon source 1-sigma divergence
    """
    if lu == None: lu = 38. * 4.9e4
    else: lu *= 1e6
    return np.sqrt(lp * 0.001 / lu / 2.)

def e2sigp(e, lu = None):
    """calling sequence: e2sig(e, lu = None)
    Inputs: e = photon energy (eV)
            lu = undulator length (m)
    Outputs: photon source 1-sigma divergence
    """
    if lu == None: lu = 38. * 4.9e4
    else: lu *= 1e6
    return np.sqrt(e2l(e) * 0.001 / lu / 2.)

def k2b(k, lu = None):
    """calling sequence: k2b(k, lu = None)
    Inputs: k = undulator k-value
            lu = undulator length (m)
    Outputs: peak magnetic field in Tesla
    """
    if lu == None: lu = 38. * 4.9e4
    return k / 0.934 / lu

def b2k(u, lu = None):
    """calling sequence: b2k(b, lu = None)
    Inputs: b = peak magnetic field in Tesla
            lu = undulator length (m)
    Outputs: undulator k-value
    """
    if lu == None: lu = 38. * 4.9e4
    return u * 0.934 * lu

def e2gap(e, lu = None):
    """calling sequence: e2gap(e, lu = None)
    Inputs: e = photon energy (eV)
            lu = undulator period (mm)
    Outputs: g = undulator gap in mm
    """
    if lu == None: lu = 49.
    return lu*(5.08-np.sqrt(5.08**2-4.*1.54*np.log(0.314*lu/e2k(e))))/2./1.54

def gap2e(g, lu = None):
    """calling sequence: gap2e(g, lu = None)
    Inputs: g = undulator gap (mm)
            lu = undulator period (mm)
    Outputs: e = resonant energy (eV)
    """
    if lu == None: lu = 49.
    return k2e(0.314*lu*np.exp(-g/lu*(5.08-1.54*g/lu)))

def flux2power(f, e):
    return f * e * p.ev

def current2flux(i,en):
    """calling sequence: pd2flux(i,en)
    Inputs: i = diode current in amps
            en = photon energy in eV
    Outputs: photons per second
    """
    eps = i / 1.6e-19
    epp = en / 3.6
    return eps / epp

def flux2current(f, en):
    """calling sequence: pd2flux(i,en)
    Inputs: f = photon flux in photons / second
            en = photon energy in eV
    Outputs: current in amps
    """

    return en / 3.6 * f * 1.6e-19

def bl901gap(en):
    e3 = 3. * (en / 5.) #third harmonic energy
    return 0.0636 * e3 + 45.421

def shift2d(data, deltax, deltay, phase=0, nthreads=1, use_numpy_fft=False,
        return_abs=False, return_real=True):
    """
    2D version: obsolete - use ND version instead
    (though it's probably easier to parse the source of this one)

    FFT-based sub-pixel image shift.
    Will turn NaNs into zeros

    Shift Theorem:

    .. math::
        FT[f(t-t_0)](x) = e^{-2 \pi i x t_0} F(x)


    Parameters
    ----------
    data : np.ndarray
        2D image
    phase : float
        Phase, in radians
    """

    fftn,ifftn = np.fft.fftn, np.fft.ifftn

    if np.any(np.isnan(data)):
        data = np.nan_to_num(data)
    ny,nx = data.shape

    xfreq = deltax * np.fft.fftfreq(nx)[np.newaxis,:]
    yfreq = deltay * np.fft.fftfreq(ny)[:,np.newaxis]
    freq_grid = xfreq + yfreq

    kernel = np.exp(-1j*2*np.pi*freq_grid-1j*phase)

    result = ifftn( fftn(data) * kernel )


    if return_real:
        return np.real(result)
    elif return_abs:
        return np.abs(result)
    else:
        return result

def shift(a, xoffset, yoffset = None):

    if yoffset == None:
        ny, nx = a.shape
        for i in range(0,nx):
            dummy = np.concatenate((a[-xoffset:], a[:-xoffset]))

    else:
        shiftxi = int(xoffset)
        shiftyi = int(yoffset)
        shiftxf = xoffset - shiftxi
        shiftyf = yoffset - shiftyi
        gx, gy = np.gradient(a)
        ny,nx = a.shape
        dummy = np.zeros((ny,nx)) + a

        for i in range(0,ny):
            dummy[i] = np.concatenate((dummy[i,-xoffset:], dummy[i,:-xoffset]))

        dummy = np.transpose(dummy)

        for i in range(0,nx):
            dummy[i] = np.concatenate((dummy[i,yoffset:],dummy[i,:yoffset]))

        dummy = np.transpose(dummy)

        if ((shiftxf != 0) * (shiftyf != 0)):
            gx, gy = np.gradient(dummy)
            dummy = dummy - (gx * shiftxf + gy * shiftyf)

    if (dummy.sum() != 0.): return dummy * a.sum() / dummy.sum()
    else: return dummy

def dist(ny,nx = None):
    # nx = int(nx)
    # a = np.roll((np.arange(nx) - float(nx) / 2)**2,nx / 2)
    # array = np.zeros((nx,nx))
    # for i in range(int(nx)/2+1):
    #     y = np.sqrt(a+i**2)
    #     array[:,i] = y
    #     if i != 0:
    #         array[:,nx-i] = y
    #
    # return np.fft.fftshift(array)
    if nx == None: nx = ny
    nx, ny = int(nx), int(ny)
    a = np.ones((ny,nx))
    ay = np.abs(np.arange(ny) - float(ny) / 2)
    ax = np.abs(np.arange(nx) - float(nx) / 2)
    return np.sqrt((a * ax)**2 + (a.transpose() * ay).transpose()**2)

def dist2(ny,nx = None):
    if nx == None: nx = ny
    nx, ny = int(nx), int(ny)
    a = np.ones((ny,nx))
    ay = np.abs(np.arange(ny) - float(ny) / 2)
    ax = np.abs(np.arange(nx) - float(nx) / 2)
    return np.sqrt((a * ax)**2 + (a.transpose() * ay).transpose()**2)

def plane(p,x,y):

    return p[0] * x + p[1] * y + p[2]

def removePlane(data):

    x,y = np.meshgrid(np.arange(data.shape[1]),np.arange(data.shape[0]))
    A = np.column_stack([y.flatten(), x.flatten(), np.ones_like(x.flatten())])
    p, residuals, rank, s = linalg.lstsq(A, data.flatten())
    fit = plane(p, y, x)
    return data - fit

def congrid(a, newdims, method='spline', centre=False, minusone=True):
    '''Arbitrary resampling of source array to new dimension sizes.
        Currently only supports maintaining the same number of dimensions.
        To use 1-D arrays, first promote them to shape (x,1).

       Uses the same parameters and creates the same co-ordinate lookup points
       as IDL''s congrid routine, which apparently originally came from a VAX/VMS
       routine of the same name.

       method:
       neighbour - closest value from original data
       nearest and linear - uses n x 1-D interpolations using
                            scipy.interpolate.interp1d
       (see Numerical Recipes for validity of use of n 1-D interpolations)
       spline - uses ndimage.map_coordinates

       centre:
       True - interpolation points are at the centres of the bins
       False - points are at the front edge of the bin

       minusone:
       For example- inarray.shape = (i,j) & new dimensions = (x,y)
       False - inarray is resampled by factors of (i/x) * (j/y)
       True - inarray is resampled by(i-1)/(x-1) * (j-1)/(y-1)
       This prevents extrapolation one element beyond bounds of input array.
       '''

    if a.dtype in [np.float64, np.float32, np.int8, np.int16, np.int32, np.int64, np.uint8]:
        a = np.cast[float](a)
        m1 = np.cast[int](minusone)
        ofs = np.cast[int](centre) * 0.5
        old = np.array( a.shape )
        ndims = len( a.shape )
        if len( newdims ) != ndims:
            print("[congrid] dimensions error. " \
                  "This routine currently only support " \
                  "rebinning to the same number of dimensions.")
            return None
        newdims = np.asarray( newdims, dtype=float )
        dimlist = []

        if method == 'neighbour':
            for i in range( ndims ):
                base = np.indices(newdims)[i]
                dimlist.append( (old[i] - m1) / (newdims[i] - m1) \
                    * (base + ofs) - ofs )
            cd = np.array( dimlist ).round().astype(int)
            newa = a[list( cd )]
            return newa

        elif method in ['nearest','linear']:
    # calculate new dims
            for i in range( ndims ):
                base = np.arange( newdims[i] )
                dimlist.append( (old[i] - m1) / (newdims[i] - m1) \
                            * (base + ofs) - ofs )
               # specify old dims
                olddims = [np.arange(i, dtype = float) for i in list( a.shape )]

               # first interpolation - for ndims = any
                mint = interpolate.interp1d( olddims[-1], a, kind=method )
                newa = mint( dimlist[-1] )

                trorder = [ndims - 1] + range( ndims - 1 )
                for i in range( ndims - 2, -1, -1 ):
                    newa = newa.transpose( trorder )

                    mint = interpolate.interp1d( olddims[i], newa, kind=method )
                    newa = mint( dimlist[i] )

                if ndims > 1:
                   # need one more transpose to return to original dimensions
                    newa = newa.transpose( trorder )

                return newa
        elif method in ['spline']:
            oslices = [ slice(0,j) for j in old ]
            oldcoords = np.ogrid[oslices]
            nslices = [ slice(0,j) for j in list(newdims) ]
            newcoords = np.mgrid[nslices]

            newcoords_dims = range(np.rank(newcoords))
               #make first index last
            newcoords_dims.append(newcoords_dims.pop(0))
            newcoords_tr = newcoords.transpose(newcoords_dims)
               # makes a view that affects newcoords

            newcoords_tr += ofs

            deltas = (np.asarray(old) - m1) / (newdims - m1)
            newcoords_tr *= deltas

            newcoords_tr -= ofs

            newa = ndimage.map_coordinates(a, newcoords)
            return newa
    else:
        print("Congrid error: Unrecognized interpolation type.\n", \
             "Currently only \'neighbour\', \'nearest\',\'linear\',", \
             "and \'spline\' are supported.")
        return None

def rot_ave(array,pix_mm,ccd_z_mm,center=None):

#    start_time=time()

    ny = len(array[:,0])
    nx = len(array[0,:])

    if center == None:
        temp = np.fix(dist(nx))
        pix_max = np.int(temp.max())
        thetas = np.fix(np.arange(pix_max+1)+1) #leave as pixels now convert to f later
        count = np.ones((pix_max+1))
        ave1d = np.zeros((pix_max+1))
    else:
        ycenter = center[0]
        xcenter = center[1]

        if nx>ny:
            temp = np.fix(dist(2*nx))
        elif ny>nx:
            temp = np.fix(dist(2*ny))
        else:
            temp = np.fix(dist(2*nx))
        temp = temp[(ny-ycenter):(2*ny-ycenter),(nx-xcenter):(2*nx-xcenter)]
        pix_max = np.int(temp.max())
        thetas = np.fix(np.arange(pix_max+1)+1) #leave as pixels now convert to f later
        count = np.ones((pix_max+1))
        ave1d = np.zeros((pix_max+1))

    ave_time = time()
    for i in range(nx):
        for j in range(ny):
            freq_index = temp[i,j]
            if array[i,j] > 0.:
                ave1d[freq_index] = ave1d[freq_index]+array[i,j]
                count[freq_index] = count[freq_index]+1
    index = np.where(ave1d>0.)
    ave1d[index] = ave1d[index] / count[index]

#    stop_time=time()
#    print("It took "+str(stop_time-start_time)+" seconds to execute.")
#    print("It took "+str(stop_time-ave_time)+" seconds to compute the radial average.")

    thetas = np.arctan(thetas * pix_mm / ccd_z_mm)

    return ave1d,thetas

def filtered_auto(diffint,diameter=None,lp=False,bp=False, center = None):

    nd = len(diffint)
    sh = diffint.shape

    if lp == False and bp == False:
        if diameter == None:
            diameter = 0.2 * nd
        filter = dist(nd)
        filter = (filter / diameter)**4 * np.exp(2 - (filter**2) / diameter**2) / 4.

    elif lp == True:
        if diameter == None:
            diameter = 0.75 * nd
        filter = dist(nd) / float(nd) * 2.
        filter = np.exp(-filter**2 / 0.25)

    elif bp == True:
        if diameter == None:
            id = 0.1 * nd
            od = 0.75 * nd
        else:
            id = diameter
            od = 0.75 * nd
        filter = dist(nd)
        filter2 = filter * 1.
        filter[np.where(filter > sqrt(2.) * diameter)] = sqrt(2.) * diameter
        filter = (filter / diameter)**4 * np.exp(2 - (filter**2) / diameter**2) / 4.
        filter2 = filter2 / float(nd) * 2.
        filter2 = np.exp(-filter**2 / 0.25)
        filter = filter * filter2
        if center != None:
            filter = shift(filter, center[1] - sh[1] / 2, center[0] - sh[0] / 2)

    auto = diffint * filter
    auto = fft.fftshift(fft.ifftn(auto))

    return auto

def circle(n,d,xcenter,ycenter):

    c = dist(n)
    c = np.where(c>d, np.zeros((n,n)), np.ones((n,n)))
    c = shift(c,xcenter - n // 2, ycenter- n // 2)

    return c

def circle2(d, sh, center = None):

    ny, nx = sh
    ycenter, xcenter = center
    if ny == None: ny = nx
    if xcenter == None: xcenter = nx / 2
    if ycenter == None: ycenter = ny / 2
    c = dist2((ny, nx))
    c = np.where(c > d, np.zeros((ny, nx)), np.ones((ny, nx)))
    return shift(c, xcenter - nx // 2, -ycenter + ny // 2)

def box(n, w, h, xcenter, ycenter, complexarr = False):

    if not complexarr:
        b = np.zeros((n,n))
        b[ycenter - h / 2:ycenter + h / 2, xcenter - w / 2:xcenter + w / 2] = 1.
    else:
        b = np.zeros((n,n),complex)
        b[ycenter - h / 2:ycenter + h / 2, xcenter - w / 2:xcenter + w / 2] = \
            complex(1.,1.)

    return b

def cropAndDetrend(data, psize):

    npy, npx = psize
    oSizeY, oSizeX = data.shape
    data = data[npy / 2:oSizeY - npy / 2, npx / 2:oSizeX - npx / 2]
    return data #abs(data) * np.exp(1j * removePlane(np.angle(data)))

def addNoise(a, mode = "poisson", readout = 1):
    '''
    a = input array of image intensities
    '''
    if a.dtype == "complex128":
        print("addNoise Error: array elements must be real, positive, and non-zero!")
        return 0

    if mode == "poisson":
        readoutNoise = np.random.poisson(readout * np.ones(a.shape))
        if readout: return np.random.poisson(a) + readoutNoise
        else: return np.random.poisson(a)

    if mode == "gauss":
        try: return np.random.normal(a, np.sqrt(a)).astype('int64')
        except ValueError:
            print("addNoise Error: array elements must be real, positive, and non-zero!")
            return 0

def atoi(text):
    return int(text) if text.isdigit() else text

def natural_keys(text):
    '''
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    (See Toothy's implementation in the comments)
    '''
    return [ atoi(c) for c in re.split('(\d+)', text) ]

def compileTomoScanDir(scanDir, outFile = None, ANGLES = 'angles.txt', filter = False, filterWidth = 2):

    dirList = os.listdir(scanDir)
    tifImageFiles = sorted([s for s in dirList if '.tif' in s], key = natural_keys)
    ##use RegEx to get the angles from the file names
    nums = re.compile(r"[+-]?\d+(?:\.\d+)?")
    angles = []
    for item in tifImageFiles:
        angles.append(float(nums.search(item).group(0)))
    sortedFileIndices = sorted(range(len(angles)), key=lambda k: angles[k])
    tifImageFiles = [tifImageFiles[i] for i in sortedFileIndices]

    nImages = len(tifImageFiles)
    tifImages = []

    i = 0
    for item in tifImageFiles:
        print("Reading image %s" %item)
        if filter:
            thisImage = ndimage.filters.median_filter(misc.imread(str(scanDir) + '/' + str(item)), size = filterWidth)
        else:
            thisImage = misc.imread(str(scanDir) + '/' + str(item))
        tifImages.append(thisImage)
        if i == 0: fullY, fullX = thisImage.shape
        thisShape = thisImage.shape
        if thisShape[0] > fullY: fullY = thisShape[0]
        if thisShape[1] > fullX: fullX = thisShape[1]
        i += 1

    imageStack = np.zeros((nImages, fullY, fullX))
    i = 0
    for item in tifImages:
        y,x = item.shape
        imageStack[i,fullY / 2 - y / 2: fullY / 2 - y / 2 + y,fullX / 2 - x / 2: fullX / 2 - x / 2 + x] = item
        i += 1

    del(tifImages)
    print("Frame stack has size: ", imageStack.shape)
    ang = []

    if ANGLES in dirList:
        angles = []
        f = open(ANGLES, 'r')
        for item in f:
            angles.append(float(item))
        if len(angles) != nImages:
            print("ERROR: number of angles does not match number of projections!")
        else:
            angles = np.array(angles)
            angles = np.sort(angles)
            print(angles)
    else:
        print("Could not locate angles file!")

    if outFile != None:

        from skimage.io import imsave
        imsave(outFile,imageStack.astype('float32'))
        tifPrefix = outFile.split('.tif')
        f = open(tifPrefix[0] + '_angles.txt', 'w')
        for angle in angles:
            f.write(str(angle) + '\n')
        f.close()

    else: return imageStack

def register_affine(refimg, timage):

    import cv2
    maximg = np.amax(refimg)
    refimg = (255 * refimg / maximg).astype('uint8')
    timage = (255 * timage / maximg).astype('uint8')
    t = cv2.estimateRigidTransform(refimg, timage, fullAffine = True)
    try:
        timage = cv2.warpAffine(timage, t, dsize = timage.shape[::-1]).astype('float32') * maximg / 255.
    except:
        print("Registration failed.")

    return timage


def propnf(a, z, l):
    """
    propnf(a,z,l) where z and l are in pixel units
    """

    if a.ndim != 2:
        raise RunTimeError("A 2-dimensional wave front 'w' was expected")

    n = len(a)
    ny, nx = a.shape
    qx, qy = np.meshgrid(np.linspace(-nx / 2, nx / 2, nx), np.linspace(-ny / 2, ny / 2, ny))
    q2 = np.fft.fftshift(qx ** 2 + qy ** 2)

    if n / np.sqrt(2.) < np.abs(z) * l:
        print("Warning: %.2f < %.2f: this calculation could fail." % (n / np.sqrt(2.), np.abs(z) * l))
        print("You could enlarge your array, or try the far field method: propff()")

    return np.fft.ifftn(np.fft.fftn(a) * np.exp(-2j * np.pi * (z / l) * (np.sqrt(1 - q2 * (l / n) ** 2) - 1)))


def propff(a, z, l):
    if a.ndim != 2:
        raise RunTimeError("A 2-dimensional wave front 'w' was expected")
    if a.shape[0] != a.shape[1]:
        raise RunTimeError("Only square arrays are currently supported")

    n = len(a)
    q2 = np.fft.fftshift(dist(n) ** 2)

    if n * np.sqrt(2.) > np.abs(z) * l:
        print
        "Warning: %.2f > %.2f: this calculation could fail." % (n * \
                                                                np.sqrt(2.), np.abs(z) * l)
        print
        "You could try the near field method: propnf()"

    return -1j * np.fft.fftshift(np.exp(4j * np.pi * l * z * q2 / n ** 2) * \
                                 np.fft.fftn(a * np.exp(1j * np.pi * np.fft.fftshift(q2) / (l * z)))) / n

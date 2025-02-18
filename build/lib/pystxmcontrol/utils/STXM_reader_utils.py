
import os
import numpy as np
import scipy
from struct import pack,unpack
import re

def eval_hdr(fname):
    """
    Reads .hdr file and uses string replacement and eval to load. Ignores the
    plethora of lines like "Image004_0 = {StorageRingCurrent = 483.21; Energy = 682.39; Time = "2017 Nov 05 16:39:13"; ZP_dest= -5176.08; ZP_error = -0.57;};"
    Note: in multi-region scans, the Region is the *inner* loop
    """
    global header_string
    s = 'dict('
    f = open(fname,mode='r')
    header_string = f.read()
    f.close()
    pattern = re.compile(r'^Image\d\d\d_\d')
    lines = header_string.replace('\t','').split('\r\n') #,'')
    lines = [l for l in lines if l!='' and pattern.match(l) is None]
    t = ''.join(lines)
    t = t.replace('{',s).replace('}',')')
    t = t.replace(';',',').replace('false','False').replace('true','True')
    bigstr = s+t+')'
    # nl = '\n'
    # lines = bigstr.split(nl)
    # nlines = len(lines)
    # numlines = nlines
    # pattern = re.compile(r'^Image\d\d\d_\d')
    # flag = 0    # start of a lame-o way to ignore lines that match ^Image\d\d\d_\d like Image123_0 but only after other header parts.
    # for i in range(0,nlines):   # this block looks for the last line that doesn't match the above
    #     l = lines[i]
    #     srch = pattern.match(l)
    #     if (srch == None) & (flag == 0):
    #         numlines = i+1
    #     else:
    #         flag = 1    #flag is needed because the last line is blank, so doesn't match the search string
    # numlines = min(numlines,255)
    # bigstr = nl.join(lines[0:numlines])+')'
    # print len(bigstr)
    d = eval(bigstr)
    return d

def readASCIIMatrix(filename,separator='\t'):
    """
    Reads data from diode channel and saves as numpy array.
    """
    data = []
    f = open(filename,'r')
    for line in f:
        row = line.split(separator)
        data.append(row[0:len(row)-1])
    return np.ascontiguousarray(np.flipud(np.array(data).astype('float')))

def xim_suff(index,iregion,nregion):
    """
    figure out .xim filename, which gets a different numerical suffix
    depending on whether it's a 1-region or multi-region scan
    """
    xs0 = "_a"
    xs1 = "%.3d" % index
    if nregion == 1:
        return xs0 + xs1 +".xim"
    else:
        return xs0 + xs1 + str(iregion) + ".xim"

def hdr2tags(hdr_content,index):
    """
    This routine begins the section of code used for reading/writing P3B files.
    Based on Andreas Scholl's code
    """
    scan_def = hdr_content['ScanDefinition']
    StackAxis = scan_def["StackAxis"]
    E = StackAxis["Points"]
    xvalname = StackAxis['Name']
    npoints = E[0]
    Energies = E[1:]
    tags = {'Type': scan_def['Type']}
    if xvalname == 'Energy':
        xvalname = 'BEAMLINE_ENERGY'    # Replicating actual PEEM P3B tag name
    tags[xvalname] = Energies[index]
    tags['XVALUE'] = Energies[index]    # This is what gets plotted as abscissa in PEEMVision
    R = scan_def['Regions']
    Regions = R[1]
    PAxis = Regions['PAxis']
    QAxis = Regions['QAxis']
    tags['xmax'] = PAxis['Max']
    tags['xmin'] = PAxis['Min']
    tags['ymax'] = QAxis['Max']
    tags['ymin'] = QAxis['Min']
    tags['Time'] = hdr_content['Time']
    return tags

def IDLType(npt):  # Andreas Scholl's P3B code
    if npt == 'uint8' or npt == 'int8': return 1
    if npt == 'int16': return 2
    if npt == 'uint16': return 12
    if npt == 'int32': return 3
    if npt == 'uint32': return 13
    if npt == 'int64': return 14
    if npt == 'uint64': return 15
    if npt == 'float32': return 4
    if npt == 'float64': return 5
    if npt == 'complex64': return 6
    if npt == 'complex128': return 9

def NPfromIDLType(vtype):  # Andreas Scholl's P3B code
    if vtype == 1: return 'uint8'
    if vtype == 2: return 'int16'
    if vtype == 12: return 'uint16'
    if vtype == 3: return 'int32'
    if vtype == 13: return 'uint32'
    if vtype == 14: return 'int64'
    if vtype == 15: return 'uint64'
    if vtype == 4: return 'float32'
    if vtype == 5: return 'float64'
    if vtype == 6: return 'complex64'
    if vtype == 7: return 'complex128'


def WriteTag(f,key,value):  # Andreas Scholl's P3B code
    if type(value) == float:
        vtype = 5
        els = 1
    elif str(key) == 'PixType':
        vtype = 2       # Fix for special handling of PIXTYPE tag
        els = 1
    elif type(value) == int:
        vtype = 3
        els = 1
    elif type(value) == str:
        vtype = 7
        els = len(value)
    elif type(value) == bool:
        vtype = 1
        els = 1
    elif type(value) == np.ndarray:
        vtype = IDLType(value.dtype)
        els = np.size(value)
    else:
        vtype = 3
        els = 1
        key = '_'+key
    f.write(pack('<l', len(key)))
    f.write(bytearray(key.upper(),'utf-8'))
    f.write(pack('<l', vtype))
    f.write(pack('<l', els))
    if key[0]=='_' and vtype ==3:
        f.write(pack('<l', 0))
    elif vtype == 5 and els == 1:
        f.write(pack('<d', value))
    elif vtype == 2 and els == 1 and str(key) == 'PixType':
        v16 = np.int16(value)   # PEEMVision writes PIXTYPE as an int16
        f.write(pack('<h', v16))
    elif vtype == 3 and els == 1:
        f.write(pack('<l', value))
    elif vtype == 1 and els == 1:
        f.write(pack('<B', value))
    elif vtype == 7:
        f.write(bytearray(value,'utf-8'))
    else:
        value.tofile(f)

def WriteP3B(filename, tags, image = []):  # Andreas Scholl's P3B code
    """
    The high-level routine for writing P3B files
    """
    with open(filename, 'wb') as f:
        if len(image)!=0:
            f.write(pack('<l',4+len(tags)))
            (n0,n1) = np.shape(image)
            pixtype = IDLType(image.dtype)
            WriteTag(f,'DimX',n0)
            WriteTag(f,'Dimy',n1)
            WriteTag(f,'PixType',pixtype)
            WriteTag(f,'Data',image)
        else:
            f.write(pack('<l',len(tags)))
        for key in tags:
            WriteTag(f,key,tags[key])

def scaleBarPixels(xrange, xstep):
        scaleBarLenMicrons = np.round(0.1 * xrange, decimals = 1)
        return np.int(scaleBarLenMicrons / xstep)

def Read_header(hdr_file):
    """
    This is the master routine which sucks in the file header and parses it,
    leaving some of the info into the global for other routines to pick up.
    This structure is motivated in part by the fact that the Enthought
    integration kit can't pass anything more complicated than an array
    of numerics or strings

    Another Enthoought issue - when hdr_file is passed in Pack as a string, it
    appears here as an objects of class Bytes, which prints out as b'c:\\dir\\fname'
    instead of 'c:\\dir\\fname'.  You have to decode it before passing it to
    any string or file function.
    """
    import sys
    global npoints,nregion,hdrinfo,RegDefs,ximfiles
    hdrfile = hdr_file#.decode("ASCII")
    hdr_content = eval_hdr(hdrfile)
    hdrinfo = hdr_content
    scan_def = hdr_content['ScanDefinition']
    region_def = scan_def['Regions']
    nregion = region_def[0]

    if scan_def['Type'] == 'NEXAFS Line Scan':
        StackAxis = scan_def["StackAxis"]
        xvalname = StackAxis['Name']
        npoints = 1
        energies = np.array(region_def[1]['PAxis']['Points'][1:])
        nxPoints = region_def[1]['QAxis']['Points'][0]
        xPoints = np.array(region_def[1]['QAxis']['Points'][1::])
        ximfiles = [[hdrfile.replace('.hdr','_a.xim')]]
        hdrDict = {'energies': energies, \
            'xcoordinate': xvalname, \
            'type': scan_def['Type'], \
            'xstep': (xPoints.max() - xPoints.min()) / nxPoints, \
            'xrange': xPoints.max() - xPoints.min(), \
            'yrange': energies.max() - energies.min(), \
            'ystep': (energies.max() - energies.min()) / float(len(energies)), \
            'xmin': xPoints.min(), \
            'xmax': xPoints.max(), \
            'ymin': energies.min(), \
            'ymax': energies.max()}
        hdrDict['files'] = ximfiles
        hdrDict['scaleBarPixels'] = scaleBarPixels(hdrDict['xrange'],hdrDict['xstep'])
    elif scan_def['Type'] == 'NEXAFS Point Scan':
        xvalname = region_def[1]['PAxis']['Name']
        npoints = 1
        energies = region_def[1]['PAxis']['Points'][1:]
        ximfiles = [[hdrfile.replace('.hdr','.xml')]]
        hdrDict = {'energies': energies, \
            'xcoordinate': xvalname, \
            'files': ximfiles, \
            'type': scan_def['Type']}
    else:
        StackAxis = scan_def["StackAxis"]
        xvalname = StackAxis['Name']
        npoints = StackAxis["Points"][0]
        energies = list(StackAxis["Points"][1::])
        ximfiles = []
        for i in range(nregion):
            ximfiles.append([])
        #if nregion == 1:
        nxPoints = region_def[1]['PAxis']['Points'][0]
        xPoints = np.array(region_def[1]['PAxis']['Points'][1::])
        nyPoints = region_def[1]['QAxis']['Points'][0]
        yPoints = np.array(region_def[1]['QAxis']['Points'][1::])
        for index in range(0,npoints):
            for ireg in range(0,nregion):
                if index < 10: npointStr = '00' + str(index)
                elif index < 100: npointStr = '0' + str(index)
                else: npointStr = str(index)
                if npoints == 1 and nregion == 1: xsuffix = '_a' + '.xim'
                elif npoints == 1: xsuffix = '_a' + str(ireg) + '.xim'
                elif nregion == 1: xsuffix = '_a' + npointStr + '.xim'
                else: xsuffix = '_a' + npointStr + str(ireg) + '.xim'
                ximfile = hdrfile.replace('.hdr',xsuffix)
                ximfiles[ireg].append(ximfile)
        hdrDict = {'energies': energies, \
            'xcoordinate': xvalname, \
            'type': scan_def['Type'], \
            'xstep': (xPoints.max() - xPoints.min()) / nxPoints, \
            'xrange': xPoints.max() - xPoints.min(), \
            'yrange': yPoints.max() - yPoints.min(), \
            'ystep': (yPoints.max() - yPoints.min()) / nyPoints, \
            'xmin': xPoints.min(), \
            'xmax': xPoints.max(), \
            'ymin': yPoints.min(), \
            'ymax': yPoints.max(), \
            'xpoints': nxPoints, \
            'ypoints': nyPoints}

        ##XIM files may not exist if scan was aborted.  Check:
        for i in range(nregion):
            ximfiles[i] = [item for item in ximfiles[i] if os.path.isfile(item)]
        hdrDict['energies'] = energies[0:len(ximfiles[0])]
        hdrDict['files'] = ximfiles
        hdrDict['scaleBarPixels'] = scaleBarPixels(hdrDict['xrange'],hdrDict['xstep'])

    #return energies,xvalname,ximfiles, scan_def['Type']
    return hdrDict

def Dictionary_strings():
    """
    Once Read_hdr is executed, this turns the big dictionary and the set of
    region-descriptor (RefDefs) dictionaries into strings so they can be passed
    to LV
    """
    RegDictStrs = [str(RegDefs[i]) for i in range(0,nregion)]
    BigDictStr = str(hdrinfo)
    return BigDictStr,RegDictStrs

def ImgFileName(ipoint,ireg):
    """
    Once Read_header has been called, get the .xim filename for a given image
    identified by point in the stack and region
    """
    index = ireg+nregion*ipoint
    return ximfiles[index]

def RegionDescriptor(ireg):
    """
    Once Read_header has been called, retrieve the # points, first and last points in P and Q axes.
    """
    r = RegDefs[ireg]
    pa = r['PAxis']
    qa = r['QAxis']
    p = pa['Points']
    q = qa['Points']
    pn = pa['Name']
    qn = qa['Name']
    np = p[0]
    nq = q[0]
    pfirst = p[1] # No, not a flashback to fortran; the 0 element is the # of points, so start at 1
    plast = p[np]
    qfirst = q[1]
    qlast = q[nq]
    return np,nq,pfirst,plast, qfirst, qlast, pn, qn

def RegionDescriptors():
    """
    Once read_header has been called, retrieve all the region descriptors
    """
    allnp = []
    allnq = []
    allpfirst = []
    allqfirst = []
    allplast = []
    allqlast = []
    allpnames = []
    allqnames = []
    for i in range(0,nregion):
        np,nq,pfirst,plast, qfirst, qlast, pn, qn = RegionDescriptor(i)
        allnp.append(np)
        allnq.append(nq)
        allpfirst.append(pfirst)
        allplast.append(plast)
        allqfirst.append(qfirst)
        allqlast.append(qlast)
        allpnames.append(pn)
        allqnames.append(qn)
    return allnp,allnq,allpfirst,allplast,allqfirst,allqlast,allpnames,allqnames


def AxisNames(ireg):
    """
    Once Read_header has been called, get the name of PAxis and QAxis, e.g. 'SampleX' and 'SampleY'
    """
    r = RegDefs[ireg]
    pa = r['PAxis']
    qa = r['QAxis']
    return pa['Name'],qa['Name']

def AxisString(AxisDef):
    """
    Performs the typographical transformations needed to go from the dictionary
    form of a scan-region definition to what gets written in the file header.
    Used by OneRegionString()
    """
    s = str(AxisDef)
    print(s)
    splitstr = "\'Points"
    s12 = s.split(splitstr)
    s1 = s12[0].replace(':',' = ').replace(',',';')
    s2 = "\n\t\t\t\t"+splitstr+s12[1].replace(':',' = ')
    s = s1+s2
    s = s.replace('}','\n};')
    return s

def AxisString1(AxisDef):
    """
    Performs the transformation from the dictionary form of the axis part of the
    scan-region definition to what needs to get written into the file header.
    This version assumes that this dictionary isn't nested
    """
    s = '{'
    for k in AxisDef.keys():
        if (type(AxisDef[k]) is str):
            s = s+' '+k+" = \'"+str(AxisDef[k])+"\';"
        else:
            s = s+' '+k+" = "+str(AxisDef[k])+";"
    s = re.sub('Points = ','\n\t\t\t\tPoints = ',s)+'\n};'
    return s

def GetEnergyRegions():
    """
    Gets the "EnergyRegions" information from the header.  I don't yet know if
    it's still called EnergyRegions when the StackAxis is not energy.  This is
    intended for use in operations in which, for instance, a frame gets deleted
    so the descriptors here have to be adjusted
    """
    si = 'ImageScan'
    if si in hdrinfo:
        imgscan = hdrinfo['ImageScan']
        er = imgscan['EnergyRegions']
        ner = er[0]
        estart = []
        eend = []
        erange = []
        estep = []
        epoints = []
        dwells = []
        for i in range(0,ner):
            ereg = er[i+1]
            estart.append(ereg['StartEnergy'])
            eend.append(ereg['EndEnergy'])
            erange.append(ereg['Range'])
            estep.append(ereg['Step'])
            epoints.append(ereg['Points'])
            dwells.append(ereg['DwellTime'])
        return estart,eend,erange,estep,epoints,dwells
    else:
        scan_def = hdrinfo['ScanDefinition']
        region_def = scan_def['Regions']
        nregion = region_def[0]
        StackAxis = scan_def["StackAxis"]
        E = StackAxis["Points"]
        energies = E[1:]
        e1 = E[1]
        e2 = E[-1]
        er = e2-e1
        ne = len(E)-1
        if ne > 1:
            es = er/(ne-1)
        else:
            es = 0
        dw = scan_def['Dwell']
        return [e1],[e2],[er],[es],[ne],[dw]


def OneRegionString(RegDef):
    """
    Constructs the hdr-file strings that define a single region, starting from the
        Regions = (
    and ending at });
    This is in aid of splitting a multi-region scan into separate 1-region scans.
    """
    pa = RegDef['PAxis']
    qa = RegDef['QAxis']
    ps = '\n\t\t\tPAxis = '+AxisString1(pa)
    qs = '\n\n\t\t\tQAxis = '+AxisString1(qa)    # there's an extra nl before 'QAxis =' for some reason
    s = "\t" + 'Regions = (1,'+'\n{'+ps+qs+'\n});'
    return s

def OnlyOneRegion(ireg):
    """
    Returns a header string in which the Regions tuple has been replaced with
    one describing the single region indexed by ireg.  Also deals with the SpatialRegions
    part of the ImageScan dict (doing this purely typographically) and the keyword
    'MultipleRegions' which needs to be set F
    """
    regstr = OneRegionString(RegDefs[ireg])
    strings = header_string.splitlines()
    i1 = -1     # find boundaries of Regions section
    i2 = -1
    for i in range(0,len(strings)):
        s = strings[i]
        if (s.find('Regions =') >= 0) & (i1 < 0):
            i1 = i   # i is index of first line of Regions section
        elif (i1 >= 0) & (s.find('});') >= 0):
            i2 = i
            break
    strings[i1:i2+1] = regstr.splitlines()  # break Regions section into lines
    for i in range(i2,len(strings)):
        s = strings[i]
        if s.find('SpatialRegions =') >= 0:
            i3 = i   # i3 is index of first line of SpatialRegions section
            break
    for i in range(i2,i3):  # Change the value of the MultipleRegions flag to F
        strings[i] = re.sub('MultipleRegions += +[tT]rue','MultipleRegions = false',strings[i])
    srstart = 'SpatialRegions = (1,'
    srline = re.sub(',$',');',strings[i3+ireg+1])
    srend = strings[i3+nregion+1]
    onesr = [srstart,srline,srend]
    strings[i3:i3+nregion+2] = onesr    # the new SpatialRegions tuple
    newline = os.linesep
    return newline.join(strings)

def SplitRegionFilenames(hdr_file, copyfiles=False):
    """
    Returns a set of new .hdr-file names containing region-number suffixes.
    Also returns a list of new .xim-file names corresponding to those in
    ximfiles[]. This assumes that Read_header() has been called.
    Iff copyfiles flag is True, then copy the contents of the original .xim
    files to the new ones
    """
    import shutil
    new_hdr_files = []
    new_xim_files = []
    scan_def = hdrinfo['ScanDefinition']
    if (scan_def['Type'] == 'Image Scan') | (nregion == 1):
        new_hdr_files.append(hdr_file)
        new_xim_files = ximfiles[:]
    else:
        for ireg in range(0,nregion):
            s = str(ireg)+'.hdr'
            new_hdr_files.append(hdr_file.replace('.hdr',s))
        ic = 0
        for index in range(0,npoints):
            xs = xim_suff(index,0,1)
            for ireg in range(0,nregion):
                hf = new_hdr_files[ireg]
                hf1 = hf.replace('.hdr',xs)
                new_xim_files.append(hf1)
                if copyfiles:
                    print(shutil.copy(ximfiles[ic],hf1))
                ic = ic+1
    return new_hdr_files,new_xim_files

def GetScanType():
    scan_def = hdrinfo['ScanDefinition']
    return scan_def['Type']

def dict2hdr(HdrDictStr):
    """ Turns a dictionary string, at least one of the StackAxis kind, into
    the corresponding part of the header string so that a modified file may be
    written.  The intent of this pair of routines is that if it's necessary to
    modify the values, we pull up the dictionary string, turn it into a dict,
    modify that dict using ReviseEdict(), then turn the result into a header
    string, which can then get inserted into the header in place of the original.
    The Points key gets an extra newline for some reason
    """
    hdrdict = eval(HdrDictStr)
    s = '{'
    for k in hdrdict:
        val = hdrdict[k]
        if type(val) is str:
            sval = "'"+val+"'"
        else:
            sval = str(val)
        if k == 'Points':
            ks = '\n '+k
        else:
            ks = ' '+k
        s = s+ks+' = '+sval+'; '
    s = s+'\n'+'};'
    return s

def ReviseEdict(energies):
    """ Edits the dictionary for energies (StackAxis) to use a new set of energies
    This modifies the hdrinfo dict in the globals and returns the corresponding
    dictionary string, which should get written into the LV global Dot_hdr global.vi,
    entry Header dictionary string.  Also returns the piece of the Raw header
    that pertains to the new dictionary, starting from just after 'StackAxis ='"""
#    d = eval('{'+Edictstr+'}')
    ne = len(energies)
    ee = np.ndarray.tolist(energies)
#    d['Points'] = tuple([ne]+ee)
#    d['Min'] = min(energies)
#    d['Max'] = max(energies)
# The concatenation using '+' only works because the energy array has been
# turned into a list.
    hdrinfo['ScanDefinition']['StackAxis']['Points'] = tuple([ne]+ee)
    hdrinfo['ScanDefinition']['StackAxis']['Min'] = min(energies)
    hdrinfo['ScanDefinition']['StackAxis']['Max'] = max(energies)
    Edictstr = str(hdrinfo['ScanDefinition']['StackAxis'])
    return str(hdrinfo),dict2hdr(Edictstr)



from skimage.feature import register_translation
from scipy.ndimage import fourier_shift
from scipy import ndimage
def RegisterImage(ref_img, target_img, upsample=100):
    """
    Registers target_img to ref_img, returning shift vector as shifts.  Upsample
    is the upsampling factor, for which 100 seems to be good.  This
    comes from the skimage package.  Note that the assumption is that y is the
    first index, so the shifts are returned as y,x.
    """
    shifts,error,phase = register_translation(ref_img,target_img,upsample)
    offset_image = ndimage.shift(target_img,shifts)
    return offset_image,shifts

def ShiftImage(Orig_img,shifts):
    """
    shifts Orig_img by amounts shifts.  If you ShiftInage an image by amount
    [dy,dx], then RegisterImage(original_image, shifted_image) will return
    a shift of [-dy,-dx] and an approximation of original_image.
    """
    import scipy
    from scipy import ndimage
    offset_image = ndimage.shift(Orig_img,shifts)
    return offset_image


from scipy.optimize import curve_fit
import numpy.polynomial.polynomial as pv

def ramp(x,x1,x2,leftval,rightval):
    """
    For each value in x returns:
        leftval                                 x <=x1
        linear ramp from leftval to right val   x member [x1,x2]
        rightval                                x >x2
    """
# I wanted to say things line min(1.,(xx-x1)/(x2-x1)) but it seems to be
# illegal to do min(scaler,array)
# Whoops, I recently learned about np.clip() which does what I want, but
# I'm not going to change it.
    r = [leftval+(rightval-leftval)*max(0.,min(1.,(xx-x1)/(x2-x1))) for xx in x]
    return r

def xscale(x):
    """
    Scales x so that it goes 0 to 1.  Really should do -1 to 1 for high-degree
    polynomials, but this is good enough for the default 3.
    """
    x1 = np.amin(x)
    x2 = np.amax(x)
    return (x-x1)/(x2-x1)

def jumpfit(x,x1_in,x2_in,y):
    """
    fits y to a polynomial times a step.  The step is a ramp which gees from a
    value of 1 at x<=x1 to an unknown jump for x>=x2.  The polynomial is
    hardwired to be cubic; no checking is done to be sure that there are enough
    points at either end of the range to have the fit make sense.  It uses as
    an initial guess the polynomial fit of the whole dataset with jump==1.

    The abscissa values get scaled internally so they run 0..1 so that the
    polynomial doesn't blow up

    Inputs:
        x       Abscissae
        x1,x2   Range over which data jumps. x2 must be >= x1
        y       Ordinates

    Outputs:
        jump    The jump factor
        yfit    The fitted y with jump
    """
    x0 = np.amin(x)
    x3 = np.amax(x)
    scalex12 = xscale(np.array([x0,x1_in,x2_in,x3]))
    x1 = scalex12[1]
    x2 = scalex12[2]
    scaledx = xscale(x)
    cguess = pv.polyfit(scaledx,y,3)
    def jumpfitfunc(scaledx,jump,c0,c1,c2,c3):
        c = np.array([c0,c1,c2,c3])
        return pv.polyval(scaledx,c)*ramp(scaledx,x1,x2,1.,jump)
    popt,pcov = curve_fit(jumpfitfunc,scaledx, y, p0=np.append(1.,cguess))
    jump = popt[0]
    c0 = popt[1]
    c1 = popt[2]
    c2 = popt[3]
    c3 = popt[4]
    yfit = jumpfitfunc(scaledx,jump,c0,c1,c2,c3)
    return jump,yfit

def mask_img(image1D,mask):
    """
    Image1D is a stack of unrolled images image[energy,pixel] and mask is a BOOL
    flag mask[pixel].  This returns a subset of image1D for which only unmasked
    pixels are given and a list of pixel indices such that
    masked_image[:,mpx] = image1D[:,OK_index[mpx]]

    For some reason, the np.asarray(np.where(mask),dtype=int) construction
    returns a 2D array with the first dimension being length 1.  That's why the
    slice at the end of the OK_index = line.
    """
    OK_index = np.asarray(np.where(mask),dtype=int)[0,:]
    masked_image = image1D[:,OK_index]
    return masked_image,OK_index

def install_masked_img(image1D,masked_image,mask,zero_fill):
    """
    It's assumed that we  have a stack, unrolled into 1D images image1D[e,pixel],
    and a mask[pixel].  We have done mask_img(image1D,mask), then done something
    to the resulting masked_image array.  We now want the results to be put into
    the entire image such that those pixels for which the mask is T are replaced
    by the corresponding pixels of masked_image, while those for which mask is F
    are left as-is.

    If zero_fill is True then elements for which the mask is F are set to 0
    """
    new1D = image1D.copy()
    indices = np.asarray(np.where(mask),dtype=int)[0,:]
    new1D[:,indices] = masked_image
    if zero_fill:
        indices = np.asarray(np.where(~mask),dtype=int)[0,:]
        new1D[:,indices]=0.
    return new1D

def cluster(data,nclus,batch_size):
    from sklearn.datasets import load_sample_image
    from sklearn.cluster import KMeans,MiniBatchKMeans
    """
    Shell around the scikit.sklearn K-means clustering routines.
    Inputs:
        X[Npts,Ndim]    Coordinates of Npts data points in Ndim-dimensional space
        nclus           # of clusters wanted
        batch_size      If batch_size<=0, does the regular KMeans, otherwise
                        does MiniBatchKmeans with the given batch_size
    Outputs:
        labels[Npts]                Label of which cluster each point belongs to
        cluster_centers[nclus,Ndim] Coordinates of cluster centers
    """
    if batch_size<=0:
        kmeans = KMeans(nclus).fit(data)
    else:
        kmeans = MiniBatchKMeans(nclus,batch_size=batch_size).fit(data)
    return kmeans.labels_,kmeans.cluster_centers_

def cluster_sums(data,cluster_labels,ncluster):
    """
    given a set of data[px,e] and a set of cluster labels label[px], this
    computes, for each cluster c, the average value of data[index,e] for values
    of index such that label[index] == c.
    """
    ne = np.shape(data)[1]
    sums = np.array([[data[np.where(labels == c),i].sum() for c in range(ncluster)] for i in range(ne)])
    nums = np.array([(labels == c).sum() for c in range(ncluster)])
    nums1 = np.clip(nums,1,None)
    avg = sums/nums1
    return nums,avg

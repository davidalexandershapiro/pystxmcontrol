from pystxmcontrol.controller.scripter import *

# ##set up and execute basic metadata required of all scans
meta = {"proposal": "BLS-000625", "experimenters":"Ditter, Shapiro", "nxFileVersion":3.0, "Sample": "Dong Hyun: R1"}
meta["xcenter"] = 0
meta["xrange"] = 5
meta["xpoints"] = 10
meta["ycenter"] = 0
meta["yrange"] = 5
meta["ypoints"] = 15
meta["energyStart"] = 700
meta["energyStop"] = 700
meta["energyPoints"] = 1
meta["dwell"] = 10
meta["spiral"] = False
meta["autofocus"] = True
meta["cmap"] = "viridis" #viridis', 'plasma', 'inferno', 'magma', 'cividis', 'Greys',
meta["daq list"] = ["default"]
meta["comment"] = "test scan"
print(meta)

#################################################################################################
##Get Server Config##############################################################################
MOTORS,SCANS,POSITIONS,DAQS,MAIN_CONFIG = get_config()

#################################################################################################
##Single Motor Scan##############################################################################
##This only looks at the X motor points and range
# meta["xmotor"] = "Dummy Motor" #choose the motor to scan
# meta["daq"] = "default" #choose the detector to measure
# filename = single_motor_scan(meta)
# print(filename)

#################################################################################################
# ##Two Motor Scan##############################################################################
# meta["xmotor"] = "OSA_X"
# meta["ymotor"] = "OSA_Y"
# meta["daq"] = "default"
# filename = two_motor_scan(meta)
# print(filename)

#################################################################################################
##basic stxm scan################################################################################
# print(stxm_scan(meta))

#################################################################################################
##Move Motor#####################################################################################
# move_motor("Energy", 1100.)

#################################################################################################
##Get Data from DAQ##############################################################################
# print(read_daq("default", 100))
#data2 = read_daq("ccd", 100)

#################################################################################################
##spiral stxm scan###############################################################################
#meta["spiral"] = True
#print(stxm_scan(meta))

#################################################################################################
##stxm tomography scan###########################################################################
#coarseR = np.linspace(-40,40,10)
#for r in coarseR:
#    move_motor("CoarseR",r)
#    stxm_scan(meta)
    
#################################################################################################
##XMCD and 2 energies############################################################################
#meta["energyStart"] = 700
#meta["energyStop"] = 710
#meta["energyPoints"] = 2
#polarizations = [-1,1]
#for p in polarizations:
#    print("Moving polarization to %s" %p)
#    move_motor("POLARIZATION",p)
#    print(stxm_scan(meta))
    
#################################################################################################
##Ptychography###################################################################################
##the scan function will automatically calculate the step size so the number of points should be 
##calculated in advance to give the correct step size
# meta = {"proposal": "BLS-000625", "experimenters":"Ditter,Shapiro", "nxFileVersion":2.1,"Sample":"Dong Hyun: R1"}
# meta["xcenter"] = 0
# meta["xrange"] = 5.5
# meta["xpoints"] = 55
# meta["ycenter"] = 0
# meta["yrange"] = 4.5
# meta["ypoints"] = 45
# meta["xstep"] = 0.05
# meta["ystep"] = 0.05
# meta["energyStart"] = 851
# meta["energyStop"] = 852
# meta["energyPoints"] = 1
# meta["dwell"] = 10.0
# meta["spiral"] = False
# meta["defocus"] = True
# meta["doubleExposure"] = False
# meta["autofocus"] = False #setting False prevents moving to calibrated focus position at scan start
# meta["scan_type"] = "Ptychography Image"
# meta["mode"] = "ptychographyGrid"
# print(ptychography_scan(meta))

#################################################################################################
##Point Spectrum#################################################################################
#en = np.linspace(700,799,100)
#spec = np.zeros((100))
#i = 0
#t0 = time.time()
#for energy in en:
#    move_motor("Energy",energy)
#    spec[i] = read_daq("default",100)
#    i += 1
#print("Point spectrum took %.2f ms" %((time.time() - t0)*1000.))

# #################################################################################################
# ##Particle Finder Scan###########################################################################
# meta = {"proposal": "BLS-000625", "experimenters":"Alex, David", "nxFileVersion":2.1,"Sample":"Standards"}
# overview_scan = '/cosmic-dtn/groups/cosmic/Data/2024/05/240508/NS_240508048.stxm'
# meta["xstep"] = 0.05
# meta["ystep"] = 0.05
# meta["energyStart"] = 704
# meta["energyStop"] = 708
# meta["energyPoints"] = 2
# meta["dwell"] = 0.1
# meta["spiral"] = True
# meta["autofocus"] = True
#
# scan_list = decimate(overview_scan)
# meta["scan_type"] = "Image"
# meta["mode"] = "continuousLine"
# print(len(scan_list))
# multi_region_stxm_scan(meta,scan_list)

#meta["xstep"] = 0.1
#meta["ystep"] = 0.1
#meta["spiral"] = False
#meta["scan_type"] = "Ptychography Image"
#meta["mode"] = "ptychographyGrid"
#meta["dwell"]=10.
#meta["defocus"]=True
#meta["doubleExposure"]=False
#multi_region_stxm_scan(meta,scan_list[10:12])

#################################################################################################
##CoarseY Adjust Tomography Scan#################################################################
#Focus at zero degrees only!!
#from scipy.interpolate import interp1d
#import numpy as np
#meta = {"proposal": "BLS-000625", "experimenters":"Ditter,Shapiro", "nxFileVersion":2.1,"Sample":"Dong Hyun: R1"}
#meta["xcenter"] = 0
#meta["xrange"] = 5
#meta["xpoints"] = 50
#meta["ycenter"] = 0
#meta["yrange"] = 3.5
#meta["ypoints"] = 35
#meta["xstep"] = 0.1
#meta["ystep"] = 0.1
#meta["energyStart"] = 500
#meta["energyStop"] = 560
#meta["energyPoints"] = 20
#meta["dwell"] = 0.2
#meta["spiral"] = True
#meta["defocus"] = True
#meta["doubleExposure"] = False
#meta["autofocus"] = False #setting False prevents moving to calibrated focus position at scan start
#meta["scan_type"] = "Image" #"Ptychography Image"
#meta["mode"] = "continuousLine" #"ptychographyGrid"

#n_angles = 100
#r_start = -50
#r_stop = 50
#z0 = -14516.0 #-11255.0 #zone plate in focus at 0 degrees
#y0 = 158.6

# theta = np.array((-70,-60,-50,-40,-30,-20,-10,0,10,20,30,40,50,60,70))
# ymeas = y0 + np.array((26.7,-38.9,-78.4,-103.6,-120.9,-132.3,-139.5,-144.6,-145.5,-144.2,-139.2,-129.8,-113.5,-87.2,-41.6))
# z = np.array((-72.69,-47.22,-34.9,-28.8,-24.1,-21.1,-18.8,0.,16.6,20.6,18.5,28.1,27.9,39.6,61.9))
# zmeas = z0 - np.array((-247.6,-174.9,-127.7,-92.8,-64.,-39.9,-18.8,0.,16.6,37.2,55.7,83.8,111.7,151.3,213.2))
# scanX = np.array((0.8,0.7,0.5,0.3,0.0,-0.2,-0.5,-0.9,-1.3,-1.3,-1.5,-1.8,-2.1,-2.6,-3.0))
# scanY = -np.array((1.2,1.1,0.6,0.6,0.2,0.3,0.5,-0.3,0.0,0.0,0.1,0.1,0.5,0.3,-0.6))

#theta = np.array((-75,-70,-60,-50,-40,-30,-20,-10,0,10,20,30,40,50,60,70,75))
#ymeas = np.array((198.2,151.7,96.5,64.1,41.7,28.3,19.9,14.8,13.6,15.2,19.9,27.9,42.1,62.3,96.6,154.0,200.1))
#z = np.array((-50.0,-68.13,-42.6,-32.0,-27.3,-23.7,-21.1,-19.3,0.,21.74,21.03,21.05,26.04,34.88,45.12,66.6,49.0))
#zmeas = z0 - np.array((-284.1,-234.1,-166.0,-123.4,-91.4,-64.1,-40.4,-19.3,0.,21.74,42.8,63.8,89.9,124.7,169.9,236.5,285.46))
#scanX = np.array((2.0,2.0,1.7,1.5,1.3,1.0,0.7,0.6,0.2,-0.1,-0.4,-0.7,-1.2,-1.3,-1.8,-2.8,-3.6))
#scanY = -np.array((1.3,1.0,0.9,1.4,0.2,0.0,0.0,-0.4,-0.2,-0.2,-0.1,-0.3,0.1,-0.4,-0.2,-0.8,-1.3))

#yf = interp1d(theta,ymeas,kind="cubic")
#zf = interp1d(theta,zmeas,kind="cubic")

#import matplotlib.pyplot as plt
#plt.plot(theta,ymeas)
#plt.figure()
#plt.plot(theta,zmeas)
#plt.xlabel('Rotation Angle (deg)')
#plt.show()

#angles = np.linspace(r_start,r_stop,n_angles)
#for i in range(n_angles):
#    meta["xcenter"] = interp1d(theta,scanX,kind="cubic")(angles[i])
#    meta["ycenter"] = interp1d(theta,scanY,kind="cubic")(angles[i])
#    print(meta['xcenter'],meta['ycenter'])
#    print("Moving motors: CoarseR,CoarseY,ZonePlateZ: %.4f, %.4f, %.4f" %(angles[i],yf(angles[i]),zf(angles[i])))
#    if not moveMotor("CoarseR",angles[i]):
#        print("Failed to move CoarseR.  Continuing...")
#    if not moveMotor("CoarseY",yf(angles[i])):
#        print("Failed to move CoarseY.  Continuing...")
#    if not moveMotor("ZonePlateZ",zf(angles[i])):
#        print("Failed to move ZonePlateZ.  Continuing...")
#    time.sleep(5.)
#    print(stxm_scan(meta))
#    #print(ptychography_scan(meta))











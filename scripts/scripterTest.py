from pystxmcontrol_mcp.scripter import scripter
import numpy as np

host = '127.0.0.1'
port = 9999
S = scripter(host,port)

#################################################################################################
##Get Server Config##############################################################################
MOTORS, SCANS, POSITIONS, DAQS, CONFIG = S.get_config()
S.help()

#################################################################################################
##Move a motor and get position##################################################################
# print(S.get_motor_position('CoarseR'))
# print(S.move_motor('CoarseR',10))
# print(S.get_motor_position('CoarseR'))

#################################################################################################
##update a stxm scan and execute#################################################################
# print(S.scan["scan_type"])
# print(S.update_scan(scan_type="Image",
#                     dwell=0.2,
#                     x_center=100,
#                     x_range=5,
#                     x_points=100,
#                     y_center=100,
#                     y_range=5,
#                     y_points=100,
#                     defocus=False,
#                     spiral=False,
#                     energy_start=700,
#                     energy_stop=700,
#                     energy_points=1,
#                     double_exposure=False,
#                     daq_list=['default'],
#                     retract=True))
# print(S.stxm_scan())

#################################################################################################
##Get Data from DAQ##############################################################################
print(S.read_daq("default", 100))
data2 = S.read_daq("CCD", 100)

#################################################################################################
##spiral stxm scan###############################################################################
# print(S.update_scan(spiral=True))
# print(S.stxm_scan())

#################################################################################################
##stxm tomography scan###########################################################################
# coarseR = np.linspace(-40,40,10)
# for r in coarseR:
#    S.move_motor("CoarseR",r)
#    S.stxm_scan()
    
#################################################################################################
##XMCD and 2 energies############################################################################
# print(S.update_scan(energy_start=700,energy_stop=710,energy_points=2))
# polarizations = [-1,1]
# for p in polarizations:
#    print("Moving polarization to %s" %p)
#    S.move_motor("POLARIZATION",p)
#    print(S.stxm_scan())
    
#################################################################################################
##Ptychography###################################################################################
# print(S.update_scan(scan_type="Ptychography Image",
#                     dwell=10,
#                     x_points=10,
#                     y_points=10,
#                     defocus=True,
#                     spiral=False,
#                     energy_start=700,
#                     energy_points=1,
#                     double_exposure=False,
#                     daq_list=['default','CCD'],
#                     retract=True))
# print(S.stxm_scan())


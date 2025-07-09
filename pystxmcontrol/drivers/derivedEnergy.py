from pystxmcontrol.controller.motor import motor
import time
import numpy as np
class derivedEnergy(motor):
    def __init__(self, controller = None, simulation = False):
        self.controller = controller
        self.simulation = simulation
        self.position = 0.5
        self.offset = 0.
        self.units = 1.
        self.axes = {}
        self.moving = False
        #These numbers below should come from a text file but just added here for now
        #self.input_energies = np.array((250,350.,450.,545.,645.,708.,778.,852.,1200,1500,2000,2500)) #these are what's commanded
        #self.output_energies = np.array((250, 350.,450.,545.,645.,708.,778.,852.,1200,1500,2000,2500)) #these are what the beamline produces

        self.input_energies = np.array((250,350.,450.,545.,645.,708.,710.,778.,852.,1200,1500,2000,2250,2262.3,2362.3,2462.3)) #these are what's commanded
        self.output_energies = np.array((250, 350.,450.,545.,645.,708,710.,778.,852.,1200,1500,2000,2250,2382.7,2482.7,2582.7)) #these are what the beamline produces

    def getStatus(self, **kwargs):
        return self.moving

    def stop(self):
        return
        
    def getZonePlateCalibration(self):
        ##should this use the position provided by the beamline or the theoretical value?
        ##I don't trust the beamline numbers
        A0 = self.config["A0"]
        A1 = self.config["A1"]
        A2 = self.config["A2"]
        A3 = self.config["A3"]
        energy = self.getPos()
        self.calibratedPosition = -(A0 + A1 * energy + A2 * energy**2 + A3 * energy **3)

        #Calibration using interpolation between multiple points.
        self.zp_energies = np.array([340, 400,440,470,500,510,515,520,525,530,535,540,545,550,560,590,620,650,
                                     680,690,700,710,720,730,740,760,770,785,800,820,835,850,865,880,900,1000,1050,1100,1150])
        # put zp position of best focus in a focus scan (without actually changing the focus) here.
        self.zp_measurements = -np.array([4488,5287, 5825, 6222, 6624, 6764, 6830, 6901, 6967, 7034, 7106, 7171, 7238, 7298, 7413, 7772, 8138, 8520,
                                          8933,9094,9217,9362,9497,9626,9759,10032,10168,10378, 10615,10947,11205,11413,11624,11833, 12104, 13481, 14173, 14869,15564])



#        self.zp_energies = np.array([697.5,701,706])
#        self.zp_measurements = -np.array([9687,9725,9793.4])

     #   if energy>=self.zp_energies.min() and energy<=self.zp_energies.max():
     #       self.calibratedPosition = np.interp(energy, self.zp_energies, self.zp_measurements)
            #print('would move zone plate to {}'.format(np.interp(energy, self.zp_energies, self.zp_measurements)))

        return self.calibratedPosition

    def moveBy(self, energy_step):
        if not(self.simulation):
            self.moving = True
            self.getPos()
            self.moveTo(self.position + energy_step)
            self.moving = False
        else:
            self.position = self.position + step

    def moveTo(self, energy):
        if not(self.simulation):
            self.moving = True
            energy = np.interp(energy,self.output_energies,self.input_energies)
            print("Moving beamline to energy: %.2f" %(energy))

            if abs(energy - self.position) > 50.:
                self.axes["axis1"].moveTo(energy - 1.)
                self.axes["axis1"].moveTo(energy)
            # elif abs(energy - self.position) < 30.:
            #     self.axes["axis1"].moveTo(energy - 30.)
            #     self.axes["axis1"].moveTo(energy)
            else:
                self.axes["axis1"].moveTo(energy)
            self.calibratedPosition = self.getZonePlateCalibration()
            self.axes["axis2"].moveTo(self.calibratedPosition)
            self.axes["axis2"].calibratedPosition = self.calibratedPosition
            self.moving = False
            self.getPos()
        else:
            self.position = pos

    def getPos(self):
        if not(self.simulation):
            self.position = self.axes["axis1"].getPos()
            interp_energy = np.interp(self.position,self.input_energies,self.output_energies)
            self.position = interp_energy
            #print("Reading beamline energy: {}. Setting GUI energy: {}".format(self.position, interp_energy))
            return self.position
        else:
            return self.position

    def connect(self, axis = None):
        self.axis = axis
        self.position = self.getPos()
        self.calibratedPosition = self.getZonePlateCalibration()
        self.axes["axis2"].calibratedPosition = self.calibratedPosition

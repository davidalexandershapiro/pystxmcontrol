# -*- coding: utf-8 -*-
from pylibftdi import Device, Driver
from pystxmcontrol.controller.hardwareController import hardwareController
import time
import struct
import numpy as np

class nptController(hardwareController):

    def __init__(self, address = '7340010', port = None, simulation = False):

        """
            :param address: Specify the nPoint controller ID
            :type address: string
            :param port: Port not needed for this driver
            :type port: int
            :param simulation: Specify simulation mode
            :type simulation: boolean
            :return: nptController object

            Main nPoint Controller Class, initialize with the controller ID for communication with the driver.
        """

        # refer to page 29 of NPoint manual for device write/read formatting info
        self.devID = address
        self.port = port
        self.isInitialized = False
        #axis base address
        self.axis1address = 0x11831000
        self.axis2address = 0x11832000

        #various offsets. To be summed with base address for an axis.
        self.positionOffset = 0x218 # "Digital Position Command" used for both reading and writing positions
        self.pOffset = 0x720 # Proportional Gain
        self.iOffset = 0x728 # Integral Gain
        self.dOffset = 0x730 # Derivative Gain
        self.sOffset = 0x084 # servo state: 1 closes the loop, 0 opens it.
        self.dsrOffset = 0x334 # digital sensor reading

        #command prefixes
        self.readCom = 0xA0 # prepends all read commands
        self.writeCom = 0xA2 # prepends all write commands
        self.readArrayCom = 0xA4 # to read multiple 32bit values, e.g. to read a single 64bit float.
        self.writeNextCom = 0xA3 # to write a single 32bit right after issuing a writeCom, at its following address.

        #some more whole addresses
        self.zeroPosAddr = 0xEC000004 # write a 32bit value to this address to set current position to zero. Setting 1st LSB to 1 zeros the first channel, 2nd LSB the second channel, ...
        self.axis1SensorGainAddr = 0x11831245
        self.axis2SensorGainAddr = 0x11832245

        #Sensor Gain. should really be read using above address. To be added later...
        self.sensorGain = 10.577 # 1nm = sensorGain*[quadrature counts]
        self.axesList = ["x","y"]
        self._stageRange = 100.
        self._countsPerMicron = 2**20 / self._stageRange

    def initialize(self, simulation = False):
        self.simulation = simulation
        self.isInitialized = True
        if not(self.simulation):
            self.dev = Device(device_id = self.devID)

    def getAddress(self, axis = None):
        if axis == 1:
            return 0x11831000
        elif axis == 2:
            return 0x11832000
        else:
            return None

    def getAxisAddress(self, axis = None):
        if axis == 1:
            return self.axis1address
        elif axis == 2:
            return self.axis2address
        else:
            return None
    
    def getAxis(self,axis=None):
        if axis in self.axesList:
            return self.axesList.index(axis) + 1
        else:
            return False

    def moveTo(self, axis = None, pos = None, checkStatus = False):
        if axis:
            writeAddr = self.posAddress(axis)
            pos = int(round(float(self.nmToSteps(pos * 1000.))))
            pos = int(self.signedIntToHex(pos),16)
            self.writeToDev4B(writeAddr, pos)

    def getPos(self, axis = None):
        readAddr = self.dsrAddress(axis)
        posInSteps = self.readFromDev4B(readAddr)
        return self.stepsToNM(posInSteps) / 1000.

    def get_status(self, axis=None):
        readAddr = self.posAddress(axis)
        moving = bool(self.readFromDev4B(0x1182906C))
        return moving

#####################################################################################################

    def DaqConnect(self):#connect DAQ devices
        try:
            devices = get_daq_device_inventory(InterfaceType.USB)
            number_of_devices = len(devices)
            daq_device= DaqDevice(devices[0])
            daq_device.connect()
            for i in range(number_of_devices):
                print(devices[i].product_name,'is connected.')
            return daq_device
        except:
            print("No DAQ device")

    def devlist(self): # should really be done outside of this script; but I'll just put it here too. SUDO PRIVILEGES NEEDED TO WORK, OTHERWISE LIST COMES BACK EMPTY.
        return Driver().list_devices()

    def posAddress(self, axis):
        if axis == 1:
            addr = self.axis1address + self.positionOffset
        elif axis == 2:
            addr = self.axis2address + self.positionOffset
        else:
            raise("invalid axis")
        return addr

    def dsrAddress(self, axis): #digital sensor reading
        if axis == 1:
            addr = self.axis1address + self.dsrOffset
        elif axis == 2:
            addr = self.axis2address + self.dsrOffset
        else:
            raise("invalid axis")
        return addr

    def pAddress(self, axis): # proportional gain
        if axis == 1:
            addr = self.axis1address + self.pOffset
        elif axis == 2:
            addr = self.axis2address + self.pOffset
        else:
            raise("invalid axis")
        return addr

    def iAddress(self, axis):
        if axis == 1:
            addr = self.axis1address + self.iOffset
        elif axis == 2:
            addr = self.axis2address + self.iOffset
        else:
            raise("invalid axis")
        return addr

    def dAddress(self, axis):
        if axis == 1:
            addr = self.axis1address + self.dOffset
        elif axis == 2:
            addr = self.axis2address + self.dOffset
        else:
            raise("invalid axis")
        return addr

    def sAddress(self, axis):
        if axis == 1:
            addr = self.axis1address + self.sOffset
        elif axis == 2:
            addr = self.axis2address + self.sOffset
        else:
            raise("invalid axis")
        return addr

    def hexToSignedInt(self, h): #converts hex numbers to signed int
        hInt = int(h[2:],16)
        if hInt <= 0x7FFFFFFF:
            return hInt
        else:
            return hInt - 0x100000000

    def signedIntToHex(self, si):
        if si < 0:
            si += 0x100000000
        return hex(si)

    def float64ToHex(self, f):
        return hex(struct.unpack('<Q', struct.pack('<d', f))[0])

    def float32Tohex(self,f):  
        return hex(struct.unpack('<I', struct.pack('<f', f))[0]) 

    def hexToFloat64(self, h):
        return struct.unpack('<d', struct.pack('<Q', int(h, 16)))[0]

    def readFromDev4B(self, addr): # to read 32bit values, e.g. position or servo state
        # format: [readCom] [address] [0x55] for a total of 6 bytes
        readTX = 0x55 * 16**10 + addr * 16**2 + self.readCom
        readTX = bytearray.fromhex(hex(readTX)[2:]) # Get the bytes in decreasing significance (need to be reversed)
        readTX.reverse()
        dataw = self.dev.write(bytes(readTX))
        if dataw != 6:
            print("dataw =", dataw)
            raise("reading value: writing to \"read address\" on device failed")
        datar = self.dev.read(10)
        while datar == b'':
            datar = self.dev.read(10)
        datar = bytearray(datar)
        datar.reverse()
        val = datar[1:5]
        val = '0x' + val.hex()
        return self.hexToSignedInt(val)

    def readArray(self, numBytes, addr): # e.g. to read PID parameters as 64bit float, use numBytes=2
        # format: [readArrayCom] [address] [numBytes] [0x55] for a total of 10 bytes
        readTX = 0x55 * 16**18 + numBytes * 16**10 + addr * 16**2 + self.readArrayCom
        readTX = bytearray.fromhex(hex(readTX)[2:]) # Get the bytes in decreasing significance (need to be reversed)
        readTX.reverse()
        dataw = self.dev.write(bytes(readTX))
        if dataw != 10:
            print("dataw =", dataw)
            raise("reading value: writing to \"read address\" on device failed")
        datar = self.dev.read(6 + 4*numBytes)
        while datar == b'':
            datar = self.dev.read(6 + 4*numBytes)
        datar = bytearray(datar)
        datar.reverse()
        val = datar[1:1+4*numBytes]
        retVal = '0x' + val.hex()
        return retVal

    def writeToDev4B(self, addr, val): # to write 32bit values, e.g. position or servo state
        # format: [writeCom] [addr] [val/data] [0x55] for a total of 10 bytes: [addr] and [val] are 4 bytes each.
        writeTX = 0x55 * 16**18 + val * 16**10 + addr * 16**2 + self.writeCom
        writeTX = bytearray.fromhex(hex(writeTX)[2:]) # Get the bytes in decreasing significance (need to be reversed)
        writeTX.reverse()
        dataw = self.dev.write(bytes(writeTX))
        if dataw != 10:
            print("dataw =", dataw)
            raise("writing value: writing to \"write address\" on device failed")

    def writeNext(self, val): # writes a single 32bit value at the current memory address.
        writeTX = 0x55 * 16**10 + val * 16**2 + self.writeNextCom
        writeTX = bytearray.fromhex(hex(writeTX)[2:])
        writeTX.reverse()
        dataw = self.dev.write(bytes(writeTX))
        if dataw != 6:
            print("dataw =", dataw)
            raise("writing value: writing to \"write address\" on device failed")

    def writeFloat64(self, addr, val):
        val = self.float64ToHex(float(val))
        val = val[2:-1] if val[-1] == 'L' else val[2:]
        val = val.zfill(16)
        val = bytearray.fromhex(val)
        self.writeToDev4B(addr, int(val[4:8].hex(),16))
        self.writeNext(int(val[:4].hex(),16))

    def writeFloat32(self,val):    
        val = self.float32Tohex(float(val))
        val = val[2:-1] if val[-1] == 'L' else val[2:]   
        val = val.zfill(8) #for 0.0 this is needed 
        val = bytearray.fromhex(val)    
        self.writeNext(int(val.hex(),16)) 

    def dsrRead(self, axis):
        readAddr = self.dsrAddress(axis)
        dsrInSteps = self.readFromDev4B(readAddr)
        return self.stepsToNM(dsrInSteps)

    '''
    def sgRead(self, axis): # sensor gain
        if axis == 1:
            sg = self.readFromDev4B(self.axis1SensorGainAddr)
        elif axis == 2:
            sg = self.readFromDev4B(self.axis2SensorGainAddr)
        return sg
    '''



    def stepsToNM(self, steps):
        return steps / self.sensorGain

    def nmToSteps(self, nm):
        return int(nm * self.sensorGain)

    def timeToCounts(self, dtime):  # dwelltime unit is seconds
        return int(dtime / 0.000024)

    def vLimitToCountLoop(self, vLimit):
        return vLimit * (1048575. / self._stageRange) * 0.024 / 2.

    def speedToLoopCycle(self, RevSpeed):
        return 1 / (RevSpeed * 0.000024)

    def pRead(self, axis):
        addr = self.pAddress(axis)
        retVal = self.readArray(2, addr)
        retVal = self.hexToFloat64(retVal)
        return retVal

    def iRead(self, axis):
        addr = self.iAddress(axis)
        return self.hexToFloat64(self.readArray(2, addr))

    def dRead(self, axis):
        addr = self.dAddress(axis)
        return self.hexToFloat64(self.readArray(2, addr))

    def pidRead(self, axis = 1):
        p = self.pRead(axis)
        i = self.iRead(axis)
        d = self.dRead(axis)
        return (p,i,d)

    def sRead(self, axis):
        #reads servo state: return value of 0 means off, 1 means on
        addr = self.sAddress(axis)
        return self.readFromDev4B(addr)

    def pWrite(self, axis, p):
        addr = self.pAddress(axis)
        self.writeFloat64(addr, p)

    def iWrite(self, axis, i):
        addr = self.iAddress(axis)
        self.writeFloat64(addr, i)

    def dWrite(self, axis, d):
        addr = self.dAddress(axis)
        self.writeFloat64(addr, d)

    def pidWrite(self, pid, axis):
        #self.curPID = ((pid[0],pid[1],pid[2]), self.curPID[1]) if axis == 1 else (self.curPID[0], (pid[0],pid[1],pid[2]))
        self.pWrite(axis, pid[0])
        self.iWrite(axis, pid[1])
        self.dWrite(axis, pid[2])

    def sWrite(self, axis, state):
        #writes servo states: 0 for off, 1 for on
        if state != 0 and state != 1:
            raise("invalid state requested. valid states are 0 for open and 1 for closed.")
        addr = self.sAddress(axis)
        self.writeToDev4B(addr, state)
        time.sleep(0.1)

    def setZero(self, axis):
        #sets current position to zero
        writeTX = 10**(axis-1)
        writeTX = str(writeTX).zfill(32)
        self.writeToDev4B(self.zeroPosAddr, int(writeTX, 2))

    def resetInterferometer(self):
        # turn servo off, set current position to zero, then turn servo back on and go back to previous position
        pos1, pos2 = self.dsrRead(1), self.dsrRead(2)
        self.moveTo(1,0) # set axis 1 position to zero
        self.moveTo(2,0) # set axis 2 position to zero
        self.sWrite(1, 0) # turn servo off on axis 1
        self.sWrite(2, 0) # turn servo off on axis 2
        time.sleep(2) # let system relax for 2 seconds
        offset1 = self.dsrRead(1) # this is the offset due to resetting interferometer
        offset2 = self.dsrRead(2)
        self.setZero(1) # redefine current position as zero
        self.setZero(2)
        self.sWrite(1, 1) # turn servo back on
        self.sWrite(2, 1)
        time.sleep(0.2)
        self.moveTo(1, pos1 - offset1)
        self.moveTo(2, pos2 - offset2)

    def disToPID(self, axis, distance):
        if axis == 1:
            if 0 <= distance < 300:
                pid = (-.1, 450, 0)
            elif 300 <= distance < 5e3:
                pid = (-.2, 240, 0)
            elif 5e3 <= distance < 20e3:
                pid = (-.27, 140, 0)
            elif 20e3 <= distance < 30e3:
                pid = (0, 250, 0)
            elif 30e3 <= distance < 60e3:
                pid = (0, 170, 0)
            elif 60e3 <= distance < 70e3:
                pid = (0, 130, 0)
            elif 70e3 <= distance < 80e3:
                pid = (0, 115, 0)
            elif 80e3 <= distance < 95e3:
                pid = (0, 100, 0)
            elif 95e3 <= distance:
                pid = (-0.13, 67, 0)
        elif axis == 2:
            if 0 <= distance < 500:
                pid = (0, 240, 0)
            elif 500 <= distance < 5e3:
                pid = (0, 210, 0)
            elif 5e3 <= distance < 10e3:
                pid = (0, 200, 0)
            elif 5e3 <= distance < 30e3:
                pid = (0, 180, 0)
            elif 30e3 <= distance < 60e3:
                pid = (0, 120, 0)
            elif 60e3 <= distance < 70e3:
                pid = (0, 100, 0)
            elif 70e3 <= distance < 80e3:
                pid = (0, 87, 0)
            elif 80e3 <= distance < 90e3:
                pid = (0, 77, 0)
            elif 90e3 <= distance:
                pid = (0, 67, 0)
        else:
            raise('invalid axis:' + str(axis))
        return pid

    def rasterScan(self, center = (0,0), fastAxis = 'x', pixelSize = 0.1, pixelCount = (11,1), pixelDwellTime = 0.01, \
        lineDwellTime = 0.01, pulseOffsetTime = 0.01, frameDwellTime = 0.01):
        """
            :param center: (x,y) center position in microns
            :type center: float tuple
            :param fastAxis: axis which changes most frequently, either 1 or 2
            :type fastAsix: int
            :param pixelSize: size of each step in microns
            :type pixelSize: float
            :param pixelCount: number of positions in each line
            :type pixelCount: int
            :param pixelDwellTime: dwell time per pixel in seconds
            :type pixelDwellTime: float
            :param lineDwellTime: dwell time before each line
            :type lineDwellTime: float
            :param pulseOffsetTime: delay before pixel pulse
            :type pulseOffsetTime: float
            :param frameDwellTime: dwell time before each frame
            :type frameDwellTime: float
            :return: None

            Uses LC400 raster scan interface which assumes three dimensional scans (pixel/line/frame).
            For 2D scanning with pystxmcontrol, frame values are ignored.  The raster scan function on the
            nPoint controller always begins from and returns to the center of the line.
        """

        #first, move to center position
        #moveTo is a high level function that does the conversion of microns to encoder counts
        #center is in microns
        self.moveTo(1,center[0])
        self.moveTo(2,center[1])

        #set rising edge polarity on TTL output for both axes
        #writeToDev4B writes 32bit integers to the device at the given address
        self.writeToDev4B(self.axis1address+0x114, 0)
        self.writeToDev4B(self.axis2address+0x114, 0)

        #select fast/slow axes and turn on raster pixel pulses for that axis
        if fastAxis == 'x':
            fastAxis = 1
            slowAxis = 2
            self.writeToDev4B(self.axis1address+0xF4, 6) #PIN6 pixel pulse ON for fast axis
        else:
            fastAxis = 2
            slowAxis = 1
            self.writeToDev4B(self.axis2address+0xF4, 6)
        #write fast and slow axes
        self.writeToDev4B(0x11830448, fastAxis)
        self.writeToDev4B(0x11830464, slowAxis)

        #write pixel sizes to device, square pixels only for now
        self.writeToDev4B(0x1183044C, int(self.nmToSteps(pixelSize * 1000.))) #pixel step size, microns converted to encoder steps
        self.writeToDev4B(0x11830468, int(self.nmToSteps(pixelSize * 1000.))) #line step size, microns converted to encoder steps

        #write pixel/line/frame counts
        self.writeToDev4B(0x11830450, pixelCount[0]-1) #pixel count
        self.writeToDev4B(0x1183046C, pixelCount[1]-1) #line count
        self.writeToDev4B(0x11830488, 0)  #frame count, always 0 for our case

        #write pixel/line/frame/pulse dwell times
        #pixel dwell time will be the same as the detector dwell time
        #line dwell time is just for stabilization after a big move, hopefully small
        #pulse dwell time is the delay after move before the pixel pulse is sent to the detector, hopefully small
        self.writeToDev4B(0x11830454, int(self.timeToCounts(pixelDwellTime)))
        self.writeToDev4B(0x11830470, int(self.timeToCounts(lineDwellTime)))
        self.writeToDev4B(0x1183048C, int(self.timeToCounts(frameDwellTime)))
        self.writeToDev4B(0x11830458, int(self.timeToCounts(pulseOffsetTime)))

        #start the scan
        #1 is for steps, 2 for waveform, 3 for TTL control.  Only 1 is implemented here
        self.writeToDev4B(0x1182906C, 1)

        #check state while moving
        moving = True
        while moving:
            moving = bool(self.readFromDev4B(0x1182906C))

        #Turn OFF pixel pulses
        self.writeToDev4B(self.axis1address+0xF4, 0) #PIN6 pixel pulse OFF
        self.writeToDev4B(self.axis2address+0xF4, 0) #PIN6 pixel pulse OFF

    def stopRasterScan(self):
        self.writeToDev4B(0x11829070, 1)
        
    def setPositionTrigger(self, pos = 0, axis = 1, mode = 'off'):
        if mode == 'off':
            trigger_position = int(round(float(self.nmToSteps(0)))) #set to 0
            trigger_position = int(self.signedIntToHex(trigger_position),16)
            self.writeToDev4B(self.getAddress(axis = axis)+0xC64, trigger_position) #write position offset
            self.writeToDev4B(self.axis1address+0xF4, 0) #PIN6 position pulse OFF
            self.writeToDev4B(self.axis2address+0xF4, 0) #PIN6 position pulse OFF
            self.writeToDev4B(self.getAddress(axis = axis)+0xC6C, 0) #write 0 after changing parameters
        elif mode == 'on':
            self.writeToDev4B(self.getAddress(axis = axis)+0x114, 0) #set polarity to rising edge on pin 6
            #self.writeToDev4B(self.axis2address+0x114, 0)
            self.writeToDev4B(self.getAddress(axis = axis)+0xF4, 10) #set for position pulse
            trigger_position = int(round(float(self.nmToSteps(-1000. * pos)))) #negative, not sure why???
            trigger_position = int(self.signedIntToHex(trigger_position),16)
            self.writeToDev4B(self.getAddress(axis = axis)+0xC64, trigger_position) #write position offset
            self.writeToDev4B(self.getAddress(axis = axis)+0xC6C, 0) #write 0 after changing parameters

    def moveTo2(self,axis,pos):
        stop_pos = [0,0]
        start_pos = [0,0]
        stop_pos[axis-1] = pos
        start_pos[axis-1] = self.getPos(axis)
        velocity = 1.0
        count = 1
        dwell = 0.01 #(stop_pos[axis-1] - start_pos[axis-1])/velocity
        self.setup_trajectory(axis,start_pos,stop_pos,dwell,count,pad=[0,0])
        self.acquire_xy(axes=[axis])
            
    def setup_trajectory(self,trigger_axis, start_position, stop_position, \
        trajectory_pixel_dwell, trajectory_pixel_count, mode=None, pad=None, **kwargs):
        """
        This function is required by derivedPiezo.py in order to execute a linear trajectory (flyscan line).  It
        sets up the trajectory parameters which are later written to the device by acquire_xy.
        :param trigger_axis: axis to trigger on
        :type trigger_axis: int
        :param start: start position (x,y)
        :type start: tuple
        :param stop: stop position (x,y)
        :type stop: tuple
        :param trajectory_pixel_dwell: dwell time per pixel
        :type trajectory_pixel_dwell: float
        :param trajectory_pixel_count: number of pixels in the trajectory
        :type trajectory_pixel_count: int
        :param mode: mode to run the trajectory in
        :type mode: str
        :return: None
        """
        #calculate requested positions so they can be returned by acquire_xy.  Must remove the acceleration distance.
        x0,y0 = start_position
        x1,y1 = stop_position
        start_x = x0 + pad[0]
        stop_x = x1 - pad[0]
        start_y = y0 + pad[1]
        stop_y = y1 - pad[1]
        self.positions = np.linspace(start_x, stop_x, trajectory_pixel_count), np.linspace(start_y, stop_y, trajectory_pixel_count)
        xvelocity = (stop_x - start_x) / (trajectory_pixel_count * trajectory_pixel_dwell)
        yvelocity = (stop_y - start_y) / (trajectory_pixel_count * trajectory_pixel_dwell)
        velocitySum = np.sqrt(xvelocity**2 + yvelocity**2)

        distance = np.sqrt((x1-x0)**2 + (y1-y0)**2)
        start_x = self.nmToSteps(1000.*start_position[0])
        start_x = int(self.signedIntToHex(start_x),16)
        start_y = self.nmToSteps(1000.*start_position[1])
        start_y = int(self.signedIntToHex(start_y),16)
        stop_x = self.nmToSteps(1000.*stop_position[0])
        stop_x = int(self.signedIntToHex(stop_x),16)
        stop_y = self.nmToSteps(1000.*stop_position[1])
        stop_y = int(self.signedIntToHex(stop_y),16)
        delay = distance / velocitySum / 1000.+0.005
        self.trajectory = {}
        self.trajectory["trigger_axis"] = trigger_axis
        self.trajectory["start"] = start_position
        self.trajectory["stop"] = stop_position
        self.trajectory["trajectory_pixel_dwell"] = trajectory_pixel_dwell
        self.trajectory["trajectory_pixel_count"] = trajectory_pixel_count
        self.trajectory["mode"] = mode
        self.trajectory["delay"] = delay
        self.trajectory["start_x"] = start_x
        self.trajectory["start_y"] = start_y
        self.trajectory["stop_x"] = stop_x
        self.trajectory["stop_y"] = stop_y
        self.trajectory["velocitySum"] = velocitySum
        self.trajectory["distance"] = distance
        self.npositions = trajectory_pixel_count

    def acquire_xy(self,axes=[1,],**kwargs):
        #this trajectory will be along the X axis at a given y_center position
        #center/range are in microns, velocity is microns/millisecond and dwell is millisecond
        for axis in axes:
            self.writeToDev4B(self.getAxisAddress(axis)+0xB10, 1)  # enable trajectory generation on axis 1
        self.writeToDev4B(0x1182A000, 2) #Number of coordinates in trajectory, just doing a line here
        self.writeToDev4B(0x1182A004, 1) #Number of trajectory iterations

        ##write the positions, velocity, acceleration, jerk and dwell for the two coordinates
        self.writeToDev4B(0x1182A6A0, self.trajectory["start_x"])
        self.writeNext(self.trajectory["start_y"]) #not strictly needed for 1D scan line

        #the next 4 values are blank
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))

        #now for the velocity limit
        self.writeFloat32(self.vLimitToCountLoop(self.trajectory["velocitySum"]))

        #Acceleration limit
        self.writeFloat32(self.vLimitToCountLoop(self.trajectory["velocitySum"]))

        #Jerk limit
        self.writeFloat32(self.vLimitToCountLoop(self.trajectory["velocitySum"]))

        #Dwell at start
        self.writeNext(self.timeToCounts(0.0))

        ##Repeat for second coordinate
        self.writeNext(self.trajectory["stop_x"])
        self.writeNext(self.trajectory["stop_y"])

        #the next 4 values are blank
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))

        #now for the velocity limit
        self.writeFloat32(self.vLimitToCountLoop(self.trajectory["velocitySum"]))

        #Acceleration limit
        self.writeFloat32(self.vLimitToCountLoop(self.trajectory["velocitySum"]))

        #Jerk limit
        self.writeFloat32(self.vLimitToCountLoop(self.trajectory["velocitySum"]))

        #Dwell at start
        self.writeNext(self.timeToCounts(0.0))

        #Start the trajectory
        self.writeToDev4B(0x11829048,1)

        #just wait the expected time (plus 10 ms) and then exit.  Assumes accurate velocity
        time.sleep(1. * self.trajectory["distance"] / self.trajectory["velocitySum"] / 1000.+0.01)

        #Stop the trajectory, just to be certain?
        self.writeToDev4B(0x1182904C,1)

        #disable trajectories on both axes
        self.writeToDev4B(self.axis1address+0xB10, 0)  # disable trajectory generation on axis 1
        self.writeToDev4B(self.axis2address+0xB10, 0)  # disable trajectory generation on axis 2
        return self.positions

    def linear_trajectory(self, start_position, stop_position, trigger_axis = 1, trigger_position = None, \
                            velocity = (0.2,0.2), dwell = 10.):

        """
        start/stop = (x,y) tuples (microns)
        trigger_position = float (microns)
        trigger_axis = 1 (x) or 2 (y)
        velocity = float (microns/millisecond same as mm/s)
        dwell = float (milliseconds), dwell at start of trajectory
        """
        x0,y0 = start_position
        x1,y1 = stop_position
        distance = np.sqrt((x1-x0)**2 + (y1-y0)**2)
        velocitySum = np.sqrt(velocity[0]**2+velocity[1]**2)
        
        #self.moveTo(axis = 1, pos = x0, checkStatus = True)
        #self.moveTo(axis = 2, pos = y0, checkStatus = True)
        #time.sleep((distance/2. + 20.)/1000.)

        #this trajectory will be along the X axis at a given y_center position
        #center/range are in microns, velocity is microns/millisecond and dwell is millisecond
        self.writeToDev4B(self.axis1address+0xB10, 1)  # 1 enable trajectory generation on axis 1
        self.writeToDev4B(self.axis2address + 0xB10, 1)  # 1 enable trajectory generation on axis 2
        self.writeToDev4B(0x1182A000, 2) #Number of coordinates in trajectory, just doing a line here
        self.writeToDev4B(0x1182A004, 1) #Number of trajectory iterations
        
        #First determine start/stop points for the line.  The line will exceed the measurement range by 5% on each side
        #The trigger on position point will start the measurement
        #start_position = x_center - r / 2. - pad * r
        start_x = self.nmToSteps(1000.*start_position[0])
        start_x = int(self.signedIntToHex(start_x),16)
        start_y = self.nmToSteps(1000.*start_position[1])
        start_y = int(self.signedIntToHex(start_y),16)
        stop_x = self.nmToSteps(1000.*stop_position[0])
        stop_x = int(self.signedIntToHex(stop_x),16)
        stop_y = self.nmToSteps(1000.*stop_position[1])
        stop_y = int(self.signedIntToHex(stop_y),16)

        ##write the positions, velocity, acceleration, jerk and dwell for the two coordinates
        self.writeToDev4B(0x1182A6A0, start_x)
        self.writeNext(start_y)
        #the next 4 values are blank
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        #now for the velocity limit
        self.writeFloat32(self.vLimitToCountLoop(velocitySum))
        #Acceleration limit
        self.writeFloat32(self.vLimitToCountLoop(velocitySum))
        #Jerk limit
        self.writeFloat32(self.vLimitToCountLoop(velocitySum))
        #Dwell at start
        self.writeNext(self.timeToCounts(0.0))#dwell/1000.))

        ##Repeat for second coordinate
        self.writeNext(stop_x)
        self.writeNext(stop_y)
        #the next 4 values are blank
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        self.writeNext(self.nmToSteps(0.))
        #now for the velocity limit
        self.writeFloat32(self.vLimitToCountLoop(velocitySum))
        #Acceleration limit
        self.writeFloat32(self.vLimitToCountLoop(velocitySum))
        #Jerk limit
        self.writeFloat32(self.vLimitToCountLoop(velocitySum))
        #Dwell at start
        self.writeNext(self.timeToCounts(0.0))#dwell/1000.))

        #enable position trigger pulse
        #if trigger_position is not None:
        #    self.setPositionTrigger(trigger_position, trigger_axis, mode = 'on')

        #Start the trajectory
        self.writeToDev4B(0x11829048,1)

        #Check for completion of the trajectory
        #moving = True
        #while moving:
        #    #The controller is taking an additional ~40ms to return 0 after the trajectory is actually complete
        #    moving = bool(self.readFromDev4B(0x11829048))

        #just wait the expected time (plus 10 ms) and then exit.  Assumes accurate velocity
        time.sleep(distance / velocitySum / 1000.+0.005)

        #Stop the trajectory, just to be certain?
        self.writeToDev4B(0x1182904C,1)
        
        #Turn OFF position trigger pulses
        #self.setPositionTrigger() #turns OFF by default

    def compile_FlyPos(self):
        # some parameters to generate the Flyscan positions, could be obtained from the Flyscan dictionary
        xstart = -1
        xend = 1
        ystart = -1
        yend = 1
        ystep = 10
        # ------------------------------------------------------------
        # generate the position, the position unit now is um
        ypos = np.linspace(ystart, yend, ystep)
        ypos = ypos.reshape((ystep, 1))

        xstartPos, xendPos = np.zeros((ystep, 1)), np.zeros((ystep, 1))
        xstartPos[:] = xstart
        xendPos[:] = xend

        liftPos = list(np.hstack((xstartPos, ypos)))
        rightPos = list(np.hstack((xendPos, ypos)))

        # create the scan pattern(the sequence of position move), this time just realize the raster_like Flyscan
        rasterFlyPos = []
        for i in range(len(ypos)):
            rasterFlyPos.append((liftPos[i], rightPos[i]))
        rasterFlyPos = np.reshape(rasterFlyPos, (2 * len(ypos), 2))

        # change pos(unit:um)to steps and transfer the step to signedInt number for writing to device
        rasterFlyPos = self.nmToSteps(rasterFlyPos * 1000)  # need to transfer um to nm first
        rasterFlyPos = list(rasterFlyPos.flatten())
        rasterFlyPosList = []
        for pos in rasterFlyPos:
            pos = int(round(float(pos)))
            pos = int(self.signedIntToHex(pos), 16)  # this is for negetive number
            rasterFlyPosList.append(pos)
        rasterFlyPos = np.reshape(rasterFlyPosList, (2 * len(ypos), 2))  # an array for furthur np.hstack

        # create the FlyPosList set; The set farmat is[ch1(int32),ch2(int32),ch3, ch4, ch5, ch6, Velocity Limit(float32),..,..,dwell time(int32)]
        # ch3_ch6 values are 0, this time just ch1/ch2 were used
        ch3_ch6 = np.zeros((len(rasterFlyPos), 4))

        # create the velocity limit
        velocity = 0.2  # um/ms
        VL = np.zeros((len(rasterFlyPos), 3))
        VL[:, 0] = self.vLimitToCountLoop(velocity)

        # create dwell time
        dwell = np.ones((len(rasterFlyPos), 1))
        dwell = self.timeToCounts(dwell)

        # horizontal stack these array to creat the set
        FlyPosList = np.hstack((rasterFlyPos, ch3_ch6, VL, dwell))
        return list(FlyPosList)

    def writeFlyPos(self, posList):
        # two steps to write the FlyPosList number to Device
        self.writeToDev4B(self.trajGenEnabelAddr, 1)  # 1 means enable generate the trajectory
        self.writeToDev4B(self.trajCoorNumAddr, len(posList))  # how many coordinate lines
        self.writeToDev4B(self.trajIterNumAddr, 1)
        self.writeToDev4B(self.trajGenParamAddr, int(posList[0][0]))
        for i in np.arange(1, 10):  # write the first coordinate line
            if i <= 5:
                self.writeNext(int(posList[0][i]))
            elif i > 5 and i < 9:
                self.writeFloat32(posList[0][i])
            elif i == 9:
                self.writeNext(int(posList[0][i]))

        for line in posList[1:]:  # write the rest of lines
            for i in range(10):
                if i <= 5:
                    self.writeNext(int(line[i]))
                elif i > 5 and i < 9:
                    self.writeFloat32(line[i])
                elif i == 9:
                    self.writeNext(int(line[i]))

    def startFlyscan(self):
        posList = self.compile_FlyPos()
        # move to the first coordinate first, please remmenber that the pos is areadly transfered to steps(counts), so we can't just ust self.moveTo function
        axis1Start = int(posList[0][0])
        axis2Start = int(posList[0][1])
        self.writeToDev4B(self.posAddress(1), axis1Start)
        self.writeToDev4B(self.posAddress(2), axis2Start)
        self.writeFlyPos(posList)
        self.writeToDev4B(self.trajStartAddr, 1)

    def compile_spiral(self):
        xCenter, yCenter = 0, 0  # unit um
        xRange, yRange = 2, 2  # unit um
        xSteps = 10
        sRevSpeed = 0.5  # similar to the velocity
        dtime = 1  # unit s

        xRadius = self.nmToSteps((xRange / 2) * 1000)
        yRadius = self.nmToSteps((yRange / 2) * 1000)
        spiralLineSpace = self.nmToSteps((xRange / (xSteps - 1)) * 1000)
        lCyclePerRev = self.speedToLoopCycle(sRevSpeed)
        dwelltime = self.timeToCounts(dtime)
        return [xCenter, yCenter, xRadius, yRadius, spiralLineSpace, lCyclePerRev, dwelltime]

    def writeSpiralscan(self, spiralParam):
        self.writeToDev4B(self.spiralAxis1Addr, 1)  # 1 means axis1
        self.writeToDev4B(self.spiralAxis2Addr, 2)  # 2 means axis2
        self.writeToDev4B(self.spiralRadius1Addr, int(spiralParam[2]))
        self.writeToDev4B(self.spiralRadius2Addr, int(spiralParam[3]))
        self.writeToDev4B(self.spiralLineSpaAddr, int(spiralParam[4]))
        self.writeToDev4B(self.spiralRevAddr, int(spiralParam[5]))
        self.writeToDev4B(self.spiralDwellAddr, int(spiralParam[6]))
        self.writeToDev4B(self.spiralFrameAddr, 1)  # 1means just 1 frame

    def stratSpiral(self):
        spiralParam = self.compile_spiral()
        self.moveTo(1, spiralParam[0])
        self.moveTo(2, spiralParam[1])
        self.writeSpiralscan(spiralParam)
        self.writeToDev4B(self.spiralStartAddr, 2)  # 2 means scanning from center to edge



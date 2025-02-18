# -*- coding: utf-8 -*-
"""
Created on Thu Jun 29 14:07:06 2017
@author: Kasra Nowrouzi

@author: Jiangtao Zhao
Added DAQ function on Wed Nov 14 20:50:05 2018
"""

from pylibftdi import Device, Driver
#from uldaq import get_daq_device_inventory, DaqDevice, InterfaceType, TmrIdleState, PulseOutOption, TmrStatus
import numpy as np
import time
import struct

class nPoint:

    def __init__(self, ftdi_device_id = '7340012A'):
        # refer to page 29 of NPoint manual for formatting info
        self.devID = ftdi_device_id
        self.dev = self.connect() # NOTE: SUDO PRIVILEGES NEEDED TO CONNECT

        #connect the daq_device
        self.daq_device = self.DaqConnect()
	#call the timer function to generate the pulse, in order to tigger ccd
        self.tmr_device = self.daq_device.get_tmr_device()

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
        self.sensorGain = 10.486 # 1nm = sensorGain*[quadrature counts]

        #read in the current pid parameters
        self.curPID = (self.pidRead(1), self.pidRead(2))

        #reset the interferometer, and start from position zero.
        self.curPos = (self.posRead(1), self.posRead(2))
        self.resetInterferometer()
        self.posWrite(1,0)
        self.posWrite(2,0)

    def connect(self):
        return Device(device_id = self.devID)

    # def DaqConnect(self):#connect DAQ devices
    #     try:
    #         devices = get_daq_device_inventory(InterfaceType.USB)
    #         number_of_devices = len(devices)
    #         daq_device = DaqDevice(devices[0])
    #         daq_device.connect()
    #         for i in range(number_of_devices):
    #             print(devices[i].product_name,'is connected.')
	#     return daq_device
    #     except:
    #         print("No DAQ device")

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

    def hexToSignedInt(self, h):
        #converts hex numbers to signed int:
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

    def hexToFloat64(self, h):
        return struct.unpack('<d', struct.pack('<Q', int(h, 16)))[0]

    def readFromDev4B(self, addr): # to read 32bit values, e.g. position or servo state
        # format: [readCom] [address] [0x55] for a total of 6 bytes
        readTX = 0x55 * 16**10 + addr * 16**2 + self.readCom
        readTX = bytearray(hex(readTX)[2:].decode('hex')) # Get the bytes in decreasing significance (need to be reversed)
        #readTX = bytearray('\x55' + hex(addr)[2:].decode('hex') + '\xa0')
        readTX.reverse()
        dataw = self.dev.write(readTX)
        if dataw != 6:
            print "dataw =", dataw
            raise("reading value: writing to \"read address\" on device failed")
        datar = self.dev.read(10)
        while datar == '':
            datar = self.dev.read(10)
        datar = bytearray(datar)
        datar.reverse()
        val = str(datar)[1:5]
        val = '0x' + val.encode('hex')
        #return int(val,16)
        return self.hexToSignedInt(val)

    def readArray(self, numBytes, addr): # e.g. to read PID parameters as 64bit float, use numBytes=2
        # format: [readArrayCom] [address] [numBytes] [0x55] for a total of 10 bytes
        #t0 = time.time()
        readTX = 0x55 * 16**18 + numBytes * 16**10 + addr * 16**2 + self.readArrayCom
        #t1 = time.time()
        readTX = bytearray(hex(readTX)[2:-1].decode('hex')) # Get the bytes in decreasing significance (need to be reversed)
        #t2 = time.time()
        readTX.reverse()
        #t3 = time.time()
        dataw = self.dev.write(readTX)
        #t4 = time.time()
        if dataw != 10:
            print "dataw =", dataw
            raise("reading value: writing to \"read address\" on device failed")
        #t5 = time.time()
        datar = self.dev.read(6 + 4*numBytes)
        while datar == '':
            datar = self.dev.read(6 + 4*numBytes)
        datar = bytearray(datar)
        #t6 = time.time()
        datar.reverse()
        #t7 = time.time()
        val = str(datar)[1:1+4*numBytes]
        #t8 = time.time()
        retVal = '0x' + val.encode('hex')
        #t9 = time.time()
        #print "t1:",t1-t0,"t2:",t2-t1,'t3:',t3-t2,'t4:',t4-t3,'t5:',t5-t4,'t6:',t6-t5,'t7:',t7-t6,'t8:',t8-t7,'t9:',t9-t8,'total:',t9-t0
        return retVal #'0x' + val.encode('hex')

    def writeToDev4B(self, addr, val): # to write 32bit values, e.g. position or servo state
        # format: [writeCom] [addr] [val/data] [0x55] for a total of 10 bytes: [addr] and [val] are 4 bytes each.
        writeTX = 0x55 * 16**18 + val * 16**10 + addr * 16**2 + self.writeCom
        writeTX = bytearray(hex(writeTX)[2:-1].decode('hex')) # Get the bytes in decreasing significance (need to be reversed)
        #writeTX = bytearray('\x55' + val[2:].decode('hex') + hex(addr)[2:].decode('hex') + '\xa0')
        writeTX.reverse()
        dataw = self.dev.write(writeTX)
        if dataw != 10:
            print "dataw =", dataw
            raise("writing value: writing to \"write address\" on device failed")

    def writeNext(self, val): # writes a single 32bit value at the current memory address.
        writeTX = 0x55 * 16**10 + val * 16**2 + self.writeNextCom
        writeTX = bytearray(hex(writeTX)[2:].decode('hex'))
        writeTX.reverse()
        dataw = self.dev.write(writeTX)
        if dataw != 6:
            print "dataw =", dataw
            raise("writing value: writing to \"write address\" on device failed")

    def writeFloat64(self, addr, val):
        val = self.float64ToHex(float(val))
        val = val[2:-1] if val[-1] == 'L' else val[2:]
        val = val.zfill(16)
        val = bytearray(val.decode('hex'))
        self.writeToDev4B(addr, int(str(val)[4:8].encode('hex'),16))
        self.writeNext(int(str(val)[:4].encode('hex'),16))

    def posRead(self, axis):
        readAddr = self.posAddress(axis)
        posInSteps = self.readFromDev4B(readAddr)
        return self.stepsToNM(posInSteps)

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

    def posWrite(self, axis, pos):
        #t0 = time.time()
        dist = np.abs(self.curPos[axis-1] - pos)
        #t1 = time.time()
        pid = self.disToPID(axis, dist)
        #t2 = time.time()
        if pid != self.curPID[axis-1]:
            print "optimal pid for this step for axis",axis,":", pid, "current pid:", self.curPID[axis-1]
            print "writing optimal pid to axis",axis,"..."
            self.pidWrite(axis, pid)
        #t3 = time.time()
        self.curPos = (self.curPos[0], pos) if axis == 2 else (pos, self.curPos[1])
        #t4 = time.time()
        #print "t1:",t1-t0,"t2:",t2-t1,"t3:",t3-t2,"t4:",t4-t3,"total:",t4-t0
        writeAddr = self.posAddress(axis)
        pos = int(round(self.nmToSteps(pos)))
        pos = int(self.signedIntToHex(pos),16)
        self.writeToDev4B(writeAddr, pos)

    def stepsToNM(self, steps):
        return steps / self.sensorGain

    def nmToSteps(self, nm):
        return nm * self.sensorGain

    def scan(self, center, xr, yr, stepsizenmX, stepsizenmY,  exposure_time, mode='raster'):
        if mode == 'raster':
            pointsX, pointsY = self.rasterScanPoints(center, xr, yr, stepsizenmX, stepsizenmY)
        elif mode == 'serpentine':
            pointsX, pointsY = self.serpScanPoints(center, xr, yr, stepsizenmX, stepsizenmY)
        elif mode == 'circular':
            #pointsX, pointsY = circScanPoints(center, stepSize, radius)
            raise('circular scans not yet implemented')
        else:
            raise("unknown scan mode")

	ccd_deadtime = 1*1e-3 #get the right number
	total_time = exposure_time + ccd_deadtime

	timer_number = 0
	frequency = 1. / total_time
	duty_cycle = float(exposure_time) / total_time
	pusle_count = 1
	initial_delay = 0.0
	idle_state = TmrIdleState.LOW
	options = PulseOutOption.DEFAULT


        for x, y in zip(pointsX, pointsY):
            #print x, y
            self.posWrite(1, x)
            #while(round(posRead(dev,1)) != round(x)):
            #    print x, posRead(dev,1)
            self.posWrite(2, y)
            #while(round(posRead(dev,2)) != round(y)):
            #    print y, posRead(dev,2)


            #generate the pulse
	    #check the pulse_out_status
	    status = self.tmr_device.get_pulse_out_status(0) # function: get_pulse_out_status(timer_number)
	    if status == TmrStatus.RUNNING:
		a,b,c = self.tmr_device.pulse_out_start(timer_number,frequency,duty_cycle,pusle_count,initial_delay,idle_state, options)
	    else:
		raise("tmr_device status is TmrStatus.IDLE, Please check the tmr_device status")
            time.sleep(total_time) ## pulse_out_start() function also need this time to generate the equivalent pulse; real total_time include expouse_time + ccddeadtime + pos_moving time;

	self.tmr_device.pulse_out_stop(0)
    	print a,b,c , len(pointsX)

    def rasterScanPoints(self, center, xr, yr, stepsizenmX, stepsizenmY):
        nx, ny = int(xr/stepsizenmX), int(yr/stepsizenmY)
        pointsX, pointsY = np.zeros((nx*ny,1)), np.zeros((ny*nx,1))
        counter = 0
        for x in np.linspace(center[0]-xr/2, center[0]+xr/2, nx):
            for y in np.linspace(center[1]-yr/2, center[1]+yr/2, ny):
                pointsX[counter], pointsY[counter] = x, y
                counter += 1
        return pointsX, pointsY


    def serpScanPoints(self, center, xr, yr, stepsizenmX, stepsizenmY):
        nx, ny = int(xr/stepsizenmX), int(yr/stepsizenmY)
        pointsX, pointsY = np.zeros((nx*ny,1)), np.zeros((ny*nx,1))
        counter = 0
        direction = 0
        for x in np.linspace(center[0]-xr/2, center[0]+xr/2, nx):
            for y in np.linspace(center[1]-yr/2, center[1]+yr/2, ny) if direction%2 == 0 else np.linspace(center[1]+yr/2, center[1]-yr/2, ny):
                pointsX[counter], pointsY[counter] = x, y
                counter += 1
            direction += 1
        return pointsX, pointsY

    def circScanPoints(self, center, stepSize, radius):
        numCircs = int(round(radius/stepSize)) # need this many circles around center
        pointsX, pointsY = np.array([center[0]]), np.array([center[1]])
        for circNum in np.arange(numCircs)+1:
            pointsXtemp, pointsYtemp = self.circPoints(center, stepSize, circNum * stepSize)
            pointsX, pointsY = np.append(pointsX, pointsXtemp), np.append(pointsY, pointsYtemp)
        return pointsX, pointsY

    def circPoints(self, center, stepSize, radius):
        #points on a single circle
        pass

    ############### added by Jiangtao ########################################
    def spiralScan(self, stepsize, r, dt, maxpoints = None):
        # r means radius
        alpha = np.sqrt(4*np.pi)
        beta = stepsize / (2*np.pi)
        if maxpoints is None:
            maxpoints = 100000
        pointsX = []
        pointsY = []
        for k in xrange(maxpoints):
            theta = alpha * np.sqrt(k)
            rr = beta * theta
            if rr > r: break
            pointsX.append(rr*np.sin(theta))
            pointsY.append(rr*np.cos(theta))
        #return pointsX, pointsY
        for x, y in zip(pointsX, pointsY):
            self.posWrite(1, x)
            #while(round(posRead(dev,1)) != round(x)):
            #    print x, posRead(dev,1)
            self.posWrite(2, y)
            #while(round(posRead(dev,2)) != round(y)):
            #    print y, posRead(dev,2)
            time.sleep(dt*1e-3)

    def roundScan(self,stepsize,nr,nth, dt, eye = True):
        # nr means how many shells, nth means how many points in the first shell
        if eye:
            pointsX, pointsY = [0.], [0.]
        else:
            pointsX = []
            pointsY = []
        for i in range(1,nr+2):
            rr = i*stepsize # rr: redius in each round
            dth = 2*np.pi / (i*nth)
            pointsX.extend([rr*np.sin(ith*dth) for ith in range(nth*i)])
            pointsY.extend([rr*np.cos(ith*dth) for ith in range(nth*i)])
        #return pointsX, pointsY
        for x, y in zip(pointsX, pointsY):
            self.posWrite(1, x)
            #while(round(posRead(dev,1)) != round(x)):
            #    print x, posRead(dev,1)
            self.posWrite(2, y)
            #while(round(posRead(dev,2)) != round(y)):
            #    print y, posRead(dev,2)
            time.sleep(dt*1e-3)
     ############### ---------------- ########################################

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

    def pidRead(self, axis):
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

    def pidWrite(self, axis, (p, i, d)):
        self.curPID = ((p,i,d), self.curPID[1]) if axis == 1 else (self.curPID[0], (p,i,d))
        self.pWrite(axis, p)
        self.iWrite(axis, i)
        self.dWrite(axis, d)

    def sWrite(self, axis, state):
        #writes servo states: 0 for off, 1 for on
        if state != 0 and state != 1:
            raise("invalid state requested. valid states are 0 for open and 1 for closed.")
        addr = self.sAddress(axis)
        self.writeToDev4B(addr, state)

    def setZero(self, axis):
        #sets current position to zero
        writeTX = 10**(axis-1)
        writeTX = str(writeTX).zfill(32)
        self.writeToDev4B(self.zeroPosAddr, int(writeTX, 2))

    def resetInterferometer(self):
        # turn servo off, set current position to zero, then turn servo back on and go back to previous position
        pos1, pos2 = self.dsrRead(1), self.dsrRead(2)
        self.posWrite(1,0) # set axis 1 position to zero
        self.posWrite(2,0) # set axis 2 position to zero
        self.sWrite(1, 0) # turn servo off on axis 1
        self.sWrite(2, 0) # turn servo off on axis 2
        time.sleep(1) # let system relax for 2 seconds
        offset1 = self.dsrRead(1) # this is the offset due to resetting interferometer
        offset2 = self.dsrRead(2)
        self.setZero(1) # redefine current position as zero
        self.setZero(2)
        self.sWrite(1, 1) # turn servo back on
        self.sWrite(2, 1)
        time.sleep(0.2)
        self.posWrite(1, pos1 - offset1)
        self.posWrite(2, pos2 - offset2)

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

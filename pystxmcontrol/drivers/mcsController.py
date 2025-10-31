# -*- coding: utf-8 -*-
from pylibftdi import Device, Driver
from pystxmcontrol.controller.hardwareController import hardwareController
from threading import Lock
from time import sleep, time
import smaract.ctl as ctl

class mcsController(hardwareController):

    def __init__(self, address = '192.168.1.200', port = None, simulation = False):

        # the smarAct ctl library does not take the IP address and just looks for all
        # devices on the network.  The port number here is the serial number of the desired
        # device.  CTL returns the full list and then we just search for the serial number.
        
        self.devID = address
        self.isInitialized = False
        self.address = address
        self.port = port
        self.simulation = simulation
        self._timeout = 5
        self.lock = Lock()

    def initialize(self, simulation = False):
        print(ctl.FindDevices().split("\n"))
        self.simulation = simulation
        if not(self.simulation):
            try:
                #these aren't blocking, some time is needed after these calls or this sequence fails
                self._address = [x for x in ctl.FindDevices().split("\n") if str(self.port) in x][0]
                print(f"[MCS2] address: {self._address}")
                self._deviceID = ctl.Open(self._address)
                print(f"[MCS2] deviceID: {self._deviceID}")
                self._move_mode = ctl.MoveMode.CL_ABSOLUTE
                print(f"[MCS2] move_mode: {self._move_mode}")
            except:
                print("[MCS] No controllers available.")

    def setup_axis(self,axis):
        ##This is only for stick-slip motors
        ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.MAX_CL_FREQUENCY, 6000)
        ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.HOLD_TIME, 1000)
        ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_VELOCITY, 10000000000)
        ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_ACCELERATION, 10000000000)

    def set_velocity(self,axis,velocity):
        velocity = int(velocity * 1E9) #convert mm/s to pm/s
        ctl.SetProperty_i64(self._deviceID,axis,ctl.Property.MOVE_VELOCITY,velocity)

    def stop(self,axis):
        ctl.Stop(self._deviceID, axis)

    def move(self,axis,position):
        self.moving = True
        t0 = time()
        ctl.Move(self._deviceID, axis, int(position), 0)
        while self.moving:
            self.getStatus(axis)
            sleep(0.005)
            if (time() - t0) > self._timeout:
                print("[MCS] Timeout exceeded on move. Stopping axis %i." %axis)
                self.stop(axis)
                self.moving=False
                return

    def getPos(self,axis):
        return ctl.GetProperty_i64(self._deviceID, axis, ctl.Property.POSITION)

    def getStatus(self,axis):
        self._status = ctl.GetProperty_i32(self._deviceID, axis, ctl.Property.CHANNEL_STATE)
        self.moving = bool(int(bin(self._status)[-1]))
        return self.moving

    def home(self,axis):
        ctl.SetProperty_i32(self._deviceID, axis, ctl.Property.REFERENCING_OPTIONS, 0)
        # Set velocity to 1mm/s
        ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_VELOCITY, 1000000000)
        # Set acceleration to 10mm/s2.
        ctl.SetProperty_i64(self._deviceID, axis, ctl.Property.MOVE_ACCELERATION, 10000000000)
        # Start referencing sequence
        ctl.Reference(self._deviceID, axis)

    def disconnect(self):
        ctl.Close(self._deviceID)

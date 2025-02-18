from ctypes import cdll, c_int, c_uint, c_double, POINTER, c_void_p, c_ushort
import atexit
from time import sleep, time
import numpy as np
import matplotlib.pyplot as plt

c_double_p = POINTER(c_double * 100)
ND_POINTER_N1 = np.ctypeslib.ndpointer(dtype = np.float64, ndim = 1, flags = 'C')

class mclController():
    def __init__(self, address = '/usr/lib/libmadlib.so.2.0.1', port = None, simulation = False):

        self.address = address
        self.port = port
        self.simulation = simulation

        if not(self.simulation):
            global MADLIB
            MADLIB = cdll.LoadLibrary(address)
            self.oversampling_factor = 3

            #set up functions needed for waveform generation
            #Single position read
            self.mcl_read = MADLIB['MCL_SingleReadN']
            self.mcl_read.restype = c_double
            self.mcl_read.argtypes = [c_uint, c_int]

            #Single position write
            self.mcl_write = MADLIB['MCL_SingleWriteN']
            self.mcl_write.restype = c_int
            self.mcl_write.argtypes = [c_double, c_uint, c_int]

            #Setup and trigger a waveform read
            self.read_waveform = MADLIB['MCL_ReadWaveFormN']
            self.read_waveform.restype = c_int
            self.read_waveform.argtypes = [c_uint, c_uint, c_double, ND_POINTER_N1, c_int]

            #Setup a waveform read
            self.setup_read_waveform = MADLIB['MCL_Setup_ReadWaveFormN']
            self.setup_read_waveform.restype = c_int
            self.setup_read_waveform.argtypes = [c_uint, c_uint, c_double, c_int]

            #Trigger a waveform read
            self.trigger_read_waveform = MADLIB['MCL_Trigger_ReadWaveFormN']
            self.trigger_read_waveform.restype = c_int
            self.trigger_read_waveform.argtypes = [c_uint, c_uint, ND_POINTER_N1, c_int]

            #Setup and trigger a waveform load
            self.load_waveform = MADLIB['MCL_LoadWaveFormN']
            self.load_waveform.restype = c_int
            self.load_waveform.argtypes = [c_uint, c_uint, c_double, ND_POINTER_N1, c_int]

            #Setup a waveform load
            self.setup_load_waveform = MADLIB['MCL_Setup_LoadWaveFormN']
            self.setup_load_waveform.restype = c_int
            self.setup_load_waveform.argtypes = [c_uint, c_uint, c_double, ND_POINTER_N1, c_int]

            #Trigger a waveform load
            self.trigger_load_waveform = MADLIB['MCL_Trigger_LoadWaveFormN']
            self.trigger_load_waveform.restype = c_int
            self.trigger_load_waveform.argtypes = [c_uint, c_uint]

            #Trigger a waveform read and load sychronously, previously setup
            self.trigger_acquisition = MADLIB['MCL_TriggerWaveformAcquisition']
            self.trigger_acquisition.restype = c_int
            self.trigger_acquisition.argtypes = [c_uint, c_uint, ND_POINTER_N1, c_int]

            #Trigger a waveform read and load sychronously, previously setup
            self.bindISSClock = MADLIB['MCL_IssBindClockToAxis']
            self.bindISSClock.restype = c_int
            self.bindISSClock.argtypes = [c_int, c_int, c_int, c_int]

            #Trigger a waveform read and load sychronously, previously setup
            self.setISSClock = MADLIB['MCL_IssSetClock']
            self.setISSClock.restype = c_int
            self.setISSClock.argtypes = [c_int, c_int, c_int]

            #Setup an xy waveform load/read
            self.setup_xy_waveform = MADLIB['MCL_WfmaSetup']
            self.setup_xy_waveform.restype = c_int
            #Docs say to pass null pointer if not using axis. Thus a c_void_p in the z-axis. None is the python equiv.
            #To do different axes, create a new function.
            self.setup_xy_waveform.argtypes = [ND_POINTER_N1, ND_POINTER_N1, c_void_p, c_int, c_double, c_ushort, c_int]

            #Trigger and read an xy waveform
            self.trigger_read_xy_waveform = MADLIB['MCL_WfmaTriggerAndRead']
            self.trigger_read_xy_waveform.restype = c_int
            #Docs say to pass null pointer if not using axis. Thus a c_void_p in the z-axis. None is the python equiv.
            #To do different axes, create a new function.
            self.trigger_read_xy_waveform.argtypes = [ND_POINTER_N1, ND_POINTER_N1, c_void_p, c_int]

            #Trigger an xy waveform
            self.trigger_xy_waveform = MADLIB['MCL_WfmaTrigger']
            self.trigger_xy_waveform.restype = c_int
            self.trigger_xy_waveform.argtypes = [c_int]

            #Read an xy waveform
            self.read_xy_waveform = MADLIB['MCL_WfmaRead']
            self.read_xy_waveform.restype = c_int
            #Docs say to pass null pointer if not using axis. Thus a c_void_p in the z-axis. None is the python equiv.
            #To do different axes, create a new function.
            self.read_xy_waveform.argtypes = [ND_POINTER_N1, ND_POINTER_N1, c_void_p, c_int]

            #Stop an xy waveform
            self.stop_xy_waveform = MADLIB['MCL_WfmaStop']
            self.stop_xy_waveform.restype = c_int
            self.stop_xy_waveform.argtypes = [c_int]
        
    def initialize(self, simulation = False):
        self.simulation = simulation
        self.isInitialized = True
        if not(self.simulation):
            self.handle = self.start()
            atexit.register(self.close)
	
    def getStatus(self, axis):
        return True
	
    def getAxis(self, axis):
        #Cables are likely switched
        if axis == 'y':
	        return 1
        if axis == 'x':
	        return 2
        else:
	        return -1

    def start(self):
        """
        Requests control of a single Mad City Labs Nano-Drive.

        Return Value:
	        Returns a valid handle or returns 0 to indicate failure.
        """
        mcl_init_handle = MADLIB['MCL_InitHandle']
        mcl_init_handle.restype = c_int
        handle = mcl_init_handle()
        if (handle==0):
	        print("MCL init error")
	        return -1
        else:	
	        print("---------------------------------------")
	        print("Mad City Labs Nanodrive Device Info...")
	        print("---------------------------------------")
	        print(MADLIB['MCL_PrintDeviceInfo'](c_int(handle)))
	        print("---------------------------------------\n")
        return 	handle

    def read(self,axis):
        """
        Read the current position of the specified axis.

        Parameters:
	        axis [IN] Which axis to move. (X=1,Y=2,Z=3,AUX=4)
	        handle [IN] Specifies which Nano-Drive to communicate with.
        Return Value:
	        Returns a position value or the appropriate error code.
        """

        val = self.mcl_read(c_uint(axis), c_int(self.handle))
        return val
		
    def readPID(self, axis):
        """
        This is a dummy placeholder function since the MCL does not have readable/writable PID
        """
        return 100,0,0
		
    def writePID(self, PID, axis):
        """
        This is a dummy placeholder function since the MCL does not have readable/writable PID
        """
        pass
		
    def setPositionTrigger(self, pos = 0., axis = 1, mode = "off", clock = 2):
        """
        The MCL cannot trigger on position so the position argument will be ignored.  It will only trigger on the start
        of a waveform and return the position data.  This changes how we must do things.
        "axis", as a descriptor of X or Y is also ignored.  In this function, it's tied to the execution of a waveform which
        must be setup separately.  That waveform contains the proper axis to use for the motion.
        Available clocks are pixel (1), line (2), frame (3) and AUX (4)
        The second argument to setISSClock is the mode.  This is hard coded to mode 2 which sets the polarity as low to high
        pulse.  Mode = 4 turns off the clock.  The third argument (axis) is hard coded to 5 which pulses on a waveform read,
        which returns the position data.  That is called by trigger_line below.
        """
        if mode == "on":
            error_code = self.bindISSClock(c_int(clock), c_int(2), c_int(5), c_int(self.handle))
            print("Clock bind error code: %i" %error_code)
        elif mode == "off":
            error_code = self.bindISSClock(c_int(clock), c_int(4), c_int(5), c_int(self.handle))
            print("Clock unbind error code: %i" %error_code)
        else:
            return
            
    def setClock(self, clock = 2, mode = 0):
        error_code = self.setISSClock(c_int(clock), c_int(mode), c_int(self.handle))
        return error_code

    def write(self,axis, pos):
        """
        Commands the Nano-Drive to move the specified axis to a position.

        Parameters:
	        position [IN] Commanded position in microns.
	        axis [IN] Which axis to move. (X=1,Y=2,Z=3,AUX=4)
	        handle [IN] Specifies which Nano-Drive to communicate with.
        Return Value:
	        Returns MCL_SUCCESS or the appropriate error code.
        """
        error_code = self.mcl_write(c_double(pos), c_uint(axis), c_int(self.handle))
        sleep(0.01)

        if(error_code != 0):
	        print("MCL write error code = ", error_code)
        return error_code
		
    def setup_trajectory(self, axis, start, stop, dwell, points, mode = "line"):
        """
        Need to convert distance (stop - start) and velocity into a number of points and a sampling interval
        The sample interval should be between 0.033 and 5 ms.  This will determine the number of points to
        put in the trajectory.  This number of points is just used for the trajectory definition and is not
        the number of points the STXM measures along the trajectory, which is determined by the DAQ config.
        We could set a default interval of 1 ms to calculate the number of points for each trajectory.
        start,stop [microns] = trajectory start, stop
        dwell [ms] = trajectory dwell / oversampling factor.
        axis should be in the motor class space.  In the motor class it is self.axis
        """
        if mode == "line":
            xstart,ystart = start
            xstop,ystop = stop
            xRange = abs(xstop - xstart)
            yRange = abs(ystop - ystart)
            self.line_dwell = dwell
            self.line_points = points
            self.xpositions = np.linspace(xstart,xstop,self.line_points).astype(np.float64)
            self.ypositions = np.linspace(ystart,ystop,self.line_points).astype(np.float64)
            #dwell in ms
            #Internal x and y cables are likely swapped. This should not need to be changed if cables are switched back.
            #This just puts the correct position values in the axis that are listed in the getAxis function.
            self.xypositions =[0,0]
            self.xypositions[self.getAxis('x')-1] = self.xpositions
            self.xypositions[self.getAxis('y')-1] = self.ypositions
            self.npositions = len(self.xpositions)
            error_code = self.setup_xy(*self.xypositions, self.line_dwell)
            
        elif mode == "1d_line_with_return":
            #This is a new method called if you want to do a return with it.
            #This mode is selected if the y-range is less than 1 nm.
            #These are done for speed and this will probably only be used in image scans.
            
            xstart, y = start
            xstop, y = stop
            xRange = abs(xstop-xstart)
            
            #Set up as a 1d waveform if yRange is small.
            self.line_dwell = dwell
            self.line_points = points
            self.xpositions = np.linspace(xstart,xstop,self.line_points).astype(np.float64)
            waittime = 10. # ms
            minwait = 2 # points
            self.waitpositions = (np.ones((max(int(waittime/self.line_dwell),minwait),))*xstop).astype(np.float64)
            maxvel = 1. # mm/s
            minreturnpoints = 5 # points
            returnpoints = max(int(xRange/maxvel/self.line_dwell),minreturnpoints)
            self.returnpositions = np.linspace(xstop, xstart, returnpoints).astype(np.float64)
            self.totalpositions = np.concatenate((self.xpositions,self.waitpositions,self.returnpositions)).astype(np.float64)
            
            self.npositions = len(self.totalpositions)
            self.ypositions = np.ones((self.npositions,))*y
            error_code = self.setup_1d_waveform(self.getAxis('x'),self.npositions,self.line_dwell, \
                                                    self.totalpositions)

        elif mode == "smooth_move":
            # This is a new method to do a single move of one axis along a smooth trajectory.
            # here "axis" comes from the motor class as self._axis which comes from controller.getAxis() so it is already
            # in the controller space

            delta_position = start - stop
            total_time = 10. + abs(delta_position)/4.

            # Set up as a 1d waveform if yRange is small.
            self.line_dwell = total_time / 20. #20 points in the line
            self.line_points = 20
            time_points = np.linspace(0,total_time,self.line_points)
            self.positions = (delta_position * np.cos(np.pi * time_points / total_time) / 2. - (delta_position / 2. - start)).astype(np.float64)
            error_code = self.setup_1d_waveform(self.getAxis(axis), self.line_points, self.line_dwell, self.positions)

        elif mode == "2d_line_with_return":
            #This is a new method called if you want to do a return with it.
            #This mode is selected if the y-range is more than 1 nm.
            #This is done for focus and linescans.
            xstart, ystart = start
            xstop, ystop = stop
            xRange = abs(xstop-xstart)
            yRange = abs(ystop-ystart)
            
            self.line_dwell = dwell
            self.line_points = points
            self.xpositions = np.linspace(xstart, xstop, self.line_points).astype(np.float64)
            self.ypositions = np.linspace(ystart, ystop, self.line_points).astype(np.float64)
            waittime = 10. #ms
            minwait = 2 # points
            nwait = max(int(waittime/self.line_dwell),minwait)
            self.xwaitpositions = (np.ones((nwait,))*xstop).astype(np.float64)
            self.ywaitpositions = (np.ones((nwait,))*ystop).astype(np.float64)
            
            maxvel = 1. # mm/s
            minreturnpoints = 5 # points
            totRange = (xRange**2+yRange**2)**0.5
            returnpoints = max(int(totRange/maxvel/self.line_dwell),minreturnpoints)
            self.xreturnpositions = np.linspace(xstop,xstart,returnpoints).astype(np.float64)
            self.yreturnpositions = np.linspace(ystop,ystart,returnpoints).astype(np.float64)
            self.xtotalpositions = np.concatenate((self.xpositions, self.xwaitpositions, self.xreturnpositions)).astype(np.float64)
            self.ytotalpositions = np.concatenate((self.ypositions, self.ywaitpositions, self.yreturnpositions)).astype(np.float64)
            self.npositions = len(self.xtotalpositions)
            
            self.xypositions =[0,0]
            self.xypositions[self.getAxis('x')-1] = self.xtotalpositions
            self.xypositions[self.getAxis('y')-1] = self.ytotalpositions

            error_code = self.setup_xy(*self.xypositions, self.line_dwell)
            # distance = abs(stop - start)
            # self.line_points = points
            # self.line_positions = np.linspace(start,stop,self.line_points).astype(np.float64)
            # self.commanded_positions = self.line_positions.copy()
            # self.line_dwell = distance / self.line_points / velocity
            # error_code = self.setup_load_waveform(c_uint(axis), c_uint(self.line_points), \
            #             c_double(self.line_dwell), self.line_positions, c_int(self.handle))

            # error_code = self.setup_read_waveform(c_uint(axis), c_uint(self.line_points), \
            #             c_double(self.line_dwell), c_int(self.handle))
			        

    def trigger_1d_waveform(self, axis = 'x'):
        ##this shouldn't assume that the 1D waveform will only happen on the X axis
        ax = self.getAxis('x')
        n = len(self.totalpositions)
        #nx = len(self.xpositions)
        y = self.read(self.getAxis('y'))
        self.all_positions = np.zeros((n,)).astype(np.float64)
        error_code = self.trigger_acquisition(c_uint(ax),c_uint(n),self.all_positions,c_int(self.handle))

        #print('trigger read waveform error code: %s' %error_code)

        xMeas = self.all_positions#[0:nx]
        yMeas = np.ones(xMeas.shape)*y
        return [xMeas,yMeas]

    def trigger_1d_waveform_new(self, axis='x'):
        ##this shouldn't assume that the 1D waveform will only happen on the X axis
        if axis == 'x':
            axis2 = 'y'
        else:
            axis2 = 'x'
        primary_axis = self.getAxis(axis)
        secondary_axis_pos = self.read(self.getAxis(axis2))
        n = len(self.totalpositions)
        # nx = len(self.xpositions)
        self.all_positions = np.zeros((n,)).astype(np.float64)
        error_code = self.trigger_acquisition(c_uint(primary_axis), c_uint(n), self.all_positions,
                                              c_int(self.handle))
        #print('trigger read waveform error code: %s' % error_code)
        if axis == 'x':
            xMeas = self.all_positions  # [0:nx]
            yMeas = np.ones(xMeas.shape) * secondary_axis_pos
        else:
            yMeas = self.all_positions  # [0:nx]
            xMeas = np.ones(yMeas.shape) * secondary_axis_pos
        return [xMeas, yMeas]

    def setup_1d_waveform(self, axis, npositions, dwell, positions):
        self.totalpositions = positions
        error_code = self.setup_load_waveform(c_uint(axis), c_uint(npositions),c_double(dwell),positions,c_int(self.handle))
        error_code2 = self.setup_read_waveform(c_uint(axis), c_uint(npositions),c_double(dwell),c_int(self.handle))
        #print("setup load waveform error code: %s" %error_code)
        #print("setup read waveform error code: %s" %error_code2)
		
    def trigger_line(self, axis):
        error_code = self.trigger_acquisition(c_uint(axis), c_uint(self.line_points),\
			        self.line_positions, c_int(self.handle))
        return self.line_positions
		
    def read_line(self, axis, start, stop, velocity):
        """
        This will measure position data during an externally executed waveform.
        """
        distance = abs(stop - start)
        nPoints = 100
        positions = np.linspace(start,stop,nPoints).astype(np.float64)
        dwell = distance / 100. / velocity
        error_code = self.read_waveform(c_uint(axis), c_uint(nPoints), c_double(dwell), positions, c_int(self.handle))
		
    def acquire_line(self, axis, start, stop, velocity):	
        """
        This will execute a waveform and measure position data (I think).
        """
        distance = abs(stop - start)
        nPoints = 100
        positions = np.linspace(start,stop,nPoints).astype(np.float64)
        dwell = distance / 100. / velocity
        error_code = self.trigger_acquisition(c_uint(axis), c_uint(nPoints), \
			        c_double(dwell), self.line_positions, c_int(self.handle))
			        
	    
			        
			        
    def setup_xy(self, ax1pos, ax2pos, dwell):
	
        """
        Very general, given a list of x-positons and y-positions, this will set up the motion to move through those in sequence.
        Dwell time (in ms) must be between 5 ms and 0.1 ms.
        Could handle longer dwell times with iterations
        xpos and ypos are numpy arrays.
        """
        #savearg will save the arguments to a folder listed here
        savearg = None
        #savearg = '/global/scratch/pystxmcontrolData/2023/11/231103/SpiralTest/'
        #These will store the desired positions.
        self.ax1pos = ax1pos.astype(np.float64)
        self.ax2pos = ax2pos.astype(np.float64)
        

        #Check to see if len of the two arrays is equal so we don't drive to somewhere crazy.
        if len(self.ax1pos) == len(self.ax2pos):
            #print('Setup xy trajectory: {} positions, {} dwell'.format(len(ax1pos),dwell))
            error_code = self.setup_xy_waveform(self.ax1pos, self.ax2pos, c_void_p(None),
                        c_int(len(ax1pos)), c_double(dwell), c_ushort(1), c_int(self.handle))
                        
            if savearg is not None:
                np.savetxt(savearg+'Succeeded_MCL_WfmaSetup_wfDacX.txt',self.ax1pos)
                np.savetxt(savearg+'Succeeded_MCL_WfmaSetup_wfDacY.txt',self.ax2pos)
                np.savetxt(savearg+'Succeeded_MCL_WfmaSetup_Others.txt',[0,len(ax1pos),dwell,1,self.handle])
                
            print("setup_xy error_code: %i" %error_code)

        else:
            print("mismatch of x and y lengths")
            print(len(self.ax1pos))
            print(len(self.ax2pos))
            pass
	        
        return error_code
	        
    def trigger_xy(self):
        """
        Triggers an already set up xy waveform.
        """
        error_code = self.trigger_xy_waveform(cint(self.handle))
        return error_code
	    
    def read_xy(self):
        """
        Reads the positions for an xy waveform.
        Will throw an error if setup_xy has not been run first.
        """
	    
	    #This is to discern between axis 1 and axis 2 vs x and y
        ax1pos_measured = np.copy(self.ax1pos)
        ax2pos_measured = np.copy(self.ax2pos)
	    
        error_code = self.read_xy_waveform(ax1pos_measured, ax2pos_measured, c_void_p(None), c_int(self.handle))
	    
        self.xpos_measured = (ax1pos_measured,ax2pos_measured)[self.getAxis('x')-1]
        self.ypos_measured = (ax1pos_measured,ax2pos_measured)[self.getAxis('y')-1]
	    
        return error_code
	    
	    
    def acquire_xy(self):
        """
        Triggers and reads the positions for an xy waveform.
        Will throw an error if setup_xy has not been run first.
        This function is blocking.
        """

        ax1pos_measured = np.copy(self.ax1pos)
        ax2pos_measured = np.copy(self.ax2pos)
        
        savearg = None
        #savearg = '/global/scratch/pystxmcontrolData/2023/11/231103/SpiralTest/'
	    
        error_code = self.trigger_read_xy_waveform(ax1pos_measured, ax2pos_measured, c_void_p(None), c_int(self.handle))
        print("acquire_xy error_code: %i" %error_code)
        if savearg is not None:
            np.savetxt(savearg+'Succeeded_MCL_WfmaTriggerAndRead_wfDacX.txt',ax1pos_measured)
            np.savetxt(savearg+'Succeeded_MCL_WfmaTriggerAndRead_wfDacY.txt',ax2pos_measured)
            np.savetxt(savearg+'Succeeded_MCL_WfmaTriggerAndRead_Others.txt',[0,self.handle])
            
	    
        self.xpos_measured = (ax1pos_measured,ax2pos_measured)[self.getAxis('x')-1]
        self.ypos_measured = (ax1pos_measured,ax2pos_measured)[self.getAxis('y')-1]
	    
        return self.xpos_measured, self.ypos_measured
	    
	    	
    def close(self):
        """
        Releases control of all Nano-Drives controlled by this instance of the DLL.
        """
        MADLIB['MCL_ReleaseAllHandles']()



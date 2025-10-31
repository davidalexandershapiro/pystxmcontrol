import automation1 as a1
import socket
import time
from pystxmcontrol.controller.hardwareController import hardwareController
from threading import Lock

class aerotechController(hardwareController):
    """
    Aerotech controller driver class that provides low-level hardware communication
    with Aerotech controllers through the Automation1 SDK.
    
    Architecture:
    ┌─────────────────┐
    │   Controller    │  High level: Hardware abstraction (this class)
    └─────────────────┘
    ┌─────────────────┐
    │     Motor       │  Mid level: Axis-specific operations (aerotechMotor.py)
    └─────────────────┘
    ┌─────────────────┐
    │   Automation1   │  Low level: SDK communication (automation1.py)  
    │      SDK        │
    └─────────────────┘
    
    This class handles:
    - Network connection management to Aerotech controllers
    - Motion control commands (move, stop, enable/disable)
    - Position and status monitoring
    - Error handling and simulation mode support
    
    The Automation1 SDK provides access to many AeroScript commands through the Commands API.
    Similar commands are grouped together under the top-level Commands property. For example,
    Commands.motion provides access to motion commands, Commands.io provides access to I/O operations, etc.
    
    If an error occurs while executing a command, like if the controller is not started or an axis fault
    has occurred, the command will throw a ControllerException that provides information on the error.
    """

    def __init__(self, address = '192.168.1.110', port = 12200, simulation = False):
        """
        Initialize the Aerotech controller object.
        
        The controller object will be None until we connect to the hardware.
        Connecting to the controller will not change its running state, meaning that we might have to also
        call start() before we can run AeroScript programs or perform motion.
        
        Args:
            address: IP address of the Aerotech controller
            port: Network port for communication (typically 12200)
            simulation: Whether to run in simulation mode (no hardware communication)
        """
        
        # Network configuration for controller connection
        self.address = address
        self.port    = port
        
        # Simulation flag for testing without hardware
        self.simulation = simulation
        
        # Motion state tracking for status monitoring
        self.stopped = False      # Flag indicating if motion was stopped
        self.moving  = False       # Flag indicating if motion is active
        
        # Aerotech SDK controller object for hardware communication
        # This reference is None if we are not connected. See connect() method for details.
        self.controller = None
        self.lock = Lock()
        self._waittime = 1. #this is wait after move since "is_moving" seems to be inaccurate

    def _checkConnection(self):
        """
        Check if controller is connected and ready for operations.
        
        We can check if the controller is running using is_running property.
        The controller must be started before calling any APIs under Controller.runtime.
        
        Returns:
            bool: True if connected and ready, False otherwise
        """
        if self.simulation:
            return True
        
        if self.controller is None:
            print(f"Error: Not connected to Aerotech controller at {self.address}:{self.port}")
            return False
        
        try:
            # Test if connection is still alive
            if not self.controller.is_running:
                print(f"Error: Controller at {self.address}:{self.port} is not running")
                return False
            return True
        except Exception as e:
            print(f"Error: Connection to {self.address}:{self.port} is stale: {e}")
            self.controller = None
            return False

    def abortMove(self, motor):
        """
        Stop motion for the specified motor/axis immediately.
        
        This method sends an abort command to the controller to stop any ongoing motion.
        The abort() method is part of the MotionCommands API under Commands.motion.
        
        Args:
            motor: Axis identifier to stop motion for
            
        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """

        if self.simulation:
            return [0, 'Move aborted (simulation)']
        
        if not self._checkConnection():
            return [-1, 'Not connected']
        
        try:
            # Use the abort() method in the MotionCommands API
            self.controller.runtime.commands.motion.abort(motor)
            return [0, 'Move aborted']
        except a1.ControllerException as e:
            print(f"Error aborting move for {motor}: {e.message}")
            return [-1, str(e.message)]
        except Exception as e:
            print(f"Error aborting move for {motor}: {e}")
            return [-1, str(e)]

    def connect(self, IP = None, port = None, timeOut = None):
        """
        Establish connection to the Aerotech controller.
        
        Calling Controller.connect() with no arguments will connect to the controller installed on
        the local machine. If we wanted to connect to a controller installed on a different machine with
        the IP address 192.168.1.15, we could instead call Controller.connect(host="192.168.1.15").
        
        Connecting to the controller will not change its running state, meaning that we might have to also
        call start() before we can run AeroScript programs or perform motion.
        
        This method:
        1. Checks if already connected to avoid redundant connections
        2. Tests network connectivity before attempting SDK connection
        3. Establishes SDK connection to the controller
        4. Starts the controller if not already running
        5. Handles simulation mode appropriately
        
        Args:
            IP: IP address (optional, uses self.address if not provided)
            port: Port number (optional, uses self.port if not provided)
            timeOut: Connection timeout (optional, uses fixed 3-second timeout)
            
        Returns:
            int: 0 for success, -1 for failure
        """

        # Use provided parameters or fall back to instance variables
        address = IP if IP is not None else self.address
        port_num = port if port is not None else self.port
        
        # Check if already connected to avoid redundant connections
        if self.controller is not None:
            try:
                # Test if connection is still alive
                if self.controller.is_running:
                    print(f"Already connected to Aerotech controller at {self.address}:{self.port}")
                    return 0
            except:
                # Connection is stale, reset it for reconnection
                print(f"Stale connection detected, reconnecting to {self.address}:{self.port}...")
                self.controller = None

        if self.simulation:
            print(f"Simulation mode - no actual connection to {self.address}:{self.port}")
            return 0
        
        try:
            print(f"Connecting to Aerotech controller at {address}:{port_num}...")
            
            # Test network connectivity first to ensure controller is reachable
            sock = socket.socket()
            sock.settimeout(3)
            sock.connect((address, port_num))
            sock.close()
            print(f"Network connectivity confirmed to {address}:{port_num}")
            
            # Establish SDK connection to the controller
            # Controller.connect() with host parameter connects to remote controller
            self.controller = a1.Controller.connect(host=address)
            print(f"Aerotech SDK connection established to {address}:{port_num}")
            
            # Start controller if not already running
            # We must start the controller before calling any APIs under Controller.runtime
            if not self.controller.is_running:
                print("Starting controller...")
                self.controller.start()
                print("Controller started")
            else:
                print("Controller already running")
            
            print(f"Aerotech controller connected and running at {address}:{port_num}")
            return 0
            
        except a1.ControllerException as e:
            print(f"Aerotech controller error: {e.message}")
            print(f"Error code: {e.error}")
            return -1
        except socket.error as e:
            print(f"Network connection failed: {e}")
            return -1
        except Exception as e:
            print(f"Failed to connect to Aerotech controller on: {address}:{port_num}")
            print(f"Error: {e}")
            return -1

    def disableAxis(self, axis):
        """
        Disable a specific axis at the hardware level.
        
        This method sends a disable command to the controller to disable the specified axis,
        which stops power to the motor. The disable() method is part of the MotionCommands API.
        
        Args:
            axis: Axis identifier to disable
            
        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """

        if self.simulation:
            return [0, 'Axis disabled (simulation)']
        
        if not self._checkConnection():
            return [-1, 'Not connected']
        
        try:
            # Use the disable() method in the MotionCommands API
            self.controller.runtime.commands.motion.disable(axis)
            print(f"Axis {axis} disabled successfully")
            return [0, "OK"]
        except a1.ControllerException as e:
            print(f"Error disabling axis {axis}: {e.message}")
            return [-1, e.message]
        except Exception as e:
            print(f"Error disabling axis {axis}: {e}")
            return [-1, str(e)]

    def disconnect(self):
        """
        Disconnect from the Aerotech controller.
        
        Disconnecting from a controller will not change its running state, meaning that the controller
        might still be running after we disconnect. Call stop() before disconnecting to stop the controller
        from running AeroScript programs or performing motion.
        
        Use this method when your application no longer needs to interact with the controller but you want
        the controller to continue running. Since we are disconnected, our controller object is no longer
        usable and we should get rid of our reference to it.
        
        This method:
        1. Stops any ongoing motion before disconnecting
        2. Disconnects the SDK connection
        3. Cleans up the controller object
        4. Handles simulation mode appropriately
        
        Returns:
            int: 0 for success, -1 for failure
        """

        if self.simulation:
            print(f"Simulation mode - no actual disconnection from {self.address}:{self.port}")
            return 0
        
        if self.controller is None:
            print(f"Not connected to Aerotech controller at {self.address}:{self.port}")
            return 0
        
        try:
            # Stop any ongoing motion before disconnecting for safety
            if self.moving:
                print("Stopping ongoing motion before disconnect...")
                self.moving = False
                self.stopped = True
            
            # Disconnect from controller and clean up
            self.controller.disconnect()
            self.controller = None
            print(f"Aerotech controller disconnected successfully from {self.address}:{self.port}")
            return 0
            
        except a1.ControllerException as e:
            print(f"Error disconnecting from Aerotech controller at {self.address}:{self.port}: {e.message}")
            self.controller = None
            return -1
        except Exception as e:
            print(f"Error disconnecting from Aerotech controller at {self.address}:{self.port}: {e}")
            self.controller = None
            return -1

    def enableAxis(self, axis):
        """
        Enable a specific axis at the hardware level.
        
        This method sends an enable command to the controller to enable the specified axis,
        which provides power to the motor. The enable() method is part of the MotionCommands API.
        
        Args:
            axis: Axis identifier to enable
            
        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """

        if self.simulation:
            return [0, 'Axis enabled (simulation)']
        
        if not self._checkConnection():
            return [-1, 'Not connected']
        
        try:
            # Use the enable() method in the MotionCommands API
            self.controller.runtime.commands.motion.enable(axis)
            print(f"Axis {axis} enabled successfully")
            return [0, "OK"]
        except a1.ControllerException as e:
            print(f"Error enabling axis {axis}: {e.message}")
            return [-1, e.message]
        except Exception as e:
            print(f"Error enabling axis {axis}: {e}")
            return [-1, str(e)]

    def getPosition(self, motor):
        """
        Get the current position of the specified motor/axis.
        
        This method queries the controller for the current position using the status API.
        ProgramPosition is the position specified in program-space, before being transformed
        and sent to the drive. See the Controller Motion Signals help file topic for more details.
        
        Args:
            motor: Axis identifier to get position for
            
        Returns:
            list: [error_code, position] where error_code is 0 for success, -1 for failure
        """

        if self.simulation:
            return [0, 0.0]  # Return 0 for simulation
        
        if not self._checkConnection():
            return [-1, 0.0]
        
        try:
            # Query position using status API for efficiency
            # Status items are defined in enums in the Python API
            status_config = a1.StatusItemConfiguration()
            status_config.axis.add(a1.AxisStatusItem.ProgramPosition, motor)
            results = self.controller.runtime.status.get_status_items(status_config)
            position = results.axis.get(a1.AxisStatusItem.ProgramPosition, motor).value
            return [0, float(position)]
        except a1.ControllerException as e:
            print(f"Error getting position for {motor}: {e.message}")
            return [-1, 0.0]
        except Exception as e:
            print(f"Error getting position for {motor}: {e}")
            return [-1, 0.0] 

    def initialize(self, simulation = False):
        """
        Initialize the controller object (setup, no connection).
        
        This method sets up the controller object but does not establish
        a connection to the hardware. Connection is handled separately.
        
        Args:
            simulation: Whether to run in simulation mode
            
        Returns:
            int: 0 for success
        """

        self.connect(self.address, self.port)

        self.simulation = simulation
        print("Aerotech controller initialized")
        return 0

    def isConnected(self):
        """
        Check if the controller is connected and ready.
        
        Returns:
            bool: True if connected and ready, False otherwise
        """
        return self._checkConnection()

    def moveBy(self, motor, displacement, speed=None):
        """
        Move motor by relative distance.
        
        This method sends a relative move command to the controller.
        The move is non-blocking - it starts the move and returns immediately.
        
        The move_relative() method is part of the MotionCommands API under Commands.motion.
        
        Args:
            motor: Axis identifier to move
            displacement: Relative distance to move (in controller units)
            speed: Movement speed (optional, uses DefaultAxisSpeed if not provided)
            
        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """

        if self.simulation:
            return [0, 'Relative move completed (simulation)']
        
        if not self._checkConnection():
            return [-1, 'Not connected']
        
        try:
            # Set axis speed if provided
            if speed is not None:
                speed_result = self.setAxisSpeed(motor, speed)
                if speed_result[0] != 0:
                    return speed_result
            
            # Get current speed for the move
            speed_info = self.getAxisSpeed(motor)
            if speed_info['error_code'] == 0:
                current_speed = speed_info['default_speed']
            else:
                current_speed = 0.1  # fallback speed
            
            # Create displacement and speeds as lists as required by Automation1 SDK
            # For single axis move, we need single-element lists
            displacements = [displacement]
            speeds = [current_speed]  # Use the set speed or current default speed
            
            # Use the move_incremental() method in the MotionCommands API
            self.controller.runtime.commands.motion.move_incremental([motor], displacements, speeds)
            return [0, 'Relative move started']
        except a1.ControllerException as e:
            print(f"Error in moveBy for {motor}: {e.message}")
            return [-1, str(e.message)]
        except Exception as e:
            print(f"Error in moveBy for {motor}: {e}")
            return [-1, str(e)]

    def setAxisSpeed(self, motor, speed):
        """
        Set the default axis speed for motion operations.
        
        This method sets the DefaultAxisSpeed parameter which controls the speed
        for move_absolute() and move_incremental() operations when no speed is specified.
        
        Args:
            motor: Axis identifier to configure
            speed: Speed in velocity units (mm/s or appropriate unit)
            
        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        
        if self.simulation:
            return [0, f'Axis speed set to {speed} (simulation)']
        
        if not self._checkConnection():
            return [-1, 'Not connected']
        
        try:
            # Access the motion parameter group for the axis
            axis_params = self.controller.runtime.parameters.axes[motor].motion
            
            # Set DefaultAxisSpeed parameter
            axis_params.default_axis_speed.value = float(speed)
            #print(f"DefaultAxisSpeed set to {speed} for axis {motor}")
            
            return [0, 'Axis speed updated successfully']
            
        except a1.ControllerException as e:
            print(f"Error setting axis speed for {motor}: {e.message}")
            return [-1, str(e.message)]
        except Exception as e:
            print(f"Error setting axis speed for {motor}: {e}")
            return [-1, str(e)]

    def getAxisSpeed(self, motor):
        """
        Get the current default axis speed.
        
        Args:
            motor: Axis identifier to query
            
        Returns:
            dict: Dictionary containing speed settings:
                - error_code: 0 for success, -1 for failure
                - default_speed: Current DefaultAxisSpeed value
                - max_jog_speed: Current MaxJogSpeed value
                - max_speed_clamp: Current MaxSpeedClamp value
        """
        
        if self.simulation:
            return {
                'error_code': 0,
                'default_speed': 0.1,
                'max_jog_speed': 1.0,
                'max_speed_clamp': 0.0
            }
        
        if not self._checkConnection():
            return {'error_code': -1}
        
        try:
            # Access the motion parameter group for the axis
            axis_params = self.controller.runtime.parameters.axes[motor].motion
            
            # Get current parameter values
            default_speed = float(axis_params.default_axis_speed.value)
            max_jog_speed = float(axis_params.max_jog_speed.value)
            max_speed_clamp = float(axis_params.max_speed_clamp.value)
            
            return {
                'error_code': 0,
                'default_speed': default_speed,
                'max_jog_speed': max_jog_speed,
                'max_speed_clamp': max_speed_clamp
            }
            
        except a1.ControllerException as e:
            print(f"Error getting axis speed for {motor}: {e.message}")
            return {'error_code': -1}
        except Exception as e:
            print(f"Error getting axis speed for {motor}: {e}")
            return {'error_code': -1}

    def moveTo(self, motor, target, speed=None):
        """
        Move motor to absolute position with blocking behavior.
        
        The move_absolute() method will not return until the move is complete.
        We can keep this application responsive during the move if we do the move on a background thread.
        
        This method:
        1. Starts an absolute move to the target position
        2. Monitors the move progress using status API
        3. Waits for the move to complete or timeout
        4. Handles simulation mode with realistic timing
        5. Provides dynamic timeout based on move distance
        
        Args:
            motor: Axis identifier to move
            target: Target position (in controller units)
            speed: Movement speed (optional, uses DefaultAxisSpeed if not provided)
            
        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """

        if self.simulation:
            self.moving = True
            time.sleep(0.1)  # Simulate movement time
            self.moving = False
            return [0, 'Move completed (simulation)']
        
        if not self._checkConnection():
            return [-1, 'Not connected']
        
        try:
            # Set axis speed if provided
            if speed is not None:
                speed_result = self.setAxisSpeed(motor, speed)
                if speed_result[0] != 0:
                    return speed_result
            
            # Get current position for timeout calculation
            current_pos = self.getPosition(motor)[1]
            move_delta = abs(target - current_pos)
            self._waittime = move_delta #mm to seconds
            
            # Get current speed for timeout calculation
            speed_info = self.getAxisSpeed(motor)
            if speed_info['error_code'] == 0:
                current_speed = speed_info['default_speed']
            else:
                current_speed = 0.1  # fallback speed
            
            # Create target and speeds as lists as required by Automation1 SDK
            # For single axis move, we need single-element lists
            targets = [target]
            speeds = [current_speed]  # Use the set speed or current default speed
            
            # Start the absolute move using move_absolute() method
            self.controller.runtime.commands.motion.move_absolute([motor], targets, speeds)
            self.moving = True
            
            # Wait for move to complete with dynamic timeout
            t0 = time.time()
            # Calculate timeout based on actual move time: distance/speed + safety margin
            expected_time = move_delta / current_speed
            timeout = max(10.0, expected_time * 3.0)  # 3x safety margin, minimum 10 seconds
            #print(f"Move distance: {move_delta:.6f}, Speed: {current_speed:.6f}, Expected time: {expected_time:.1f}s, Timeout: {timeout:.1f}s")
            
            while self.moving:
                if self.stopped:
                    self.moving = False
                    self.stopped = False
                    time.sleep(self._waittime)
                    return [0, 'Move stopped']
                
                # Check if move is complete using status API
                try:
                    # Use DriveStatus to check if in position and not moving
                    status_config = a1.StatusItemConfiguration()
                    status_config.axis.add(a1.AxisStatusItem.DriveStatus, motor)
                    results = self.controller.runtime.status.get_status_items(status_config)
                    drive_status = int(results.axis.get(a1.AxisStatusItem.DriveStatus, motor).value)
                    
                    # Check if in position and not moving
                    in_position = (drive_status & a1.DriveStatus.InPosition) == a1.DriveStatus.InPosition
                    move_active = (drive_status & a1.DriveStatus.MoveActive) == a1.DriveStatus.MoveActive
                    
                    # Also check AxisStatus for more reliable motion detection
                    axis_status_config = a1.StatusItemConfiguration()
                    axis_status_config.axis.add(a1.AxisStatusItem.AxisStatus, motor)
                    axis_results = self.controller.runtime.status.get_status_items(axis_status_config)
                    axis_status = int(axis_results.axis.get(a1.AxisStatusItem.AxisStatus, motor).value)
                    
                    motion_done = (axis_status & a1.AxisStatus.MotionDone) == a1.AxisStatus.MotionDone
                    jogging = (axis_status & a1.AxisStatus.Jogging) == a1.AxisStatus.Jogging
                    
                    # More reliable movement detection using AxisStatus
                    # MotionDone = True means motion is complete (velocity command reached zero)
                    # Jogging = True means axis is performing MoveIncremental/MoveAbsolute motion
                    # Moving = Jogging and NOT MotionDone
                    is_moving = jogging and not motion_done
                    
                    # print(f"DriveStatus: InPosition={in_position}, MoveActive={move_active}")
                    # print(f"AxisStatus: MotionDone={motion_done}, Jogging={jogging}, IsMoving={is_moving}")
                    
                    # Use the more reliable AxisStatus-based movement detection
                    if not is_moving:
                        # print("breaking the loop - motion complete")
                        self.moving = False
                        time.sleep(self._waittime)
                        return [0, 'Move completed']
                    
                    # Check timeout and abort if necessary
                    if (time.time() - t0) > timeout:
                        print(f"Aerotech move timeout for {motor}. Aborting...")
                        self.moving = False
                        return self.abortMove(motor)
                    
                    time.sleep(0.01)  # Small delay to prevent busy waiting
                    
                except a1.ControllerException as e:
                    print(f"Error checking move status: {e.message}")
                    self.moving = False
                    return [-1, str(e.message)]
                except Exception as e:
                    print(f"Error checking move status: {e}")
                    self.moving = False
                    return [-1, str(e)]
                    
        except a1.ControllerException as e:
            print(f"Error in moveTo for {motor}: {e.message}")
            self.moving = False
            return [-1, str(e.message)]
        except Exception as e:
            print(f"Error in moveTo for {motor}: {e}")
            self.moving = False
            return [-1, str(e)]

    def getAxes(self):
        """
        Get the list of available axes from the controller.
        
        This method queries the controller for all available axes using the Automation1 SDK.
        It uses the axis count and identification parameters to get axis names.
        
        Returns:
            list: List of available axis names, or empty list if not connected or error
        """
        
        if self.simulation:
            # Return common axis names for simulation
            return ["XCoarse_sim", "YCoarse_sim", "YDetector_sim", "XDetector_sim", "ZDetector_sim", "ZCoarse_sim", "Ypiezo_sim", "Xpiezo_sim"]
        
        if not self._checkConnection():
            return []
        
        try:
            # Get all available axes from the controller using axis count and identification
            if self.controller is not None and hasattr(self.controller.runtime, 'parameters'):
                try:
                    runtime = self.controller.runtime
                    
                    # Get all axis names using axis count and identification
                    axis_names = []
                    for axis_index in range(runtime.parameters.axes.count):
                        # Get the axis name parameter for each axis
                        axis_name = runtime.parameters.axes[axis_index].identification.axis_name.value
                        axis_names.append(axis_name)
                    
                    print(f"Axis count: {len(axis_names)}")
                    print("Axis names:", axis_names)
                    
                    return axis_names
                    
                except Exception as e:
                    print(f"Error accessing axis identification parameters: {e}")
                    return []
            else:
                print("Controller not available or parameters not accessible")
                return []
            
        except a1.ControllerException as e:
            print(f"Error getting axes from controller: {e.message}")
            return []
        except Exception as e:
            print(f"Error getting axes from controller: {e}")
            return []

    def start(self):
        
        """
        Start the Aerotech controller if connected.
        
        The act of connecting to the controller on its own will not change the running state of the controller
        so we have to explicitly start it by calling Controller.start(). We could check Controller.is_running to
        see if the controller is already running, but since Controller.start() will just do nothing if the
        controller is already running we can call it regardless.
        
        We must start the controller before calling any APIs under Controller.runtime.
        
        This method:
        1. Checks if controller is connected before attempting to start
        2. Verifies if controller is already running
        3. Starts the controller if not already running
        4. Handles simulation mode appropriately
        
        Returns:
            int: 0 for success, -1 for failure
        """

        if self.simulation:
            print(f"Simulation mode - no actual start for {self.address}:{self.port}")
            return 0
        
        if self.controller is None:
            print(f"Cannot start controller - not connected to {self.address}:{self.port}")
            return -1
        
        try:
            # Check if controller is already running to avoid redundant starts
            if self.controller.is_running:
                print(f"Aerotech controller at {self.address}:{self.port} is already running")
                return 0
            
            # Start the controller
            print(f"Starting Aerotech controller at {self.address}:{self.port}...")
            self.controller.start()
            print(f"Aerotech controller at {self.address}:{self.port} started successfully")
            return 0
            
        except a1.ControllerException as e:
            print(f"Error starting Aerotech controller at {self.address}:{self.port}: {e.message}")
            return -1
        except Exception as e:
            print(f"Error starting Aerotech controller at {self.address}:{self.port}: {e}")
            return -1 

    def setInPositionTolerance(self, motor, distance=None, time=None, timeout_threshold=None):
        """
        Set the InPosition tolerance parameters for the specified motor/axis.
        
        The InPosition status is determined by both distance and time criteria:
        - InPositionDistance: Maximum position error allowed (distance units)
        - InPositionTime: How long axis must stay within tolerance (milliseconds)
        - InPositionTimeoutThreshold: Maximum time allowed to reach "in position" (milliseconds)
        
        Args:
            motor: Axis identifier to configure
            distance: Position tolerance in distance units (None to keep current)
            time: Time requirement in milliseconds (None to keep current)
            timeout_threshold: Maximum time to reach "in position" in milliseconds (None to keep current)
            
        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        
        if self.simulation:
            return [0, f'InPosition tolerance set (simulation): distance={distance}, time={time}, timeout_threshold={timeout_threshold}']
        
        if not self._checkConnection():
            return [-1, 'Not connected']
        
        try:
            # Access the motion parameter group for the axis
            axis_params = self.controller.runtime.parameters.axes[motor].motion
            
            # Set InPositionDistance if provided
            if distance is not None:
                axis_params.in_position_distance.value = float(distance)
                print(f"InPositionDistance set to {distance} for axis {motor}")
            
            # Set InPositionTime if provided  
            if time is not None:
                axis_params.in_position_time.value = float(time)
                print(f"InPositionTime set to {time} ms for axis {motor}")
            
            # Set InPositionTimeoutThreshold if provided
            if timeout_threshold is not None:
                axis_params.in_position_timeout_threshold.value = float(timeout_threshold)
                print(f"InPositionTimeoutThreshold set to {timeout_threshold} ms for axis {motor}")
            
            return [0, 'InPosition tolerance updated successfully']
            
        except a1.ControllerException as e:
            print(f"Error setting InPosition tolerance for {motor}: {e.message}")
            return [-1, str(e.message)]
        except Exception as e:
            print(f"Error setting InPosition tolerance for {motor}: {e}")
            return [-1, str(e)]

    def getInPositionTolerance(self, motor):
        """
        Get the current InPosition tolerance parameters for the specified motor/axis.
        
        Returns:
            dict: Dictionary containing tolerance settings:
                - error_code: 0 for success, -1 for failure
                - distance: Current InPositionDistance value
                - time: Current InPositionTime value  
                - timeout_threshold: InPositionTimeoutThreshold value
        """
        
        if self.simulation:
            return {
                'error_code': 0,
                'distance': 0.01,
                'time': 0.0,
                'timeout_threshold': 0.0
            }
        
        if not self._checkConnection():
            return {'error_code': -1}
        
        try:
            # Access the motion parameter group for the axis
            axis_params = self.controller.runtime.parameters.axes[motor].motion
            
            # Get current parameter values
            distance = float(axis_params.in_position_distance.value)
            time = float(axis_params.in_position_time.value)
            timeout_threshold = float(axis_params.in_position_timeout_threshold.value)
            
            return {
                'error_code': 0,
                'distance': distance,
                'time': time,
                'timeout_threshold': timeout_threshold
            }
            
        except a1.ControllerException as e:
            print(f"Error getting InPosition tolerance for {motor}: {e.message}")
            return {'error_code': -1}
        except Exception as e:
            print(f"Error getting InPosition tolerance for {motor}: {e}")
            return {'error_code': -1}

    def printInPositionTolerance(self, motor):
        """
        Print the current InPosition tolerance settings for debugging.
        
        Args:
            motor: Axis identifier to check
        """
        tolerance = self.getInPositionTolerance(motor)
        if tolerance['error_code'] == 0:
            print(f"InPosition Tolerance for {motor}:")
            print(f"  Distance: {tolerance['distance']:.6f} units")
            print(f"  Time: {tolerance['time']:.1f} ms")
            print(f"  Timeout Threshold: {tolerance['timeout_threshold']:.1f} ms")
        else:
            print(f"Failed to get InPosition tolerance for {motor}") 


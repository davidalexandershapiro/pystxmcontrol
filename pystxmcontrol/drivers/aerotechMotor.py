from pystxmcontrol.controller.motor import motor
import time
import automation1 as a1

class aerotechMotor(motor):
    """
    Aerotech motor driver class that provides high-level interface for controlling
    Aerotech axes through the Automation1 SDK.
    
    Architecture:
    ┌─────────────────┐
    │   Controller    │  High level: Hardware abstraction (aerotechController.py)
    └─────────────────┘
    ┌─────────────────┐
    │     Motor       │  Mid level: Axis-specific operations (this class)
    └─────────────────┘
    ┌─────────────────┐
    │   Automation1   │  Low level: SDK communication (automation1.py)
    │      SDK        │
    └─────────────────┘
    
    This class handles unit conversion, software limits, simulation mode,
    and provides status checking methods for axis state monitoring.
    
    The motor class acts as a high-level wrapper around the controller's low-level
    motion commands, providing unit conversion, software limits, and status monitoring.
    It uses the controller's Commands API for motion operations and Status API for
    position and status information.
    """
    
    def __init__(self, controller = None, config = None):
        """
        Initialize the Aerotech motor object.
        
        The motor requires a controller reference to perform hardware operations.
        The configuration dictionary contains parameters for unit conversion and limits.
        
        Args:
            controller: Reference to the aerotechController instance
            config: Dictionary containing motor configuration parameters
                   (units, offset, minValue, maxValue, etc.)
        """

        # No Simulation
        self.simulation = False
        
        # Controller reference for low-level hardware communication
        self.controller = controller
        
        # Motor configuration with default values if none provided
        # units: conversion factor from controller units to user units
        # offset: position offset to apply
        # minValue/maxValue: software limits for safety
        self.config = config or {"units": 1, "offset": 0, "minValue": -40, "maxValue": 40}
        
        # Motor state variables
        self.axis = None          # Axis identifier (e.g., "X", "Y", "Z")
        self.position = None      # Current position (will be set when connected)
        self.moving = False       # Motion state flag

    def _checkConnection(self):
        """
        Check if motor is properly connected and ready for operations.
        
        This method validates both the controller reference and the controller's
        connection state before allowing hardware operations.
        
        Returns:
            bool: True if connected and ready, False otherwise
        """
        if self.simulation:
            return True
        
        if self.controller is None:
            print(f"Error: Motor {self.axis} has no controller reference")
            return False
        
        if not self.controller.isConnected():
            print(f"Error: Controller for motor {self.axis} is not connected")
            return False
        
        return True

    def _checkAxis(self):
        """
        Check if axis is properly set.
        
        Returns:
            bool: True if axis is set, False otherwise
        """
        if self.axis is None:
            print("Error: No axis specified for motor")
            return False
        return True

    def _getStatusItem(self, status_item, axis=None):
        """
        Helper method to get a specific status item for the axis.
        
        Status items are defined in enums in the Python API. We can get information
        about the current state of the controller, tasks, and axes via status items.
        To do so, we must first specify the items we want to query by creating a
        StatusItemConfiguration object.
        
        Args:
            status_item: The status item to retrieve (e.g., DriveStatus, AxisStatus)
            axis: Axis to check (defaults to self.axis)
            
        Returns:
            int: Status value, or 0 if error
        """
        if axis is None:
            axis = self.axis
        
        try:
            status_config = a1.StatusItemConfiguration()
            status_config.axis.add(status_item, axis)
            results = self.controller.controller.runtime.status.get_status_items(status_config)
            return int(results.axis.get(status_item, axis).value)
        except Exception as e:
            print(f"Error getting status item for {axis}: {e}")
            return 0

    def checkLimits(self, pos):
        """
        Check if the requested position is within software limits.
        
        Software limits provide safety boundaries to prevent the motor from
        moving to potentially dangerous positions.
        
        Args:
            pos: Position to check (in user units)
            
        Returns:
            bool: True if position is within limits, False otherwise
        """
        return self.config["minValue"] <= pos <= self.config["maxValue"]

    def connect(self, axis = None, **kwargs):
        """
        Connect the motor to a specific axis and initialize it.
        
        This method sets up the axis identifier and enables the axis if not already enabled.
        It also gets the initial position and handles simulation mode appropriately.
        
        The enable() method is part of the MotionCommands API under Commands.motion.
        If an error occurs while executing a command, like if the controller is not started
        or an axis fault has occurred, the command will throw a ControllerException.
        
        Args:
            axis: Axis identifier (e.g., "X", "Y", "Z")
            **kwargs: Additional keyword arguments
            
        Returns:
            bool: True if connection successful
        """

        if axis is None:
            print("Error: No axis specified for connection")
            return False
        
        self.axis = axis
        self.group = self.axis.split('.')[0]  # Extract group from axis name
        self.simulation = self.controller.simulation if self.controller else False
        
        if not(self.simulation):
            if not self._checkConnection():
                return False
            
            # Enable the axis if not already enabled
            try:
                # Check if axis is enabled using status API
                # DriveStatus is a series of bits that can be masked to get various information
                drive_status = self._getStatusItem(a1.AxisStatusItem.DriveStatus, self.axis)
                is_enabled = (drive_status & a1.DriveStatus.Enabled) == a1.DriveStatus.Enabled
                
                self.controller.setInPositionTolerance(self.axis, self.config["position tolerance"]/self.config["units"], 10, 10000)
                
                if not is_enabled:
                    print(f"Enabling axis {self.axis}...")
                    try:
                        # Use the enable() method in the MotionCommands API
                        self.controller.controller.runtime.commands.motion.enable(self.axis)
                        time.sleep(0.5)  # Allow time for enable to complete
                        print(f"Axis {self.axis} enabled successfully")
                    except a1.ControllerException as e:
                        print(f"Warning: Could not enable axis {self.axis}: {e.message}")
                        # Continue anyway - some axes might not need explicit enabling
                if self.config["max velocity"] > 0:
                    self.velocity = self.config["max velocity"]
                else:
                    self.velocity = 0.1
                # Get initial position
                self.position = self.getPos()
                print(f"Axis {self.axis} connected, position: {self.position:.6f}")
                
            except a1.ControllerException as e:
                print(f"Warning: Could not connect to axis {self.axis}: {e.message}")
                # Still try to get position even if enable failed
                try:
                    self.position = self.getPos()
                except:
                    print(f"Could not get position for axis {self.axis}")
            except Exception as e:
                print(f"Warning: Could not enable axis {self.axis}: {e}")
                # Still try to get position even if enable failed
                try:
                    self.position = self.getPos()
                except:
                    print(f"Could not get position for axis {self.axis}")
        return True

    def setAxisParams(self, velocity = 0.1):
        """
        Set the axis parameters.
        """
        self.velocity = velocity

    def disable(self):
        """
        Disable this motor/axis.
        
        This method calls the controller's disableAxis method to disable the axis
        at the hardware level. The disable() method is part of the MotionCommands API.
        
        Returns:
            bool: True if disable successful, False otherwise
        """

        if self.simulation:
            print(f"Simulation: Disabling axis {self.axis}")
            return True
        
        if not self._checkAxis() or not self._checkConnection():
            return False
        
        try:
            self.err, retStr = self.controller.disableAxis(self.axis)
            return self.err == 0
        except Exception as e:
            print(f"Error disabling motor {self.axis}: {e}")
            return False

    def enable(self):
        """
        Enable this motor/axis.
        
        This method calls the controller's enableAxis method to enable the axis
        at the hardware level. The enable() method is part of the MotionCommands API.
        
        Returns:
            bool: True if enable successful, False otherwise
        """

        if self.simulation:
            print(f"Simulation: Enabling axis {self.axis}")
            return True
        
        if not self._checkAxis() or not self._checkConnection():
            return False
        
        try:
            self.err, retStr = self.controller.enableAxis(self.axis)
            return self.err == 0
        except Exception as e:
            print(f"Error enabling motor {self.axis}: {e}")
            return False

    def getDetailedStatus(self):
        """
        Get comprehensive status information about the axis.
        
        This method uses the status API to get multiple status items in one call for efficiency.
        Status items are defined in enums in the Python API. DriveStatus is a series of bits that
        can be masked to get various information about the state of the drive. AxisStatus is similar
        and can be masked to get information about the state of the axis.
        
        Returns a dictionary containing:
        - enabled: Whether the axis is enabled
        - homed: Whether the axis is homed
        - in_position: Whether the axis is in position
        - move_active: Whether a move is currently active
        - position: Current position (in user units)
        - moving: Motion state flag
        
        Returns:
            dict: Dictionary containing detailed status information
        """

        if self.simulation:
            return {
                'enabled': True,
                'homed': True,
                'in_position': True,
                'position': self.position or 0.0,
                'moving': self.moving
            }
        
        if not self._checkAxis() or not self._checkConnection():
            return {
                'enabled': False,
                'homed': False,
                'in_position': False,
                'move_active': False,
                'position': 0.0,
                'moving': False
            }
        
        try:
            # Get multiple status items in one API call for efficiency
            status_config = a1.StatusItemConfiguration()
            status_config.axis.add(a1.AxisStatusItem.ProgramPosition, self.axis)
            status_config.axis.add(a1.AxisStatusItem.DriveStatus, self.axis)
            status_config.axis.add(a1.AxisStatusItem.AxisStatus, self.axis)
            results = self.controller.controller.runtime.status.get_status_items(status_config)
            
            # Extract position
            position = results.axis.get(a1.AxisStatusItem.ProgramPosition, self.axis).value
            
            # Extract drive status flags
            # DriveStatus is acquired as a float, but we need to interpret it as a series of maskable bits
            drive_status = int(results.axis.get(a1.AxisStatusItem.DriveStatus, self.axis).value)
            is_enabled = (drive_status & a1.DriveStatus.Enabled) == a1.DriveStatus.Enabled
            in_position = (drive_status & a1.DriveStatus.InPosition) == a1.DriveStatus.InPosition
            move_active = (drive_status & a1.DriveStatus.MoveActive) == a1.DriveStatus.MoveActive
            acceleration_phase = (drive_status & a1.DriveStatus.AccelerationPhase) == a1.DriveStatus.AccelerationPhase
            deceleration_phase = (drive_status & a1.DriveStatus.DecelerationPhase) == a1.DriveStatus.DecelerationPhase
            
            # Extract axis status flags
            # AxisStatus is similar to DriveStatus in that it can be masked to get information
            axis_status = int(results.axis.get(a1.AxisStatusItem.AxisStatus, self.axis).value)
            is_homed = (axis_status & a1.AxisStatus.Homed) == a1.AxisStatus.Homed
            is_jogging = (axis_status & a1.AxisStatus.Jogging) == a1.AxisStatus.Jogging
            motion_done = (axis_status & a1.AxisStatus.MotionDone) == a1.AxisStatus.MotionDone
            
            # Much simpler and more reliable movement detection:
            # Jogging = True means axis is performing MoveIncremental/MoveAbsolute motion
            # MotionDone = True means motion is complete (velocity command reached zero)
            # Moving = Jogging and NOT MotionDone
            is_moving = is_jogging and not motion_done
            
            return {
                'enabled': is_enabled,
                'homed': is_homed,
                'in_position': in_position,
                'move_active': move_active,
                'position': position * self.config["units"] + self.config["offset"],
                'moving': is_moving  # Use combined movement indicators
            }
        except Exception as e:
            print(f"Error getting detailed status for {self.axis}: {e}")
            return {
                'enabled': False,
                'homed': False,
                'in_position': False,
                'move_active': False,
                'position': 0.0,
                'moving': False
            }

    def getPos(self, **kwargs):
        """
        Get the current position of the motor.
        
        This method converts the controller position to user units by applying the units
        conversion factor and offset. ProgramPosition is the position specified in program-space,
        before being transformed and sent to the drive.
        
        Returns:
            float: Current position in user units
        """

        if not(self.simulation):
            if not self._checkAxis() or not self._checkConnection():
                return 0.0
            
            try:
                self.err, self.position = self.controller.getPosition(self.axis)
                if self.err == 0:
                    return self.position * self.config["units"] + self.config["offset"]
                else:
                    print(f"Error getting position for {self.axis}: {self.position}")
                    return 0.0
            except Exception as e:
                print(f"Error getting position for {self.axis}: {e}")
                return 0.0
        else:
            # In simulation, return 0 if position is None
            if self.position is None:
                return 0.0
            return self.position

    def getStatus(self, **kwargs):
        """
        Get the basic motion status of the motor.
        
        Returns:
            bool: True if motor is moving, False if stationary
        """

        return self.moving

    def home(self):
        """
        Home the axis.
        
        This method initiates a homing sequence for the axis. Homing establishes a reference
        position for the axis. The home() method is part of the MotionCommands API.
        
        Returns:
            bool: True if homing successful, False otherwise
        """

        if self.simulation:
            print(f"Simulation: Homing axis {self.axis}")
            return True
        
        if not self._checkAxis() or not self._checkConnection():
            return False
        
        try:
            # Use the home() method in the MotionCommands API
            self.controller.controller.runtime.commands.motion.home(self.axis)
            print(f"Axis {self.axis} homed successfully")
            return True
        except a1.ControllerException as e:
            print(f"Error homing axis {self.axis}: {e.message}")
            return False
        except Exception as e:
            print(f"Error homing axis {self.axis}: {e}")
            return False

    def isEnabled(self):
        """
        Check if the axis is enabled.
        
        This method uses DriveStatus to check if the axis is enabled.
        DriveStatus is a series of bits that can be masked to get various information.
        
        Returns:
            bool: True if axis is enabled, False otherwise
        """

        if self.simulation:
            return True
        
        if not self._checkAxis() or not self._checkConnection():
            return False
        
        try:
            drive_status = self._getStatusItem(a1.AxisStatusItem.DriveStatus, self.axis)
            return (drive_status & a1.DriveStatus.Enabled) == a1.DriveStatus.Enabled
        except:
            return False

    def isHomed(self):
        """
        Check if the axis is homed.
        
        This method uses AxisStatus to check if the axis is homed.
        AxisStatus is a series of bits that can be masked to get various information.
        Homed indicates whether the axis has been homed since the last controller reset.
        
        Returns:
            bool: True if axis is homed, False otherwise
        """

        if self.simulation:
            return True
        
        if not self._checkAxis() or not self._checkConnection():
            return False
        
        try:
            axis_status = self._getStatusItem(a1.AxisStatusItem.AxisStatus, self.axis)
            return (axis_status & a1.AxisStatus.Homed) == a1.AxisStatus.Homed
        except:
            return False

    def isInPosition(self):
        """
        Check if the axis is in position (not moving).
        
        This method uses DriveStatus to check if the axis is in position.
        DriveStatus is a series of bits that can be masked to get various information.
        
        Returns:
            bool: True if axis is in position, False otherwise
        """

        if self.simulation:
            return True
        
        if not self._checkAxis() or not self._checkConnection():
            return False
        
        try:
            drive_status = self._getStatusItem(a1.AxisStatusItem.DriveStatus, self.axis)
            return (drive_status & a1.DriveStatus.InPosition) == a1.DriveStatus.InPosition
        except:
            return False

    def moveBy(self, step, **kwargs):
        """
        Move the motor by a relative distance.
        
        This method sends a relative move command to the controller using move_relative().
        The move is non-blocking - it starts the move and returns immediately.
        
        The move_relative() method is part of the MotionCommands API under Commands.motion.
        
        This method:
        1. Checks software limits before moving
        2. Converts user units to controller units
        3. Calls the controller's moveBy method
        4. Handles simulation mode
        
        Args:
            step: Relative distance to move (in user units)
            **kwargs: Additional keyword arguments
            
        Returns:
            float: New position after the move
        """

        if not self._checkAxis():
            return 0.0
        
        pos = self.getPos()
        if self.checkLimits(pos + step):
            if not(self.simulation):
                if not self._checkConnection():
                    return pos
                
                try:
                    step = step / self.config["units"]  # Convert to controller units
                    self.err, retStr = self.controller.moveBy(self.axis, step)
                    if self.err != 0:
                        print(f"Error in moveBy for {self.axis}: {retStr}")
                except Exception as e:
                    print(f"Error in moveBy for {self.axis}: {e}")
            else:
                self.position = self.position + step
        else:
            print("[Aerotech] Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,pos))
        return self.getPos()

    def moveTo(self, position, **kwargs):
        """
        Move the motor to an absolute position.
        
        This method sends an absolute move command to the controller using move_absolute().
        The move_absolute() method will not return until the move is complete.
        We can keep this application responsive during the move if we do the move on a background thread.
        
        This method:
        1. Checks software limits before moving
        2. Converts user units to controller units
        3. Applies position offset
        4. Calls the controller's moveTo method
        5. Handles simulation mode with realistic timing
        
        Args:
            position: Target position (in user units)
            **kwargs: Additional keyword arguments
            
        Returns:
            float: New position after the move
        """

        if not self._checkAxis():
            return 0.0
        
        if self.checkLimits(position):
            if not(self.simulation):
                if not self._checkConnection():
                    return self.getPos()
                
                try:
                    pos = (position - self.config["offset"]) / self.config["units"]  # Convert to controller units
                    self.moving = True
                    
                    if "speed" in kwargs.keys():
                        speed = kwargs["speed"]
                    else:
                        speed = self.velocity 
                    
                    self.err, retStr = self.controller.moveTo(self.axis, pos, speed)
                    self.moving = False
                    if self.err != 0:
                        print(f"Error in moveTo for {self.axis}: {retStr}")
                except Exception as e:
                    print(f"Error in moveTo for {self.axis}: {e}")
                    self.moving = False
            else:
                # Simulate movement time based on distance for realistic behavior
                move_time = abs(position - self.position) * 0.001  # 0.001 seconds per unit
                self.controller.moving = True
                time.sleep(move_time)
                self.controller.moving = False
                self.position = position
        else:
            print("[Aerotech] Software limits exceeded for axis %s. Requested position: %.2f" %(self.axis,position))
        return self.getPos()

    def stop(self):
        """
        Stop the motor motion immediately.
        
        This method calls the controller's abortMove method to stop any ongoing motion
        for this axis. The abort() method is part of the MotionCommands API.
        """

        if not self._checkAxis() or not self._checkConnection():
            return
        
        try:
            self.err, self.returnedStr = self.controller.abortMove(self.axis)
            if self.err != 0:
                print(f"Error stopping motor {self.axis}: {self.returnedStr}")
        except Exception as e:
            print(f"Error stopping motor {self.axis}: {e}")
        return 
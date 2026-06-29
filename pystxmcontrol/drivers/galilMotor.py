from pystxmcontrol.controller.motor import motor, SoftwareLimitError
import time

class galilMotor(motor):
    """
    Galil motor driver class that provides a high-level interface for controlling a
    single Galil axis through the galilController (gclib) low-level driver.

    Architecture:
    ┌─────────────────┐
    │     Motor       │  High level: Axis abstraction (this class)
    └─────────────────┘
    ┌─────────────────┐
    │   Controller    │  Mid level: Hardware communication (galilController.py)
    └─────────────────┘
    ┌─────────────────┐
    │     gclib       │  Low level: Galil C library wrapper (gclib.py)
    └─────────────────┘

    This driver covers Coarse-style stages only, so its responsibilities mirror the XPS
    and Aerotech coarse motors: unit conversion (encoder counts <-> engineering units),
    software limit enforcement, simulation mode, and blocking absolute/relative moves.

    Galil positions and speeds are in encoder counts.  This layer converts to/from user
    units with the standard ``user = counts * units + offset`` convention used across the
    other drivers, so ``config["units"]`` is the engineering value of one encoder count.

    NOTE: This is a draft placeholder written before hardware was available.  Verify the
    axis letter mapping, the units/counts scaling, and speed handling against the real
    controller once it arrives.
    """

    def __init__(self, controller = None, config = None):
        """
        Initialize the Galil motor object.

        Args:
            controller: Reference to the galilController instance
            config: Dictionary of motor configuration parameters
                    (units, offset, minValue, maxValue, max velocity, ...)
        """
        self.controller = controller
        self.simulation = False
        self.config = config or {"units": 1, "offset": 0, "minValue": -40, "maxValue": 40}
        self.axis = None
        self.position = 0.0
        self.moving = False
        self.velocity = None
        self._controller_position = 0.0  # encoder counts, used for simulation mode

    def _checkConnection(self):
        """
        Check that the motor has a connected controller and an assigned axis.

        Returns:
            bool: True if ready for hardware operations, False otherwise
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
        Check that an axis letter has been assigned.

        Returns:
            bool: True if axis is set, False otherwise
        """
        if self.axis is None:
            print("Error: No axis specified for Galil motor")
            return False
        return True

    def checkLimits(self, pos):
        """
        Check whether the requested position is within software limits.

        Args:
            pos: Position to check (in user units)

        Returns:
            bool: True if within limits

        Raises:
            SoftwareLimitError: if the position is outside the configured limits
        """
        if pos < self.config["minValue"]:
            limit_type, limit = "lower", self.config["minValue"]
        elif pos > self.config["maxValue"]:
            limit_type, limit = "upper", self.config["maxValue"]
        if self.config["minValue"] <= pos <= self.config["maxValue"]:
            return True
        self.moving = False
        raise SoftwareLimitError(self.axis, pos, limit, limit_type=limit_type)

    def connect(self, axis = None, **kwargs):
        """
        Assign the motor to a Galil axis letter and initialize it.

        Enables the axis (servo on), seeds the slew speed from ``config["max velocity"]``,
        and reads the initial position.

        Args:
            axis: Axis letter (e.g. "A")
            **kwargs: Additional keyword arguments

        Returns:
            bool: True if connection successful
        """
        if axis is None:
            print("Error: No axis specified for Galil motor connection")
            return False

        self.axis = axis
        self.simulation = self.controller.simulation if self.controller else False

        if not self.simulation:
            if not self._checkConnection():
                return False
            try:
                self.controller.enableAxis(self.axis)
                # Seed slew speed from config; converted to counts/sec in setAxisParams.
                if self.config.get("max velocity", 0) > 0:
                    self.setAxisParams(self.config["max velocity"])
                self.position = self.getPos()
                print(f"Galil axis {self.axis} connected, position: {self.position:.6f}")
            except Exception as e:
                print(f"Warning: Could not fully initialize Galil axis {self.axis}: {e}")
        return True

    def setAxisParams(self, velocity):
        """
        Set the slew speed for the axis.

        ``velocity`` is in user (engineering) units/second and is converted to encoder
        counts/second for the controller.

        Args:
            velocity: Slew speed in user units/second
        """
        self.velocity = velocity
        if not self.simulation and self._checkConnection() and self._checkAxis():
            counts_per_sec = abs(velocity / self.config["units"])
            self.controller.setAxisSpeed(self.axis, counts_per_sec)

    def getPos(self, **kwargs):
        """
        Get the current position of the motor in user units.

        Returns:
            float: Current position (counts * units + offset)
        """
        if not self.simulation:
            if not self._checkAxis() or not self._checkConnection():
                return 0.0
            self.err, counts = self.controller.getPosition(self.axis)
            if self.err == 0:
                self.position = counts * self.config["units"] + self.config["offset"]
                return self.position
            print(f"Error getting position for {self.axis}")
            return 0.0
        return self._controller_position * self.config["units"] + self.config["offset"]

    def getStatus(self, **kwargs):
        """
        Get the basic motion status of the motor.

        Returns:
            bool: True if the motor is moving, False otherwise
        """
        return self.moving

    def moveTo(self, position, **kwargs):
        """
        Move the motor to an absolute position (user units), blocking until complete.

        Args:
            position: Target position in user units
            **kwargs: May contain "speed" (user units/second) to override the slew speed

        Returns:
            float: New position after the move
        """
        if not self._checkAxis():
            return 0.0

        if self.checkLimits(position):
            counts = (position - self.config["offset"]) / self.config["units"]
            if not self.simulation:
                if not self._checkConnection():
                    return self.getPos()
                speed = kwargs.get("speed", self.velocity)
                speed_counts = abs(speed / self.config["units"]) if speed else None
                self.moving = True
                self.err, retStr = self.controller.moveTo(
                    self.axis, counts, speed=speed_counts,
                    timeout=self.config.get("timeout", 30.0))
                self.moving = False
                if self.err != 0:
                    print(f"Error in moveTo for {self.axis}: {retStr}")
            else:
                self.controller.moving = True
                self._controller_position = counts
                self.controller.moving = False
        return self.getPos()

    def moveBy(self, step, **kwargs):
        """
        Move the motor by a relative distance (user units), blocking until complete.

        Args:
            step: Relative distance in user units
            **kwargs: May contain "speed" (user units/second) to override the slew speed

        Returns:
            float: New position after the move
        """
        if not self._checkAxis():
            return 0.0

        pos = self.getPos()
        if self.checkLimits(pos + step):
            counts = step / self.config["units"]
            if not self.simulation:
                if not self._checkConnection():
                    return pos
                speed = kwargs.get("speed", self.velocity)
                speed_counts = abs(speed / self.config["units"]) if speed else None
                self.moving = True
                self.err, retStr = self.controller.moveBy(
                    self.axis, counts, speed=speed_counts,
                    timeout=self.config.get("timeout", 30.0))
                self.moving = False
                if self.err != 0:
                    print(f"Error in moveBy for {self.axis}: {retStr}")
            else:
                self._controller_position = self._controller_position + counts
        return self.getPos()

    def stop(self):
        """
        Stop motion on this axis immediately.
        """
        if not self._checkAxis() or not self._checkConnection():
            return
        self.err, self.returnedStr = self.controller.abortMove(self.axis)
        if self.err != 0:
            print(f"Error stopping motor {self.axis}: {self.returnedStr}")
        return

    def enable(self):
        """
        Enable (servo on) this axis.

        Returns:
            bool: True if enable successful
        """
        if self.simulation:
            return True
        if not self._checkAxis() or not self._checkConnection():
            return False
        self.err, retStr = self.controller.enableAxis(self.axis)
        return self.err == 0

    def disable(self):
        """
        Disable (motor off) this axis.

        Returns:
            bool: True if disable successful
        """
        if self.simulation:
            return True
        if not self._checkAxis() or not self._checkConnection():
            return False
        self.err, retStr = self.controller.disableAxis(self.axis)
        return self.err == 0

    def home(self):
        """
        Home this axis.

        Returns:
            bool: True if homing successful
        """
        if self.simulation:
            return True
        if not self._checkAxis() or not self._checkConnection():
            return False
        self.err, retStr = self.controller.home(self.axis)
        return self.err == 0

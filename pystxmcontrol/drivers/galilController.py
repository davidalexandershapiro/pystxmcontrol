import gclib
import time
from pystxmcontrol.controller.hardwareController import hardwareController
from threading import Lock

class galilController(hardwareController):
    """
    Galil controller driver class that provides low-level hardware communication
    with Galil motion controllers through the gclib Python module (a wrapper
    around Galil's C library).

    Architecture:
    ┌─────────────────┐
    │     Motor       │  High level: Axis abstraction (galilMotor.py)
    └─────────────────┘
    ┌─────────────────┐
    │   Controller    │  Mid level: Hardware communication (this class)
    └─────────────────┘
    ┌─────────────────┐
    │     gclib       │  Low level: Galil C library wrapper (gclib.py)
    └─────────────────┘

    This class handles:
    - Ethernet connection management to Galil controllers
    - Motion control commands (move, stop, enable/disable)
    - Position and status monitoring
    - Error handling and simulation mode support

    Galil controllers are commanded with short two-letter ASCII commands sent over a
    single connection via gclib's GCommand().  Axes are addressed by letter (A-H), so
    a per-axis command is formed by appending the axis letter, e.g. ``PAA=1000`` sets
    the absolute target of axis A, ``BGA`` begins motion on A, ``STA`` stops A, and
    ``TPA`` reports the position of A.  Positions and speeds are in encoder counts and
    counts/second respectively; unit conversion to engineering units is handled in the
    motor layer (galilMotor.py).

    gclib exposes a single connection object (``self.g``), so all transactions are
    serialized with a lock.  This mirrors the per-socket locking used by the XPS driver
    and keeps concurrent readers (e.g. a position monitor) from interleaving with an
    in-flight move command on the shared connection.

    NOTE: This is a draft placeholder written before hardware was available.  The gclib
    call structure and Galil command strings follow the standard API, but command
    details (axis letters, speed scaling, homing routine) should be verified against the
    actual controller once it arrives.
    """

    def __init__(self, address = '192.168.1.100', port = 0, simulation = False):
        """
        Initialize the Galil controller object.

        The gclib connection object is None until connect() is called.

        Args:
            address: IP address (or gclib address string) of the Galil controller
            port: Unused for Ethernet Galil controllers; kept for interface symmetry
            simulation: Whether to run in simulation mode (no hardware communication)
        """

        self.address = address
        self.port = port
        self.simulation = simulation

        # Motion state tracking for status monitoring
        self.stopped = False      # Flag indicating if motion was stopped
        self.moving = False       # Flag indicating if motion is active

        # gclib connection object for hardware communication.
        # None until connect() succeeds.  See connect() for details.
        self.g = None

        # Serializes every GCommand transaction on the single shared connection.
        self.lock = Lock()

    def _checkConnection(self):
        """
        Check if the controller is connected and ready for operations.

        Returns:
            bool: True if connected and ready, False otherwise
        """
        if self.simulation:
            return True

        if self.g is None:
            print(f"Error: Not connected to Galil controller at {self.address}")
            return False

        return True

    def _command(self, command):
        """
        Send a single command to the controller and return its response.

        Holds the connection lock for the whole transaction so concurrent callers on
        the shared gclib connection cannot interleave their commands and responses.

        Args:
            command: Galil command string (e.g. "PAA=1000", "TPA")

        Returns:
            list: [error_code, response] where error_code is 0 for success, -1 for failure.
                  response is the (stripped) string returned by the controller.
        """
        if self.simulation:
            return [0, '']

        if not self._checkConnection():
            return [-1, 'Not connected']

        try:
            with self.lock:
                response = self.g.GCommand(command)
            return [0, response.strip()]
        except gclib.GclibError as e:
            print(f"Galil command error for '{command}': {e}")
            return [-1, str(e)]
        except Exception as e:
            print(f"Error sending command '{command}': {e}")
            return [-1, str(e)]

    def connect(self, IP = None, port = None, timeOut = None):
        """
        Establish connection to the Galil controller.

        gclib opens an Ethernet connection with GOpen() using an address string.  The
        ``--direct`` option connects directly to the controller (bypassing gcaps), and
        ``-s ALL`` subscribes to all unsolicited messages and data records.

        Args:
            IP: IP address (optional, uses self.address if not provided)
            port: Unused (kept for interface symmetry)
            timeOut: Connection timeout in ms (optional)

        Returns:
            int: 0 for success, -1 for failure
        """

        address = IP if IP is not None else self.address

        # Avoid redundant connections
        if self.g is not None:
            print(f"Already connected to Galil controller at {address}")
            return 0

        if self.simulation:
            print(f"Simulation mode - no actual connection to {address}")
            return 0

        try:
            print(f"Connecting to Galil controller at {address}...")
            self.g = gclib.py()
            self.g.GOpen(f"{address} --direct -s ALL")
            if timeOut is not None:
                self.g.GTimeout(int(timeOut))
            print(self.g.GInfo())
            print(f"Galil controller connected at {address}")
            return 0
        except gclib.GclibError as e:
            print(f"Galil controller error connecting to {address}: {e}")
            self.g = None
            return -1
        except Exception as e:
            print(f"Failed to connect to Galil controller at {address}: {e}")
            self.g = None
            return -1

    def disconnect(self):
        """
        Disconnect from the Galil controller and release the gclib connection.

        Returns:
            int: 0 for success, -1 for failure
        """
        if self.simulation:
            print(f"Simulation mode - no actual disconnection from {self.address}")
            return 0

        if self.g is None:
            print(f"Not connected to Galil controller at {self.address}")
            return 0

        try:
            self.g.GClose()
            self.g = None
            print(f"Galil controller disconnected from {self.address}")
            return 0
        except Exception as e:
            print(f"Error disconnecting from Galil controller at {self.address}: {e}")
            self.g = None
            return -1

    def initialize(self, simulation = False):
        """
        Initialize the controller object and connect to the hardware.

        Args:
            simulation: Whether to run in simulation mode

        Returns:
            int: 0 for success
        """
        self.simulation = simulation
        self.connect(self.address, self.port)
        print("Galil controller initialized")
        return 0

    def isConnected(self):
        """
        Check if the controller is connected and ready.

        Returns:
            bool: True if connected and ready, False otherwise
        """
        return self._checkConnection()

    def getPosition(self, motor):
        """
        Get the current (encoder) position of the specified axis.

        Uses the Galil ``TP`` (Tell Position) command for the axis, e.g. ``TPA``.

        Args:
            motor: Axis letter (e.g. "A")

        Returns:
            list: [error_code, position] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            return [0, 0.0]

        if not self._checkConnection():
            return [-1, 0.0]

        err, response = self._command(f"TP{motor}")
        if err != 0:
            return [-1, 0.0]
        try:
            return [0, float(response)]
        except ValueError:
            print(f"Could not parse position for {motor}: '{response}'")
            return [-1, 0.0]

    def setAxisSpeed(self, motor, speed):
        """
        Set the slew speed for an axis using the Galil ``SP`` command (counts/second).

        Args:
            motor: Axis letter to configure
            speed: Speed in counts/second

        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            return [0, f'Axis speed set to {speed} (simulation)']

        err, response = self._command(f"SP{motor}={int(speed)}")
        if err != 0:
            return [-1, response]
        return [0, 'Axis speed updated successfully']

    def getAxisSpeed(self, motor):
        """
        Get the current slew speed for an axis (counts/second).

        Args:
            motor: Axis letter to query

        Returns:
            list: [error_code, speed] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            return [0, 0.0]

        err, response = self._command(f"SP{motor}=?")
        if err != 0:
            return [-1, 0.0]
        try:
            return [0, float(response)]
        except ValueError:
            return [-1, 0.0]

    def enableAxis(self, axis):
        """
        Enable (servo on) the specified axis using the Galil ``SH`` command.

        Args:
            axis: Axis letter to enable

        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            return [0, 'Axis enabled (simulation)']

        err, response = self._command(f"SH{axis}")
        if err != 0:
            return [-1, response]
        print(f"Axis {axis} enabled (servo on)")
        return [0, "OK"]

    def disableAxis(self, axis):
        """
        Disable (motor off) the specified axis using the Galil ``MO`` command.

        Args:
            axis: Axis letter to disable

        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            return [0, 'Axis disabled (simulation)']

        err, response = self._command(f"MO{axis}")
        if err != 0:
            return [-1, response]
        print(f"Axis {axis} disabled (motor off)")
        return [0, "OK"]

    def abortMove(self, motor):
        """
        Stop motion on the specified axis immediately using the Galil ``ST`` command.

        Args:
            motor: Axis letter to stop

        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            self.moving = False
            return [0, 'Move aborted (simulation)']

        err, response = self._command(f"ST{motor}")
        self.moving = False
        if err != 0:
            return [-1, response]
        return [0, 'Move aborted']

    def _waitForMotion(self, motor, timeout):
        """
        Block until motion on the axis completes, the move is stopped, or a timeout fires.

        gclib's GMotionComplete() blocks until the profiler reports the move done.  It is
        called under the connection lock; for responsiveness to stop()/timeout this driver
        instead polls the ``_BGn`` operand (1 while axis n is profiling motion).

        Args:
            motor: Axis letter being moved
            timeout: Maximum seconds to wait before aborting

        Returns:
            list: [error_code, message]
        """
        t0 = time.time()
        while self.moving:
            if self.stopped:
                self.stopped = False
                return self.abortMove(motor)

            err, response = self._command(f"MG _BG{motor}")
            if err != 0:
                self.moving = False
                return [-1, response]

            try:
                in_motion = float(response) != 0.0
            except ValueError:
                in_motion = False

            if not in_motion:
                self.moving = False
                return [0, 'Move completed']

            if (time.time() - t0) > timeout:
                print(f"Galil move timeout for {motor}. Aborting...")
                return self.abortMove(motor)

            time.sleep(0.01)

        return [0, 'Move completed']

    def moveTo(self, motor, target, speed=None, timeout=30.0):
        """
        Move an axis to an absolute (encoder) position with blocking behavior.

        Issues ``PA<axis>=target`` followed by ``BG<axis>`` then polls until motion
        completes.  Position is in encoder counts; unit conversion is done by the motor.

        Args:
            motor: Axis letter to move
            target: Absolute target position in counts
            speed: Optional slew speed in counts/second
            timeout: Maximum seconds to wait for the move

        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            self.moving = True
            time.sleep(0.1)
            self.moving = False
            return [0, 'Move completed (simulation)']

        if not self._checkConnection():
            return [-1, 'Not connected']

        if speed is not None:
            result = self.setAxisSpeed(motor, speed)
            if result[0] != 0:
                return result

        err, response = self._command(f"PA{motor}={int(round(target))}")
        if err != 0:
            return [-1, response]
        err, response = self._command(f"BG{motor}")
        if err != 0:
            return [-1, response]

        self.moving = True
        return self._waitForMotion(motor, timeout)

    def moveBy(self, motor, displacement, speed=None, timeout=30.0):
        """
        Move an axis by a relative (encoder) distance with blocking behavior.

        Issues ``PR<axis>=displacement`` followed by ``BG<axis>`` then polls until
        motion completes.

        Args:
            motor: Axis letter to move
            displacement: Relative distance in counts
            speed: Optional slew speed in counts/second
            timeout: Maximum seconds to wait for the move

        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            self.moving = True
            time.sleep(0.1)
            self.moving = False
            return [0, 'Relative move completed (simulation)']

        if not self._checkConnection():
            return [-1, 'Not connected']

        if speed is not None:
            result = self.setAxisSpeed(motor, speed)
            if result[0] != 0:
                return result

        err, response = self._command(f"PR{motor}={int(round(displacement))}")
        if err != 0:
            return [-1, response]
        err, response = self._command(f"BG{motor}")
        if err != 0:
            return [-1, response]

        self.moving = True
        return self._waitForMotion(motor, timeout)

    def home(self, motor, timeout=120.0):
        """
        Home the axis using the Galil ``HM``/``BG`` homing sequence.

        Args:
            motor: Axis letter to home
            timeout: Maximum seconds to wait for the homing move

        Returns:
            list: [error_code, message] where error_code is 0 for success, -1 for failure
        """
        if self.simulation:
            return [0, 'Axis homed (simulation)']

        if not self._checkConnection():
            return [-1, 'Not connected']

        err, response = self._command(f"HM{motor}")
        if err != 0:
            return [-1, response]
        err, response = self._command(f"BG{motor}")
        if err != 0:
            return [-1, response]

        self.moving = True
        return self._waitForMotion(motor, timeout)

    def start(self):
        """
        Start the controller.  Galil controllers begin operating on connection, so this
        is a no-op kept for interface symmetry with the other controller drivers.

        Returns:
            int: 0 for success
        """
        return 0

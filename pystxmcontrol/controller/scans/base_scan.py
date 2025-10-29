"""
Abstract base class for STXM scan routines.

This module provides a base class that encapsulates common functionality
shared across different scan types (line scans, focus scans, point scans, etc.).
"""

from abc import ABC, abstractmethod
from typing import Dict, Tuple, Optional, Any
import numpy as np


class BaseScan(ABC):
    """
    Abstract base class for STXM scan implementations.

    This class provides common functionality for:
    - DAQ configuration and metadata management
    - Motor positioning and trajectory setup
    - Energy handling and focus control
    - Coarse/fine motor coordination
    - Scan region management

    Subclasses must implement:
    - execute_scan(): Main scan execution logic
    - setup_scan_geometry(): Scan-specific geometric setup
    """

    def __init__(self, scan: Dict, dataHandler, controller, queue):
        """
        Initialize base scan.

        :param scan: Scan parameter dictionary
        :param dataHandler: Data handler instance
        :param controller: Controller instance
        :param queue: Async queue for scan control
        """
        self.scan = scan
        self.dataHandler = dataHandler
        self.controller = controller
        self.queue = queue
        self.scanInfo = {}

    async def run(self) -> bool:
        """
        Main entry point for scan execution.

        :return: True if scan completed successfully, False otherwise
        """
        await self.scan["synch_event"].wait()

        # Initialize scan info
        await self.initialize_scan_info()

        # Setup DAQs
        self.setup_daqs()

        # Execute the scan
        return await self.execute_scan()

    async def initialize_scan_info(self):
        """Initialize common scanInfo dictionary with scan parameters."""
        self.scanInfo = {
            "scan": self.scan,
            "type": self.scan["scan_type"],
            "daq list": self.scan.get("daq list", ["default"]),
            "direction": "forward",
            "rawData": {}
        }

    def setup_daqs(self):
        """
        Setup DAQ configurations and metadata.

        This method initializes DAQ metadata, determines timing parameters,
        and sets up interpolation flags based on oversampling settings.
        """
        energies = self.dataHandler.data.energies.get("default", [])

        # Initialize rawData structure for each DAQ
        for daq in self.scanInfo["daq list"]:
            daq_meta = self.controller.daq[daq].meta
            self.scanInfo["rawData"][daq] = {
                "meta": daq_meta,
                "data": None
            }

            # Set n_energies based on DAQ type
            if daq_meta["type"] == "spectrum":
                self.scanInfo["rawData"][daq]["meta"]["n_energies"] = len(daq_meta["x"])
            else:
                self.scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)

            # Determine if interpolation is needed
            oversampling = daq_meta.get("oversampling_factor", 1)
            include_return = self.scanInfo.get("include_return", False)
            self.scanInfo["rawData"][daq]["interpolate"] = (oversampling > 1) or include_return

    def get_daq_timing_parameters(self) -> Tuple[float, float, float]:
        """
        Calculate DAQ timing parameters from attached DAQs.

        :return: (min_dwell, dwell_pad, time_resolution) tuple
        """
        daq_list = self.scanInfo["daq list"]

        # Find minimum dwell from non-simulation DAQs
        min_dwell = max([
            float(self.scanInfo["rawData"][daq]["meta"]["minimum dwell"])
            for daq in daq_list
            if not self.scanInfo["rawData"][daq]["meta"]["simulation"]
        ] + [0.001])

        # Find maximum dwell padding
        dwell_pad = max([
            float(self.scanInfo["rawData"][daq]["meta"]["dwell pad"])
            for daq in daq_list
            if not self.scanInfo["rawData"][daq]["meta"]["simulation"]
        ] + [0.0])

        # Find worst time resolution
        time_resolution = max([
            float(self.scanInfo["rawData"][daq]["meta"]["time resolution"])
            for daq in daq_list
            if not self.scanInfo["rawData"][daq]["meta"]["simulation"]
        ] + [0.001])

        return min_dwell, dwell_pad, time_resolution

    def calculate_actual_dwell(self, requested_dwell: float,
                               min_motor_dwell: float = 0.12,
                               max_motor_dwell: float = 5.0) -> Tuple[float, float]:
        """
        Calculate actual DAQ and motor dwell times based on constraints.

        :param requested_dwell: Requested dwell time in ms
        :param min_motor_dwell: Minimum motor dwell in ms
        :param max_motor_dwell: Maximum motor dwell in ms
        :return: (daq_dwell, motor_dwell) tuple in ms
        """
        min_daq_dwell, dwell_pad, time_resolution = self.get_daq_timing_parameters()

        # Constrain requested dwell
        req_daq_dwell = min(
            max_motor_dwell - dwell_pad,
            max(min_daq_dwell, min_motor_dwell, requested_dwell)
        )

        # Quantize to time resolution
        actual_daq_dwell = np.floor(req_daq_dwell / time_resolution) * time_resolution
        actual_motor_dwell = actual_daq_dwell + time_resolution

        return actual_daq_dwell, actual_motor_dwell

    def setup_motor_trajectory(self, motor_name: str,
                               start_pos: Tuple[float, float],
                               stop_pos: Tuple[float, float],
                               pixel_count: int,
                               pixel_dwell: float,
                               line_mode: str = "continuous",
                               include_return: bool = False):
        """
        Configure motor trajectory parameters.

        :param motor_name: Name of the motor
        :param start_pos: (x, y) start position in fine coordinates
        :param stop_pos: (x, y) stop position in fine coordinates
        :param pixel_count: Number of pixels in trajectory
        :param pixel_dwell: Dwell time per pixel in ms
        :param line_mode: Trajectory mode ('continuous' or other)
        :param include_return: Whether to include return trajectory
        """
        motor = self.controller.motors[motor_name]["motor"]
        motor.trajectory_start = start_pos
        motor.trajectory_stop = stop_pos
        motor.trajectory_pixel_count = pixel_count
        motor.trajectory_pixel_dwell = pixel_dwell
        motor.lineMode = line_mode
        motor.update_trajectory(include_return=include_return)

    def move_coarse_to_range(self, x_motor: str, y_motor: str,
                            x_start: float, x_stop: float,
                            y_start: float, y_stop: float) -> Tuple[float, float]:
        """
        Move coarse motors to bring scan range into fine motor range.

        :param x_motor: Name of X motor
        :param y_motor: Name of Y motor
        :param x_start: X start position (global coordinates)
        :param x_stop: X stop position (global coordinates)
        :param y_start: Y start position (global coordinates)
        :param y_stop: Y stop position (global coordinates)
        :return: (x_coarse_offset, y_coarse_offset) tuple
        """
        # Move coarse motors if needed
        self.controller.motors[x_motor]["motor"].move_coarse_to_fine_range(x_start, x_stop)
        self.controller.motors[y_motor]["motor"].move_coarse_to_fine_range(y_start, y_stop)

        # Decompose ranges to get coarse offsets
        _, x_coarse, _, _ = self.controller.motors[x_motor]["motor"].decompose_range(x_start, x_stop)
        _, y_coarse, _, _ = self.controller.motors[y_motor]["motor"].decompose_range(y_start, y_stop)

        return x_coarse, y_coarse

    def handle_energy_and_focus(self, energy: float,
                               energy_motor: str = "Energy",
                               move_energy: bool = True):
        """
        Handle energy change and automatic focus adjustment.

        :param energy: Target energy value
        :param energy_motor: Name of energy motor
        :param move_energy: Whether to move energy motor
        """
        if move_energy:
            self.controller.moveMotor(energy_motor, energy)

        # Handle autofocus if enabled
        if self.scan.get("autofocus", False):
            calibrated_pos = self.controller.motors["Energy"]["motor"].calibratedPosition
            self.controller.moveMotor("ZonePlateZ", calibrated_pos)

    def setup_position_trigger(self, motor_name: str,
                               trigger_position: Optional[float] = None):
        """
        Setup position trigger on specified motor.

        :param motor_name: Name of motor to trigger on
        :param trigger_position: Trigger position (if None, uses trajectory_trigger)
        """
        motor = self.controller.motors[motor_name]["motor"]
        trigger_axis = motor.trigger_axis

        if trigger_position is None:
            trigger_position = motor.trajectory_trigger[trigger_axis - 1]

        motor.setPositionTriggerOn(pos=trigger_position)

        return trigger_axis, trigger_position

    def disable_position_trigger(self, motor_name: str):
        """
        Disable position trigger on specified motor.

        :param motor_name: Name of motor
        """
        self.controller.motors[motor_name]["motor"].setPositionTriggerOff()

    def update_motor_positions(self, region_index: int = 0):
        """
        Get current motor positions and store in data handler.

        :param region_index: Region index for storing positions
        """
        self.controller.getMotorPositions()
        self.dataHandler.data.motorPositions[region_index] = self.controller.allMotorPositions
        self.scanInfo["motorPositions"] = self.controller.allMotorPositions

    async def check_abort(self) -> bool:
        """
        Check if scan abort has been requested.

        :return: True if abort requested, False otherwise
        """
        return not self.queue.empty()

    async def handle_abort(self, region_index: int, motor_name: str,
                          message: str = "Scan aborted.") -> bool:
        """
        Handle scan abort request.

        :param region_index: Current region index
        :param motor_name: Name of motor to disable trigger on
        :param message: Abort message
        :return: False to indicate scan termination
        """
        from pystxmcontrol.controller.scans.scan_utils import terminateFlyscan

        await self.queue.get()
        self.dataHandler.data.saveRegion(region_index)
        return await terminateFlyscan(self.controller, self.dataHandler,
                                     self.scan, motor_name, message)

    def configure_daqs(self, dwell: float, count: int, samples: int,
                      trigger: str = "EXT"):
        """
        Configure all DAQs with specified parameters.

        :param dwell: Dwell time in ms
        :param count: Number of acquisitions
        :param samples: Number of samples per acquisition
        :param trigger: Trigger type ('EXT', 'BUS', etc.)
        """
        self.controller.config_daqs(dwell=dwell, count=count,
                                   samples=samples, trigger=trigger)

    def get_scan_region_geometry(self, region_index: int = 0) -> Dict[str, Any]:
        """
        Extract scan region geometry parameters.

        :param region_index: Index of scan region
        :return: Dictionary with geometry parameters
        """
        xPos = self.dataHandler.data.xPos[region_index]
        yPos = self.dataHandler.data.yPos[region_index]

        x_start, x_stop = xPos[0], xPos[-1]
        y_start, y_stop = yPos[0], yPos[-1]
        x_range = x_stop - x_start
        y_range = y_stop - y_start
        x_points = len(xPos)
        y_points = len(yPos)
        x_step = x_range / (x_points - 1) if x_points > 1 else 0
        y_step = y_range / (y_points - 1) if y_points > 1 else 0

        return {
            "xPos": xPos,
            "yPos": yPos,
            "xStart": x_start,
            "xStop": x_stop,
            "yStart": y_start,
            "yStop": y_stop,
            "xRange": x_range,
            "yRange": y_range,
            "xPoints": x_points,
            "yPoints": y_points,
            "xStep": x_step,
            "yStep": y_step,
            "xCenter": x_start + x_range / 2.0,
            "yCenter": y_start + y_range / 2.0,
        }

    @abstractmethod
    async def execute_scan(self) -> bool:
        """
        Execute the scan (must be implemented by subclasses).

        :return: True if scan completed successfully, False otherwise
        """
        pass

    def setup_scan_geometry(self):
        """
        Setup scan-specific geometry (optional override for subclasses).

        This should configure trajectory, motor positions, and any
        scan-type-specific parameters. Default implementation does nothing.
        """
        pass

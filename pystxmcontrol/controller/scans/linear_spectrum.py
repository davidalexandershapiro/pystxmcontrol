"""
Refactored derived line spectrum scan using BaseScan abstract class.

This is a continuous flyscan spectrum scan that uses the linear trajectory
function on the controller. It moves coarse motors to the center of the
scan range and executes a fine scan smaller than the max piezo scan range.
"""

from pystxmcontrol.controller.scans.base_scan import BaseScan
from pystxmcontrol.controller.scans.scan_utils import doFlyscanLine, terminateFlyscan
from numpy import ones
from time import sleep

class LinearSpectrumScan(BaseScan):
    """
    Continuous flyscan line spectrum scan implementation.

    Features:
    - Multi-region scanning
    - Multi-energy support
    - Coarse/fine motor coordination
    - Automatic spectrum control
    - Position-triggered data acquisition
    """

    async def initialize_scan_info(self):
        """Initialize scan-specific parameters."""
        await super().initialize_scan_info()

        # Add line scan specific parameters
        self.scanInfo.update({
            "mode": "continuousLine",
            "oversampling_factor": self.controller.daq["default"].meta["oversampling_factor"],
            "totalSplit": None,
            "coarse_only": self.scan.get("coarse_only", False),
            "include_return": self.controller.scanConfig["scans"][self.scan["scan_type"]]["include_return"]
        })

    async def execute_scan(self) -> bool:
        """
        Execute the line spectrum scan.

        Loops through:
        1. Energies
        2. Scan regions
        3. Y positions (lines)

        :return: True if scan completed successfully
        """
        energies = self.dataHandler.data.energies["default"]
        n_scan_regions = len(self.dataHandler.data.xPos)

        for energy_index, energy in enumerate(energies):
            # Handle energy and timing
            success = await self.process_energy(energy, energy_index, energies)
            if not success:
                return False

            # Process each scan region
            for region_index in range(n_scan_regions):
                success = await self.process_region(region_index, energy, energy_index, energies)
                if not success:
                    return False

                # Signal end of region
                await self.dataHandler.dataQueue.put('endOfRegion')

        # Scan completed successfully
        return await terminateFlyscan(self.controller, self.dataHandler,
                                     self.scan, "x_motor", "Flyscan completed.")

    async def process_energy(self, energy: float, energy_index: int,
                           energies: list) -> bool:  # noqa: ARG002
        """
        Process energy change and calculate timing parameters.

        :param energy: Target energy
        :param energy_index: Index of energy in energy list
        :param energies: List of all energies
        :return: True if successful
        """
        # Calculate actual dwell times
        requested_dwell = self.dataHandler.data.dwells[energy_index]
        actual_daq_dwell, actual_motor_dwell = self.calculate_actual_dwell(requested_dwell)

        # Update scan info for this energy
        self.scanInfo["energy"] = energy
        self.scanInfo["energyIndex"] = energy_index
        self.scanInfo["dwell"] = actual_daq_dwell

        # Move energy motor if multi-energy scan
        if len(energies) > 1:
            #this also moves the zone plate to the focus position
            self.controller.moveMotor(self.scan["energy_motor"], energy)
        else:
            # Single energy - just handle autofocus
            if self.scan.get("autofocus", False):
                calibrated_pos = self.controller.motors["Energy"]["motor"].calibratedPosition
                self.controller.moveMotor("ZonePlateZ", calibrated_pos)

        # Store motor dwell for trajectory setup
        self.scanInfo["_motor_dwell"] = actual_motor_dwell

        return True

    async def process_region(self, region_index: int, energy: float,
                           energy_index: int, energies: list) -> bool:
        """
        Process a single scan region.

        :param region_index: Index of scan region
        :param energy: Current energy value
        :param energy_index: Index of energy
        :param energies: List of all energies
        :return: True if successful
        """
        # Get scan region geometry
        geometry = self.get_scan_region_geometry(region_index)

        # Update scanInfo with region geometry
        self.scanInfo.update({
            "scanRegion": f"Region{region_index + 1}",
            "xPoints": geometry["xPoints"],
            "xStep": geometry["xStep"],
            "xStart": geometry["xStart"],
            "xCenter": geometry["xCenter"],
            "xRange": geometry["xRange"],
            "yPoints": geometry["yPoints"],
            "yStep": geometry["yStep"],
            "yStart": geometry["yStart"],
            "yCenter": geometry["yCenter"],
            "yRange": geometry["yRange"],
            "zPoints": geometry["zPoints"],
            "zStep": geometry["zStep"],
            "zStart": geometry["zStart"],
            "zCenter": geometry["zCenter"],
            "zRange": geometry["zRange"]
        })

        # Setup motors and trajectory for this region
        self.setup_region_geometry(geometry, region_index)

        # Calculate number of points
        num_line_motor_points = self.controller.motors[self.scan["x_motor"]]["motor"].npositions
        self.scanInfo["numLineDAQPoints"] = num_line_motor_points * self.scanInfo["oversampling_factor"]
        self.scanInfo["numMotorPoints"] = num_line_motor_points * geometry["yPoints"]
        self.scanInfo["numDAQPoints"] = self.scanInfo["numMotorPoints"] * self.scanInfo["oversampling_factor"]

        # Update data arrays on first energy
        if energy == energies[0]:
            self.dataHandler.data.updateArrays(region_index, self.scanInfo)

        # Configure DAQs
        self.configure_daqs(
            dwell=self.scanInfo["dwell"],
            count=1,
            samples=self.scanInfo["numLineDAQPoints"],
            trigger="EXT"
        )

        # Move to start position
        await self.move_to_start_position(geometry, region_index)

        # Setup position trigger
        trigger_axis, _ = self.setup_position_trigger(self.scan["x_motor"])
        self.scanInfo["trigger_axis"] = trigger_axis

        # Scan all Y lines
        success = await self.scan_spectrum_lines(geometry, num_line_motor_points, region_index)

        return success

    def setup_region_geometry(self, geometry: dict, region_index: int):  # noqa: ARG002
        """
        Setup motor trajectories and positions for scan region.

        :param geometry: Region geometry dictionary
        :param region_index: Index of scan region
        """
        x_motor_name = self.scan["x_motor"]
        y_motor_name = self.scan["y_motor"]
        coarse_only = self.scanInfo["coarse_only"]
        coarse_offset = 20  # Should be in config

        # Move coarse motors to position range in fine motor range
        x_coarse, y_coarse = self.move_coarse_to_range(
            x_motor_name, y_motor_name,
            geometry["xStart"], geometry["xStop"],
            geometry["yStart"], geometry["yStop"]
        )

        # Override coarse for coarse-only scans
        if coarse_only:
            x_coarse, y_coarse = 0.0, 0.0

        self.scanInfo["offset"] = (x_coarse, y_coarse)

        # Decompose ranges to get fine coordinates
        _, _, x_start_fine, x_stop_fine = \
            self.controller.motors[x_motor_name]["motor"].decompose_range(
                geometry["xStart"], geometry["xStop"]
            )
        _, _, y_start_fine, _ = \
            self.controller.motors[y_motor_name]["motor"].decompose_range(
                geometry["yStart"], geometry["yStop"]
            )

        # Setup trajectory
        motor = self.controller.motors[x_motor_name]["motor"]

        # Calculate pixel dwell from motor dwell
        pixel_dwell = self.scanInfo["_motor_dwell"] / self.scanInfo["oversampling_factor"]

        if not coarse_only:
            # Fine motor trajectory
            self.setup_motor_trajectory(
                x_motor_name,
                start_pos=(x_start_fine, y_start_fine),
                stop_pos=(x_stop_fine, y_start_fine),
                pixel_count=geometry["xPoints"],
                pixel_dwell=pixel_dwell,
                line_mode="continuous",
                include_return=self.scanInfo["include_return"]
            )
        else:
            # Coarse-only trajectory
            start_x = geometry["xStart"] - coarse_offset
            start_y = geometry["yStart"]

            # Move motors for coarse-only scan
            self.controller.moveMotor(x_motor_name, start_x, coarse_only=True)
            self.controller.moveMotor(y_motor_name, start_y)

            # Setup trajectory with trigger offsets
            motor.trajectory_start = (geometry["xStart"] - coarse_offset, geometry["yPos"][0])
            motor.trajectory_stop = (geometry["xStop"] + coarse_offset, geometry["yPos"][0])
            motor.trajectory_pixel_count = geometry["xPoints"]
            motor.trajectory_pixel_dwell = pixel_dwell
            motor.lineMode = "continuous"
            motor.update_trajectory(include_return=False)
            motor.trajectory_trigger = (coarse_offset, coarse_offset)

    async def move_to_start_position(self, geometry: dict, region_index: int):  # noqa: ARG002
        """
        Move motors to scan start position.

        :param geometry: Region geometry dictionary
        :param region_index: Index of scan region
        """
        coarse_only = self.scanInfo["coarse_only"]
        x_motor_name = self.scan["x_motor"]
        y_motor_name = self.scan["y_motor"]
        motor = self.controller.motors[x_motor_name]["motor"]

        # Calculate start position with padding
        start_x = motor.trajectory_start[0] - motor.xpad
        start_y = motor.trajectory_start[1] - motor.ypad

        self.scanInfo["start_position_x"] = start_x
        self.scanInfo["start_position_y"] = start_y
        self.scanInfo["xpad"] = motor.xpad
        self.scanInfo["ypad"] = motor.ypad

        # Get coarse offset
        x_coarse, y_coarse = self.scanInfo["offset"]

        # Move to start position (global coordinates)
        # Force both moves to use coarse motors to reset both piezos for large scans
        self.controller.moveMotor(x_motor_name, x_coarse + start_x, coarse_only = coarse_only)
        self.controller.moveMotor(y_motor_name, y_coarse + start_y, coarse_only = coarse_only)

        sleep(0.1)  # Allow settling

    async def scan_spectrum_lines(self, geometry: dict, num_line_motor_points: int,
                          region_index: int) -> bool:
        """
        Scan all Y lines in the region.

        :param geometry: Region geometry dictionary
        :param num_line_motor_points: Number of motor points per line
        :param region_index: Index of scan region
        :return: True if successful
        """
        coarse_only = self.scanInfo["coarse_only"]
        x_motor_name = self.scan["x_motor"]
        y_motor_name = self.scan["y_motor"]
        x_coarse, y_coarse = self.scanInfo["offset"]
        start_x = self.scanInfo["start_position_x"]
        start_y = self.scanInfo["start_position_y"]
        wait_time = 0.005 + geometry["xPoints"] * 0.0001

        if await self.check_abort():
            return await self.handle_abort(region_index, "x_motor", "Flyscan aborted.")

        # Move to line position
        #Force the vertical move to use coarse motors for large scans
        self.controller.moveMotor(x_motor_name, x_coarse + start_x)
        self.controller.moveMotor(y_motor_name, y_coarse + start_y)

        # Update motor positions
        self.update_motor_positions(region_index)

        # Update scanInfo for this line
        self.scanInfo.update({
            "index": 0,
            "lineIndex": 0,
            "zIndex": 0,
            "zVal": geometry["zPos"],
            "xVal": geometry["xPos"],
            "yVal": geometry["yPos"]
        })

        # Execute flyscan line
        success = await doFlyscanLine(
            self.controller, self.dataHandler,
            self.scan, self.scanInfo, wait_time
        )

        if not success:
            # Trigger missed - skip line with zeros in data
            # Could add retry logic here if desired
            pass

        return True


async def linear_spectrum(scan, dataHandler, controller, queue):
    """
    Entry point for linear spectrum scan using derived motors(v2 using BaseScan).

    :param scan: Scan parameter dictionary
    :param dataHandler: Data handler instance
    :param controller: Controller instance
    :param queue: Async queue for scan control
    :return: Scan completion status
    """
    scan_instance = LinearSpectrumScan(scan, dataHandler, controller, queue)
    return await scan_instance.run()


# Maintain backward compatibility
async def derived_line_spectrum(scan, dataHandler, controller, queue):
    """
    Legacy entry point - redirects to v2 implementation.
    """
    return await linear_spectrum(scan, dataHandler, controller, queue)

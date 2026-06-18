"""
OSA focus scan (point and continuous line modes) using BaseScan abstract class.

Steps ZonePlateZ through focus positions (outer loop) and either steps X+Y
point-by-point (mode="point") or runs a continuous fly-scan along X for each
Z step (mode="continuousLine"). ZonePlateZ positions are offset by -A0 so that
the zone plate is focused on the OSA rather than the sample.
"""

import asyncio
import numpy as np
from pystxmcontrol.controller.scans.base_scan import BaseScan


class OsaFocusScan(BaseScan):
    """
    OSA focus scan implementation.

    ZonePlateZ is the outer (row) axis; X is the inner (column) axis.
    Y moves in lock-step with X in point mode (1-D path along the OSA),
    and is fixed in continuousLine mode.

    Point mode       — storage_pattern "double_motor_point":
                       data stored at interp_counts[daq][k][0, z_idx, col].
    Continuous mode  — storage_pattern "2d_line":
                       interpolated data stored at interp_counts[daq][k][0, z_idx, :].
    """

    async def initialize_scan_info(self):
        await super().initialize_scan_info()
        mode = self.scan["mode"]
        self.scanInfo.update({
            "mode": mode,
            "storage_pattern": "double_motor_point" if mode == "point" else "2d_line",
            "zIndex": 0,
            "energyIndex": 0,
            "direction": "forward",
        })

    def setup_daqs(self):
        super().setup_daqs()
        for daq in self.scanInfo["daq_list"]:
            self.scanInfo["rawData"][daq]["interpolate"] = False

    async def execute_scan(self) -> bool:
        energies = self.dataHandler.data.energies["default"]
        mode = self.scan["mode"]

        geom = self.get_scan_region_geometry(0)
        x, y, z = geom["xPos"], geom["yPos"], geom["zPos"]
        xStart, xStop = geom["xStart"], geom["xStop"]
        xRange = geom["xRange"]
        xPoints, zPoints = geom["xPoints"], geom["zPoints"]
        xStep = geom["xStep"]
        # ZonePlateZ is the outer/row axis and is what the image displays vertically, so the
        # y-display geometry must describe Z (zCenter/zRange/zStep/zStart), NOT OSA_Y. OSA_Y is
        # fixed for a focus line scan (yRange≈0), so using it collapses the display axis to ~0.
        zStart, zCenter = geom["zStart"], geom["zCenter"]
        zRange, zStep = geom["zRange"], geom["zStep"]

        # Move ZonePlateZ to focus on the OSA (not the sample)
        A0 = self.controller.motors["Energy"]["motor"].config["A0"]
        self.controller.moveMotor(
            "ZonePlateZ",
            self.controller.motors["Energy"]["motor"].calibratedPosition - A0
        )

        self.scanInfo.update({
            "energy":    energies[0],
            "dwell":     self.dataHandler.data.dwells[0],
            "scanRegion": "Region1",
            "xPoints":   xPoints,
            "xStep":     xStep,
            "xStart":    xStart,
            "xCenter":   xStart + xRange / 2.,
            "xRange":    xRange,
            "yPoints":   zPoints,   # Z is the outer/row axis for display
            "yStep":     zStep,
            "yStart":    zStart,
            "yCenter":   zCenter,
            "yRange":    zRange,
        })

        velocity = None
        if mode == "continuousLine":
            velocity = xStep / self.scanInfo["dwell"]
            self.controller.motors[self.scan["x_motor"]]["motor"].setAxisParams(velocity)
            self.scanInfo.update({
                "numMotorPoints": xPoints * zPoints,
                "numDAQPoints":   xPoints * zPoints,
            })
            for daq in self.scanInfo["daq_list"]:
                meta = self.scanInfo["rawData"][daq]["meta"]
                meta["n_energies"] = (len(meta["x"]) if meta["type"] == "spectrum"
                                      else len(energies))

        self.dataHandler.data.updateArrays(0, self.scanInfo)

        samples = xPoints if mode == "continuousLine" else 1
        self.configure_daqs(dwell=self.scanInfo["dwell"], count=1,
                            samples=samples, trigger="BUS")
        # The physical line runs along X at the fixed OSA_Y position (y[0]); this is the OSA_Y
        # motor coordinate, distinct from the Z value carried in the y-display fields above.
        self.scanInfo["line_positions"] = [
            np.linspace(xStart, xStop, samples),
            np.ones(samples) * y[0],
        ]

        # Position Y motor at the start of the OSA path
        self.controller.moveMotor(self.scan["y_motor"], y[0])

        if mode == "point":
            success = await self._scan_point_z(x, y, z, A0)
        else:
            success = await self._scan_continuous_z(x, z, xStart, xStop, xPoints,
                                                    velocity, A0)

        if not success:
            return False

        await self.dataHandler.dataQueue.put("endOfScan")
        await asyncio.sleep(0.1)
        self.dataHandler.data.saveRegion(0)
        return True

    async def _scan_point_z(self, x, y, z, A0) -> bool:
        """Outer Z loop with point-by-point X+Y inner loop."""
        for i, z_pos in enumerate(z):
            self.controller.moveMotor("ZonePlateZ", z_pos - A0)
            self.update_motor_positions(0)
            self.scanInfo["lineIndex"] = i
            for j in range(len(x)):
                self.controller.moveMotor(self.scan["y_motor"], y[j])
                self.controller.moveMotor(self.scan["x_motor"], x[j])
                self.scanInfo.update({
                    "columnIndex": j,
                    "index": i * len(z) + j,
                })
                if await self.check_abort():
                    await self.queue.get()
                    self.dataHandler.data.saveRegion(0)
                    await self.dataHandler.dataQueue.put("endOfScan")
                    return False
                self.controller.daq["default"].autoGateOpen(shutter=True)
                await self.dataHandler.getPoint(self.scanInfo)
                self.controller.daq["default"].autoGateClosed()
        return True

    async def _scan_continuous_z(self, x, z, xStart, xStop, xPoints,
                                  velocity, A0) -> bool:
        """Outer Z loop with fly-scan along X for each step."""
        x_motor = self.scan["x_motor"]
        return_velocity = self.controller.motors[x_motor]["motor"].config.get("return_velocity", 1)

        for i, z_pos in enumerate(z):
            self.controller.moveMotor("ZonePlateZ", z_pos - A0)
            self.update_motor_positions(0)
            self.scanInfo.update({
                "lineIndex": i,
                "index":     i * len(x),
                "direction": "forward",
            })

            # Return X to start at return velocity, then switch to scan velocity
            self.controller.motors[x_motor]["motor"].setAxisParams(return_velocity)
            self.controller.moveMotor(x_motor, xStart)
            self.controller.motors[x_motor]["motor"].setAxisParams(velocity)

            if await self.check_abort():
                await self.queue.get()
                self.dataHandler.data.saveRegion(0)
                await self.dataHandler.dataQueue.put("endOfScan")
                return False

            self.controller.daq["default"].initLine()
            self.controller.daq["default"].autoGateOpen()
            self.controller.daq["default"].bus_trigger()
            self.controller.moveMotor(x_motor, xStop)
            self.controller.daq["default"].autoGateClosed()
            try:
                await self.dataHandler.getLine(self.scanInfo.copy())
            except Exception:
                pass

        return True


async def osa_focus_scan(scan, dataHandler, controller, queue):
    """Entry point for OSA focus scan."""
    scan_instance = OsaFocusScan(scan, dataHandler, controller, queue)
    return await scan_instance.run()

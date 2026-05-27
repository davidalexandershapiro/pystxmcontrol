"""
Double motor scan (point and continuous line modes) using BaseScan abstract class.

Steps the Y motor through rows and either steps the X motor point-by-point
(mode="point") or runs a continuous fly-scan along X for each row
(mode="continuousLine").
"""

import asyncio
import numpy as np
from pystxmcontrol.controller.scans.base_scan import BaseScan


class DoubleMotorScan(BaseScan):
    """
    Two-motor scan implementation.

    Point mode   — storage_pattern "double_motor_point": raw data stored at
                   interp_counts[daq][k][0, row, col] (energy index fixed at 0).
    Line mode    — storage_pattern "2d_line": interpolated (or raw if oversampling=1)
                   data stored at interp_counts[daq][k][m, row, :] per line.
    """

    async def initialize_scan_info(self):
        await super().initialize_scan_info()
        mode = self.scan["mode"]
        self.scanInfo.update({
            "mode": mode,
            "storage_pattern": "2d_line" if mode == "continuousLine" else "double_motor_point",
            "zIndex": 0,
            "direction": "forward",
        })

    def setup_daqs(self):
        super().setup_daqs()
        # No spatial interpolation for either mode
        for daq in self.scanInfo["daq_list"]:
            self.scanInfo["rawData"][daq]["interpolate"] = False

    async def execute_scan(self) -> bool:
        energies = self.dataHandler.data.energies["default"]
        xPos = self.dataHandler.data.xPos[0]
        yPos = self.dataHandler.data.yPos[0]
        mode = self.scan["mode"]

        # Capture home position so we can restore it on completion or abort
        x_home = self.controller.allMotorPositions[self.scan["x_motor"]]
        y_home = self.controller.allMotorPositions[self.scan["y_motor"]]

        def move_home():
            self.controller.moveMotor(self.scan["x_motor"], x_home)
            self.controller.moveMotor(self.scan["y_motor"], y_home)

        refocus_offset = None
        if not self.scan.get("autofocus", False):
            current_zpz = self.controller.motors["ZonePlateZ"]["motor"].getPos()

        xStart, xStop = xPos[0], xPos[-1]
        yStart, yStop = yPos[0], yPos[-1]
        xRange = xStop - xStart
        yRange = yStop - yStart
        xPoints = len(xPos)
        yPoints = len(yPos)

        for energy_index, energy in enumerate(energies):
            self.scanInfo.update({
                "energy": energy,
                "energyIndex": energy_index,
                "dwell": self.dataHandler.data.dwells[energy_index],
                "scanRegion": "Region1",
                "xPoints": xPoints,
                "xStep": xRange / (xPoints - 1),
                "xStart": xStart,
                "xCenter": xStart + xRange / 2.,
                "xRange": xRange,
                "yPoints": yPoints,
                "yStep": yRange / (yPoints - 1),
                "yStart": yStart,
                "yCenter": yStart,
                "yRange": yRange,
            })

            if len(energies) > 1:
                self.controller.moveMotor(self.scan["energy_motor"], energy)
                if not self.scan.get("autofocus", False):
                    if energy_index == 0:
                        refocus_offset = (current_zpz -
                                          self.controller.motors["ZonePlateZ"]["motor"].calibratedPosition)
                    self.controller.moveMotor(
                        "ZonePlateZ",
                        self.controller.motors["Energy"]["motor"].calibratedPosition + refocus_offset
                    )
            else:
                if self.scan.get("autofocus", False):
                    self.controller.moveMotor(
                        "ZonePlateZ",
                        self.controller.motors["Energy"]["motor"].calibratedPosition
                    )

            if mode == "point":
                self.configure_daqs(dwell=self.scanInfo["dwell"], count=1, samples=1, trigger="BUS")
                success = await self._scan_point_rows(xPos, yPos, move_home)
            else:
                velocity = self.scanInfo["xStep"] / self.scanInfo["dwell"]
                self.controller.motors[self.scan["x_motor"]]["motor"].setAxisParams(velocity)
                self.scanInfo.update({
                    "numMotorPoints": xPoints * yPoints,
                    "numDAQPoints":   xPoints * yPoints,
                })
                # Re-apply n_energies after geometry update
                # for daq in self.controller.daq.keys():
                for daq in self.scanInfo["daq_list"]:
                    meta = self.scanInfo["rawData"][daq]["meta"]
                    meta["n_energies"] = (len(meta["x"]) if meta["type"] == "spectrum"
                                          else len(energies))
                if energy_index == 0:
                    self.dataHandler.data.updateArrays(0, self.scanInfo)
                self.configure_daqs(dwell=self.scanInfo["dwell"], count=1,
                                    samples=xPoints, trigger="BUS")
                success = await self._scan_continuous_rows(xPos, yPos, xStart, xStop,
                                                           xPoints, velocity, move_home)

            if not success:
                return False

        await self.dataHandler.dataQueue.put("endOfScan")
        await asyncio.sleep(0.1)
        self.dataHandler.data.saveRegion(0)
        move_home()
        return True

    async def _scan_point_rows(self, xPos, yPos, move_home) -> bool:
        """Inner loops for point-mode: move Y then step X, collecting one point each."""
        for row_idx, y_pos in enumerate(yPos):
            self.controller.moveMotor(self.scan["y_motor"], y_pos)
            self.controller.getMotorPositions()
            self.dataHandler.data.motorPositions[0] = self.controller.allMotorPositions
            self.scanInfo.update({
                "lineIndex": row_idx,
                "motorPositions": self.controller.allMotorPositions,
            })
            for col_idx, x_pos in enumerate(xPos):
                self.scanInfo.update({
                    "columnIndex": col_idx,
                    "index": row_idx * len(yPos) + col_idx,
                })
                self.controller.moveMotor(self.scan["x_motor"], x_pos)
                if await self.check_abort():
                    await self.queue.get()
                    self.dataHandler.data.saveRegion(0)
                    move_home()
                    await self.dataHandler.dataQueue.put("endOfScan")
                    return False
                if not await self.check_pause():
                    await self.queue.get()
                    self.dataHandler.data.saveRegion(0)
                    move_home()
                    await self.dataHandler.dataQueue.put("endOfScan")
                    return False
                self.controller.daq["default"].autoGateOpen()
                await self.dataHandler.getPoint(self.scanInfo)
                self.controller.daq["default"].autoGateClosed()
        return True

    async def _scan_continuous_rows(self, xPos, yPos, xStart, xStop,
                                    samples, velocity, move_home) -> bool:
        """Inner loop for continuousLine mode: move Y then fly-scan along X."""
        x_motor = self.scan["x_motor"]
        return_velocity = self.controller.motors[x_motor]["motor"].config.get("return_velocity", 1)

        for row_idx, y_pos in enumerate(yPos):
            self.controller.moveMotor(self.scan["y_motor"], y_pos)
            self.controller.getMotorPositions()
            self.dataHandler.data.motorPositions[0] = self.controller.allMotorPositions
            self.scanInfo.update({
                "lineIndex": row_idx,
                "index": row_idx * len(yPos),
                "direction": "forward",
                "motorPositions": self.controller.allMotorPositions,
            })

            # Return X to start at return velocity, then set scan velocity
            self.controller.motors[x_motor]["motor"].setAxisParams(return_velocity)
            self.controller.moveMotor(x_motor, xStart)
            self.controller.motors[x_motor]["motor"].setAxisParams(velocity)

            if await self.check_abort():
                await self.queue.get()
                self.dataHandler.data.saveRegion(0)
                move_home()
                await self.dataHandler.dataQueue.put("endOfScan")
                return False
            if not await self.check_pause():
                await self.queue.get()
                self.dataHandler.data.saveRegion(0)
                move_home()
                await self.dataHandler.dataQueue.put("endOfScan")
                return False

            self.controller.daq["default"].initLine()
            self.controller.daq["default"].autoGateOpen()
            self.controller.daq["default"].bus_trigger()
            self.controller.moveMotor(x_motor, xStop)
            self.controller.daq["default"].autoGateClosed()
            self.scanInfo["line_positions"] = [
                np.linspace(xStart, xStop, samples),
                np.ones(samples) * y_pos,
            ]
            try:
                await self.dataHandler.getLine(self.scanInfo.copy())
            except Exception:
                pass

        return True


async def double_motor_scan(scan, dataHandler, controller, queue):
    """Entry point for double motor scan."""
    scan_instance = DoubleMotorScan(scan, dataHandler, controller, queue)
    return await scan_instance.run()

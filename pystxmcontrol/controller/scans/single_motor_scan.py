"""
Single motor point scan using BaseScan abstract class.

Steps one motor through a range, taking a point measurement at each position.
Supports multi-energy scans (where the motor is "Energy") or single-energy
spatial scans using any configured motor.
"""

import asyncio
from pystxmcontrol.controller.scans.base_scan import BaseScan
from pystxmcontrol.controller.scans.scan_utils import set_scan_energy


class SingleMotorScan(BaseScan):
    """
    Single motor scan implementation.

    For multi-energy scans the energy motor is stepped and one point is
    collected per energy step (index stays at 0).  For spatial scans the
    x_motor is stepped and one point is collected per position.
    """

    async def initialize_scan_info(self):
        await super().initialize_scan_info()
        energies = self.dataHandler.data.energies["default"]
        self.scanInfo.update({
            "mode": "point",
            "storage_pattern": "single_motor",
            "lineIndex": 0,
            "zIndex": 0,
            "direction": "forward",
            "scanMotor": "Energy" if len(energies) > 1 else self.scan["x_motor"],
        })

    def setup_daqs(self):
        super().setup_daqs()
        # Point scan never needs interpolation
        for daq in self.scanInfo["daq_list"]:
            self.scanInfo["rawData"][daq]["interpolate"] = False

    async def execute_scan(self) -> bool:
        energies = self.dataHandler.data.energies["default"]
        xPos = self.dataHandler.data.xPos[0]
        yPos = self.dataHandler.data.yPos[0]

        refocus_offset = None
        if not self.scan.get("autofocus", False):
            current_zpz = self.controller.motors["ZonePlateZ"]["motor"].getPos()

        for energy_index, energy in enumerate(energies):
            self.controller.getMotorPositions()
            self.dataHandler.data.motorPositions[0] = self.controller.allMotorPositions
            self.scanInfo.update({
                "energy": energy,
                "energyIndex": energy_index,
                "dwell": self.dataHandler.data.dwells[energy_index],
                "motorPositions": self.controller.allMotorPositions,
            })

            # Move energy motor (deadband for single-energy) and record actual energy.
            set_scan_energy(self.controller, self.scan, self.scanInfo, energy, energies)
            if len(energies) > 1:
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

            xStart, xStop = xPos[0], xPos[-1]
            xRange = xStop - xStart
            xPoints = len(xPos)

            self.scanInfo.update({
                "scanRegion": "Region1",
                "xPoints": xPoints,
                "xStep": xRange / (xPoints - 1),
                "xStart": xStart,
                "xCenter": xStart + xRange / 2.,
                "xRange": xRange,
                "yPoints": 1,
                "yStep": 0,
                "yStart": yPos[0],
                "yCenter": yPos[0],
                "yRange": 0,
            })

            self.configure_daqs(dwell=self.scanInfo["dwell"], count=1, samples=1, trigger="BUS")

            if self.scan["x_motor"] == "Energy":
                # Energy is the scan motor: one point per energy step
                self.scanInfo.update({"scanMotorVal": energy, "index": 0, "energyIndex": energy_index})
                if await self.check_abort():
                    await self.queue.get()
                    self.dataHandler.data.saveRegion(0)
                    await self.dataHandler.dataQueue.put("endOfScan")
                    return False
                self.controller.daq["default"].autoGateOpen()
                await self.dataHandler.getPoint(self.scanInfo)
                self.controller.daq["default"].autoGateClosed()
            else:
                # Spatial motor: step through x positions
                for i, x_pos in enumerate(xPos):
                    self.scanInfo.update({"scanMotorVal": x_pos, "index": i, "energyIndex": 0})
                    self.controller.moveMotor(self.scan["x_motor"], x_pos)
                    if await self.check_abort():
                        await self.queue.get()
                        self.dataHandler.data.saveRegion(0)
                        await self.dataHandler.dataQueue.put("endOfScan")
                        return False
                    self.controller.daq["default"].autoGateOpen()
                    await self.dataHandler.getPoint(self.scanInfo)
                    self.controller.daq["default"].autoGateClosed()

        await self.dataHandler.dataQueue.put("endOfScan")
        await asyncio.sleep(0.1)
        self.dataHandler.data.saveRegion(0)
        return True


async def single_motor_scan(scan, dataHandler, controller, queue):
    """Entry point for single motor scan."""
    scan_instance = SingleMotorScan(scan, dataHandler, controller, queue)
    return await scan_instance.run()

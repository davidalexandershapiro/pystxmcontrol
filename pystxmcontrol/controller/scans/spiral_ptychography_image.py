"""
Spiral ptychography image scan using a Fermat spiral trajectory.

The scan positions fill a rectangular field of view with a Fermat (sunflower)
spiral pattern.  Compared to a raster grid, a Fermat spiral avoids the periodic
sampling artifacts that can arise from line-by-line acquisition and provides
more uniform angular coverage, which benefits ptychographic reconstruction.

Position generation
-------------------
Given a rectangular FOV of width W and height H with target probe step *s*,
the Fermat spiral positions are::

    r_n     = c * sqrt(n + 1)      n = 0, 1, 2, …
    theta_n = n * golden_angle     golden_angle ≈ 137.508° = π(3 − √5)

where *c* is chosen so that the spiral fills the circumscribed circle of the
rectangle.  Points outside the rectangle are discarded, leaving approximately
W * H / s² scan positions — the same total count as a raster grid with the same
step.

Usage in scan.json
------------------
Mirror the ``derived_ptychography_image`` entry but set::

    "driver": "spiral_ptychography_image"

All other keys (``scan_regions``, ``doubleExposure``, ``n_repeats``,
``retract``, ``outerLoop``, …) work identically.
"""

import asyncio
import datetime
import os

import numpy as np

from pystxmcontrol.controller.scans.base_scan import BaseScan
from pystxmcontrol.controller.scans.derived_ptychography_image import (
    insertSTXMDetector,
    retractSTXMDetector,
    point_loop,
)
from pystxmcontrol.utils.writeNX import stxm


# ---------------------------------------------------------------------------
# Fermat spiral geometry
# ---------------------------------------------------------------------------

_GOLDEN_ANGLE = np.pi * (3.0 - np.sqrt(5.0))   # ≈ 2.3999 rad ≈ 137.508°


def fermat_spiral_positions(
    x_center: float,
    y_center: float,
    x_range: float,
    y_range: float,
    step: float,
) -> tuple:
    """
    Generate Fermat spiral (x, y) positions that fill a rectangle.

    :param x_center: Rectangle centre in X (µm).
    :param y_center: Rectangle centre in Y (µm).
    :param x_range:  Rectangle full width in X (µm).
    :param y_range:  Rectangle full height in Y (µm).
    :param step:     Target probe step / average nearest-neighbour distance (µm).
    :returns:        ``(xp, yp)`` — 1-D arrays of accepted positions (µm).

    The spiral is scaled so that it fills the circumscribed circle of the
    rectangle.  Points outside the rectangle are rejected, so the returned
    arrays are shorter than the generated series by a factor of roughly π/4
    (for a square) up to π/4 * diagonal²/area (for a very elongated rectangle).
    """
    # Number of points needed to fill the rectangle at the given step
    n_rect = max(1, int(np.ceil(x_range * y_range / step ** 2)))

    # The spiral must reach the far corner of the rectangle
    r_max = 0.5 * np.hypot(x_range, y_range)

    # Generate enough points to fill the circumscribed circle
    # (circle area / rectangle area) × n_rect, with headroom
    circle_area = np.pi * r_max ** 2
    rect_area   = x_range * y_range
    n_gen       = int(np.ceil(n_rect * circle_area / rect_area)) + 20

    # Scaling constant: last generated point lands at r_max
    c = r_max / np.sqrt(n_gen)

    # Vectorised generation — much faster than a Python loop for large N
    idx     = np.arange(n_gen, dtype=float)
    r       = c * np.sqrt(idx + 1.0)
    theta   = idx * _GOLDEN_ANGLE
    xp_all  = x_center + r * np.cos(theta)
    yp_all  = y_center + r * np.sin(theta)

    # Reject points outside the rectangle
    mask = (
        (np.abs(xp_all - x_center) <= x_range / 2.0) &
        (np.abs(yp_all - y_center) <= y_range / 2.0)
    )
    return xp_all[mask], yp_all[mask]


def reorder_spiral_positions(
    xp: np.ndarray,
    yp: np.ndarray,
    x_center: float,
    y_center: float,
    mode: str = "raster",
) -> tuple:
    """
    Reorder Fermat spiral positions to reduce motor travel.

    :param xp:       X positions (µm), as returned by :func:`fermat_spiral_positions`.
    :param yp:       Y positions (µm).
    :param x_center: Centre X of the scan region (µm).
    :param y_center: Centre Y of the scan region (µm).
    :param mode:     ``'outward'`` — sort by increasing radius (centre → edge).
                     ``'raster'``  — bin by Y row, boustrophedon X ordering (default).
    :returns:        ``(xp_ordered, yp_ordered)`` — reordered copies of the input arrays.
    """
    if mode == "outward":
        r = np.hypot(xp - x_center, yp - y_center)
        order = np.argsort(r)
        return xp[order], yp[order]

    # mode == 'raster' (default)
    n = len(xp)
    if n <= 1:
        return xp, yp

    # Estimate the typical inter-point spacing from the FOV area and point count
    x_span = xp.max() - xp.min() if n > 1 else 1.0
    y_span = yp.max() - yp.min() if n > 1 else 1.0
    step_est = np.sqrt(x_span * y_span / n)

    # Assign each point to a Y-row bin (round to nearest row)
    row_bin = np.round((yp - yp.min()) / step_est).astype(int)

    rows = sorted(set(row_bin.tolist()))
    indices = []
    for i, row in enumerate(rows):
        pts = np.where(row_bin == row)[0]
        pts_sorted = pts[np.argsort(xp[pts])]
        if i % 2 == 1:                   # reverse every other row (boustrophedon)
            pts_sorted = pts_sorted[::-1]
        indices.extend(pts_sorted.tolist())

    order = np.array(indices, dtype=int)
    return xp[order], yp[order]


# ---------------------------------------------------------------------------
# Scan class
# ---------------------------------------------------------------------------

class SpiralPtychographyScan(BaseScan):
    """
    Ptychography scan using a Fermat spiral position list.

    The Fermat spiral covers the user-defined rectangular scan region.  Each
    position is visited once (like ``derived_ptychography_image``) with an
    optional dark-field acquisition beforehand.  All ZMQ messaging, energy
    handling, focus offset, defocus, and detector retract/insert logic mirror
    the ``derived_ptychography_image`` driver.
    """

    # ------------------------------------------------------------------
    # BaseScan interface
    # ------------------------------------------------------------------

    async def execute_scan(self) -> bool:
        scan        = self.scan
        dataHandler = self.dataHandler
        controller  = self.controller
        queue       = self.queue

        energies       = dataHandler.data.energies["default"]
        zPos           = dataHandler.data.zPos
        nScanRegions   = len(dataHandler.data.xPos)

        scanInfo = self.scanInfo
        scanInfo["mode"]            = "ptychographySpiral"
        scanInfo["storage_pattern"] = "ptychography"
        scanInfo["doubleExposure"]  = scan["doubleExposure"]
        scanInfo["n_repeats"]       = scan["n_repeats"]
        scanInfo["oversampling_factor"] = 1
        scanInfo["totalSplit"]      = None
        scanInfo["retract"]         = scan["retract"]
        scanInfo["rawData"]         = {}

        for daq in scanInfo["daq_list"]:
            scanInfo["rawData"][daq] = {
                "meta": controller.daq[daq].meta,
                "data": None,
            }
            if scanInfo["rawData"][daq]["meta"]["type"] == "spectrum":
                scanInfo["rawData"][daq]["meta"]["n_energies"] = \
                    len(scanInfo["rawData"][daq]["meta"]["x"])
            else:
                scanInfo["rawData"][daq]["meta"]["n_energies"] = len(energies)
            scanInfo["rawData"][daq]["interpolate"] = \
                controller.daq[daq].meta.get("oversampling_factor", 1) > 1

        energyIndex = 0
        scanInfo["energyIndex"] = energyIndex
        scanInfo["dwell"]       = dataHandler.data.dwells[energyIndex]

        if scan["doubleExposure"]:
            dwell1 = round(scanInfo["dwell"] * 10.0)
            dwell2 = round(scanInfo["dwell"])
        else:
            dwell1 = round(scanInfo["dwell"])
            dwell2 = 0

        scanID = dataHandler.ptychoDir
        print(f"[spiral_ptychography_image] Starting spiral ptychography scan: {scanID}")

        if scanInfo["retract"]:
            await retractSTXMDetector(controller)
            print("[spiral_ptychography_image] Done retracting STXM diode")

        # DAQ configuration — same as derived_ptychography_image
        controller.config_daqs(
            dwell   = [dwell1 + 10.0, dwell2 + 10.0],
            count   = 1,
            samples = 1,
            trigger = "BUS",
            daq_list = scanInfo["daq_list"],
        )

        currentZonePlateZ = controller.motors["ZonePlateZ"]["motor"].getPos()

        for energy in energies:
            scanInfo["energy"]      = energy
            scanInfo["energyIndex"] = energyIndex

            for j in range(nScanRegions):
                scanRegion = f"Region{j + 1}"
                region     = scan["scan_regions"][scanRegion]

                # ----------------------------------------------------------
                # Build Fermat spiral positions for this region
                # ----------------------------------------------------------
                x_center = region["xCenter"]
                y_center = region["yCenter"]
                x_range  = region["xRange"]
                y_range  = region["yRange"]
                # Use the average of xStep and yStep as the isotropic probe step
                step = 0.5 * (abs(region["xStep"]) + abs(region["yStep"]))

                xp_spiral, yp_spiral = fermat_spiral_positions(
                    x_center, y_center, x_range, y_range, step
                )
                ordering = scan.get("spiral_ordering", "raster")
                xp_spiral, yp_spiral = reorder_spiral_positions(
                    xp_spiral, yp_spiral, x_center, y_center, mode=ordering
                )

                if len(xp_spiral) == 0:
                    print(f"[spiral_ptychography_image] WARNING: no spiral points "
                          f"generated for {scanRegion} — skipping.")
                    continue

                n_spiral = len(xp_spiral)
                print(f"[spiral_ptychography_image] {scanRegion}: "
                      f"{n_spiral} spiral positions "
                      f"(FOV {x_range:.2f} × {y_range:.2f} µm, step {step:.3f} µm)")

                # Update scanInfo arrays so DataHandler can size its buffers
                if energy == energies[0]:
                    scanInfo["xPoints"]        = scan["scan_regions"][scanRegion]["xPoints"]
                    scanInfo["yPoints"]        = scan["scan_regions"][scanRegion]["yPoints"]
                    scanInfo["numMotorPoints"] = n_spiral
                    scanInfo["numDAQPoints"]   = n_spiral
                    dataHandler.data.updateArrays(j, scanInfo)

                # ----------------------------------------------------------
                # Energy / focus handling (matches derived_ptychography_image)
                # ----------------------------------------------------------
                if len(energies) > 1:
                    controller.moveMotor(scan["energy_motor"], energy)
                    if not scan.get("autofocus", False):
                        if energy == energies[0]:
                            scanInfo["refocus_offset"] = (
                                currentZonePlateZ
                                - controller.motors["ZonePlateZ"]["motor"].calibratedPosition
                            )
                            print(f"[spiral_ptychography_image] "
                                  f"calculated refocus offset: {scanInfo['refocus_offset']:.4f}")
                        controller.moveMotor(
                            "ZonePlateZ",
                            controller.motors["ZonePlateZ"]["motor"].calibratedPosition
                            + scanInfo["refocus_offset"],
                        )

                if scan.get("defocus", False):
                    step_defocus = (
                        energies[0] / 700.0
                        * controller.main_config["ptychography"]["defocus"]
                    )
                    print(f"[spiral_ptychography_image] "
                          f"defocusing zone plate by {step_defocus:.4f} µm")
                    controller.motors["ZonePlateZ"]["motor"].moveBy(step=step_defocus)

                # ----------------------------------------------------------
                # Move coarse motors and compute fine offsets
                # ----------------------------------------------------------
                xp_all = xp_spiral
                yp_all = yp_spiral

                controller.motors[scan["x_motor"]]["motor"].move_coarse_to_fine_range(
                    xp_all.min(), xp_all.max()
                )
                controller.motors[scan["y_motor"]]["motor"].move_coarse_to_fine_range(
                    yp_all.min(), yp_all.max()
                )

                x_coarse = controller.motors[scan["x_motor"]]["motor"].coarsePos
                y_coarse = controller.motors[scan["y_motor"]]["motor"].coarsePos

                xp_fine = xp_all - x_coarse
                yp_fine = yp_all - y_coarse

                # ----------------------------------------------------------
                # Nearest-neighbour mapping: spiral → GUI grid indices
                # ----------------------------------------------------------
                # The GUI grid in global coordinates (same reference as xp_spiral)
                xpts = scan["scan_regions"][scanRegion]["xPoints"]
                ypts = scan["scan_regions"][scanRegion]["yPoints"]
                x_grid = np.linspace(x_center - x_range / 2,
                                     x_center + x_range / 2, xpts)
                y_grid = np.linspace(y_center - y_range / 2,
                                     y_center + y_range / 2, ypts)

                col_idx = np.argmin(
                    np.abs(xp_spiral[:, None] - x_grid[None, :]), axis=1
                )
                row_idx = np.argmin(
                    np.abs(yp_spiral[:, None] - y_grid[None, :]), axis=1
                )
                spiral_grid_indices = list(zip(row_idx.tolist(), col_idx.tolist()))

                # Dark positions (5 diagonal points) — same nearest-neighbour mapping
                xp_dark = np.linspace(xp_fine.min(), xp_fine.max(), 5)
                yp_dark = np.linspace(yp_fine.min(), yp_fine.max(), 5)
                xp_dark_global = xp_dark + x_coarse
                yp_dark_global = yp_dark + y_coarse
                col_dark = np.argmin(
                    np.abs(xp_dark_global[:, None] - x_grid[None, :]), axis=1
                )
                row_dark = np.argmin(
                    np.abs(yp_dark_global[:, None] - y_grid[None, :]), axis=1
                )
                dark_grid_indices = list(zip(row_dark.tolist(), col_dark.tolist()))

                # ----------------------------------------------------------
                # Open NX file and gather motor positions
                # ----------------------------------------------------------
                scan["file_name"] = dataHandler.currentScanID.replace(
                    ".stxm",
                    f"_ccdframes_{energyIndex}_{j}.stxm",
                )
                dataHandler.ptychodata = stxm(scan)
                dataHandler.ptychodata.start_time = str(datetime.datetime.now())
                controller.getMotorPositions()
                dataHandler.data.motorPositions[j] = controller.allMotorPositions
                dataHandler.ptychodata.motorPositions[0] = controller.allMotorPositions
                scanInfo["motorPositions"] = controller.allMotorPositions

                # ----------------------------------------------------------
                # Build metadata dict (matches derived_ptychography_image)
                # ----------------------------------------------------------
                scanMeta = {
                    "header":           dataHandler.currentScanID,
                    "repetition":       1,
                    "defocus":          scan.get("defocus", False),
                    "isDoubleExp":      int(scan["doubleExposure"]),
                    "pos_x":            x_center,
                    "pos_y":            y_center,
                    # For a spiral, "step size" is the average probe step
                    "step_size_x":      step,
                    "step_size_y":      step,
                    "num_pixels_x":     n_spiral,
                    "num_pixels_y":     1,
                    "background_pixels_x": 5,
                    "background_pixels_y": 5,
                    "dwell1":           dwell1,
                    "dwell2":           dwell2,
                    "energy":           energy,
                    "energyIndex":      energyIndex,
                    "scanRegion":       j,
                    "dark_num_x":       5,
                    "dark_num_y":       5,
                    "exp_num_x":        n_spiral,
                    "exp_num_y":        1,
                    "exp_step_x":       step,
                    "exp_step_y":       step,
                    "double_exposure":  bool(scan["doubleExposure"]),
                    "geometry":         controller.main_config["geometry"],
                    "n_repeats":        scan["n_repeats"],
                    # Spiral-specific — flat list of (y, x) fine positions
                    "translations":     [(float(y), float(x))
                                         for x, y in zip(xp_fine, yp_fine)],
                }
                scanMeta["exp_num_total"] = (
                    scanMeta["exp_num_x"]
                    * (2 - int(not scanMeta["double_exposure"]))
                )

                scan_copy = {k: v for k, v in scan.items() if k != "synch_event"}
                scanMeta["scan"] = scan_copy

                dataHandler.zmq_start_event(scan, metadata=scanMeta)
                await asyncio.sleep(0.1)

                scanInfo["scanRegion"] = scanRegion

                # ----------------------------------------------------------
                # Dark acquisition (5 points along the diagonal of the FOV)
                # ----------------------------------------------------------
                scanInfo["ccd_mode"] = "dark"
                print("[spiral_ptychography_image] Acquiring background (dark)")
                if await point_loop(
                    scan, scanInfo.copy(),
                    (xp_dark, yp_dark, zPos[j]),
                    dataHandler, controller, queue,
                    shutter=False, scanRegion=scanRegion,
                    grid_indices=dark_grid_indices,
                ):
                    await dataHandler.dataQueue.put("endOfRegion")
                else:
                    dataHandler.zmq_send({"event": "abort", "data": None})
                    if scanInfo["retract"]:
                        await insertSTXMDetector(controller)
                    return False

                # ----------------------------------------------------------
                # Exposure acquisition — spiral positions
                # ----------------------------------------------------------
                scanInfo["ccd_mode"] = "exp"
                print("[spiral_ptychography_image] Acquiring data (spiral exposure)")
                if await point_loop(
                    scan, scanInfo.copy(),
                    (xp_fine, yp_fine, zPos[j]),
                    dataHandler, controller, queue,
                    shutter=True, scanRegion=scanRegion,
                    grid_indices=spiral_grid_indices,
                ):
                    await dataHandler.dataQueue.put("endOfRegion")
                    while not dataHandler.dataQueue.empty():
                        await asyncio.sleep(0.1)
                else:
                    print("[spiral_ptychography_image] Aborting scan…")
                    dataHandler.zmq_send({"event": "abort", "data": None})
                    if scanInfo["retract"]:
                        await insertSTXMDetector(controller)
                    if scan.get("defocus", False):
                        controller.motors["ZonePlateZ"]["motor"].moveBy(
                            step=-step_defocus
                        )
                    return False

                # Wait for DataHandler to finish writing the region
                while not dataHandler.regionComplete:
                    print("[spiral_ptychography_image] Waiting for region to complete…")
                    await asyncio.sleep(1)

                print("[spiral_ptychography_image] Scan region complete — saving data")
                scanMeta.pop("illumination", None)
                dataHandler.ptychodata.addDict(scanMeta, "metadata")
                dataHandler.ptychodata.saveRegion(0)
                dataHandler.ptychodata.close()
                dataHandler.zmq_send_string({
                    "event": "ccd_data",
                    "data":  {"identifier": os.path.basename(dataHandler.ptychodata.file_name)},
                })
                dataHandler.data.end_time = str(datetime.datetime.now())
                dataHandler.zmq_stop_event()
                print("[spiral_ptychography_image] Done!")

            energyIndex += 1

        await dataHandler.dataQueue.put("endOfScan")
        if scanInfo["retract"]:
            await insertSTXMDetector(controller)
        if scan.get("defocus", False):
            controller.motors["ZonePlateZ"]["motor"].moveBy(step=-step_defocus)
        print("[spiral_ptychography_image] Finished spiral ptychography scan")
        return True


# ---------------------------------------------------------------------------
# Module-level entry point (matches the convention used by all other drivers)
# ---------------------------------------------------------------------------

async def spiral_ptychography_image(scan, dataHandler, controller, queue):
    """
    Entry point called by the scan dispatcher.

    Instantiates :class:`SpiralPtychographyScan` and runs it.
    """
    await scan["synch_event"].wait()
    obj = SpiralPtychographyScan(scan, dataHandler, controller, queue)
    # Populate scanInfo and rawData via BaseScan helpers before execute_scan
    await obj.initialize_scan_info()
    obj.setup_daqs()
    return await obj.execute_scan()

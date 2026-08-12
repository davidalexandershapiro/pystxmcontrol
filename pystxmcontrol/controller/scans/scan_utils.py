from time import time,sleep
import numpy as np
import traceback
import asyncio


def set_scan_energy(controller, scan, scanInfo, energy, energies):
    """Move the energy motor for a scan's target energy and record the ACTUAL
    energy in ``scanInfo["energy"]``.

    Multi-energy scans always move (each energy point is a deliberate step).
    Single-energy scans move only when the request differs from the current
    energy by more than the energy motor's ``energy_deadband`` config value
    (default 0.1 eV) — small energy moves take several seconds, so repeated
    near-same-energy scans skip the move.  Either way ``scanInfo["energy"]`` is
    set to the energy the scan actually runs at, so the GUI, metadata overlay,
    and saved file never disagree with the hardware.

    Does NOT change the caller's ``energy`` variable (so ``energy == energies[0]``
    bookkeeping still holds) and does NOT touch autofocus/refocus — callers keep
    that logic.  Returns the actual energy for optional use.
    """
    energy_motor = scan["energy_motor"]
    actual = energy
    if len(energies) > 1:
        controller.moveMotor(energy_motor, energy)
    else:
        motor = controller.motors[energy_motor]["motor"]
        current = motor.getPos()
        deadband = motor.config.get("energy_deadband", 0.1)
        if abs(energy - current) > deadband:
            controller.moveMotor(energy_motor, energy)
        else:
            actual = current
    scanInfo["energy"] = actual
    return actual


async def async_check_pause(controller, queue) -> bool:
    """Wait while paused.  Returns True to continue, False to terminate.

    On cancel-during-pause: consumes the cancel message and returns False.
    On timeout: clears controller.pause, injects a sentinel so handle_abort
    style callers can call queue.get() without deadlocking, and returns False.
    """
    if not controller.pause:
        return True
    timeout = getattr(controller, 'pause_timeout_seconds', 120)
    pause_start = getattr(controller, '_pause_start_time', None) or time()
    while controller.pause:
        if not queue.empty():
            await queue.get()
            controller.pause = False
            return False
        if time() - pause_start > timeout:
            print(f"[scan] Pause timeout ({timeout}s) — terminating scan.")
            controller.pause = False
            await queue.put("pause_timeout")
            return False
        await asyncio.sleep(0.1)
    return True

def getLoopMotorPositions(scan):
    r = scan["outerLoop"]["range"]
    center = scan["outerLoop"]["center"]
    points = scan["outerLoop"]["points"]
    start = center - r / 2
    stop = center + r / 2
    return np.linspace(start, stop, points)

async def terminateFlyscan(controller, dataHandler, scan, axis, message):
    await dataHandler.dataQueue.put('endOfScan')
    controller.motors[scan[axis]]["motor"].setPositionTriggerOff()
    while not controller.scanQueue.empty():
        try:
            controller.scanQueue.get_nowait()
        except asyncio.QueueEmpty:
            break
    print(message)
    return False


def executeReturnTrajectory(self, motor, xStart, xStop, yStart, yStop):
    maxSpeed = 2.0  # um/ms or mm/s
    minpoints = 5
    motor.trajectory_start = (xStop, yStop)
    motor.trajectory_stop = (xStart, yStart)
    xyRange = ((xStop - xStart) ** 2 + (yStop - yStart) ** 2) ** 0.5
    dwell = 0.301  # ms. Unimportant I think.
    xyPoints = int(max(xyRange / (maxSpeed * dwell), minpoints))
    motor.trajectory_pixel_count = xyPoints
    motor.trajectory_pixel_dwell = dwell
    motor.update_trajectory()
    motor.moveLine()

async def doFlyscanLine(controller, dataHandler, scan, scanInfo, waitTime, axes=[1,]):
    daq_master = scan.get("daq_master", False)
    x_motor = controller.motors[scan["x_motor"]]["motor"]
    if "offset" not in scanInfo.keys():
        scanInfo["offset"] = 0,0
    if daq_master:
        # DAQ-master clocking (e.g. SmarAct MCS2): the stage stream is the SLAVE and
        # must be armed and *waiting* before the DAQ emits its first gate edge, else
        # the earliest edges are lost and the stage trails the detector all line.
        # Order: arm slave -> open gate -> start DAQ (gate clock) -> drain slave.
        x_motor.armLine(coarse_offset = scanInfo["offset"],
                        coarse_only = scan["coarse_only"], axes=axes)
        controller.daq["default"].autoGateOpen()
        if scan["spiral"]:
            sleep(0.02)
        await asyncio.sleep(waitTime)
        for daq in scanInfo["daq_list"]:
            controller.daq[daq].initLine()
        x_motor.finishLine(coarse_offset = scanInfo["offset"],
                          coarse_only = scan["coarse_only"], axes=axes)
    else:
        # Stage-master clocking (historical, e.g. MCL): the stage emits the per-pixel
        # clock and the DAQ is triggered "EXT".  Unchanged legacy order.
        for daq in scanInfo["daq_list"]:
            controller.daq[daq].initLine()
        controller.daq["default"].autoGateOpen()
        #Wait time I assume for initializing detector. Without it, spiral scan doesn't work.
        if scan["spiral"]:
            sleep(0.02)
        await asyncio.sleep(waitTime)
        x_motor.moveLine(coarse_offset = scanInfo["offset"],
                        coarse_only = scan["coarse_only"], axes=axes)
    scanInfo["line_positions"] = x_motor.positions
    controller.daq["default"].autoGateClosed()
    try:
        #this will timeout if there is a missed trigger.  That can happen at the start of
        #big scans or some reason.
        await dataHandler.getLine(scanInfo.copy())
    except Exception as e:
        #by default, if a trigger is missed we end up here, restart the daq and return False.  The scan routine
        #can decide if it wants to retry.
        print("[scan utils] DAQ timeout.  Restarting DAQ and moving on.")
        dataHandler.record_event(
            "daq_timeout",
            line_index=scanInfo.get("lineIndex"),
            region=scanInfo.get("scanRegion"),
            energy_index=scanInfo.get("energyIndex"),
            error=str(e),
        )
        controller.daq["default"].stop()
        controller.daq["default"].start()
        controller.config_daqs(dwell = scanInfo["dwell"],
                               count = scanInfo["trigger_count"],
                               samples = scanInfo["trigger_samples"],
                               trigger = "GATE_OUT" if daq_master else "EXT",
                               daq_list=scanInfo["daq_list"])
        return False
    return True

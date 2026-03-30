"""
CCD Replay scan — replays CCD frames from a prior ptychography scan.

No motors are moved and no DAQs are triggered. CCD frames are read from
the HDF5 _ccdframes_ file produced by ptychography_image and republished
via the CCD ZMQ channel so the viewer displays them as if live.

Required scan dict fields:
    source_scan (str): Absolute path to the _ccdframes_ .stxm HDF5 file.
    frame_delay_ms (float, optional): Delay between frames in ms (default 100).
"""

import asyncio
import h5py
import numpy as np
from pystxmcontrol.drivers.fccd import FCCD


async def ccd_replay(scan, dataHandler, controller, queue):
    """
    Replay CCD frames from a prior scan over the CCD ZMQ channel.

    :param scan: Scan parameter dictionary (must include 'source_scan').
    :param dataHandler: Data handler instance.
    :param controller: Controller instance (unused, kept for API consistency).
    :param queue: Async abort queue.
    """
    await scan["synch_event"].wait()
    print('ccd replay scan:')
    print(scan)
    source_path = scan.get("source_scan", "")
    frame_delay = scan.get("frame_delay_ms", 100) / 1000.0
    # shape = (1040,1152)
    # num_rows = shape[0] // 2
    # num_adcs = shape[1] // 6
    # CCD = FCCD(nrows = num_rows)
    # CCD2 = FCCD(nrows = 490)

    if not source_path:
        print("[CCD Replay] No source_scan path specified.")
        await dataHandler.dataQueue.put("endOfScan")
        return

    try:
        with h5py.File(source_path, "r") as f:
            data = f.get("entry_1/data_1/data")
            if data is None:
                print(f"[CCD Replay] No CCD exp data found in {source_path}")
                await dataHandler.dataQueue.put("endOfScan")
                return

            
            n_frames = len(data)
            print(f"[CCD Replay] Replaying {n_frames} frames from {source_path}")


            dataHandler.zmq_send({
                "event": "start",
                "data": scan,
                "metadata": {
                    "source_scan": source_path,
                    "n_frames": n_frames,
                },
            })

            for frame_num, frame in enumerate(data):
                if frame_num % 10 == 0:
                    print(f"[CCD Replay] Displaying frame number {frame_num}")
                if not queue.empty():
                    print("[CCD Replay] Aborted.")
                    break



                display = np.clip(frame, 0, None)
                

                scanInfo = {
                    "mode": "ccd_replay",
                    "type": scan["scan_type"],
                    "scan": scan,
                    "ccd_frame_num": frame_num,
                    "ccd_mode": "exp",
                    "doubleExposure": False,
                    "rawData": {"CCD": {"data": frame}},
                    "data": {"CCD": display},
                    "index": frame_num,
                }

                dataHandler.zmq_publisher.publish_stxm_data(scanInfo)
                await asyncio.sleep(frame_delay)

            dataHandler.zmq_send({"event": "stop", "data": None})
            print(f"[CCD Replay] Finished replaying {n_frames} frames.")

    except OSError as e:
        print(f"[CCD Replay] Could not open source file: {e}")
    except Exception as e:
        print(f"[CCD Replay] Unexpected error: {e}")

    await dataHandler.dataQueue.put("endOfScan")

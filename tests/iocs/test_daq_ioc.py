import time
from pathlib import Path

import pytest

from pystxmcontrol.iocs.config import load_fleet

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def daq_ioc(ioc_harness):
    fleet = load_fleet(str(REPO / "config" / "motor.json"),
                       str(REPO / "config" / "daq.json"), station="SIM")
    from pystxmcontrol.iocs.daq_ioc import build_pvdb_for_entry
    pvdb, group = build_pvdb_for_entry(fleet.daqs[0].entry, fleet.daqs[0].prefix)
    ioc_harness.start(pvdb)
    return ioc_harness, group


def test_acquire_put_completion_blocks_until_done(daq_ioc):
    h, group = daq_ioc
    ctx = h.client()
    dwell, acq, counts, rate = ctx.get_pvs(
        "STXMSIM:DEFAULT:DWELL", "STXMSIM:DEFAULT:ACQUIRE",
        "STXMSIM:DEFAULT:COUNTS", "STXMSIM:DEFAULT:RATE")
    acq.wait_for_connection(timeout=10)
    dwell.write(200.0, wait=True, timeout=10)  # 200 ms sim acquisition
    t0 = time.monotonic()
    acq.write(1, wait=True, timeout=30)        # completion callback semantics
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.18, f"put completed in {elapsed:.3f}s - did not wait for acquisition"
    c = counts.read().data[0]
    assert c > 0  # Poisson(1e7 * 0.2) ~ 2e6
    assert abs(rate.read().data[0] - c / 0.2) / (c / 0.2) < 1e-6


def test_counts_wf_written_by_write_line(daq_ioc):
    import numpy as np
    h, group = daq_ioc
    ctx = h.client()
    (wf,) = ctx.get_pvs("STXMSIM:DEFAULT:COUNTS:WF")
    wf.wait_for_connection(timeout=10)
    line = np.arange(50, dtype=float)
    h.call_soon(group.write_line(line)).result(timeout=10)
    data = wf.read().data
    assert list(data[:50]) == list(line)


def test_mode_enum(daq_ioc):
    from caproto import ChannelType
    h, group = daq_ioc
    ctx = h.client()
    (mode,) = ctx.get_pvs("STXMSIM:DEFAULT:MODE")
    mode.wait_for_connection(timeout=10)
    # A bare mode.write("line") fails CLIENT-side in caproto 1.3's numpy
    # backend (ValueError: invalid literal for int() with base 10: b'line',
    # _numpy_backend.py:64) -- the threading client does not map enum strings
    # to indices for the native ENUM dtype. Write by index instead:
    mode.write(1, wait=True, timeout=10)
    assert mode.read(data_type="native").data[0] == 1
    # String writes DO work when sent as a CA STRING; the server-side
    # ChannelEnum maps them back to the enum index.
    mode.write("point", wait=True, timeout=10, data_type=ChannelType.STRING)
    assert mode.read(data_type="native").data[0] == 0


def test_mode_rejects_unknown_string(daq_ioc):
    from caproto import ChannelType
    h, group = daq_ioc
    ctx = h.client()
    (mode,) = ctx.get_pvs("STXMSIM:DEFAULT:MODE")
    mode.wait_for_connection(timeout=10)
    with pytest.raises(Exception):
        mode.write("bogus", wait=True, timeout=10, data_type=ChannelType.STRING)
    assert mode.read(data_type="native").data[0] in (0, 1)  # unchanged/valid

"""nPoint controller read-frame parsing.

The controller echoes the command's addr ahead of the value, so a sensor read
returns a 10-byte frame [readCom][addr:4][value:4][0x55] (and readArray a
6 + 4*numBytes frame). An earlier port read only 6 bytes, so the value slice
landed on the ADDRESS -- e.g. 0x11831334 -> a bogus ~27777 um that tripped the
outlier guard on both axes. GOLDEN_FRAMES below are real captures from the
station-5321 nPoint (controllerID 7340015A); readFromDev4B must decode them to
small sub-micron positions.
"""
import types

import pytest

from pystxmcontrol.drivers.nptController import nptController

GAIN = 10.577  # counts per nm; controller.getPos() = steps / (GAIN*1000) um

# (hex frame off the wire) -> expected signed step count
GOLDEN_FRAMES = {
    "a0341383110401000055": 260,          # axis x, ~+0.025 um
    "a03413831112ffffff55": -238,         # axis x, ~-0.023 um (signed)
    "a034238311f003000055": 1008,         # axis y, ~+0.095 um
    "a034238311cd03000055": 973,          # axis y, ~+0.092 um
}


class _MockDev:
    """Returns a full frame in one read(), then EOF -- like the real FTDI read
    for these short responses."""

    def __init__(self, frame: bytes):
        self._frame = frame
        self._sent = False

    def write(self, b):
        return len(b)

    def read(self, n):
        if self._sent:
            return b""
        self._sent = True
        return self._frame


def _ctrl(frame_hex: str) -> nptController:
    c = nptController.__new__(nptController)
    c.readCom = 0xA0
    c.readArrayCom = 0xA4
    c._read_timeout = 1.0
    c.dev = _MockDev(bytes.fromhex(frame_hex))
    for m in ("_readResponse", "hexToSignedInt", "readFromDev4B", "readArray"):
        setattr(c, m, types.MethodType(getattr(nptController, m), c))
    return c


@pytest.mark.parametrize("frame_hex,expected_steps", GOLDEN_FRAMES.items())
def test_readfromdev4b_decodes_value_not_address(frame_hex, expected_steps):
    steps = _ctrl(frame_hex).readFromDev4B(0x11831334)
    assert steps == expected_steps
    microns = steps / (GAIN * 1000)
    assert -50.0 <= microns <= 50.0  # sane fine-stage range, never ~27777


def test_readarray_skips_echoed_cmd_and_addr_prefix():
    # frame: [readArrayCom][addr LE 4][value LE 8][0x55]  (numBytes=2 -> 14 bytes)
    value_le = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
    addr_le = bytes([0x34, 0x13, 0x83, 0x11])
    frame = bytes([0xA4]) + addr_le + value_le + bytes([0x55])
    retval = _ctrl(frame.hex()).readArray(2, 0x11831334)
    # after reverse, value comes back big-endian; must be the value, not addr
    assert retval == "0x" + bytes(reversed(value_le)).hex()
    assert "11831334" not in retval  # not the echoed address

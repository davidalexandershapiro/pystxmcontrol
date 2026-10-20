"""Regression tests for nptController's FTDI read reassembly.

Root cause of the observed IOC crash (`ValueError: invalid literal for int()
with base 16: ''`): pylibftdi's ``Device.read(n)`` returns *up to* n bytes, so
a short/fragmented USB read left ``readFromDev4B`` with a truncated buffer whose
``[1:5]`` value slice was empty -> ``'0x'`` -> ``int('', 16)`` blew up. The old
``while datar == b'':`` loop only retried *fully* empty reads, not partial ones.
"""
import sys
import types

import pytest

# nptController.py does `from pylibftdi import Device, Driver` at import time,
# and pylibftdi isn't installed off the beamline host. Stub it -- the tests
# inject a fake `.dev` directly and never touch the real Device.
if "pylibftdi" not in sys.modules:
    _stub = types.ModuleType("pylibftdi")
    _stub.Device = object
    _stub.Driver = object
    sys.modules["pylibftdi"] = _stub

from pystxmcontrol.drivers.nptController import (  # noqa: E402
    nptCommError, nptController)

# A valid 4-byte read response is a 6-byte frame: [lead][b0 b1 b2 b3][0x55].
FRAME = bytes([0x11, 0x01, 0x02, 0x03, 0x04, 0x55])
READ_ADDR = 0x11831334  # axis-1 dsr address (base + dsrOffset)


class FakeDev:
    """Minimal pylibftdi.Device stand-in. ``read`` yields the scripted chunks
    in order, then endless ``b''`` (mimicking a device with nothing more to
    send)."""

    def __init__(self, write_ret, read_chunks):
        self._write_ret = write_ret
        self._chunks = list(read_chunks)

    def write(self, data):
        return self._write_ret

    def read(self, n):
        return self._chunks.pop(0) if self._chunks else b""


def _controller(read_chunks, write_ret=6):
    c = nptController()
    c.dev = FakeDev(write_ret, read_chunks)
    return c


def test_single_full_read_decodes():
    """Baseline: a device that returns the whole frame in one read works."""
    assert _controller([FRAME]).readFromDev4B(READ_ADDR) == \
        _controller([FRAME]).readFromDev4B(READ_ADDR)


def test_fragmented_read_reassembles_to_same_value():
    """The crash scenario: the frame dribbles in across several short reads
    (including a stray empty one). Must decode identically, never raise."""
    baseline = _controller([FRAME]).readFromDev4B(READ_ADDR)
    fragmented = _controller(
        [FRAME[:1], b"", FRAME[1:3], FRAME[3:]]).readFromDev4B(READ_ADDR)
    assert fragmented == baseline


def test_one_byte_then_silence_raises_clean_error_not_valueerror():
    """A truncated response that never completes must raise the driver's own
    nptCommError within the read timeout -- not a bare ValueError, and not an
    infinite spin."""
    c = _controller([b"\x11"])  # one byte, then endless b''
    c._read_timeout = 0.05
    with pytest.raises(nptCommError):
        c.readFromDev4B(READ_ADDR)


def test_hex_to_signed_int_rejects_empty():
    c = nptController()
    with pytest.raises(nptCommError):
        c.hexToSignedInt("0x")


def test_readarray_reassembles_fragmented_response():
    # numBytes=2 -> expected frame length 4*2 + 2 = 10 bytes.
    frame = bytes([0x11, 1, 2, 3, 4, 5, 6, 7, 8, 0x55])
    baseline = _controller([frame], write_ret=10).readArray(2, READ_ADDR)
    fragmented = _controller(
        [frame[:1], b"", frame[1:6], frame[6:]], write_ret=10).readArray(2, READ_ADDR)
    assert fragmented == baseline

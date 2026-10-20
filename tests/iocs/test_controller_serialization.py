"""Motors sharing a controller must serialize their blocking driver calls.

Two axes on one controller share a single link (e.g. one FTDI handle for both
nPoint axes). If their RBV pollers / moves issue overlapping write+read
transactions, the frames interleave and one axis reads the other's response as
garbage. MotorRecordGroup guards every driver call with a per-controller
io_lock; these tests verify that guard actually serializes concurrent access.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from pystxmcontrol.iocs.base import MotorRecordGroup


class SharedLink:
    """Stands in for a controller's single physical link. Records the peak
    number of transactions running inside it at once."""

    def __init__(self):
        self._n = 0
        self.max_concurrent = 0
        self._guard = threading.Lock()

    def transact(self):
        with self._guard:
            self._n += 1
            self.max_concurrent = max(self.max_concurrent, self._n)
        time.sleep(0.002)  # widen the interleave window
        with self._guard:
            self._n -= 1
        return 1.0


class FakeMotor:
    """A motor whose every driver call goes through the shared controller link."""

    def __init__(self, link):
        self.controller = link

    def getPos(self):
        return self.controller.transact()

    def moveTo(self, target):
        self.controller.transact()


def _group(link, lock):
    return MotorRecordGroup("X", driver=FakeMotor(link),
                            motor_config={"minValue": -50, "maxValue": 50},
                            io_lock=lock)


def test_shared_lock_serializes_two_axes():
    link = SharedLink()
    lock = threading.Lock()
    gx, gy = _group(link, lock), _group(link, lock)  # same controller, same lock

    calls = []
    for g in (gx, gy):
        calls += [lambda g=g: g._locked_call(g._driver.getPos)] * 40
        calls += [lambda g=g: g._guarded_move_to(1.0)] * 20

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda f: f(), calls))

    assert link.max_concurrent == 1, (
        f"transactions overlapped on the shared link "
        f"(peak={link.max_concurrent}); io_lock did not serialize them")


def test_without_shared_lock_axes_can_overlap():
    """Control: give each group its OWN lock (the pre-fix behavior) and the
    same shared link does see overlap -- confirming the test can detect the
    race the shared lock prevents."""
    link = SharedLink()
    gx = _group(link, threading.Lock())
    gy = _group(link, threading.Lock())  # DIFFERENT lock per group

    calls = []
    for g in (gx, gy):
        calls += [lambda g=g: g._locked_call(g._driver.getPos)] * 100

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda f: f(), calls))

    assert link.max_concurrent >= 2, (
        "expected overlap with per-group locks; the probe may be too fast to "
        "observe the race")

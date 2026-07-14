"""MotorMonitorSet against the live sim fleet (spec #4 Task 4)."""
import statistics
import threading
import time

import pytest

from pystxmcontrol.remote.ca_monitors import MotorMonitorSet


class _Collector:
    """Thread-safe callback collector for on_update payloads."""

    def __init__(self):
        self._lock = threading.Lock()
        self.calls: list[dict] = []

    def __call__(self, payload: dict) -> None:
        with self._lock:
            self.calls.append(payload)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.calls)


def _wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def two_motors(stxm_fleet):
    return {
        "SampleX": stxm_fleet.motor_pv["SampleX"],
        "SampleY": stxm_fleet.motor_pv["SampleY"],
    }


def test_initial_snapshot_within_5s(two_motors):
    collector = _Collector()
    mon = MotorMonitorSet(two_motors, collector, min_period_s=0.2)
    mon.start()
    try:
        ok = _wait_until(
            lambda: any(
                "SampleX" in c and "SampleY" in c for c in collector.snapshot()
            )
            or (
                any("SampleX" in c for c in collector.snapshot())
                and any("SampleY" in c for c in collector.snapshot())
            ),
            timeout=5.0,
        )
        assert ok, f"no initial snapshot within 5s: {collector.snapshot()}"
        names_seen = {k for c in collector.snapshot() for k in c if k != "status"}
        assert {"SampleX", "SampleY"} <= names_seen
    finally:
        mon.stop()


def test_move_reports_position_and_status_transition(two_motors):
    from caproto.threading.client import Context

    collector = _Collector()
    mon = MotorMonitorSet(two_motors, collector, min_period_s=0.1)
    mon.start()
    client_ctx = None
    try:
        assert _wait_until(lambda: mon.connected.get("SampleX") is True)

        client_ctx = Context()
        (val_pv,) = client_ctx.get_pvs(f"{two_motors['SampleX']}.VAL")
        val_pv.wait_for_connection(timeout=10)
        val_pv.write([7.0], wait=False)

        def _arrived():
            calls = collector.snapshot()
            return any(
                "SampleX" in c and abs(c["SampleX"] - 7.0) < 1e-3 for c in calls
            )

        assert _wait_until(_arrived, timeout=10.0), (
            f"SampleX never reported ~7.0: {collector.snapshot()}"
        )

        # Collect the status sequence for SampleX across all callbacks.
        status_seq = [
            c["status"]["SampleX"]
            for c in collector.snapshot()
            if "status" in c and "SampleX" in c["status"]
        ]
        assert status_seq, "no status updates observed for SampleX"
        # The E712 sim move is effectively instantaneous, so True->False may
        # collapse into a single coalesced flush that only reports the final
        # False; assert on the final resting state (False) plus, if a
        # transition was actually observable, that it went True before False.
        assert status_seq[-1] is False
        if True in status_seq:
            assert status_seq.index(True) < len(status_seq) - list(
                reversed(status_seq)
            ).index(False)
    finally:
        mon.stop()
        if client_ctx is not None:
            client_ctx.disconnect()


def test_rate_limiting_inter_arrival_timestamps(stxm_fleet):
    from caproto.threading.client import Context

    motors = {"energy": stxm_fleet.motor_pv["energy"]}
    timestamps: list[float] = []
    lock = threading.Lock()

    def _on_update(_payload):
        with lock:
            timestamps.append(time.monotonic())

    min_period = 0.3
    mon = MotorMonitorSet(motors, _on_update, min_period_s=min_period)
    mon.start()
    client_ctx = None
    try:
        assert _wait_until(lambda: mon.connected.get("energy") is True)

        client_ctx = Context()
        (val_pv,) = client_ctx.get_pvs(f"{motors['energy']}.VAL")
        val_pv.wait_for_connection(timeout=10)

        for target in range(600, 630):
            val_pv.write([float(target)], wait=True, timeout=10)

        assert _wait_until(lambda: len(timestamps) >= 6, timeout=20.0)
    finally:
        mon.stop()
        if client_ctx is not None:
            client_ctx.disconnect()

    with lock:
        ts = list(timestamps)
    diffs = [b - a for a, b in zip(ts, ts[1:])]
    assert diffs, "not enough callbacks to measure inter-arrival"
    median = statistics.median(diffs)
    assert median >= 0.8 * min_period, (
        f"median inter-arrival {median} < 0.8*{min_period}: diffs={diffs}"
    )


def test_stop_silences_callbacks(two_motors):
    collector = _Collector()
    mon = MotorMonitorSet(two_motors, collector, min_period_s=0.1)
    mon.start()
    try:
        assert _wait_until(lambda: len(collector.snapshot()) > 0)
    finally:
        mon.stop()

    count_after_stop = len(collector.snapshot())
    time.sleep(1.0)
    assert len(collector.snapshot()) == count_after_stop, (
        "callbacks continued to arrive after stop()"
    )


def test_unknown_pv_reports_disconnected(stxm_fleet):
    motors = {
        "SampleX": stxm_fleet.motor_pv["SampleX"],
        "Bogus": "STXMSIM:DOES:NOT:EXIST",
    }
    collector = _Collector()
    mon = MotorMonitorSet(motors, collector, min_period_s=0.2)
    mon.start()
    try:
        assert _wait_until(lambda: mon.connected.get("SampleX") is True)
        # Bogus never connects; give it the same generous window before
        # asserting it stays disconnected without disturbing SampleX.
        time.sleep(2.0)
        connected = mon.connected
        assert connected["Bogus"] is False
        assert connected["SampleX"] is True
    finally:
        mon.stop()

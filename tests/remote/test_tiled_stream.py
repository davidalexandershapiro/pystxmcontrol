"""RunStreamer unit tests against a FakeRun/FakeStream (spec #4 Task 6).

No Tiled server involved: FakeStream.read() returns a growing table
(dict of column -> list) that mimics the primary stream table facet.
Live coverage against a real Tiled server lands in Task 8.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from pystxmcontrol.remote.tiled_stream import RunStreamer


def _wait_until(predicate, timeout=5.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeStream:
    """Duck-types the tiled stream node surface: only .read() is used."""

    def __init__(self, table_fn=None, table=None, raise_exc=None):
        self._table_fn = table_fn
        self._table = table
        self._raise_exc = raise_exc
        self.read_count = 0

    def read(self):
        self.read_count += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._table_fn is not None:
            return self._table_fn()
        return self._table


class FakeRun:
    """Duck-types run.metadata["start"] + run["primary"]."""

    def __init__(self, start_md, primary=None, primary_exc=None):
        self.metadata = {"start": start_md}
        self._primary = primary
        self._primary_exc = primary_exc

    def __getitem__(self, key):
        if key != "primary":
            raise KeyError(key)
        if self._primary_exc is not None:
            raise self._primary_exc
        if self._primary is None:
            raise KeyError("primary")
        return self._primary


def _raster_md(ny=3, nx=4):
    return {
        "plan_name": "stxm_fly_raster",
        "shape": [ny, nx],
        "x_extent": [0.0, 10.0],
        "y_extent": [-5.0, 5.0],
    }


class _Collector:
    def __init__(self):
        self.lock = threading.Lock()
        self.images = []
        self.progress = []
        self.errors = []

    def on_image(self, images, extents):
        with self.lock:
            self.images.append((images, extents))

    def on_progress(self, done, total):
        with self.lock:
            self.progress.append((done, total))

    def on_error(self, exc):
        with self.lock:
            self.errors.append(exc)


def _factory_for(run):
    """RunStreamer calls ``factory() -> catalog`` then ``catalog[run_uid]``."""
    return lambda: {"fake-uid": run}


def test_assembles_rows_in_order_with_nan_fill():
    ny, nx = 3, 4
    rows = {"Counter1": [], "SampleY": []}
    stream = FakeStream(table_fn=lambda: dict(rows))
    run = FakeRun(_raster_md(ny, nx))
    # primary itself IS the stream node in this layout (run["primary"].read())
    run._primary = stream

    collector = _Collector()
    streamer = RunStreamer(
        _factory_for(run), "fake-uid",
        on_image=collector.on_image, on_progress=collector.on_progress,
        on_error=collector.on_error, poll_s=0.02, data_field="Counter1",
    )
    streamer.start()
    try:
        # No rows yet: still get at least one on_image call all-NaN, or none.
        rows["Counter1"] = [[1.0, 2.0, 3.0, 4.0]]
        rows["SampleY"] = [-5.0]

        def _first_row_filled():
            if not collector.images:
                return False
            img = collector.images[-1][0]["Counter1"]
            return not np.any(np.isnan(img[0]))

        assert _wait_until(_first_row_filled)
        images, extents = collector.images[-1]
        img = images["Counter1"]
        assert img.shape == (ny, nx)
        np.testing.assert_allclose(img[0], [1.0, 2.0, 3.0, 4.0])
        assert np.all(np.isnan(img[1]))
        assert np.all(np.isnan(img[2]))
        assert extents == ([0.0, 10.0], [-5.0, 5.0])

        rows["Counter1"] = [[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]]
        rows["SampleY"] = [-5.0, 0.0]

        def _second_row_filled():
            if not collector.images:
                return False
            img = collector.images[-1][0]["Counter1"]
            return not np.any(np.isnan(img[1]))

        assert _wait_until(_second_row_filled)
        img = collector.images[-1][0]["Counter1"]
        np.testing.assert_allclose(img[1], [5.0, 6.0, 7.0, 8.0])
        assert np.all(np.isnan(img[2]))
    finally:
        streamer.stop()


def test_progress_counts_rows_done_and_total():
    ny, nx = 2, 3
    rows = {"Counter1": [[1.0, 2.0, 3.0]], "SampleY": [0.0]}
    stream = FakeStream(table_fn=lambda: dict(rows))
    run = FakeRun(_raster_md(ny, nx))
    run._primary = stream

    collector = _Collector()
    streamer = RunStreamer(
        _factory_for(run), "fake-uid",
        on_image=collector.on_image, on_progress=collector.on_progress,
        on_error=collector.on_error, poll_s=0.02, data_field="Counter1",
    )
    streamer.start()
    try:
        assert _wait_until(lambda: len(collector.progress) >= 1)
        done, total = collector.progress[-1]
        assert total == ny  # single-energy raster: rows_total == ny
        assert done == 1
    finally:
        streamer.stop()


def test_stop_halts_polling():
    stream = FakeStream(table={"Counter1": [], "SampleY": []})
    run = FakeRun(_raster_md())
    run._primary = stream

    collector = _Collector()
    streamer = RunStreamer(
        _factory_for(run), "fake-uid",
        on_image=collector.on_image, on_progress=collector.on_progress,
        on_error=collector.on_error, poll_s=0.02,
    )
    streamer.start()
    _wait_until(lambda: stream.read_count >= 2)
    streamer.stop()
    count_at_stop = stream.read_count
    time.sleep(0.15)
    assert stream.read_count <= count_at_stop + 1  # no further polls sneak in


def test_missing_primary_stream_reports_single_error_no_crash():
    run = FakeRun(_raster_md(), primary_exc=KeyError("primary"))

    collector = _Collector()
    streamer = RunStreamer(
        _factory_for(run), "fake-uid",
        on_image=collector.on_image, on_progress=collector.on_progress,
        on_error=collector.on_error, poll_s=0.02,
    )
    streamer.start()
    try:
        assert _wait_until(lambda: len(collector.errors) >= 1)
        time.sleep(0.1)
        assert len(collector.errors) == 1
        assert not collector.images
    finally:
        streamer.stop()


def test_malformed_table_reports_single_error_no_crash():
    stream = FakeStream(table_fn=lambda: {"unexpected": "not a table"})
    run = FakeRun(_raster_md())
    run._primary = stream

    collector = _Collector()
    streamer = RunStreamer(
        _factory_for(run), "fake-uid",
        on_image=collector.on_image, on_progress=collector.on_progress,
        on_error=collector.on_error, poll_s=0.02, data_field="Counter1",
    )
    streamer.start()
    try:
        assert _wait_until(lambda: len(collector.errors) >= 1)
        time.sleep(0.1)
        assert len(collector.errors) == 1
    finally:
        streamer.stop()


def test_energy_stack_shows_current_slice_modulo_ny():
    ny, nx, nE = 2, 3, 2
    start_md = {
        "plan_name": "stxm_energy_stack",
        "stxm": {
            "contract_version": 1,
            "shape": [nE, ny, nx],
            "energies": [270.0, 280.0],
            "x_extent": [0.0, 1.0],
            "y_extent": [0.0, 1.0],
        },
    }
    # 3 rows so far: iE=0,iy=0 ; iE=0,iy=1 ; iE=1,iy=0 (current slice = energy 1)
    rows = {
        "Counter1": [[1.0, 1.0, 1.0], [2.0, 2.0, 2.0], [3.0, 3.0, 3.0]],
        "SampleY": [0.0, 1.0, 0.0],
    }
    stream = FakeStream(table_fn=lambda: dict(rows))
    run = FakeRun(start_md)
    run._primary = stream

    collector = _Collector()
    streamer = RunStreamer(
        _factory_for(run), "fake-uid",
        on_image=collector.on_image, on_progress=collector.on_progress,
        on_error=collector.on_error, poll_s=0.02, data_field="Counter1",
    )
    streamer.start()
    try:
        assert _wait_until(lambda: len(collector.progress) >= 1
                            and collector.progress[-1][0] == 3)
        img = collector.images[-1][0]["Counter1"]
        assert img.shape == (ny, nx)
        np.testing.assert_allclose(img[0], [3.0, 3.0, 3.0])
        assert np.all(np.isnan(img[1]))
        done, total = collector.progress[-1]
        assert done == 3
        assert total == nE * ny
    finally:
        streamer.stop()

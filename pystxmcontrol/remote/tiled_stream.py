"""RunStreamer: poll a Tiled STXM run's primary stream into live image
payloads (spec #4 Task 6).

Run-layout rules transcribed from ``lightfall_pystxmcontrol/contract.py`` and
the read-side of ``lightfall_pystxmcontrol/stxm_map_viz.py`` (this module
imports NOTHING from that plugin package -- it only mirrors the layout):

- **Fly-raster runs** (``plans.py: stxm_fly_raster``) put ``shape: [ny, nx]``
  and ``x_extent``/``y_extent`` directly at the top level of the start doc
  (``run.metadata["start"]``). There is no ``stxm`` block. Row *r* (0-based,
  == the number of primary-stream table rows written so far, minus one) maps
  straight onto image row *r*.
- **Energy-stack runs** (``plans.py: stxm_energy_stack`` /
  ``contract.stxm_start_md``) nest ``shape: [nE, ny, nx]`` and
  ``x_extent``/``y_extent`` under ``start["stxm"]``. Row ordering follows
  ``contract.decode_line_index``: ``seq_num = iE*ny + iy + 1``, i.e. row *r*
  (0-based) decodes to ``iE, iy = divmod(r, ny)`` (transcribed here, not
  imported). v1 policy (this task): show the CURRENT energy slice only --
  the image is (ny, nx), each row's value coming from the highest ``iE``
  that has any data, rows within that slice indexed by ``iy``. This matches
  the "rows modulo ny" framing in the task brief and keeps the widget a
  plain 2-D map for both run kinds.
- Either way, ``run["primary"]`` is the stream node and **must** be read via
  its table facet (``stream.read()``), never a scalar column facet (Tiled
  gotcha: scalar facets 500/hang under concurrent writer appends). The table
  is a mapping of column name -> sequence, one entry per line-event row;
  ``data_field`` (default ``"Counter1"``) is the per-row length-``nx`` array
  column blitted into the image.

RunStreamer runs this poll on a background thread: pure Python, no Qt, no
lightfall imports. Tiled client objects arrive via ``tiled_client_factory``
and are used duck-typed (``factory() -> catalog``, ``catalog[run_uid] ->
run``, ``run["primary"] -> stream node``).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import numpy as np


class RunStreamer:
    """Background-thread poller: Tiled run primary stream -> live 2-D image.

    Args:
        tiled_client_factory: ``() -> catalog``-like object (e.g.
            ``LightfallClient.tiled_client()``); called once at ``start()``
            time on the background thread so a slow/failed Tiled connection
            never blocks the caller. ``catalog[run_uid]`` yields the run.
        run_uid: catalog key for the run (``catalog[run_uid]``).
        on_image: ``({data_field: ndarray(ny, nx)}, (x_extent, y_extent))``,
            invoked whenever the polled table has grown.
        on_progress: ``(rows_done, rows_total)``, invoked on every poll.
        on_error: ``(exc)``, invoked exactly once on the first failure
            (missing/malformed stream, bad metadata, factory/catalog errors);
            the poll loop then stops cleanly, never crashing the thread.
        poll_s: seconds between polls.
        data_field: table column blitted into the image.
    """

    def __init__(self, tiled_client_factory: Callable[[], Any], run_uid: str,
                 on_image: Callable[[dict, tuple], None],
                 on_progress: Callable[[int, int], None], *,
                 on_error: Callable[[BaseException], None] | None = None,
                 poll_s: float = 1.0, data_field: str = "Counter1") -> None:
        self._factory = tiled_client_factory
        self._run_uid = run_uid
        self._on_image = on_image
        self._on_progress = on_progress
        self._on_error = on_error
        self._poll_s = poll_s
        self._data_field = data_field

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._rows_done = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._poll_s + 2.0)

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        try:
            catalog = self._factory()
            run = catalog[self._run_uid]
            layout = self._resolve_layout(run)
        except Exception as exc:  # noqa: BLE001 - report, never crash
            self._report_error(exc)
            return

        while not self._stop_event.is_set():
            try:
                self._poll_once(run, layout)
            except Exception as exc:  # noqa: BLE001 - report, never crash
                self._report_error(exc)
                return
            self._stop_event.wait(self._poll_s)

    def _poll_once(self, run: Any, layout: "_Layout") -> None:
        stream = run["primary"]
        table = stream.read()
        column = table[self._data_field]
        rows_done = len(column)
        self._rows_done = rows_done

        image = _assemble_image(column, layout)
        self._on_image({self._data_field: image},
                        (layout.x_extent, layout.y_extent))
        self._on_progress(rows_done, layout.rows_total)

    def _report_error(self, exc: BaseException) -> None:
        if self._on_error is not None:
            self._on_error(exc)

    @staticmethod
    def _resolve_layout(run: Any) -> "_Layout":
        start = run.metadata["start"]
        stxm = start.get("stxm")
        if isinstance(stxm, dict):
            nE, ny, nx = (int(v) for v in stxm["shape"])
            return _Layout(ny=ny, nx=nx, n_energies=nE,
                            x_extent=list(stxm["x_extent"]),
                            y_extent=list(stxm["y_extent"]))
        ny, nx = (int(v) for v in start["shape"])
        return _Layout(ny=ny, nx=nx, n_energies=1,
                        x_extent=list(start["x_extent"]),
                        y_extent=list(start["y_extent"]))


class _Layout:
    """Resolved (ny, nx[, nE]) shape + extents for one run."""

    __slots__ = ("ny", "nx", "n_energies", "x_extent", "y_extent")

    def __init__(self, *, ny: int, nx: int, n_energies: int,
                 x_extent: list, y_extent: list) -> None:
        self.ny = ny
        self.nx = nx
        self.n_energies = n_energies
        self.x_extent = x_extent
        self.y_extent = y_extent

    @property
    def rows_total(self) -> int:
        return self.n_energies * self.ny


def _assemble_image(column: Any, layout: "_Layout") -> np.ndarray:
    """Build the (ny, nx) NaN-filled image for the current display slice.

    Single-energy (raster) runs: row *r* -> image row *r* directly.
    Multi-energy (stack) runs: rows decode via ``iE, iy = divmod(r, ny)``
    (contract.decode_line_index's rule, transcribed); v1 shows only the
    slice containing the most-recently-written row (the CURRENT energy),
    each row within that slice placed at ``iy``.
    """
    ny, nx = layout.ny, layout.nx
    image = np.full((ny, nx), np.nan, dtype=float)
    n_rows = len(column)
    if n_rows == 0:
        return image

    if layout.n_energies <= 1:
        rows = column[:ny]
        for r, line in enumerate(rows):
            _blit_row(image, r, line, nx)
        return image

    current_row = n_rows - 1
    current_iE, _ = divmod(current_row, ny)
    slice_start = current_iE * ny
    slice_end = slice_start + ny
    for r in range(slice_start, min(slice_end, n_rows)):
        _, iy = divmod(r, ny)
        _blit_row(image, iy, column[r], nx)
    return image


def _blit_row(image: np.ndarray, row: int, line: Any, nx: int) -> None:
    arr = np.asarray(line, dtype=float)
    if arr.shape != (nx,):
        raise ValueError(
            f"row {row}: expected a length-{nx} line, got shape {arr.shape}")
    image[row] = arr

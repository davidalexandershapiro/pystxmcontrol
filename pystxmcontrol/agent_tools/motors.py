"""Reading and moving motors, and single-point DAQ reads.

A mixin: ToolSet composes this with the other domains, so `self` is the whole
ToolSet and these methods may use any of its state or call any other tool.
"""

import logging
import os
import tempfile
import time

import numpy as np

from pystxmcontrol.controller.tool_registry import tool


log = logging.getLogger(__name__)


class MotorTools:
    """Reading and moving motors, and single-point DAQ reads."""

    @tool()
    def get_motor_position(self, axis: str) -> str:
        """Return the current position of a named motor.

        Args:
            axis: Motor name, e.g. 'SampleX'
        """
        if self._motors is None:
            self.get_config()
        if self._motors and axis not in self._motors:
            return f"Unknown motor '{axis}'. Call get_config() to see available motors."
        try:
            # Force a live hardware poll rather than serving the cached positions,
            # which go stale after every move/scan (get_config does not re-poll).
            pos = self._refresh_positions().get(axis)
            return f"Current position of {axis}: {round(float(pos), 4)}" if pos is not None \
                   else f"Position not available for {axis}"
        except Exception as e:
            return f"Failed to get position for {axis}: {e}"

    @tool(mutates_hardware=True)
    def move_motor(self, axis: str, pos: float) -> str:
        """Move a named motor to the given position.

        Args:
            axis: Motor name
            pos: Target position in µm (or degrees for rotation)
        """
        if self._motors is None:
            self.get_config()
        if self._motors and axis not in self._motors:
            return f"Unknown motor '{axis}'. Call get_config() for the motor list."
        try:
            response = self._client.send_message({"command": "moveMotor", "axis": axis, "pos": pos})
            if response and response.get('status'):
                return f"Successfully moved {axis} to {pos}"
            else:
                data = response.get('data', 'no details') if response else 'no response'
                return f"Move failed for {axis}: {data}"
        except Exception as e:
            return f"Failed to move {axis}: {e}"

    def _refresh_positions(self) -> dict:
        """Force a live hardware poll and update the cached positions.

        get_config() does NOT re-poll the motors server-side, so the cached
        positions go stale after every move/scan. getMotorPositions forces the
        server to call getPos() on each motor (which also refreshes the Energy
        motor's calibratedPosition used by autofocus). Falls back to the cache
        if the live poll fails.
        """
        try:
            self._positions = self._client.getMotorPositions()
        except Exception:
            if self._positions is None:
                self.get_config()
        return self._positions or {}

    def _motor_pos(self, axis: str) -> float | None:
        """Return a fresh float position for *axis* via a live hardware poll."""
        pos = self._refresh_positions().get(axis)
        try:
            return float(pos) if pos is not None else None
        except (TypeError, ValueError):
            return None

    @tool()
    def plot_motor_positions(self, axis: str, date: str | None = None,
                             start_date: str | None = None, end_date: str | None = None,
                             file_path: str | None = None) -> str:
        """Plot a motor's logged position history and return the saved image path.

        Reads the server's motor-history database, so it answers "was the energy drifting
        overnight?" without a scan. Give a time range one of three ways; a date range wins
        over a single date.

        Args:
            axis: motor name, e.g. 'Energy'.
            date: single date to plot, YYYY-MM-DD (default: today).
            start_date: start of a date range, YYYY-MM-DD.
            end_date: end of a date range, YYYY-MM-DD.
            file_path: where to save the PNG (default: a temporary file).
        """
        from pystxmcontrol.mcp.utilities import plot_motor_positions as _plot
        if self._motors is None:
            self.get_config()
        if self._motors and axis not in self._motors:
            return f"Unknown motor '{axis}'. Call get_config() to see available motors."
        main_cfg = getattr(self._client, "main_config", None) or {}
        db_base_dir = (main_cfg.get("server") or {}).get("data_dir")
        if not db_base_dir:
            return ("No motor-history database directory is configured "
                    "(server.data_dir), so position history cannot be plotted.")
        if file_path is None:
            file_path = os.path.join(tempfile.gettempdir(), f"{axis}_position_plot.png")
        try:
            img = _plot(axis, date=date, start_date=start_date, end_date=end_date,
                        db_base_dir=db_base_dir, file_path=file_path)
        except Exception as e:
            return f"Error generating plot for {axis}: {e}"
        if img and "No data found" in str(img):
            return str(img)
        return f"Saved {axis} position plot to {img}" if img else \
               f"Failed to generate a plot for {axis}"

    @tool(mutates_hardware=True)
    def read_daq(self, daq: str = "default", dwell: float = 100.0, shutter: bool = True) -> str:
        """Take a single-point DAQ reading without running a scan.

        Useful for checking beam intensity before committing to a full scan.

        Args:
            daq: DAQ channel name
            dwell: Integration time in ms
            shutter: Open shutter during measurement
        """
        try:
            response = self._client.send_message({
                "command": "get_data",
                "daq": daq,
                "dwell": dwell,
                "shutter": shutter,
            })
            value = response.get('data') if response else None
            scalar, n = self._daq_value_to_scalar(value)
            if scalar is None:
                return "No data returned from DAQ"
            suffix = f" (mean of {n} samples)" if n > 1 else ""
            return f"DAQ reading ({daq}, {dwell} ms): {round(scalar, 4)}{suffix}"
        except Exception as e:
            return f"DAQ read failed: {e}"

    @staticmethod
    def _daq_value_to_scalar(value):
        """Reduce a DAQ getPoint() result to (scalar, n_samples), or (None, 0).

        getPoint() shapes vary by DAQ: a bare scalar, a numpy array of raw samples
        (size 1 or more — float() on a size-≥1 array raises in modern numpy, which was
        the read_daq failure), or a {channel: array} dict for multi-channel counters.
        Reduce to a single mean intensity so read_daq can report one number.
        """
        if value is None:
            return None, 0
        # Multi-channel counters return {channel: array([...])}; pool all channels.
        if isinstance(value, dict):
            value = list(value.values())
        try:
            arr = np.asarray(value, dtype=float).reshape(-1)
        except (TypeError, ValueError):
            return None, 0
        if arr.size == 0:
            return None, 0
        return float(arr.mean()), int(arr.size)

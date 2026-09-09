"""Shared fixtures for the acquisition-dashboard GUI tests.

Building the window is the expensive part of these tests and several files need
it, so the stub server and the window fixture live here.  The window is built
headless against a stub controller carrying the real ScanModel/MotorModel and
the repo's own scan.json / daq.json, then attached through the same steps
``_go_live`` uses — so the view is built from config rather than from the
offline placeholder fallbacks.
"""

import json
import os
from pathlib import Path

import pytest

# Must be set before PySide6 imports a platform plugin: these tests run in CI and
# over SSH, where there is no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="GUI tests need PySide6")
pytest.importorskip("pyqtgraph", reason="the dashboard image area needs pyqtgraph")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pystxmcontrol.gui.dashboard import mainwindow as mwd  # noqa: E402
from pystxmcontrol.gui.models.image_model import ImageModel  # noqa: E402
from pystxmcontrol.gui.models.motor_model import MotorModel  # noqa: E402
from pystxmcontrol.gui.models.scan_model import ScanModel  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
GOLDEN_DIR = Path(__file__).parent / "data" / "dashboard_scans"

UPDATE_GOLDEN = os.environ.get("PYSTXM_UPDATE_GOLDEN") == "1"


# ── stub server side ────────────────────────────────────────────────────────

class StubClient:
    """Stands in for ``stxm_client``: config dictionaries and nothing else.

    ``main_config`` deliberately carries no ``source.beamline``, which is what
    the window checks before calling the ALS ESAF API — so building the window
    never reaches the network.
    """

    def __init__(self, scan_config, daq_config):
        self.scanConfig = scan_config
        self.daqConfig = daq_config
        self.main_config = {}
        self.currentMotorPositions = {}


class StubController(QObject):
    """The slice of ``MainController`` the dashboard actually touches.

    The signal list mirrors ``MainController`` exactly (same names, same
    signatures) so ``_connect_controller_signals`` succeeds unchanged; the models
    are the real ones, because they are pure state holders and compiling against
    a fake would defeat the point of the snapshot.
    """

    motor_position_updated = Signal(str, float)
    motor_status_updated = Signal(str, bool)
    image_updated = Signal(object)
    scan_progress_updated = Signal(str)
    scan_file_updated = Signal(str)
    error_occurred = Signal(str)
    status_updated = Signal(str)
    monitor_data_updated = Signal()
    daq_value_updated = Signal(float)
    scan_state_changed = Signal(bool)
    estimated_time_updated = Signal(float)
    elapsed_time_updated = Signal(float)
    external_scan_started = Signal(str)
    shutter_state_changed = Signal(str)
    scan_region_geometry_updated = Signal(dict, str)

    def __init__(self, scan_config, daq_config, motor_info):
        super().__init__()
        self.client = StubClient(scan_config, daq_config)
        self.scan_model = ScanModel()
        self.motor_model = MotorModel()
        self.image_model = ImageModel()
        self.motor_model.set_motor_info(motor_info)
        # Deterministic "current" positions: several compile paths centre a
        # region on wherever a motor happens to be.
        for name in motor_info:
            self.motor_model.update_position(name, 0.0)
        self.scanning = False
        self.errors = []
        self.error_occurred.connect(self.errors.append)

    def get_scan_model(self):
        return self.scan_model

    def get_motor_model(self):
        return self.motor_model

    def get_image_model(self):
        return self.image_model

    def get_available_scan_types(self):
        return [k for k, v in self.client.scanConfig.items()
                if v.get("display", False)]

    # Nothing in these tests may reach hardware.
    def start_scan(self, preview=False):
        raise AssertionError("start_scan must not be called by a compile test")

    def cancel_scan(self):
        raise AssertionError("cancel_scan must not be called by a compile test")

    def move_motor(self, *a, **k):
        raise AssertionError("move_motor must not be called by a compile test")

    def jog_motor(self, *a, **k):
        raise AssertionError("jog_motor must not be called by a compile test")

    def set_gate(self, *a, **k):
        pass

    def handle_motor_config_change(self, *a, **k):
        pass

    def quit_application(self):
        pass


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dashboard(qapp, monkeypatch):
    """A dashboard window wired to the stub controller, built offline.

    Three pieces of machine state are neutralised first, or the snapshots would
    depend on the box the tests run on:

    * ``_maybe_connect_controller`` / ``_server_endpoint`` — otherwise a window
      built where the real control server *is* running connects to it, and
      starts a heartbeat thread that keeps trying.
    * ``find_last_scan_file`` — ``_show_last_scan_image`` seeds ``Region1``
      (and, through it, the focus/line geometry) from the most recent ``.stxm``
      file in the data directory, so a developer's last scan would leak into the
      compiled dict.  Patched on ``dashboard.mainwindow``, where it is looked
      up, rather than on the module that now defines it.

    The controller is then attached through the same steps ``_go_live`` uses, so
    the view is built from the stub's config exactly as a live one would be.
    """
    monkeypatch.setattr(mwd.MainWindowDashboard, "_maybe_connect_controller",
                        lambda self, live: None)
    monkeypatch.setattr(mwd.MainWindowDashboard, "_server_endpoint",
                        lambda self: (None, None))
    monkeypatch.setattr(mwd, "find_last_scan_file", lambda: None)

    with open(CONFIG_DIR / "scan.json") as f:
        scan_config = json.load(f)
    with open(CONFIG_DIR / "daq.json") as f:
        daq_config = json.load(f)
    with open(CONFIG_DIR / "motor.json") as f:
        motor_info = json.load(f)

    win = mwd.MainWindowDashboard(live=False)
    win.controller = StubController(scan_config, daq_config, motor_info)
    win._adopt_server_config(win.controller)
    win._rebuild_acquisition_view()
    win._connect_controller_signals()
    win._seed_from_controller()

    # A proposal is normally chosen from the ALS list; pin one so the compiled
    # dict does not depend on what the API happened to return.
    win._proposal_combo.addItem("TEST-0000")
    win._proposal_combo.setCurrentText("TEST-0000")
    win._esaf_participants["TEST-0000"] = ["Test Experimenter"]
    win._sample_field.setText("golden sample")
    if getattr(win, "_comment_field", None) is not None:
        win._comment_field.setText("golden comment")

    yield win

    if win.server_heartbeat is not None:      # defensive: patched off above
        win.server_heartbeat.stop()
        win.server_heartbeat.wait(2000)
    win.controller = None
    win.close()
    win.deleteLater()



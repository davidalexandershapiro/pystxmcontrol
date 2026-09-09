"""Characterization tests for the acquisition dashboard's scan compiler.

These are *golden-output* tests, written to protect a refactor rather than to
specify new behaviour: they drive ``MainWindowDashboard`` through each supported
scan type and snapshot the scan dictionary it compiles into the scan model.  The
recorded dictionaries in ``tests/data/dashboard_scans/`` are exactly what the
dashboard produced before ``mainwindow_dashboard.py`` was split up, so any phase
of that split which changes what the server would be asked to run shows up here
as a diff instead of as a surprise on the beamline.

Nothing here asserts that a given value is *correct* — only that it has not
changed.  If a change is intentional, regenerate the snapshots with::

    PYSTXM_UPDATE_GOLDEN=1 pytest tests/test_dashboard_compile.py

and review the resulting diff as part of the change.

The window is built against a stub controller rather than a live server, so the
real ``ScanModel`` does the compiling (it is a plain QObject dict wrapper — no
hardware, no ZMQ) while ``scanConfig``/``daqConfig`` come from the repo's own
``config/*.json``.  That keeps the snapshots reproducible on any machine.
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

from pystxmcontrol.gui import mainwindow_dashboard as mwd  # noqa: E402
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
      compiled dict.  Patched on ``mainwindow_dashboard``, where it is looked
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


# ── helpers ─────────────────────────────────────────────────────────────────

def set_spatial(win, xc=1.0, yc=-2.0, xr=10.0, yr=8.0, xn=40, yn=32):
    """Type a SampleX/SampleY grid into the fields and let the view react."""
    for name, c, rng, n in (("SampleX", xc, xr, xn), ("SampleY", yc, yr, yn)):
        f = win._spatial_fields[name]
        f["center"].setText(f"{c}")
        f["range"].setText(f"{rng}")
        f["npts"].setText(f"{n}")
    win._on_spatial_edit()


def set_energy(win, start=280.0, stop=290.0, step=0.5, dwell=2.0):
    for key, val in (("start", start), ("stop", stop),
                     ("step", step), ("dwell", dwell)):
        win._energy_fields[key].setText(f"{val}")
    win._recompute_energy_n()
    win._sync_active_energy_region()


def compile_scan(win):
    """Compile the current view and return the scan dict, failing on error."""
    ok = win._compile_scan()
    assert ok, f"compile failed: {win.controller.errors}"
    assert not win.controller.errors, f"compile errors: {win.controller.errors}"
    return win.controller.get_scan_model().to_dict()


def assert_matches_golden(name, produced):
    """Compare against the recorded snapshot, or record it when regenerating."""
    path = GOLDEN_DIR / f"{name}.json"
    # Round-trip through JSON so tuples/numpy scalars compare as what a snapshot
    # can actually hold.
    produced = json.loads(json.dumps(produced, default=str, sort_keys=True))
    if UPDATE_GOLDEN:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(produced, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"regenerated golden snapshot {path.name}")
    if not path.exists():
        pytest.fail(f"no golden snapshot {path.name} — run with "
                    f"PYSTXM_UPDATE_GOLDEN=1 to record it")
    assert produced == json.loads(path.read_text())


# ── tests ───────────────────────────────────────────────────────────────────

def test_window_builds_against_stub_controller(dashboard):
    """The view adopts the stub's scan.json rather than the offline placeholder
    list — without this the compile tests would exercise fallback paths only."""
    types = [dashboard.scan_type.itemText(i)
             for i in range(dashboard.scan_type.count())]
    assert types == dashboard.controller.get_available_scan_types()


def test_image_scan(dashboard):
    dashboard.scan_type.setCurrentText("Image")
    set_spatial(dashboard)
    set_energy(dashboard)
    assert_matches_golden("image", compile_scan(dashboard))


def test_image_scan_multi_region(dashboard):
    """Two spatial regions and two energy regions: the multi-region path that
    carries per-region dwell through to the server."""
    dashboard.scan_type.setCurrentText("Image")
    set_spatial(dashboard)
    set_energy(dashboard)
    dashboard._add_spatial_region()
    set_spatial(dashboard, xc=20.0, yc=15.0, xr=4.0, yr=4.0, xn=16, yn=16)
    dashboard._add_energy_region()
    set_energy(dashboard, start=700.0, stop=710.0, step=1.0, dwell=5.0)
    assert_matches_golden("image_multi_region", compile_scan(dashboard))


def test_focus_scan(dashboard):
    # The focus line is centred on Region 1, so pin Region 1 rather than
    # inheriting the spatial page's placeholder defaults.
    set_spatial(dashboard)
    dashboard.scan_type.setCurrentText("Focus")
    set_energy(dashboard, start=520.0, stop=520.0, step=0.0, dwell=1.0)
    dashboard._line_fields["length"].setText("12.0")
    dashboard._line_fields["angle"].setText("30.0")
    dashboard._on_line_edit()
    dashboard._focus_fields["center"].setText("0.5")
    dashboard._focus_fields["range"].setText("40.0")
    dashboard._focus_fields["points"].setText("25")
    dashboard._on_focus_edit()
    assert_matches_golden("focus", compile_scan(dashboard))


def test_line_spectrum_scan(dashboard):
    set_spatial(dashboard)
    dashboard.scan_type.setCurrentText("Line Spectrum")
    set_energy(dashboard)
    dashboard._line_fields["length"].setText("6.0")
    dashboard._line_fields["angle"].setText("0.0")
    dashboard._on_line_edit()
    assert_matches_golden("line_spectrum", compile_scan(dashboard))


def test_single_motor_scan(dashboard):
    dashboard.scan_type.setCurrentText("Single Motor")
    set_energy(dashboard, start=280.0, stop=280.0, step=0.0, dwell=1.0)
    ax = dashboard._motor_axis_widgets[0]
    ax["center"].setText("0.0")
    ax["range"].setText("2.0")
    ax["npts"].setText("21")
    dashboard._on_motor_edit()
    assert_matches_golden("single_motor", compile_scan(dashboard))


def test_double_motor_scan(dashboard):
    dashboard.scan_type.setCurrentText("Double Motor")
    set_energy(dashboard, start=280.0, stop=280.0, step=0.0, dwell=1.0)
    for widgets, rng, npts in ((dashboard._motor_axis_widgets[0], 2.0, 21),
                               (dashboard._motor_axis_widgets[1], 1.0, 11)):
        widgets["center"].setText("0.0")
        widgets["range"].setText(f"{rng}")
        widgets["npts"].setText(f"{npts}")
    dashboard._on_motor_edit()
    assert_matches_golden("double_motor", compile_scan(dashboard))


def test_preview_does_not_disturb_the_full_definition(dashboard):
    """A preview compiles one region at one energy but must leave the view's
    region lists alone, so the next full compile is unchanged."""
    dashboard.scan_type.setCurrentText("Image")
    set_spatial(dashboard)
    set_energy(dashboard)
    dashboard._add_spatial_region()
    set_spatial(dashboard, xc=20.0, yc=15.0, xr=4.0, yr=4.0, xn=16, yn=16)
    full_before = compile_scan(dashboard)

    assert dashboard._compile_scan(preview=True)
    preview = dashboard.controller.get_scan_model().to_dict()
    assert len(preview["scan_regions"]) == 1
    assert preview["loop_scan"] is False

    assert compile_scan(dashboard) == full_before


def test_unsupported_scan_type_is_refused(dashboard):
    """OSA Focus is in scan.json but its driver is not in the dashboard's
    supported set — it must fail loudly rather than compile something wrong."""
    dashboard.scan_type.setCurrentText("OSA Focus")
    assert dashboard._compile_scan() is False
    assert dashboard.controller.errors

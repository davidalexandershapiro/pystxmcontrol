"""Window-level behaviour of the acquisition dashboard.

The unit tests elsewhere cover the logic modules directly; these cover the thin
layer where the window *calls* them, which is where a refactor slip shows up.
The staff-mode tests exist because that path is only reachable by clicking a
button and answering a dialog, so nothing else exercises it — a stray
``@staticmethod`` left on ``_check_staff_password`` by an earlier refactor
shipped undetected until someone pressed the button.

The window fixture lives in ``conftest.py``.
"""

import ast
import inspect
from pathlib import Path

import numpy as np
import pytest

from PySide6.QtWidgets import (
    QInputDialog, QLineEdit, QMainWindow, QMessageBox,
)

from pystxmcontrol.gui.dashboard import staff_auth as auth
from pystxmcontrol.gui.dashboard.mainwindow import MainWindowDashboard


# ── method binding ──────────────────────────────────────────────────────────

def test_no_staticmethod_takes_self():
    """A ``@staticmethod`` whose first parameter is ``self`` is always a bug —
    usually a decorator orphaned by a cut that started one line too low.  It
    only fails when the method is called, which for dialog-driven code can be
    long after the change."""
    offenders = []
    for name, member in vars(MainWindowDashboard).items():
        if not isinstance(member, staticmethod):
            continue
        params = list(inspect.signature(member.__func__).parameters)
        if params and params[0] == "self":
            offenders.append(name)
    assert offenders == []


def _assigned_self_attrs(node):
    """Every ``self.X`` the class ever assigns — including through tuple
    unpacking, for-loop targets and ``with ... as``, all of which real code
    here uses."""
    found = set()

    def target(t):
        if isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                target(e)
        elif isinstance(t, ast.Starred):
            target(t.value)
        elif (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                and t.value.id == "self"):
            found.add(t.attr)

    for n in ast.walk(node):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                target(t)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            target(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            target(n.target)
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            target(n.optional_vars)
    return found


def test_no_call_to_a_method_the_window_no_longer_has():
    """Every ``self.X`` resolves to something the class defines, assigns, or
    inherits.

    Moving a method into a panel and missing one call site leaves an
    AttributeError that only fires on the path that calls it — during a scan,
    in the case that prompted this test.  Neither pyflakes nor an import check
    sees it.
    """
    source = Path(inspect.getfile(MainWindowDashboard)).read_text()
    cls = next(n for n in ast.parse(source).body
               if isinstance(n, ast.ClassDef)
               and n.name == "MainWindowDashboard")

    defined = {n.name for n in cls.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for n in cls.body:
        if isinstance(n, ast.Assign):
            defined |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    defined |= _assigned_self_attrs(cls)
    defined |= set(dir(QMainWindow))          # inherited Qt API

    missing = sorted({
        n.attr for n in ast.walk(cls)
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
        and n.value.id == "self" and n.attr not in defined
    })
    assert missing == []


def test_every_method_can_be_bound():
    """Each plain function attribute takes something as its first parameter.
    A zero-argument method on a class can never be called on an instance."""
    zero_arg = [
        name for name, member in vars(MainWindowDashboard).items()
        if inspect.isfunction(member)
        and not list(inspect.signature(member).parameters)
    ]
    assert zero_arg == []


# ── staff mode ──────────────────────────────────────────────────────────────

@pytest.fixture
def stored_password(monkeypatch, tmp_path):
    """Point the credential at a temp main.json carrying a known password, so
    the developer's real config is never read or written."""
    path = tmp_path / "main.json"
    auth.write_config(auth.set_password({}, "letmein"), path=path)
    monkeypatch.setattr(auth, "config_path", lambda: str(path))
    return path


def answer_password(monkeypatch, text, ok=True):
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: (text, ok)))


def test_entering_staff_mode_requires_the_password(dashboard, stored_password,
                                                   monkeypatch):
    assert dashboard._expert is False
    answer_password(monkeypatch, "letmein")
    dashboard._toggle_expert()
    assert dashboard._expert is True


def test_a_wrong_password_does_not_enter_staff_mode(dashboard, stored_password,
                                                    monkeypatch):
    answer_password(monkeypatch, "nope")
    dashboard._toggle_expert()
    assert dashboard._expert is False


def test_cancelling_the_prompt_does_not_enter_staff_mode(dashboard,
                                                         stored_password,
                                                         monkeypatch):
    answer_password(monkeypatch, "letmein", ok=False)
    dashboard._toggle_expert()
    assert dashboard._expert is False


def test_leaving_staff_mode_needs_no_password(dashboard, stored_password,
                                              monkeypatch):
    answer_password(monkeypatch, "letmein")
    dashboard._toggle_expert()
    assert dashboard._expert is True
    # Dropping back must not prompt at all: make any prompt an error.
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(
        lambda *a, **k: pytest.fail("leaving staff mode must not prompt")))
    dashboard._toggle_expert()
    assert dashboard._expert is False


def test_declining_to_set_a_first_password_stays_in_user_mode(
        dashboard, monkeypatch, tmp_path):
    """With no password configured the window offers to set one; saying no must
    not grant access."""
    monkeypatch.setattr(auth, "config_path", lambda: str(tmp_path / "none.json"))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    dashboard._toggle_expert()
    assert dashboard._expert is False


def test_staff_mode_reveals_the_hidden_motors(dashboard, stored_password,
                                              monkeypatch):
    """The visible effect of staff mode: the rail lists `display: false` motors
    that User mode hides."""
    group = dashboard._motor_groups()[0]
    user_rows = len(dashboard._motor_rows(group))
    answer_password(monkeypatch, "letmein")
    dashboard._toggle_expert()
    assert len(dashboard._motor_rows(group)) >= user_rows


def test_setting_a_password_writes_it_where_the_check_reads_it(
        dashboard, monkeypatch, tmp_path):
    path = tmp_path / "main.json"
    monkeypatch.setattr(auth, "config_path", lambda: str(path))
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("newpass", True)))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    dashboard.set_staff_password()
    assert auth.verify_password("newpass", auth.read_config(path=path))


def test_the_password_dialog_masks_input(dashboard, stored_password, monkeypatch):
    """A staff password typed in the clear on a shared beamline screen defeats
    the point of having one."""
    seen = {}

    def capture(*args, **kwargs):
        seen["echo"] = args[3] if len(args) > 3 else kwargs.get("echo")
        return ("letmein", True)

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(capture))
    dashboard._toggle_expert()
    assert seen["echo"] == QLineEdit.Password


# ── the live curve of a single-motor scan ───────────────────────────────────
#
# The server stores a single-motor scan at ``interp_counts[ch][region][m, 0, i]``
# and publishes only the current energy's ``[m, :, :]`` slice.  A spatial scan
# fills ``i`` across one slice, so the published frame is the whole curve.  An
# Energy scan holds ``i`` at 0 and advances ``m``, so every frame carries a
# single filled element — the curve only exists down the energy axis of the
# stack, which is why it must be read from there.

class FakeLive:
    def __init__(self, n_energies, x_points):
        self.interp_counts = {"default": [np.zeros((n_energies, 1, x_points))]}


def setup_motor_scan(win, motor, center, rng, npts):
    win.scan_type.setCurrentText("Single Motor")
    ax = win._motor_axis_widgets[0]
    ax["combo"].setCurrentText(motor)
    ax["center"].setText(str(center))
    ax["range"].setText(str(rng))
    ax["npts"].setText(str(npts))
    win._on_motor_edit()


def run_energy_scan(win, energies):
    """Feed frames exactly as _write_single_motor publishes them."""
    live = FakeLive(len(energies), len(energies))
    win.controller._live_stxm = live
    im = win.controller.get_image_model()
    im.set("energy_list", list(energies))
    im.set("channel_key", "default")
    im.set("scan_region_index", "Region1")
    cube = live.interp_counts["default"][0]
    for m, _e in enumerate(energies):
        cube[m, 0, 0] = (m + 1) * 10.0
        im.set("energy_index", m)
        win._on_image(cube[m, :, :])
        yield win.image_area.plot_curve.getData()


def test_energy_motor_curve_grows_with_each_energy(dashboard):
    """The reported bug: the plot froze after the first point while the energy
    readout kept advancing."""
    energies = [700.0, 705.0, 710.0, 715.0, 720.0]
    setup_motor_scan(dashboard, "Energy", 710.0, 20.0, len(energies))
    lengths = [len(x) for x, _y in run_energy_scan(dashboard, energies)]
    assert lengths == [1, 2, 3, 4, 5]


def test_energy_motor_curve_is_plotted_against_energy(dashboard):
    energies = [700.0, 705.0, 710.0]
    setup_motor_scan(dashboard, "Energy", 705.0, 10.0, len(energies))
    x = y = None
    for x, y in run_energy_scan(dashboard, energies):
        pass
    assert list(x) == energies
    assert list(y) == [10.0, 20.0, 30.0]
    assert dashboard.image_area.plot_item.getAxis("bottom").labelText == "Energy (eV)"


def test_unmeasured_energies_are_not_drawn_as_zeros(dashboard):
    """Drawing the whole stack would trail a flat line at zero ahead of the
    scan and wreck the autoscale."""
    energies = [700.0, 705.0, 710.0, 715.0]
    setup_motor_scan(dashboard, "Energy", 707.5, 15.0, len(energies))
    for i, (x, y) in enumerate(run_energy_scan(dashboard, energies)):
        assert len(x) == i + 1
        assert 0.0 not in list(y)


def test_a_spatial_single_motor_curve_still_comes_from_the_frame(dashboard):
    """The other branch is unchanged: one slice filled across, plotted against
    the motor's position."""
    setup_motor_scan(dashboard, "ZonePlateZ", 0.0, 2.0, 5)
    im = dashboard.controller.get_image_model()
    im.set("x_center", 0.0)
    im.set("x_range", 2.0)
    frame = np.zeros((1, 5))
    frame[0, :3] = [1.0, 2.0, 3.0]
    dashboard._on_image(frame)
    x, y = dashboard.image_area.plot_curve.getData()
    assert len(x) == 5
    assert list(x) == pytest.approx([-1.0, -0.5, 0.0, 0.5, 1.0])
    assert dashboard.image_area.plot_item.getAxis("bottom").labelText.startswith("ZonePlateZ")


def test_the_energy_curve_survives_a_missing_live_stack(dashboard):
    """Before the first frame arrives there is no stack; the placer must fall
    back rather than raise inside _on_image, which swallows exceptions."""
    setup_motor_scan(dashboard, "Energy", 710.0, 20.0, 5)
    dashboard.controller._live_stxm = None
    dashboard._on_image(np.zeros((1, 5)))      # must not raise

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

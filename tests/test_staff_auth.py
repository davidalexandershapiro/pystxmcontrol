"""Tests for the dashboard's staff-mode password.

Staff mode unhides motors users should not drive by accident and unlocks
editing of the beamline parameter database, so the paths that can wrongly
return True are what matter here: no password set, a malformed salt, an empty
entry.  None of them may read as a successful login.
"""

import json

import pytest

from pystxmcontrol.gui.dashboard import staff_auth as auth


@pytest.fixture
def cfg():
    return auth.set_password({}, "correct horse battery staple")


# ── setting a password ──────────────────────────────────────────────────────

def test_setting_a_password_stores_a_hash_and_a_salt():
    c = auth.set_password({}, "hunter2")
    assert auth.has_password(c)
    assert c[auth.HASH_KEY] and c[auth.SALT_KEY]


def test_the_password_itself_is_never_stored():
    c = auth.set_password({}, "hunter2")
    assert "hunter2" not in json.dumps(c)


def test_other_config_keys_survive():
    """main.json holds the instrument config too — setting a password must not
    drop it."""
    c = auth.set_password({"server": {"command_port": 9999}}, "pw")
    assert c["server"] == {"command_port": 9999}


def test_the_original_config_is_not_mutated():
    original = {"server": {}}
    auth.set_password(original, "pw")
    assert auth.HASH_KEY not in original


def test_each_set_uses_a_fresh_salt():
    """The same password twice must not produce the same stored hash."""
    a = auth.set_password({}, "same")
    b = auth.set_password({}, "same")
    assert a[auth.SALT_KEY] != b[auth.SALT_KEY]
    assert a[auth.HASH_KEY] != b[auth.HASH_KEY]


# ── verifying ───────────────────────────────────────────────────────────────

def test_the_right_password_is_accepted(cfg):
    assert auth.verify_password("correct horse battery staple", cfg) is True


def test_a_wrong_password_is_refused(cfg):
    assert auth.verify_password("wrong", cfg) is False


def test_verification_is_case_sensitive(cfg):
    assert auth.verify_password("Correct Horse Battery Staple", cfg) is False


def test_an_empty_password_is_refused(cfg):
    """Dialogs can return an empty string; it must never authenticate."""
    assert auth.verify_password("", cfg) is False
    assert auth.verify_password(None, cfg) is False


def test_nothing_authenticates_when_no_password_is_set():
    assert auth.verify_password("anything", {}) is False
    assert auth.verify_password("", {}) is False


@pytest.mark.parametrize("broken", [
    {auth.HASH_KEY: "abc"},                              # salt missing
    {auth.SALT_KEY: "abc"},                              # hash missing
    {auth.HASH_KEY: "abc", auth.SALT_KEY: "not-hex"},    # unusable salt
    {auth.HASH_KEY: "abc", auth.SALT_KEY: ""},           # empty salt
])
def test_a_damaged_credential_refuses_rather_than_crashing(broken):
    assert auth.has_password(broken) is False or \
        auth.verify_password("x", broken) is False


def test_half_a_credential_is_not_a_password():
    assert auth.has_password({auth.HASH_KEY: "abc"}) is False
    assert auth.has_password({auth.SALT_KEY: "abc"}) is False
    assert auth.has_password({}) is False


def test_a_password_survives_a_round_trip_through_the_config_file(tmp_path):
    path = tmp_path / "main.json"
    auth.write_config(auth.set_password({"other": 1}, "pw"), path=path)
    loaded = auth.read_config(path=path)
    assert loaded["other"] == 1
    assert auth.verify_password("pw", loaded) is True
    assert auth.verify_password("no", loaded) is False


# ── reading config ──────────────────────────────────────────────────────────

def test_a_missing_config_is_empty_not_an_error(tmp_path):
    """A fresh install or dev checkout simply has no password yet."""
    assert auth.read_config(path=tmp_path / "nope.json") == {}


def test_unreadable_json_is_empty_not_an_error(tmp_path):
    path = tmp_path / "main.json"
    path.write_text("{not json")
    assert auth.read_config(path=path) == {}


def test_a_failed_write_is_reported(tmp_path):
    """Silently losing a password change would be worse than an error."""
    with pytest.raises(Exception):
        auth.write_config({}, path=tmp_path / "no-such-dir" / "main.json")


# ── hashing ─────────────────────────────────────────────────────────────────

def test_hashing_is_deterministic_for_a_given_salt():
    salt = b"\x01" * auth.SALT_BYTES
    assert auth.hash_password("pw", salt) == auth.hash_password("pw", salt)


def test_different_salts_give_different_hashes():
    assert auth.hash_password("pw", b"\x01" * 32) != \
        auth.hash_password("pw", b"\x02" * 32)


def test_the_iteration_count_is_not_lowered_by_accident():
    """A drop here would weaken every stored credential; make it a deliberate,
    visible change."""
    assert auth.HASH_ITERATIONS >= 260000

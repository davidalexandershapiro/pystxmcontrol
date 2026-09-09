"""The staff-mode password: where it is stored, and how it is checked.

Split out of ``mainwindow_dashboard``.  Staff mode unhides motors that users
should not drive by accident and lets the beamline parameter database be
edited, so the check is worth keeping in one place with tests around it rather
than inline among the dialogs that prompt for it.

The credential itself is a PBKDF2-HMAC-SHA256 hash with a per-installation
random salt, both stored in the runtime ``main.json`` beside the rest of the
instrument config.  This guards against shoulder-surfing and casual snooping on
a shared beamline account — it is not a security boundary against someone who
can already write to the config file or the motor server.

The functions here do no prompting: the window owns the dialogs, and passes the
typed string in.  That split is what lets the verification be tested.
"""

import hashlib
import hmac
import json
import os
import sys

HASH_ITERATIONS = 260000
SALT_BYTES = 32

HASH_KEY = "staff_password_hash"
SALT_KEY = "staff_password_salt"


def config_path():
    """The runtime ``main.json`` the server also reads."""
    return os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json")


def read_config(path=None):
    """The config as a dict, or ``{}`` when it cannot be read.

    A missing or unreadable file is normal (a fresh install, a dev checkout), so
    it is not an error — it simply means no password has been set yet.
    """
    try:
        with open(path or config_path()) as f:
            return json.load(f)
    except Exception:
        return {}


def write_config(data, path=None):
    """Write the config back.  Raises on failure so the caller can report it —
    silently losing a password change would be worse than an error dialog."""
    with open(path or config_path(), "w") as f:
        json.dump(data, f, indent=4)


def hash_password(password, salt):
    """PBKDF2-HMAC-SHA256 of ``password`` with ``salt`` (bytes), as hex."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, HASH_ITERATIONS).hex()


def has_password(cfg):
    """True when the config carries a usable hash *and* its salt.  Either one
    alone cannot verify anything, so both must be present."""
    return bool(cfg.get(HASH_KEY) and cfg.get(SALT_KEY))


def verify_password(password, cfg):
    """Check ``password`` against the stored hash.

    False when no password is set, when the stored salt is malformed, or when
    the password is empty — never let any of those read as a successful login.
    """
    if not password or not has_password(cfg):
        return False
    try:
        salt = bytes.fromhex(cfg[SALT_KEY])
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(hash_password(password, salt), cfg[HASH_KEY])


def set_password(cfg, password):
    """Return a copy of ``cfg`` carrying a hash of ``password`` under a freshly
    generated salt.  A new salt every time means setting the same password twice
    does not produce the same stored hash."""
    salt = os.urandom(SALT_BYTES)
    updated = dict(cfg)
    updated[HASH_KEY] = hash_password(password, salt)
    updated[SALT_KEY] = salt.hex()
    return updated

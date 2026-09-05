"""Build hook only — all packaging metadata lives in pyproject.toml.

This file used to duplicate the metadata (packages, entry points, dependencies, data
files) and had drifted from pyproject.toml, which silently wins: its package list had
not gained agent_tools, gui/controllers or gui/models; it declared console scripts that
were never installed; and it pinned numpy<2.0, which is not what gets applied. Reading
it gave a wrong picture of the build. What remains is the one thing pyproject.toml
cannot express: a post-install hook for the Linux desktop launcher.
"""

import os
import subprocess
import sys

from setuptools import setup
from setuptools.command.develop import develop
from setuptools.command.install import install

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def _install_desktop_file():
    """Install a freedesktop .desktop launcher.  Linux only, and never fatal.

    A .desktop file means nothing on macOS or Windows, and update-desktop-database does
    not exist there — check=False suppresses a non-zero exit but NOT the
    FileNotFoundError from a missing executable, which failed the whole wheel build.
    Installing the package must not depend on the desktop environment.
    """
    if not sys.platform.startswith("linux"):
        return
    try:
        icon_path = os.path.join(_REPO_ROOT, "pystxmcontrol", "gui", "icons",
                                 "pystxmcontrol_icon.png")
        desktop_dir = os.path.expanduser("~/.local/share/applications")
        os.makedirs(desktop_dir, exist_ok=True)
        desktop_path = os.path.join(desktop_dir, "pystxmcontrol.desktop")
        with open(desktop_path, "w") as f:
            f.write(
                "[Desktop Entry]\n"
                "Name=pystxmControl\n"
                # The console script from pyproject.toml, not a module path: python -m
                # would need the right interpreter on PATH, which a launcher has no way
                # to guarantee.
                "Exec=stxmcontrol\n"
                f"Icon={icon_path}\n"
                "Type=Application\n"
                "Categories=Science;\n"
            )
        subprocess.run(["update-desktop-database", desktop_dir], check=False)
        print(f"Installed desktop file: {desktop_path}")
    except Exception as e:                      # never fail an install over a launcher
        print(f"Skipped desktop file: {e}")


class _PostInstall(install):
    def run(self):
        super().run()
        _install_desktop_file()


class _PostDevelop(develop):
    def run(self):
        super().run()
        _install_desktop_file()


setup(cmdclass={"install": _PostInstall, "develop": _PostDevelop})

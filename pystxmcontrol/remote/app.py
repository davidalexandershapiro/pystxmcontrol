"""``stxmcontrol-remote`` entry point: the pystxmcontrol GUI wired to a
Lightfall RemoteBackend instead of David's legacy ZMQ server (spec #4 Task 7).

Usage::

    stxmcontrol-remote [--config path/to/remote.json]

``--config`` defaults to the packaged ``remote.json`` sitting alongside this
module: ``{"nats_url": "nats://127.0.0.1:4222", "prefix": "als.stxm",
"app_name": "pystxmcontrol-remote"}``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PySide6 import QtWidgets

from pystxmcontrol.gui.controllers.main_controller import MainController
from pystxmcontrol.gui.mainwindow_mvc import MainWindowMVC
from pystxmcontrol.remote.client import LightfallClient
from pystxmcontrol.remote.qt_bridge import RemoteBackend

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "remote.json"


def _load_config(path: str | None) -> dict:
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    with open(config_path) as f:
        return json.load(f)


def _show_auth_failure_dialog(message: str) -> bool:
    """Show a modal retry/quit dialog for an auth failure.

    Returns True if the user chose Retry, False if they chose Quit.
    """
    box = QtWidgets.QMessageBox()
    box.setIcon(QtWidgets.QMessageBox.Critical)
    box.setWindowTitle("Authentication failed")
    box.setText(f"Failed to authenticate with Lightfall:\n{message}")
    retry_button = box.addButton("Retry", QtWidgets.QMessageBox.AcceptRole)
    box.addButton("Quit", QtWidgets.QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is retry_button


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stxmcontrol-remote")
    parser.add_argument(
        "--config", default=None,
        help="Path to a remote-GUI config JSON "
             "(default: packaged pystxmcontrol/remote/remote.json)")
    args = parser.parse_args(argv)

    config = _load_config(args.config)

    app = QtWidgets.QApplication(sys.argv[:1])

    client = LightfallClient(config["nats_url"], config["prefix"], config["app_name"])
    backend = RemoteBackend(client)
    backend.start()

    controller = MainController(backend=backend)

    def _on_auth_failed(message: str) -> None:
        if _show_auth_failure_dialog(message):
            controller.initialize_client()
        else:
            backend.shutdown()
            app.quit()

    backend.auth_failed.connect(_on_auth_failed)

    window = MainWindowMVC(controller=controller)
    window.show()

    exit_code = app.exec()
    backend.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

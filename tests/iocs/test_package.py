import subprocess
import sys


def test_iocs_importable():
    import pystxmcontrol.iocs  # noqa: F401


def test_base_package_does_not_import_iocs():
    # importing pystxmcontrol must not pull in caproto or pystxmcontrol.iocs
    code = (
        "import sys, pystxmcontrol, pystxmcontrol.drivers; "
        "assert 'pystxmcontrol.iocs' not in sys.modules, 'iocs leaked into base import'; "
        "assert 'caproto' not in sys.modules, 'caproto leaked into base import'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_require_caproto_returns_module():
    from pystxmcontrol.iocs import require_caproto
    assert require_caproto().__name__ == "caproto"

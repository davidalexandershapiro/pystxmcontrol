"""Thin Lightfall remote client for the pystxmcontrol GUI (spec #4).

Leaf package: NOTHING here imports lightfall, and nothing in the base
pystxmcontrol package imports this. Install extras: pip install pystxmcontrol[remote]
"""


def require_remote_deps() -> None:
    missing = []
    for mod in ("nats", "tiled", "caproto", "netifaces"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        raise ImportError(
            f"pystxmcontrol.remote requires {missing}; "
            "install with: pip install pystxmcontrol[remote]")

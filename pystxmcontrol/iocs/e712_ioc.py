"""Back-compat shim for the controller-agnostic fly IOC.

The fly IOC used to live here under the historical name ``e712_ioc``. The
line loop is not E712-specific (it serves any fly-capable controller, e.g.
nptController), so the implementation now lives in
``pystxmcontrol.iocs.fly_ioc``. This module re-exports everything from there
so existing imports (``from pystxmcontrol.iocs.e712_ioc import FlyGroup``) and
``python -m pystxmcontrol.iocs.e712_ioc --slice ...`` keep working.

Prefer importing from ``pystxmcontrol.iocs.fly_ioc`` in new code.
"""
from __future__ import annotations

from pystxmcontrol.iocs.fly_ioc import (  # noqa: F401
    STATES,
    FlyGroup,
    _enum_index,
    _fly_group_class,
    build_pvdb_from_slice,
    main,
)

if __name__ == "__main__":
    main()

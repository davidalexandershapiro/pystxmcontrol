"""EPICS IOC layer for pystxmcontrol devices (caproto-based).

Leaf subpackage: nothing here is imported by the base pystxmcontrol package.
Install the extra to use it:  pip install pystxmcontrol[iocs]
"""

import logging
import sys

_LOGGING_CONFIGURED = False


def configure_ioc_logging(level: int = logging.INFO) -> None:
    """Attach a stdout handler to the ``caproto`` logger.

    caproto emits its startup banner and the ``run(..., log_pv_names=True)``
    PV-name list at INFO on the ``caproto`` logger, which defaults to WARNING
    with *no* handler -- so those lines are silently dropped. Every IOC ``main``
    calls this before ``run`` so the list is actually printed to stdout. The
    supervisor spawns each IOC with a piped stdout and relays it (prefixed with
    the IOC name), so these lines surface in the supervisor's own output.

    Idempotent: a second call in the same process is a no-op.
    """
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    caproto_logger = logging.getLogger("caproto")
    caproto_logger.addHandler(handler)
    caproto_logger.setLevel(level)
    _LOGGING_CONFIGURED = True


def require_caproto():
    """Import and return caproto, with an actionable error if missing."""
    try:
        import caproto
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "pystxmcontrol.iocs requires caproto. "
            "Install with: pip install pystxmcontrol[iocs]"
        ) from exc
    return caproto

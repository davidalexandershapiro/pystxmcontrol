"""The optional collaborators the agent tools use, and their headless stand-ins.

Sibling of :mod:`instrument_client`, which names the one collaborator every tool needs
(the control-server connection).  The three here are OPTIONAL: the GUI supplies them,
an out-of-process or scripted run does not.

Before these existed each was a bare ``None`` that every tool had to guard, which made
"does this tool work headless?" a property of thirteen scattered conditionals rather
than something a caller could ask.  Null implementations answer the defensive half of
those guards; :func:`frames_available` and :attr:`Approval.interactive` answer the half
that needs to TELL the operator why a tool cannot do its job — "no live frames in this
session" is a different fact from "no scan has run yet", and the agent must not confuse
them by suggesting a scan that would not help.

The logbook is deliberately absent.  It stays GUI-only for now; when it grows a port it
belongs here beside these.
"""

from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Live scan frames and the agent-loop queues that ride alongside them
# ---------------------------------------------------------------------------

@runtime_checkable
class FrameSource(Protocol):
    """Live scan frames, their geometry, and the agent-loop queues.

    Dict-shaped because the GUI's ``ImageModel`` already is: the tools only ever reach
    it through ``get``/``set``.  Keys in use fall into three roles:

    * frame data — ``all_detector_images``, ``scan_buffer``
    * frame geometry — ``x_center``, ``y_center``, ``x_range``, ``y_range``,
      ``scan_type``, ``current_energy``
    * agent-loop queues — ``time_remaining``, ``pending_alarms``,
      ``pending_recommendations`` (written by the GUI controller, drained by the tools)
    """

    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...


class NullFrameSource:
    """No live frame feed in this session.

    Reads yield the caller's default and writes go nowhere, so the tools' defensive
    guards fall through naturally.  Tools that must EXPLAIN the absence ask
    :func:`frames_available` instead of getting a misleading empty result.
    """

    def get(self, key: str, default: Any = None) -> Any:
        return default

    def set(self, key: str, value: Any) -> None:
        pass


def frames_available(frames: FrameSource) -> bool:
    """False when *frames* is the null source, i.e. no live frames reach this session.

    The distinction matters to the operator: a tool that says "run a scan first" when
    the real problem is that this session can never see frames sends them chasing a
    scan that will not help.  Stage 3's registry keys tool tiering on this too.
    """
    return not isinstance(frames, NullFrameSource)


def frame_geometry(frames: FrameSource) -> tuple[float, float, float, float]:
    """``(x_center, y_center, x_range, y_range)`` in µm for the current frame.

    Ranges fall back to 1.0 rather than 0.0 because callers divide by them when
    converting pixels to µm; centres fall back to 0.0.  Read as one block in four
    places before this existed.
    """
    return (float(frames.get('x_center') or 0.0),
            float(frames.get('y_center') or 0.0),
            float(frames.get('x_range') or 1.0),
            float(frames.get('y_range') or 1.0))


# ---------------------------------------------------------------------------
# Operator approval
# ---------------------------------------------------------------------------

@runtime_checkable
class Approval(Protocol):
    """Gate an action on operator approval.

    ``interactive`` is False when nothing can actually ask a human, which the caller
    must report rather than pass off as a real approval.
    """

    interactive: bool

    def __call__(self, request: dict) -> bool: ...


class AutoApprove:
    """No interactive UI (headless / cron run), so nothing can be gated.

    Callers check ``interactive`` and say so plainly; silently returning True while
    claiming the operator approved would be a lie about a safety gate.
    """

    interactive = False

    def __call__(self, request: dict) -> bool:
        return True


class CallableApproval:
    """Wraps the GUI's ``confirm_fn`` — a callable that shows Approve/Decline buttons
    and BLOCKS the agent thread until the operator chooses."""

    interactive = True

    def __init__(self, fn):
        self._fn = fn

    def __call__(self, request: dict) -> bool:
        return bool(self._fn(request))


def approval_or_auto(confirm_fn) -> Approval:
    """An :class:`Approval` from an optional GUI ``confirm_fn``."""
    return AutoApprove() if confirm_fn is None else CallableApproval(confirm_fn)


# ---------------------------------------------------------------------------
# Scan lifecycle
# ---------------------------------------------------------------------------

@runtime_checkable
class ScanLifecycle(Protocol):
    """Notified as a scan is launched, so a host can set up to receive its frames."""

    def __call__(self, scan_dict: dict) -> None: ...


class NullScanLifecycle:
    """No host to notify (no GUI controller building a live stxm object)."""

    def __call__(self, scan_dict: dict) -> None:
        pass


def lifecycle_or_null(on_scan_started) -> ScanLifecycle:
    """A :class:`ScanLifecycle` from an optional callback."""
    return NullScanLifecycle() if on_scan_started is None else on_scan_started

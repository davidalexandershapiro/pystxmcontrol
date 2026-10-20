"""Per-connection NATS capability helpers (stdlib only; vendor byte-for-byte).

Every connection sends a random secret as its NATS connect token.  The broker's
auth callout derives the same prefix ``p`` from it and grants subscribe rights on
``_INBOX.<p>.>`` and ``_PRIV.<p>.>``.  This file must stay free of Qt, lightfall
and third-party imports so other repos can copy it verbatim.

Inbox isolation protects *reads* only.  nats-server lets any connection answer a
message it received with a reply subject (``allow_responses``), and a connection can
set any reply subject on what it publishes, so a spy can reflect a forged message
into another connection's ``_INBOX.<p>`` if it can guess the exact subject.  The
reply subjects nats-py's ``request()`` uses are predictable.  Every private or
session request must therefore go through :func:`private_request`, which waits on a
fresh unguessable reply subject that only the ``_PRIV`` owner ever sees.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any

VENDORED_FROM = "lightfall_utils.ipc.capability v2"

_DOMAIN = "lightfall-nats-v1:"
_PREFIX_LEN = 26
_PRIV_ROOT_RE = re.compile(r"^_PRIV\.[a-z2-7]{26}$")
_STATUS_NO_RESPONDERS = "503"


class PrivateRootUnavailable(RuntimeError):
    """The service did not advertise a well-formed ``priv_root`` in its meta.actions reply."""


class PrivateNoResponders(RuntimeError):
    """Nobody is subscribed to the subject a :func:`private_request` was sent to."""


def derive_prefix(secret: str) -> str:
    """Return base32(sha256(domain + secret)), lowercase, unpadded, 26 chars."""
    digest = hashlib.sha256((_DOMAIN + secret).encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=").lower()[:_PREFIX_LEN]


def new_token() -> str:
    """Return a 32-byte URL-safe random string (43 chars)."""
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class ConnectionCapability:
    secret: str
    prefix: str

    @property
    def inbox_prefix(self) -> str:
        return f"_INBOX.{self.prefix}"

    @property
    def priv_root(self) -> str:
        return f"_PRIV.{self.prefix}"

    def connect_kwargs(self) -> dict[str, str]:
        return {"token": self.secret, "inbox_prefix": self.inbox_prefix}


def new_capability() -> ConnectionCapability:
    secret = new_token()
    return ConnectionCapability(secret=secret, prefix=derive_prefix(secret))


def _inbox_prefix_of(nc: Any) -> str:
    raw = getattr(nc, "_inbox_prefix", None)
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("ascii")
    if not isinstance(raw, str) or not raw:
        raise ValueError("cannot read the connection's inbox prefix; pass inbox_prefix=")
    return raw


async def private_request(
    nc: Any,
    subject: str,
    payload: dict,
    timeout: float = 5.0,
    inbox_prefix: str | None = None,
) -> dict:
    """Send one JSON request whose reply subject cannot be guessed, and return the JSON reply.

    The reply subject is ``<inbox_prefix>.<new_token()>`` (256 random bits), subscribed
    for exactly one message.  ``inbox_prefix`` defaults to the connection's own (the
    ``inbox_prefix`` it was connected with).  Raises the client's timeout error (a
    :class:`TimeoutError`) when no reply arrives, :class:`PrivateNoResponders` when
    nobody listens on ``subject``, and :class:`json.JSONDecodeError` on a non-JSON reply.
    """
    inbox = f"{inbox_prefix or _inbox_prefix_of(nc)}.{new_token()}"
    sub = await nc.subscribe(inbox, max_msgs=1)
    try:
        await nc.publish(subject, json.dumps(payload).encode(), reply=inbox)
        msg = await sub.next_msg(timeout=timeout)
    except BaseException:
        try:
            await sub.unsubscribe()
        except Exception:
            pass
        raise
    headers = getattr(msg, "headers", None)
    if headers and headers.get("Status") == _STATUS_NO_RESPONDERS:
        raise PrivateNoResponders(f"no responders on {subject}")
    return json.loads(msg.data.decode())


async def private_auth_request(
    nc: Any, topic_prefix: str, payload: dict, timeout: float = 5.0
) -> dict:
    """Discover the private root via ``meta.actions`` then send ``auth.request`` there.

    The ``meta.actions`` leg is public (its reply can be spoofed, like discovery), so
    the advertised ``priv_root`` is shape-checked; the ``auth.request`` leg goes through
    :func:`private_request` so its reply cannot be forged.
    """
    msg = await nc.request(f"{topic_prefix}.meta.actions", b"{}", timeout=timeout)
    info = json.loads(msg.data.decode())
    priv_root = info.get("priv_root") if isinstance(info, dict) else None
    if not isinstance(priv_root, str) or not _PRIV_ROOT_RE.fullmatch(priv_root):
        raise PrivateRootUnavailable(
            f"{topic_prefix}.meta.actions did not return a valid priv_root: {priv_root!r}"
        )
    return await private_request(nc, f"{priv_root}.auth.request", payload, timeout=timeout)

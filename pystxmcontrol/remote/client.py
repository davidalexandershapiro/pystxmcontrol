"""Production Lightfall remote client for the pystxmcontrol GUI (spec #4).

Flow:
    client = LightfallClient("nats://127.0.0.1:4222", "als.test", "myapp")
    await client.connect()
    auth = await client.authenticate()        # -> approved reply w/ session_token
    reply = await client.call("commands.plan.list", {})
    await client.subscribe_event("runs.new", cb)
    await client.close()

bcgnats (auth callout): the client connects with one per-client connection
capability (``nats_capability.new_capability().connect_kwargs()``: connect token
plus ``inbox_prefix``), runs the private handshake (``meta.actions`` ->
``priv_root`` -> ``{priv_root}.auth.request``) and sends every capability-channel
call to ``{session_subject}.<suffix>`` via ``private_request`` (an unguessable
reply subject, so no other connection can forge the reply). See Lightfall's
developer guide, "NATS Use Model". ``nats_capability.py`` is a byte-for-byte copy
of ``lightfall_utils/ipc/capability.py``; never edit it here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import nats

from pystxmcontrol.remote.nats_capability import (
    new_capability,
    private_auth_request,
    private_request,
)

CONTRACT_VERSION = 1


class RemoteError(Exception):
    """Raised when the server replies with a structured error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class LightfallClient:
    """Minimal remote-control client: handshake + capability-channel calls."""

    def __init__(self, nats_url: str, prefix: str, app_name: str, app_version: str = "0.0", *,
                 _nats_connect=None) -> None:
        self._nats_url = nats_url
        self._prefix = prefix
        self._app_name = app_name
        self._app_version = app_version
        self._nc: nats.NATS | None = None
        self.session_token: str | None = None
        self.session_subject: str | None = None
        self.tiled_url: str | None = None
        self.tiled_token: str | None = None
        self._nats_connect = _nats_connect
        self._tiled = None
        # One capability per client, reused across reconnects.
        self._capability = new_capability()

    async def connect(self) -> None:
        connect = self._nats_connect or nats.connect
        self._nc = await connect(self._nats_url, **self._capability.connect_kwargs())

    async def authenticate(self, timeout: float = 90.0) -> dict:
        """Run the private auth.request handshake; store the session on approval.

        ``meta.actions`` -> ``priv_root`` -> ``{priv_root}.auth.request``. Raises
        ``PrivateRootUnavailable`` if the instance predates the private handshake.
        The 90 s default outlives Lightfall's 60 s trust-dialog timeout.
        """
        reply = await private_auth_request(
            self._nc,
            self._prefix,
            {"app_name": self._app_name, "app_version": self._app_version},
            timeout=timeout,
        )
        if reply.get("status") == "approved":
            self.session_token = reply["session_token"]
            self.session_subject = reply["session_subject"]
            self.tiled_url = reply.get("tiled_url")
            self.tiled_token = reply.get("tiled_token")
        return reply

    async def call(self, suffix: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
        """Request/reply on the capability channel; raise RemoteError on errors."""
        if self.session_subject is None:
            raise RuntimeError("Not authenticated — call authenticate() first")
        subject = f"{self.session_subject}.{suffix}"
        body = dict(payload or {})
        body.setdefault("contract_version", CONTRACT_VERSION)
        # Never nc.request() here: its reply subjects are predictable, so another
        # connection could forge the reply by allow_responses reflection.
        reply = await private_request(self._nc, subject, body, timeout=timeout)
        if reply.get("status") == "error":
            raise RemoteError(reply.get("code", "unknown"), reply.get("message", ""))
        return reply

    async def call_bare(self, suffix: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
        """Request on the bare (non-channel) subject — used to prove rejection."""
        msg = await self._nc.request(
            f"{self._prefix}.{suffix}", json.dumps(payload or {}).encode(), timeout=timeout
        )
        return json.loads(msg.data.decode())

    async def subscribe_event(self, suffix: str, callback: Callable[[dict], Any]) -> None:
        """Subscribe a broadcast event (public prefixed subject)."""

        async def _cb(msg) -> None:
            callback(json.loads(msg.data.decode()))

        await self._nc.subscribe(f"{self._prefix}.{suffix}", cb=_cb)

    async def ping(self, timeout: float = 3.0) -> bool:
        """Pre-trust liveness: meta.actions on the bare subject."""
        try:
            await self.call_bare("meta.actions", {}, timeout=timeout)
            return True
        except Exception:
            return False

    def tiled_client(self):
        """Lazy tiled.client rooted at the handshake's URL/token."""
        if not self.tiled_url:
            raise RuntimeError("Not authenticated - no tiled_url yet")
        if self._tiled is None:
            from tiled.client import from_uri
            self._tiled = from_uri(self.tiled_url, api_key=self.tiled_token)
        return self._tiled

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
            self._nc = None

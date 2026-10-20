import pytest

from pystxmcontrol.remote.client import CONTRACT_VERSION, LightfallClient, RemoteError
from pystxmcontrol.remote.nats_capability import PrivateRootUnavailable, derive_prefix
from .conftest import StubNats

PRIV = "_PRIV." + "p" * 26
SESSION = f"{PRIV}.session.tok123"


@pytest.fixture
def stub():
    return StubNats()


@pytest.fixture
async def client(stub):
    async def _connect(url, **kwargs):
        stub.connect_kwargs = kwargs
        return stub
    c = LightfallClient("nats://x", "als.test", "stxm-gui", _nats_connect=_connect)
    await c.connect()
    return c


def _serve_handshake(stub, reply=None):
    stub.handlers["als.test.meta.actions"] = lambda s, p: {"priv_root": PRIV, "actions": []}
    stub.handlers[f"{PRIV}.auth.request"] = lambda s, p: reply or {
        "status": "approved", "session_token": "tok123", "session_subject": SESSION,
        "tiled_url": "http://t", "tiled_token": "tt"}


async def test_connect_uses_one_capability(client, stub):
    kw = stub.connect_kwargs
    assert set(kw) == {"token", "inbox_prefix"}
    assert len(kw["token"]) == 43
    assert kw["inbox_prefix"] == f"_INBOX.{derive_prefix(kw['token'])}"
    await client.connect()  # reconnect reuses the same capability
    assert stub.connect_kwargs == kw


async def test_authenticate_uses_private_root(client, stub):
    _serve_handshake(stub)
    reply = await client.authenticate()
    assert reply["status"] == "approved"
    assert client.session_token == "tok123"
    assert client.session_subject == SESSION
    assert client.tiled_url == "http://t"
    subjects = [s for s, _ in stub.requests]
    assert subjects == ["als.test.meta.actions", f"{PRIV}.auth.request"]
    assert "als.test.auth.request" not in subjects
    # The private leg used an unguessable reply subject, not nc.request().
    (subject, reply_subject), = stub.private
    assert subject == f"{PRIV}.auth.request"
    head, token = reply_subject.rsplit(".", 1)
    assert head == "_INBOX.stub" and len(token) == 43


async def test_authenticate_without_priv_root_raises(client, stub):
    stub.handlers["als.test.meta.actions"] = lambda s, p: {"actions": []}
    with pytest.raises(PrivateRootUnavailable):
        await client.authenticate()


async def test_call_travels_on_session_subject_via_private_request(client, stub):
    _serve_handshake(stub)
    await client.authenticate()
    stub.handlers[f"{SESSION}.commands.engine.status"] = (
        lambda s, p: {"status": "ok", "state": "idle", "contract_version": 1})
    reply = await client.call("commands.engine.status")
    assert reply["state"] == "idle"
    subject, payload = stub.requests[-1]
    assert subject == f"{SESSION}.commands.engine.status"
    assert payload["contract_version"] == CONTRACT_VERSION
    assert stub.private[-1][0] == subject
    assert stub.private[-1][1] != stub.private[0][1]  # fresh reply subject per call


async def test_structured_error_raises(client, stub):
    _serve_handshake(stub)
    await client.authenticate()
    stub.handlers[f"{SESSION}.commands.plan.run"] = (
        lambda s, p: {"status": "error", "code": "busy", "message": "engine busy"})
    with pytest.raises(RemoteError) as ei:
        await client.call("commands.plan.run", {"plan_name": "x"})
    assert ei.value.code == "busy"


async def test_denied_leaves_no_session(client, stub):
    _serve_handshake(stub, {"status": "denied", "reason": "denied"})
    reply = await client.authenticate()
    assert reply["status"] == "denied"
    with pytest.raises(RuntimeError):
        await client.call("commands.engine.status")


async def test_call_before_auth_raises(client):
    with pytest.raises(RuntimeError):
        await client.call("commands.engine.status")


async def test_tiled_client_requires_auth(client):
    with pytest.raises(RuntimeError):
        client.tiled_client()

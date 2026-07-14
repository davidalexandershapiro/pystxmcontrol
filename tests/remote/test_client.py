import json

import pytest

from pystxmcontrol.remote.client import CONTRACT_VERSION, LightfallClient, RemoteError
from .conftest import StubNats


@pytest.fixture
def stub():
    return StubNats()


@pytest.fixture
async def client(stub):
    async def _connect(url):
        return stub
    c = LightfallClient("nats://x", "als.test", "stxm-gui", _nats_connect=_connect)
    await c.connect()
    return c


async def test_authenticate_stores_token_and_tiled(client, stub):
    stub.handlers["als.test.auth.request"] = lambda s, p: {
        "status": "approved", "session_token": "tok123",
        "tiled_url": "http://t", "tiled_token": "tt"}
    reply = await client.authenticate()
    assert reply["status"] == "approved"
    assert client.session_token == "tok123"
    assert client.tiled_url == "http://t"


async def test_call_travels_on_capability_channel(client, stub):
    stub.handlers["als.test.auth.request"] = lambda s, p: {
        "status": "approved", "session_token": "tok123"}
    await client.authenticate()
    stub.handlers["als.test.session.tok123.commands.engine.status"] = (
        lambda s, p: {"status": "ok", "state": "idle", "contract_version": 1})
    reply = await client.call("commands.engine.status")
    assert reply["state"] == "idle"
    subject, payload = stub.requests[-1]
    assert subject == "als.test.session.tok123.commands.engine.status"
    assert payload["contract_version"] == CONTRACT_VERSION


async def test_structured_error_raises(client, stub):
    stub.handlers["als.test.auth.request"] = lambda s, p: {
        "status": "approved", "session_token": "tok123"}
    await client.authenticate()
    stub.handlers["als.test.session.tok123.commands.plan.run"] = (
        lambda s, p: {"status": "error", "code": "busy", "message": "engine busy"})
    with pytest.raises(RemoteError) as ei:
        await client.call("commands.plan.run", {"plan_name": "x"})
    assert ei.value.code == "busy"


async def test_call_before_auth_raises(client):
    with pytest.raises(RuntimeError):
        await client.call("commands.engine.status")


async def test_tiled_client_requires_auth(client):
    with pytest.raises(RuntimeError):
        client.tiled_client()

"""Stub NATS for unit-testing LightfallClient without a broker."""
import json


class _StubMsg:
    def __init__(self, data: bytes):
        self.data = data


class StubNats:
    """Duck-types the nats-py client surface LightfallClient uses."""

    def __init__(self):
        self.handlers = {}       # exact subject -> callable(payload dict) -> dict
        self.subscriptions = {}  # subject -> cb
        self.requests = []       # (subject, payload) log

    async def request(self, subject, data, timeout=None):
        payload = json.loads(data.decode())
        self.requests.append((subject, payload))
        for pat, handler in self.handlers.items():
            if subject == pat or (pat.endswith(".*") and subject.startswith(pat[:-1])):
                return _StubMsg(json.dumps(handler(subject, payload)).encode())
        raise TimeoutError(f"no stub handler for {subject}")

    async def subscribe(self, subject, cb=None):
        self.subscriptions[subject] = cb

    async def drain(self):
        pass


async def stub_connect_factory(stub):
    async def _connect(url):
        return stub
    return _connect

"""Guards the byte-for-byte vendored copy of lightfall_utils.ipc.capability."""

from pystxmcontrol.remote import nats_capability as cap


def test_derive_prefix_known_vectors():
    assert cap.derive_prefix("test-secret-0001") == "r5itqnjn2uhkfjylxqpf7fwjv7"
    assert cap.derive_prefix("A" * 43) == "3dcidrblqoesmah3mp7u5jx4cx"


def test_vendored_from_marker():
    assert cap.VENDORED_FROM == "lightfall_utils.ipc.capability v2"

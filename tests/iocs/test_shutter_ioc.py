import pytest


@pytest.fixture
def shutter_ioc(ioc_harness):
    from pystxmcontrol.drivers.shutter import shutter as Shutter
    sh = Shutter(address="COM_FAKE")
    sh.connect(simulation=True)
    from pystxmcontrol.iocs.shutter_ioc import ShutterGroup
    group = ShutterGroup("STXMSIM:SHUTTER1", shutter=sh)
    ioc_harness.start(group.pvdb)
    return ioc_harness, sh


@pytest.mark.parametrize("mode_idx,mode_str,david_mode", [
    (0, "OPEN", "open"), (1, "CLOSED", "close"), (2, "AUTO", "auto")])
def test_mode_maps_to_setgate_semantics(shutter_ioc, mode_idx, mode_str, david_mode):
    h, sh = shutter_ioc
    ctx = h.client()
    (mode,) = ctx.get_pvs("STXMSIM:SHUTTER1:MODE")
    mode.wait_for_connection(timeout=10)
    # Caproto's threading client cannot write enum values as bare strings
    # (native ENUM dtype fails with "invalid literal for int()"). Write by index instead.
    mode.write(mode_idx, wait=True, timeout=10)
    assert sh.mode == david_mode


def test_state_readback_exists(shutter_ioc):
    h, sh = shutter_ioc
    ctx = h.client()
    (state,) = ctx.get_pvs("STXMSIM:SHUTTER1:STATE")
    state.wait_for_connection(timeout=10)
    assert state.read().data[0] in (0, 1)

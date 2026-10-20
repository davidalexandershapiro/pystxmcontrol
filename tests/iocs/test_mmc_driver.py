"""Unit tests for the rewritten Micronix MMC driver (fake transport, no I/O)."""
import pytest


class FakeMMC:
    """Scripted line transport: records writes, replays canned replies."""
    def __init__(self, replies=()):
        self.writes = []
        self.replies = list(replies)

    def write(self, data: bytes):
        self.writes.append(data.decode())

    def readline(self) -> bytes:
        return (self.replies.pop(0) if self.replies else "").encode()

    def close(self):
        pass


def make_controller(replies=()):
    from pystxmcontrol.drivers.mmcController import mmcController
    ctrl = mmcController(address="COM99")
    ctrl.simulation = False
    ctrl._transport = FakeMMC(replies)
    return ctrl


def test_driver_importable_without_optional_deps():
    # Legacy module imported pylibftdi at module scope, which knocked the
    # whole driver out of pystxmcontrol.drivers in envs without it.
    import pystxmcontrol.drivers as drv
    assert hasattr(drv, "mmcController")


def test_command_frames_axis_prefix_and_cr():
    ctrl = make_controller()
    ctrl.command(2, "MVA1.234")
    assert ctrl._transport.writes == ["2MVA1.234\r"]


def test_query_strips_hash_and_returns_payload():
    ctrl = make_controller(replies=["#0.500000,0.498400\n"])
    assert ctrl.query(1, "POS?") == "0.500000,0.498400"
    assert ctrl._transport.writes == ["1POS?\r"]


def test_query_malformed_reply_raises_mmcerror():
    from pystxmcontrol.drivers.mmcController import MMCError
    ctrl = make_controller(replies=["garbage\n"])
    with pytest.raises(MMCError):
        ctrl.query(1, "POS?")


def test_query_empty_reply_raises_mmcerror():
    from pystxmcontrol.drivers.mmcController import MMCError
    ctrl = make_controller(replies=[""])
    with pytest.raises(MMCError):
        ctrl.query(1, "POS?")


def test_get_errors_never_raises():
    ctrl = make_controller(replies=[""])  # empty reply would raise in query()
    assert ctrl.get_errors(1) == ""


def test_simulation_initialize_opens_no_transport():
    from pystxmcontrol.drivers.mmcController import mmcController
    ctrl = mmcController(address="COM99")
    ctrl.initialize(simulation=True)
    assert ctrl.simulation is True and ctrl._transport is None


def test_transport_selection_serial_vs_tcp():
    from pystxmcontrol.drivers.mmcController import mmcController
    assert mmcController(address="COM3")._is_serial_address()
    assert mmcController(address="/dev/ttyUSB0")._is_serial_address()
    assert not mmcController(address="192.168.1.50", port=4001)._is_serial_address()


ENTRY = {"axis": "x", "minValue": -10.0, "maxValue": 10.0, "offset": 0.0,
         "units": 1.0, "max velocity": 2.0, "timeout": 10, "simulation": 0}


def make_motor(replies=(), entry=None, axis="x"):
    from pystxmcontrol.drivers.mmcMotor import mmcMotor
    ctrl = make_controller(replies)
    m = mmcMotor()
    m.controller = ctrl
    m.config = dict(ENTRY, **(entry or {}), axis=axis)
    m.connect(axis=axis)
    return m, ctrl._transport


def test_connect_maps_axis_and_enables_servo():
    m, t = make_motor()
    assert m._axis == 1
    assert "1FBK3\r" in t.writes


def test_connect_axis_y_is_2():
    m, _ = make_motor(axis="y")
    assert m._axis == 2


def test_get_pos_uses_encoder_field_and_units():
    m, t = make_motor(replies=["#2.000000,1.998000\n"],
                      entry={"units": 2.0, "offset": 1.0})
    assert m.getPos() == pytest.approx(1.998000 * 2.0 + 1.0)
    assert t.writes[-1] == "1POS?\r"


def test_status_decodes_moving_bit():
    # bit 3 (0x08) set = idle. 8 and 136 are the historically observed
    # idle bytes; 1 (bit 3 clear) means moving.
    m, _ = make_motor(replies=["#8\n", "#136\n", "#1\n"])
    assert m.getStatus() is False
    assert m.getStatus() is False
    assert m.getStatus() is True


def test_check_limits_raises_software_limit_error():
    from pystxmcontrol.controller.motor import SoftwareLimitError
    m, _ = make_motor()
    with pytest.raises(SoftwareLimitError):
        m.checkLimits(10.5)


def test_move_to_frames_float_target_no_truncation():
    m, t = make_motor(replies=["#8\n"])  # immediately idle
    m.moveTo(1.2345)
    # writes[0] is connect()'s "1FBK3\r"
    assert t.writes[1] == "1MVA1.234\r"  # 3-decimal round, NOT int()


def test_move_to_timeout_stops_and_raises():
    from pystxmcontrol.drivers.mmcController import MMCError
    moving = "#1\n"
    m, t = make_motor(replies=[moving] * 10000, entry={"timeout": 0.05})
    with pytest.raises(MMCError):
        m.moveTo(1.0)
    assert "1STP\r" in t.writes


def test_stop_sends_stp():
    m, t = make_motor()
    m.stop()
    assert t.writes[-1] == "1STP\r"


def test_velocity_set_and_get():
    m, t = make_motor(replies=["#0,1.500000\n"])
    m.setAxisParams(velocity=1.5)
    assert t.writes[-1] == "1VEL1.5\r"
    assert m.get_velocity() == pytest.approx(1.5)


def test_simulation_move_and_readback():
    from pystxmcontrol.drivers.mmcController import mmcController
    from pystxmcontrol.drivers.mmcMotor import mmcMotor
    ctrl = mmcController(address="COM99")
    ctrl.initialize(simulation=True)
    m = mmcMotor()
    m.controller = ctrl
    m.config = dict(ENTRY, offset=1.0, units=2.0)
    m.connect(axis="x")
    m.moveTo(5.0)
    assert m.getPos() == pytest.approx(5.0)
    assert m.getStatus() is False


def test_update_trajectory_computes_velocity_from_fast_axis():
    m, _ = make_motor(replies=[])
    m.trajectory_start = (-1.0, 0.0)  # fast axis = x (varies)
    m.trajectory_stop = (1.0, 0.0)
    m.trajectory_pixel_count = 20
    m.trajectory_pixel_dwell = 100.0  # ms -> line time 2 s, span 2 -> 1 u/s
    m.update_trajectory()
    assert m.line_velocity == pytest.approx(1.0)
    assert (m._line_start, m._line_stop) == (-1.0, 1.0)
    assert m.npositions == 20


def test_update_trajectory_picks_y_when_it_varies():
    m, _ = make_motor(axis="y")
    m.trajectory_start = (3.0, -2.0)
    m.trajectory_stop = (3.0, 2.0)
    m.trajectory_pixel_count = 10
    m.trajectory_pixel_dwell = 200.0
    m.update_trajectory()
    assert (m._line_start, m._line_stop) == (-2.0, 2.0)


def test_update_trajectory_rejects_unflyable_line():
    from pystxmcontrol.drivers.mmcController import MMCError
    m, _ = make_motor()  # max velocity 2.0 (ENTRY)
    m.trajectory_start = (-10.0, 0.0)
    m.trajectory_stop = (10.0, 0.0)
    m.trajectory_pixel_count = 10
    m.trajectory_pixel_dwell = 1.0  # 20 units in 10 ms -> 2000 u/s
    with pytest.raises(MMCError):
        m.update_trajectory()


def test_move_line_sequence_and_velocity_restore():
    # replies consumed in order:
    #   VEL? (cruise) -> moveTo(start) STA? idle -> line MVA STA? idle
    m, t = make_motor(replies=["#0,1.000000\n", "#8\n", "#8\n"])
    m.trajectory_start = (-1.0, 0.0)
    m.trajectory_stop = (1.0, 0.0)
    m.trajectory_pixel_count = 20
    m.trajectory_pixel_dwell = 100.0
    m.update_trajectory()
    m.moveLine()
    w = t.writes
    # w[0] is connect()'s "1FBK3\r"
    assert w[1] == "1VEL?\r"               # read cruise velocity first
    assert "1MVA-1.0\r" in w               # move to line start
    assert "1VEL1.0\r" in w                # line velocity
    assert "1MVA1.0\r" in w                # constant-velocity line move
    assert w[-1] == "1VEL1.0\r"            # cruise restored last
    # line velocity set BEFORE the line move
    assert w.index("1VEL1.0\r") < w.index("1MVA1.0\r")


def test_update_trajectory_rejects_zero_span():
    from pystxmcontrol.drivers.mmcController import MMCError
    m, _ = make_motor()
    m.trajectory_start = (3.0, 0.0)
    m.trajectory_stop = (3.0, 0.0)  # zero span on both slots
    m.trajectory_pixel_count = 10
    m.trajectory_pixel_dwell = 100.0
    with pytest.raises(MMCError):
        m.update_trajectory()


def test_prepare_line_then_move_line_split_sequence():
    # prepareLine: VEL? (cruise) -> MVA(start)+STA? poll -> VEL(line).
    # moveLine (prepared): only MVA(stop) -> STA? polls -> VEL restore.
    # Cruise (0.5) deliberately differs from line velocity (1.0) so the
    # restore assertion can't be satisfied by the line-velocity write.
    m, t = make_motor(replies=["#0,0.500000\n",  # VEL? cruise
                               "#8\n",           # moveTo(start) STA? idle
                               "#8\n"])          # line MVA STA? idle
    m.trajectory_start = (-1.0, 0.0)
    m.trajectory_stop = (1.0, 0.0)
    m.trajectory_pixel_count = 20
    m.trajectory_pixel_dwell = 100.0
    m.update_trajectory()
    m.prepareLine()
    prep = list(t.writes)
    # w[0] is connect()'s "1FBK3\r"
    assert prep[1] == "1VEL?\r"
    assert prep[2] == "1MVA-1.0\r"
    assert prep[-1] == "1VEL1.0\r"  # line velocity set in prepareLine
    assert m._prepared is True
    m.moveLine()
    tail = t.writes[len(prep):]
    # prepared moveLine: no re-positioning, no VEL? re-read
    assert tail[0] == "1MVA1.0\r"
    assert "1VEL?\r" not in tail and "1MVA-1.0\r" not in tail
    assert tail[-1] == "1VEL0.5\r"  # CRUISE (not line velocity) restored last
    assert m._prepared is False


def test_re_prepare_after_abort_keeps_original_cruise():
    # Abort between prepareLine and moveLine leaves the axis at line
    # velocity with _prepared=True; a second prepareLine must NOT re-stash
    # the (still-set) line velocity as cruise.
    m, t = make_motor(replies=["#0,0.500000\n",  # 1st prepare: VEL? cruise
                               "#8\n",           # 1st prepare: MVA(start) idle
                               "#8\n",           # 2nd prepare: MVA(start) idle
                               "#8\n"])          # moveLine: line MVA idle
    m.trajectory_start = (-1.0, 0.0)
    m.trajectory_stop = (1.0, 0.0)
    m.trajectory_pixel_count = 20
    m.trajectory_pixel_dwell = 100.0
    m.update_trajectory()
    m.prepareLine()
    assert m._cruise_velocity == pytest.approx(0.5)
    # ... line aborted here (no moveLine); axis left at line velocity ...
    n_writes = len(t.writes)
    m.prepareLine()
    # no VEL? re-read on the second prepare (stash preserved)
    assert "1VEL?\r" not in t.writes[n_writes:]
    assert m._cruise_velocity == pytest.approx(0.5)
    m.moveLine()
    assert t.writes[-1] == "1VEL0.5\r"  # original cruise restored
    assert m._prepared is False


def test_move_line_unprepared_is_self_contained():
    # Without prepareLine, moveLine still does the full sequence itself.
    m, t = make_motor(replies=["#0,1.000000\n", "#8\n", "#8\n"])
    m.trajectory_start = (-1.0, 0.0)
    m.trajectory_stop = (1.0, 0.0)
    m.trajectory_pixel_count = 20
    m.trajectory_pixel_dwell = 100.0
    m.update_trajectory()
    m.moveLine()
    w = t.writes
    assert w[1] == "1VEL?\r"
    assert "1MVA-1.0\r" in w
    assert w.index("1VEL1.0\r") < w.index("1MVA1.0\r")
    assert w[-1] == "1VEL1.0\r"


def test_move_line_velocity_restore_failure_does_not_mask_error():
    from pystxmcontrol.drivers.mmcController import MMCError
    m, t = make_motor(replies=["#0,1.000000\n", "#8\n"])
    m.trajectory_start = (-1.0, 0.0)
    m.trajectory_stop = (1.0, 0.0)
    m.trajectory_pixel_count = 20
    m.trajectory_pixel_dwell = 100.0
    m.update_trajectory()
    m.prepareLine()
    # after prepare, make the line's STA? polls report "moving" forever,
    # and make the finally-block restore itself fail too.
    m.config["timeout"] = 0.05

    def boom(velocity):
        raise IOError("link dropped")
    m.setAxisParams = boom
    t.replies = ["#1\n"] * 10000
    # deadline is >= 5 s; shrink line time to keep the test fast by faking
    # the status as an immediate stall via deadline: use tiny dwell and
    # monkeypatch time is overkill -- instead exercise via getStatus raising.
    def bad_status(**kwargs):
        raise MMCError("garbled STA? reply")
    m.getStatus = bad_status
    with pytest.raises(MMCError, match="garbled STA"):
        m.moveLine()  # restore failure is logged, original error surfaces
    assert m._prepared is False


def test_move_line_simulation_lands_on_stop():
    from pystxmcontrol.drivers.mmcController import mmcController
    from pystxmcontrol.drivers.mmcMotor import mmcMotor
    ctrl = mmcController(address="COM99")
    ctrl.initialize(simulation=True)
    m = mmcMotor()
    m.controller = ctrl
    m.config = dict(ENTRY)
    m.connect(axis="x")
    m.trajectory_start = (-1.0, 0.0)
    m.trajectory_stop = (1.0, 0.0)
    m.trajectory_pixel_count = 5
    m.trajectory_pixel_dwell = 200.0
    m.update_trajectory()
    m.moveLine()
    assert m.getPos() == pytest.approx(1.0)

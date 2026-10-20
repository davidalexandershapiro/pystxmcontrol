# Micronix MMC Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Micronix MMC axes served by the generic motor IOC and the controller-agnostic fly IOC, with software-timed (internal-trigger) fly lines as the default.

**Architecture:** Rewrite `drivers/mmcController.py` as a lock-free transaction layer (pluggable serial/TCP transport) and `drivers/mmcMotor.py` to the modern point-to-point + duck-typed fly interface; add a `line_trigger` motor attribute honored by `fly_ioc`; register `mmcController` in `FLY_CAPABLE_CONTROLLERS`. Spec: `docs/superpowers/specs/2026-07-22-mmc-integration-design.md`.

**Tech Stack:** Python, caproto (IOC layer), pyserial, pytest.

## Global Constraints

- Repo/worktree: `C:\Users\rp\PycharmProjects\ncs\lightfall-pystxmcontrol\_pystxmcontrol_iocs_wt`, branch `feature/caproto-iocs`. All commands below run with this as CWD.
- Test command: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest <paths> -q` (this venv has caproto 1.3.0, numpy, pyserial). NEVER bare `pytest`.
- Pre-existing failures to IGNORE (missing optional deps in this venv, unrelated): `tests/iocs/test_config.py::test_motor_pv_naming`, `::test_colocated_derived`. Everything else must stay green.
- Drivers are **lock-agnostic**: no `threading.Lock` anywhere in `drivers/mmcController.py` / `drivers/mmcMotor.py`. The IOC layer's `io_lock` serializes.
- MMC wire protocol: ASCII, axis-number prefix, `\r` terminated. Commands used: `MVA` (move abs), `POS?` (reply `#<theory>,<encoder>`), `STA?` (status byte; idle when bit 3 / 0x08 set — legacy idle values 8 and 136 both have bit 3 set), `VEL`/`VEL?`, `FBK3`/`FBK0`, `HOM`, `HCG<dir>`, `STP`, `ERR?`. Query replies start with `#`. Serial 38400 8N1, 1 s timeout.
- Positions: GUI units → controller units via `(pos - offset) / units`, rounded to **3 decimals** (never `int()`).
- `git commit` only with explicit paths (never `git add -A`). Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01AHAAJ8YhaHTjQRLC9aAfso`

---

### Task 1: mmcController transaction layer

**Files:**
- Modify (full rewrite): `pystxmcontrol/drivers/mmcController.py`
- Test: `tests/iocs/test_mmc_driver.py` (new)

**Interfaces:**
- Produces: `MMCError(IOError)`; `mmcController(address="COM3", port=None, simulation=False)` with `.initialize(simulation=False)`, `.command(axis: int, cmd: str) -> None`, `.query(axis: int, cmd: str) -> str` (payload after `#`, raises `MMCError` on malformed/empty reply), `.get_errors(axis: int) -> str` (never raises), `.positions: dict[int, float]` and `.velocities: dict[int, float]` sim-state dicts, `._transport` attribute (object with `write(bytes)`, `readline() -> bytes`, `close()`); tests inject a fake there.

- [ ] **Step 1: Write the failing tests**

Create `tests/iocs/test_mmc_driver.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_driver.py -q`
Expected: FAIL/ERROR — `ImportError`/`AttributeError` (legacy module has no `MMCError`, imports `pylibftdi`).

- [ ] **Step 3: Rewrite the driver**

Replace `pystxmcontrol/drivers/mmcController.py` entirely:

```python
# -*- coding: utf-8 -*-
"""Micronix MMC controller driver.

Transaction layer only: framing (axis prefix + CR), response parsing
(# payload), and transport (serial or TCP, chosen from the address).
No locking here -- the IOC layer's per-controller io_lock serializes all
link I/O (see pystxmcontrol.iocs.base.MotorRecordGroup).
"""
from pystxmcontrol.controller.hardwareController import hardwareController


class MMCError(IOError):
    """A malformed/absent MMC response or a failed MMC motion."""


class _TcpLineTransport:
    """Line-oriented TCP transport matching pyserial's write/readline API."""

    def __init__(self, host, port, timeout=1.0):
        import socket
        self._sock = socket.create_connection((host, int(port)), timeout=timeout)
        self._sock.settimeout(timeout)
        self._file = self._sock.makefile("rb")

    def write(self, data: bytes):
        self._sock.sendall(data)

    def readline(self) -> bytes:
        import socket
        try:
            return self._file.readline()
        except socket.timeout:
            return b""

    def close(self):
        try:
            self._file.close()
        finally:
            self._sock.close()


class mmcController(hardwareController):

    def __init__(self, address="COM3", port=None, simulation=False):
        self.address = address
        self.port = port
        self.simulation = simulation
        self._transport = None
        # Simulation state, shared by all mmcMotor instances on this
        # controller: axis number -> position (controller units) / velocity.
        self.positions = {}
        self.velocities = {}

    def _is_serial_address(self) -> bool:
        addr = str(self.address)
        return addr.upper().startswith("COM") or addr.startswith("/dev/")

    def _open_transport(self):
        if self._is_serial_address():
            import serial
            return serial.Serial(port=str(self.address), baudrate=38400,
                                 bytesize=8, timeout=1,
                                 stopbits=serial.STOPBITS_ONE)
        if self.port in (None, 0):
            raise MMCError(
                f"TCP address {self.address!r} requires a nonzero port")
        return _TcpLineTransport(str(self.address), self.port, timeout=1.0)

    def initialize(self, simulation=False):
        self.simulation = simulation
        if self.simulation:
            return
        print(f"Connecting to MMC controller on {self.address}"
              + (f":{self.port}" if not self._is_serial_address() else ""),
              flush=True)
        self._transport = self._open_transport()

    def command(self, axis, cmd):
        """Fire-and-forget command; no reply expected."""
        if self.simulation:
            return
        self._transport.write(f"{int(axis)}{cmd}\r".encode())

    def query(self, axis, cmd) -> str:
        """Send a query and return the reply payload (text after '#')."""
        if self.simulation:
            raise MMCError("query() has no meaning in simulation mode")
        self._transport.write(f"{int(axis)}{cmd}\r".encode())
        raw = self._transport.readline().decode(errors="replace").strip()
        if not raw.startswith("#"):
            raise MMCError(
                f"malformed MMC reply to {cmd!r} on axis {axis}: {raw!r}")
        return raw[1:]

    def get_errors(self, axis) -> str:
        """Best-effort ERR? readout for diagnostics; never raises."""
        try:
            return self.query(axis, "ERR?")
        except Exception:
            return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_driver.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add pystxmcontrol/drivers/mmcController.py tests/iocs/test_mmc_driver.py
git commit -m "feat(mmc): rewrite mmcController as lock-free transaction layer (serial/TCP)"
```

---

### Task 2: mmcMotor point-to-point interface

**Files:**
- Modify (full rewrite): `pystxmcontrol/drivers/mmcMotor.py`
- Test: append to `tests/iocs/test_mmc_driver.py`

**Interfaces:**
- Consumes: Task 1's `mmcController.command/query/get_errors/positions/velocities`, `MMCError`.
- Produces: `mmcMotor(controller=None, config=None)` with `connect(axis=, **kwargs)`, `checkLimits(pos)` (raises `SoftwareLimitError`), `moveTo(pos)` (blocks until idle; timeout → `STP` + `MMCError`), `moveBy(step)`, `getPos() -> float`, `getStatus() -> bool` (True while moving), `stop()`, `setAxisParams(velocity=)`, `get_velocity() -> float`, `home()`, `configure_home(direction)`, `setServo(bool)`. Attribute `_axis: int` (1-based).

- [ ] **Step 1: Write the failing tests**

Append to `tests/iocs/test_mmc_driver.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_driver.py -q`
Expected: Task 1 tests pass; new tests FAIL (legacy motor references `self.lock`, `int(pos)` truncation, no `stop`).

- [ ] **Step 3: Rewrite the motor (point-to-point half)**

Replace `pystxmcontrol/drivers/mmcMotor.py` entirely:

```python
# -*- coding: utf-8 -*-
"""Micronix MMC axis driver (point-to-point + constant-velocity fly lines).

Lock-agnostic: the IOC layer's per-controller io_lock serializes all link
I/O. Software-timed fly lines (line_trigger = "INT"): the MMC has no
trigger output, so the DAQ free-runs during the constant-velocity move.
"""
import time

from pystxmcontrol.controller.motor import motor, SoftwareLimitError
from pystxmcontrol.drivers.mmcController import MMCError

_AXIS_NUMBERS = {"x": 1, "y": 2, "z": 3}
_STATUS_STOPPED_BIT = 0x08  # STA? bit 3: axis stopped (legacy idle 8/136)


class mmcMotor(motor):

    #: DAQ trigger source for fly lines (fly_ioc reads this; the MMC has no
    #: hardware trigger output, so lines are software-timed by default).
    line_trigger = "INT"

    def __init__(self, controller=None, config=None):
        self.controller = controller
        self.config = config
        self.simulation = False
        self.axis = None
        self._axis = 1
        self.moving = False
        self.velocity = 0.0
        # fly interface (duck-typed; see iocs/fly_ioc.py _run_line)
        self.lineMode = "raster"
        self.trajectory_start = (0.0, 0.0)
        self.trajectory_stop = (0.0, 0.0)
        self.trajectory_pixel_count = 10
        self.trajectory_pixel_dwell = 1.0  # ms per pixel
        self.npositions = 10
        self.line_velocity = 0.0
        self._line_start = 0.0
        self._line_stop = 0.0
        self._poll = 0.005

    # ---- helpers -------------------------------------------------------
    def _to_controller(self, pos):
        return round((pos - self.config["offset"]) / self.config["units"], 3)

    def _from_controller(self, pos):
        return pos * self.config["units"] + self.config["offset"]

    # ---- point-to-point interface --------------------------------------
    def connect(self, axis=None, **kwargs):
        if "logger" in kwargs:
            self.logger = kwargs["logger"]
        self.simulation = self.controller.simulation
        self.axis = axis
        self._axis = int(self.config.get("controller_index",
                                         _AXIS_NUMBERS.get(axis, 1)))
        self.setServo(True)
        return True

    def checkLimits(self, pos):
        lo, hi = self.config["minValue"], self.config["maxValue"]
        if pos < lo:
            raise SoftwareLimitError(self.axis, pos, lo, limit_type="lower")
        if pos > hi:
            raise SoftwareLimitError(self.axis, pos, hi, limit_type="upper")
        return True

    def getStatus(self, **kwargs):
        if self.simulation:
            return self.moving
        status = int(self.controller.query(self._axis, "STA?"))
        self.moving = not (status & _STATUS_STOPPED_BIT)
        return self.moving

    def getPos(self):
        if self.simulation:
            return self._from_controller(
                self.controller.positions.get(self._axis, 0.0))
        payload = self.controller.query(self._axis, "POS?")
        # closed-loop reply: "<theoretical>,<encoder>"; use the encoder
        # (last) field, which is also correct for single-field replies.
        return self._from_controller(float(payload.split(",")[-1]))

    def moveTo(self, pos):
        self.checkLimits(pos)
        if self.simulation:
            self.controller.positions[self._axis] = \
                (pos - self.config["offset"]) / self.config["units"]
            self.moving = False
            return
        self.controller.command(self._axis, f"MVA{self._to_controller(pos)}")
        timeout = float(self.config.get("timeout", 10))
        t0 = time.time()
        while self.getStatus():
            if time.time() - t0 > timeout:
                self.stop()
                raise MMCError(
                    f"MMC axis {self.axis} move to {pos} timed out after "
                    f"{timeout}s; controller errors: "
                    f"{self.controller.get_errors(self._axis)!r}")
            time.sleep(self._poll)

    def moveBy(self, step):
        self.moveTo(self.getPos() + step)

    def stop(self):
        if not self.simulation:
            self.controller.command(self._axis, "STP")
        self.moving = False

    def setAxisParams(self, velocity):
        self.velocity = round(float(velocity), 3)
        if self.simulation:
            self.controller.velocities[self._axis] = self.velocity
        else:
            self.controller.command(self._axis, f"VEL{self.velocity}")

    def get_velocity(self):
        if self.simulation:
            return self.controller.velocities.get(self._axis, self.velocity)
        payload = self.controller.query(self._axis, "VEL?")
        self.velocity = float(payload.split(",")[-1])
        return self.velocity

    def setServo(self, servo=True):
        if not self.simulation:
            self.controller.command(self._axis, f"FBK{3 if servo else 0}")

    def home(self):
        if not self.simulation:
            self.controller.command(self._axis, "HOM")

    def configure_home(self, direction=0):
        if not self.simulation:
            self.controller.command(self._axis, f"HCG{int(direction)}")
```

(The fly half — `update_trajectory`/`moveLine` — is Task 3; the attributes above already exist so this file imports cleanly either way.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_driver.py -q`
Expected: all pass (18).

- [ ] **Step 5: Commit**

```bash
git add pystxmcontrol/drivers/mmcMotor.py tests/iocs/test_mmc_driver.py
git commit -m "feat(mmc): modern point-to-point mmcMotor (limits, stop, float targets, sim mode)"
```

---

### Task 3: mmcMotor fly interface

**Files:**
- Modify: `pystxmcontrol/drivers/mmcMotor.py` (append two methods)
- Test: append to `tests/iocs/test_mmc_driver.py`

**Interfaces:**
- Consumes: Task 2's motor internals (`_to_controller`, `moveTo`, `setAxisParams`, `get_velocity`, `getStatus`, `stop`).
- Produces: `update_trajectory(direction="forward", include_return=False)` (sets `line_velocity`, `_line_start`, `_line_stop`, `npositions`; raises `MMCError` if the line needs more than `config["max velocity"]`), `moveLine(**kwargs)` (blocking constant-velocity line; restores cruise velocity in `finally`). Both driven by `fly_ioc._run_line` under `io_lock`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/iocs/test_mmc_driver.py`:

```python
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
    m.trajectory_pixel_dwell = 100.0
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
    m.trajectory_pixel_dwell = 1.0
    m.update_trajectory()
    m.moveLine()
    assert m.getPos() == pytest.approx(1.0)
```

Note on `test_move_line_sequence_and_velocity_restore`: cruise velocity read
back is 1.0 and line velocity computes to 1.0, so the restore write equals the
line write; the ordering assertion is what matters. Keep the arithmetic simple.

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_driver.py -q`
Expected: new tests FAIL with `AttributeError: ... no attribute 'update_trajectory'`.

- [ ] **Step 3: Implement the fly methods**

Append to `class mmcMotor` in `pystxmcontrol/drivers/mmcMotor.py`:

```python
    # ---- fly interface (duck-typed; driven by iocs/fly_ioc.py) ---------
    def update_trajectory(self, direction="forward", include_return=False):
        """Compute the constant velocity for a software-timed fly line.

        The MMC flies one axis at constant velocity; the fast axis is
        whichever trajectory slot varies (fly_ioc holds the other constant).
        """
        x0, y0 = self.trajectory_start
        x1, y1 = self.trajectory_stop
        if abs(x1 - x0) >= abs(y1 - y0):
            start, stop = x0, x1
        else:
            start, stop = y0, y1
        if direction == "backward":
            start, stop = stop, start
        line_time = self.trajectory_pixel_count * self.trajectory_pixel_dwell / 1000.0
        if line_time <= 0:
            raise MMCError("fly line has non-positive duration")
        velocity = abs(stop - start) / line_time / abs(self.config["units"])
        max_v = self.config.get("max velocity")
        if max_v and velocity > float(max_v):
            raise MMCError(
                f"fly line needs {velocity:.3f} units/s > max velocity "
                f"{max_v}; increase dwell or shorten the line")
        self._line_start, self._line_stop = start, stop
        self.line_velocity = velocity
        self.npositions = self.trajectory_pixel_count

    def moveLine(self, **kwargs):
        """Blocking constant-velocity line move (runs under fly_ioc's
        io_lock in an executor thread). DAQ acquisition free-runs
        concurrently (line_trigger = "INT")."""
        line_time = self.trajectory_pixel_count * self.trajectory_pixel_dwell / 1000.0
        if self.simulation:
            time.sleep(min(line_time, 0.1))
            self.controller.positions[self._axis] = \
                (self._line_stop - self.config["offset"]) / self.config["units"]
            return
        cruise = self.get_velocity()
        self.moveTo(self._line_start)
        self.setAxisParams(velocity=self.line_velocity)
        try:
            self.controller.command(
                self._axis, f"MVA{self._to_controller(self._line_stop)}")
            deadline = time.time() + max(5.0, line_time * 4.0 + 5.0)
            while self.getStatus():
                if time.time() > deadline:
                    self.stop()
                    raise MMCError(
                        f"MMC fly line on axis {self.axis} stalled "
                        f"(no completion within {line_time * 4 + 5:.1f}s)")
                time.sleep(self._poll)
        finally:
            self.setAxisParams(velocity=cruise)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_driver.py -q`
Expected: all pass (23).

- [ ] **Step 5: Commit**

```bash
git add pystxmcontrol/drivers/mmcMotor.py tests/iocs/test_mmc_driver.py
git commit -m "feat(mmc): constant-velocity fly interface (update_trajectory/moveLine)"
```

---

### Task 4: line_trigger in fly_ioc + register MMC as fly-capable

**Files:**
- Modify: `pystxmcontrol/iocs/fly_ioc.py` (the `daq.config` call inside `_hw_line`, ~line 292)
- Modify: `pystxmcontrol/iocs/config.py:23` (`FLY_CAPABLE_CONTROLLERS`)
- Test: `tests/iocs/test_mmc_fly.py` (new)

**Interfaces:**
- Consumes: `mmcMotor.line_trigger == "INT"` (Task 2); `fly_ioc.FlyGroup`, `build_pvdb_from_slice`.
- Produces: fly hardware path configures the DAQ with `trigger=getattr(motor, "line_trigger", "EXT")` — npt/E712 (no attribute) keep `"EXT"`; `config.FLY_CAPABLE_CONTROLLERS` contains `"mmcController"` so the supervisor routes MMC groups to the fly IOC and `fly_ioc.build_pvdb_from_slice` accepts them.

- [ ] **Step 1: Write the failing tests**

Create `tests/iocs/test_mmc_fly.py`:

```python
"""MMC fly-capability routing + line_trigger plumbing (no hardware)."""
import pytest


def test_mmc_is_fly_capable():
    from pystxmcontrol.iocs.config import FLY_CAPABLE_CONTROLLERS
    assert "mmcController" in FLY_CAPABLE_CONTROLLERS


def test_mmc_motor_declares_internal_trigger():
    from pystxmcontrol.drivers.mmcMotor import mmcMotor
    assert mmcMotor.line_trigger == "INT"


def test_npt_default_stays_external():
    # Drivers without the attribute must keep today's EXT behavior.
    from pystxmcontrol.iocs import fly_ioc
    class NoAttr: pass
    assert getattr(NoAttr(), "line_trigger", "EXT") == "EXT"
    # and the source actually consults the attribute:
    import inspect
    src = inspect.getsource(fly_ioc)
    assert 'getattr(motor, "line_trigger", "EXT")' in src


def test_fly_slice_builds_for_mmc(tmp_path):
    """fly_ioc.build_pvdb_from_slice accepts an mmcController group and
    serves motor records + FLY PVs (simulation)."""
    import json
    from pystxmcontrol.iocs.fly_ioc import build_pvdb_from_slice
    entry = {"type": "primary", "driver": "mmcMotor",
             "controller": "mmcController", "controllerID": "COM99",
             "axis": "x", "minValue": -10.0, "maxValue": 10.0,
             "offset": 0.0, "units": 1.0, "max velocity": 2.0,
             "simulation": 1}
    s = {"kind": "controller", "station": "SIM", "controller_id": "COM99",
         "controller_cls": "mmcController", "label": "MMC", "port": 0,
         "simulation": True,
         "motors": [{"key": "CoarseX", "entry": entry,
                     "pv": "STXMSIM:MMC:CoarseX"}],
         "derived": [], "motor_pv": {"CoarseX": "STXMSIM:MMC:CoarseX"},
         "daqs": [{"key": "default", "prefix": "STXMSIM:DEFAULT",
                   "entry": {"name": "Counter1", "driver": "keysight53230A",
                             "address": "sim", "port": 5025, "channel": 1,
                             "ndim": 0, "gate": False, "record": True,
                             "simulation": True}}]}
    p = tmp_path / "slice.json"
    p.write_text(json.dumps(s))
    from pystxmcontrol.iocs.config import read_slice
    pvdb = build_pvdb_from_slice(read_slice(str(p)))
    names = set(pvdb)
    assert "STXMSIM:MMC:CoarseX" in names
    assert "STXMSIM:MMC:FLY:GO" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_fly.py -q`
Expected: FAIL — `mmcController` not in `FLY_CAPABLE_CONTROLLERS`; `getattr` string absent from fly_ioc source.

- [ ] **Step 3: Implement**

In `pystxmcontrol/iocs/config.py` change line 23:

```python
FLY_CAPABLE_CONTROLLERS = {"E712Controller", "nptController", "mmcController"}
```

In `pystxmcontrol/iocs/fly_ioc.py`, inside `_hw_line` (the hardware path), change the `daq.config` call:

```python
                    stage["name"] = "config"
                    # Trigger source is a driver capability: motors with no
                    # hardware trigger output (e.g. MMC) declare
                    # line_trigger = "INT" and the DAQ free-runs during the
                    # line; absent attribute keeps the EXT line-start
                    # trigger contract (nPoint, E712).
                    line_trigger = getattr(motor, "line_trigger", "EXT")
                    await loop.run_in_executor(None, functools.partial(
                        daq.config, dwell, count=1, samples=n,
                        trigger=line_trigger))
```

(`motor = self._current_motor()` is already in scope in the hardware branch. `initLine`/beam-shutter sequencing is unchanged: with an internal trigger the counter starts on arm, a few ms before the move — accepted skew per the spec.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_fly.py tests\iocs\test_mmc_driver.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pystxmcontrol/iocs/config.py pystxmcontrol/iocs/fly_ioc.py tests/iocs/test_mmc_fly.py
git commit -m "feat(fly): per-motor line_trigger source; register mmcController as fly-capable"
```

---

### Task 5: IOC-level simulation tests over real CA

**Files:**
- Test: append to `tests/iocs/test_mmc_fly.py`

**Interfaces:**
- Consumes: everything above; `tests/iocs/conftest.py`'s `ioc_harness` fixture (starts a caproto server in-process and hands back a threading-client factory — same usage as `tests/iocs/test_npt_fly.py`).
- Produces: proof that an MMC group serves a working motor record and fly line end-to-end in simulation.

- [ ] **Step 1: Write the tests**

Append to `tests/iocs/test_mmc_fly.py` (mirrors `test_npt_fly.py`):

```python
FLY_PREFIX = "STXMSIM:MMC:FLY"


@pytest.fixture
def mmc_fly_ioc(ioc_harness):
    from pystxmcontrol.iocs.base import (MotorRecordGroup, build_controller,
                                         build_motor)
    from pystxmcontrol.iocs.daq_ioc import build_pvdb_for_entry
    from pystxmcontrol.iocs.fly_ioc import FlyGroup

    ctrl = build_controller({"controller": "mmcController",
                             "address": "COM99", "port": 0,
                             "simulation": True})
    entry = {"axis": "x", "minValue": -50.0, "maxValue": 50.0, "offset": 0.0,
             "units": 1.0, "max velocity": 1000.0, "simulation": 1}
    mx = build_motor("mmcMotor", ctrl, dict(entry), "x")
    my = build_motor("mmcMotor", ctrl, dict(entry, axis="y"), "y")

    daq_entry = {"name": "Counter1", "driver": "keysight53230A",
                 "address": "sim", "port": 5025, "channel": 1, "ndim": 0,
                 "gate": False, "record": True, "simulation": True}
    daq_pvdb, daq_group = build_pvdb_for_entry(daq_entry, "STXMSIM:DEFAULT")

    pvdb = {}
    pvdb.update(MotorRecordGroup("STXMSIM:MMC:CoarseX", driver=mx,
                                 motor_config=dict(entry)).pvdb)
    fly = FlyGroup(FLY_PREFIX, motors={"x": mx, "y": my},
                   daq_groups={"default": daq_group}, simulation=True)
    pvdb.update(daq_pvdb)
    pvdb.update(fly.pvdb)
    ioc_harness.start(pvdb)
    return ioc_harness, ioc_harness.client()


def _pvs(ctx, *names):
    pvs = ctx.get_pvs(*names, timeout=15)
    for pv in pvs:
        pv.wait_for_connection(timeout=15)
    return pvs


def test_mmc_motor_record_moves(mmc_fly_ioc):
    _, ctx = mmc_fly_ioc
    val, rbv = _pvs(ctx, "STXMSIM:MMC:CoarseX", "STXMSIM:MMC:CoarseX.RBV")
    val.write(7.25, wait=True, timeout=30)
    assert rbv.read().data[0] == pytest.approx(7.25, abs=1e-6)


def test_mmc_motor_record_rejects_out_of_limits(mmc_fly_ioc):
    _, ctx = mmc_fly_ioc
    (val,) = _pvs(ctx, "STXMSIM:MMC:CoarseX")
    with pytest.raises(Exception):
        val.write(500.0, wait=True, timeout=15)


def test_mmc_fly_line_sim(mmc_fly_ioc):
    import numpy as np
    _, ctx = mmc_fly_ioc
    start, stop, npts, dwell, arm, go, index, data, pos = _pvs(
        ctx, *[f"{FLY_PREFIX}:{s}" for s in (
            "START", "STOP", "NPOINTS", "DWELL", "ARM", "GO",
            "INDEX", "DATA:default", "POS")])
    start.write(-5.0, wait=True); stop.write(5.0, wait=True)
    npts.write(25, wait=True); dwell.write(1.0, wait=True)
    arm.write(1, wait=True, timeout=15)
    go.write(1, wait=True, timeout=60)
    assert index.read().data[0] == 1
    p = np.asarray(pos.read().data, dtype=float)
    d = np.asarray(data.read().data, dtype=float)
    assert len(p) == 25 and len(d) == 25
    assert p[0] == pytest.approx(-5.0) and p[-1] == pytest.approx(5.0)
```

- [ ] **Step 2: Run the new tests**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs\test_mmc_fly.py -q`
Expected: all pass (CA tests take ~10-30 s).

- [ ] **Step 3: Run the whole IOC suite for regressions**

Run: `C:\Users\rp\PycharmProjects\ncs\.venv\Scripts\python.exe -m pytest tests\iocs -q`
Expected: everything green except the two pre-existing `test_config.py` env failures and env-dependent skips.

- [ ] **Step 4: Commit**

```bash
git add tests/iocs/test_mmc_fly.py
git commit -m "test(mmc): IOC-level motor record + fly line over real CA (simulation)"
```

---

### Task 6: Documentation touch-up

**Files:**
- Modify: `pystxmcontrol/iocs/README.md` (add MMC to the supported-controllers / fly notes)

**Interfaces:** none (docs only).

- [ ] **Step 1: Edit README**

In `pystxmcontrol/iocs/README.md`, find the section describing fly-capable controllers (search for `nptController` / `FLY_CAPABLE_CONTROLLERS`) and add:

```markdown
- `mmcController` (Micronix MMC): constant-velocity software-timed fly lines.
  The MMC has no trigger output, so `mmcMotor.line_trigger = "INT"` makes the
  DAQ free-run during the line (start-skew of a few ms; positions are nominal
  `linspace`). Transport is serial (`COM*`/`/dev/tty*`, 38400 8N1) or TCP
  (`address` + nonzero `port`), chosen from the address format.
```

- [ ] **Step 2: Commit**

```bash
git add pystxmcontrol/iocs/README.md
git commit -m "docs(iocs): document MMC support and internal-trigger fly lines"
```

---

## Friday hardware checklist (not part of local execution)

1. Confirm transport (COM port vs Ethernet) and update `motor.json` entry.
2. Verify `STA?` idle bit mask (0x08) against real firmware; adjust `_STATUS_STOPPED_BIT` if needed.
3. Exercise `scripts/testMMC.py` equivalents through CA: jog, limits, stop mid-move.
4. Fly a line; check counts-vs-position skew; decide whether an external gate is worth switching `line_trigger` to `"EXT"`.
5. Measure settle time; tune `timeout` and `_poll` in `motor.json`/driver.

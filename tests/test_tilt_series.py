"""The tilt-series tracker against a simulated instrument.

The fake renders a two-lobed sample wherever its "true" orbit puts it at the current
CoarseR, into whatever field the scan asks for, so the tracker's whole loop — moves,
coarse cross-correlation, fine centring, ptychography placement, database write-back —
runs as it would on the beamline.  The true orbit differs from the planned one by an
error that grows with tilt, which is what the correlation step exists to absorb.
"""

import numpy as np
import pytest

from pystxmcontrol.controller.orbit_database import OrbitDatabase
from pystxmcontrol.controller.tilt_series import (
    OrbitTarget, TiltSeriesConfig, TiltSeriesTracker, angle_list, plan_series,
)
from pystxmcontrol.utils.rotation import orbit

A1 = 13.2444


class FakeInstrument:
    """Motors, scans and images for a sample on a known orbit."""

    def __init__(self, truth, stuck: dict | None = None, energy: float = 851.0, seed=0):
        self.truth = truth                       # angle -> (y, x) of the sample centre
        self.rng = np.random.default_rng(seed)
        self.pos = {"CoarseR": 0.0, "CoarseY": 0.0, "ZonePlateZ": 0.0,
                    "POLARIZATION": 1.0, "Energy": energy}
        self.stuck = stuck or {}
        self.scans = []

    def move(self, motor, pos):
        self.pos[motor] = self.stuck.get(motor, pos)
        if motor == "Energy":                    # derivedEnergy drags ZonePlateZ along
            self.pos["ZonePlateZ"] = self.zp_calibration(pos)

    def position(self, motor):
        return self.pos[motor]

    def run_scan(self, scan, should_stop=lambda: False):
        # What the server does at the start of a single-energy scan.
        if abs(scan["energy_start"] - self.pos["Energy"]) > 0.1:
            self.move("Energy", scan["energy_start"])
        if scan.get("autofocus", True):
            self.pos["ZonePlateZ"] = self.zp_calibration()
        self.scans.append(dict(scan, angle=self.pos["CoarseR"], z=self.pos["ZonePlateZ"]))
        return f"scan{len(self.scans) - 1}"

    def counts(self, path):
        scan = self.scans[int(path[4:])]
        n, rng = scan["x_points"], scan["x_range"]
        step = rng / n
        offsets = (np.arange(n) - (n - 1) / 2) * step
        ys, xs = scan["y_center"] + offsets, scan["x_center"] + offsets
        Y, X = np.meshgrid(ys, xs, indexing="ij")          # rows are y
        ty, tx = self.truth(scan["angle"])
        od = sum(np.exp(-((Y - ty - dy) ** 2 + (X - tx - dx) ** 2) / (2 * 1.2 ** 2))
                 for dy, dx in ((1.5, 0.75), (-1.5, -0.75)))
        # Shot noise: the "auto" threshold fits the background, which needs a width.
        return self.rng.poisson(1000.0 * np.exp(-od)).astype(float)[None]

    def energy(self):
        return self.pos["Energy"]

    def zp_calibration(self, energy=None):
        return -A1 * (self.pos["Energy"] if energy is None else energy)

    def zp_offset(self, z_motor="ZonePlateZ"):
        return -18780.0


def _planned(angle):
    return 200.0 + 0.02 * angle ** 2, -85.0


def _true(angle):
    y, x = _planned(angle)
    return y + 1.0 + 0.04 * angle, x - 0.5 + 0.01 * angle   # model error grows with tilt


ANGLES = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0]


def _targets(angles=ANGLES):
    return [OrbitTarget(a, *_planned(a), zone_plate_z=-11000.0 - a) for a in angles]


def _config(**kw):
    base = dict(stxm_scan={"scan_type": "Spiral Image", "spiral": True, "dwell": 0.2,
                           "energy_start": 851.0},
                ptycho_scan={"scan_type": "Ptychography Image", "dwell": 10.0,
                             "energy_start": 851.0, "x_range": 4.0, "y_range": 2.5,
                             "x_points": 40, "y_points": 25},
                coarse_range=20.0, coarse_points=40, fine_range=15.0, fine_points=50,
                ptycho_shift_x=1.5, settle_s=0.0)
    base.update(kw)
    return TiltSeriesConfig(**base)


@pytest.fixture
def db(tmp_path):
    db = OrbitDatabase(db_path=str(tmp_path / "orbits.db"))
    return db


class TestTracking:

    def test_every_scan_runs_at_the_orbit_focus(self):
        # Energy starts off the series energy and the templates omit autofocus (default
        # on): either alone would put ZonePlateZ back on its calibration at each scan.
        inst = FakeInstrument(_true, energy=700.0)
        result = TiltSeriesTracker(inst, _config(), _targets()).run()
        assert result.status == "complete", result.message
        assert inst.pos["Energy"] == 851.0
        for scan in inst.scans:
            assert scan["z"] == pytest.approx(-11000.0 - scan["angle"])

    def test_follows_the_sample_and_records_pending_points(self, db):
        inst = FakeInstrument(_true)
        sid = db.create_sample("sim")
        result = TiltSeriesTracker(inst, _config(), _targets(), db=db, sample_id=sid).run()

        assert result.status == "complete", result.message
        assert len(result.results) == len(ANGLES)
        for r in result.results:
            ty, tx = _true(r.angle)
            assert r.center_y == pytest.approx(ty, abs=0.3)
            assert r.center_x == pytest.approx(tx, abs=0.3)
            assert r.final_confidence > 0.9
        ptycho = [s for s in inst.scans if s["scan_type"] == "Ptychography Image"]
        assert len(ptycho) == len(ANGLES)
        last = result.results[-1]
        assert ptycho[-1]["x_center"] == pytest.approx(last.center_x + 1.5)

        points = db.get_points(sample_id=sid)
        assert len(points) == len(ANGLES)
        assert all(p["kind"] == "tracked" and not p["approved"] and not p["z_measured"]
                   for p in points)
        assert points[0]["zp_calibration"] == pytest.approx(-A1 * 851.0)
        assert sid not in db.orbit_samples()      # pending points do not count yet

    def test_large_tilt_error_is_fed_forward(self):
        # Without feed-forward the error at 25° (2 µm) is fine; make it grow fast enough
        # that only feeding the last offset forward keeps the sample in the coarse field.
        def runaway(angle):
            y, x = _planned(angle)
            return y + 0.45 * angle, x
        angles = [0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 24.0, 28.0]
        on = TiltSeriesTracker(FakeInstrument(runaway), _config(), _targets(angles)).run()
        off = TiltSeriesTracker(FakeInstrument(runaway), _config(feed_forward=False),
                                _targets(angles)).run()
        assert on.status == "complete", on.message
        assert off.status == "failed"

    def test_lost_sample_stops_at_that_angle(self, db):
        def jumps(angle):
            y, x = _true(angle)
            return (y + 40.0, x) if angle >= 15.0 else (y, x)
        result = TiltSeriesTracker(FakeInstrument(jumps), _config(), _targets()).run()
        assert result.status == "failed"
        assert result.next_index == 3
        assert len(result.results) == 3
        assert "15.0°" in result.message

    def test_resume_starts_with_a_fresh_reference(self):
        result = TiltSeriesTracker(FakeInstrument(_true), _config(), _targets()).run(
            start_index=3)
        assert result.status == "complete"
        assert [r.index for r in result.results] == [3, 4, 5]
        assert result.results[0].cc_confidence is None    # centred, not correlated

    def test_stop_between_angles(self):
        tracker = None

        def on_event(kind, data):
            if kind == "angle_done" and data["index"] == 1:
                tracker.stop()
        tracker = TiltSeriesTracker(FakeInstrument(_true), _config(), _targets(),
                                    on_event=on_event)
        result = tracker.run()
        assert result.status == "stopped"
        assert result.next_index == 2

    def test_motor_that_does_not_arrive_fails_the_angle(self):
        inst = FakeInstrument(_true, stuck={"CoarseR": 0.0})
        result = TiltSeriesTracker(inst, _config(), _targets()).run()
        assert result.status == "failed"
        assert result.next_index == 1
        assert "CoarseR did not reach 5.0" in result.message

    def test_debug_moves_only(self, db):
        inst = FakeInstrument(_true)
        sid = db.create_sample("dry run")
        result = TiltSeriesTracker(inst, _config(debug=True), _targets(), db=db,
                                   sample_id=sid).run()
        assert result.status == "complete"
        assert inst.scans == []
        assert db.get_points(sample_id=sid) == []
        assert inst.pos["CoarseR"] == ANGLES[-1]

    def test_xmcd_alternates_polarization(self):
        inst = FakeInstrument(_true)
        result = TiltSeriesTracker(inst, _config(xmcd=True), _targets(ANGLES[:2])).run()
        assert result.status == "complete"
        assert [r.polarization for r in result.results] == [1.0, -1.0]
        assert sum(len(r.ptycho_files) for r in result.results) == 4

    def test_auto_threshold(self):
        result = TiltSeriesTracker(FakeInstrument(_true), _config(threshold="auto"),
                                   _targets()).run()
        assert result.status == "complete", result.message

    def test_log_file_has_one_line_per_angle(self, tmp_path):
        log = tmp_path / "series.jsonl"
        TiltSeriesTracker(FakeInstrument(_true), _config(), _targets(),
                          log_path=str(log)).run()
        assert len(log.read_text().splitlines()) == len(ANGLES)


class TestClientInstrument:
    """The messages the tracker sends are the ones the control server understands."""

    class _Server:
        def __init__(self):
            self.motorInfo = {"CoarseR": {}, "Energy": {"A0": 0.0, "A1": A1},
                              "ZonePlateZ": {"offset": -18780.0}}
            self.scanConfig = {"Spiral Image": {"driver": "spiral_image", "mode": "spiral"}}
            self.sent = []
            self._busy = 0

        def get_config(self):
            pass

        def send_message(self, m):
            self.sent.append(m)
            if m["command"] == "scan":
                self._busy = 2
                return {"status": True, "data": "/data/NS_1.stxm"}
            if m["command"] == "get_scan_data":
                return {"status": True, "data": {"images": {"default": np.ones((1, 4, 4))}}}
            return {"status": True}

        def get_status(self):
            self._busy -= 1
            return {"mode": "scanning" if self._busy > 0 else "idle"}

        def getMotorPositions(self):
            return {"Energy": 851.0}

    def test_scan_move_read(self):
        from pystxmcontrol.controller.tilt_series import ClientInstrument
        server = self._Server()
        inst = ClientInstrument(server, poll_s=0.0)
        inst.move("CoarseR", 10.0)
        path = inst.run_scan({"scan_type": "Spiral Image", "spiral": True, "x_center": 1.0,
                              "y_center": 2.0, "x_range": 20.0, "y_range": 20.0,
                              "x_points": 100, "y_points": 100})
        assert path == "/data/NS_1.stxm"
        assert inst.counts(path).shape == (1, 4, 4)
        assert inst.zp_calibration() == pytest.approx(-A1 * 851.0)
        assert inst.zp_offset() == -18780.0

        move, scan, read = (m for m in server.sent)
        assert move == {"command": "moveMotor", "axis": "CoarseR", "pos": 10.0}
        region = next(iter(scan["scan"]["scan_regions"].values()))
        assert scan["scan"]["driver"] == "spiral_image"
        assert region["xStep"] == pytest.approx(0.2)          # range/points
        assert read["path"] == path

    def test_unknown_motor_is_refused(self):
        from pystxmcontrol.controller.tilt_series import ClientInstrument, TrackingError
        with pytest.raises(TrackingError, match="no motor named"):
            ClientInstrument(self._Server(), poll_s=0.0).move("CoarseZ", 1.0)


class TestConfig:

    def test_unknown_scan_template_keys_are_rejected(self):
        with pytest.raises(ValueError, match="sample"):
            TiltSeriesTracker(FakeInstrument(_true),
                              _config(stxm_scan={"scan_type": "Spiral Image",
                                                 "sample": "Al2O3-NiFe"}), _targets())

    @pytest.mark.parametrize("change,match", [
        ({"energy_start": None}, "explicit energy_start"),
        ({"energy_points": 5, "energy_stop": 860.0}, "single-energy"),
        ({"energy_list": [851.0, 852.0]}, "single-energy"),
    ])
    def test_scans_that_would_move_energy_are_rejected(self, change, match):
        stxm = {"scan_type": "Spiral Image", "energy_start": 851.0, **change}
        stxm = {k: v for k, v in stxm.items() if v is not None}
        with pytest.raises(ValueError, match=match):
            _config(stxm_scan=stxm).validate()

    def test_templates_must_share_an_energy(self):
        cfg = _config()
        cfg.ptycho_scan["energy_start"] = 852.0
        with pytest.raises(ValueError, match="differ"):
            cfg.validate()

    def test_unknown_settings_are_rejected(self):
        with pytest.raises(ValueError, match="cc_tolerance"):
            TiltSeriesConfig.from_dict({"cc_tolerance": 0.5})


class TestPlanning:

    def test_angle_ranges_merge(self):
        spec = [{"start": -10, "stop": 10, "step": 5}, {"start": 0, "stop": 20, "step": 10}]
        assert angle_list(spec) == [-10.0, -5.0, 0.0, 5.0, 10.0, 20.0]

    def test_anchors_focused_at_another_edge_move_to_the_run_energy(self, db):
        db.import_csv("tests/data/rotation/tomo_orbit_motors.csv")
        truth = orbit.OrbitParams(AY=200.0, AZ=30.0, AX=-85.0, P=250.0)
        GY = 0.96
        angles = [-10.0, 0.0, 10.0]
        Y, X, Zrel = orbit.predict(truth, angles, GY)
        cal = lambda e: -A1 * e                                   # noqa: E731
        fe = [{"angle": a, "coarse_y": y, "sample_x": x, "zone_plate_z": z + cal(708.0),
               "energy": 708.0} for a, y, x, z in zip(angles, Y, X, Zrel)]
        plan = plan_series(fe, [0.0, 30.0], db.orbit_samples(), energy=851.0,
                           zp_calibration=cal, GY=GY)
        _, _, Zexp = orbit.predict(truth, [0.0, 30.0], GY)
        got = [t.zone_plate_z for t in plan.targets]
        np.testing.assert_allclose(got, Zexp + cal(851.0), atol=1e-6)
        assert got[0] - (Zrel[1] + cal(708.0)) == pytest.approx(-A1 * 143.0)

    def test_gy_comes_from_history(self, db):
        db.import_csv("tests/data/rotation/tomo_orbit_motors.csv")
        anchors = [{"angle": a, "coarse_y": 200.0, "sample_x": -85.0, "zone_plate_z": -11000.0}
                   for a in (-10.0, 0.0, 10.0)]
        plan = plan_series(anchors, {"start": -20, "stop": 20, "step": 10},
                           db.orbit_samples(), energy=None, zp_calibration=None)
        assert plan.fit.GY == pytest.approx(0.9614189, rel=1e-5)
        assert len(plan.targets) == 5

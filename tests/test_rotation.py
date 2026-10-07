"""Non-eucentric rotation: orbit model, tracking image processing, orbit database.

The orbit model is checked against predictions captured from the beamline script it was
ported from (rotation_tracker_260620.py, Ni-edge anchors), so the port cannot drift
from what was used on the instrument.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import correlate2d

from pystxmcontrol.controller import orbit_database
from pystxmcontrol.controller.orbit_database import OrbitDatabase, OrbitDatabaseClient
from pystxmcontrol.utils.rotation import imaging, orbit

DATA = Path(__file__).parent / "data" / "rotation"
CSV = DATA / "tomo_orbit_motors.csv"


@pytest.fixture
def reference():
    return json.loads((DATA / "orbit_reference_260620.json").read_text())


@pytest.fixture
def db(tmp_path):
    return OrbitDatabase(db_path=str(tmp_path / "orbits.db"))


# ----------------------------------------------------------------------
# orbit model
# ----------------------------------------------------------------------

class TestOrbitModelMatchesTheScript:

    def test_global_fit_reproduces_gy(self, db, reference):
        db.import_csv(str(CSV))
        GY, params = orbit.fit_global(db.orbit_samples())
        assert GY == pytest.approx(reference["GY"], rel=1e-6)
        assert len(params) == len(reference["params"])

    @pytest.mark.parametrize("variant,small", [("small", True), ("plain", False)])
    def test_anchor_predictions(self, reference, variant, small):
        a = reference["anchors"]
        fit = orbit.fit_from_anchors(a["angles"], a["Y"], a["X"], a["Z"], reference["GY"],
                                     use_small_terms=small)
        Y, X, Z = fit.predict(reference["targets"])
        np.testing.assert_allclose(Y, reference[variant]["Y"], atol=1e-6)
        np.testing.assert_allclose(X, reference[variant]["X"], atol=1e-6)
        np.testing.assert_allclose(Z, reference[variant]["Z"], atol=1e-6)


class TestOrbitFit:

    TRUE = orbit.OrbitParams(AY=200.0, AZ=-150.0, AX=-85.0, P=300.0, DY=4.0, DZ=-6.0)

    def _measure(self, angles, GY=0.96, noise=0.0, seed=0):
        rng = np.random.default_rng(seed)
        Y, X, Z = orbit.predict(self.TRUE, angles, GY)
        n = len(angles)
        return Y + noise * rng.standard_normal(n), X, Z + noise * rng.standard_normal(n)

    def test_three_anchors_near_zero_recover_the_amplitude(self):
        angles = [-10.0, 0.0, 10.0]
        Y, X, Z = self._measure(angles)
        fit = orbit.fit_from_anchors(angles, Y, X, Z, GY=0.96)
        assert not fit.use_small_terms            # too few anchors to separate DY/DZ
        # DY/DZ leak into the offsets, but P — the large-tilt motion — is close.
        assert fit.params.P == pytest.approx(self.TRUE.P, rel=0.05)

    def test_small_terms_chosen_once_anchors_span_enough(self):
        angles = [-30.0, -10.0, 0.0, 10.0, 30.0]
        Y, X, Z = self._measure(angles)
        fit = orbit.fit_from_anchors(angles, Y, X, Z, GY=0.96)
        assert fit.use_small_terms
        for k, v in self.TRUE.as_dict().items():
            assert getattr(fit.params, k) == pytest.approx(v, abs=1e-6)

    def test_uncertainty_grows_away_from_the_anchors(self):
        angles = [-20.0, -10.0, 0.0, 10.0, 20.0]
        Y, X, Z = self._measure(angles, noise=1.0)
        fit = orbit.fit_from_anchors(angles, Y, X, Z, GY=0.96)
        sy, sz = fit.predict_sigma([0.0, 40.0, 70.0])
        assert np.all(np.isfinite(sy)) and np.all(np.isfinite(sz))
        assert sy[0] < sy[1] < sy[2]
        assert sz[0] < sz[1] < sz[2]

    def test_uncertainty_unknown_with_no_residual_freedom(self):
        angles = [0.0, 10.0]
        Y, X, Z = self._measure(angles)
        fit = orbit.fit_from_anchors(angles, Y, X, Z, GY=0.96)
        assert np.all(np.isnan(fit.predict_sigma([30.0])[0]))


# ----------------------------------------------------------------------
# image processing
# ----------------------------------------------------------------------

def _blob(shape=(64, 64), center=(30.0, 34.0), sigma=4.0):
    y, x = np.indices(shape)
    return np.exp(-((y - center[0]) ** 2 + (x - center[1]) ** 2) / (2 * sigma ** 2))


class TestImaging:

    def test_fft_cc_equals_direct_correlate2d(self):
        rng = np.random.default_rng(1)
        ref, mov = rng.random((20, 24)), rng.random((20, 24))
        r, m = ref - ref.mean(), mov - mov.mean()
        direct = correlate2d(r, m, mode="full") / np.sqrt((r ** 2).sum() * (m ** 2).sum())
        np.testing.assert_allclose(imaging._normalized_cc(ref, mov), direct, atol=1e-10)

    def test_shift_recovered_in_um_with_original_sign(self):
        ref = _blob(center=(32.0, 32.0))
        mov = _blob(center=(35.0, 30.0))          # moved +3 rows, -2 columns
        dy, dx, conf = imaging.cc_shift(ref, mov, xstep=0.2, ystep=0.2)
        # reference minus moving, as the script's update `centre - dy` expects
        assert dy == pytest.approx(-3 * 0.2, abs=0.02)
        assert dx == pytest.approx(2 * 0.2, abs=0.02)
        assert 0.9 < conf <= 1.0

    def test_confidence_is_a_correlation_not_an_index(self):
        rng = np.random.default_rng(2)
        _, _, conf = imaging.cc_shift(_blob(), rng.random((64, 64)))
        assert conf < 0.6                          # the script's CC_TOL would now trip
        assert imaging.cc_shift(np.zeros((8, 8)), np.ones((8, 8)))[2] == 0.0

    def test_od_image_handles_spiral_zero_corners(self):
        counts = 1000.0 * np.exp(-_blob())         # absorbing sample on a 1000-count beam
        counts[:5, :5] = 0.0                       # unvisited spiral corner
        od = imaging.od_image(counts[None], smooth_sigma=0)
        assert np.all(np.isfinite(od))
        assert od[30, 34] == pytest.approx(1.0, abs=0.05)
        assert od[0, 0] == 0.0

    def test_bounding_box_shift_of_offset_sample(self):
        img = _blob(center=(40.0, 22.0))
        mask = imaging.center_mask(img, 0.5)
        dy, dx = imaging.bounding_box_shift(mask, xstep=0.1, ystep=0.1)
        assert dy == pytest.approx((40 - 31.5) * 0.1, abs=0.06)
        assert dx == pytest.approx((22 - 31.5) * 0.1, abs=0.06)
        with pytest.raises(ValueError):
            imaging.bounding_box_shift(np.zeros((4, 4), bool))

    def test_gaussian_threshold_sits_above_the_background(self):
        rng = np.random.default_rng(3)
        img = 0.05 * rng.standard_normal((80, 80)) + 2.0 * _blob((80, 80), (40, 40), 6)
        thr, mu, sigma = imaging.threshold_from_gaussian(img)
        assert mu == pytest.approx(0.0, abs=0.02)
        assert thr == pytest.approx(mu + 5 * sigma)

    def test_crop_spiral_image(self):
        out = imaging.crop_spiral_image(np.ones((100, 100)))
        assert out.shape == (62, 62)               # 2 * int((50 - 5) * cos 45°)
        with pytest.raises(ValueError):
            imaging.crop_spiral_image(np.ones((10, 12)))


# ----------------------------------------------------------------------
# orbit database
# ----------------------------------------------------------------------

class TestOrbitDatabase:

    def test_import_keeps_every_csv_row(self, db):
        ids = db.import_csv(str(CSV))
        samples = db.list_samples()
        assert [s["id"] for s in samples] == ids
        assert sum(s["n_approved"] for s in samples) == sum(1 for _ in open(CSV)) - 1
        assert all(s["n_pending"] == 0 for s in samples)

    def test_tracked_points_wait_for_approval(self, db):
        sid = db.create_sample("tomo test")
        for a in (-10.0, 0.0, 10.0):
            db.add_point(sid, a, 100.0, -85.0, -9700.0, kind="anchor")
        tracked = [db.add_point(sid, a, 110.0, -85.0, -9750.0, kind="tracked",
                                cc_confidence=0.9) for a in (20.0, 30.0)]
        assert len(db.orbit_samples()[sid]["angle"]) == 3
        assert db.list_samples()[0]["n_pending"] == 2

        assert db.approve_points(sid, point_ids=tracked[:1]) == 1
        assert len(db.orbit_samples()[sid]["angle"]) == 4
        assert db.discard_pending(sid) == 1
        assert db.list_samples()[0]["n_pending"] == 0

    def test_z_is_relative_to_the_calibration_at_its_energy(self, db):
        sid = db.create_sample("two edges")
        cal_fe, cal_ni = -13.2444 * 708.0, -13.2444 * 851.0
        db.add_point(sid, 0.0, 0, 0, cal_fe + 25.0, energy=708.0, zp_calibration=cal_fe)
        db.add_point(sid, 10.0, 0, 0, cal_ni + 15.0, energy=851.0, zp_calibration=cal_ni)
        db.add_point(sid, 20.0, 0, 0, -500.0)            # no calibration recorded: raw
        assert db.orbit_samples()[sid]["zone_plate_z"] == pytest.approx([25.0, 15.0, -500.0])

    def test_samples_too_short_to_fit_are_left_out(self, db):
        sid = db.create_sample("two points")
        db.add_point(sid, 0.0, 0, 0, 0)
        db.add_point(sid, 5.0, 0, 0, 0)
        assert sid not in db.orbit_samples()

    def test_rejects_unknown_kind_and_fields(self, db):
        sid = db.create_sample("x")
        with pytest.raises(ValueError):
            db.add_point(sid, 0, 0, 0, 0, kind="guess")
        with pytest.raises(ValueError):
            db.add_point(sid, 0, 0, 0, 0, colour="red")

    def test_deleting_a_sample_removes_its_points(self, db):
        sid = db.create_sample("gone")
        db.add_point(sid, 0, 0, 0, 0)
        db.delete_sample(sid)
        assert db.get_points(sample_id=sid) == []


class TestOrbitDatabaseClient:
    """The client round-trips through the same dispatch the server's orbit_db runs."""

    class _Loopback:
        def __init__(self, db):
            self.db = db

        def send_message(self, message):
            assert message["command"] == "orbit_db"
            try:
                data = orbit_database.dispatch(self.db, message["action"], message["args"])
                return {"status": True, "data": data}
            except Exception as e:
                return {"status": False, "error": str(e)}

    def test_round_trip(self, db):
        client = OrbitDatabaseClient(self._Loopback(db))
        sid = client.create_sample(label="remote")
        for a in (-10.0, 0.0, 10.0):
            client.add_point(sample_id=sid, angle=a, coarse_y=1.0, sample_x=2.0,
                             zone_plate_z=3.0)
        assert list(client.orbit_samples()) == [sid]

    def test_server_only_methods_are_not_reachable(self, db):
        client = OrbitDatabaseClient(self._Loopback(db))
        with pytest.raises(AttributeError):
            client.import_csv
        with pytest.raises(RuntimeError, match="unknown orbit_db action"):
            client._request("import_csv", path="/etc/passwd")

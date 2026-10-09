"""Tilt-series tracking for non-eucentric tomography.

The rotation axis does not pass through the sample, so at every CoarseR angle the sample
has moved: the orbit model (``utils.rotation.orbit``) predicts where, and this module
finds it there and takes the data.  Per angle:

1. Move CoarseR, CoarseY and ZonePlateZ to the predicted orbit position (and set the
   polarization in XMCD mode), and check CoarseR and CoarseY actually arrived.
2. Take a coarse STXM image around the prediction and cross-correlate it with the
   previous angle's image to find where the sample went.
3. Take a fine STXM image there and recentre on the sample mask's bounding box.
4. Confirm the result still looks like the previous angle, then run ptychography at
   the centre (twice, with opposite polarization, in XMCD mode).

The first angle has no previous image; it centres on the coarse image's mask instead.
When anything fails — a motor that does not arrive, a correlation below tolerance, an
empty mask — the run stops at that angle and says so; :meth:`TiltSeriesTracker.run`
with ``start_index`` resumes from there with a fresh reference.

Ported from the beamline script ``rotation_tracker_260620.py``.  Changes in behaviour:

* The correlation confidence is the real peak correlation (the script compared the
  peak's array index to the tolerance, so a lost sample never stopped it).
* The reference image's own offset from centre is carried forward.  The script took
  every reference as centred, but one kept without a recentring retake can be off by
  up to the retake tolerance plus the correlation shift, and that error passed into the
  next angle's correlation.
* ``feed_forward`` adds the last angle's measured-minus-predicted offset to the next
  prediction, so a model error that grows smoothly with tilt does not walk the sample
  out of the coarse field.
* Energy is set once before the first angle and autofocus is forced off.  The server
  resets ZonePlateZ to its calibration whenever a scan moves Energy (Energy more than
  0.1 eV off) or autofocuses (ScanModel's default), so in the script the first angle's
  scans could run at the calibrated focus rather than the orbit's.
* Each centred position is written to the orbit database as a *pending* tracked point
  (ZonePlateZ marked as predicted, not measured) for the user to approve at the end.
"""

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field, fields

import numpy as np

from pystxmcontrol.controller.scan_conversion import build_server_scan
from pystxmcontrol.controller.scan_model import ScanModel
from pystxmcontrol.utils.rotation import imaging

log = logging.getLogger(__name__)

# Tighter than the server's default 0.1 eV energy deadband, so scans never move Energy.
ENERGY_MATCH_EV = 0.05


# ----------------------------------------------------------------------
# configuration
# ----------------------------------------------------------------------

@dataclass
class TiltSeriesConfig:
    """Everything the tracker needs besides the orbit itself.  Distances are µm."""

    # update_scan-style templates (ScanModel fields).  The tracker sets the geometry.
    stxm_scan: dict = field(default_factory=lambda: {"scan_type": "Spiral Image",
                                                     "spiral": True, "dwell": 0.2,
                                                     "autofocus": False})
    ptycho_scan: dict | None = None          # None: track only, no ptychography

    coarse_range: float = 20.0
    coarse_points: int = 100
    fine_range: float = 15.0
    fine_points: int = 75

    # Sample mask: a fraction of the image maximum, or "auto" (background Gaussian fit).
    threshold: float | str = 0.3
    align_to_fiducial: bool = False          # track transmitted counts, not OD
    open_kernel: int = 3
    close_kernel: int = 3

    ptycho_shift_x: float = 0.0              # ptychography centre relative to the sample
    ptycho_shift_y: float = 0.0

    cc_tol: float = 0.6                      # minimum peak correlation to trust
    thresh_var_tol: float = 0.25             # "auto" threshold: allowed mu/sigma drift
    recenter_tol: float = 0.5                # retake the coarse image beyond this shift
    feed_forward: bool = True

    rotation_motor: str = "CoarseR"
    y_motor: str = "CoarseY"
    z_motor: str = "ZonePlateZ"
    rotation_tol: float = 0.3                # degrees
    y_tol: float = 1.0
    settle_s: float = 5.0                    # wait before re-checking a motor

    xmcd: bool = False
    polarization_motor: str = "POLARIZATION"
    polarization_start: float = 1.0
    polarization_tol: float = 0.1
    polarization_timeout_s: float = 60.0

    debug: bool = False                      # move motors only; no scans, no database

    @classmethod
    def from_dict(cls, d: dict) -> "TiltSeriesConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown tilt-series settings: {sorted(unknown)}")
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def energy(self) -> float:
        """The single energy every scan of the series runs at."""
        return float(self.stxm_scan["energy_start"])

    def validate(self) -> None:
        """Reject scan templates that would silently undo the orbit's ZonePlateZ.

        The server puts ZonePlateZ back on its calibration (A0 - A1*E) whenever it moves
        Energy — any multi-energy scan, or a single-energy scan more than the energy
        deadband from the current energy — and on every scan with autofocus on.  So the
        series runs at one energy, shared by both templates and set once before the
        first angle (:meth:`TiltSeriesTracker.run`), and autofocus is forced off.
        ScanModel ignores unknown keys, so those are refused here too: the beamline
        script passed sample=..., not a field (sample_description is), and the name
        was dropped without a word.
        """
        energies = []
        for name in ("stxm_scan", "ptycho_scan"):
            template = getattr(self, name)
            if template is None:
                continue
            unknown = set(template) - set(ScanModel.model_fields)
            if unknown:
                raise ValueError(f"{name} has keys that are not scan fields: {sorted(unknown)}")
            if "energy_start" not in template:
                raise ValueError(f"{name} needs an explicit energy_start (eV)")
            start = float(template["energy_start"])
            stop = float(template.get("energy_stop", start))
            if template.get("energy_list") or template.get("energy_regions") \
                    or int(template.get("energy_points", 1)) != 1 or stop != start:
                raise ValueError(f"{name} must be a single-energy scan: moving Energy "
                                 "resets ZonePlateZ and loses the orbit's focus")
            energies.append(start)
            template.update(autofocus=False, energy_stop=start, energy_points=1)
            ScanModel(**template)
        if len(set(energies)) > 1:
            raise ValueError(f"stxm_scan and ptycho_scan energies differ ({energies}); "
                             "switching between them would reset ZonePlateZ every scan")


@dataclass
class OrbitTarget:
    """Predicted motor positions at one angle."""
    angle: float
    coarse_y: float
    sample_x: float
    zone_plate_z: float


def plan_targets(fit, angles, zp_calibration: float = 0.0) -> list[OrbitTarget]:
    """Targets from an ``OrbitFit`` at *angles*.

    The orbit database fits ZonePlateZ relative to the zone-plate calibration, so pass
    the calibration (A0 - A1*E) at the energy the series will run at to get motor units.
    """
    Y, X, Z = fit.predict(angles)
    return [OrbitTarget(float(a), float(y), float(x), float(z) + zp_calibration)
            for a, y, x, z in zip(np.asarray(angles, float), Y, X, Z)]


def angle_list(spec) -> list[float]:
    """Angles from a list, or ``{"start", "stop", "step"}`` (stop inclusive), or several
    such ranges ``[{...}, {...}]`` merged — e.g. fine steps near zero, coarse at large tilt.
    """
    if isinstance(spec, dict):
        spec = [spec]
    out = []
    for item in spec:
        if isinstance(item, dict):
            start, stop, step = float(item["start"]), float(item["stop"]), float(item["step"])
            out.extend(np.arange(start, stop + step / 2, step).tolist())
        else:
            out.append(float(item))
    return [float(a) for a in np.unique(np.round(out, 6))]


@dataclass
class SeriesPlan:
    """The fit and targets for one tilt series, and what they rest on."""
    fit: object                              # orbit.OrbitFit
    targets: list
    sigma_y: list
    sigma_z: list
    zp_calibration: float                    # at the run energy; added to relative Z
    energy: float | None
    history_samples: list                    # database samples GY was fit from

    def table(self) -> str:
        lines = [f"{'CoarseR':>8} {'CoarseY':>10} {'±':>6} {'SampleX':>9} "
                 f"{'ZonePlateZ':>11} {'±':>6}"]
        for t, sy, sz in zip(self.targets, self.sigma_y, self.sigma_z):
            lines.append(f"{t.angle:>8.1f} {t.coarse_y:>10.1f} {sy:>6.1f} {t.sample_x:>9.1f} "
                         f"{t.zone_plate_z:>11.1f} {sz:>6.1f}")
        return "\n".join(lines)


def plan_series(anchors: list[dict], angles, history: dict, energy: float | None,
                zp_calibration, use_small_terms: bool | None = None,
                scale: float | None = None, GY: float | None = None) -> SeriesPlan:
    """Fit an orbit to *anchors* and predict *angles*.

    *anchors* are dicts with ``angle``, ``coarse_y``, ``sample_x``, ``zone_plate_z`` and
    optionally ``zp_calibration`` (as recorded in the database) or ``energy`` (the
    energy they were focused at; default *energy*).
    *history* is ``OrbitDatabase.orbit_samples()`` output, for GY — leave the sample
    being planned out of it.  *zp_calibration* is a callable ``energy -> A0 - A1*E`` (or
    None when the instrument has no calibration), so anchors focused at another edge are
    brought to the run energy.
    """
    from pystxmcontrol.utils.rotation import orbit

    scale = orbit.DEFAULT_SCALE if scale is None else scale
    if GY is None:
        if not history:
            raise ValueError("no orbit history to fit GY from; pass GY explicitly")
        GY, _ = orbit.fit_global(history, scale=scale)

    def cal(e):
        if zp_calibration is None or e is None:
            return 0.0
        return float(zp_calibration(e))

    def anchor_cal(a):
        # A calibration recorded with the anchor wins: A0 may have changed since.
        if a.get("zp_calibration") is not None:
            return float(a["zp_calibration"])
        return cal(a["energy"] if a.get("energy") is not None else energy)

    z_rel = [a["zone_plate_z"] - anchor_cal(a) for a in anchors]
    fit = orbit.fit_from_anchors([a["angle"] for a in anchors],
                                 [a["coarse_y"] for a in anchors],
                                 [a["sample_x"] for a in anchors], z_rel, GY,
                                 use_small_terms=use_small_terms, scale=scale)
    angles = angle_list(angles)
    run_cal = cal(energy)
    sy, sz = fit.predict_sigma(angles)
    return SeriesPlan(fit=fit, targets=plan_targets(fit, angles, run_cal),
                      sigma_y=[float(v) for v in sy], sigma_z=[float(v) for v in sz],
                      zp_calibration=run_cal, energy=energy,
                      history_samples=sorted(history))


# ----------------------------------------------------------------------
# results
# ----------------------------------------------------------------------

@dataclass
class AngleResult:
    index: int
    angle: float                             # target
    angle_read: float | None = None
    predicted_y: float = 0.0
    predicted_x: float = 0.0
    zone_plate_z: float = 0.0
    center_y: float | None = None            # where the sample was found
    center_x: float | None = None
    cc_confidence: float | None = None       # coarse image vs previous reference
    final_confidence: float | None = None    # after centring
    threshold: float | None = None
    polarization: float | None = None
    stxm_files: list = field(default_factory=list)
    ptycho_files: list = field(default_factory=list)
    point_id: int | None = None
    elapsed_s: float = 0.0


@dataclass
class TiltSeriesResult:
    status: str                              # "complete" | "stopped" | "failed"
    message: str
    results: list
    next_index: int                          # resume from here
    elapsed_s: float

    def summary(self) -> dict:
        return {"status": self.status, "message": self.message,
                "completed": len(self.results), "next_index": self.next_index,
                "elapsed_s": round(self.elapsed_s, 1)}


class TrackingError(RuntimeError):
    """The sample or a motor was lost at the current angle; the run stops here."""


class _Stopped(Exception):
    pass


# ----------------------------------------------------------------------
# instrument
# ----------------------------------------------------------------------

class ClientInstrument:
    """The few instrument operations the tracker uses, over an ``InstrumentClient``.

    ``ScripterClient(scripter(host, port))`` for a headless run; the GUI's client or the
    agent's works the same, since all of them speak the same server commands.
    """

    def __init__(self, client, poll_s: float = 1.0):
        self.client = client
        self.poll_s = poll_s
        if not getattr(client, "motorInfo", None):
            client.get_config()

    def move(self, motor: str, pos: float) -> None:
        if motor not in self.client.motorInfo:
            raise TrackingError(f"no motor named {motor!r} in this instrument's config")
        response = self.client.send_message({"command": "moveMotor", "axis": motor,
                                             "pos": float(pos)})
        if response is None:
            raise TrackingError(f"no response moving {motor} to {pos}")

    def position(self, motor: str) -> float:
        return float(self.client.getMotorPositions()[motor])

    def run_scan(self, scan: dict, should_stop=lambda: False) -> str:
        """Run one scan (ScanModel fields) to completion; returns the server's file path."""
        server_scan = build_server_scan(ScanModel(**scan).model_dump(),
                                        self.client.scanConfig)
        response = self.client.send_message({"command": "scan", "scan": server_scan})
        if not response or not response.get("status"):
            raise TrackingError(f"server refused the {scan.get('scan_type')} scan: "
                                f"{(response or {}).get('data')}")
        path = response.get("data")
        time.sleep(self.poll_s)
        while (self.client.get_status() or {}).get("mode") != "idle":
            if should_stop():
                self.cancel()
            time.sleep(self.poll_s)
        return path

    def cancel(self) -> None:
        self.client.send_message({"command": "cancel"})

    def counts(self, path: str, detector: str = "default") -> np.ndarray:
        """The first frame's counts of a saved scan, read by the server."""
        response = self.client.send_message({"command": "get_scan_data", "path": path,
                                             "frames": None, "detector": detector,
                                             "region": 0})
        if not response or not response.get("status"):
            raise TrackingError(f"could not read {path}: {(response or {}).get('data')}")
        images = response["data"].get("images") or {}
        image = images.get(detector)
        if image is None and images:
            image = next(iter(images.values()))
        if image is None:
            raise TrackingError(f"{path} holds no image data")
        return np.asarray(image)

    def energy(self) -> float:
        return self.position("Energy")

    def zp_calibration(self, energy: float | None = None) -> float | None:
        """A0 - A1*E: where the Energy motor puts ZonePlateZ at *energy*."""
        info = self.client.motorInfo.get("Energy") or {}
        if "A0" not in info or "A1" not in info:
            return None
        if energy is None:
            energy = self.energy()
        return float(info["A0"]) - float(info["A1"]) * float(energy)

    def zp_offset(self, z_motor: str = "ZonePlateZ") -> float | None:
        offset = (self.client.motorInfo.get(z_motor) or {}).get("offset")
        return None if offset is None else float(offset)


# ----------------------------------------------------------------------
# tracker
# ----------------------------------------------------------------------

class TiltSeriesTracker:
    """Run a tilt series along predicted orbit targets.

    *db* is an ``OrbitDatabase`` or ``OrbitDatabaseClient``; with *sample_id*, each
    centred position is written there as a pending tracked point.  *log_path* gets one
    JSON line per completed angle, so a crashed run still leaves its record.
    *on_event* is called with ``(kind, data)`` for progress ("angle_start",
    "angle_done", "scan", "warning", "finished").
    """

    def __init__(self, instrument, config: TiltSeriesConfig, targets: list[OrbitTarget],
                 db=None, sample_id: int | None = None, log_path: str | None = None,
                 on_event=None):
        self.inst = instrument
        self.cfg = config
        self.targets = list(targets)
        self.db = db
        self.sample_id = sample_id
        self.log_path = log_path
        self._on_event = on_event
        self._stop = threading.Event()
        self._abort_scan = False
        self.cfg.validate()

    # -- control ---------------------------------------------------------

    def stop(self, abort_scan: bool = False) -> None:
        """Stop after the current step; *abort_scan* also cancels a scan in progress."""
        self._abort_scan = abort_scan
        self._stop.set()

    def _check_stop(self):
        if self._stop.is_set():
            raise _Stopped()

    def _should_abort_scan(self) -> bool:
        return self._stop.is_set() and self._abort_scan

    def _emit(self, kind: str, **data):
        log.info("tilt series %s: %s", kind, data)
        if self._on_event is not None:
            try:
                self._on_event(kind, data)
            except Exception:
                log.exception("tilt-series event callback failed")

    # -- run -------------------------------------------------------------

    def run(self, start_index: int = 0) -> TiltSeriesResult:
        """Track every target from *start_index*; returns when done, stopped or failed."""
        self._stop.clear()
        t0 = time.time()
        results: list[AngleResult] = []
        self._ref = None               # (image, offset_y, offset_x) of the last good angle
        self._ref_stats = None         # (mu, sigma) of the first "auto" threshold fit
        self._last_stats = None
        self._residual = (0.0, 0.0)    # last measured - predicted, for feed_forward
        self._polar = self.cfg.polarization_start
        self._energy = self.cfg.energy
        self._zp_cal = self._safe(lambda: self.inst.zp_calibration(self._energy))
        self._zp_offset = self._safe(lambda: self.inst.zp_offset(self.cfg.z_motor))

        status, message, index = "complete", "", start_index
        try:
            if not self.cfg.debug:
                self._set_energy()
            for index in range(start_index, len(self.targets)):
                self._check_stop()
                result = self._track_angle(index)
                results.append(result)
                self._record(result)
                self._emit("angle_done", index=index, total=len(self.targets),
                           angle=result.angle, elapsed_s=round(time.time() - t0, 1))
            index = len(self.targets)
            message = f"tracked all {len(self.targets) - start_index} angles"
        except _Stopped:
            status, message = "stopped", f"stopped by request before angle index {index}"
        except TrackingError as e:
            status = "failed"
            message = (f"at angle {self.targets[index].angle}° (index {index}): {e}. "
                       + (f"Last good angle {results[-1].angle}°." if results else
                          "No angle completed."))
        result = TiltSeriesResult(status, message, results, index, time.time() - t0)
        self._emit("finished", **result.summary())
        return result

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception as e:
            log.warning("tilt series: %s", e)
            return None

    # -- one angle -------------------------------------------------------

    def _track_angle(self, i: int) -> AngleResult:
        t0 = time.time()
        cfg, tgt = self.cfg, self.targets[i]
        py = tgt.coarse_y + (self._residual[0] if cfg.feed_forward else 0.0)
        px = tgt.sample_x + (self._residual[1] if cfg.feed_forward else 0.0)
        res = AngleResult(index=i, angle=tgt.angle, predicted_y=py, predicted_x=px,
                          zone_plate_z=tgt.zone_plate_z)
        self._emit("angle_start", index=i, angle=tgt.angle, coarse_y=py, sample_x=px,
                   zone_plate_z=tgt.zone_plate_z)

        self.inst.move(cfg.rotation_motor, tgt.angle)
        self.inst.move(cfg.y_motor, py)
        self.inst.move(cfg.z_motor, tgt.zone_plate_z)
        if cfg.xmcd:
            self._set_polarization(self._polar)
            res.polarization = self._polar
        res.angle_read = self._verify(cfg.rotation_motor, tgt.angle, cfg.rotation_tol)
        self._verify(cfg.y_motor, py, cfg.y_tol)
        if cfg.debug:
            res.elapsed_s = time.time() - t0
            return res
        self._check_stop()

        coarse_step = cfg.coarse_range / cfg.coarse_points
        fine_step = cfg.fine_range / cfg.fine_points
        coarse, path = self._image(px, py, coarse=True)
        res.stxm_files.append(path)

        if self._ref is None:
            # No previous angle: centre on the coarse image's mask.
            thr = self._threshold(coarse)
            dy, dx = self._mask_shift(coarse, thr, coarse_step)
            cy, cx = py + dy, px + dx
            ref, oy, ox = coarse, dy, dx
            if max(abs(dy), abs(dx)) > cfg.recenter_tol:
                self._check_stop()
                ref, path = self._image(cx, cy, coarse=True)
                res.stxm_files.append(path)
                oy = ox = 0.0
            res.threshold = thr
            res.final_confidence = 1.0
        else:
            ref_img, ref_oy, ref_ox = self._ref
            sy, sx, conf = imaging.cc_shift(ref_img, coarse, coarse_step, coarse_step)
            res.cc_confidence = conf
            if conf < cfg.cc_tol:
                raise TrackingError(f"coarse image correlation {conf:.2f} is below "
                                    f"{cfg.cc_tol}: the sample is not where predicted")
            # The sample sits at (reference offset - shift) from this image's centre.
            cy, cx = py + ref_oy - sy, px + ref_ox - sx
            self._check_stop()

            fine, path = self._image(cx, cy, coarse=False)
            res.stxm_files.append(path)
            thr = self._threshold(fine)
            if self._background_drifted():
                self._emit("warning", index=i,
                           message="image background changed; retaking the fine image")
                self._check_stop()
                fine, path = self._image(cx, cy, coarse=False)
                res.stxm_files.append(path)
                thr = self._threshold(fine)
            dy, dx = self._mask_shift(fine, thr, fine_step)
            cy, cx = cy + dy, cx + dx
            res.threshold = thr

            if max(abs(dy), abs(dx)) > cfg.recenter_tol:
                self._check_stop()
                ref, path = self._image(cx, cy, coarse=True)
                res.stxm_files.append(path)
                oy = ox = 0.0
            else:
                ref, oy, ox = coarse, cy - py, cx - px
            res.final_confidence = imaging.cc_confidence(ref_img, ref)
            if res.final_confidence < cfg.cc_tol:
                raise TrackingError(f"after centring, correlation with the previous angle "
                                    f"is {res.final_confidence:.2f} (< {cfg.cc_tol})")

        self._ref = (ref, oy, ox)
        res.center_y, res.center_x = cy, cx
        # Measured minus model (not minus the fed-forward prediction), so it does not
        # accumulate.  The sample was found there, so however large, it is real.
        self._residual = (cy - tgt.coarse_y, cx - tgt.sample_x)

        if cfg.ptycho_scan is not None:
            self._check_stop()
            res.ptycho_files.append(self._ptycho(cx, cy))
            if cfg.xmcd:
                self._polar = -self._polar
                self._set_polarization(self._polar)
                res.ptycho_files.append(self._ptycho(cx, cy))
        res.elapsed_s = time.time() - t0
        return res

    # -- steps -----------------------------------------------------------

    def _stxm_geometry(self, x, y, coarse: bool) -> dict:
        rng = self.cfg.coarse_range if coarse else self.cfg.fine_range
        pts = self.cfg.coarse_points if coarse else self.cfg.fine_points
        return {**self.cfg.stxm_scan, "x_center": float(x), "y_center": float(y),
                "x_range": rng, "y_range": rng, "x_points": pts, "y_points": pts}

    def _image(self, x, y, coarse: bool):
        scan = self._stxm_geometry(x, y, coarse)
        self._emit("scan", image="coarse" if coarse else "fine", x_center=x, y_center=y)
        path = self.inst.run_scan(scan, should_stop=self._should_abort_scan)
        self._check_stop()
        counts = self.inst.counts(path)
        if self.cfg.align_to_fiducial:
            image = imaging.crop_spiral_image(imaging.amplitude_image(counts))
        else:
            image = imaging.od_image(counts)
        return image, path

    def _ptycho(self, cx, cy) -> str:
        scan = {**self.cfg.ptycho_scan, "x_center": float(cx + self.cfg.ptycho_shift_x),
                "y_center": float(cy + self.cfg.ptycho_shift_y)}
        self._emit("scan", image="ptycho", x_center=scan["x_center"],
                   y_center=scan["y_center"])
        return self.inst.run_scan(scan, should_stop=self._should_abort_scan)

    def _threshold(self, image) -> float:
        """The mask threshold: a fraction of the maximum, or from the background fit.

        With "auto", the first fit of the run is kept as the reference background
        (``_ref_stats``) and every fit is left in ``_last_stats`` for
        :meth:`_background_drifted`.
        """
        if self.cfg.threshold != "auto":
            return float(self.cfg.threshold) * float(np.max(image))
        try:
            thr, mu, sigma = imaging.threshold_from_gaussian(image)
        except ValueError as e:
            raise TrackingError(str(e)) from e
        self._last_stats = (mu, sigma)
        if self._ref_stats is None:
            self._ref_stats = (mu, sigma)
        return thr

    def _background_drifted(self) -> bool:
        """Whether the last "auto" fit moved more than thresh_var_tol from the reference."""
        if self.cfg.threshold != "auto" or self._ref_stats is None:
            return False
        (mu, sigma), (ref_mu, ref_sigma) = self._last_stats, self._ref_stats
        tol = self.cfg.thresh_var_tol
        return abs(mu - ref_mu) > tol or abs(sigma - ref_sigma) > tol

    def _mask_shift(self, image, threshold, step):
        mask = imaging.center_mask(image, threshold, self.cfg.open_kernel,
                                   self.cfg.close_kernel)
        try:
            return imaging.bounding_box_shift(mask, step, step)
        except ValueError as e:
            raise TrackingError(str(e)) from e

    def _set_energy(self) -> None:
        """Put Energy on the series energy before any ZonePlateZ move.

        Every scan then finds Energy inside the server's deadband and leaves it — and
        so ZonePlateZ — alone.  Moving Energy here resets ZonePlateZ to its calibration,
        which the first angle's move then replaces with the orbit's.
        """
        if abs(self.inst.energy() - self._energy) > ENERGY_MATCH_EV:
            self._emit("energy", energy=self._energy)
            self.inst.move("Energy", self._energy)
        actual = self.inst.energy()
        if abs(actual - self._energy) > ENERGY_MATCH_EV:
            raise TrackingError(f"Energy is at {actual} eV, not the series' {self._energy} eV; "
                                "scans would move it and reset ZonePlateZ")

    def _verify(self, motor: str, target: float, tol: float) -> float:
        """Confirm *motor* reached *target*: wait, re-check, re-command once, re-check."""
        pos = self.inst.position(motor)
        if abs(pos - target) <= tol:
            return pos
        self._emit("warning", message=f"{motor} at {pos}, target {target}; waiting")
        time.sleep(self.cfg.settle_s)
        pos = self.inst.position(motor)
        if abs(pos - target) <= tol:
            return pos
        self.inst.move(motor, target)
        time.sleep(self.cfg.settle_s)
        pos = self.inst.position(motor)
        if abs(pos - target) <= tol:
            return pos
        raise TrackingError(f"{motor} did not reach {target} (at {pos}, tolerance {tol})")

    def _set_polarization(self, value: float) -> None:
        """Move the (slow) polarization motor and wait for it to settle on target."""
        cfg = self.cfg
        self.inst.move(cfg.polarization_motor, value)
        deadline = time.time() + cfg.polarization_timeout_s
        prev = self.inst.position(cfg.polarization_motor)
        time.sleep(1.0)
        while True:
            pos = self.inst.position(cfg.polarization_motor)
            if abs(pos - prev) < 1e-6:
                break
            if time.time() > deadline:
                raise TrackingError(f"{cfg.polarization_motor} still moving after "
                                    f"{cfg.polarization_timeout_s:.0f} s")
            prev = pos
            time.sleep(0.5)
        if abs(pos - value) > cfg.polarization_tol:
            raise TrackingError(f"{cfg.polarization_motor} settled at {pos}, not {value}")

    # -- record ----------------------------------------------------------

    def _record(self, res: AngleResult) -> None:
        if self.db is not None and self.sample_id is not None and not self.cfg.debug \
                and res.center_y is not None:
            try:
                res.point_id = self.db.add_point(
                    sample_id=self.sample_id,
                    angle=res.angle_read if res.angle_read is not None else res.angle,
                    coarse_y=res.center_y, sample_x=res.center_x,
                    zone_plate_z=res.zone_plate_z, kind="tracked",
                    energy=self._energy, zp_calibration=self._zp_cal,
                    zp_offset=self._zp_offset, z_measured=False,
                    cc_confidence=res.final_confidence,
                    scan_file=(res.ptycho_files or res.stxm_files or [None])[-1])
            except Exception as e:
                # Losing a database row must not lose the tilt series.
                self._emit("warning", message=f"could not record angle {res.angle}: {e}")
        if self.log_path:
            try:
                with open(self.log_path, "a") as f:
                    f.write(json.dumps(asdict(res)) + "\n")
            except OSError as e:
                self._emit("warning", message=f"could not write {self.log_path}: {e}")

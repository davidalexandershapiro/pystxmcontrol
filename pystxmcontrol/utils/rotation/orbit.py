"""Orbit model for a sample rotated off the rotation axis (non-eucentric tomography).

With phi = scale * CoarseR (the encoder reads larger than the physical angle), a sample
at in-plane distance P from the axis follows

    CoarseY    = AY + GY * P * sec(phi) + DY * tan(phi)
    ZonePlateZ = AZ -      P * tan(phi) + DZ * sec(phi)
    SampleX    = AX

AY/AZ/AX place the sample, P is its orbit amplitude and DY/DZ absorb small misalignments.
GY is an instrument constant shared by every sample, so it is fit once from the history
of past orbits (:func:`fit_global`); a new sample then needs only a few anchor
measurements (:func:`fit_from_anchors`).  Y and Z share P, which is what makes three
anchors near zero tilt enough: CoarseY's secant is flat there but ZonePlateZ's tangent
is not, so Z pins the amplitude.

ZonePlateZ is whatever frame the caller supplies.  The orbit database hands it over
relative to the zone-plate calibration at the energy it was measured at, so a fit made
at one absorption edge predicts focus at another; AZ is per sample, so the global fit
does not care which frame the history is in.
"""

from dataclasses import dataclass, asdict

import numpy as np
from scipy.optimize import least_squares

DEFAULT_SCALE = 0.89        # encoder angle -> physical angle
DEFAULT_GY = 0.96           # starting guess for the global fit

# Below this many anchors, or this angular span, DY/DZ are not separable from AY/AZ/P.
SMALL_TERMS_MIN_ANCHORS = 5
SMALL_TERMS_MIN_SPAN_DEG = 40.0


def basis(angle_deg, scale: float = DEFAULT_SCALE):
    """``(sec(phi), tan(phi))`` with phi = scale * angle, angle in encoder degrees."""
    phi = np.deg2rad(scale * np.asarray(angle_deg, float))
    return 1.0 / np.cos(phi), np.tan(phi)


@dataclass
class OrbitParams:
    """One sample's orbit: offsets AY/AZ/AX (µm), amplitude P (µm), small terms DY/DZ."""
    AY: float
    AZ: float
    AX: float
    P: float
    DY: float = 0.0
    DZ: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def predict(params: OrbitParams, angles, GY: float, scale: float = DEFAULT_SCALE):
    """Predicted ``(CoarseY, SampleX, ZonePlateZ)`` arrays at *angles* for one sample."""
    angles = np.asarray(angles, float)
    sec, tan = basis(angles, scale)
    p = params
    Y = p.AY + GY * p.P * sec + p.DY * tan
    Z = p.AZ - p.P * tan + p.DZ * sec
    X = p.AX * np.ones_like(angles)
    return Y, X, Z


# ----------------------------------------------------------------------
# global fit: shared GY, per-sample {AY, AZ, AX, P, DY, DZ}
# ----------------------------------------------------------------------

def fit_global(samples: dict, scale: float = DEFAULT_SCALE, gy0: float = DEFAULT_GY):
    """Fit GY jointly across past orbits.  Returns ``(GY, {sample: OrbitParams})``.

    *samples* maps a sample key to a mapping of equal-length arrays ``angle``,
    ``coarse_y``, ``sample_x`` and ``zone_plate_z`` — the orbit database's columns.
    """
    keys = sorted(samples)
    if not keys:
        raise ValueError("fit_global needs at least one sample")
    data = {k: {c: np.asarray(samples[k][c], float)
                for c in ("angle", "coarse_y", "sample_x", "zone_plate_z")} for k in keys}

    # Linear per-sample fits give the starting point for the joint solve.
    p0, start = [gy0], {}
    for k in keys:
        d = data[k]
        sec, tan = basis(d["angle"], scale)
        cy, *_ = np.linalg.lstsq(np.column_stack([np.ones_like(sec), sec, tan]),
                                 d["coarse_y"], rcond=None)
        cz, *_ = np.linalg.lstsq(np.column_stack([np.ones_like(sec), tan, sec]),
                                 d["zone_plate_z"], rcond=None)
        start[k] = len(p0)
        p0 += [cy[0], cz[0], d["sample_x"].mean(), max(-cz[1], 1.0), cy[2], cz[2]]

    def resid(p):
        GY = p[0]
        out = []
        for k in keys:
            AY, AZ, AX, P, DY, DZ = p[start[k]:start[k] + 6]
            d = data[k]
            sec, tan = basis(d["angle"], scale)
            out.append(d["coarse_y"] - (AY + GY * P * sec + DY * tan))
            out.append(d["zone_plate_z"] - (AZ - P * tan + DZ * sec))
            out.append(d["sample_x"] - AX)
        return np.concatenate(out)

    sol = least_squares(resid, np.array(p0), method="lm", max_nfev=20000)
    GY = float(sol.x[0])
    params = {k: OrbitParams(*map(float, sol.x[start[k]:start[k] + 6])) for k in keys}
    return GY, params


# ----------------------------------------------------------------------
# per-sample fit from anchors, GY held fixed
# ----------------------------------------------------------------------

@dataclass
class OrbitFit:
    """A sample's fitted orbit plus what is needed to say how far to trust it."""
    params: OrbitParams
    GY: float
    scale: float
    use_small_terms: bool
    n_anchors: int
    rms_y: float
    rms_z: float
    rms_x: float
    # Parameter covariance (AY, AZ, AX, P[, DY, DZ]); None when too few anchors to say.
    cov: np.ndarray | None = None

    def predict(self, angles):
        """``(CoarseY, SampleX, ZonePlateZ)`` at *angles*."""
        return predict(self.params, angles, self.GY, self.scale)

    def predict_sigma(self, angles):
        """1-sigma prediction uncertainty ``(sigma_y, sigma_z)`` in µm at *angles*.

        From the fit covariance, so it grows away from the anchors — the signal for where
        the next anchor is worth taking.  NaN when there are too few anchors to estimate.
        """
        angles = np.asarray(angles, float)
        if self.cov is None:
            nan = np.full_like(angles, np.nan)
            return nan, nan.copy()
        jy, jz = _design_rows(angles, self.GY, self.scale, self.use_small_terms)
        sy = np.sqrt(np.einsum("ij,jk,ik->i", jy, self.cov, jy))
        sz = np.sqrt(np.einsum("ij,jk,ik->i", jz, self.cov, jz))
        return sy, sz

    def summary(self) -> dict:
        return {"params": self.params.as_dict(), "GY": self.GY, "scale": self.scale,
                "use_small_terms": self.use_small_terms, "n_anchors": self.n_anchors,
                "rms_um": {"coarse_y": self.rms_y, "zone_plate_z": self.rms_z,
                           "sample_x": self.rms_x}}


def _design_rows(angles, GY, scale, use_small_terms):
    """Y and Z rows of the linear model; columns AY, AZ, AX, P[, DY, DZ]."""
    sec, tan = basis(angles, scale)
    one, zero = np.ones_like(sec), np.zeros_like(sec)
    y_cols = [one, zero, zero, GY * sec]
    z_cols = [zero, one, zero, -tan]
    if use_small_terms:
        y_cols += [tan, zero]
        z_cols += [zero, sec]
    return np.column_stack(y_cols), np.column_stack(z_cols)


def auto_small_terms(angles) -> bool:
    """Whether the anchors span enough to separate DY/DZ from the offsets."""
    angles = np.asarray(angles, float)
    return (angles.size >= SMALL_TERMS_MIN_ANCHORS
            and float(np.ptp(angles)) >= SMALL_TERMS_MIN_SPAN_DEG)


def fit_from_anchors(angles, Y, X, Z, GY: float, use_small_terms: bool | None = None,
                     scale: float = DEFAULT_SCALE) -> OrbitFit:
    """Fit one sample's orbit from anchor measurements with GY fixed.

    Y and Z are fit jointly with a shared P.  *use_small_terms* also recovers DY/DZ;
    None decides from the anchors (:func:`auto_small_terms`).
    """
    angles, Y, X, Z = (np.asarray(v, float) for v in (angles, Y, X, Z))
    n = angles.size
    if n < 2:
        raise ValueError("fit_from_anchors needs at least two anchors")
    if use_small_terms is None:
        use_small_terms = auto_small_terms(angles)

    ay, az = _design_rows(angles, GY, scale, use_small_terms)
    k = ay.shape[1]
    ax = np.zeros((n, k))
    ax[:, 2] = 1.0
    A = np.vstack([ay, az, ax])
    b = np.concatenate([Y, Z, X])
    c, *_ = np.linalg.lstsq(A, b, rcond=None)

    ry, rz, rx = Y - ay @ c, Z - az @ c, X - ax @ c
    params = OrbitParams(*map(float, c)) if use_small_terms else \
        OrbitParams(*map(float, c), DY=0.0, DZ=0.0)
    return OrbitFit(params=params, GY=float(GY), scale=scale,
                    use_small_terms=bool(use_small_terms), n_anchors=n,
                    rms_y=_rms(ry), rms_z=_rms(rz), rms_x=_rms(rx),
                    cov=_sandwich_cov(A, [(slice(0, n), ry, 3 if use_small_terms else 2),
                                          (slice(n, 2 * n), rz, 3 if use_small_terms else 2),
                                          (slice(2 * n, 3 * n), rx, 1)]))


def _rms(r) -> float:
    return float(np.sqrt(np.mean(np.square(r)))) if np.size(r) else 0.0


def _sandwich_cov(A, blocks):
    """Parameter covariance with a separate noise level per motor.

    The fit itself is unweighted (as it always was), but CoarseY, ZonePlateZ and
    SampleX scatter by very different amounts, so each block gets its own residual
    variance: cov = (AᵀA)⁻¹ Aᵀ Σ A (AᵀA)⁻¹.  *blocks* is ``(rows, residuals, n_params
    touching that block)``.  None when any block has no residual degrees of freedom.
    """
    w = np.zeros(A.shape[0])
    for rows, r, k in blocks:
        dof = np.size(r) - k
        if dof <= 0:
            return None
        w[rows] = np.sum(np.square(r)) / dof
    try:
        inv = np.linalg.inv(A.T @ A)
    except np.linalg.LinAlgError:
        return None
    return inv @ (A.T * w) @ A @ inv

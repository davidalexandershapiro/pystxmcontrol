import numpy as np
from pathlib import Path
from scipy.ndimage import gaussian_filter

# ── Reference spectra ──────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent / "data"


def _load_spectrum(fname):
    d = np.loadtxt(_DATA_DIR / fname, delimiter=',')
    energies = d[:, 0]
    betas = np.maximum(d[:, 1], 0.0) + 0.1   # clamp negatives, then add pre-edge offset
    return energies, betas


_E_A, _BETA_A = _load_spectrum("material_A.csv")
_E_B, _BETA_B = _load_spectrum("material_B.csv")

# ── Particle world (generated once at import) ───────────────────────────────

_WORLD_SIZE_UM = 500.0          # ±250 µm in x and y
_PARTICLE_RADIUS_UM = 0.25      # 0.5 µm diameter
_PARTICLE_DENSITY = 0.2         # particles per µm²  (~1 per 5 µm²)

_N_PARTICLES = int(_WORLD_SIZE_UM ** 2 * _PARTICLE_DENSITY)   # ~50 000

_rng = np.random.default_rng(42)
_PX = _rng.uniform(-_WORLD_SIZE_UM / 2, _WORLD_SIZE_UM / 2, _N_PARTICLES)
_PY = _rng.uniform(-_WORLD_SIZE_UM / 2, _WORLD_SIZE_UM / 2, _N_PARTICLES)
_PMATERIAL = np.arange(_N_PARTICLES) % 3   # 0 = no-iron,  1 = material A,  2 = material B

# Pre-edge beta (first energy point after clamping + offset): used for the no-iron
# particles so they have constant absorption across the full energy range.
_BETA_PRE = float(_BETA_A[0])   # = 0.1 (the pre-edge floor added in _load_spectrum)

# OD scale: at peak beta, a full-diameter chord yields OD = 1.5 (~22% transmission).
# This gives good visible contrast regardless of the absolute magnitude of the CSV values.
_PEAK_BETA = max(float(_BETA_A.max()), float(_BETA_B.max()))
_OD_PEAK_TARGET = 1.5
_OD_SCALE = (_OD_PEAK_TARGET / (_PEAK_BETA * 2.0 * _PARTICLE_RADIUS_UM)
             if _PEAK_BETA > 0 else 1.0)

# ── Geometry cache (spatial only — reused across energies) ──────────────────

_geom_key = None
_chord_A_img = None   # scaled chord-length sum for A-material particles
_chord_B_img = None   # scaled chord-length sum for B-material particles
_chord_C_img = None   # scaled chord-length sum for no-iron particles

# ── Transmission-image cache (spatial + energy) ─────────────────────────────

_img_key = None
_img_cache = None


def _build_geometry(y_size, x_size, pixel_size_um, y_center_um, x_center_um):
    """Return (chord_A, chord_B, chord_C) images [shape (y_size, x_size)].

    Each image contains the sum of scaled sphere-chord-length profiles for all
    particles of that material that overlap the FOV.  Multiply by beta(E) to
    get the per-energy optical depth contributed by that material.

    Material assignments (by particle index % 3):
      0 = no-iron  (chord_C) — constant pre-edge absorption, no resonance
      1 = material A (chord_A)
      2 = material B (chord_B)
    """
    global _geom_key, _chord_A_img, _chord_B_img, _chord_C_img

    key = (y_size, x_size, round(pixel_size_um, 8),
           round(y_center_um, 6), round(x_center_um, 6))
    if _geom_key == key:
        return _chord_A_img, _chord_B_img, _chord_C_img

    # Pixel coordinate grid in absolute sample µm
    y_idx, x_idx = np.indices((y_size, x_size), dtype=float)
    x_abs = (x_idx - (x_size - 1) / 2.0) * pixel_size_um + x_center_um
    y_abs = (y_idx - (y_size - 1) / 2.0) * pixel_size_um + y_center_um

    # Particle selection: keep only those whose circles overlap the FOV
    margin = _PARTICLE_RADIUS_UM + pixel_size_um
    x_min = x_abs[0, 0]  - margin
    x_max = x_abs[0, -1] + margin
    y_min = y_abs[0, 0]  - margin
    y_max = y_abs[-1, 0] + margin
    sel = (_PX >= x_min) & (_PX <= x_max) & (_PY >= y_min) & (_PY <= y_max)
    px = _PX[sel]
    py = _PY[sel]
    pm = _PMATERIAL[sel]

    chord_A = np.zeros((y_size, x_size), dtype=float)
    chord_B = np.zeros((y_size, x_size), dtype=float)
    chord_C = np.zeros((y_size, x_size), dtype=float)
    R2 = _PARTICLE_RADIUS_UM ** 2

    for i in range(len(px)):
        dx = x_abs - px[i]
        dy = y_abs - py[i]
        r2 = dx * dx + dy * dy
        inside = r2 < R2
        if not inside.any():
            continue
        # Sphere cross-section: chord = 2 * sqrt(R² - r²)
        chord = np.where(inside, 2.0 * np.sqrt(np.maximum(R2 - r2, 0.0)), 0.0)
        if pm[i] == 0:
            chord_C += chord
        elif pm[i] == 1:
            chord_A += chord
        else:
            chord_B += chord

    # Absorb _OD_SCALE into the cached arrays so the per-energy step is just a multiply
    chord_A *= _OD_SCALE
    chord_B *= _OD_SCALE
    chord_C *= _OD_SCALE

    _geom_key = key
    _chord_A_img = chord_A
    _chord_B_img = chord_B
    _chord_C_img = chord_C
    return chord_A, chord_B, chord_C


def _compute_particle_image(y_size, x_size, pixel_size_um, energy_ev,
                             y_center_um, x_center_um, photon_flux, dwell_ms):
    """Transmission image with Poisson noise for the particle sample."""
    global _img_key, _img_cache

    img_key = (y_size, x_size, round(pixel_size_um, 8), round(energy_ev, 3),
               round(y_center_um, 6), round(x_center_um, 6),
               round(photon_flux, 0), round(dwell_ms, 4))
    if _img_key == img_key:
        return _img_cache

    chord_A, chord_B, chord_C = _build_geometry(y_size, x_size, pixel_size_um,
                                                y_center_um, x_center_um)

    beta_a = float(np.interp(energy_ev, _E_A, _BETA_A))
    beta_b = float(np.interp(energy_ev, _E_B, _BETA_B))

    # No-iron particles use a constant pre-edge beta at all energies — they absorb
    # uniformly across the iron edge with no resonant feature.
    optical_depth = beta_a * chord_A + beta_b * chord_B + _BETA_PRE * chord_C
    transmission = np.exp(-optical_depth)

    mean_counts = np.maximum(transmission * photon_flux * dwell_ms / 1000.0, 0.0)
    image = np.random.poisson(mean_counts).astype(float)

    _img_key = img_key
    _img_cache = image
    return image


# ── Public API ──────────────────────────────────────────────────────────────

def test_sample(row_index, column_index, y_size, x_size, pixel_size, dwell,
                y_center=None, x_center=None, full_line=True, full_image=False,
                sample_type='star', energy=700.0):
    """Return simulated detector signal for one pixel, one line, or the full image.

    Parameters
    ----------
    row_index, column_index : int
        Current scan position (used when full_line=False or full_image=False).
    y_size, x_size : int
        Image dimensions in pixels.
    pixel_size : float
        Pixel size in µm (assumed square).
    dwell : float
        Dwell time in ms.
    y_center, x_center : float, optional
        Absolute sample coordinates of the scan centre in µm.
    full_line : bool
        Return the entire current row (default True).
    full_image : bool
        Return the full 2-D image.
    sample_type : str
        'star'      – original angular-stripe pattern (default).
        'particles' – two-material particle field with energy-dependent contrast.
    energy : float
        Photon energy in eV (only used for sample_type='particles').
    """
    photon_flux = 1e6

    if x_center is None:
        x_center = x_size // 2 * pixel_size
    if y_center is None:
        y_center = y_size // 2 * pixel_size

    if sample_type == 'particles':
        pattern = _compute_particle_image(y_size, x_size, pixel_size, energy,
                                          y_center, x_center, photon_flux, dwell)
    else:
        # Original star (angular-stripe) pattern
        resolution = 0.05
        frequency = 10.0
        y, x = np.indices((y_size, x_size)).astype('float') * pixel_size
        y -= -y_center + y_size // 2 * pixel_size
        x -= -x_center + x_size // 2 * pixel_size
        angles = np.arctan(y / x)
        pattern = (gaussian_filter((np.cos(frequency * angles) > 0).astype('float'),
                                   sigma=resolution / pixel_size)
                   * photon_flux * dwell / 1000.0)
        pattern = np.random.poisson(pattern)

    if full_image:
        return pattern
    elif full_line:
        return pattern[row_index]
    else:
        return pattern[row_index, column_index]

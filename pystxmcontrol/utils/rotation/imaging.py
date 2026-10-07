"""Image processing for tracking a sample through a tilt series.

Ported from the beamline's ``cosmic_rotation`` scripts.  Everything works on plain 2-D
numpy arrays — the caller gets counts from the server (``get_scan_data``) — so there is
no file reader here and no pystxm_core dependency.

Shift convention throughout: a positive ``(dy, dx)`` means the feature sits at larger
row/column index than the reference (or the image centre), in µm when pixel sizes are
given.  Cross-correlation shifts are *reference minus moving*: the moving image's
feature lies at ``-shift`` relative to the reference.
"""

import numpy as np
from scipy import ndimage
from scipy.optimize import curve_fit
from scipy.signal import fftconvolve, find_peaks, medfilt2d, peak_prominences


# ----------------------------------------------------------------------
# counts -> image
# ----------------------------------------------------------------------

def first_frame(counts) -> np.ndarray:
    """A 2-D float image from a scan's counts: ``(energy, y, x)`` takes the first frame."""
    a = np.asarray(counts, dtype=float)
    while a.ndim > 2:
        a = a[0]
    if a.ndim != 2:
        raise ValueError(f"expected a 2-D image, got shape {np.shape(counts)}")
    return a


def despike(image, threshold: float = 7.0, kernel_size: int = 3) -> np.ndarray:
    """Replace pixels more than *threshold* σ from a median-filtered copy with the median."""
    if kernel_size % 2 == 0:
        kernel_size += 1
    image = np.asarray(image, float)
    filtered = medfilt2d(image, kernel_size=kernel_size)
    diff = np.abs(filtered - image)
    spikes = diff > threshold * diff.std()
    out = image.copy()
    out[spikes] = filtered[spikes]
    return out


def i0_mask(image, nbins: int = 10) -> np.ndarray:
    """Pixels in the brightest histogram bin — the unattenuated beam around the sample."""
    _, edges = np.histogram(image, bins=nbins)
    return image > edges[-2]


def od_image(counts, smooth_sigma: float = 1.0) -> np.ndarray:
    """Optical density ``-log(I/I0)`` of the first frame, despiked and lightly smoothed.

    I0 is the mean of the brightest-bin pixels.  Zero-count pixels (a spiral scan's
    unvisited corners) come out as 0 OD rather than inf.
    """
    image = first_frame(counts)
    mask = i0_mask(image)
    i0 = image[mask].mean() if mask.any() else image.max()
    with np.errstate(divide="ignore", invalid="ignore"):
        od = -np.log(image / i0)
    od[~np.isfinite(od)] = 0.0
    od = despike(od)
    return ndimage.gaussian_filter(od, sigma=smooth_sigma) if smooth_sigma else od


def amplitude_image(counts) -> np.ndarray:
    """The raw transmitted counts of the first frame (for aligning to a bright fiducial)."""
    return first_frame(counts)


def crop_spiral_image(image, pad: int = 5) -> np.ndarray:
    """The largest square inside a square spiral image's circular footprint.

    The corners of a spiral scan are never visited and read zero, which a
    cross-correlation would lock onto.
    """
    image = np.asarray(image)
    h, w = image.shape
    if h != w:
        raise ValueError(f"spiral image expected to be square, got {image.shape}")
    half = int((h // 2 - pad) * np.cos(np.radians(45)))
    c = h // 2
    return image[c - half:c + half, c - half:c + half]


# ----------------------------------------------------------------------
# cross-correlation
# ----------------------------------------------------------------------

def _normalized_cc(ref, mov):
    """Full linear cross-correlation of mean-subtracted images, normalised to [-1, 1].

    Identical to ``scipy.signal.correlate2d(ref, mov, 'full')`` divided by the norms, but
    by FFT: the direct form is O(N⁴) and took seconds per 100×100 image.
    """
    ref = np.asarray(ref, float) - np.mean(ref)
    mov = np.asarray(mov, float) - np.mean(mov)
    norm = np.sqrt(np.sum(ref ** 2) * np.sum(mov ** 2))
    if norm == 0:
        return None
    return fftconvolve(ref, mov[::-1, ::-1], mode="full") / norm


def cc_confidence(ref, mov) -> float:
    """Peak normalised cross-correlation: 1 is identical, ~0 is unrelated, 0 if blank."""
    cc = _normalized_cc(ref, mov)
    return 0.0 if cc is None else float(cc.max())


def cc_shift(ref, mov, xstep: float = 1.0, ystep: float = 1.0):
    """Shift between two images by cross-correlation with sub-pixel parabolic refinement.

    Returns ``(dy, dx, confidence)``: the shift in µm (pixels when steps are 1) and the
    peak normalised correlation.  The original script returned the peak's flat *index*
    as the confidence, so its "can't find the sample" check never fired.
    """
    cc = _normalized_cc(ref, mov)
    if cc is None:
        return 0.0, 0.0, 0.0
    py, px = np.unravel_index(np.argmax(cc), cc.shape)
    centre = (np.array(cc.shape) - 1) / 2.0
    dy, dx = py - centre[0], px - centre[1]
    if 1 <= py <= cc.shape[0] - 2:
        dy += _parabolic(cc[py - 1, px], cc[py, px], cc[py + 1, px])
    if 1 <= px <= cc.shape[1] - 2:
        dx += _parabolic(cc[py, px - 1], cc[py, px], cc[py, px + 1])
    return float(dy * ystep), float(dx * xstep), float(cc[py, px])


def _parabolic(m, c, p) -> float:
    denom = m - 2 * c + p
    return 0.0 if denom == 0 else -0.5 * (p - m) / denom


# ----------------------------------------------------------------------
# masking and centring
# ----------------------------------------------------------------------

def threshold_from_gaussian(image, sigma_thresh: float = 5.0):
    """Mask threshold ``mu + sigma_thresh*sigma`` from a Gaussian fit to the background.

    The background is the histogram's most prominent peak.  Returns
    ``(threshold, mu, sigma)``; raises ValueError when no peak or fit is found.
    """
    hist, edges = np.histogram(np.ravel(image), density=True, bins=100)
    x = (edges[:-1] + edges[1:]) / 2
    smooth = ndimage.gaussian_filter1d(hist, sigma=1)
    peaks, _ = find_peaks(smooth)
    if len(peaks) == 0:
        raise ValueError("no peak in the image histogram to fit a background to")
    peak = peaks[np.argmax(peak_prominences(smooth, peaks)[0])]

    def gaussian(v, amp, mu, sigma, bkg):
        return amp * np.exp(-0.5 * ((v - mu) / sigma) ** 2) + bkg

    try:
        popt, _ = curve_fit(gaussian, x, smooth,
                            p0=[hist[peak], x[peak], (x[-1] - x[0]) / 10, 0.0], maxfev=5000)
    except Exception as e:
        raise ValueError(f"Gaussian fit to the image histogram failed: {e}") from e
    mu, sigma = float(popt[1]), float(abs(popt[2]))
    return mu + sigma_thresh * sigma, mu, sigma


def center_mask(image, threshold: float, open_kernel: int | None = 3,
                close_kernel: int | None = 3) -> np.ndarray:
    """Binary sample mask: pixels above the absolute *threshold*, opened then closed."""
    mask = np.asarray(image) > threshold
    if open_kernel:
        mask = ndimage.binary_opening(mask, structure=np.ones((open_kernel, open_kernel)))
    if close_kernel:
        mask = ndimage.binary_closing(mask, structure=np.ones((close_kernel, close_kernel)))
    return mask


def bounding_box_shift(mask, xstep: float = 1.0, ystep: float = 1.0):
    """``(dy, dx)`` of the mask's bounding-box centre from the image centre.

    Raises ValueError for an empty mask — there is nothing to centre on.
    """
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        raise ValueError("sample mask is empty: nothing above the threshold")
    h, w = np.shape(mask)
    dy = (ys.min() + ys.max()) / 2.0 - (h - 1) / 2.0
    dx = (xs.min() + xs.max()) / 2.0 - (w - 1) / 2.0
    return float(dy * ystep), float(dx * xstep)


def centroid_shift(image, xstep: float = 1.0, ystep: float = 1.0):
    """``(dy, dx)`` of the intensity-weighted centroid from the image centre."""
    image = np.asarray(image, float)
    total = image.sum()
    if total == 0:
        raise ValueError("image has no intensity to take a centroid of")
    yi, xi = np.indices(image.shape)
    h, w = image.shape
    dy = (yi * image).sum() / total - (h - 1) / 2.0
    dx = (xi * image).sum() / total - (w - 1) / 2.0
    return float(dy * ystep), float(dx * xstep)

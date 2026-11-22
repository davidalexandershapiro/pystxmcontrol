"""Reading a multi-page TIFF plus its sidecar energy list as an image stack.

A common interchange format for spectromicroscopy — MANTiS writes exactly this on
export — where the frames are the pages of one TIFF and the photon energies are a text
file of the same name, one per line:

    240605043_rawframes.tif    49 pages, 299 x 353
    240605043_rawframes.txt    49 energies in eV

Neither file carries a pixel size.  One is read from the TIFF's resolution tags when
they are actually set (ImageJ writes them; the MANTiS export does not) and otherwise
reported as unknown rather than guessed, so a figure never gets a scale bar that is
quietly wrong.

Qt-free and headless, so a script can read one of these without the GUI: the analysis
``stack`` class uses it in :meth:`stack.openTIFF`.
"""

import os
import re

import numpy as np


TIFF_SUFFIXES = (".tif", ".tiff")

# Sidecar extensions tried in order, before falling back to '<base>_energies.txt'.
_SIDECAR_SUFFIXES = (".txt", ".dat", ".csv")

# A photon energy in eV. Used only to pick the energy column out of a multi-column
# sidecar, so it is deliberately loose — soft X-ray work sits at 100-2000 eV.
_EV_MIN, _EV_MAX = 1.0, 1e5

# A plausible pixel size in µm, for sanity-checking what the resolution tags claim.
_PIXEL_UM_MIN, _PIXEL_UM_MAX = 1e-4, 1e3


class TiffStack:
    """One loaded TIFF stack: the frames, their energies, and where they came from.

    ``pixel_size_um`` is None when the file does not record one — the common case for
    this format, and the caller has to decide what to do about it.
    """

    def __init__(self, frames, energies, pixel_size_um, path, energy_file):
        self.frames = frames                  # (n_energies, ny, nx) float array
        self.energies = energies              # (n_energies,) float array, eV
        self.pixel_size_um = pixel_size_um    # float µm/px, or None if unrecorded
        self.path = path
        self.energy_file = energy_file

    def __repr__(self):
        n, ny, nx = self.frames.shape
        pixel = "unknown" if self.pixel_size_um is None else f"{self.pixel_size_um:g} µm"
        return (f"<TiffStack {os.path.basename(self.path)}: {n} frames, {ny}x{nx} px, "
                f"{self.energies[0]:.2f}-{self.energies[-1]:.2f} eV, pixel {pixel}>")


def is_tiff_stack(path: str) -> bool:
    """Whether *path* names a TIFF this module can load."""
    return str(path).lower().endswith(TIFF_SUFFIXES)


def find_energy_file(tiff_path: str) -> str | None:
    """The energy list beside *tiff_path*, or None if there is none.

    The contract is a text file of the same name, so '<base>.txt' is tried first; '.dat'
    and '.csv' follow because the same export is sometimes saved under those, and
    '<base>_energies.txt' last.
    """
    base = os.path.splitext(tiff_path)[0]
    candidates = [base + suffix for suffix in _SIDECAR_SUFFIXES]
    candidates += [base + suffix.upper() for suffix in _SIDECAR_SUFFIXES]
    candidates.append(base + "_energies.txt")
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def read_energies(path: str) -> np.ndarray:
    """Read the photon energies from a sidecar text file.

    One energy per line is the expected form.  Blank lines, '#'/';' comments and a
    non-numeric header line are skipped; a wrapped list (several per line) is read as
    one sequence.  A table of several columns keeps the one column that reads as
    energies — monotonic and within a plausible eV range — because picking the wrong
    column would mislabel every frame rather than fail.

    :raises ValueError: when the file holds no numbers, or no column reads as energies.
    """
    rows = []
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = re.split(r"[#;]", line, maxsplit=1)[0].strip()
            if not line:
                continue
            values = []
            for field in re.split(r"[,\s]+", line):
                try:
                    values.append(float(field))
                except ValueError:
                    values = []           # a header or units line — skip the whole row
                    break
            if values:
                rows.append(values)

    name = os.path.basename(path)
    if not rows:
        return _fail(f"{name} contains no numbers — it should hold one energy per line")

    widths = {len(row) for row in rows}
    if widths == {1} or len(widths) > 1:
        # One per line, or a wrapped list: the file is one sequence either way.
        return np.array([value for row in rows for value in row], dtype=float)

    table = np.array(rows, dtype=float)
    energy_columns = [i for i in range(table.shape[1]) if _reads_as_energies(table[:, i])]
    if len(energy_columns) != 1:
        return _fail(f"{name} has {table.shape[1]} columns and none of them reads "
                     "unambiguously as energies — give one energy per line")
    return table[:, energy_columns[0]]


def read_tiff_stack(path: str, energy_file: str | None = None) -> TiffStack:
    """Read a multi-page TIFF and its energy sidecar into a :class:`TiffStack`.

    :param path: the multi-page TIFF.
    :param energy_file: the energy list; found beside the TIFF when omitted.
    :raises ValueError: when the TIFF is not a 2-D image stack, the sidecar is missing,
        or it holds a different number of energies than the TIFF has pages.
    """
    import tifffile

    if not os.path.isfile(path):
        return _fail(f"no file at '{path}'")

    energy_file = energy_file or find_energy_file(path)
    if energy_file is None:
        base = os.path.basename(os.path.splitext(path)[0])
        return _fail(f"no energy list beside {os.path.basename(path)} — this format needs "
                     f"a text file of the same name ('{base}.txt') holding one photon "
                     "energy per line")
    energies = read_energies(energy_file)

    with tifffile.TiffFile(path) as tif:
        frames = tif.asarray()
        axes = tif.series[0].axes      # 'QYX'/'IYX' for pages, 'YXS' for colour samples
        pixel_size_um = _pixel_size_um(tif)

    # A colour image is three samples of ONE picture, not three frames: its array is
    # 3-D like a page stack, so the shape alone would let it through as a stack whose
    # "energies" are rows.
    if "S" in axes:
        return _fail(f"{os.path.basename(path)} is a colour image (axes {axes}) — "
                     "expected greyscale pages, one per energy")

    frames = np.asarray(frames)
    if frames.ndim == 2:                      # a single-page TIFF is a one-frame stack
        frames = frames[np.newaxis]
    if frames.ndim != 3:
        return _fail(f"{os.path.basename(path)} is {frames.ndim}-dimensional "
                     f"{frames.shape} — expected greyscale pages, one per energy")

    if len(energies) != len(frames):
        return _fail(f"{os.path.basename(energy_file)} holds {len(energies)} energies but "
                     f"{os.path.basename(path)} has {len(frames)} pages — they must match")

    return TiffStack(frames=frames.astype(float), energies=energies.astype(float),
                     pixel_size_um=pixel_size_um, path=path, energy_file=energy_file)


def _reads_as_energies(column: np.ndarray) -> bool:
    """Whether a sidecar column could be the energy axis: monotonic and in eV range."""
    if column.size < 2 or not np.all(np.isfinite(column)):
        return False
    if not (np.all(np.diff(column) > 0) or np.all(np.diff(column) < 0)):
        return False
    return bool(np.all((column > _EV_MIN) & (column < _EV_MAX)))


def _pixel_size_um(tif) -> float | None:
    """Pixel size in µm from the TIFF's resolution tags, or None if it records none.

    ImageJ-style files carry the unit in their metadata and the resolution as pixels per
    unit; a plain TIFF gives pixels per inch or per centimetre.  A file with no unit
    (ResolutionUnit NONE and no ImageJ block, which is what the MANTiS export writes)
    says nothing about scale, and a resolution of 1 with no unit is Qt's way of saying
    "unset" rather than one pixel per inch.
    """
    try:
        page = tif.pages[0]
        resolution = page.tags["XResolution"].value
        unit = int(page.tags["ResolutionUnit"].value)
    except (KeyError, AttributeError, IndexError, TypeError, ValueError):
        return None

    try:
        numerator, denominator = resolution
        per_unit = float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if per_unit <= 0:
        return None

    if unit == 2:                                    # RESUNIT.INCH
        pixel_um = 25400.0 / per_unit
    elif unit == 3:                                  # RESUNIT.CENTIMETER
        pixel_um = 10000.0 / per_unit
    else:                                            # RESUNIT.NONE — ImageJ or nothing
        scale = _imagej_unit_um(getattr(tif, "imagej_metadata", None))
        if scale is None:
            return None
        pixel_um = scale / per_unit

    return pixel_um if _PIXEL_UM_MIN < pixel_um < _PIXEL_UM_MAX else None


def _imagej_unit_um(metadata) -> float | None:
    """µm per ImageJ length unit, or None when the unit is missing or not a length."""
    if not isinstance(metadata, dict):
        return None
    unit = str(metadata.get("unit", "")).strip().lower()
    return {"um": 1.0, "µm": 1.0, "micron": 1.0, "microns": 1.0,
            "nm": 1e-3, "mm": 1e3, "cm": 1e4, "m": 1e6}.get(unit)


def _fail(message: str):
    raise ValueError(message)

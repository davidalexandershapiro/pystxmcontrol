"""What the stack-open dialog offers, and how a stack without an NXstxm header
describes itself.

Both analysis panels read their metadata out of ``stack.nx``, which only a .stxm file
has.  A stack loaded from an HDR, a CXI or a multi-page TIFF carries no such header,
and the panels showed nothing at all for one — but it still knows its shape, its energy
axis and where its energies came from, which is most of what the operator is checking.
"""

import os


# Offered by the Open Stack dialog.  The combined entry is first so the common case —
# "show me the stacks in this directory" — needs no choosing.
STACK_FILE_FILTER = (
    "Stacks (*.stxm *.hdr *.cxi *.tif *.tiff);;"
    "NXstxm (*.stxm);;"
    "Header + XIM (*.hdr);;"
    "CXI (*.cxi);;"
    "TIFF + energy list (*.tif *.tiff);;"
    "All files (*)"
)


def describe_stack(st) -> list[str]:
    """Display lines for a stack with no NXstxm metadata, in the panels' label style.

    The caller adds the file name — both panels already print one — so this covers what
    is specific to the data: where the energies came from, the shape, the field of view,
    and the energy range.  A pixel size the file never recorded is reported as missing
    rather than printed from the placeholder the stack loaded with.
    """
    lines = []
    energy_file = getattr(st, "energyFile", None)
    if energy_file:
        lines.append(f"Energies from: {os.path.basename(energy_file)}")

    frames = getattr(st, "processedFrames", None)
    if frames is not None and getattr(frames, "ndim", 0) == 3:
        ne, ny, nx = frames.shape
        lines.append(f"Image size:    {nx} × {ny} px")
        dx = getattr(st, "xpixelsize", None)
        if dx and getattr(st, "pixelSizeKnown", True):
            dy = getattr(st, "ypixelsize", None) or dx
            lines.append(f"X range:       {nx * dx:.3f} µm  ({nx} pts, {dx:.4f} µm/pt)")
            lines.append(f"Y range:       {ny * dy:.3f} µm  ({ny} pts, {dy:.4f} µm/pt)")
        else:
            lines.append("Pixel size:    not recorded in the file (no scale bar)")

    energies = getattr(st, "energies", None)
    if energies is not None and len(energies):
        lines.append(f"Energies:      {len(energies)}  "
                     f"({energies[0]:.2f} – {energies[-1]:.2f} eV)")
    return lines

#!/usr/bin/env python3
"""
Diagnostic for automatic focus determination on a REAL focus .stxm file.

A focus-scan image is ROWS = ZonePlateZ, COLS = position along the scanned line. The
feature (OSA edge / blob) is sharp at focus and blurry off focus. This script:

  * loads the focus scan and the per-row ZonePlateZ values,
  * computes several per-row "crispness" metrics (Tenengrad, Brenner, normalized
    variance, max|grad|) so we can see which best peaks at focus on real data,
  * picks a robust focus row from one metric: smooth the crispness-vs-Z curve, take the
    argmax with parabolic sub-row refinement, and gate on bilateral falloff / interior position,
  * reports the focus ZonePlateZ, a confidence, and whether the focus is in range,
  * saves a figure (focus image + crispness curves with the picked focus marked).

This is the tuning ground before the metric is wired into analyze_focus_scan / the
intelligence module. Nothing here imports instrument state — just the file reader.

Usage:
    python scripts/test_focus_scan.py /path/to/FOCUS.stxm
    python scripts/test_focus_scan.py FILE --metric tenengrad --smooth 1.5
    python scripts/test_focus_scan.py FILE --z-motor zoneplatez   # force the Z motor key
    python scripts/test_focus_scan.py FILE --transpose            # if rows are the line, not Z
    python scripts/test_focus_scan.py FILE --show
"""

import argparse
import os
import sys

import numpy as np

import matplotlib
if "--show" not in sys.argv:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter1d

from pystxmcontrol.utils.writeNX import stxm


# --------------------------------------------------------------------------- #
# Crispness metrics (per row = per ZonePlateZ). Each returns a 1-D array over rows.
# Operate along axis=1 (the scanned line). A sharper edge → larger value.
# --------------------------------------------------------------------------- #
def crispness_metrics(img, line_smooth=1.0):
    a = img.astype(float)
    sm = gaussian_filter1d(a, line_smooth, axis=1) if line_smooth > 0 else a
    grad = np.gradient(sm, axis=1)
    tenengrad = np.sum(grad ** 2, axis=1)                 # Σ(∇I)²  — gradient energy
    maxgrad = np.max(np.abs(grad), axis=1)                # steepest edge
    d2 = a[:, 2:] - a[:, :-2]
    brenner = np.sum(d2 ** 2, axis=1)                     # Brenner gradient
    mean = a.mean(axis=1)
    normvar = a.var(axis=1) / (mean ** 2 + 1e-12)         # normalized variance
    return {"tenengrad": tenengrad, "brenner": brenner,
            "normvar": normvar, "maxgrad": maxgrad}


def pick_focus(curve, zvals, smooth_rows=1.0, edge_margin=1, falloff_frac=0.35):
    """Robust focus pick from a crispness-vs-row curve.

    Returns dict with sub-row peak index, focus Z, confidence, in_range flag, and the
    smoothed curve. The true focus rises to a peak and FALLS OFF on both sides; an
    out-of-range focus has its max pinned near a boundary with the curve still trending up
    to that edge. in_range therefore requires an interior peak that descends by at least
    ``falloff_frac`` of its dynamic range on each side, and ``confidence`` (0-1) is the
    smaller of the two side-falloffs (mirrors intelligence.analyze_focus).
    """
    n = curve.size
    cs = gaussian_filter1d(curve, smooth_rows) if smooth_rows > 0 else curve.astype(float)
    i = int(np.argmax(cs))

    # Parabolic sub-row refinement around the discrete peak.
    di = 0.0
    if 0 < i < n - 1:
        a, b, c = cs[i - 1], cs[i], cs[i + 1]
        denom = (a - 2 * b + c)
        if denom != 0:
            di = 0.5 * (a - c) / denom
            di = float(np.clip(di, -1.0, 1.0))
    pos = i + di

    # Bilateral-falloff test for out-of-range focus, on a more heavily smoothed curve so
    # row-to-row noise can't fake a turnover. confidence = smaller side-falloff (0-1):
    # how cleanly the crispness turns over into a real peak on both sides.
    trend = gaussian_filter1d(curve, max(smooth_rows, n * 0.05))
    ti = int(np.argmax(trend))
    floor = float(trend.min())
    rise = float(trend[ti]) - floor
    if rise <= 1e-12:
        left_drop = right_drop = 0.0
    else:
        left_drop = (float(trend[ti]) - float(trend[: ti + 1].min())) / rise
        right_drop = (float(trend[ti]) - float(trend[ti:].min())) / rise
    falls_low = left_drop >= falloff_frac
    falls_high = right_drop >= falloff_frac
    confidence = min(left_drop, right_drop)

    margin = max(edge_margin, int(round(0.05 * n)))
    interior = (margin <= i <= n - 1 - margin)
    in_range = bool(interior and falls_low and falls_high)

    if in_range:
        edge_hint = None
    elif not falls_high:
        edge_hint = "high-Z end"
    elif not falls_low:
        edge_hint = "low-Z end"
    else:
        edge_hint = "low-Z end" if i <= n // 2 else "high-Z end"

    # Sub-row → Z (linear interp on the row→Z mapping; works for ascending or descending Z).
    focus_z = float(np.interp(pos, np.arange(n), zvals)) if n > 1 else float(zvals[0])

    return {"peak_row": pos, "peak_row_int": i, "focus_z": focus_z,
            "confidence": confidence, "in_range": in_range, "edge_hint": edge_hint,
            "smoothed": cs}


# --------------------------------------------------------------------------- #
# File loading
# --------------------------------------------------------------------------- #
def extract_focus_image(entry, daq, energy):
    counts = entry["counts"]
    if isinstance(counts, dict):
        daq_used = daq if daq in counts else ("default" if "default" in counts else next(iter(counts)))
        arr = np.asarray(counts[daq_used], dtype=float)
    else:
        daq_used = "(single)"
        arr = np.asarray(counts, dtype=float)
    arr = np.squeeze(arr)
    if arr.ndim == 3:
        arr = arr[min(energy, arr.shape[0] - 1)]
    if arr.ndim != 2:
        raise ValueError(f"Unexpected counts shape after squeeze: {arr.shape}")
    return arr, daq_used


def find_z_values(entry, nrows, z_motor=None):
    """Return (zvals[len=nrows], source_str). Tries the requested/auto Z motor, else row index."""
    motors = entry.get("motors", {}) or {}
    keys = list(motors.keys())
    cand = None
    if z_motor and z_motor in motors:
        cand = z_motor
    else:
        for k in keys:
            kl = k.lower().replace("_", "").replace(" ", "")
            if "zoneplate" in kl or kl in ("zpos", "z"):
                cand = k
                break
    if cand is not None:
        z = np.asarray(motors[cand], dtype=float)
        z = np.squeeze(z)
        if z.ndim == 2:                      # (rows, cols) → one value per row
            z = z.mean(axis=1)
        z = z.ravel()
        if z.size == nrows:
            return z, f"motors['{cand}']"
        # Sometimes stored per-point; subsample to rows if it divides evenly.
        if z.size % nrows == 0 and z.size > nrows:
            return z.reshape(nrows, -1).mean(axis=1), f"motors['{cand}'] (reshaped)"
    return np.arange(nrows, dtype=float), "ROW INDEX (no Z motor found — pass --z-motor)"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--daq", default="default")
    ap.add_argument("--region", type=int, default=0)
    ap.add_argument("--energy", type=int, default=0)
    ap.add_argument("--metric", default="tenengrad",
                    choices=["tenengrad", "brenner", "normvar", "maxgrad"],
                    help="metric used for the focus pick (default tenengrad)")
    ap.add_argument("--line-smooth", type=float, default=1.0, help="per-line smoothing sigma (px)")
    ap.add_argument("--smooth", type=float, default=1.0, help="crispness-vs-Z smoothing sigma (rows)")
    ap.add_argument("--z-motor", default=None, help="motor key holding ZonePlateZ (else auto)")
    ap.add_argument("--zstart", type=float, default=None,
                    help="ZonePlateZ at row 0 (the file usually does not store the scanned Z axis)")
    ap.add_argument("--zstop", type=float, default=None, help="ZonePlateZ at the last row")
    ap.add_argument("--transpose", action="store_true", help="swap axes if rows are the line, not Z")
    ap.add_argument("--out", default=None)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    f = stxm(stxm_file=args.file)
    entry = f.data[f"entry{args.region}"]
    img, daq_used = extract_focus_image(entry, args.daq, args.energy)
    if args.transpose:
        img = img.T
    nrows, ncols = img.shape  # rows = ZonePlateZ, cols = line position
    if args.zstart is not None and args.zstop is not None:
        zvals, zsrc = np.linspace(args.zstart, args.zstop, nrows), "CLI --zstart/--zstop"
    else:
        zvals, zsrc = find_z_values(entry, nrows, args.z_motor)

    print(f"file        : {args.file}")
    print(f"scan_type   : {f.meta.get('scan_type')}   region {args.region}   daq '{daq_used}'")
    print(f"image       : {nrows} rows (Z) x {ncols} cols (line)")
    print(f"motor keys  : {list((entry.get('motors') or {}).keys())}")
    print(f"Z source    : {zsrc}")
    print(f"Z range     : [{zvals.min():.3f}, {zvals.max():.3f}]  ({nrows} steps)")
    print()

    metrics = crispness_metrics(img, line_smooth=args.line_smooth)
    print("per-metric peak row (raw argmax) — they should roughly agree at the true focus:")
    for name, c in metrics.items():
        print(f"   {name:10s} argmax row = {int(np.argmax(c)):3d}  (Z={zvals[int(np.argmax(c))]:.3f})")
    print()

    res = pick_focus(metrics[args.metric], zvals, smooth_rows=args.smooth)
    print(f"PICK ({args.metric}):")
    print(f"   focus row   = {res['peak_row']:.2f}  (Z = {res['focus_z']:.3f})")
    print(f"   confidence  = {res['confidence']:.2f}   (0-1, bilateral falloff; ~0.5+ is a clear peak)")
    print(f"   in_range    = {res['in_range']}" + ("" if res["in_range"]
          else f"   → focus likely beyond the {res['edge_hint']}; rescan shifted that way"))

    # --- figure ---
    fig, ax = plt.subplots(1, 2, figsize=(13, 6))
    ax[0].imshow(img, origin="lower", aspect="auto", cmap="viridis",
                 extent=[0, ncols, zvals[0], zvals[-1]])
    ax[0].axhline(res["focus_z"], color="red", lw=1.5, label=f"focus Z={res['focus_z']:.2f}")
    ax[0].set_xlabel("line position (px)"); ax[0].set_ylabel("ZonePlateZ")
    ax[0].set_title(f"focus scan ({nrows}×{ncols})"); ax[0].legend(loc="upper right", fontsize=8)

    for name, c in metrics.items():
        cn = (c - c.min()) / (np.ptp(c) + 1e-12)
        ax[1].plot(cn, zvals, label=name, alpha=0.6 if name != args.metric else 1.0,
                   lw=2 if name == args.metric else 1)
    ax[1].axhline(res["focus_z"], color="red", lw=1.5)
    ax[1].set_xlabel("crispness (normalized)"); ax[1].set_ylabel("ZonePlateZ")
    ax[1].set_title("crispness vs Z"); ax[1].legend(fontsize=8)

    out = args.out or os.path.splitext(args.file)[0] + "_focus.png"
    fig.tight_layout(); fig.savefig(out, dpi=120)
    print(f"\nsaved figure: {out}")
    if args.show:
        plt.show()


if __name__ == "__main__":
    main()

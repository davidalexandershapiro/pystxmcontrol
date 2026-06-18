#!/usr/bin/env python3
"""
Diagnostic for OSA small-scan beam centering on a REAL .stxm file.

Loads an OSA-scan .stxm file, then compares ways of locating the focused beam:
  * plain intensity-weighted centroid (COM) — what large-mode uses
  * Laplacian-of-Gaussian (LoG) focused-peak finder — what small-mode uses
    (imported directly from the task-agent tools, so this tests the real code)
  * brightest single pixel

It also sweeps the LoG sigma so you can see which spot scale (if any) isolates the
focused peak, and saves a figure overlaying every estimate on the image and on the
LoG response map.

Usage:
    python scripts/test_osa_center.py /path/to/NS_xxxxxx.stxm
    python scripts/test_osa_center.py FILE --daq default --region 0 --energy 0
    python scripts/test_osa_center.py FILE --sigma-um 4        # force a spot scale (µm)
    python scripts/test_osa_center.py FILE --show              # pop up the figure

The figure is saved next to the input file as <name>_osa_center.png unless --out is given.
"""

import argparse
import os
import sys

import numpy as np

# Headless-safe: pick a non-interactive backend unless --show is requested.
import matplotlib
if "--show" not in sys.argv:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_laplace

from pystxmcontrol.utils.writeNX import stxm
# The exact function small-mode uses, so the script tests the deployed calculation.
from pystxmcontrol.controller.task_agent.tools import _focused_peak_center


def extract_image(entry, daq, energy):
    """Return (img2d, xpos, ypos, daq_used) for one region entry of the stxm reader.

    counts may be a per-DAQ dict or a single ndarray; the energy axis (if present) is
    indexed by *energy*. xpos/ypos are the 1-D requested positions (µm) per axis.
    """
    counts = entry["counts"]
    if isinstance(counts, dict):
        daq_used = daq if daq in counts else ("default" if "default" in counts else next(iter(counts)))
        arr = np.asarray(counts[daq_used], dtype=float)
    else:
        daq_used = "(single)"
        arr = np.asarray(counts, dtype=float)

    # Collapse to a 2-D image (n_lines, n_x). Shapes seen: (n_energy, n_lines, n_x) or (n_lines, n_x).
    arr = np.squeeze(arr)
    if arr.ndim == 3:
        arr = arr[min(energy, arr.shape[0] - 1)]
    if arr.ndim != 2:
        raise ValueError(f"Unexpected counts shape after squeeze: {arr.shape}")

    xpos = np.asarray(entry.get("xpos"), dtype=float).ravel()
    ypos = np.asarray(entry.get("ypos"), dtype=float).ravel()
    return arr, xpos, ypos, daq_used


def idx_to_um(idx, pos):
    """Map a (possibly fractional) pixel index to µm via the axis endpoints.

    Uses endpoints rather than np.interp so it works whether pos ascends or descends.
    """
    n = pos.size
    if n < 2:
        return float(pos[0]) if n else float("nan")
    return float(pos[0] + idx * (pos[-1] - pos[0]) / (n - 1))


def com(img):
    w = np.clip(img.astype(float), 0.0, None)
    t = w.sum()
    if t <= 0:
        return None
    nx = img.shape[1]; ny = img.shape[0]
    cc = float((w.sum(0) * np.arange(nx)).sum() / t)
    rr = float((w.sum(1) * np.arange(ny)).sum() / t)
    return cc, rr


def log_peak(img, sigma_px):
    """LoG focused-peak at an explicit sigma (px). Returns (col,row,prominence,resp_map,margin).

    Matches _focused_peak_center: mode='nearest' + border mask to kill the Laplacian edge
    artifact that a bright scan boundary produces.
    """
    a = img.astype(float)
    a = a - a.min()
    ny, nx = img.shape
    resp = np.clip(-gaussian_laplace(a, sigma_px, mode="nearest"), 0.0, None)
    margin = min(int(np.ceil(2.0 * sigma_px)), min(ny, nx) // 4)
    if margin > 0:
        keep = np.zeros_like(resp, dtype=bool)
        keep[margin:ny - margin, margin:nx - margin] = True
        resp = np.where(keep, resp, 0.0)
    if resp.max() <= 0:
        return None
    pr, pc = np.unravel_index(int(np.argmax(resp)), resp.shape)
    win = max(1, int(round(sigma_px * 2.0)))
    r0, r1 = max(0, pr - win), min(img.shape[0], pr + win + 1)
    c0, c1 = max(0, pc - win), min(img.shape[1], pc + win + 1)
    sub = resp[r0:r1, c0:c1]; t = float(sub.sum())
    if t > 0:
        cc = float((sub.sum(0) * np.arange(c0, c1)).sum() / t)
        rr = float((sub.sum(1) * np.arange(r0, r1)).sum() / t)
    else:
        cc, rr = float(pc), float(pr)
    interior = resp[margin:ny - margin, margin:nx - margin] if margin > 0 else resp
    prominence = float(resp.max()) / (float(interior.mean()) + 1e-12)
    return cc, rr, prominence, resp, margin


def fmt(cc, rr, xpos, ypos):
    return f"px=({cc:5.1f},{rr:5.1f})  µm=({idx_to_um(cc, xpos):8.3f},{idx_to_um(rr, ypos):8.3f})"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="path to an OSA-scan .stxm file")
    ap.add_argument("--daq", default="default", help="DAQ channel (default: 'default')")
    ap.add_argument("--region", type=int, default=0, help="scan region / entry index (default 0)")
    ap.add_argument("--energy", type=int, default=0, help="energy index (default 0)")
    ap.add_argument("--sigma-um", type=float, default=None, help="force LoG spot scale in µm")
    ap.add_argument("--sigma-px", type=float, default=None, help="force LoG spot scale in pixels")
    ap.add_argument("--out", default=None, help="output PNG path")
    ap.add_argument("--show", action="store_true", help="display the figure interactively")
    args = ap.parse_args()

    nx_file = stxm(stxm_file=args.file)
    entry = nx_file.data[f"entry{args.region}"]
    img, xpos, ypos, daq_used = extract_image(entry, args.daq, args.energy)
    ny, nx = img.shape
    # µm per pixel (for converting sigma); fall back to 1 if positions are degenerate.
    px_um_x = abs(xpos[-1] - xpos[0]) / (nx - 1) if xpos.size > 1 else 1.0

    print(f"file        : {args.file}")
    print(f"scan_type   : {nx_file.meta.get('scan_type')}   region {args.region}   daq '{daq_used}'")
    print(f"image       : {ny} x {nx} px   pixel ≈ {px_um_x*1000:.1f} nm")
    print(f"x range µm  : [{xpos.min():.2f}, {xpos.max():.2f}]   y range µm : [{ypos.min():.2f}, {ypos.max():.2f}]")
    print()

    # --- the three estimates ---
    c = com(img)
    print("COM (large-mode)      :", fmt(*c, xpos, ypos) if c else "no positive signal")

    fp = _focused_peak_center(img)   # auto sigma, exactly as small-mode runs it
    if fp:
        auto_sigma = fp["sigma_px"]
        print(f"LoG focused-peak(auto): {fmt(fp['col_c'], fp['row_c'], xpos, ypos)}"
              f"   sigma={auto_sigma}px (~{auto_sigma*px_um_x:.2f}µm)  prominence={fp['prominence']}")
    else:
        auto_sigma = max(1.0, min(ny, nx) / 12.0)
        print("LoG focused-peak(auto): no positive LoG response")

    br, bc = np.unravel_index(int(np.argmax(img)), img.shape)
    print("brightest pixel       :", fmt(float(bc), float(br), xpos, ypos))
    print()

    # --- sigma sweep so you can see which spot scale isolates the real peak ---
    if args.sigma_px is not None:
        forced = [args.sigma_px]
    elif args.sigma_um is not None:
        forced = [args.sigma_um / px_um_x]
    else:
        forced = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
    print("LoG sigma sweep (px → peak):")
    sweep = []
    for s in forced:
        lp = log_peak(img, s)
        if lp:
            cc, rr, prom, _, _ = lp
            sweep.append((s, cc, rr, prom))
            print(f"   sigma={s:4.1f}px (~{s*px_um_x:4.2f}µm)  {fmt(cc, rr, xpos, ypos)}  prominence={prom:6.2f}")
        else:
            print(f"   sigma={s:4.1f}px  no response")

    # sigma to visualize the response map: forced value if given, else the auto sigma
    vis_sigma = forced[0] if (args.sigma_px or args.sigma_um) else auto_sigma
    lp_vis = log_peak(img, vis_sigma)
    resp = lp_vis[3] if lp_vis else np.zeros_like(img)
    vis_margin = lp_vis[4] if lp_vis else 0

    # --- figure ---
    fig, ax = plt.subplots(1, 2, figsize=(13, 6))
    ax[0].imshow(img, origin="lower", cmap="viridis")
    ax[0].set_title(f"OSA image ({ny}×{nx})")
    ax[1].imshow(resp, origin="lower", cmap="magma")
    ax[1].set_title(f"-LoG response (sigma={vis_sigma:.1f}px ~ {vis_sigma*px_um_x:.2f}µm)")

    def mark(a, cc, rr, m, color, label):
        a.plot(cc, rr, m, color=color, markersize=14, markeredgewidth=2,
               markerfacecolor="none", label=label)

    for a in ax:
        if c:
            mark(a, c[0], c[1], "x", "red", "COM")
        if fp:
            mark(a, fp["col_c"], fp["row_c"], "+", "cyan", "LoG auto")
        mark(a, bc, br, "o", "yellow", "brightest")
        a.plot((nx - 1) / 2.0, (ny - 1) / 2.0, "s", color="white",
               markersize=10, markerfacecolor="none", label="scan center")
        # Border margin that the peak finder ignores (Laplacian edge artifacts live here).
        if vis_margin > 0:
            a.add_patch(plt.Rectangle((vis_margin - 0.5, vis_margin - 0.5),
                                      nx - 2 * vis_margin, ny - 2 * vis_margin,
                                      fill=False, edgecolor="lime", ls="--", lw=1.2))
    ax[0].legend(loc="upper right", fontsize=8, framealpha=0.6)

    out = args.out or os.path.splitext(args.file)[0] + "_osa_center.png"
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\nsaved figure: {out}")
    if args.show:
        plt.show()


if __name__ == "__main__":
    main()

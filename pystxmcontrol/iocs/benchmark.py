"""Fly-line benchmark: native pystxmcontrol server vs caproto IOC path.

NEEDS BEAMLINE TIME + HARDWARE (E712 + keysight). Run with David.
Acceptance (spec 2026-07-12 §7): no measurable line-rate regression;
target < 2 % line-turnaround overhead vs the native scan server.

Usage (once implemented):
    python -m pystxmcontrol.iocs.benchmark --lines 100 --npoints 1000 --dwell 1.0
"""
from __future__ import annotations

import argparse


def bench_ioc_path(lines: int, npoints: int, dwell_ms: float) -> list[float]:
    """Time `lines` fly lines through STXM{station}:E712:FLY PVs.

    Implementation sketch (do NOT run in sim - sim timings are meaningless):
    ARM once, then per line: t0 = perf_counter(); put GO with wait=True;
    record perf_counter() - t0. Return per-line turnaround seconds.
    """
    raise NotImplementedError("needs hardware; see module docstring")


def bench_native_path(lines: int, npoints: int, dwell_ms: float) -> list[float]:
    """Same measurement through David's native scan server (line_image scan),
    same hardware, same trajectory. Coordinate with David for the driver call
    sequence (controller/scans/line_image.py)."""
    raise NotImplementedError("needs hardware; see module docstring")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines", type=int, default=100)
    parser.add_argument("--npoints", type=int, default=1000)
    parser.add_argument("--dwell", type=float, default=1.0)
    args = parser.parse_args(argv)
    ioc = bench_ioc_path(args.lines, args.npoints, args.dwell)
    native = bench_native_path(args.lines, args.npoints, args.dwell)
    import statistics
    m_i, m_n = statistics.median(ioc), statistics.median(native)
    print(f"native median {m_n * 1000:.2f} ms | ioc median {m_i * 1000:.2f} ms "
          f"| overhead {(m_i / m_n - 1) * 100:+.2f}%")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""
piezo_relax_diagnostic.py

Measure the open-loop relaxation drift of the fine (interferometer/piezo) axis so
that `relax_time` for the derived-piezo drivers (derivedPiezo, inclinedDerivedPiezo,
inclinedSampleDerivedPiezo) can be calibrated.

Background
----------
Those drivers make a large coarse move by: fine -> 0, servo OFF, coarse move,
setZero(), servo ON, fine correction.  While the servo is OFF the piezo relaxes
open-loop by some drift delta.  The drivers now capture that drift immediately
after servo-off and subtract it from the final fine correction (the `relax_offset`
term).  For that subtraction to be accurate the drift MUST have settled by the time
we read it -- i.e. `relax_time` (the sleep between servo-off and the read) must be
long enough.

This script disables the servo on the fine axis and logs getPos() over time so you
can see where the drift flattens out and pick `relax_time` accordingly.

SAFETY
------
This physically turns the servo OFF on a real piezo stage, which lets it drift
open-loop.  It:
  * refuses to run without --yes,
  * refuses to run against a simulated axis unless --allow-sim,
  * ALWAYS turns the servo back on and restores the starting setpoint, even on
    Ctrl-C or error (try/finally),
  * warns if the configured driver's servoState() is a no-op (e.g. mclMotor), in
    which case no relaxation can occur and the relax_offset correction is inert.

Usage
-----
    python piezo_relax_diagnostic.py --motor FineX --yes
    python piezo_relax_diagnostic.py --motor FineY --duration 5 --interval 0.02 --yes

Outputs a CSV and (if matplotlib is available) a PNG next to a --out prefix.
"""
import argparse
import inspect
import json
import os
import sys
import time

# Same import surface the controller uses, so eval() below can find every driver class.
from pystxmcontrol.drivers import *  # noqa: F401,F403

BASEPATH = sys.prefix
DEFAULT_CONFIG = os.path.join(BASEPATH, "pystxmcontrol_cfg", "motor.json")


def load_config(path):
    with open(path) as fh:
        return json.load(fh)


def servostate_is_stub(motor_obj):
    """True if the driver's servoState() body is effectively just `pass`/docstring."""
    try:
        src = inspect.getsource(type(motor_obj).servoState)
    except (OSError, TypeError):
        return False
    body = []
    for line in src.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(("def ", '"', "'")):
            continue
        body.append(s)
    return body == ["pass"] or body == []


def build_fine_axis(motor_config, motor_name, force_sim, allow_live):
    """Instantiate just the requested primary axis' controller + driver and connect.

    Mirrors controller.controller.initialize() for a single primary motor.
    """
    if motor_name not in motor_config:
        sys.exit(f"Motor '{motor_name}' not found in config. "
                 f"Available: {', '.join(sorted(motor_config))}")
    cfg = motor_config[motor_name]
    if cfg.get("type") != "primary":
        sys.exit(f"Motor '{motor_name}' is type '{cfg.get('type')}', not a primary "
                 f"axis. Pass the FINE axis (e.g. FineX/FineY), not the derived motor.")

    # Resolve simulation: --allow-sim keeps the config value; otherwise force live.
    if force_sim:
        sim = True
    elif allow_live:
        sim = bool(cfg.get("simulation", True))
    else:
        sim = False
    cfg["simulation"] = int(sim)

    controller_name = cfg["controller"]
    controller_id = cfg["controllerID"]
    port = int(cfg.get("port", 0))
    print(f"Instantiating controller {controller_name} (id={controller_id}, "
          f"port={port}, simulation={sim}) ...")
    ctrl = eval("%s(address = '%s', port = %i, simulation = %i)"
                % (controller_name, controller_id, port, int(sim)))
    # initialize() signature varies across controllers; try the kwarg form first.
    try:
        ctrl.initialize(simulation=sim)
    except TypeError:
        ctrl.initialize()

    motor_obj = eval(cfg["driver"] + "()")
    motor_obj.controller = ctrl
    motor_obj.config = cfg
    motor_obj.connect(axis=cfg["axis"])
    return motor_obj, ctrl, sim


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--motor", default="FineX",
                    help="Name of the FINE (piezo/interferometer) axis in motor.json "
                         "(default: FineX).")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help=f"Path to motor.json (default: {DEFAULT_CONFIG}).")
    ap.add_argument("--duration", type=float, default=3.0,
                    help="Seconds to observe drift after servo-off (default: 3.0).")
    ap.add_argument("--interval", type=float, default=0.05,
                    help="Sampling period in seconds (default: 0.05).")
    ap.add_argument("--no-center", action="store_true",
                    help="Do NOT move the fine axis to 0 before the test. By default "
                         "it is centered to mimic the driver's fine->0 step.")
    ap.add_argument("--settle-tol-nm", type=float, default=5.0,
                    help="Drift is 'settled' once it stays within this many nm of its "
                         "final value; used to recommend relax_time (default: 5 nm).")
    ap.add_argument("--out", default="piezo_relax",
                    help="Output filename prefix for CSV/PNG (default: piezo_relax).")
    ap.add_argument("--yes", action="store_true",
                    help="Required to actually disable the servo on hardware.")
    ap.add_argument("--allow-sim", action="store_true",
                    help="Allow running against a simulated axis (drift will be ~0).")
    args = ap.parse_args()

    if not args.yes:
        sys.exit("Refusing to run without --yes: this disables the servo on a real "
                 "piezo and lets it drift open-loop. Re-run with --yes when ready.")

    motor_config = load_config(args.config)
    fine, ctrl, sim = build_fine_axis(motor_config, args.motor,
                                      force_sim=False, allow_live=args.allow_sim)

    if sim and not args.allow_sim:
        sys.exit(f"Axis '{args.motor}' is configured for simulation. There is nothing "
                 f"to relax. Point --config at the live beamline motor.json, or pass "
                 f"--allow-sim to dry-run the script logic.")

    stub = servostate_is_stub(fine)
    print(f"\nFine axis driver: {type(fine).__name__}")
    if stub:
        print("  WARNING: this driver's servoState() is a NO-OP. The servo will not "
              "actually turn off, no relaxation will occur, and the relax_offset "
              "correction in the derived driver is inert on this hardware.\n"
              "  (This is the case for mclMotor / Mad City Labs.)")

    samples = []  # (t_seconds, position_um)
    start_pos = None
    try:
        start_pos = fine.getPos()
        print(f"Starting fine position: {start_pos:.6f} um")

        if not args.no_center:
            print("Centering fine axis (moveTo 0) to mimic the driver's fine->0 step ...")
            fine.moveTo(0.)
            time.sleep(0.2)

        baseline = fine.getPos()
        print(f"Baseline (servo on): {baseline:.6f} um")

        print(f"Disabling servo and logging for {args.duration:.1f} s "
              f"every {args.interval*1000:.0f} ms ...")
        fine.servoState(False)

        t0 = time.perf_counter()
        next_t = 0.0
        while True:
            t = time.perf_counter() - t0
            pos = fine.getPos()
            samples.append((t, pos))
            if t >= args.duration:
                break
            next_t += args.interval
            sleep_for = next_t - (time.perf_counter() - t0)
            if sleep_for > 0:
                time.sleep(sleep_for)
    finally:
        # ALWAYS restore: servo on, then return to the original setpoint.
        try:
            fine.servoState(True)
            time.sleep(0.2)
            if start_pos is not None:
                fine.moveTo(start_pos)
                print(f"\nServo re-enabled; restored fine axis toward {start_pos:.6f} um.")
        except Exception as exc:  # pragma: no cover - best-effort cleanup
            print(f"\nWARNING: failed to fully restore fine axis: {exc}")
        try:
            ctrl.close()
        except Exception:
            pass

    if not samples:
        sys.exit("No samples collected.")

    # ---- analysis -------------------------------------------------------
    baseline_pos = samples[0][1]
    final_pos = samples[-1][1]
    drift_um = [p - baseline_pos for _, p in samples]
    total_drift_nm = (final_pos - baseline_pos) * 1000.0
    peak_drift_nm = max((abs(d) for d in drift_um)) * 1000.0

    tol_um = args.settle_tol_nm / 1000.0
    settle_t = None
    for i, (t, p) in enumerate(samples):
        # settled once THIS and all later samples stay within tol of the final value
        if all(abs(pp - final_pos) <= tol_um for _, pp in samples[i:]):
            settle_t = t
            break

    print("\n" + "=" * 60)
    print(f"Total drift (servo-off -> end): {total_drift_nm:+.1f} nm "
          f"({total_drift_nm/1000.0:+.4f} um)")
    print(f"Peak |drift|:                   {peak_drift_nm:.1f} nm")
    if settle_t is not None:
        recommended = round(settle_t * 1.5 + 0.05, 2)  # 50% margin, min headroom
        print(f"Drift settled within {args.settle_tol_nm:.0f} nm at t = {settle_t:.3f} s")
        print(f"Recommended relax_time (with 50% margin): {recommended:.2f} s")
    else:
        print(f"Drift did NOT settle within {args.settle_tol_nm:.0f} nm during the "
              f"{args.duration:.1f} s window -- increase --duration and re-run.")
    if stub:
        print("(servoState is a no-op on this driver; drift above is just sensor "
              "noise, not real relaxation.)")
    print("=" * 60)

    # ---- CSV ------------------------------------------------------------
    csv_path = f"{args.out}.csv"
    with open(csv_path, "w") as fh:
        fh.write("time_s,position_um,drift_nm\n")
        for (t, p), d in zip(samples, drift_um):
            fh.write(f"{t:.4f},{p:.6f},{d*1000.0:.3f}\n")
    print(f"Wrote {csv_path} ({len(samples)} samples).")

    # ---- plot (best effort) --------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ts = [t for t, _ in samples]
        dn = [d * 1000.0 for d in drift_um]
        plt.figure(figsize=(8, 4.5))
        plt.plot(ts, dn, marker=".", ms=3, lw=1)
        if settle_t is not None:
            plt.axvline(settle_t, color="r", ls="--",
                        label=f"settled @ {settle_t:.2f}s")
            plt.legend()
        plt.xlabel("time after servo-off (s)")
        plt.ylabel("drift (nm)")
        plt.title(f"{args.motor} open-loop relaxation ({type(fine).__name__})")
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        png_path = f"{args.out}.png"
        plt.savefig(png_path, dpi=120)
        print(f"Wrote {png_path}.")
    except Exception as exc:
        print(f"(Skipped plot: {exc})")


if __name__ == "__main__":
    main()

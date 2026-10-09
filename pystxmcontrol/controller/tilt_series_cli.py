"""Run a tilt series from a JSON file — the headless replacement for the beamline script.

    python -m pystxmcontrol.controller.tilt_series_cli plan  series.json
    python -m pystxmcontrol.controller.tilt_series_cli run   series.json [--start N] [--yes]

``plan`` connects, fits and prints the predicted orbit without moving anything; ``run``
does the same, asks for confirmation, then tracks.  Ctrl-C stops cleanly (the scan in
progress is cancelled) and prints the index to resume from with ``--start``.  At the end
the tracked positions are offered for approval into the orbit database.

series.json::

    {
      "server": {"host": "131.243.73.81", "port": 9999},     # default: main.json
      "sample": {"label": "Al2O3-NiFe"},                     # or {"sample_id": 7}
      "anchors": [                                           # recorded into the database
        {"angle": 0.0,  "coarse_y": 209.0, "sample_x": -85.0, "zone_plate_z": -9730.0,
         "energy": 708.0},
        ...
      ],
      "angles": [{"start": -80, "stop": 70, "step": 2}],
      "tracker": {                                           # TiltSeriesConfig fields
        "stxm_scan":   {"scan_type": "Spiral Image", "spiral": true, "dwell": 0.2,
                        "energy_start": 851.0, "energy_stop": 851.0, ...},
        "ptycho_scan": {"scan_type": "Ptychography Image", "dwell": 10, ...},
        "ptycho_shift_x": 1.5
      },
      "log_path": "tilt_series_log.jsonl"
    }

The series runs at the scan templates' energy_start, which both templates must share
(see ``TiltSeriesConfig.validate``); anchors without "energy" are taken as focused at
it.  With "sample_id", the sample's approved database points are used as anchors as
well as any listed here.
"""

import argparse
import json
import os
import sys
import threading

from pystxmcontrol.controller.orbit_database import OrbitDatabaseClient
from pystxmcontrol.controller.tilt_series import (
    ClientInstrument, TiltSeriesConfig, TiltSeriesTracker, plan_series,
)


def _server_address(spec: dict):
    server = spec.get("server") or {}
    if server.get("host"):
        return server["host"], int(server.get("port", 9999))
    cfg_path = os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json")
    with open(cfg_path) as f:
        main = json.load(f)["server"]
    return main["stxm_address"], int(main.get("command_port", 9999))


def _connect(spec):
    from pystxmcontrol.controller.instrument_client import ScripterClient
    from pystxmcontrol.controller.scripter import scripter

    host, port = _server_address(spec)
    client = ScripterClient(scripter(host, port))
    client.get_config()
    return client


def _anchor_key(a) -> tuple:
    return (round(a["angle"], 3), round(a["coarse_y"], 3), round(a["zone_plate_z"], 3))


def _sample_and_anchors(db, spec):
    """``(sample_id or None, anchors, new_anchors)``.

    *anchors* is everything the fit uses: the sample's approved database points plus the
    file's.  *new_anchors* is the file's that the database does not hold yet, so a
    resumed run does not record them twice.
    """
    sid = (spec.get("sample") or {}).get("sample_id")
    stored = []
    if sid is not None:
        stored = [{k: p[k] for k in ("angle", "coarse_y", "sample_x", "zone_plate_z",
                                     "energy", "zp_calibration")}
                  for p in db.get_points(sample_id=sid, approved_only=True)]
    known = {_anchor_key(a) for a in stored}
    new = [dict(a) for a in spec.get("anchors") or [] if _anchor_key(a) not in known]
    return sid, stored + new, new


def _plan(client, db, spec, sid, anchors, config):
    inst = ClientInstrument(client)
    energy = config.energy
    exclude = [sid] if sid is not None else None
    history = db.orbit_samples(exclude=exclude)
    zp_cal = (lambda e: inst.zp_calibration(e)) if inst.zp_calibration(energy) is not None \
        else None
    plan = plan_series(anchors, spec["angles"], history, energy, zp_cal,
                       use_small_terms=spec.get("use_small_terms"), GY=spec.get("GY"))
    return inst, plan


def _print_plan(plan):
    fit = plan.fit
    print(f"GY {fit.GY:.4f} from {len(plan.history_samples)} past samples; "
          f"{fit.n_anchors} anchors; small terms {'on' if fit.use_small_terms else 'off'}")
    print(f"params {json.dumps({k: round(v, 2) for k, v in fit.params.as_dict().items()})}")
    print(f"anchor rms: CoarseY {fit.rms_y:.2f} µm, ZonePlateZ {fit.rms_z:.2f} µm")
    print(f"run energy {plan.energy} eV, zone-plate calibration {plan.zp_calibration:.1f} µm")
    print(plan.table())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("plan", "run"))
    parser.add_argument("spec", help="series JSON file")
    parser.add_argument("--start", type=int, default=0, help="resume from this angle index")
    parser.add_argument("--yes", action="store_true", help="do not ask before running")
    a = parser.parse_args(argv)

    with open(a.spec) as f:
        spec = json.load(f)
    config = TiltSeriesConfig.from_dict(spec.get("tracker") or {})
    config.validate()                    # before connecting: a bad file costs nothing
    client = _connect(spec)
    db = OrbitDatabaseClient(client)

    sid, anchors, new_anchors = _sample_and_anchors(db, spec)
    if len(anchors) < 2:
        sys.exit("need at least two anchors (listed in the file or recorded for sample_id)")
    if a.action == "run" and a.start > 0 and sid is None:
        sys.exit("resuming needs the database sample: set \"sample\": {\"sample_id\": N} "
                 "to the id the first run printed")
    inst, plan = _plan(client, db, spec, sid, anchors, config)
    _print_plan(plan)
    if a.action != "run":
        return

    if not a.yes and input(f"\nTrack {len(plan.targets) - a.start} angles from index "
                           f"{a.start}? [y/N] ").strip().lower() != "y":
        return
    if not config.debug:
        if sid is None:
            sid = db.create_sample(label=(spec.get("sample") or {}).get("label")
                                   or "tilt series", created_by="tilt_series_cli")
        for anc in new_anchors:
            e = anc.get("energy", plan.energy)
            db.add_point(sample_id=sid, kind="anchor", angle=anc["angle"],
                         coarse_y=anc["coarse_y"], sample_x=anc["sample_x"],
                         zone_plate_z=anc["zone_plate_z"], energy=e,
                         zp_calibration=inst.zp_calibration(e) if e is not None else None)
        print(f"database sample {sid} ({len(new_anchors)} new anchors recorded); "
              f"to resume, set \"sample\": {{\"sample_id\": {sid}}}")

    def on_event(kind, data):
        if kind in ("angle_start", "warning", "finished"):
            print(f"[{kind}] {data}", flush=True)
        elif kind == "angle_done":
            print(f"[done] {data['index'] + 1}/{data['total']} at {data['angle']}°, "
                  f"{data['elapsed_s']:.0f} s elapsed", flush=True)

    tracker = TiltSeriesTracker(inst, config, plan.targets, db=db, sample_id=sid,
                                log_path=spec.get("log_path"), on_event=on_event)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(r=tracker.run(a.start)),
                              daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.5)
    except KeyboardInterrupt:
        print("\nstopping: cancelling the scan in progress...", flush=True)
        tracker.stop(abort_scan=True)
        worker.join()
    result = outcome["r"]
    print(f"\n{result.status}: {result.message}")
    if result.status != "complete":
        print(f"resume with: --start {result.next_index}")

    tracked = [r for r in result.results if r.point_id is not None]
    if tracked and sid is not None:
        answer = input(f"Approve {len(tracked)} tracked positions into the orbit history "
                       f"for sample {sid}? [y/N/discard] ").strip().lower()
        if answer == "y":
            n = db.approve_points(sample_id=sid, point_ids=[r.point_id for r in tracked])
            print(f"approved {n}")
        elif answer == "discard":
            print(f"discarded {db.discard_pending(sample_id=sid)}")
        else:
            print("left pending; approve or discard later")


if __name__ == "__main__":
    main()

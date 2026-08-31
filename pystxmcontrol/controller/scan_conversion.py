"""Conversion between the flat agent-facing scan definition (``ScanModel``) and the
nested scan dict the control server consumes.

Both agent surfaces — the task agent's ``ToolSet`` and the MCP server (through
``scripter``) — build the same ``energy_regions`` structure, so that construction
lives here once.  The server supports any number of regions, each with its own
dwell (``writeNX._extractEnergies`` concatenates them into per-energy energy/dwell
arrays that the scan drivers index), which is what a saved energy definition
expresses; building only ``EnergyRegion1`` silently flattens the operator's intent.

Note the precedence the server applies, which ``build_energy_regions`` is careful to
respect: a top-level ``energy_list`` short-circuits ``energy_regions`` entirely and
forces one uniform dwell.  A multi-region scan must therefore send ``energy_list``
as None.

``build_server_scan`` builds the whole outbound scan dict, spatial geometry included.
That was forked for a while — ``scripter`` spanned the full range with
``step = range/(points-1)`` and no inset, so an MCP-launched scan came out one pixel
larger than the same scan launched from the GUI or the task agent.  The GUI convention
(``step = range/points``, first/last pixel centres inset half a step) is the correct one
and is now the only one.
"""


def build_energy_regions(scan: dict) -> dict:
    """Build the server's ``{"EnergyRegionN": {...}}`` from a flat scan definition.

    Precedence, highest first:

    1. ``energy_regions`` — a multi-region definition (e.g. an applied energy
       preset); emitted verbatim, each region keeping its own dwell.
    2. ``energy_list``    — an explicit list of energies, emitted as one region
       spanning the list (the server reads the list itself and applies the single
       top-level ``dwell``).
    3. ``energy_start`` / ``energy_stop`` / ``energy_points`` — one region.
    """
    regions = scan.get("energy_regions")
    if regions:
        out = {}
        for i, r in enumerate(regions):
            # Regions may be EnergyRegionModel instances or plain dicts.
            r = r if isinstance(r, dict) else r.model_dump()
            n = int(r.get("n_energies", 1) or 1)
            start, stop = float(r["start"]), float(r["stop"])
            step = r.get("step")
            if step is None:
                step = (stop - start) / (n - 1) if n > 1 else 0.0
            out[f"EnergyRegion{i + 1}"] = {
                "dwell": float(r.get("dwell", 1.0)),
                "start": start,
                "stop": stop,
                "step": float(step),
                "n_energies": n,
            }
        return out

    energy_list = scan.get("energy_list")
    if energy_list:
        e_start, e_stop, e_points = energy_list[0], energy_list[-1], len(energy_list)
    else:
        e_start = scan["energy_start"]
        e_stop = scan["energy_stop"]
        e_points = scan["energy_points"]
    return {
        "EnergyRegion1": {
            "dwell": scan["dwell"],
            "start": e_start,
            "stop": e_stop,
            "step": (e_stop - e_start) / max(e_points, 1),
            "n_energies": e_points,
            "energy_list": energy_list,
        }
    }


def energy_list_for_scan(scan: dict):
    """The top-level ``energy_list`` to send alongside ``build_energy_regions``.

    None for a multi-region scan: a non-None ``energy_list`` makes the server ignore
    ``energy_regions`` and apply one uniform dwell, discarding the per-region dwells.
    """
    return None if scan.get("energy_regions") else scan.get("energy_list")


def energy_regions_from_server(scan: dict):
    """Read a server/``lastScan`` scan dict's energy regions back into flat form.

    Returns a list of region dicts when the scan has MORE than one region, else None
    — a single region is fully described by the flat ``energy_start``/``stop``/
    ``points``/``dwell`` fields, and leaving ``energy_regions`` unset there keeps the
    common single-region case simple for the agent to reason about.
    """
    regions = scan.get("energy_regions") or {}
    if len(regions) < 2:
        return None

    def _index(item):
        digits = "".join(c for c in str(item[0]) if c.isdigit())
        return int(digits) if digits else 0

    out = []
    for _key, r in sorted(regions.items(), key=_index):
        n = int(r.get("n_energies", 1) or 1)
        start, stop = float(r["start"]), float(r["stop"])
        step = r.get("step")
        out.append({
            "start": start,
            "stop": stop,
            "n_energies": n,
            "dwell": float(r.get("dwell", 1.0)),
            "step": float(step) if step is not None else (
                (stop - start) / (n - 1) if n > 1 else 0.0),
        })
    return out


def convert_scan(scan: dict) -> dict:
    """Convert a pystxmcontrol scan dict (nested scan_regions) to flat ScanModel form.

    Shared by the task agent and the MCP server so a scan read back from the
    server's ``lastScan`` means the same thing on both paths.
    """
    _er = scan["energy_regions"]["EnergyRegion1"]
    _e_start = _er["start"]
    _e_points = _er["n_energies"]
    # A single-energy scan sits at ONE energy — the region's 'start'.  Its stored 'stop'
    # can be stale or descending (start > stop), e.g. after the beamline energy is moved,
    # which trips ScanModel's energy_stop >= energy_start validator and makes the caller
    # silently fall back to ScanModel() DEFAULTS (5x5 µm, 50x50, 700 eV, 0.2 ms, …) — the
    # symptom of the agent reporting default parameters instead of the real last scan.
    # Collapse stop→start when there is only one energy so it round-trips cleanly.
    _e_stop = _e_start if (_e_points and int(_e_points) <= 1) else _er["stop"]
    return {
        'scan_type':          scan['scan_type'],
        'proposal':           scan['proposal'],
        'experimenters':      scan['experimenters'],
        'nx_file_version':    float(scan.get('nx_file_version') or 3.0),
        'sample_description': scan['sample'],
        'x_motor':            scan['x_motor'],
        'y_motor':            scan['y_motor'],
        'z_motor':            scan.get('z_motor'),
        'x_center':           scan['scan_regions']['Region1']['xCenter'],
        'y_center':           scan['scan_regions']['Region1']['yCenter'],
        'z_center':           scan['scan_regions']['Region1']['zCenter'],
        'x_range':            scan['scan_regions']['Region1']['xRange'],
        'y_range':            scan['scan_regions']['Region1']['yRange'],
        'z_range':            scan['scan_regions']['Region1']['zRange'],
        'x_points':           scan['scan_regions']['Region1']['xPoints'],
        'y_points':           scan['scan_regions']['Region1']['yPoints'],
        'z_points':           scan['scan_regions']['Region1']['zPoints'],
        'energy_start':       _e_start,
        'energy_stop':        _e_stop,
        'energy_points':      _e_points,
        'energy_regions':     energy_regions_from_server(scan),
        'dwell':              _er['dwell'],
        'spiral':             scan.get('spiral', False),
        'autofocus':          scan.get('autofocus', True),
        'defocus':            scan.get('defocus', False),
        'daq_list':           scan.get('daq_list', ['default']),
        'comment':            scan.get('comment', ''),
        'energy_list':        scan.get('energy_list'),
        'retract':            scan.get('retract', True),
        'double_exposure':    False,
        'loop_scan':          False,
    }


def build_scan_region(x_center: float, x_range: float, x_points: int,
                      y_center: float, y_range: float, y_points: int,
                      z_center: float = 0.0, z_range: float = 0.0, z_points: int = 1,
                      ndigits: int = 3) -> dict:
    """Build one server ``Region`` entry from a centre/range/points triple per axis.

    Follows the GUI/server convention (mainwindow_mvc / main_controller._get_region):
    ``range`` is the FULL field, so ``step = range/points`` and the first/last pixel
    CENTRES are inset half a step from the field edges — the scanned span is
    ``(points-1)*step``.  Using ``range/(points-1)`` with no inset makes the field one
    pixel too big, which is exactly the divergence this helper exists to prevent.

    ``start``/``stop`` use the unrounded step so the geometry matches the GUI exactly;
    only the reported ``Step`` field is rounded, to *ndigits*.  Small particle ROIs pass
    ``ndigits=4`` because 3 decimals cannot express their sub-10 nm pixel size.
    """
    out = {}
    for axis, center, rng, points in (("x", x_center, x_range, x_points),
                                      ("y", y_center, y_range, y_points),
                                      ("z", z_center, z_range, z_points)):
        step_raw = (rng / points) if points else 0.0
        out[f"{axis}Start"]  = center - rng / 2.0 + step_raw / 2.0
        out[f"{axis}Stop"]   = center + rng / 2.0 - step_raw / 2.0
        out[f"{axis}Points"] = points
        out[f"{axis}Step"]   = round(step_raw, ndigits)
        out[f"{axis}Range"]  = rng
        out[f"{axis}Center"] = center
    return out


def build_server_scan(scan: dict, scans_config: dict) -> dict:
    """Convert a flat ``ScanModel`` dict into the nested scan dict the server consumes.

    The inverse of :func:`convert_scan`, and the single builder for every outbound
    scan: the task agent's ``start_scan``, its multi-region scan (which replaces
    ``scan_regions`` afterwards), and ``scripter.stxm_scan``.

    *scans_config* is the server's scan.json (scan-type → driver/mode metadata); a
    scan type missing from it falls back to a derived-line image on continuous lines.
    """
    energy_regions = build_energy_regions(scan)
    energy_list = energy_list_for_scan(scan)

    scan_type = scan['scan_type']
    driver = scans_config.get(scan_type, {}).get('driver', 'derived_line_image')
    mode   = scans_config.get(scan_type, {}).get('mode', 'continuousLine')

    return {
        'scan_type':          scan_type,
        'proposal':           scan['proposal'],
        'experimenters':      scan['experimenters'],
        'sample':             scan['sample_description'],
        'x_motor':            scan['x_motor'],
        'y_motor':            scan['y_motor'],
        'z_motor':            scan.get('z_motor'),
        'energy_motor':       'Energy',
        'doubleExposure':     scan.get('double_exposure', False),
        'n_repeats':          1,
        'defocus':            scan.get('defocus', False),
        'autofocus':          scan.get('autofocus', True),
        'oversampling_factor': 3,
        'mode':               mode,
        'coarse_only':        scan.get('coarse_only', False),
        'spiral':             scan.get('spiral', False),
        'tiled':              scan.get('tiled', False),
        'daq_list':           scan.get('daq_list', ['default']),
        'comment':            scan.get('comment', ''),
        'loop_scan':          scan.get('loop_scan', False),
        'energy_list':        energy_list,
        'dwell':              scan['dwell'],
        'retract':            scan.get('retract', True),
        'driver':             driver,
        'scan_regions': {
            'Region1': build_scan_region(
                scan['x_center'], scan['x_range'], scan['x_points'],
                scan['y_center'], scan['y_range'], scan['y_points'],
                scan['z_center'], scan['z_range'], scan['z_points'],
            )
        },
        'energy_regions': energy_regions,
    }

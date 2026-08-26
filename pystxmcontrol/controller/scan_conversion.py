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

The spatial (``scan_regions``) construction is deliberately NOT shared: the task
agent insets the first/last pixel centres by half a step to match the GUI, while
``scripter`` spans the full range without an inset.  Unifying those would change
scan geometry, which is a separate decision from this one.
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

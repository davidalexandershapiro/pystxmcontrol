from mcp.server.fastmcp import FastMCP
from pystxmcontrol.controller.scripter import scripter
import pystxmcontrol.mcp.utilities as stxm_utils
import os
import json
import sys
import zmq
import asyncio
import traceback

# Things to add:
# 3. Single/Double motor scans

mcp = FastMCP("pystxmcontrol-mcp")

# Read-only mode: when PYSTXM_MCP_READONLY is set, hardware-mutating tools
# (move_motor, stxm_scan) are NOT advertised to the agent, so general users can
# read state and build scan configs but cannot move motors or start acquisitions.
# Launch this mode via `python -m pystxmcontrol.mcp.readonly`.
READONLY = os.environ.get("PYSTXM_MCP_READONLY", "").strip().lower() in ("1", "true", "yes", "on")


def _hw_tool():
    """Register a hardware-mutating tool only when NOT in read-only mode.

    In read-only mode the function stays importable/callable (tests, internal
    use) but is never registered with the MCP server, so it is invisible to the
    agent — a stronger guarantee than a permission deny-rule the user could edit.
    """
    def deco(fn):
        return fn if READONLY else mcp.tool()(fn)
    return deco
# Module state, populated on connect. Initialise ALL to None so a tool called
# before connect_to_server() hits a clean guard (or lazy auto-connect) instead of
# `NameError: name 'SCRIPTER' is not defined`.
MOTORS = SCANS = POSITIONS = DAQS = CONFIG = SCRIPTER = None


def _default_server():
    """Resolve the control-server (host, port) to use when connect_to_server is
    called with no explicit address.

    Priority: PYSTXM_SERVER_HOST/PORT env vars → the ``server`` block of the
    pystxmcontrol main.json (located via PYSTXM_MAIN_JSON, else common install
    paths) → 127.0.0.1:9999.  Reading main.json means the agent can just say
    "connect to the server" and reach the real instrument instead of hanging on
    the localhost default.
    """
    host = os.environ.get("PYSTXM_SERVER_HOST")
    if host:
        return host, int(os.environ.get("PYSTXM_SERVER_PORT") or 9999)

    candidates = [os.environ.get("PYSTXM_MAIN_JSON"),
                  os.path.join(sys.prefix, "pystxmcontrol_cfg", "main.json")]
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                srv = json.load(open(path)).get("server", {})
                return srv.get("stxm_address", "127.0.0.1"), int(srv.get("command_port", 9999))
            except Exception:
                pass
    return "127.0.0.1", 9999


def _ensure_connected():
    """Lazily open the scripter connection (using the configured default address)
    if a tool is invoked before connect_to_server().  Removes the whole class of
    "forgot to connect" / "SCRIPTER is not defined" failures.

    Returns None on success, or an error string if the connection cannot be made.
    """
    global SCRIPTER, MOTORS, SCANS, POSITIONS, DAQS, CONFIG
    if SCRIPTER is not None:
        return None
    host, port = _default_server()
    try:
        SCRIPTER = scripter(host, port)
        MOTORS, SCANS, POSITIONS, DAQS, CONFIG = SCRIPTER.get_config()
        return None
    except Exception as e:
        SCRIPTER = None
        return (f"Not connected, and auto-connect to {host}:{port} failed: {e}. "
                "The control server may be down; ask the operator how to proceed.")

@mcp.tool()
def get_safety_instructions() -> str:
    return """
    CRITICAL SAFETY RULES:
        1. Always ask the user to confirm the scan configuration before executing the scan
        2. Never move the OSA_Z motor as this can cause hardware failure
        3. Always ask for confirmation before moving the CoarseR stage by more than 5 degrees.
        4. Always ask for confirmation before moving the energy more than 100 eV
        5. Never attempt to move a motor beyond its software limit
    GENERAL OPERATING RULES:
        1. If a tool fails, don't try to solve the problem.  Just report the failure to the user and ask how to proceed.
        2. Scanning takes time.  ASk for confirmation if scans are bigger than 100x100 pixels or dwell time is bigger than 5 ms.
        3. Ask for confirmation if the number of energies is larger than about 10
        4. Ask for confirmation if the scan range is greater than 50x50 microns for Sample motors or bigger than 500x500 for OSA motors
        5. Ask for confirmation if the scan configuration shows the scan positions far away from the current motor positions, by a distance
        larger than the scan range.
    TYPICAL WORKFLOW FOR SINGLE ENERGY IMAGES, after receiving user prompt
        1. If the current x-ray energy is not the same as the requested scan energy, move the energy motor before executing the scan
        2. execute get_config() to get the most recent information from the server
        3. update_scan with the requested scan_type and arguments from the user
        4. request confirmation of the updated scan configuration
        5. execute stxm_scan()
        6. after scan completes, execute load_stxm_data using the new file path, DO NOT REPEAT THE SCAN WITHOUT EXPLICIT INSTRUCTIONS TO DO SO
        7. display_single_frame, this only generates a PNG file with the image
        8. open the PNG file for viewing using the system image display app
        9. ask the user for next steps
    """

def check_motor_status(axis: str) -> dict:
    """
    Docstring for check_motor_status

    Checks that the requested motor exists and returns basic information from the config.
    
    :param axis: Motor name
    :type axis: str
    :return: Description
    :rtype: dict
    """
    global MOTORS
    if axis not in MOTORS.keys():
        return False
    else:
        return True
    
@mcp.tool()
def define_scan_from_file(file_path: str) -> str:
    """
    Docstring for stxm_scan_from_file.
    Reads an existing stxm file and generates a scan dictionary from its metadata.  This is then submitted
    to the scripter stxm_scan routine to repeat.
    
    :param file_path: path to the existing stxm file
    :type file_path: str
    :return: Description
    :rtype: str
    """

    try:
        SCRIPTER.scan = stxm_utils.scan_from_stxm(file_path)
    except:
        return f"Failed to generate the scan from file {file_path}"
    else:
        return f"Generated a new scan from file {file_path}"

@_hw_tool()
def stxm_scan() -> str:
    """
    TODO:
    1. get_config(), determine the configurations of the previously run scans
    2. update_scan(), sets the scan parameters as desired
    3. confirm the scan configuration with the user
    4. run the scan if requested
    5. load_stxm_data() and display the first frame

    Docstring for stxm_scan.  This executes the scan currently defined in the scripter object S.
    If S.scan is not updated after it is generated by connect_to_server, it will execute the default
    scan parameters.  This will not be useful in general.  It is best to ask if the current scan
    parameters are the desired parameters.  Running update_scan without any arguments returns
    the current scan parameters list.

    Before running this function, it is best to have the user confirm the configuration by reviewing the output
    of update_scan().
    
    :return: Description
    :rtype: str
    """
    try:
        new_scan_file = SCRIPTER.stxm_scan()
    except Exception as e:
        return f"Failed to execute the STXM scan with error: {e}"
    else:
        return f"Completed scan stxm and saved data to {new_scan_file}"

@mcp.tool()
def update_scan(
    scan_type: str = 'Image',
    proposal: str = None,
    experimenters: str = None,
    nx_file_version: float = None,
    sample_description: str = None,
    x_motor: str = None,
    y_motor: str = None,
    z_motor: str = None,
    x_center: float = None,
    y_center: float = None,
    z_center: float = None,
    x_range: float = None,
    y_range: float = None,
    z_range: float = None,
    x_points: int = None,
    y_points: int = None,
    z_points: int = None,
    energy_start: float = None,
    energy_stop: float = None,
    energy_points: int = None,
    dwell: float = None,
    spiral: bool = None,
    autofocus: bool = None,
    defocus: bool = None,
    daq_list: list[str] = None,
    comment: str = None,
    energy_list: list = None,
    retract: bool = None,
    double_exposure: bool = None,
    loop_scan: bool = None
) -> str:
    
    """
    TODO:
    1. get_config(), this returns the configurations for the previously run scans of each scan_type
    2. update_scan(), sets the scan parameters for the desired scan_type using the results from get_config and the function arguments
    3. confirm the scan configuration with the user
    4. run the scan if requested

    Docstring for update_scan.  The parameters listed below are part of the scan definition in scripter.py and can
    be changed upon request.  Any scan defined in the control system configuration can be defined here.  For example,
    to do an OSA x/y image scan, the scan_type will be set to "OSA Image" if that is the name in the configuration and
    the x/y motors will be set to those defined in the config, likely OSA_X/OSA_Y for example.

    At a minimum, the x/y motors must be set according to what is in the configuration for the given scan_type.
    For single and double_motor_scans, the x/y motors can be arbitrarily set and don't need to follow a specific configuration.

    :param proposal: Proposal identifier
    :param experimenters: Names of experimenters
    :param nx_file_version: NeXus file version (default 3.0)
    :param sample_description: Description of the sample
    :param x_motor: X motor name
    :param y_motor: Y motor name
    :param z_motor: Z motor name
    :param x_center: X center position
    :param y_center: Y center position
    :param z_center: Z center position
    :param x_range: X scan range
    :param y_range: Y scan range
    :param z_range: Z scan range
    :param x_points: Number of X points
    :param y_points: Number of Y points
    :param z_points: Number of Z points
    :param energy_start: Starting energy
    :param energy_stop: Stopping energy
    :param energy_points: Number of energy points
    :param dwell: Dwell time in milliseconds
    :param spiral: Enable spiral scan
    :param autofocus: Enable autofocus
    :param defocus: Enable defocus
    :param scan_type: Type of scan
    :param daq_list: List of data acquisition devices
    :param comment: Comment for the scan
    :param energy_list: List of energies
    :param retract: Enable retraction after scan
    """

    global SCRIPTER
    err = _ensure_connected()
    if err:
        return err
    try:
        # The ScanModel requires daq_list to be a list[str]; tolerate a bare
        # string (e.g. "default") by wrapping it so validation does not fail.
        if isinstance(daq_list, str):
            daq_list = [daq_list]
        params = locals()

        # Load the previous scan for scan_type as the baseline
        SCRIPTER.scan = stxm_utils.convert_scan(CONFIG["lastScan"][scan_type])

        # Filter out None values and delegate to scripter.update_scan for validation
        updated_params = {key: value for key, value in params.items() if value is not None}
        return SCRIPTER.update_scan(**updated_params)
    except Exception as e:
        return f"Failed to update scan parameters with error: {e}.  Requested parameters: {locals()}"
    
@mcp.tool()
def get_motor_position(axis: str) -> str:
    """
    Docstring for get_motor_position

    Retrieves the current motor position reading from the pystxmcontrol server.  Requires that the connection is already established.
    
    :param axis: motor name
    :type axis: str
    :return: description of the result
    :rtype: str
    """
    global SCRIPTER
    err = _ensure_connected()
    if err:
        return err
    motor_status = check_motor_status(axis)
    if not motor_status:
        return "Motor status checked failed.  Please confirm the motor list."
    try:
        result = SCRIPTER.get_motor_position(axis)
    except Exception as e:
        return f"Failed to get position for {axis} with error: {e}"
    else:
        return f"Current position for {axis}: {round(result,3)}"
    
@mcp.tool()
def connect_to_server(host: str = None, port: int = None) -> str:
    """
    Docstring for connect_to_server

    Creates a scripter connection to a pystxmcontrol server and retrieves the system configuration.

    Call with NO arguments to use the configured control server (from main.json);
    only pass host/port to override. Do not default to 127.0.0.1 — the real server
    address is resolved automatically.

    :param host: IP address of the server (default: from main.json)
    :type host: str
    :param port: port of the server for commands (default: from main.json)
    :type port: int
    :return: status message
    :rtype: str
    """
    global SCRIPTER, MOTORS, SCANS, POSITIONS, DAQS, CONFIG
    d_host, d_port = _default_server()
    host = host or d_host
    port = port or d_port
    try:
        SCRIPTER = scripter(host, port)
        MOTORS, SCANS, POSITIONS, DAQS, CONFIG = SCRIPTER.get_config()
        motor_count = len(MOTORS) if MOTORS else 0
        motor_list = list(MOTORS.keys())[:5] if MOTORS else []
        safety_instructions = get_safety_instructions()
        return f"Successfully connected to {host}:{port}. Found {motor_count} motors: {', '.join(motor_list)}{'...' if motor_count > 5 else ''}.  Safety instructions: {safety_instructions}"
    except TimeoutError as e:
        return f"Connection timeout to {host}:{port}. The pystxmcontrol server may not be running or responding. Error: {str(e)}"
    except ConnectionError as e:
        return f"Connection error to {host}:{port}. Error: {str(e)}"
    except Exception as e:
        return f"Failed to connect to {host}:{port}. Error: {type(e).__name__}: {str(e)}"

@_hw_tool()
def move_motor(axis: str = None, pos: float = None) -> dict:
    """
    Things to be careful about:
    1. Energy changes of more than 100 eV or so require special consideration.  Ask before moving.
    2. Do not move the OSA_Z motor
    3. Rotation changes of more than 5 degrees require special consideration.  Ask before moving CoarseR.
    
    Move a motor (axis) to the requested position (pos).  The motor must exist in the MOTORS
    config file.  Software limits are checked externally by the control system.  A failure to
    move the move due to system or limit faults will return False.
    Args:
        axis: name of the motor to move
        pos: position to move to
    Returns:
        status: True for success and False for failure
    """
    global MOTORS, SCRIPTER
    err = _ensure_connected()
    if err:
        return err
    motor_status = check_motor_status(axis)
    if not motor_status:
        return "Motor status checked failed.  Please confirm the motor list."
    try:
        response = SCRIPTER.move_motor(axis, pos)
        if response['status']:
            return f"Successfully moved motor {axis} to {pos}"
        else:
            return response['data']
    except Exception as e:
        return f"Failed to communicate with the control server with error: {str(e)}"

# Password secrets must never be echoed back to the model / proxy.  The server
# already strips these, but strip again here as defense-in-depth against an older
# server that still includes them.
_SECRET_KEYS = ("staff_password_hash", "staff_password_salt")


def _strip_secrets(cfg: dict) -> dict:
    """Shallow copy of the main config with staff-password secrets removed."""
    if not isinstance(cfg, dict):
        return cfg
    return {k: v for k, v in cfg.items() if k not in _SECRET_KEYS}


def _motor_summary(motors: dict) -> dict:
    """Compact per-motor view: just the fields needed to plan moves/scans
    (units and travel limits), dropping the ~30 calibration/driver fields."""
    out = {}
    for name, m in (motors or {}).items():
        if not isinstance(m, dict):
            out[name] = m
            continue
        out[name] = {
            "type": m.get("type"),
            "unit": m.get("unit"),
            "min": m.get("minScanValue", m.get("minValue")),
            "max": m.get("maxScanValue", m.get("maxValue")),
            "value": m.get("last value"),
        }
    return out


@mcp.tool()
def get_config(section: str = None) -> str:
    """Returns the control-system configuration.

    The full configuration is large (~50k characters), so by default this
    returns a compact SUMMARY (available scan types, a motor summary with
    units/limits, current positions, and DAQ names).  Request a specific
    section when you need full detail.

    Args:
        section: Which slice to return. One of:
            - None / "summary" (default): compact overview (~5k chars)
            - "scans":     full scan-type templates
            - "motors":    full motor configuration (all calibration fields)
            - "positions": current motor positions
            - "daqs":      full DAQ configuration
            - "lastScan":  last-used parameters per scan type (use these to build update_scan)
            - "config":    main config (minus secrets), including lastScan
            - "all":       everything (minus secrets) — the legacy full dump
    Returns:
        A JSON string for the requested section.
    """
    global SCRIPTER, MOTORS, SCANS, POSITIONS, DAQS, CONFIG
    err = _ensure_connected()
    if err:
        return err
    try:
        MOTORS, SCANS, POSITIONS, DAQS, CONFIG = SCRIPTER.get_config()
        safe_config = _strip_secrets(CONFIG)
        sec = (section or "summary").strip().lower()

        if sec in ("summary", "none"):
            payload = {
                "scan_types": list(SCANS.keys()) if isinstance(SCANS, dict) else SCANS,
                "motors": _motor_summary(MOTORS),
                "positions": POSITIONS,
                "daqs": list(DAQS.keys()) if isinstance(DAQS, dict) else DAQS,
                "hint": ("This is a summary. For full detail call get_config with "
                         "section='scans', 'motors', 'daqs', 'lastScan', 'config', or 'all'."),
            }
        elif sec == "scans":
            payload = SCANS
        elif sec == "motors":
            payload = MOTORS
        elif sec == "positions":
            payload = POSITIONS
        elif sec == "daqs":
            payload = DAQS
        elif sec == "lastscan":
            payload = safe_config.get("lastScan", {}) if isinstance(safe_config, dict) else {}
        elif sec == "config":
            payload = safe_config
        elif sec == "all":
            payload = {
                "motors": MOTORS,
                "scans": SCANS,
                "positions": POSITIONS,
                "daqs": DAQS,
                "config": safe_config,
            }
        else:
            return (f"Unknown section '{section}'. Valid sections: summary, scans, "
                    "motors, positions, daqs, lastScan, config, all.")

        return json.dumps(payload, indent=2)
    except Exception as e:
        return f"Failed to communicate with the control server. Error: {str(e)}"
    
@mcp.tool()
def plot_motor_positions(axis: str, date: str = None, start_date: str = None,
                        end_date: str = None, start_time: str = None,
                        end_time: str = None, file_path: str = None) -> str:
    """
    Plot motor positions over a specific date or time period.
    Plots the position and offset data for the requested axis.
    Requires that the connection to the server is already established and that the database is local.
    The database directory is given by the server in CONFIG.

    You can specify the time range in one of three ways:
    1. Single date: Use 'date' parameter (defaults to today)
    2. Date range: Use 'start_date' and 'end_date' parameters (format: YYYY-MM-DD)
    3. Time range: Use 'start_time' and 'end_time' parameters
       - Format: "YYYY-MM-DD HH:MM:SS" (e.g., "2026-01-09 14:30:00")
       - Also accepts Unix timestamps as strings (e.g., "1736420394")

    Priority: time range > date range > single date

    :param axis: Motor name
    :type axis: str
    :param date: Single date to plot (YYYY-MM-DD). Ignored if start_date/end_date or start_time/end_time provided.
    :type date: str
    :param start_date: Start date for time period (YYYY-MM-DD)
    :type start_date: str
    :param end_date: End date for time period (YYYY-MM-DD)
    :type end_date: str
    :param start_time: Start time (YYYY-MM-DD HH:MM:SS or Unix timestamp string)
    :type start_time: str
    :param end_time: End time (YYYY-MM-DD HH:MM:SS or Unix timestamp string)
    :type end_time: str
    :param file_path: File to save the plot as an image
    :type file_path: str
    :return: file path where the plot was saved
    :rtype: str
    """
    from datetime import datetime

    if file_path is None:
        file_path = f"/tmp/{axis}_position_plot.png"
    db_base_dir = CONFIG["server"]["data_dir"]

    # Convert start_time and end_time strings to timestamps if provided
    start_timestamp = None
    end_timestamp = None

    if start_time is not None:
        try:
            # Try parsing as Unix timestamp first
            start_timestamp = float(start_time)
        except ValueError:
            # Try parsing as datetime string
            try:
                dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
                start_timestamp = dt.timestamp()
            except ValueError:
                return f"Invalid start_time format: {start_time}. Use 'YYYY-MM-DD HH:MM:SS' or Unix timestamp"

    if end_time is not None:
        try:
            # Try parsing as Unix timestamp first
            end_timestamp = float(end_time)
        except ValueError:
            # Try parsing as datetime string
            try:
                dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
                end_timestamp = dt.timestamp()
            except ValueError:
                return f"Invalid end_time format: {end_time}. Use 'YYYY-MM-DD HH:MM:SS' or Unix timestamp"

    try:
        img_path = stxm_utils.plot_motor_positions(
            axis,
            date=date,
            start_date=start_date,
            end_date=end_date,
            start_time=start_timestamp,
            end_time=end_timestamp,
            db_base_dir=db_base_dir,
            file_path=file_path
        )
        # If img_path is an error message (no data found), return it
        if img_path and "No data found" in img_path:
            return img_path
        # Otherwise return the file path
        return img_path if img_path else f"Failed to generate plot for {axis}"
    except Exception as e:
        return f"Error generating plot: {str(e)}"



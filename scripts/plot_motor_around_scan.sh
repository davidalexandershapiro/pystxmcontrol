#!/bin/bash
# Plot a motor's logged positions in a window around a scan's start time.
# Reads the scan start time from the .stxm file, then queries the OperationLogger
# database for the requested motor over [start - N min, start + N min].
#
# Usage: ./plot_motor_around_scan.sh <scan_file> <motor_name> <minutes> [--save path]
#
# Arguments:
#   scan_file:  Required. Path to the .stxm scan file.
#   motor_name: Required. Motor to plot (e.g., SampleX, Energy).
#   minutes:    Required. Window (in minutes) BEFORE and AFTER the scan start time.
#   --save:     Optional. Path to save the plot image instead of displaying it.
#
# Examples:
#   ./plot_motor_around_scan.sh /data/.../scan123.stxm SampleX 5
#   ./plot_motor_around_scan.sh /data/.../scan123.stxm Energy 10 --save /tmp/plot.png

set -e  # Exit on error

if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
    echo "Error: scan_file, motor_name and minutes are all required"
    echo "Usage: $0 <scan_file> <motor_name> <minutes> [--save path]"
    echo "Example: $0 /data/scan123.stxm SampleX 5"
    exit 1
fi

SCAN_FILE="$1"
MOTOR_NAME="$2"
MINUTES="$3"
SAVE_PATH=""
SHOW="True"

shift 3
if [ "$1" == "--save" ] && [ -n "$2" ]; then
    SAVE_PATH="$2"
    SHOW="False"
fi

if [ ! -f "$SCAN_FILE" ]; then
    echo "Error: scan file not found: $SCAN_FILE"
    exit 1
fi

# Find the main.json config file (same locations as plot_motor_positions.sh)
CONFIG_PATHS=(
    "/opt/miniconda3/envs/stxm/pystxmcontrol_cfg/main.json"
    "$HOME/.config/pystxmcontrol/main.json"
    "/etc/pystxmcontrol/main.json"
    "$CONDA_PREFIX/pystxmcontrol_cfg/main.json"
)

CONFIG_FILE=""
for path in "${CONFIG_PATHS[@]}"; do
    if [ -f "$path" ]; then
        CONFIG_FILE="$path"
        break
    fi
done

if [ -z "$CONFIG_FILE" ]; then
    echo "Error: Could not find main.json config file"
    echo "Searched in:"
    for path in "${CONFIG_PATHS[@]}"; do
        echo "  - $path"
    done
    exit 1
fi

echo "Using config file: $CONFIG_FILE"

# Extract data_dir from main.json
DATA_DIR=$(python3 -c "
import json, sys
try:
    with open('$CONFIG_FILE', 'r') as f:
        config = json.load(f)
    data_dir = config.get('server', {}).get('data_dir')
    if data_dir:
        print(data_dir)
    else:
        sys.exit(1)
except Exception as e:
    print(f'Error reading config: {e}', file=sys.stderr)
    sys.exit(1)
")

if [ -z "$DATA_DIR" ]; then
    echo "Error: Could not extract data_dir from $CONFIG_FILE"
    exit 1
fi

echo "Database directory: $DATA_DIR/pystxmcontrol_data"

PYTHON_SCRIPT=$(cat <<'EOF'
import sys
from datetime import datetime
import h5py
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pystxmcontrol.controller.operation_logger import OperationLogger

scan_file  = sys.argv[1]
motor_name = sys.argv[2]
minutes    = float(sys.argv[3])
data_dir   = sys.argv[4]
save_path  = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else None
show       = (sys.argv[6] == "True") if len(sys.argv) > 6 else True

if save_path:
    matplotlib.use("Agg")


def _h5str(val):
    """Return a plain str from an h5py scalar that may be bytes/str/array."""
    if isinstance(val, (list,)):
        val = val[0]
    try:
        import numpy as np
        if isinstance(val, np.ndarray):
            val = val.flat[0]
    except Exception:
        pass
    if isinstance(val, bytes):
        return val.decode()
    return str(val)


def _parse_time(s):
    """Parse the scan start_time string into an epoch timestamp."""
    s = s.strip()
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt).timestamp()
            except ValueError:
                continue
    raise ValueError(f"Could not parse scan start_time: {s!r}")


# Read scan start time from the file
try:
    with h5py.File(scan_file, "r") as f:
        start_str = _h5str(f["entry0/start_time"][()])
except Exception as e:
    print(f"Error reading start_time from {scan_file}: {e}", file=sys.stderr)
    sys.exit(1)

t0 = _parse_time(start_str)
window = minutes * 60.0
t_start, t_end = t0 - window, t0 + window
print(f"Scan start: {start_str}  (epoch {t0:.0f})")
print(f"Window: +/- {minutes:g} min  [{datetime.fromtimestamp(t_start)} .. {datetime.fromtimestamp(t_end)}]")

# Query motor positions over the window
logger = OperationLogger(db_path=data_dir, readonly=True)
results = logger.query_motor_positions(
    motor_name=motor_name, start_time=t_start, end_time=t_end, limit=1000000,
)
results = [r for r in results if r.get("actual_position") is not None]
results.sort(key=lambda r: r["timestamp"])

if not results:
    print(f"No logged positions for motor '{motor_name}' in the window.")
    sys.exit(1)

times = [datetime.fromtimestamp(r["timestamp"]) for r in results]
positions = [r["actual_position"] for r in results]

fig, ax = plt.subplots(figsize=(12, 6))
ax.plot(times, positions, "s-", markersize=3, alpha=0.7, label="Actual Position")
ax.axvline(datetime.fromtimestamp(t0), color="red", linestyle="--",
           linewidth=1.5, label="Scan start")

ax.set_xlabel("Time", fontsize=12)
ax.set_ylabel("Position", fontsize=12)
ax.set_title(f"{motor_name} positions +/- {minutes:g} min around scan start",
             fontsize=14, fontweight="bold")
ax.legend()
ax.grid(True, alpha=0.3)

stats = (f"Readings: {len(results)} | "
         f"Range: {min(positions):.3f} - {max(positions):.3f}")
ax.text(0.02, 0.98, stats, transform=ax.transAxes, verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))

locator = mdates.AutoDateLocator()
ax.xaxis.set_major_locator(locator)
ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
plt.xticks(rotation=45)
plt.tight_layout()

if save_path:
    plt.savefig(save_path, dpi=150)
    print(f"Plot saved to: {save_path}")
if show:
    plt.show()
EOF
)

python3 -c "$PYTHON_SCRIPT" "$SCAN_FILE" "$MOTOR_NAME" "$MINUTES" "$DATA_DIR" "$SAVE_PATH" "$SHOW"

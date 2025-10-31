#!/bin/bash
# Script to plot motor moves using OperationLogger
# Usage: ./plot_motor_moves.sh <motor_name> [date] [--save path]
#
# Arguments:
#   motor_name: Required. Name of the motor to plot (e.g., SampleX, Energy)
#   date: Optional. Date in YYYY-MM-DD format (defaults to today)
#   --save: Optional. Path to save the plot image
#
# Examples:
#   ./plot_motor_moves.sh SampleX
#   ./plot_motor_moves.sh Energy 2025-10-27
#   ./plot_motor_moves.sh SampleX 2025-10-27 --save /tmp/plot.png

set -e  # Exit on error

# Check if motor name is provided
if [ -z "$1" ]; then
    echo "Error: Motor name is required"
    echo "Usage: $0 <motor_name> [date] [--save path]"
    echo "Example: $0 SampleX 2025-10-27"
    exit 1
fi

MOTOR_NAME="$1"
DATE="${2:-}"  # Optional date, defaults to empty (will use today)
SAVE_PATH=""
SHOW="True"

# Parse remaining arguments for --save option
shift
if [ $# -gt 0 ]; then
    if [ "$1" != "--save" ] && [ -n "$1" ]; then
        # Second argument is date
        DATE="$1"
        shift
    fi
fi

if [ $# -ge 2 ] && [ "$1" == "--save" ]; then
    SAVE_PATH="$2"
    SHOW="False"
    shift 2
fi

# Find the main.json config file
# Try common locations
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

# Extract data_dir from main.json using Python
DATA_DIR=$(python3 -c "
import json
import sys

try:
    with open('$CONFIG_FILE', 'r') as f:
        config = json.load(f)
    data_dir = config.get('server', {}).get('data_dir')
    if data_dir:
        print(data_dir)
    else:
        print('', file=sys.stderr)
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

# Create Python script to plot motor moves
PYTHON_SCRIPT=$(cat <<'EOF'
import sys
from pystxmcontrol.controller.operation_logger import OperationLogger

# Get arguments
motor_name = sys.argv[1]
data_dir = sys.argv[2]
date_str = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
save_path = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
show = sys.argv[5] == "True" if len(sys.argv) > 5 else True

# Create logger instance
logger = OperationLogger(db_path=data_dir, readonly=True)

# Plot motor moves
try:
    fig = logger.plot_motor_moves(
        motor_name=motor_name,
        date=date_str,
        show=show,
        save_path=save_path
    )

    if fig is None:
        print(f"No data found for motor '{motor_name}' on {date_str if date_str else 'today'}")
        sys.exit(1)
    else:
        if save_path:
            print(f"Plot saved to: {save_path}")
        else:
            print(f"Displaying plot for motor '{motor_name}'...")
        sys.exit(0)

except Exception as e:
    print(f"Error plotting motor moves: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
EOF
)

# Run the Python script
python3 -c "$PYTHON_SCRIPT" "$MOTOR_NAME" "$DATA_DIR" "$DATE" "$SAVE_PATH" "$SHOW"

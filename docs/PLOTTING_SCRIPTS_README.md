# Operation Logger Plotting Scripts

These bash scripts provide convenient command-line access to the OperationLogger plotting functionality. They automatically locate the database by reading the configuration from `main.json`.

## Available Scripts

### 1. `plot_motor_positions.sh`
Plots motor positions over time for a given day.

**Usage:**
```bash
./plot_motor_positions.sh <motor_name> [date] [--save path]
```

**Arguments:**
- `motor_name`: Required. Name of the motor to plot (e.g., SampleX, SampleY, Energy, ZonePlateZ)
- `date`: Optional. Date in YYYY-MM-DD format (defaults to today)
- `--save path`: Optional. Path to save the plot image (if not provided, displays interactively)

**Examples:**
```bash
# Plot SampleX positions for today
./plot_motor_positions.sh SampleX

# Plot Energy positions for a specific date
./plot_motor_positions.sh Energy 2025-10-27

# Plot and save to file
./plot_motor_positions.sh SampleX 2025-10-27 --save /tmp/samplex_positions.png
```

**Output:**
- Timeline of motor positions throughout the day
- Motor offset values (if available)
- Statistics: number of readings, position range

---

### 2. `plot_motor_moves.sh`
Plots motor move commands over time for a given day.

**Usage:**
```bash
./plot_motor_moves.sh <motor_name> [date] [--save path]
```

**Arguments:**
- `motor_name`: Required. Name of the motor to plot
- `date`: Optional. Date in YYYY-MM-DD format (defaults to today)
- `--save path`: Optional. Path to save the plot image

**Examples:**
```bash
# Plot SampleX moves for today
./plot_motor_moves.sh SampleX

# Plot Energy moves for a specific date
./plot_motor_moves.sh Energy 2025-10-27

# Plot and save to file
./plot_motor_moves.sh ZonePlateZ 2025-10-27 --save /tmp/zoneplate_moves.png
```

**Output:**
- Target vs actual positions over time
- Failed moves marked with red X
- Statistics: total moves, position range, failure count

---

### 3. `plot_commands.sh`
Plots server command activity for a given day.

**Usage:**
```bash
./plot_commands.sh [date] [--save path]
```

**Arguments:**
- `date`: Optional. Date in YYYY-MM-DD format (defaults to today)
- `--save path`: Optional. Path to save the plot image

**Examples:**
```bash
# Plot command activity for today
./plot_commands.sh

# Plot command activity for a specific date
./plot_commands.sh 2025-10-27

# Plot and save to file
./plot_commands.sh 2025-10-27 --save /tmp/commands.png
```

**Output:**
- Timeline showing when each command type was executed
- Bar chart showing distribution of command types
- Statistics: total commands, success count, failure count

---

## Configuration

The scripts automatically search for `main.json` in the following locations (in order):
1. `/opt/miniconda3/envs/stxm/pystxmcontrol_cfg/main.json`
2. `$HOME/.config/pystxmcontrol/main.json`
3. `/etc/pystxmcontrol/main.json`
4. `$CONDA_PREFIX/pystxmcontrol_cfg/main.json`

The database path is read from `server.data_dir` in the configuration file.

## Requirements

- Python 3 with pystxmcontrol installed
- matplotlib (for plotting)
- Access to the operation logger database

## Database Location

The operation logger database files are stored in:
```
{data_dir}/pystxmcontrol_data/operations_YYYY-MM.db
```

Where `{data_dir}` is specified in `main.json` under `server.data_dir`.

## Error Handling

If no data is found for the specified motor or date, the script will:
1. Display an informative message
2. Exit with status code 1

If the configuration file cannot be found or the database directory is invalid, the script will:
1. Display which paths were searched
2. Exit with an error message

## Interactive vs. Saved Plots

By default, plots are displayed interactively using matplotlib's viewer. Use the `--save` option to save plots to a file instead (PNG, PDF, SVG formats supported based on file extension).

When using `--save`, the plot window will not be displayed, making it suitable for automated/batch processing.

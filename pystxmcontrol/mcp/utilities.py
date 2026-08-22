import sqlite3
import asyncio
import time
import json
import os
import threading
from datetime import datetime, timedelta
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pystxm_core.io.stxm_reader import read_stxm_stack

def scan_from_stxm(stxm_file: str) -> dict:
    stack = read_stxm_stack(stxm_file)
    scan = {"proposal": stack.metadata["title"], 
            "experimenters":stack.metadata["experimenters"], 
            "scan_type": stack.metadata["scan_type"],
            "x_motor": stack.metadata["x_motor"],
            "y_motor": stack.metadata["y_motor"],
            "z_motor": None,
            "nx_file_version":stack.metadata["version"],
            "x_center": sum(stack.metadata["x_positions"])/len(stack.metadata["x_positions"]),
            "y_center": sum(stack.metadata["y_positions"])/len(stack.metadata["y_positions"]),
            "x_range": max(stack.metadata["x_positions"])-min(stack.metadata["x_positions"]),
            "y_range": max(stack.metadata["y_positions"])-min(stack.metadata["y_positions"]),
            "x_points": len(stack.metadata["x_positions"]),
            "y_points": len(stack.metadata["y_positions"]),
            "z_center": 0,
            "z_range": 0,
            "z_points": 1,
            "energy_list": stack.energies.tolist(),
            "dwell": stack.images[0].dwell,
            "defocus": False,
            "double_exposure": False,
            "spiral": False,
            "autofocus": True,
            "daq_list": stack.metadata["detectors"],
            "comment": stack.metadata["comment"],
            "sample_description": stack.metadata["sample_description"],
            "loop_scan": False,
            "retract": True}
    return scan

def convert_scan(scan: dict) -> dict:
    scan = {
        'scan_type': scan['scan_type'],
        'proposal': scan['proposal'],
        'experimenters': scan['experimenters'],
        'nx_file_version': float(scan.get('nx_file_version') or 3),
        'sample_description': scan['sample'],
        'x_motor': scan['x_motor'],
        'y_motor': scan['y_motor'],
        'z_motor': scan.get('z_motor',None),
        'x_center': scan['scan_regions']['Region1']['xCenter'],
        'y_center': scan['scan_regions']['Region1']['yCenter'],
        'z_center': scan['scan_regions']['Region1']['zCenter'],
        'x_range': scan['scan_regions']['Region1']['xRange'],
        'y_range': scan['scan_regions']['Region1']['yRange'],
        'z_range': scan['scan_regions']['Region1']['zRange'],
        'x_points': scan['scan_regions']['Region1']['xPoints'],
        'y_points': scan['scan_regions']['Region1']['yPoints'],
        'z_points': scan['scan_regions']['Region1']['zPoints'],
        'energy_start': scan['energy_regions']['EnergyRegion1']['start'],
        'energy_stop': scan['energy_regions']['EnergyRegion1']['stop'],
        'energy_points': scan['energy_regions']['EnergyRegion1']['n_energies'],
        'dwell': scan['energy_regions']['EnergyRegion1']['dwell'],
        'spiral': scan.get('spiral',False),
        'autofocus': scan.get('autofocus',True),
        'defocus': scan.get('defocus',False),
        'daq_list': scan.get('daq_list',['default']),
        'comment': scan.get('comment',''),
        'energy_list': scan.get('energy_list',None),
        'retract': scan.get('retract',True),
        'double_exposure': False,
        'loop_scan': False
    }
    return scan

def _get_db_directory(db_base_dir):
    """Get database directory"""
    import sys
    db_dir = os.path.join(db_base_dir, 'pystxmcontrol_data')
    os.makedirs(db_dir, exist_ok=True)
    return db_dir

def _get_monthly_db_path(date=None,db_base_dir=None):
    """
    Get database path for a specific month

    :param date: datetime object or None for current month
    :return: Path to monthly database file
    """
    if date is None:
        date = datetime.now()
    elif isinstance(date, str):
        date = datetime.strptime(date, '%Y-%m-%d')

    month_str = date.strftime('%Y-%m')
    return os.path.join(_get_db_directory(db_base_dir), f'operations_{month_str}.db')

def _get_db_files_for_range(start_time, end_time, db_base_dir):
    """
    Get list of database files covering a time range

    :param start_time: Start timestamp
    :param end_time: End timestamp
    :return: List of (db_path, start_ts, end_ts) tuples
    """

    start_date = datetime.fromtimestamp(start_time)
    end_date = datetime.fromtimestamp(end_time)

    db_files = []
    current_date = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    while current_date <= end_date:
        # Get month boundaries
        month_start = current_date
        if current_date.month == 12:
            month_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(seconds=1)
        else:
            month_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(seconds=1)

        # Calculate effective range for this DB
        effective_start = max(start_time, month_start.timestamp())
        effective_end = min(end_time, month_end.timestamp())

        db_path = _get_monthly_db_path(current_date,db_base_dir)

        # Only include if file exists
        if os.path.exists(db_path):
            db_files.append((db_path, effective_start, effective_end))

        # Move to next month
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)

    return db_files

def query_motor_positions(motor_name=None, start_time=None, end_time=None, limit=100, db_base_dir=None):
    """
    Query motor positions from database(s) - works across monthly rotation

    :param motor_name: Filter by motor name (None for all)
    :param start_time: Start timestamp (None for all)
    :param end_time: End timestamp (None for all)
    :param limit: Maximum number of results
    :return: List of motor position records
    """
    # Default to recent data if no time range specified
    if start_time is None and end_time is None:
        end_time = time.time()
        start_time = end_time - (24 * 3600)  # Last 24 hours
    elif start_time is None:
        start_time = 0
    elif end_time is None:
        end_time = time.time()

    # Get relevant database files
    db_files = _get_db_files_for_range(start_time, end_time, db_base_dir)
    all_results = []
    for db_path, db_start, db_end in db_files:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM motor_positions WHERE 1=1"
        params = []

        if motor_name:
            query += " AND motor_name = ?"
            params.append(motor_name)

        query += " AND timestamp >= ? AND timestamp <= ?"
        params.append(db_start)
        params.append(db_end)

        query += " ORDER BY timestamp DESC"

        cursor.execute(query, params)
        all_results.extend([dict(row) for row in cursor.fetchall()])
        conn.close()

    # Sort combined results and apply limit
    all_results.sort(key=lambda x: x['timestamp'], reverse=True)
    return all_results[:limit]

def plot_motor_positions(motor_name, date=None, start_date=None, end_date=None,
                         start_time=None, end_time=None, db_base_dir=None, file_path=None):
    """
    Plot motor positions over a given day or time period

    :param motor_name: Name of the motor to plot
    :param date: Date to plot (datetime object or 'YYYY-MM-DD' string). If None, uses today.
                 Ignored if start_date/end_date or start_time/end_time are provided.
    :param start_date: Start date for time period (datetime object or 'YYYY-MM-DD' string)
    :param end_date: End date for time period (datetime object or 'YYYY-MM-DD' string)
    :param start_time: Start timestamp (float) for time period
    :param end_time: End timestamp (float) for time period
    :param db_base_dir: Base directory for database files
    :param file_path: Path to save the plot image (optional)
    :return: file path if file_path is provided, otherwise matplotlib figure object
    """
    # Determine time range - priority: timestamps > date range > single date
    if start_time is not None and end_time is not None:
        # Use provided timestamps
        start_timestamp = start_time
        end_timestamp = end_time
        start_datetime = datetime.fromtimestamp(start_timestamp)
        end_datetime = datetime.fromtimestamp(end_timestamp)
        date_label = f"{start_datetime.date()} to {end_datetime.date()}"
    elif start_date is not None and end_date is not None:
        # Use provided date range
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        elif isinstance(start_date, datetime):
            start_date = start_date.date()

        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
        elif isinstance(end_date, datetime):
            end_date = end_date.date()

        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.max.time())
        start_timestamp = start_datetime.timestamp()
        end_timestamp = end_datetime.timestamp()
        date_label = f"{start_date} to {end_date}"
    else:
        # Use single date (default to today)
        if date is None:
            date = datetime.now().date()
        elif isinstance(date, str):
            date = datetime.strptime(date, '%Y-%m-%d').date()
        elif isinstance(date, datetime):
            date = date.date()

        # Get start and end timestamps for the day
        start_datetime = datetime.combine(date, datetime.min.time())
        end_datetime = datetime.combine(date, datetime.max.time())
        start_timestamp = start_datetime.timestamp()
        end_timestamp = end_datetime.timestamp()
        date_label = str(date)

    # Query motor positions for the day (uses multi-month query)
    results = query_motor_positions(
        motor_name=motor_name,
        start_time=start_timestamp,
        end_time=end_timestamp,
        limit=100000,  # High limit for full day
        db_base_dir=db_base_dir
    )

    # Sort by timestamp ascending for plotting
    results.sort(key=lambda x: x['timestamp'])

    if not results:
        error_msg = f"No data found for motor '{motor_name}' for {date_label}"
        print(error_msg)
        return error_msg

    # Extract data for plotting
    timestamps = [datetime.fromtimestamp(r['timestamp']) for r in results]
    actual_positions = [r['actual_position'] for r in results if r['actual_position'] is not None]
    motor_offsets = [r.get('motor_offset') for r in results]

    # Check if we have offset data
    has_offsets = any(o is not None for o in motor_offsets)

    # Create figure with subplots if we have offset data
    if has_offsets:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
    else:
        fig, ax1 = plt.subplots(figsize=(12, 6))

    # Plot actual positions
    ax1.plot(timestamps, actual_positions, 's-', label='Actual Position',
            markersize=3, alpha=0.7)

    # Formatting for position plot
    ax1.set_ylabel('Position', fontsize=12)
    if not has_offsets:
        ax1.set_xlabel('Time', fontsize=12)
    ax1.set_title(f'{motor_name} Positions - {date_label}', fontsize=14, fontweight='bold')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Add statistics for positions
    stats_text = f'Readings: {len(results)} | Range: {min(actual_positions):.3f} - {max(actual_positions):.3f}'
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes,
            verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    # Plot motor offsets if available
    if has_offsets:
        # Filter out None values for plotting
        offset_times = [timestamps[i] for i, o in enumerate(motor_offsets) if o is not None]
        offset_values = [o for o in motor_offsets if o is not None]

        ax2.plot(offset_times, offset_values, 'o-', label='Motor Offset',
                markersize=3, alpha=0.7, color='orange')

        # Formatting for offset plot
        ax2.set_xlabel('Time', fontsize=12)
        ax2.set_ylabel('Offset', fontsize=12)
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        # Add statistics for offsets
        if offset_values:
            offset_stats = f'Offset Range: {min(offset_values):.3f} - {max(offset_values):.3f}'
            ax2.text(0.02, 0.98, offset_stats, transform=ax2.transAxes,
                    verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    # Format x-axis as time (on bottom plot if we have offsets, otherwise on main plot)
    axis_for_time = ax2 if has_offsets else ax1
    axis_for_time.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    axis_for_time.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45)

    plt.tight_layout()

    # Save if requested
    if file_path:
        plt.savefig(file_path, dpi=150)
        return file_path
    else:
        plt.show()
        return fig

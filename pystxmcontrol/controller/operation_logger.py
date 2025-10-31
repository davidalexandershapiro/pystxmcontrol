"""
Operation Logger for pystxmcontrol

Logs motor moves and scan operations to SQLite database with minimal overhead.
Uses async queue pattern to avoid blocking motor operations.
"""

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


class OperationLogger:
    def __init__(self, db_path=None, logger=None, readonly=True):
        """
        Initialize operation logger with SQLite database

        :param db_path: Path to SQLite database file. If None, uses monthly rotation.
        :param logger: Optional external logger for error reporting
        """
        self._logger = logger
        self._readonly = readonly
        self.use_monthly_rotation = (db_path is None)

        if self.use_monthly_rotation:
            # Use default system location
            self.db_base_dir = self._get_default_db_directory()
            self.db_path = self._get_monthly_db_path()
        else:
            # User provided a custom base directory
            self.db_base_dir = db_path
            self.db_path = self._get_monthly_db_path()

        self.log_queue = None
        self.writer_task = None
        self.writer_thread = None
        self.running = False

        # Create database and tables
        if not self._readonly:
            self._create_database()

    def _get_db_directory(self):
        """Get database directory"""
        import sys
        db_dir = os.path.join(self.db_base_dir, 'pystxmcontrol_data')
        os.makedirs(db_dir, exist_ok=True)
        return db_dir

    def _get_monthly_db_path(self, date=None):
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
        return os.path.join(self._get_db_directory(), f'operations_{month_str}.db')

    def _create_database(self, db_path=None):
        """
        Create database schema if it doesn't exist

        :param db_path: Optional specific database path (for creating historical DBs)
        """
        if db_path is None:
            db_path = self.db_path
        print(f"[Logger] database path: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Enable WAL mode for better write concurrency
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA cache_size=-64000')  # 64MB cache

        # Motor positions table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS motor_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                datetime TEXT NOT NULL,
                motor_name TEXT NOT NULL,
                actual_position REAL,
                motor_offset REAL,
                error_message TEXT
            )
        ''')

        # Create index on timestamp for faster queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_motor_positions_timestamp
            ON motor_positions(timestamp)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_motor_positions_motor
            ON motor_positions(motor_name, timestamp)
        ''')

        # Motor moves table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS motor_moves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                datetime TEXT NOT NULL,
                motor_name TEXT NOT NULL,
                target_position REAL NOT NULL,
                actual_position REAL,
                duration REAL,
                success BOOLEAN,
                error_message TEXT
            )
        ''')

        # Create index on timestamp for faster queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_motor_moves_timestamp
            ON motor_moves(timestamp)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_motor_moves_motor
            ON motor_moves(motor_name, timestamp)
        ''')

        # Scans table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                datetime TEXT NOT NULL,
                scan_id TEXT,
                scan_type TEXT,
                parameters TEXT,
                file_path TEXT,
                duration REAL,
                status TEXT,
                error_message TEXT
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_scans_timestamp
            ON scans(timestamp)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_scans_scan_id
            ON scans(scan_id)
        ''')

        # Commands table - logs all commands processed by server
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                datetime TEXT NOT NULL,
                command TEXT NOT NULL,
                parameters TEXT,
                status BOOLEAN,
                mode TEXT,
                error_message TEXT,
                duration REAL
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_commands_timestamp
            ON commands(timestamp)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_commands_command
            ON commands(command, timestamp)
        ''')

        conn.commit()
        conn.close()

        if self._logger and db_path == self.db_path:
            self._logger.log(f"Operation logger database initialized: {db_path}", level="info")

    def _get_db_files_for_range(self, start_time, end_time):
        """
        Get list of database files covering a time range

        :param start_time: Start timestamp
        :param end_time: End timestamp
        :return: List of (db_path, start_ts, end_ts) tuples
        """
        if not self.use_monthly_rotation:
            # Single database covers everything
            return [(self.db_path, start_time, end_time)]

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

            db_path = self._get_monthly_db_path(current_date)

            # Only include if file exists
            if os.path.exists(db_path):
                db_files.append((db_path, effective_start, effective_end))

            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

        return db_files

    def start(self):
        """Start the async logging writer task"""
        if self.running or self._readonly:
            return

        self.running = True
        self.log_queue = asyncio.Queue()

        # Run writer in a separate thread with its own event loop
        def run_writer():
            asyncio.run(self._log_writer())

        self.writer_thread = threading.Thread(target=run_writer, daemon=True)
        self.writer_thread.start()

        if self._logger:
            self._logger.log("Operation logger started", level="info")

    def stop(self):
        """Stop the async logging writer task"""
        if not self.running or self._readonly:
            return

        self.running = False

        # Signal writer to stop by adding sentinel value
        if self.log_queue is not None:
            try:
                self.log_queue.put_nowait(None)
            except:
                pass

        # Wait for writer thread to finish
        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=2)

        if self._logger:
            self._logger.log("Operation logger stopped", level="info")

    async def _log_writer(self):
        """Background task that writes log entries to database"""
        if self._readonly:
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        batch = []
        batch_size = 10
        last_commit = time.time()
        commit_interval = 1.0  # Commit at least every second

        try:
            while self.running:
                try:
                    # Wait for log entry with timeout
                    entry = await asyncio.wait_for(self.log_queue.get(), timeout=0.1)

                    if entry is None:  # Shutdown signal
                        break

                    batch.append(entry)

                    # Commit if batch is full or enough time has passed
                    if len(batch) >= batch_size or (time.time() - last_commit) > commit_interval:
                        self._write_batch(cursor, batch)
                        conn.commit()
                        batch = []
                        last_commit = time.time()

                except asyncio.TimeoutError:
                    # Timeout - commit any pending entries
                    if batch:
                        self._write_batch(cursor, batch)
                        conn.commit()
                        batch = []
                        last_commit = time.time()
                    continue

        finally:
            # Write any remaining entries
            if batch:
                self._write_batch(cursor, batch)
                conn.commit()
            conn.close()

    def _write_batch(self, cursor, batch):
        """Write a batch of log entries to database"""
        if self._readonly:
            return
        for entry in batch:
            try:
                if entry['type'] == 'motor_move':
                    cursor.execute('''
                        INSERT INTO motor_moves
                        (timestamp, datetime, motor_name, target_position,
                         actual_position, duration, success, error_message)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        entry['timestamp'],
                        entry['datetime'],
                        entry['motor_name'],
                        entry['target_position'],
                        entry.get('actual_position'),
                        entry.get('duration'),
                        entry.get('success', True),
                        entry.get('error_message')
                    ))

                elif entry['type'] == 'scan':
                    cursor.execute('''
                        INSERT INTO scans
                        (timestamp, datetime, scan_id, scan_type, parameters,
                         file_path, duration, status, error_message)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        entry['timestamp'],
                        entry['datetime'],
                        entry.get('scan_id'),
                        entry.get('scan_type'),
                        json.dumps(entry.get('parameters', {})),
                        entry.get('file_path'),
                        entry.get('duration'),
                        entry.get('status', 'started'),
                        entry.get('error_message')
                    ))

                elif entry['type'] == 'motor_position':
                    cursor.execute('''
                        INSERT INTO motor_positions
                        (timestamp, datetime, motor_name,
                         actual_position, motor_offset, error_message)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        entry['timestamp'],
                        entry['datetime'],
                        entry['motor_name'],
                        entry.get('actual_position'),
                        entry.get('motor_offset'),
                        entry.get('error_message')
                    ))

                elif entry['type'] == 'command':
                    cursor.execute('''
                        INSERT INTO commands
                        (timestamp, datetime, command, parameters,
                         status, mode, error_message, duration)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        entry['timestamp'],
                        entry['datetime'],
                        entry['command'],
                        json.dumps(entry.get('parameters', {})),
                        entry.get('status'),
                        entry.get('mode'),
                        entry.get('error_message'),
                        entry.get('duration')
                    ))

            except Exception as e:
                if self._logger:
                    self._logger.log(f"Error writing log entry: {e}", level="error")

    def log_motor_move(self, motor_name, target_position, actual_position=None,
                       duration=None, success=True, error_message=None):
        """
        Log a motor move operation (non-blocking)

        :param motor_name: Name of the motor
        :param target_position: Requested position
        :param actual_position: Final position (if available)
        :param duration: Time taken for move in seconds
        :param success: Whether move succeeded
        :param error_message: Error message if failed
        """
        if not self.running or self.log_queue is None or self._readonly:
            return

        entry = {
            'type': 'motor_move',
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat(),
            'motor_name': motor_name,
            'target_position': target_position,
            'actual_position': actual_position,
            'duration': duration,
            'success': success,
            'error_message': error_message
        }

        # Non-blocking queue put
        try:
            self.log_queue.put_nowait(entry)
        except asyncio.QueueFull:
            if self._logger:
                self._logger.log("Log queue full, dropping entry", level="warning")

    def log_motor_position(self, motor_name, actual_position, motor_offset = None, error_message=None):
        """
        Log a motor move operation (non-blocking)

        :param motor_name: Name of the motor
        :param actual_position: Final position (if available)
        :param error_message: Error message if failed
        """
        if not self.running or self.log_queue is None or self._readonly:
            return

        entry = {
            'type': 'motor_position',
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat(),
            'motor_name': motor_name,
            'actual_position': actual_position,
            'motor_offset': motor_offset,
            'error_message': error_message
        }

        # Non-blocking queue put
        try:
            self.log_queue.put_nowait(entry)
        except asyncio.QueueFull:
            if self._logger:
                self._logger.log("Log queue full, dropping entry", level="warning")

    def log_scan_start(self, scan_id, scan_type, parameters):
        """
        Log scan start (non-blocking)

        :param scan_id: Unique scan identifier
        :param scan_type: Type of scan (e.g., 'line_image', 'ptychography')
        :param parameters: Dictionary of scan parameters
        """
        if not self.running or self.log_queue is None or self._readonly:
            return

        entry = {
            'type': 'scan',
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat(),
            'scan_id': scan_id,
            'scan_type': scan_type,
            'parameters': parameters,
            'status': 'started'
        }

        try:
            self.log_queue.put_nowait(entry)
        except asyncio.QueueFull:
            if self._logger:
                self._logger.log("Log queue full, dropping entry", level="warning")

    def log_scan_end(self, scan_id, scan_type, parameters, file_path=None,
                     duration=None, status='completed', error_message=None):
        """
        Log scan completion (non-blocking)

        :param scan_id: Unique scan identifier
        :param scan_type: Type of scan
        :param parameters: Dictionary of scan parameters
        :param file_path: Path to output data file
        :param duration: Total scan duration in seconds
        :param status: 'completed', 'aborted', or 'failed'
        :param error_message: Error message if failed
        """
        if not self.running or self.log_queue is None or self._readonly:
            return

        entry = {
            'type': 'scan',
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat(),
            'scan_id': scan_id,
            'scan_type': scan_type,
            'parameters': parameters,
            'file_path': file_path,
            'duration': duration,
            'status': status,
            'error_message': error_message
        }

        try:
            self.log_queue.put_nowait(entry)
        except asyncio.QueueFull:
            if self._logger:
                self._logger.log("Log queue full, dropping entry", level="warning")

    def log_command(self, command, parameters=None, status=None, mode=None,
                    error_message=None, duration=None):
        """
        Log a command processed by the server (non-blocking)

        :param command: The command name (e.g., 'moveMotor', 'scan', 'getData')
        :param parameters: Dictionary of command parameters
        :param status: Whether the command succeeded
        :param mode: Mode after command execution (e.g., 'idle', 'scanning')
        :param error_message: Error message if failed
        :param duration: Time taken to process command in seconds
        """
        if not self.running or self.log_queue is None or self._readonly:
            return

        entry = {
            'type': 'command',
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat(),
            'command': command,
            'parameters': parameters or {},
            'status': status,
            'mode': mode,
            'error_message': error_message,
            'duration': duration
        }

        try:
            self.log_queue.put_nowait(entry)
        except asyncio.QueueFull:
            if self._logger:
                self._logger.log("Log queue full, dropping entry", level="warning")

    def query_motor_moves(self, motor_name=None, start_time=None, end_time=None, limit=100):
        """
        Query motor moves from database(s) - works across monthly rotation

        :param motor_name: Filter by motor name (None for all)
        :param start_time: Start timestamp (None for all)
        :param end_time: End timestamp (None for all)
        :param limit: Maximum number of results
        :return: List of motor move records
        """
        # Default to recent data if no time range specified
        if start_time is None and end_time is None:
            end_time = time.time()
            start_time = end_time - (30 * 24 * 3600)  # Last 30 days
        elif start_time is None:
            start_time = 0
        elif end_time is None:
            end_time = time.time()

        # Get relevant database files
        db_files = self._get_db_files_for_range(start_time, end_time)

        all_results = []
        for db_path, db_start, db_end in db_files:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM motor_moves WHERE 1=1"
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
    
    def query_motor_positions(self, motor_name=None, start_time=None, end_time=None, limit=100):
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
            start_time = end_time - (30 * 24 * 3600)  # Last 30 days
        elif start_time is None:
            start_time = 0
        elif end_time is None:
            end_time = time.time()

        # Get relevant database files
        db_files = self._get_db_files_for_range(start_time, end_time)
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

    def query_scans(self, scan_type=None, start_time=None, end_time=None, limit=100):
        """
        Query scans from database(s) - works across monthly rotation

        :param scan_type: Filter by scan type (None for all)
        :param start_time: Start timestamp (None for all)
        :param end_time: End timestamp (None for all)
        :param limit: Maximum number of results
        :return: List of scan records
        """
        # Default to recent data if no time range specified
        if start_time is None and end_time is None:
            end_time = time.time()
            start_time = end_time - (30 * 24 * 3600)  # Last 30 days
        elif start_time is None:
            start_time = 0
        elif end_time is None:
            end_time = time.time()

        # Get relevant database files
        db_files = self._get_db_files_for_range(start_time, end_time)

        all_results = []
        for db_path, db_start, db_end in db_files:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM scans WHERE 1=1"
            params = []

            if scan_type:
                query += " AND scan_type = ?"
                params.append(scan_type)

            query += " AND timestamp >= ? AND timestamp <= ?"
            params.append(db_start)
            params.append(db_end)

            query += " ORDER BY timestamp DESC"

            cursor.execute(query, params)
            all_results.extend([dict(row) for row in cursor.fetchall()])
            conn.close()

        # Sort combined results and apply limit
        all_results.sort(key=lambda x: x['timestamp'], reverse=True)
        results = all_results[:limit]

        # Parse JSON parameters
        for result in results:
            if result['parameters']:
                try:
                    result['parameters'] = json.loads(result['parameters'])
                except:
                    pass

        return results

    def query_commands(self, command=None, start_time=None, end_time=None, limit=100):
        """
        Query commands from database(s) - works across monthly rotation

        :param command: Filter by command name (None for all)
        :param start_time: Start timestamp (None for all)
        :param end_time: End timestamp (None for all)
        :param limit: Maximum number of results
        :return: List of command records
        """
        # Default to recent data if no time range specified
        if start_time is None and end_time is None:
            end_time = time.time()
            start_time = end_time - (30 * 24 * 3600)  # Last 30 days
        elif start_time is None:
            start_time = 0
        elif end_time is None:
            end_time = time.time()

        # Get relevant database files
        db_files = self._get_db_files_for_range(start_time, end_time)

        all_results = []
        for db_path, db_start, db_end in db_files:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM commands WHERE 1=1"
            params = []

            if command:
                query += " AND command = ?"
                params.append(command)

            query += " AND timestamp >= ? AND timestamp <= ?"
            params.append(db_start)
            params.append(db_end)

            query += " ORDER BY timestamp DESC"

            cursor.execute(query, params)
            all_results.extend([dict(row) for row in cursor.fetchall()])
            conn.close()

        # Sort combined results and apply limit
        all_results.sort(key=lambda x: x['timestamp'], reverse=True)
        results = all_results[:limit]

        # Parse JSON parameters
        for result in results:
            if result['parameters']:
                try:
                    result['parameters'] = json.loads(result['parameters'])
                except:
                    pass

        return results

    def plot_motor_moves(self, motor_name, date=None, show=True, save_path=None):
        """
        Plot motor positions over a given day

        :param motor_name: Name of the motor to plot
        :param date: Date to plot (datetime object or 'YYYY-MM-DD' string). If None, uses today.
        :param show: Whether to display the plot
        :param save_path: Path to save the plot image (optional)
        :return: matplotlib figure object
        """
        # Parse date
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

        # Query motor moves for the day (uses multi-month query)
        results = self.query_motor_moves(
            motor_name=motor_name,
            start_time=start_timestamp,
            end_time=end_timestamp,
            limit=100000  # High limit for full day
        )

        # Sort by timestamp ascending for plotting
        results.sort(key=lambda x: x['timestamp'])

        if not results:
            print(f"No data found for motor '{motor_name}' on {date}")
            return None

        # Extract data for plotting
        timestamps = [datetime.fromtimestamp(r['timestamp']) for r in results]
        target_positions = [r['target_position'] for r in results]
        actual_positions = [r['actual_position'] if r['actual_position'] is not None else r['target_position']
                           for r in results]
        success = [r['success'] for r in results]

        # Create figure
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot target and actual positions
        ax.plot(timestamps, target_positions, 'o-', label='Target Position',
                markersize=4, alpha=0.7)
        ax.plot(timestamps, actual_positions, 's-', label='Actual Position',
                markersize=3, alpha=0.7)

        # Mark failed moves with red X
        failed_times = [timestamps[i] for i, s in enumerate(success) if not s]
        failed_positions = [target_positions[i] for i, s in enumerate(success) if not s]
        if failed_times:
            ax.plot(failed_times, failed_positions, 'rx', label='Failed Moves',
                    markersize=10, markeredgewidth=2)

        # Formatting
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel('Position', fontsize=12)
        ax.set_title(f'{motor_name} Positions - {date}', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)

        # Format x-axis as time
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        plt.xticks(rotation=45)

        # Add statistics
        stats_text = f'Moves: {len(results)} | Range: {min(target_positions):.3f} - {max(target_positions):.3f}'
        if failed_times:
            stats_text += f' | Failed: {len(failed_times)}'
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        plt.tight_layout()

        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=150)
            print(f"Plot saved to {save_path}")

        # Show if requested
        if show:
            plt.show()

        return fig
    
    def plot_motor_positions(self, motor_name, date=None, show=True, save_path=None):
        """
        Plot motor positions over a given day

        :param motor_name: Name of the motor to plot
        :param date: Date to plot (datetime object or 'YYYY-MM-DD' string). If None, uses today.
        :param show: Whether to display the plot
        :param save_path: Path to save the plot image (optional)
        :return: matplotlib figure object
        """
        # Parse date
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

        # Query motor positions for the day (uses multi-month query)
        results = self.query_motor_positions(
            motor_name=motor_name,
            start_time=start_timestamp,
            end_time=end_timestamp,
            limit=100000  # High limit for full day
        )

        # Sort by timestamp ascending for plotting
        results.sort(key=lambda x: x['timestamp'])

        if not results:
            print(f"No data found for motor '{motor_name}' on {date}")
            return None

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
        ax1.set_title(f'{motor_name} Positions - {date}', fontsize=14, fontweight='bold')
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
        if save_path:
            plt.savefig(save_path, dpi=150)
            print(f"Plot saved to {save_path}")

        # Show if requested
        if show:
            plt.show()

        return fig

    def plot_commands(self, date=None, show=True, save_path=None):
        """
        Plot command frequency over a given day

        :param date: Date to plot (datetime object or 'YYYY-MM-DD' string). If None, uses today.
        :param show: Whether to display the plot
        :param save_path: Path to save the plot image (optional)
        :return: matplotlib figure object
        """
        # Parse date
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

        # Query commands for the day
        results = self.query_commands(
            start_time=start_timestamp,
            end_time=end_timestamp,
            limit=100000  # High limit for full day
        )

        if not results:
            print(f"No commands found on {date}")
            return None

        # Sort by timestamp ascending for plotting
        results.sort(key=lambda x: x['timestamp'])

        # Count commands by type
        from collections import Counter
        command_counts = Counter(r['command'] for r in results)

        # Extract data for plotting
        timestamps = [datetime.fromtimestamp(r['timestamp']) for r in results]
        commands = [r['command'] for r in results]
        statuses = [r['status'] for r in results]

        # Create figure with two subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

        # Plot 1: Command frequency over time
        unique_commands = sorted(set(commands))
        colors = plt.cm.tab20(range(len(unique_commands)))
        command_colors = dict(zip(unique_commands, colors))

        for cmd in unique_commands:
            cmd_times = [timestamps[i] for i, c in enumerate(commands) if c == cmd]
            cmd_y = [unique_commands.index(cmd)] * len(cmd_times)
            ax1.scatter(cmd_times, cmd_y, label=cmd, color=command_colors[cmd],
                       alpha=0.6, s=50)

        ax1.set_yticks(range(len(unique_commands)))
        ax1.set_yticklabels(unique_commands)
        ax1.set_xlabel('Time', fontsize=12)
        ax1.set_ylabel('Command Type', fontsize=12)
        ax1.set_title(f'Commands Timeline - {date}', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3, axis='x')
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax1.xaxis.set_major_locator(mdates.HourLocator(interval=1))

        # Plot 2: Command type distribution (bar chart)
        cmd_names = list(command_counts.keys())
        cmd_values = list(command_counts.values())
        bars = ax2.barh(cmd_names, cmd_values, color=[command_colors[c] for c in cmd_names])

        ax2.set_xlabel('Count', fontsize=12)
        ax2.set_ylabel('Command Type', fontsize=12)
        ax2.set_title('Command Distribution', fontsize=14, fontweight='bold')
        ax2.grid(True, alpha=0.3, axis='x')

        # Add value labels on bars
        for bar, value in zip(bars, cmd_values):
            ax2.text(value, bar.get_y() + bar.get_height()/2,
                    f' {value}', va='center', fontsize=9)

        # Add statistics
        failed_count = sum(1 for s in statuses if s is False)
        success_count = sum(1 for s in statuses if s is True)
        stats_text = f'Total: {len(results)} | Success: {success_count} | Failed: {failed_count}'
        fig.text(0.5, 0.02, stats_text, ha='center', fontsize=11,
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
        plt.tight_layout()
        plt.subplots_adjust(bottom=0.08)

        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=150)
            print(f"Plot saved to {save_path}")

        # Show if requested
        if show:
            plt.show()

        return fig

    def plot_motor_with_commands(self, motor_name, date=None, show=True, save_path=None):
        """
        Plot motor positions with overlaid command execution information.

        This creates a comprehensive view showing:
        - Motor position over time
        - Command execution markers
        - Command type annotations
        - Motor moves highlighted
        - Scan operations marked

        :param motor_name: Name of the motor to plot
        :param date: Date to plot (datetime object or 'YYYY-MM-DD' string). If None, uses today.
        :param show: Whether to display the plot
        :param save_path: Path to save the plot image (optional)
        :return: matplotlib figure object
        """
        # Parse date
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

        # Query motor positions for the day
        position_results = self.query_motor_positions(
            motor_name=motor_name,
            start_time=start_timestamp,
            end_time=end_timestamp,
            limit=100000
        )

        # Query commands for the day
        command_results = self.query_commands(
            start_time=start_timestamp,
            end_time=end_timestamp,
            limit=100000
        )

        if not position_results:
            print(f"No position data found for motor '{motor_name}' on {date}")
            return None

        # Sort by timestamp
        position_results.sort(key=lambda x: x['timestamp'])
        if command_results:
            command_results.sort(key=lambda x: x['timestamp'])

        # Extract position data
        pos_timestamps = [datetime.fromtimestamp(r['timestamp']) for r in position_results]
        positions = [r['actual_position'] for r in position_results if r['actual_position'] is not None]
        pos_times_filtered = [pos_timestamps[i] for i, r in enumerate(position_results) if r['actual_position'] is not None]

        # Create figure with 2 subplots
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(2, 1, height_ratios=[2, 1], hspace=0.3)
        ax1 = fig.add_subplot(gs[0])  # Motor position
        ax2 = fig.add_subplot(gs[1], sharex=ax1)  # Command details table

        # Plot 1: Motor position over time
        ax1.plot(pos_times_filtered, positions, '-', linewidth=1, alpha=0.7, label='Position')
        ax1.set_ylabel(f'{motor_name} Position', fontsize=12, fontweight='bold')
        ax1.set_title(f'{motor_name} Position with Commands - {date}', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper left')

        # Add position statistics
        if positions:
            pos_stats = f'Range: {min(positions):.3f} - {max(positions):.3f} | Readings: {len(positions)}'
            ax1.text(0.02, 0.98, pos_stats, transform=ax1.transAxes,
                    verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.5))

        if command_results:
            # Categorize commands
            motor_commands = []
            scan_commands = []
            other_commands = []

            for cmd in command_results:
                cmd_time = datetime.fromtimestamp(cmd['timestamp'])
                cmd_name = cmd['command']
                cmd_status = cmd.get('status', True)

                if cmd_name in ['moveMotor', 'move_to_focus', 'getMotorPositions','changeMotorConfig']:
                    motor_commands.append((cmd_time, cmd_name, cmd_status, cmd.get('parameters', {})))
                elif cmd_name in ['scan', 'cancel', 'pause']:
                    scan_commands.append((cmd_time, cmd_name, cmd_status, cmd.get('parameters', {})))
                else:
                    other_commands.append((cmd_time, cmd_name, cmd_status))

            # Overlay motor commands on position plot
            if motor_commands:
                move_times = [t for t, cmd, status, _ in motor_commands if cmd == 'moveMotor' and status]
                failed_times = [t for t, cmd, status, _ in motor_commands if cmd == 'moveMotor' and not status]

                if move_times:
                    ax1.scatter(move_times, [ax1.get_ylim()[0]] * len(move_times),
                              marker='^', s=100, c='green', alpha=0.6,
                              label='Motor Move', zorder=5)
                if failed_times:
                    ax1.scatter(failed_times, [ax1.get_ylim()[0]] * len(failed_times),
                              marker='x', s=100, c='red', alpha=0.8,
                              label='Failed Move', zorder=5)

            # Overlay scan operations
            if scan_commands:
                scan_start_times = [t for t, cmd, _, _ in scan_commands if cmd == 'scan']
                scan_cancel_times = [t for t, cmd, _, _ in scan_commands if cmd == 'cancel']

                for scan_time in scan_start_times:
                    ax1.axvline(x=scan_time, color='blue', linestyle='--',
                              alpha=0.4, linewidth=2, label='Scan Start' if scan_time == scan_start_times[0] else '')

                for cancel_time in scan_cancel_times:
                    ax1.axvline(x=cancel_time, color='red', linestyle=':',
                              alpha=0.4, linewidth=2, label='Scan Cancel' if cancel_time == scan_cancel_times[0] else '')

            ax1.legend(loc='upper left', fontsize=9)

            # Plot 2: Command details with annotations
            ax2.set_title('Command Execution Details', fontsize=12, fontweight='bold')
            ax2.set_ylabel('Command', fontsize=11, fontweight='bold')
            ax2.set_xlabel('Time', fontsize=12, fontweight='bold')

            # Select important commands to display
            # Prioritize: scans, motor moves, and failed commands
            important_commands = []
            for cmd in command_results:
                cmd_name = cmd['command']
                if cmd_name in ['scan', 'moveMotor', 'cancel', 'pause'] or cmd.get('status') is False:
                    important_commands.append(cmd)

            # Limit to reasonable number for display (e.g., last 50)
            display_commands = important_commands[-50:] if len(important_commands) > 50 else important_commands

            if display_commands:
                # Create color map for command types
                unique_commands = sorted(set(c['command'] for c in display_commands))
                colors = plt.cm.tab20(range(len(unique_commands)))
                command_colors = dict(zip(unique_commands, colors))

                # Plot commands as vertical lines with annotations
                for cmd in display_commands:
                    cmd_time = datetime.fromtimestamp(cmd['timestamp'])
                    cmd_name = cmd['command']
                    cmd_status = cmd.get('status', True)
                    params = cmd.get('parameters', {})

                    # Line style based on status
                    linestyle = '-' if cmd_status else '--'
                    alpha = 0.7 if cmd_status else 0.9
                    linewidth = 1.5 if cmd_status else 2

                    # Draw vertical line for command
                    color = command_colors[cmd_name]
                    ax2.axvline(x=cmd_time, color=color, linestyle=linestyle,
                              alpha=alpha, linewidth=linewidth)

                    # Build annotation text with command details
                    annotation_parts = [cmd_name]

                    # Add relevant parameters based on command type
                    if cmd_name == 'moveMotor':
                        axis = params.get('axis', '?')
                        pos = params.get('pos', '?')
                        if axis != '?' and pos != '?':
                            annotation_parts.append(f"{axis}→{pos:.2f}" if isinstance(pos, (int, float)) else f"{axis}→{pos}")
                    elif cmd_name == 'scan':
                        scan_type = params.get('scan_type', '?')
                        scan_id = params.get('scan_id', '?')
                        if scan_type != '?':
                            annotation_parts.append(scan_type)
                        if scan_id != '?':
                            annotation_parts.append(f"#{scan_id}")
                    elif cmd_name == 'getData':
                        daq = params.get('daq', '?')
                        dwell = params.get('dwell', '?')
                        if daq != '?' or dwell != '?':
                            annotation_parts.append(f"daq:{daq}")

                    # Add status indicator
                    if not cmd_status:
                        annotation_parts.append('✗FAIL')

                    annotation = '\n'.join(annotation_parts)

                    # Annotate every Nth command to avoid clutter
                    # Show all failed commands and every 5th successful command
                    show_annotation = (not cmd_status) or (display_commands.index(cmd) % 5 == 0)

                    if show_annotation:
                        ax2.text(cmd_time, 0.5, annotation,
                               rotation=90, verticalalignment='bottom',
                               fontsize=8, alpha=0.8,
                               bbox=dict(boxstyle='round,pad=0.3', facecolor=color, alpha=0.3))

                # Set y-axis limits and remove ticks
                ax2.set_ylim(0, 1)
                ax2.set_yticks([])

                # Add legend for command types
                from matplotlib.patches import Patch
                legend_elements = [Patch(facecolor=command_colors[cmd], label=cmd, alpha=0.7)
                                 for cmd in unique_commands]
                ax2.legend(handles=legend_elements, loc='upper left', fontsize=8, ncol=min(len(unique_commands), 5))

                # Add statistics
                failed_count = sum(1 for r in command_results if r.get('status') is False)
                success_count = sum(1 for r in command_results if r.get('status') is True)
                cmd_stats = f'Total: {len(command_results)} | Displayed: {len(display_commands)} | Success: {success_count} | Failed: {failed_count}'
                ax2.text(0.98, 0.98, cmd_stats, transform=ax2.transAxes,
                        ha='right', verticalalignment='top',
                        bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.7),
                        fontsize=9)
            else:
                ax2.text(0.5, 0.5, 'No important commands to display\n(Showing: scan, moveMotor, cancel, pause, and failures)',
                        ha='center', va='center', transform=ax2.transAxes, fontsize=11, style='italic')
                ax2.set_ylim(0, 1)
                ax2.set_yticks([])

            ax2.grid(True, alpha=0.3, axis='x')

        else:
            # No commands - just show empty plot
            ax2.text(0.5, 0.5, 'No commands recorded', ha='center', va='center',
                    transform=ax2.transAxes, fontsize=12, style='italic')
            ax2.set_ylabel('Command', fontsize=11, fontweight='bold')
            ax2.set_xlabel('Time', fontsize=12, fontweight='bold')
            ax2.set_ylim(0, 1)
            ax2.set_yticks([])
            ax2.grid(True, alpha=0.3, axis='x')

        # Format x-axis (time) on bottom plot only
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax2.xaxis.set_major_locator(mdates.HourLocator(interval=max(1, int(24 / 12))))  # ~12 ticks max
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha='right')

        # Hide x labels on upper plot
        plt.setp(ax1.get_xticklabels(), visible=False)

        plt.tight_layout()

        # Save if requested
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"Plot saved to {save_path}")

        # Show if requested
        if show:
            plt.show()

        return fig

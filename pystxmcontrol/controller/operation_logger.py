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

        # Signal writer to stop
        if self.log_queue is not None:
            try:
                # Use a non-async method to put the sentinel
                asyncio.run_coroutine_threadsafe(
                    self.log_queue.put(None),
                    asyncio.get_event_loop()
                ).result(timeout=1)
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

                if entry['type'] == 'motor_position':
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

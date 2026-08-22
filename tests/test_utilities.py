import pytest
import os
import sqlite3
import tempfile
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
import pystxmcontrol.mcp.utilities as stxm_utils


class TestScanFromStxm:
    """Test scan_from_stxm function"""

    @patch('pystxmcontrol.mcp.utilities.read_stxm_stack')
    def test_scan_from_stxm_success(self, mock_read_stack):
        """Test successful scan extraction from STXM file"""
        # Mock stack object
        mock_stack = Mock()
        mock_stack.metadata = {
            "title": "Test-2026-001",
            "experimenters": "Smith",
            "version": 3.0,
            "scan_type": "Image",
            "x_motor": "SampleX",
            "y_motor": "SampleY",
            "x_positions": [0, 1, 2, 3, 4],
            "y_positions": [0, 1, 2, 3, 4],
            "detectors": ["default"],
            "comment": "Test scan",
            "sample_description": "Test sample"
        }
        mock_stack.energies = np.array([700, 705, 710])

        mock_image = Mock()
        mock_image.dwell = 0.5
        mock_stack.images = [mock_image]

        mock_read_stack.return_value = mock_stack

        result = stxm_utils.scan_from_stxm("/path/to/file.nxs")

        assert result["proposal"] == "Test-2026-001"
        assert result["experimenters"] == "Smith"
        assert result["nx_file_version"] == 3.0
        assert result["x_center"] == 2.0
        assert result["y_center"] == 2.0
        assert result["x_range"] == 4.0
        assert result["y_range"] == 4.0
        assert result["x_points"] == 5
        assert result["y_points"] == 5
        assert result["energy_list"] == [700, 705, 710]
        assert result["dwell"] == 0.5
        assert result["autofocus"] is True
        assert result["spiral"] is False


class TestDatabaseUtilities:
    """Test database utility functions"""

    def test_get_db_directory(self):
        """Test database directory creation"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stxm_utils._get_db_directory(tmpdir)

            expected_path = os.path.join(tmpdir, 'pystxmcontrol_data')
            assert result == expected_path
            assert os.path.exists(result)

    def test_get_monthly_db_path_current_month(self):
        """Test monthly database path for current month"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stxm_utils._get_monthly_db_path(db_base_dir=tmpdir)

            expected_month = datetime.now().strftime('%Y-%m')
            expected_filename = f'operations_{expected_month}.db'

            assert expected_filename in result

    def test_get_monthly_db_path_specific_date(self):
        """Test monthly database path for specific date"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_date = datetime(2026, 1, 15)
            result = stxm_utils._get_monthly_db_path(date=test_date, db_base_dir=tmpdir)

            assert 'operations_2026-01.db' in result

    def test_get_monthly_db_path_string_date(self):
        """Test monthly database path with string date"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stxm_utils._get_monthly_db_path(date='2026-03-20', db_base_dir=tmpdir)

            assert 'operations_2026-03.db' in result

    def test_get_db_files_for_range_single_month(self):
        """Test getting database files for single month range"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = stxm_utils._get_db_directory(tmpdir)

            # Create a test database file
            test_db = os.path.join(db_dir, 'operations_2026-01.db')
            open(test_db, 'a').close()

            start_time = datetime(2026, 1, 10).timestamp()
            end_time = datetime(2026, 1, 20).timestamp()

            result = stxm_utils._get_db_files_for_range(start_time, end_time, tmpdir)

            assert len(result) == 1
            assert result[0][0] == test_db
            assert result[0][1] == start_time
            assert result[0][2] == end_time

    def test_get_db_files_for_range_multiple_months(self):
        """Test getting database files spanning multiple months"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = stxm_utils._get_db_directory(tmpdir)

            # Create test database files for different months
            for month in ['2025-12', '2026-01', '2026-02']:
                test_db = os.path.join(db_dir, f'operations_{month}.db')
                open(test_db, 'a').close()

            start_time = datetime(2025, 12, 20).timestamp()
            end_time = datetime(2026, 2, 10).timestamp()

            result = stxm_utils._get_db_files_for_range(start_time, end_time, tmpdir)

            assert len(result) == 3

    def test_get_db_files_for_range_no_files(self):
        """Test getting database files when none exist"""
        with tempfile.TemporaryDirectory() as tmpdir:
            start_time = datetime(2026, 1, 1).timestamp()
            end_time = datetime(2026, 1, 31).timestamp()

            result = stxm_utils._get_db_files_for_range(start_time, end_time, tmpdir)

            assert len(result) == 0


class TestQueryMotorPositions:
    """Test query_motor_positions function"""

    def setup_test_db(self, db_path, base_timestamp):
        """Helper to create and populate test database"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE motor_positions (
                id INTEGER PRIMARY KEY,
                motor_name TEXT,
                timestamp REAL,
                actual_position REAL,
                motor_offset REAL
            )
        ''')

        # Insert test data with timestamps relative to base
        test_data = [
            ('SampleX', base_timestamp + 1000, 10.5, 0.1),
            ('SampleX', base_timestamp + 2000, 11.5, 0.1),
            ('SampleX', base_timestamp + 3000, 12.5, 0.2),
            ('SampleY', base_timestamp + 1500, -5.0, 0.0),
            ('SampleY', base_timestamp + 2500, -4.5, 0.0),
        ]

        cursor.executemany(
            'INSERT INTO motor_positions (motor_name, timestamp, actual_position, motor_offset) VALUES (?, ?, ?, ?)',
            test_data
        )

        conn.commit()
        conn.close()

    def test_query_motor_positions_specific_motor(self):
        """Test querying positions for specific motor"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Use a recent date to ensure proper month calculation
            test_date = datetime(2026, 1, 15)
            base_timestamp = test_date.timestamp()

            db_dir = stxm_utils._get_db_directory(tmpdir)
            db_path = os.path.join(db_dir, 'operations_2026-01.db')

            self.setup_test_db(db_path, base_timestamp)

            result = stxm_utils.query_motor_positions(
                motor_name='SampleX',
                start_time=base_timestamp,
                end_time=base_timestamp + 5000,
                limit=100,
                db_base_dir=tmpdir
            )

            assert len(result) == 3
            assert all(r['motor_name'] == 'SampleX' for r in result)

    def test_query_motor_positions_time_range(self):
        """Test querying positions within time range"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_date = datetime(2026, 1, 15)
            base_timestamp = test_date.timestamp()

            db_dir = stxm_utils._get_db_directory(tmpdir)
            db_path = os.path.join(db_dir, 'operations_2026-01.db')

            self.setup_test_db(db_path, base_timestamp)

            result = stxm_utils.query_motor_positions(
                motor_name='SampleX',
                start_time=base_timestamp + 1500,
                end_time=base_timestamp + 2500,
                limit=100,
                db_base_dir=tmpdir
            )

            assert len(result) == 1
            assert result[0]['timestamp'] == base_timestamp + 2000.0

    def test_query_motor_positions_limit(self):
        """Test query limit"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_date = datetime(2026, 1, 15)
            base_timestamp = test_date.timestamp()

            db_dir = stxm_utils._get_db_directory(tmpdir)
            db_path = os.path.join(db_dir, 'operations_2026-01.db')

            self.setup_test_db(db_path, base_timestamp)

            result = stxm_utils.query_motor_positions(
                motor_name='SampleX',
                start_time=base_timestamp,
                end_time=base_timestamp + 5000,
                limit=2,
                db_base_dir=tmpdir
            )

            assert len(result) == 2

    def test_query_motor_positions_default_time_range(self):
        """Test query with default time range (last 24 hours)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stxm_utils.query_motor_positions(
                motor_name='SampleX',
                db_base_dir=tmpdir
            )

            # Should not fail even with no database
            assert isinstance(result, list)


class TestPlotMotorPositions:
    """Test plot_motor_positions function"""

    def setup_test_db_with_recent_data(self, db_path):
        """Helper to create database with recent data"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE motor_positions (
                id INTEGER PRIMARY KEY,
                motor_name TEXT,
                timestamp REAL,
                actual_position REAL,
                motor_offset REAL
            )
        ''')

        # Insert data for today
        today = datetime.now()
        base_time = datetime.combine(today.date(), datetime.min.time())

        test_data = [
            ('SampleX', (base_time + timedelta(hours=i)).timestamp(), 10.0 + i * 0.5, 0.1)
            for i in range(10)
        ]

        cursor.executemany(
            'INSERT INTO motor_positions (motor_name, timestamp, actual_position, motor_offset) VALUES (?, ?, ?, ?)',
            test_data
        )

        conn.commit()
        conn.close()

    @patch('pystxmcontrol.mcp.utilities.plt.savefig')
    def test_plot_motor_positions_save_file(self, mock_savefig):
        """Test plotting and saving to file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = stxm_utils._get_db_directory(tmpdir)
            today = datetime.now()
            month_str = today.strftime('%Y-%m')
            db_path = os.path.join(db_dir, f'operations_{month_str}.db')

            self.setup_test_db_with_recent_data(db_path)

            output_file = os.path.join(tmpdir, 'test_plot.png')

            result = stxm_utils.plot_motor_positions(
                motor_name='SampleX',
                db_base_dir=tmpdir,
                file_path=output_file
            )

            assert result == output_file
            mock_savefig.assert_called_once_with(output_file, dpi=150)

    def test_plot_motor_positions_no_data(self):
        """Test plotting with no data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = stxm_utils.plot_motor_positions(
                motor_name='NonExistentMotor',
                db_base_dir=tmpdir
            )

            assert "No data found" in result

    @patch('pystxmcontrol.mcp.utilities.plt.savefig')
    def test_plot_motor_positions_date_range(self, mock_savefig):
        """Test plotting with date range"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = stxm_utils._get_db_directory(tmpdir)
            today = datetime.now()
            month_str = today.strftime('%Y-%m')
            db_path = os.path.join(db_dir, f'operations_{month_str}.db')

            self.setup_test_db_with_recent_data(db_path)

            output_file = os.path.join(tmpdir, 'test_plot.png')

            result = stxm_utils.plot_motor_positions(
                motor_name='SampleX',
                start_date=today.date(),
                end_date=today.date(),
                db_base_dir=tmpdir,
                file_path=output_file
            )

            assert result == output_file

    @patch('pystxmcontrol.mcp.utilities.plt.savefig')
    def test_plot_motor_positions_timestamp_range(self, mock_savefig):
        """Test plotting with timestamp range"""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_dir = stxm_utils._get_db_directory(tmpdir)
            today = datetime.now()
            month_str = today.strftime('%Y-%m')
            db_path = os.path.join(db_dir, f'operations_{month_str}.db')

            self.setup_test_db_with_recent_data(db_path)

            output_file = os.path.join(tmpdir, 'test_plot.png')

            start_time = datetime.combine(today.date(), datetime.min.time()).timestamp()
            end_time = datetime.combine(today.date(), datetime.max.time()).timestamp()

            result = stxm_utils.plot_motor_positions(
                motor_name='SampleX',
                start_time=start_time,
                end_time=end_time,
                db_base_dir=tmpdir,
                file_path=output_file
            )

            assert result == output_file

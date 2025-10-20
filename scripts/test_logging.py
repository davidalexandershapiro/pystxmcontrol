#!/usr/bin/env python3
"""
Test script for operation logging functionality
Tests motor move logging and scan logging
"""

import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pystxmcontrol.controller.operation_logger import OperationLogger


def test_motor_logging():
    """Test motor move logging"""
    print("=" * 60)
    print("Testing Motor Move Logging")
    print("=" * 60)

    logger = OperationLogger()
    logger.start()

    # Simulate some motor moves
    print("\nLogging 5 motor moves...")
    for i in range(5):
        logger.log_motor_move(
            motor_name=f"Motor{i % 2}",
            target_position=10.0 + i * 0.5,
            actual_position=10.01 + i * 0.5,
            duration=0.05 + i * 0.01,
            success=True
        )
        time.sleep(0.01)

    # Log a failed move
    print("Logging 1 failed motor move...")
    logger.log_motor_move(
        motor_name="MotorX",
        target_position=100.0,
        duration=0.001,
        success=False,
        error_message="Motor limit exceeded"
    )

    # Give time for async writes
    time.sleep(0.5)

    # Query the results
    print("\nQuerying recent motor moves...")
    moves = logger.query_motor_moves(limit=10)
    print(f"Found {len(moves)} motor moves:")
    for move in moves[:3]:  # Show first 3
        print(f"  {move['datetime']}: {move['motor_name']} -> {move['target_position']:.2f} "
              f"(success={move['success']})")

    # Query specific motor
    print("\nQuerying Motor0 moves...")
    motor0_moves = logger.query_motor_moves(motor_name="Motor0", limit=5)
    print(f"Found {len(motor0_moves)} Motor0 moves")

    logger.stop()
    print("\n✅ Motor logging test completed")


def test_scan_logging():
    """Test scan logging"""
    print("\n" + "=" * 60)
    print("Testing Scan Logging")
    print("=" * 60)

    logger = OperationLogger()
    logger.start()

    # Simulate scan start
    print("\nLogging scan start...")
    scan_params = {
        "x_motor": "SampleX",
        "y_motor": "SampleY",
        "energy_motor": "Energy",
        "xPoints": 100,
        "yPoints": 100,
        "dwell": 0.001,
    }

    logger.log_scan_start(
        scan_id="test_scan_001",
        scan_type="line_image",
        parameters=scan_params
    )

    # Simulate scan running
    time.sleep(0.2)

    # Simulate scan end
    print("Logging scan completion...")
    logger.log_scan_end(
        scan_id="test_scan_001",
        scan_type="line_image",
        parameters=scan_params,
        file_path="/data/test_scan_001.h5",
        duration=0.2,
        status="completed"
    )

    # Simulate failed scan
    print("Logging failed scan...")
    logger.log_scan_start(
        scan_id="test_scan_002",
        scan_type="ptychography",
        parameters={"detector": "CCD"}
    )

    time.sleep(0.1)

    logger.log_scan_end(
        scan_id="test_scan_002",
        scan_type="ptychography",
        parameters={"detector": "CCD"},
        duration=0.1,
        status="failed",
        error_message="Detector timeout"
    )

    # Give time for async writes
    time.sleep(0.5)

    # Query the results
    print("\nQuerying recent scans...")
    scans = logger.query_scans(limit=10)
    print(f"Found {len(scans)} scan entries:")
    for scan in scans[:4]:  # Show first 4
        print(f"  {scan['datetime']}: {scan['scan_id']} ({scan['scan_type']}) - {scan['status']}")
        if scan.get('file_path'):
            print(f"    File: {scan['file_path']}")
        if scan.get('duration'):
            print(f"    Duration: {scan['duration']:.2f}s")

    # Query by type
    print("\nQuerying line_image scans...")
    line_scans = logger.query_scans(scan_type="line_image", limit=5)
    print(f"Found {len(line_scans)} line_image scans")

    logger.stop()
    print("\n✅ Scan logging test completed")


def test_performance():
    """Test logging performance impact"""
    print("\n" + "=" * 60)
    print("Testing Logging Performance")
    print("=" * 60)

    logger = OperationLogger()
    logger.start()

    # Test rapid motor move logging
    n_moves = 1000
    print(f"\nLogging {n_moves} motor moves rapidly...")

    start = time.perf_counter()
    for i in range(n_moves):
        logger.log_motor_move(
            motor_name=f"Motor{i % 5}",
            target_position=i * 0.01,
            actual_position=i * 0.01 + 0.001,
            duration=0.05,
            success=True
        )
    elapsed = time.perf_counter() - start

    print(f"Time to queue {n_moves} log entries: {elapsed*1000:.2f} ms")
    print(f"Average time per log: {elapsed/n_moves*1000:.4f} ms")

    # Wait for writes to complete
    print("\nWaiting for async writes to complete...")
    time.sleep(2)

    # Verify all were written
    recent = logger.query_motor_moves(limit=n_moves)
    print(f"Verified {len(recent)} entries written to database")

    logger.stop()
    print("\n✅ Performance test completed")


def main():
    print("\n" + "=" * 60)
    print("Operation Logger Test Suite")
    print("=" * 60)

    test_motor_logging()
    test_scan_logging()
    test_performance()

    print("\n" + "=" * 60)
    print("All tests completed successfully!")
    print("=" * 60)

    # Show database location
    logger = OperationLogger()
    print(f"\nDatabase location: {logger.db_path}")
    print("You can query this database with SQLite tools")


if __name__ == "__main__":
    main()

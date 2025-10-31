#!/usr/bin/env python3
"""
Benchmark SQLite logging performance for motor moves and scans.
Tests synchronous vs async logging to measure time overhead.
"""

import sqlite3
import time
import asyncio
import json
import tempfile
import os
from statistics import mean, stdev

def create_test_db(db_path):
    """Create test database schema"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS motor_moves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            motor_name TEXT,
            target_position REAL,
            actual_position REAL,
            duration REAL,
            success BOOLEAN
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            scan_id TEXT,
            scan_type TEXT,
            parameters TEXT,
            duration REAL,
            status TEXT
        )
    ''')

    conn.commit()
    return conn

def benchmark_synchronous_logging(conn, n_iterations=1000):
    """Measure synchronous (blocking) logging time"""
    cursor = conn.cursor()
    times = []

    for i in range(n_iterations):
        start = time.perf_counter()

        cursor.execute('''
            INSERT INTO motor_moves (timestamp, motor_name, target_position,
                                     actual_position, duration, success)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (time.time(), f"Motor_{i%5}", 10.5 + i*0.1, 10.51 + i*0.1, 0.05, True))

        conn.commit()

        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)  # Convert to milliseconds

    return times

def benchmark_batched_logging(conn, n_iterations=1000, batch_size=10):
    """Measure batched logging time (commit every N inserts)"""
    cursor = conn.cursor()
    times = []

    for i in range(n_iterations):
        start = time.perf_counter()

        cursor.execute('''
            INSERT INTO motor_moves (timestamp, motor_name, target_position,
                                     actual_position, duration, success)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (time.time(), f"Motor_{i%5}", 10.5 + i*0.1, 10.51 + i*0.1, 0.05, True))

        if i % batch_size == 0:
            conn.commit()

        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)

    conn.commit()  # Final commit
    return times

def benchmark_scan_logging(conn, n_iterations=100):
    """Measure scan logging time (larger payload)"""
    cursor = conn.cursor()
    times = []

    scan_params = {
        "x_motor": "SampleX",
        "y_motor": "SampleY",
        "energy_motor": "Energy",
        "scan_type": "line_image",
        "xPoints": 100,
        "yPoints": 100,
        "dwell": 0.001,
        "energies": [280.0, 285.0, 290.0]
    }

    for i in range(n_iterations):
        start = time.perf_counter()

        cursor.execute('''
            INSERT INTO scans (timestamp, scan_id, scan_type, parameters, duration, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (time.time(), f"scan_{i:04d}", "line_image",
              json.dumps(scan_params), 125.3, "completed"))

        conn.commit()

        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)

    return times

async def benchmark_async_queue_logging(n_iterations=1000):
    """Simulate async logging with queue (non-blocking pattern)"""
    queue = asyncio.Queue()
    times = []

    # Simulate database writer task
    async def db_writer():
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
                if item is None:
                    break
                # Simulate DB write
                await asyncio.sleep(0.0001)  # ~0.1ms write time
            except asyncio.TimeoutError:
                break

    writer_task = asyncio.create_task(db_writer())

    # Measure time to add to queue (what moveMotor would experience)
    for i in range(n_iterations):
        start = time.perf_counter()

        await queue.put({
            'timestamp': time.time(),
            'motor_name': f"Motor_{i%5}",
            'target_position': 10.5 + i*0.1,
            'actual_position': 10.51 + i*0.1,
            'duration': 0.05,
            'success': True
        })

        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)

    await queue.put(None)  # Signal completion
    await writer_task

    return times

def print_statistics(label, times):
    """Print timing statistics"""
    print(f"\n{label}:")
    print(f"  Mean:   {mean(times):.4f} ms")
    print(f"  Median: {sorted(times)[len(times)//2]:.4f} ms")
    print(f"  Min:    {min(times):.4f} ms")
    print(f"  Max:    {max(times):.4f} ms")
    if len(times) > 1:
        print(f"  StdDev: {stdev(times):.4f} ms")
    print(f"  99th percentile: {sorted(times)[int(len(times)*0.99)]:.4f} ms")

def main():
    print("=" * 60)
    print("SQLite Logging Performance Benchmark")
    print("=" * 60)

    # Create temporary database
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_logging.db")

    print(f"\nDatabase: {db_path}")

    conn = create_test_db(db_path)

    # Test 1: Synchronous logging (worst case - what you want to avoid)
    print("\n" + "=" * 60)
    print("TEST 1: Synchronous (Blocking) Motor Move Logging")
    print("=" * 60)
    times = benchmark_synchronous_logging(conn, n_iterations=1000)
    print_statistics("Per-move overhead (BLOCKING)", times)
    print(f"\n⚠️  This would add ~{mean(times):.2f}ms to EVERY motor move!")

    # Clear table
    conn.execute("DELETE FROM motor_moves")
    conn.commit()

    # Test 2: Batched commits (better but still blocking)
    print("\n" + "=" * 60)
    print("TEST 2: Batched Commits (commit every 10 moves)")
    print("=" * 60)
    times = benchmark_batched_logging(conn, n_iterations=1000, batch_size=10)
    print_statistics("Per-move overhead (batched)", times)

    # Test 3: Scan logging
    print("\n" + "=" * 60)
    print("TEST 3: Scan Logging (larger payload)")
    print("=" * 60)
    times = benchmark_scan_logging(conn, n_iterations=100)
    print_statistics("Per-scan overhead", times)

    conn.close()

    # Test 4: Async queue (recommended approach)
    print("\n" + "=" * 60)
    print("TEST 4: Async Queue Logging (RECOMMENDED)")
    print("=" * 60)
    times = asyncio.run(benchmark_async_queue_logging(n_iterations=1000))
    print_statistics("Per-move overhead (queue.put)", times)
    print(f"\n✅ This would add only ~{mean(times):.4f}ms to motor moves!")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY & RECOMMENDATIONS")
    print("=" * 60)
    print("""
    1. SYNCHRONOUS (blocking) logging: ~0.1-1ms overhead per operation
       ❌ NOT RECOMMENDED - adds latency to motor moves

    2. ASYNC QUEUE logging: ~0.001-0.01ms overhead per operation
       ✅ RECOMMENDED - negligible impact on motor operations

    3. Implementation pattern:
       - Motor move adds log entry to asyncio.Queue (microseconds)
       - Background task writes queue entries to DB
       - No blocking of motor operations

    4. For your typical scan with 10,000 motor positions:
       - Synchronous: adds ~1-10 seconds to scan time ❌
       - Async queue: adds ~0.01 seconds to scan time ✅
    """)

    # Cleanup
    os.unlink(db_path)
    os.rmdir(temp_dir)
    print(f"\nCleaned up temporary database")

if __name__ == "__main__":
    main()

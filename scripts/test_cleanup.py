#!/usr/bin/env python3
"""
Test script to verify ZMQ socket cleanup on Ctrl-C
"""

import signal
import sys
import time

# Mock classes to test cleanup without full controller
class MockLogger:
    def log(self, msg, level="info"):
        print(f"[{level.upper()}] {msg}")

class MockDataHandler:
    def __init__(self):
        import zmq
        import atexit

        self.context = zmq.Context()
        self.test_socket = self.context.socket(zmq.PUB)

        # Try to bind to a test port
        try:
            self.test_socket.bind("tcp://127.0.0.1:55555")
            print("✅ Test socket bound to tcp://127.0.0.1:55555")
        except Exception as e:
            print(f"❌ Could not bind socket: {e}")
            return

        # Register cleanup
        atexit.register(self.cleanup)
        print("✅ Cleanup handler registered via atexit")

    def cleanup(self):
        """Cleanup ZMQ sockets"""
        print("\n🧹 Cleanup called!")
        try:
            if hasattr(self, 'test_socket'):
                self.test_socket.close(linger=0)
                print("✅ Test socket closed successfully")
        except Exception as e:
            print(f"❌ Error closing socket: {e}")

        try:
            if hasattr(self, 'context'):
                self.context.term()
                print("✅ ZMQ context terminated")
        except Exception as e:
            print(f"❌ Error terminating context: {e}")

def signal_handler(sig, frame):
    """Handle Ctrl-C gracefully"""
    print("\n\n⚠️  Ctrl-C detected! Python will call atexit handlers...")
    sys.exit(0)

def main():
    print("=" * 60)
    print("ZMQ Socket Cleanup Test")
    print("=" * 60)
    print("\nThis test verifies that ZMQ sockets are properly closed")
    print("when the program exits via Ctrl-C.\n")

    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)

    # Create mock data handler with ZMQ socket
    print("Creating mock dataHandler with ZMQ socket...")
    handler = MockDataHandler()

    print("\n" + "=" * 60)
    print("Press Ctrl-C to test cleanup")
    print("=" * 60)

    # Keep running
    try:
        while True:
            time.sleep(1)
            print(".", end="", flush=True)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()

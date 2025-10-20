#!/usr/bin/env python3
"""
Test script to verify MVC components work correctly.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from pystxmcontrol.gui.models.scan_model import ScanModel
from pystxmcontrol.gui.models.motor_model import MotorModel
from pystxmcontrol.gui.models.image_model import ImageModel
from pystxmcontrol.gui.controllers.main_controller import MainController


def test_models():
    """Test that models work correctly."""
    print("Testing Models...")
    
    # Test ScanModel
    scan_model = ScanModel()
    scan_model.set('scan_type', 'Image')
    assert scan_model.get('scan_type') == 'Image'
    print("✓ ScanModel works")
    
    # Test MotorModel
    motor_model = MotorModel()
    motor_model.update_position('SampleX', 10.5)
    assert motor_model.get_position('SampleX') == 10.5
    print("✓ MotorModel works")
    
    # Test ImageModel
    image_model = ImageModel()
    image_model.update_cursor_position(5.0, 3.0, 100.0)
    assert image_model.get('cursor_x') == 5.0
    print("✓ ImageModel works")


def test_controller():
    """Test that controller works correctly."""
    print("\nTesting Controller...")
    
    controller = MainController()
    
    # Test model access
    scan_model = controller.get_scan_model()
    motor_model = controller.get_motor_model()
    image_model = controller.get_image_model()
    
    assert scan_model is not None
    assert motor_model is not None
    assert image_model is not None
    print("✓ Controller model access works")
    
    # Test scan type setting
    controller.set_scan_type('Focus')
    assert scan_model.get('scan_type') == 'Focus'
    print("✓ Controller scan type setting works")


def test_signals():
    """Test that signals work correctly."""
    print("\nTesting Signals...")
    
    scan_model = ScanModel()
    signal_received = []
    
    def on_data_changed(property_name, value):
        signal_received.append((property_name, value))
    
    scan_model.data_changed.connect(on_data_changed)
    scan_model.set('test_property', 'test_value')
    
    assert len(signal_received) == 1
    assert signal_received[0] == ('test_property', 'test_value')
    print("✓ Model signals work")


def main():
    """Main test function."""
    print("Testing MVC Architecture Components\n")
    
    try:
        test_models()
        test_controller()
        test_signals()
        
        print("\n🎉 All tests passed! MVC architecture is working correctly.")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    return 0


if __name__ == "__main__":
    sys.exit(main())
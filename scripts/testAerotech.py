#!/usr/bin/env python3

"""
Comprehensive Aerotech Controller and Motor Test Suite
====================================================

Architecture:
┌─────────────────┐
│   Controller    │  High level: Hardware abstraction (aerotechController.py)
└─────────────────┘
┌─────────────────┐
│     Motor       │  Mid level: Axis-specific operations (aerotechMotor.py)
└─────────────────┘
┌─────────────────┐
│   Automation1   │  Low level: SDK communication (automation1.py)
│      SDK        │
└─────────────────┘

This test suite comprehensively tests all functions in both aerotechController.py 
and aerotechMotor.py, organized into two main categories:

SAFE TESTS (can be run immediately - NO PHYSICAL MOVEMENT):
- Initialization and connection tests
- Status and position reading tests
- Configuration validation tests
- Connection state tests
- Error handling tests
- Simulation mode tests

PHYSICAL TESTS (require supervision - PHYSICAL MOVEMENT):
- Motion commands (moveTo, moveBy)
- Emergency stop tests
- Axis enable/disable tests
- Homing tests
- Motion monitoring tests

Usage:
    python scripts/testAerotech.py
"""

from pystxmcontrol.drivers.aerotechController import aerotechController
from pystxmcontrol.drivers.aerotechMotor import aerotechMotor
import time
import sys
import automation1 as a1

# =============================================================================
# SAFE TESTS (No physical movement)
# =============================================================================

def test_controller_creation(controller_address, controller_port):
    """Test controller creation and initialization"""
    print("\n" + "="*60)
    print("TEST: Controller Creation")
    print("="*60)
    
    try:
        # Create controller
        print(f"Creating Aerotech controller at {controller_address}:{controller_port}...")
        controller = aerotechController(address=controller_address, port=controller_port)
        print(f"Controller object created successfully")
        print(f"  Address: {controller.address}")
        print(f"  Port: {controller.port}")
        print(f"  Simulation mode: {controller.simulation}")
        
        # Initialize controller
        print("\nInitializing controller...")
        result = controller.initialize()
        print(f"Initialization completed with result: {result}")
        
        return controller
        
    except Exception as e:
        print(f"Controller creation failed: {e}")
        return None

def test_controller_connection(controller):
    """Test controller connection and startup"""
    print("\n" + "="*60)
    print("TEST: Controller Connection")
    print("="*60)
    
    try:
        # Connect to controller
        print("Connecting to controller...")
        result = controller.connect()
        print(f"Connection result: {result}")
        
        # Check connection status
        print("\nChecking connection status...")
        is_connected = controller.isConnected()
        print(f"Connection status: {is_connected}")
        
        # Start controller
        print("\nStarting controller...")
        start_result = controller.start()
        print(f"Start result: {start_result}")
        
        return controller
        
    except Exception as e:
        print(f"Controller connection failed: {e}")
        return None

def test_motor_creation(controller):
    """Test motor object creation and configuration"""
    print("\n" + "="*60)
    print("TEST: Motor Creation")
    print("="*60)
    
    try:
        # Create motor with controller reference
        print("Creating Aerotech motor with controller reference...")
        motor = aerotechMotor(controller=controller)
        print(f"Motor object created successfully")
        print(f"  Default position: {motor.position}")
        print(f"  Simulation mode: {motor.simulation}")
        print(f"  Config: {motor.config}")
        
        # Test motor creation with custom config
        print("\nCreating Aerotech motor with custom config...")
        custom_config = {
            "units": 1000,
            "offset": 0.5,
            "minValue": -5.0,
            "maxValue": 5.0
        }
        custom_motor = aerotechMotor(controller=controller, config=custom_config)
        print(f"Custom motor created successfully")
        print(f"  Custom config: {custom_motor.config}")
        
        return motor
        
    except Exception as e:
        print(f"Motor creation failed: {e}")
        return None

def test_motor_connection(motor, test_axis):
    """Test motor connection to axis"""
    print("\n" + "="*60)
    print("TEST: Motor Connection")
    print("="*60)
    
    try:
        # Connect motor to axis
        print(f"Connecting motor to axis: {test_axis}")
        connection_result = motor.connect(axis=test_axis)
        print(f"Motor connection result: {connection_result}")
        print(f"  Axis: {motor.axis}")
        print(f"  Group: {motor.group}")
        
        return motor
        
    except Exception as e:
        print(f"Motor connection failed: {e}")
        return None

def test_position_reading(motor):
    """Test position reading functionality"""
    print("\n" + "="*60)
    print("TEST: Position Reading")
    print("="*60)
    
    try:
        # Test position reading multiple times
        print("Reading position multiple times...")
        positions = []
        for i in range(5):
            pos = motor.getPos()
            positions.append(pos)
            print(f"  Reading {i+1}: {pos:.6f}")
            time.sleep(0.1)
        
        # Check consistency
        if len(set(positions)) == 1:
            print(f"Position readings are consistent: {positions[0]:.6f}")
        else:
            print(f"Position readings vary: {positions}")
            print(f"  Min: {min(positions):.6f}, Max: {max(positions):.6f}")
        
        return motor
        
    except Exception as e:
        print(f"Position reading failed: {e}")
        return None

def test_status_reading(motor):
    """Test status reading functionality"""
    print("\n" + "="*60)
    print("TEST: Status Reading")
    print("="*60)
    
    try:
        # Test basic status
        print("Reading basic motor status...")
        status = motor.getStatus()
        print(f"Motor status: {status}")
        
        # Test detailed status
        print("\nReading detailed status...")
        detailed_status = motor.getDetailedStatus()
        print(f"Detailed status:")
        for key, value in detailed_status.items():
            print(f"  {key}: {value}")
        
        # Test individual status methods
        print("\nTesting individual status methods...")
        is_enabled = motor.isEnabled()
        is_homed = motor.isHomed()
        is_in_position = motor.isInPosition()
        
        print(f"  Enabled: {is_enabled}")
        print(f"  Homed: {is_homed}")
        print(f"  In position: {is_in_position}")
        
        return motor
        
    except Exception as e:
        print(f"Status reading failed: {e}")
        return None

def test_limits_checking(motor):
    """Test software limits validation"""
    print("\n" + "="*60)
    print("TEST: Limits Checking")
    print("="*60)
    
    try:
        # Test limits checking
        print("Testing software limits...")
        current_pos = motor.getPos()
        min_limit = motor.config["minValue"]
        max_limit = motor.config["maxValue"]
        
        print(f"  Current position: {current_pos:.6f}")
        print(f"  Min limit: {min_limit}")
        print(f"  Max limit: {max_limit}")
        
        # Test various positions
        test_positions = [
            current_pos,  # Current position (should be OK)
            min_limit,    # At min limit (should be OK)
            max_limit,    # At max limit (should be OK)
            min_limit - 1,  # Below min limit (should be rejected)
            max_limit + 1,  # Above max limit (should be rejected)
            (min_limit + max_limit) / 2,  # Middle position (should be OK)
        ]
        
        for pos in test_positions:
            is_valid = motor.checkLimits(pos)
            status = "OK" if is_valid else "REJECTED"
            print(f"  Position {pos:.2f}: {status}")
        
        return motor
        
    except Exception as e:
        print(f"Limits checking failed: {e}")
        return None

def test_controller_methods(controller, motor):
    """Test controller-level methods"""
    print("\n" + "="*60)
    print("TEST: Controller Methods")
    print("="*60)
    
    try:
        # Test getPosition at controller level
        print("Testing controller.getPosition()...")
        err, pos = controller.getPosition(motor.axis)
        print(f"  Error code: {err}")
        print(f"  Position: {pos}")
        
        # Test getAxes method
        print("\nTesting controller.getAxes()...")
        axes = controller.getAxes()
        print(f"  Available axes: {axes}")
        print(f"  Number of axes: {len(axes)}")
        
        # Test connection validation
        print("\nTesting connection validation...")
        is_connected = controller.isConnected()
        print(f"  Connection status: {is_connected}")
        
        return motor
        
    except Exception as e:
        print(f"Controller methods test failed: {e}")
        return None

def test_simulation_mode(controller_address, controller_port, test_axis):
    """Test simulation mode functionality"""
    print("\n" + "="*60)
    print("TEST: Simulation Mode")
    print("="*60)
    
    try:
        # Create controller in simulation mode
        print("Creating controller in simulation mode...")
        sim_controller = aerotechController(address=controller_address, simulation=True)
        sim_controller.initialize()
        sim_controller.connect()
        
        # Create motor in simulation mode
        print("Creating motor in simulation mode...")
        sim_motor = aerotechMotor(controller=sim_controller)
        sim_motor.connect(axis=test_axis)
        
        # Test simulation operations
        print("Testing simulation operations...")
        sim_pos = sim_motor.getPos()
        print(f"  Simulation position: {sim_pos}")
        
        sim_status = sim_motor.getDetailedStatus()
        print(f"  Simulation status: {sim_status}")
        
        # Test simulation limits
        sim_limits = sim_motor.checkLimits(5.0)
        print(f"  Simulation limits check: {sim_limits}")
        
        print("Simulation mode tests completed")
        
        return None  # Return None for continuation
        
    except Exception as e:
        print(f"Simulation mode test failed: {e}")
        return None

def test_error_handling(controller, motor):
    """Test error handling scenarios"""
    print("\n" + "="*60)
    print("TEST: Error Handling")
    print("="*60)
    
    try:
        # Test invalid axis operations
        print("Testing invalid axis operations...")
        try:
            err, pos = controller.getPosition("INVALID_AXIS")
            print(f"  Invalid axis position result: {err}, {pos}")
        except Exception as e:
            print(f"  Invalid axis handled properly: {e}")
        
        # Test connection with invalid address
        print("\nTesting invalid connection...")
        invalid_controller = aerotechController(address="192.168.1.999")
        invalid_controller.initialize()
        result = invalid_controller.connect()
        print(f"  Invalid connection result: {result}")
        
        return motor
        
    except Exception as e:
        print(f"Error handling test failed: {e}")
        return None

def test_configuration_validation(controller, motor):
    """Test configuration and parameter validation"""
    print("\n" + "="*60)
    print("TEST: Configuration Validation")
    print("="*60)
    
    try:
        # Test motor configuration
        print("Testing motor configuration...")
        config = motor.config
        print(f"  Units: {config['units']}")
        print(f"  Offset: {config['offset']}")
        print(f"  Min value: {config['minValue']}")
        print(f"  Max value: {config['maxValue']}")
        
        # Test controller configuration
        print("\nTesting controller configuration...")
        print(f"  Address: {controller.address}")
        print(f"  Port: {controller.port}")
        print(f"  Simulation: {controller.simulation}")
        
        return motor
        
    except Exception as e:
        print(f"Configuration validation failed: {e}")
        return None

def test_axis_discovery(controller):
    """Test comprehensive axis discovery"""
    print("\n" + "="*60)
    print("TEST: Axis Discovery")
    print("="*60)
    
    try:
        # Test the enhanced getAxes method
        print("Testing enhanced getAxes method...")
        axes = controller.getAxes()
        print(f"\nTotal axes discovered: {len(axes)}")
        print(f"Axes found: {axes}")
        
        # Compare with expected axes from motorConfig.json
        print("\nExpected axes from motorConfig.json:")
        expected_axes = [
            "x", "y",  # MCL motors (lowercase)
            "X",  # Xeryon motor (uppercase)
            "DetectorY",  # BCS motor
            "BL7012:OSA_X", "BL7012:OSA_Y", "BL7012:OSA_Z",  # EPICS motors
            "x", "y"  # XPS motors (lowercase)
        ]
        print(f"Expected: {expected_axes}")
        
        # Check for missing axes
        missing_axes = [axis for axis in expected_axes if axis not in axes]
        if missing_axes:
            print(f"\nMissing axes: {missing_axes}")
        else:
            print("\nAll expected axes found!")
        
        # Check for unexpected axes
        unexpected_axes = [axis for axis in axes if axis not in expected_axes]
        if unexpected_axes:
            print(f"Unexpected axes found: {unexpected_axes}")
        
        return controller
        
    except Exception as e:
        print(f"Axis discovery test failed: {e}")
        return None


# =============================================================================
# PHYSICAL TESTS (Physical movement)
# =============================================================================

def test_axis_enable_disable(motor):
    """Test axis enable/disable functionality"""
    print("\n" + "="*60)
    print("TEST: Axis Enable/Disable (PHYSICAL)")
    print("="*60)
    print("WARNING: This test will enable/disable the axis")
    
    try:
        # Test axis disable
        print("Disabling axis...")
        disable_result = motor.disable()
        print(f"  Disable result: {disable_result}")
        
        # Wait for disable to complete
        print("  Waiting for disable to complete...")
        time.sleep(2)
        
        # Check if disabled
        is_enabled = motor.isEnabled()
        print(f"  Axis enabled after disable: {is_enabled}")
        
        # Test axis enable
        print("\nEnabling axis...")
        enable_result = motor.enable()
        print(f"  Enable result: {enable_result}")
        
        # Wait for enable to complete
        print("  Waiting for enable to complete...")
        time.sleep(3)
        
        # Check if enabled
        is_enabled = motor.isEnabled()
        print(f"  Axis enabled after enable: {is_enabled}")
        
        return motor
        
    except Exception as e:
        print(f"Axis enable/disable test failed: {e}")
        return None

def test_homing(motor):
    """Test axis homing functionality"""
    print("\n" + "="*60)
    print("TEST: Axis Homing (PHYSICAL)")
    print("="*60)
    print("WARNING: This test will home the axis")
    
    try:
        # Test homing
        print("Homing axis...")
        home_result = motor.home()
        print(f"  Home result: {home_result}")
        
        # Wait for homing to complete (homing can take significant time)
        print("  Waiting for homing to complete...")
        print("  This may take 10-30 seconds depending on the axis...")
        
        # Monitor homing progress
        start_time = time.time()
        timeout = 60  # 60 second timeout for homing
        while time.time() - start_time < timeout:
            is_homed = motor.isHomed()
            is_enabled = motor.isEnabled()
            print(f"    Time elapsed: {time.time() - start_time:.1f}s, Homed: {is_homed}, Enabled: {is_enabled}")
            
            if is_homed:
                print("  Homing completed successfully!")
                break
                
            time.sleep(2)  # Check every 2 seconds
        else:
            print("  Homing timeout reached!")
        
        # Final check
        is_homed = motor.isHomed()
        print(f"  Final homed status: {is_homed}")
        
        return motor
        
    except Exception as e:
        print(f"Homing test failed: {e}")
        return None

def test_move_to_absolute(motor, safe_move_distance):
    """Test absolute movement functionality"""
    print("\n" + "="*60)
    print("TEST: Absolute Movement (PHYSICAL)")
    print("="*60)
    print("WARNING: This test will move the axis")
    
    try:
        # Get current position and store as original position
        original_pos = motor.getPos()
        current_pos = original_pos
        print(f"\nOriginal position: {original_pos:.6f}")
        print(f"Moving distance: {safe_move_distance:.6f}")
        
        # Calculate safe target position
        move_distance = safe_move_distance
        if not motor.checkLimits(original_pos + move_distance):
            move_distance = -safe_move_distance
        
        print(f"Moving to target position: {original_pos + move_distance:.6f}")
        
        # Perform movement
        motor.moveTo(original_pos + move_distance)
        
        # Wait for movement to complete with monitoring
        print("  Waiting for movement to complete...")
        start_time = time.time()
        timeout = 30  # 30 second timeout for movement
        target_position = original_pos + move_distance
        position_tolerance = 0.01  # Consider arrived if within this distance of target
        
        while time.time() - start_time < timeout:
            status = motor.getDetailedStatus()
            current_pos = motor.getPos()
            print(f"    Time elapsed: {time.time() - start_time:.1f}s, Position: {current_pos:.6f}, Moving: {status['moving']}")
            
            # Check if controller reports movement complete
            if not status['moving'] and status['in_position']:
                print("  Movement completed successfully!")
                break
            
            # Backup: position-based completion check
            if abs(current_pos - target_position) <= position_tolerance:
                print(f"  Movement completed (reached target within {position_tolerance} tolerance)!")
                break
                
            time.sleep(0.5)  # Check every 0.5 seconds
        
        # Check final position
        final_pos = motor.getPos()
        print(f"Final position: {final_pos:.6f}")
        
        # Wait before returning to original position
        print("  Waiting 2 seconds before return movement...")
        time.sleep(2)
        
        # Return to original position
        print(f"Returning to original position: {original_pos:.6f}")
        motor.moveTo(original_pos)
        
        # Wait for return movement to complete
        print("  Waiting for return movement to complete...")
        start_time = time.time()
        return_target_position = original_pos  # Should return to original position
        position_tolerance = 0.01  # Consider arrived if within this distance of target
        
        while time.time() - start_time < timeout:
            status = motor.getDetailedStatus()
            current_pos = motor.getPos()
            print(f"    Time elapsed: {time.time() - start_time:.1f}s, Position: {current_pos:.6f}, Moving: {status['moving']}")
            
            # Check if controller reports movement complete
            if not status['moving'] and status['in_position']:
                print("  Return movement completed successfully!")
                break
            
            # Backup: position-based completion check
            if abs(current_pos - return_target_position) <= position_tolerance:
                print(f"  Return movement completed (reached target within {position_tolerance} tolerance)!")
                break
                
            time.sleep(0.5)
        
        return motor
        
    except Exception as e:
        print(f"Absolute movement test failed: {e}")
        return None

def test_move_by_increment(motor, safe_move_distance):
    """Test relative movement functionality"""
    print("\n" + "="*60)
    print("TEST: Relative Movement (PHYSICAL)")
    print("="*60)
    print("WARNING: This test will move the axis")
    
    try:
        # Get current position
        current_pos = motor.getPos()
        print(f"\nCurrent position: {current_pos:.6f}")
        
        # Perform relative movement
        move_distance = safe_move_distance
        print(f"Moving by: {move_distance:.6f}")
        
        motor.moveBy(move_distance)
        
        # Wait for movement to complete with monitoring
        print("  Waiting for movement to complete...")
        start_time = time.time()
        timeout = 30  # 30 second timeout for movement
        
        while time.time() - start_time < timeout:
            status = motor.getDetailedStatus()
            current_pos = motor.getPos()
            print(f"    Time elapsed: {time.time() - start_time:.1f}s, Position: {current_pos:.6f}, Moving: {status['moving']}")
            
            if not status['moving'] and status['in_position']:
                print("  Movement completed successfully!")
                break
                
            time.sleep(0.5)  # Check every 0.5 seconds
        else:
            print("  Movement timeout reached!")
        
        # Check position after relative move
        new_pos = motor.getPos()
        print(f"Position after relative move: {new_pos:.6f}")
        
        # Wait before return movement
        print("  Waiting 2 seconds before return movement...")
        time.sleep(2)
        
        # Return to original position
        print(f"Returning to original position by moving: {-move_distance:.6f}")
        motor.moveBy(-move_distance)
        
        # Wait for return movement to complete
        print("  Waiting for return movement to complete...")
        start_time = time.time()
        last_position = new_pos  # Start from the position after first move
        position_stable_start = None
        position_tolerance = 0.001  # Consider stable if position changes less than this
        stable_time_required = 2.0  # Seconds of stable position to consider stopped
        
        while time.time() - start_time < timeout:
            status = motor.getDetailedStatus()
            current_pos = motor.getPos()
            print(f"    Time elapsed: {time.time() - start_time:.1f}s, Position: {current_pos:.6f}, Moving: {status['moving']}")
            
            # Check if controller reports movement complete
            if not status['moving'] and status['in_position']:
                print("  Return movement completed successfully!")
                break
            
            # Backup: position-based movement detection
            position_change = abs(current_pos - last_position)
            if position_change < position_tolerance:
                # Position is stable
                if position_stable_start is None:
                    position_stable_start = time.time()
                elif time.time() - position_stable_start >= stable_time_required:
                    print(f"  Return movement completed (position stable for {stable_time_required}s)!")
                    break
            else:
                # Position is still changing
                position_stable_start = None
                last_position = current_pos
                
            time.sleep(0.5)
        
        return motor
        
    except Exception as e:
        print(f"Relative movement test failed: {e}")
        return None

def test_emergency_stop(motor, safe_move_distance):
    """Test emergency stop functionality"""
    print("\n" + "="*60)
    print("TEST: Emergency Stop (PHYSICAL)")
    print("="*60)
    print("WARNING: This test will move and stop the axis")
    
    try:
        # Start a movement
        print("\nStarting movement for emergency stop test...")
        motor.moveBy(safe_move_distance)
        
        # Wait a short time then stop
        print("  Waiting 1 second before emergency stop...")
        time.sleep(1)

        # Check if its moving
        is_moving = motor.getStatus()
        print(f"  Motor moving after sleep: {is_moving}")

        print("  Executing emergency stop...")
        motor.stop()
        
        # Wait for stop to complete
        print("  Waiting for stop to complete...")
        time.sleep(2)
        
        # Check if stopped
        is_moving = motor.getStatus()
        print(f"  Motor moving after stop: {is_moving}")
        
        # Get final position
        final_pos = motor.getPos()
        print(f"  Final position after emergency stop: {final_pos:.6f}")
        
        return motor
        
    except Exception as e:
        print(f"Emergency stop test failed: {e}")
        return None

def test_motion_monitoring(motor, safe_move_distance):
    """Test motion monitoring during movement"""
    print("\n" + "="*60)
    print("TEST: Motion Monitoring (PHYSICAL)")
    print("="*60)
    print("WARNING: This test will move the axis")
    
    try:
        # Get starting position to calculate target
        start_position = motor.getPos()
        target_position = start_position + safe_move_distance
        
        # Start movement and monitor
        print(f"\nStarting movement with monitoring...")
        print(f"  Start position: {start_position:.6f}")
        print(f"  Target position: {target_position:.6f}")
        print(f"  Move distance: {safe_move_distance:.6f}")
        motor.moveBy(safe_move_distance)
        
        # Monitor during movement
        print("  Monitoring movement...")
        start_time = time.time()
        timeout = 30  # 30 second timeout
        
        while time.time() - start_time < timeout:
            status = motor.getDetailedStatus()
            current_pos = status['position']
            delta_from_target = abs(current_pos - target_position)
            elapsed = time.time() - start_time
            
            print(f"    Time {elapsed:.1f}s: Pos={current_pos:.6f}, Target={target_position:.6f}, Delta={delta_from_target:.6f}, Moving={status['moving']}, InPosition={status['in_position']}")
            
            # Stop monitoring if movement is complete
            if not status['moving'] and status['in_position']:
                print(f"  Movement completed! Final delta from target: {delta_from_target:.6f}")
                break
                
            time.sleep(0.2)  # Monitor every 0.2 seconds
        else:
            print("  Monitoring timeout reached!")
        
        # Wait before return movement
        print("  Waiting 2 seconds before return movement...")
        time.sleep(2)
        
        # Return to original position
        return_target = start_position  # Return to original starting position
        print(f"  Starting return movement...")
        print(f"  Return target: {return_target:.6f}")
        motor.moveBy(-safe_move_distance)
        
        # Monitor return movement
        print("  Monitoring return movement...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = motor.getDetailedStatus()
            current_pos = status['position']
            delta_from_return_target = abs(current_pos - return_target)
            elapsed = time.time() - start_time
            
            print(f"    Time {elapsed:.1f}s: Pos={current_pos:.6f}, Target={return_target:.6f}, Delta={delta_from_return_target:.6f}, Moving={status['moving']}, InPosition={status['in_position']}")
            
            if not status['moving'] and status['in_position']:
                print(f"  Return movement completed! Final delta from target: {delta_from_return_target:.6f}")
                break
                
            time.sleep(0.2)
        else:
            print("  Return movement timeout reached!")
        
        return motor
        
    except Exception as e:
        print(f"Motion monitoring test failed: {e}")
        return None

# =============================================================================
# TEST RUNNERS
# =============================================================================

def run_safe_tests(controller_address, controller_port, test_axis):
    """Run all safe tests (no physical movement)
    
    This function contains ONLY read-only operations and configuration tests.
    NO physical movement will occur during these tests.
    
    Safe operations include:
    - Controller creation and connection
    - Motor creation and connection
    - Position and status reading
    - Configuration validation
    - Error handling
    - Simulation mode testing
    
    Physical operations are NOT included:
    - No enable/disable operations
    - No homing operations
    - No movement commands (moveTo, moveBy)
    - No emergency stop operations
    """

    print("\n" + "="*60)
    print("RUNNING SAFE TESTS (No Physical Movement)")
    print("="*60)
    print("NOTE: These tests are 100% safe - no physical movement will occur")
    print("="*60)
    
    try:
        # Create controller
        controller = test_controller_creation(controller_address, controller_port)
        if controller is None:
            return False
                
        # Connect controller
        controller = test_controller_connection(controller)
        if controller is None:
            return False
        
        # Create motor
        motor = test_motor_creation(controller)
        if motor is None:
            return False
        
        # Connect motor
        motor = test_motor_connection(motor, test_axis)
        if motor is None:
            return False
                
        # Run all safe tests
        motor = test_position_reading(motor)
        if motor is None:
            return False
        
        
        motor = test_status_reading(motor)
        if motor is None:
            return False
        
        motor = test_limits_checking(motor)
        if motor is None:
            return False
                
        motor = test_controller_methods(controller, motor)
        if motor is None:
            return False
        
        
        motor = test_error_handling(controller, motor)
        if motor is None:
            return False
        
        motor = test_configuration_validation(controller, motor)
        if motor is None:
            return False
        
        # Test axis discovery
        controller = test_axis_discovery(controller)
        if controller is None:
            return False
        '''
        # Test simulation mode separately
        test_simulation_mode(controller_address, controller_port, test_axis)
        '''

        print("\n" + "="*60)
        print("ALL SAFE TESTS COMPLETED SUCCESSFULLY")
        print("="*60)
        return True
        
    except Exception as e:
        print(f"\nSafe tests failed with exception: {e}")
        return False

def run_physical_tests(controller_address, controller_port, test_axis, safe_move_distance):
    """Run all physical tests (with physical movement)"""
    print("\n" + "="*60)
    print("RUNNING PHYSICAL TESTS (Physical Movement)")
    print("="*60)
    print("WARNING: These tests will move the hardware")
    print("Ensure no obstacles are in the way")
    
    try:
        # Create controller
        controller = test_controller_creation(controller_address, controller_port)
        if controller is None:
            return False
        
        # Connect controller
        controller = test_controller_connection(controller)
        if controller is None:
            return False
        
        # Create motor
        motor = test_motor_creation(controller)
        if motor is None:
            return False
        
        # Connect motor
        motor = test_motor_connection(motor, test_axis)
        if motor is None:
            return False
        
        # Run all physical tests
        motor = test_axis_enable_disable(motor)
        if motor is None:
            return False
        
        #motor = test_homing(motor)
        #if motor is None:
        #    return False
                
        #motor = test_move_to_absolute(motor, safe_move_distance)
        #if motor is None:
        #    return False
        
        #motor = test_move_by_increment(motor, safe_move_distance)
        #if motor is None:
        #    return False
        
        #motor = test_emergency_stop(motor, safe_move_distance)
        #if motor is None:
        #     return False
        
        #motor = test_motion_monitoring(motor, safe_move_distance)
        #if motor is None:
        #    return False
        
        print("\n" + "="*60)
        print("ALL PHYSICAL TESTS COMPLETED SUCCESSFULLY")
        print("="*60)
        return True
        
    except Exception as e:
        print(f"\nPhysical tests failed with exception: {e}")
        return False

# =============================================================================
# MAIN FUNCTION
# =============================================================================

def main():
    """Main test runner"""
    print("Aerotech Controller and Motor Test Suite")
    print("========================================")
    
    # Configuration moved to main
    controller_address = '192.168.1.110'
    controller_port = 12200  # Using 12201 to avoid communication as noted
    test_axis = "XCoarse"  # Primary test axis
    safe_move_distance = 1  # Small safe movement for testing
    timeout_seconds = 10.0
    
    print(f"Controller Address: {controller_address}")
    print(f"Controller Port: {controller_port}")
    print(f"Test Axis: {test_axis}")
    print(f"Safe Move Distance: {safe_move_distance}")
    print("="*60)
    
    # Run safe tests
    # safe_success = run_safe_tests(controller_address, controller_port, test_axis)
    
    # Run physical tests (commented out for safety)
    # Uncomment the following line to run physical tests
    physical_success = run_physical_tests(controller_address, controller_port, test_axis, safe_move_distance)
    

if __name__ == "__main__":
    main() 


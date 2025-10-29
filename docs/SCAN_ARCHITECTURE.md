# STXM Scan Architecture

This document describes the scan architecture refactoring that introduces an abstract base class for all scan types.

## Overview

The scan system has been refactored to use an object-oriented architecture with a `BaseScan` abstract base class that encapsulates common functionality shared across different scan types.

## Architecture

### BaseScan Abstract Class

**Location:** `pystxmcontrol/controller/scans/base_scan.py`

The `BaseScan` class provides:

#### Common Functionality
- **DAQ Configuration**: Setup and metadata management for data acquisition systems
- **Motor Control**: Trajectory setup, positioning, and coarse/fine coordination
- **Energy Handling**: Energy changes with automatic focus control
- **Timing Management**: Dwell time calculations respecting hardware constraints
- **Trigger Management**: Position trigger setup and control
- **Scan Control**: Abort handling, region management

#### Abstract Methods

Subclasses must implement:

1. **`execute_scan()`**: Main scan execution logic
   - Defines the scan loop structure (energy, regions, lines, points, etc.)
   - Calls helper methods from BaseScan
   - Returns True on success, False on abort/error

2. **`setup_scan_geometry()`**: Scan-specific geometric setup (optional override)
   - Configures trajectories
   - Sets motor parameters
   - Calculates scan-specific values

### Key Methods in BaseScan

#### DAQ Methods
- `setup_daqs()`: Initialize DAQ metadata and configurations
- `get_daq_timing_parameters()`: Extract timing constraints from DAQs
- `calculate_actual_dwell()`: Compute actual dwell times respecting hardware limits
- `configure_daqs()`: Configure all DAQs with specified parameters

#### Motor Methods
- `setup_motor_trajectory()`: Configure motor trajectory parameters
- `move_coarse_to_range()`: Position coarse motors to bring range into fine range
- `setup_position_trigger()`: Enable position-based triggering
- `disable_position_trigger()`: Disable position triggering
- `update_motor_positions()`: Read and store current motor positions

#### Energy Methods
- `handle_energy_and_focus()`: Move to energy and handle autofocus

#### Scan Control Methods
- `check_abort()`: Check if abort has been requested
- `handle_abort()`: Process abort request and cleanup
- `get_scan_region_geometry()`: Extract region geometry parameters

## Example Implementation: DerivedLineImageScan

**Location:** `pystxmcontrol/controller/scans/derived_line_image_v2.py`

This is a refactored version of the continuous flyscan line image scan.

### Class Structure

```python
class DerivedLineImageScan(BaseScan):
    async def execute_scan(self) -> bool:
        # Loop through energies and regions
        for energy in energies:
            await self.process_energy(energy, ...)
            for region in regions:
                await self.process_region(region, ...)
                for line in y_positions:
                    await doFlyscanLine(...)
        return True

    def setup_region_geometry(self, geometry, region_index):
        # Configure trajectories for this region
        self.setup_motor_trajectory(...)
```

### Key Features

1. **Separation of Concerns**:
   - Energy processing separated from region processing
   - Line scanning logic isolated in dedicated method
   - Geometry setup separate from scan execution

2. **Code Reuse**:
   - Uses BaseScan methods for common operations
   - Minimal duplication compared to original implementation

3. **Readability**:
   - Clear method names describing intent
   - Logical flow from high-level to low-level operations

4. **Maintainability**:
   - Changes to timing, DAQ config, or motor control can be made in BaseScan
   - Scan-specific logic remains in subclass

## Usage

### Using the Refactored Scan

The refactored scan can be used in two ways:

#### 1. Direct Class Usage (Recommended for new code)
```python
from pystxmcontrol.controller.scans import DerivedLineImageScan

scan_instance = DerivedLineImageScan(scan, dataHandler, controller, queue)
result = await scan_instance.run()
```

#### 2. Functional Interface (Backward compatible)
```python
from pystxmcontrol.controller.scans import derived_line_image_v2

result = await derived_line_image_v2(scan, dataHandler, controller, queue)
```

### Creating New Scan Types

To create a new scan type:

1. **Subclass BaseScan**:
```python
from pystxmcontrol.controller.scans.base_scan import BaseScan

class MyCustomScan(BaseScan):
    pass
```

2. **Override `initialize_scan_info()` (optional)**:
```python
async def initialize_scan_info(self):
    await super().initialize_scan_info()
    self.scanInfo.update({
        "mode": "my_mode",
        "custom_parameter": value
    })
```

3. **Implement `execute_scan()`**:
```python
async def execute_scan(self) -> bool:
    # Get data
    energies = self.dataHandler.data.energies["default"]

    # Setup DAQs (if not using default setup)
    # self.setup_daqs() is called automatically by run()

    # Execute scan loop
    for energy in energies:
        # Use BaseScan helper methods
        self.handle_energy_and_focus(energy, index)

        # Check for abort
        if await self.check_abort():
            return await self.handle_abort(region, motor, "Aborted")

        # Do scan-specific work
        await self.do_custom_scan_work()

    # Cleanup and return
    return await terminateFlyscan(...)
```

4. **Add helper methods as needed**:
```python
async def do_custom_scan_work(self):
    # Scan-specific logic
    pass

def setup_custom_geometry(self):
    # Custom geometry setup
    geometry = self.get_scan_region_geometry(0)
    # Configure motors, trajectories, etc.
```

## Migration Guide

### Converting Existing Scans

To convert an existing scan function to use `BaseScan`:

1. **Create class inheriting from BaseScan**
2. **Move initialization code to `initialize_scan_info()`**
3. **Move main scan loop to `execute_scan()`**
4. **Replace direct controller calls with BaseScan methods**:
   - Motor moves → `self.handle_energy_and_focus()`, `self.setup_motor_trajectory()`
   - DAQ config → `self.configure_daqs()`
   - Position updates → `self.update_motor_positions()`
   - Abort checks → `await self.check_abort()`, `await self.handle_abort()`
5. **Create helper methods for complex sections**
6. **Provide functional wrapper for backward compatibility**

### Example Conversion

**Before:**
```python
async def my_scan(scan, dataHandler, controller, queue):
    energies = dataHandler.data.energies["default"]
    for energy in energies:
        controller.moveMotor("Energy", energy)
        # ... scan logic ...
```

**After:**
```python
class MyScan(BaseScan):
    async def execute_scan(self):
        energies = self.dataHandler.data.energies["default"]
        for energy_index, energy in enumerate(energies):
            self.handle_energy_and_focus(energy, energy_index)
            # ... scan logic using self.controller, self.dataHandler ...
        return True

async def my_scan(scan, dataHandler, controller, queue):
    """Backward compatible wrapper"""
    return await MyScan(scan, dataHandler, controller, queue).run()
```

## Benefits

### Code Organization
- **Separation of concerns**: Common functionality separate from scan-specific logic
- **Single responsibility**: Each method has a clear, focused purpose
- **Logical hierarchy**: High-level flow separate from low-level operations

### Maintainability
- **Centralized common code**: Bug fixes and improvements apply to all scans
- **Easier testing**: Can test common functionality once in BaseScan
- **Clear contracts**: Abstract methods define what subclasses must implement

### Extensibility
- **Easy to add new scans**: Just inherit and implement abstract methods
- **Code reuse**: Inherit all common functionality automatically
- **Customization points**: Can override any method for special behavior

### Readability
- **Self-documenting**: Method names describe what they do
- **Consistent patterns**: All scans follow same structure
- **Less duplication**: Common code not repeated in each scan

## File Structure

```
pystxmcontrol/controller/scans/
├── __init__.py                      # Exports all scan types
├── base_scan.py                     # Abstract base class
├── derived_line_image.py            # Original implementation
├── derived_line_image_v2.py         # Refactored implementation
├── scan_utils.py                    # Utility functions
├── SCAN_ARCHITECTURE.md            # This document
└── [other scan implementations]     # Other scan types
```

## Future Work

### Recommended Next Steps

1. **Convert other scan types**: Apply this pattern to:
   - `derived_line_focus`
   - `derived_line_spectrum`
   - `single_motor_scan`
   - `double_motor_scan`
   - Others as needed

2. **Add more helper methods**: Extract common patterns into BaseScan methods

3. **Improve error handling**: Standardize error handling across all scans

4. **Add logging**: Integrate operation logger into BaseScan

5. **Configuration management**: Move magic numbers to config

6. **Testing**: Create unit tests for BaseScan and integration tests for scans

### Potential Enhancements

- **Retry logic**: Add configurable retry for missed triggers in BaseScan
- **Progress tracking**: Built-in progress reporting
- **Pause/resume**: Standard pause/resume functionality
- **Validation**: Parameter validation before scan start
- **Metrics**: Built-in timing and performance metrics

## References

### Related Files
- `pystxmcontrol/controller/controller.py` - Main controller
- `pystxmcontrol/controller/dataHandler.py` - Data handling
- `pystxmcontrol/drivers/` - Motor drivers

### Design Patterns
- Template Method Pattern (BaseScan.run() calls abstract execute_scan())
- Strategy Pattern (Different scan strategies via subclasses)

---

**Version:** 1.0
**Date:** 2025-10-29
**Author:** Claude Code refactoring

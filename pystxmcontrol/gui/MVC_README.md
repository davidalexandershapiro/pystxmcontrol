# MVC Architecture Refactoring

This directory contains the refactored version of the mainwindow.py using Model-View-Controller (MVC) architecture.

## Architecture Overview

The MVC refactoring separates concerns into three main components:

### Models (`models/` directory)
- **BaseModel**: Abstract base class providing common functionality for all models
- **ScanModel**: Manages scan configuration, regions, and calculations
- **MotorModel**: Handles motor positions, status, and limits
- **ImageModel**: Manages image data, display settings, and cursor information

### Controllers (`controllers/` directory)
- **MainController**: Coordinates between models and views, handles business logic

### Views
- **MainWindowMVC**: Refactored main window focused on UI interactions and display

## Key Benefits

1. **Separation of Concerns**: Business logic is separated from UI code
2. **Testability**: Models and controllers can be unit tested independently
3. **Maintainability**: Changes to data structures don't require UI changes
4. **Reusability**: Models can be reused in different contexts
5. **Signal/Slot Architecture**: Clean communication between components

## Usage

To use the MVC version instead of the original:

```python
from pystxmcontrol.gui.mainwindow_mvc import MainWindowMVC

# Create the main window
window = MainWindowMVC()
window.show()
```

Or run the standalone application:

```bash
python pystxmcontrol/gui/app_mvc.py
```

## File Structure

```
gui/
├── models/
│   ├── __init__.py
│   ├── base_model.py      # Base model class
│   ├── scan_model.py      # Scan configuration model
│   ├── motor_model.py     # Motor control model
│   └── image_model.py     # Image display model
├── controllers/
│   ├── __init__.py
│   └── main_controller.py # Main application controller
├── mainwindow_mvc.py      # Refactored main window (View)
├── app_mvc.py            # Application entry point
└── MVC_README.md         # This file
```

## Migration Notes

The original `mainwindow.py` has been refactored into:

1. **Models**: Data and business logic extracted to separate model classes
2. **Controller**: User interactions and coordination logic moved to MainController
3. **View**: UI-specific code remains in MainWindowMVC

### Key Changes

- **Data Management**: All data is now managed through model classes with proper validation
- **Business Logic**: Scan calculations, motor limits, and validation moved to models
- **Communication**: Controller mediates all communication between models and views
- **Signals**: Clean signal/slot architecture for loose coupling

### Original Functionality Preserved

All original functionality is preserved but reorganized:
- Scan configuration and execution
- Motor control and monitoring
- Image display and manipulation
- Real-time monitor plot updates
- DAQ current value display
- File operations (save/load scan definitions)
- Theme management
- Real-time data updates

## Testing

The MVC architecture enables better testing:

```python
# Test models independently
scan_model = ScanModel()
scan_model.set_scan_type("Image")
assert scan_model.validate()

# Test controller logic
controller = MainController()
success = controller.move_motor("SampleX", 10.0)
assert success
```

## Future Enhancements

The MVC architecture makes it easier to add:
- Multiple views (different UI layouts)
- Remote control interfaces
- Automated testing
- Plugin systems
- Alternative data sources

## Compatibility

The MVC version maintains compatibility with the existing client and server infrastructure while providing a cleaner, more maintainable codebase.
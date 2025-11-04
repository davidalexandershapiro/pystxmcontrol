from PySide6.QtCore import QObject, Signal, QThread
from typing import Dict, Any, Optional
import time
import sys
import numpy as np
from queue import Queue

from ..models.scan_model import ScanModel
from ..models.motor_model import MotorModel
from ..models.image_model import ImageModel
from ...controller.client import stxm_client


class ControlThread(QThread):
    """Thread for handling client communication."""
    
    controlResponse = Signal(object)
    
    def __init__(self, client, message_queue):
        QThread.__init__(self)
        self.message_queue = message_queue
        self.client = client
        self.monitor = True
        
    def run(self):
        while self.monitor:
            message = self.message_queue.get(True)
            if message != "exit":
                response = self.client.send_message(message)
                if response is None:
                    response = {"command": message["command"], "status": "No response from server"}
                self.controlResponse.emit(response)
            else:
                return


class MainController(QObject):
    """Main controller that coordinates between models and views."""
    
    # Signals for view updates
    motor_position_updated = Signal(str, float)  # motor_name, position
    motor_status_updated = Signal(str, bool)     # motor_name, is_moving
    image_updated = Signal(object)               # image data
    scan_progress_updated = Signal(str)          # progress info
    error_occurred = Signal(str)                 # error message
    status_updated = Signal(str)                 # status message
    monitor_data_updated = Signal()              # monitor plot needs update
    daq_value_updated = Signal(float)            # DAQ current value
    scan_state_changed = Signal(bool)            # scanning state changed (True=scanning, False=completed)
    estimated_time_updated = Signal(float)       # estimated scan time updated
    elapsed_time_updated = Signal(float)         # elapsed scan time updated
    
    def __init__(self):
        super().__init__()
        
        # Initialize models
        self.scan_model = ScanModel()
        self.motor_model = MotorModel()
        self.image_model = ImageModel()
        
        # Initialize client and communication
        self.client = stxm_client()
        self.message_queue = Queue()
        self.control_thread = None
        
        # State tracking
        self.scanning = False
        self.server_status = False
        self.exiting = False
        
        # Connect model signals
        self._connect_model_signals()
        
    def _connect_model_signals(self):
        """Connect model signals to controller methods."""
        self.scan_model.data_changed.connect(self._on_scan_model_changed)
        self.motor_model.data_changed.connect(self._on_motor_model_changed)
        self.image_model.data_changed.connect(self._on_image_model_changed)
        
    def _on_scan_model_changed(self, property_name: str, value: Any):
        """Handle scan model changes."""
        if property_name in ['scan_regions', 'energy_regions']:
            self.image_model.set('energy_list',self.scan_model.get_energies())
            # Recalculate estimated time when scan parameters change
            estimated_time = self.scan_model.calculate_estimated_time()
            # Emit signal for view to update
            self.estimated_time_updated.emit(estimated_time)
            
    def _on_motor_model_changed(self, property_name: str, value: Any):
        """Handle motor model changes."""
        if property_name == 'current_positions':
            for motor_name, position in value.items():
                self.motor_position_updated.emit(motor_name, position)
        elif property_name == 'motor_status':
            for motor_name, is_moving in value.items():
                self.motor_status_updated.emit(motor_name, is_moving)
                
    def _on_image_model_changed(self, property_name: str, value: Any):
        """Handle image model changes."""
        if property_name == 'current_image':
            self.image_updated.emit(value)
        elif property_name == 'monitor_data':
            # Monitor data updated, trigger plot update
            self.monitor_data_updated.emit()
        elif property_name == 'daq_current_value':
            # DAQ value updated
            self.daq_value_updated.emit(value)
        elif property_name in ['cursor_x', 'cursor_y', 'cursor_intensity']:
            # Cursor position updates could be handled here
            pass
            
    def initialize_client(self):
        """Initialize the client connection."""
        try:
            # Set up control thread
            self.control_thread = ControlThread(self.client, self.message_queue)
            self.control_thread.start()
            self.control_thread.controlResponse.connect(self._handle_client_response)
            
            # Get configuration
            self.client.get_config()
            self.motor_model.set_motor_info(self.client.motorInfo)
            
            # Initialize motor positions from client
            self._initialize_motor_positions()
            
            # Connect to client monitor for real-time updates
            self._connect_client_monitors()
            
            self.server_status = True
            self.status_updated.emit("Connected to server")
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to connect to server: {str(e)}")
            self.server_status = False
            return False
            
    def _initialize_motor_positions(self):
        """Initialize motor positions from client."""
        try:
            if hasattr(self.client, 'currentMotorPositions') and self.client.currentMotorPositions:
                # Update motor model with current positions
                for motor_name, position in self.client.currentMotorPositions.items():
                    if isinstance(position, (int, float)):
                        self.motor_model.update_position(motor_name, position)
                        
            # Set default status (all motors not moving initially)
            motor_info = self.motor_model.get('motor_info', {})
            for motor_name in motor_info.keys():
                self.motor_model.update_status(motor_name, False)
                
        except Exception as e:
            print(f"Warning: Could not initialize motor positions: {e}")
            
    def _connect_client_monitors(self):
        """Connect to client monitor signals for real-time updates."""
        try:
            # Connect to scan data monitor for motor positions and image updates
            self.client.monitor.scan_data.connect(self._handle_monitor_message)
            
            # Try to connect to other monitors
            try:
                self.client.ccd.framedata.connect(self._handle_ccd_data)
            except:
                pass  # CCD monitor not available
                
            try:
                self.client.ptycho.ptychoData.connect(self._handle_ptycho_data)
            except:
                pass  # Ptycho monitor not available
                
        except Exception as e:
            print(f"Warning: Could not connect all monitors: {e}")
            
    def _handle_client_response(self, response):
        """Handle responses from client commands."""
        # Emit response for any views that need it
        status_message = response["command"] + ": " + str(response["status"])
        if response["status"]:
            pass
        else:
            self.status_updated.emit(f"Command response: {response.get('status', 'Unknown')}")
        
    def _handle_monitor_message(self, message):
        """Handle real-time monitor messages from client.  These messages are python dictionaries which 
        contain the data and it's definition for live display.  It may either be the idle monitor stream
        or the data images during a scan."""
        # Handle scan completion
        if message == "scan_complete":
            self.scanning = False
            self.status_updated.emit("Scan completed")
            self.scan_state_changed.emit(False)  # Signal scan completed
        try:
            # Extract motor positions and status
            if 'motorPositions' in message:
                motor_positions = message['motorPositions']
                motor_status = message['motorPositions'].get('status', {})
                
                # Update motor model
                for motor_name, position in motor_positions.items():
                    if motor_name != 'status' and isinstance(position, (int, float)):
                        self.motor_model.update_position(motor_name, position)
                        
                # Update motor status
                for motor_name, is_moving in motor_status.items():
                    self.motor_model.update_status(motor_name, is_moving)
                    
            # Handle monitor data for plotting
            if message["mode"] == "monitor" and isinstance(message['data'], np.ndarray) and len(message['data']) > 0:
                monitor_value = message['data'][0]
                self.image_model.add_monitor_data(monitor_value, max_points=500)
                
                # Update current DAQ value display
                daq_display_value = monitor_value * 10.0  # Scale factor from original
                self.image_model.set('daq_current_value', daq_display_value)
                
                # Signals will be emitted automatically by model changes
                    
            # Handle elapsed time from scan messages
            elif 'elapsedTime' in message:
                elapsed_time = message['elapsedTime']
                self.elapsed_time_updated.emit(float(elapsed_time))
                
            # Handle image data
            if 'image' in message and message.get('mode') in ['rasterLine', 'continuousLine', 'ptychographyGrid']:
                image_data = message['image']
                metadata = {
                    'energy': message.get('energy'),
                    'dwell': message.get('dwell'),
                    'scan_region': message.get('scanRegion'),
                    'energy_index': message.get('energyIndex'),
                    'type': message.get('type')
                }
                self.update_image_data(image_data, metadata)
                
        except Exception as e:
            print(f"Error handling monitor message: {e}")
            
    def _handle_ccd_data(self, ccd_data):
        """Handle CCD frame data."""
        # Update image model with CCD data
        self.image_model.set('ccd_data', ccd_data)
        
    def _handle_ptycho_data(self, ptycho_data):
        """Handle ptychography data."""
        # Update image model with ptycho data
        self.image_model.set('ptycho_data', ptycho_data)
            
    def get_available_motors(self) -> list:
        """Get list of available motors for display."""
        motor_info = self.motor_model.get('motor_info', {})
        motors = []
        
        # Sort motors by index
        motor_keys = list(motor_info.keys())
        if motor_keys:
            try:
                motor_indices = [(key, motor_info[key].get('index', 0)) for key in motor_keys]
                motor_indices.sort(key=lambda x: x[1])
                
                for motor_name, _ in motor_indices:
                    if motor_info[motor_name].get('display', False):
                        motors.append(motor_name)
            except (KeyError, TypeError):
                # Fallback if index sorting fails
                motors = [key for key in motor_keys if motor_info[key].get('display', False)]
                
        return motors
        
    def get_available_scan_types(self) -> list:
        """Get list of available scan types."""
        if hasattr(self.client, 'scanConfig') and self.client.scanConfig:
            scan_types = []
            for scan_type, config in self.client.scanConfig.get("scans", {}).items():
                if config.get("display", False):
                    scan_types.append(scan_type)
            return scan_types
        return ["Image", "Focus Scan", "Line Spectrum", "Single Motor", "Double Motor"]  # Default fallback
            
    def compile_scan_from_view(self, view) -> bool:
        """Compile scan configuration from view widgets."""
        try:
            # Clear existing regions
            self.scan_model.set('scan_regions', {})
            self.scan_model.set('energy_regions', {})
            
            # Get basic scan settings
            scan_type = view.ui.scanType.currentText()
            self.scan_model.set('scan_type', scan_type)
            self.scan_model.set('x_motor', view.ui.xMotorCombo.currentText())
            self.scan_model.set('y_motor', view.ui.yMotorCombo.currentText())
            self.scan_model.set('tiled', view.ui.tiledCheckbox.isChecked())
            self.scan_model.set('defocus', view.ui.defocusCheckbox.isChecked())
            self.scan_model.set('autofocus', view.ui.autofocusCheckbox.isChecked())
            self.scan_model.set('proposal', view.ui.proposalComboBox.currentText() if view.ui.proposalComboBox.count() > 0 else '')
            self.scan_model.set('experimenters', view.ui.experimentersLineEdit.text())
            self.scan_model.set('sample', view.ui.sampleLineEdit.text())
            self.scan_model.set('driver',self.client.scanConfig["scans"][scan_type]['driver'])
            
            # Collect scan regions from widgets
            for i, region_widget in enumerate(view.scan_region_widgets):
                region_name = f"Region{i + 1}"
                region_data = self._extract_scan_region_data(region_widget, view, scan_type)
                if region_data:
                    self.scan_model.add_scan_region(region_name, region_data)
            
            # Collect energy regions from widgets  
            for i, energy_widget in enumerate(view.energy_region_widgets):
                region_name = f"EnergyRegion{i + 1}"
                energy_data = self._extract_energy_region_data(energy_widget, view)
                if energy_data:
                    self.scan_model.add_energy_region(region_name, energy_data)
                    
            # Calculate estimated time and include it in status message
            estimated_time = self.scan_model.calculate_estimated_time()
            if estimated_time < 100:
                time_str = f"{estimated_time:.2f} s"
            elif estimated_time < 3600:
                time_str = f"{estimated_time / 60:.2f} m"
            else:
                time_str = f"{estimated_time / 3600:.2f} hr"
            
            self.status_updated.emit(f"Scan compiled - Estimated time: {time_str}")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to compile scan: {str(e)}")
            return False
            
    def _extract_scan_region_data(self, region_widget, view, scan_type: str) -> dict:
        """Extract scan region data from widget."""
        try:
            if "Image" in scan_type:
                x_center = float(region_widget.ui.xCenter.text() or 0)
                y_center = float(region_widget.ui.yCenter.text() or 0)
                x_range = float(region_widget.ui.xRange.text() or 10)
                y_range = float(region_widget.ui.yRange.text() or 10)
                x_points = int(region_widget.ui.xNPoints.text() or 100)
                y_points = int(region_widget.ui.yNPoints.text() or 100)
                x_step = x_range / x_points if x_points > 0 else 0.1
                y_step = y_range / y_points if y_points > 0 else 0.1
                
                return {
                    'xCenter': x_center,
                    'yCenter': y_center,
                    'xRange': x_range,
                    'yRange': y_range,
                    'xPoints': x_points,
                    'yPoints': y_points,
                    'xStep': x_step,
                    'yStep': y_step,
                    'xStart': x_center - x_range / 2.0 + x_step / 2.0,
                    'xStop': x_center + x_range / 2.0 - x_step / 2.0,
                    'yStart': y_center - y_range / 2.0 + y_step / 2.0,
                    'yStop': y_center + y_range / 2.0 - y_step / 2.0,
                    'zCenter': 0,
                    'zRange': 0,
                    'zPoints': 1,
                    'zStep': 0,
                    'zStart': 0,
                    'zStop': 0
                }
            elif "Focus" in scan_type:
                x_center = float(region_widget.ui.xCenter.text() or 0)
                y_center = float(region_widget.ui.yCenter.text() or 0)
                z_center = float(view.ui.focusCenterEdit.text())
                x_range = float(region_widget.ui.xRange.text() or 10)
                y_range = float(region_widget.ui.yRange.text() or 10)
                z_range = float(view.ui.focusRangeEdit.text())
                z_points = int(view.ui.focusStepsEdit.text())
                x_points = int(region_widget.ui.xNPoints.text() or 100)
                y_points = int(region_widget.ui.yNPoints.text() or 100)
                x_step = x_range / x_points if x_points > 0 else 0.1
                y_step = y_range / y_points if y_points > 0 else 0.1
                z_step = z_range / z_points if z_points > 0 else 0.1
                return {
                    'xCenter': x_center,
                    'yCenter': y_center,
                    'xRange': x_range,
                    'yRange': y_range,
                    'xPoints': x_points,
                    'yPoints': y_points,
                    'xStep': x_step,
                    'yStep': y_step,
                    'xStart': x_center - x_range / 2.0 + x_step / 2.0,
                    'xStop': x_center + x_range / 2.0 - x_step / 2.0,
                    'yStart': y_center - y_range / 2.0 + y_step / 2.0,
                    'yStop': y_center + y_range / 2.0 - y_step / 2.0,
                    'zCenter': z_center,
                    'zRange': z_range,
                    'zPoints': z_points,
                    'zStep': z_step,
                    'zStart': z_center - z_range / 2.0 + z_step / 2.0,
                    'zStop': z_center + z_range / 2.0 - z_step / 2.0,
                }
            elif "Line Spectrum" in scan_type:
                x_center = float(region_widget.ui.xCenter.text() or 0)
                y_center = float(region_widget.ui.yCenter.text() or 0)
                x_range = float(region_widget.ui.xRange.text() or 10)
                y_range = float(region_widget.ui.yRange.text() or 10)
                x_points = int(view.ui.linePointsEdit.text() or 100)
                y_points = 1
                x_step = x_range / x_points if x_points > 0 else 0.1
                y_step = y_range / y_points if y_points > 0 else 0.1
                return {
                    'xCenter': x_center,
                    'yCenter': y_center,
                    'xRange': x_range,
                    'yRange': y_range,
                    'xPoints': x_points,
                    'yPoints': y_points,
                    'xStep': x_step,
                    'yStep': y_step,
                    'xStart': x_center - x_range / 2.0 + x_step / 2.0,
                    'xStop': x_center + x_range / 2.0 - x_step / 2.0,
                    'yStart': y_center - y_range / 2.0 + y_step / 2.0,
                    'yStop': y_center + y_range / 2.0 - y_step / 2.0,
                    'zCenter': 0,
                    'zRange': 0,
                    'zPoints': 1,
                    'zStep': 0,
                    'zStart': 0,
                    'zStop': 0
                }
        except (ValueError, AttributeError) as e:
            print(f"Error extracting scan region data: {e}")
            return {}
            
    def _extract_energy_region_data(self, energy_widget, view) -> dict:
        """Extract energy region data from widget."""
        try:
            start_energy = float(energy_widget.energyDef.energyStart.text() or 280)
            stop_energy = float(energy_widget.energyDef.energyStop.text() or 320)
            energy_step = float(energy_widget.energyDef.energyStep.text() or 1)
            dwell_time = float(energy_widget.energyDef.dwellTime.text() or 1000)
            n_energies = int(energy_widget.energyDef.nEnergies.text() or 1)
            
            return {
                'start': start_energy,
                'stop': stop_energy,
                'step': energy_step,
                'dwell': dwell_time,
                'n_energies': n_energies
            }
        except (ValueError, AttributeError) as e:
            print(f"Error extracting energy region data: {e}")
            return {}

    def start_scan(self) -> bool:
        """Start a scan based on current scan model."""
        if not self.scan_model.validate():
            self.error_occurred.emit("Invalid scan configuration")
            return False
            
        if self.scanning:
            self.error_occurred.emit("Scan already in progress")
            return False
            
        try:
            scan_config = self.scan_model.to_dict()
            message = {"command": "scan", "scan": scan_config}
            self.message_queue.put(message)
            self.scanning = True
            self.status_updated.emit("Scan started")
            self.scan_state_changed.emit(True)  # Signal scan started
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to start scan: {str(e)}")
            return False
            
    def cancel_scan(self):
        """Cancel the current scan."""
        if self.scanning:
            message = {"command": "cancel"}
            self.message_queue.put(message)
            self.scanning = False
            self.status_updated.emit("Scan cancelled")
            self.scan_state_changed.emit(False)  # Signal scan completed
        else:
            self.error_occurred.emit("No scan in progress")
            
    def move_motor(self, motor_name: str, position: float) -> bool:
        """Move a motor to the specified position."""
        if not self.motor_model.is_position_valid(motor_name, position):
            self.error_occurred.emit(f"Position {position} out of range for {motor_name}")
            return False
            
        try:
            message = {
                "command": "moveMotor",
                "axis": motor_name,
                "pos": position
            }
            self.message_queue.put(message)
            self.motor_model.set_target_position(motor_name, position)
            self.status_updated.emit(f"Moving {motor_name} to {position}")
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to move motor: {str(e)}")
            return False
            
    def jog_motor(self, motor_name: str, step_size: float, direction: int) -> bool:
        """Jog a motor by the specified step size and direction."""
        current_pos = self.motor_model.get_position(motor_name)
        if current_pos is None:
            self.error_occurred.emit(f"Unknown position for {motor_name}")
            return False
            
        new_position = current_pos + (step_size * direction)
        return self.move_motor(motor_name, new_position)
        
    def update_motor_positions(self, positions: Dict[str, float]):
        """Update motor positions from server."""
        for motor_name, position in positions.items():
            self.motor_model.update_position(motor_name, position)
            
    def update_motor_status(self, status: Dict[str, bool]):
        """Update motor status from server."""
        for motor_name, is_moving in status.items():
            self.motor_model.update_status(motor_name, is_moving)
            
    def update_image_data(self, image_data: np.ndarray, metadata: Dict[str, Any]):
        """Update image data and metadata.  This is called by _handle_monitor_message and updates the image_model 
        during the scan.  The model then emits the data changed signal."""
        self.image_model.set_current_image(image_data)
        
        # Update image metadata
        if 'energy' in metadata:
            self.image_model.set('current_energy', metadata['energy'])
        if 'dwell' in metadata:
            self.image_model.set('current_dwell', metadata['dwell'])
        if 'scan_region' in metadata:
            self.image_model.set('scan_region_index', metadata['scan_region'])
        if 'energy_index' in metadata:
            self.image_model.set('energy_index', metadata['energy_index'])
        if 'type' in metadata:
            self.image_model.set('scan_type', metadata['type'])
            
        # Update image geometry from scan model if available
        scan_regions = self.scan_model.get('scan_regions', {})
        if scan_regions and 'scan_region' in metadata:
            region_name = metadata['scan_region']
            if region_name in scan_regions:
                region_data = scan_regions[region_name]
                x_center = region_data.get('xCenter', 0.0)
                y_center = region_data.get('yCenter', 0.0)
                x_range = region_data.get('xRange', 70.0)
                y_range = region_data.get('yRange', 70.0)
                x_pts = region_data.get('xPoints', 100)
                y_pts = region_data.get('yPoints', 100)
                
                # Calculate pixel size for proper coordinate conversion
                pixel_size_x = x_range / x_pts if x_pts > 0 else 1.0
                pixel_size_y = y_range / y_pts if y_pts > 0 else 1.0
                
                # Update image model geometry
                self.image_model.set('x_center', x_center)
                self.image_model.set('y_center', y_center)
                self.image_model.set('x_range', x_range)
                self.image_model.set('y_range', y_range)
                self.image_model.set('image_scale', (pixel_size_x, pixel_size_y))
                self.image_model.set('pixel_size', pixel_size_x)  # Use x pixel size
            
    def set_scan_type(self, scan_type: str):
        """Set the scan type."""
        self.scan_model.set('scan_type', scan_type)
        
    def add_scan_region(self, region_data: Dict[str, Any]) -> str:
        """Add a scan region and return its name."""
        region_count = len(self.scan_model.get('scan_regions', {}))
        region_name = f"Region{region_count + 1}"
        self.scan_model.add_scan_region(region_name, region_data)
        return region_name
        
    def remove_scan_region(self, region_name: str):
        """Remove a scan region."""
        self.scan_model.remove_scan_region(region_name)
        
    def add_energy_region(self, region_data: Dict[str, Any]) -> str:
        """Add an energy region and return its name."""
        region_count = len(self.scan_model.get('energy_regions', {}))
        region_name = f"EnergyRegion{region_count + 1}"
        self.scan_model.add_energy_region(region_name, region_data)
        return region_name
        
    def remove_energy_region(self, region_name: str):
        """Remove an energy region."""
        self.scan_model.remove_energy_region(region_name)
        
    def set_image_display_settings(self, settings: Dict[str, Any]):
        """Set image display settings."""
        for key, value in settings.items():
            self.image_model.set(key, value)
            
    def handle_mouse_click(self, x: float, y: float):
        """Handle mouse click on image."""
        self.image_model.update_cursor_position(x, y)
        
    def handle_motor_config_change(self, motor_name: str, config_type: str, value: float):
        """Handle motor configuration changes."""
        try:
            message = {
                "command": "changeMotorConfig",
                "data": {
                    "motor": motor_name,
                    "config": config_type,
                    "value": value
                }
            }
            self.message_queue.put(message)
            self.status_updated.emit(f"Updated {motor_name} {config_type} to {value}")
        except Exception as e:
            self.error_occurred.emit(f"Failed to update motor config: {str(e)}")
            
    def save_scan_definition(self, filename: str) -> bool:
        """Save scan definition to file."""
        try:
            import json
            scan_config = self.scan_model.to_dict()
            with open(filename, 'w') as f:
                json.dump(scan_config, f, indent=4)
            self.status_updated.emit(f"Scan definition saved to {filename}")
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to save scan definition: {str(e)}")
            return False
            
    def load_scan_definition(self, filename: str) -> bool:
        """Load scan definition from file."""
        try:
            import json
            with open(filename, 'r') as f:
                scan_config = json.load(f)
            self.scan_model.update(scan_config)
            self.status_updated.emit(f"Scan definition loaded from {filename}")
            return True
        except Exception as e:
            self.error_occurred.emit(f"Failed to load scan definition: {str(e)}")
            return False
            
    def quit_application(self):
        """Quit the application."""
        self.exiting = True
        if self.control_thread:
            self.control_thread.monitor = False
            self.message_queue.put("exit")
        if self.client:
            self.client.disconnect()
        sys.exit()
        
    def get_scan_model(self) -> ScanModel:
        """Get the scan model."""
        return self.scan_model
        
    def get_motor_model(self) -> MotorModel:
        """Get the motor model."""
        return self.motor_model
        
    def get_image_model(self) -> ImageModel:
        """Get the image model."""
        return self.image_model
        
    def refresh_motor_positions(self):
        """Manually refresh motor positions from client."""
        try:
            if hasattr(self.client, 'currentMotorPositions') and self.client.currentMotorPositions:
                for motor_name, position in self.client.currentMotorPositions.items():
                    if isinstance(position, (int, float)):
                        self.motor_model.update_position(motor_name, position)
                self.status_updated.emit("Motor positions refreshed")
        except Exception as e:
            self.error_occurred.emit(f"Failed to refresh motor positions: {str(e)}")
            
    def simulate_motor_updates(self):
        """Simulate motor position updates for testing."""
        import random
        test_motors = ['SampleX', 'SampleY', 'Energy', 'ZonePlateZ']
        
        for motor in test_motors:
            # Generate random position
            position = random.uniform(-100, 100)
            self.motor_model.update_position(motor, position)
            
            # Random status
            is_moving = random.choice([True, False])
            self.motor_model.update_status(motor, is_moving)
            
        self.status_updated.emit("Simulated motor updates completed")
        
    def simulate_monitor_data(self, num_points: int = 10):
        """Simulate monitor data updates for testing."""
        import random
        import time
        
        for _ in range(num_points):
            # Generate random monitor value
            monitor_value = random.uniform(0.1, 1.0)
            self.image_model.add_monitor_data(monitor_value, max_points=500)
            
            # Update DAQ display value
            daq_display_value = monitor_value * 10.0
            self.image_model.set('daq_current_value', daq_display_value)
            
            # Signals will be emitted automatically by model changes
            
            # Small delay to see the updates
            time.sleep(0.1)
            
        self.status_updated.emit(f"Simulated {num_points} monitor data points")
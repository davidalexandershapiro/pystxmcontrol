from typing import Dict, Any, Optional, List
from .base_model import BaseModel
import numpy as np


class ImageModel(BaseModel):
    """Model for managing image data and display settings."""
    
    def __init__(self):
        super().__init__()
        self.reset()
        
    def reset(self) -> None:
        """Reset image model to default state."""
        self._data = {
            'current_image': None,
            'image_stack': {},
            'image_type': 'Image',
            'scan_type': 'Image',
            'energy_index': 0,
            'energy_list': [],
            'scan_region_index': 0,
            'scan_file_name': '',
            'image_center': (0.0, 0.0),
            'image_scale': (1.0, 1.0),
            'x_range': 70.0,
            'y_range': 70.0,
            'z_range': 0.0,
            'x_center': 0.0,
            'y_center': 0.0,
            'z_center': 0.0,
            'x_pts': 100,
            'y_pts': 100,
            'z_pts': 1,
            'current_energy': 500.0,
            'current_dwell': 1.0,
            'pixel_size': 1.0,
            'scale_bar_length': 100.0,
            'cursor_x': None,
            'cursor_y': None,
            'cursor_intensity': 0.0,
            'autorange': True,
            'autoscale': True,
            'show_beam_position': False,
            'show_range_finder': True,
            'show_roi': True,
            'composite_image': True,
            'channel_select': 'Diode',
            'plot_type': 'Monitor',
            'beam_position': None,
            'crosshair_position': None,
            'monitor_data': [],
            'motor_scan_x_data': [],
            'motor_scan_y_data': []
        }
        
    def validate(self) -> bool:
        """Validate image model state."""
        return True  # Image model is always valid
        
    def set_current_image(self, image: np.ndarray) -> None:
        """Set the current display image."""
        self.set('current_image', image)
        
    def get_current_image(self) -> Optional[np.ndarray]:
        """Get the current display image."""
        return self.get('current_image')
        
    def add_image_to_stack(self, image_id: str, image: np.ndarray) -> None:
        """Add an image to the image stack."""
        stack = self.get('image_stack', {}).copy()
        stack[image_id] = image
        self.set('image_stack', stack)
        
    def remove_image_from_stack(self, image_id: str) -> None:
        """Remove an image from the image stack."""
        stack = self.get('image_stack', {}).copy()
        if image_id in stack:
            del stack[image_id]
            self.set('image_stack', stack)
            
    def clear_image_stack(self) -> None:
        """Clear all images from the stack."""
        self.set('image_stack', {})
        
    def set_image_geometry(self, center: tuple, scale: tuple, ranges: tuple) -> None:
        """Set image geometry parameters."""
        self.set('image_center', center)
        self.set('image_scale', scale)
        x_range, y_range, z_range = ranges
        self.set('x_range', x_range)
        self.set('y_range', y_range)
        self.set('z_range', z_range)
        
    def set_image_dimensions(self, x_pts: int, y_pts: int, z_pts: int = 1) -> None:
        """Set image dimensions."""
        self.set('x_pts', x_pts)
        self.set('y_pts', y_pts)
        self.set('z_pts', z_pts)
        
    def update_cursor_position(self, x: float, y: float, intensity: float = 0.0) -> None:
        """Update cursor position and intensity."""
        self.set('cursor_x', x)
        self.set('cursor_y', y)
        self.set('cursor_intensity', intensity)
        
    def set_beam_position(self, x: float, y: float) -> None:
        """Set beam position."""
        self.set('beam_position', (x, y))
        
    def get_beam_position(self) -> Optional[tuple]:
        """Get beam position."""
        return self.get('beam_position')
        
    def set_crosshair_position(self, x: float, y: float) -> None:
        """Set crosshair position."""
        self.set('crosshair_position', (x, y))
        
    def get_crosshair_position(self) -> Optional[tuple]:
        """Get crosshair position."""
        return self.get('crosshair_position')
        
    def add_monitor_data(self, data_point: float, max_points: int = 500) -> None:
        """Add a data point to monitor data."""
        monitor_data = self.get('monitor_data', []).copy()
        monitor_data.append(data_point)
        
        # Keep only the last max_points
        if len(monitor_data) > max_points:
            monitor_data = monitor_data[-max_points:]
        self.set('monitor_data', monitor_data)
        
    def add_motor_scan_data(self, x_data: float, y_data: float) -> None:
        """Add data points to motor scan data."""
        x_scan_data = self.get('motor_scan_x_data', []).copy()
        y_scan_data = self.get('motor_scan_y_data', []).copy()
        
        x_scan_data.append(x_data)
        y_scan_data.append(y_data)
        
        self.set('motor_scan_x_data', x_scan_data)
        self.set('motor_scan_y_data', y_scan_data)
        
    def clear_motor_scan_data(self) -> None:
        """Clear motor scan data."""
        self.set('motor_scan_x_data', [])
        self.set('motor_scan_y_data', [])
        
    def clear_monitor_data(self) -> None:
        """Clear monitor data."""
        self.set('monitor_data', [])
        
    def update_image_info(self, energy: float = None, dwell: float = None, 
                         pixel_size: float = None) -> None:
        """Update image information."""
        if energy is not None:
            self.set('current_energy', energy)
        if dwell is not None:
            self.set('current_dwell', dwell)
        if pixel_size is not None:
            self.set('pixel_size', pixel_size)
            
    def calculate_scale_bar_length(self, pixel_size: float, 
                                 target_length_um: float = 100.0) -> float:
        """Calculate scale bar length in pixels."""
        return target_length_um / pixel_size
from typing import Dict, Any, Optional
from .base_model import BaseModel


class MotorModel(BaseModel):
    """Model for managing motor positions and status."""
    
    def __init__(self):
        super().__init__()
        self.reset()
        
    def reset(self) -> None:
        """Reset motor model to default state."""
        self._data = {
            'current_positions': {},
            'motor_status': {},
            'motor_info': {},
            'moving_motors': set(),
            'last_motor': '',
            'target_positions': {}
        }
        
    def validate(self) -> bool:
        """Validate motor configuration."""
        return True  # Motor model is always valid
        
    def update_position(self, motor_name: str, position: float) -> None:
        """Update the current position of a motor."""
        positions = self.get('current_positions', {}).copy()
        positions[motor_name] = position
        self.set('current_positions', positions)
        
    def update_status(self, motor_name: str, is_moving: bool) -> None:
        """Update the moving status of a motor."""
        status = self.get('motor_status', {}).copy()
        status[motor_name] = is_moving
        self.set('motor_status', status)
        
        # Update moving motors set
        moving = self.get('moving_motors', set()).copy()
        if is_moving:
            moving.add(motor_name)
        else:
            moving.discard(motor_name)
        self.set('moving_motors', moving)
        
    def set_motor_info(self, motor_info: Dict[str, Any]) -> None:
        """Set motor configuration information."""
        self.set('motor_info', motor_info)
        
    def get_position(self, motor_name: str) -> Optional[float]:
        """Get current position of a motor."""
        return self.get('current_positions', {}).get(motor_name)
        
    def is_moving(self, motor_name: str) -> bool:
        """Check if a motor is currently moving."""
        return self.get('motor_status', {}).get(motor_name, False)
        
    def get_motor_limits(self, motor_name: str) -> tuple:
        """Get the min/max limits for a motor."""
        motor_info = self.get('motor_info', {}).get(motor_name, {})
        min_val = motor_info.get('minValue', 0.0)
        max_val = motor_info.get('maxValue', 100.0)
        return min_val, max_val
        
    def get_scan_limits(self, motor_name: str) -> tuple:
        """Get the min/max scan limits for a motor."""
        motor_info = self.get('motor_info', {}).get(motor_name, {})
        min_val = motor_info.get('minScanValue', 0.0)
        max_val = motor_info.get('maxScanValue', 100.0)
        return min_val, max_val
        
    def is_position_valid(self, motor_name: str, position: float) -> bool:
        """Check if a position is within motor limits."""
        min_val, max_val = self.get_motor_limits(motor_name)
        return min_val <= position <= max_val
        
    def is_scan_position_valid(self, motor_name: str, position: float) -> bool:
        """Check if a position is within scan limits."""
        min_val, max_val = self.get_scan_limits(motor_name)
        return min_val <= position <= max_val
        
    def set_target_position(self, motor_name: str, position: float) -> None:
        """Set target position for a motor."""
        targets = self.get('target_positions', {}).copy()
        targets[motor_name] = position
        self.set('target_positions', targets)
        
    def get_target_position(self, motor_name: str) -> Optional[float]:
        """Get target position for a motor."""
        return self.get('target_positions', {}).get(motor_name)
        
    def clear_target_position(self, motor_name: str) -> None:
        """Clear target position for a motor."""
        targets = self.get('target_positions', {}).copy()
        if motor_name in targets:
            del targets[motor_name]
            self.set('target_positions', targets)
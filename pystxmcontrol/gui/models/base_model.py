from PySide6.QtCore import QObject, Signal
from typing import Any, Dict, Optional


class BaseModel(QObject):
    """Base model class that provides common functionality for all models."""
    
    # Signal emitted when model data changes
    data_changed = Signal(str, object)  # (property_name, new_value)
    
    def __init__(self):
        super().__init__()
        self._data = {}
        
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the model data."""
        return self._data.get(key, default)
        
    def set(self, key: str, value: Any) -> None:
        """Set a value in the model data and emit change signal."""
        old_value = self._data.get(key)
        # if old_value != value:
        self._data[key] = value
        self.data_changed.emit(key, value)
            
    def update(self, data: Dict[str, Any]) -> None:
        """Update multiple values at once."""
        for key, value in data.items():
            self.set(key, value)

    def silent_update(self, data: Dict[str, Any]) -> None:
        """Write multiple keys directly into _data without emitting any signals.
        Use this for metadata that doesn't need to trigger UI redraws on its own."""
        self._data.update(data)
            
    def to_dict(self) -> Dict[str, Any]:
        """Return a copy of the internal data dictionary."""
        return self._data.copy()
        
    def validate(self) -> bool:
        """Validate the current model state. Should be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement validate method")
        
    def reset(self) -> None:
        """Reset model to default state. Should be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement reset method")
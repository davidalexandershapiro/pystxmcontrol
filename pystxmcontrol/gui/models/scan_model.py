from typing import Dict, Any, List, Optional
from .base_model import BaseModel
import numpy as np


class ScanModel(BaseModel):
    """Model for managing scan-related data and operations."""
    
    def __init__(self):
        super().__init__()
        self.reset()
        
    def reset(self) -> None:
        """Reset scan model to default state."""
        self._data = {
            'scan_type': 'Image',
            'scan_regions': {},
            'energy_regions': {},
            'x_motor': 'SampleX',
            'y_motor': 'SampleY',
            'energy_motor': 'Energy',
            'z_motor': 'ZonePlateZ',
            'tiled': False,
            'coarse_only': False,
            'defocus': False,
            'autofocus': True,
            'double_exposure': False,
            'multi_frame': False,
            'n_repeats': 1,
            'proposal': '',
            'experimenters': '',
            'sample': '',
            'oversampling_factor': 1,
            'refocus': False,
            'retract': True,
            'spiral': False,
            'driver': '',
            'mode': '',
            'nx_file_version': '',
            'single_energy': True,
            'energy_list': None,
            'dwell': 1.0
        }
        
    def validate(self) -> bool:
        """Validate scan configuration."""
        # Check required fields
        required_fields = ['scan_type', 'x_motor', 'y_motor']
        for field in required_fields:
            if not self.get(field):
                return False
                
        # Check that we have at least one scan region
        scan_regions = self.get('scan_regions', {})
        if not scan_regions:
            return False
            
        # Check that we have at least one energy region
        energy_regions = self.get('energy_regions', {})
        if not energy_regions:
            return False
            
        return True
        
    def add_scan_region(self, region_name: str, region_data: Dict[str, Any]) -> None:
        """Add a scan region."""
        regions = self.get('scan_regions', {}).copy()
        regions[region_name] = region_data
        self.set('scan_regions', regions)
        
    def remove_scan_region(self, region_name: str) -> None:
        """Remove a scan region."""
        regions = self.get('scan_regions', {}).copy()
        if region_name in regions:
            del regions[region_name]
            self.set('scan_regions', regions)
            
    def add_energy_region(self, region_name: str, region_data: Dict[str, Any]) -> None:
        """Add an energy region."""
        regions = self.get('energy_regions', {}).copy()
        regions[region_name] = region_data
        self.set('energy_regions', regions)
        
    def remove_energy_region(self, region_name: str) -> None:
        """Remove an energy region."""
        regions = self.get('energy_regions', {}).copy()
        if region_name in regions:
            del regions[region_name]
            self.set('energy_regions', regions)
            
    def get_scan_region(self, region_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific scan region."""
        return self.get('scan_regions', {}).get(region_name)
        
    def get_energy_region(self, region_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific energy region."""
        return self.get('energy_regions', {}).get(region_name)
        
    def calculate_estimated_time(self) -> float:
        """Calculate estimated scan time."""
        scan_regions = self.get('scan_regions', {})
        energy_regions = self.get('energy_regions', {})
        scan_type = self.get('scan_type')
        
        estimated_time = 0.0
        n_points = 0
        n_lines = 0
        n_energies = 0
        time_per_point = 0
        
        point_overhead = 0.0001
        line_overhead = 0.02
        energy_overhead = 5.0
        
        # Calculate points and lines based on scan type
        for region in scan_regions.values():
            if "Image" in scan_type:
                n_points += region.get('xPoints', 1) * region.get('yPoints', 1)
                n_lines += region.get('yPoints', 1)
            elif "Focus" in scan_type:
                n_points += region.get('xPoints', 1) * region.get('zPoints', 1)
                n_lines += region.get('zPoints', 1)
            elif scan_type == "Line Spectrum":
                n_points += region.get('xPoints', 1)
                
        # Calculate time per point from energy regions
        for region in energy_regions.values():
            dwell = region.get('dwell', 1.0)
            energies = region.get('nEnergies', 1)
            
            if "Ptychography" in scan_type:
                if self.get('double_exposure'):
                    point_overhead = 0.2
                    point_dwell = dwell + dwell * 10.0
                elif self.get('multi_frame'):
                    point_overhead = 0.25
                    point_dwell = dwell * 5.0
                else:
                    point_overhead = 0.1
                    point_dwell = dwell
                time_per_point += (point_dwell / 1000.0 + point_overhead) * energies
            else:
                time_per_point += (dwell / 1000.0 + point_overhead) * energies
                
            n_energies += energies
            
        estimated_time = n_points * time_per_point + n_lines * line_overhead + (n_energies - 1) * energy_overhead
        return estimated_time
    
    def get_energies(self) -> Optional[Dict[str, Any]]:
        energies = []
        energy_regions = self.get('energy_regions', {})
        for region in energy_regions.values():
            energies = energies + np.linspace(region.get("start"),
                                        region.get("stop"),region.get("n_energies")).tolist()
            print(region.get('start'),region.get('stop'),region.get('n_energies'))
        return energies
        
    def get_scan_velocity(self) -> float:
        """Calculate scan velocity."""
        scan_regions = self.get('scan_regions', {})
        energy_regions = self.get('energy_regions', {})
        
        if not scan_regions or not energy_regions:
            return 0.0
            
        velocity_list = []
        first_energy_region = list(energy_regions.values())[0]
        dwell = first_energy_region.get('dwell', 1.0)
        
        for region in scan_regions.values():
            x_step = region.get('xStep', 1.0)
            velocity_list.append(x_step / dwell)
            
        return max(velocity_list) if velocity_list else 0.0
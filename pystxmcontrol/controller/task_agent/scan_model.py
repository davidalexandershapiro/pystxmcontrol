from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator


class ScanModel(BaseModel):
    proposal: str = "BLS-000001"
    experimenters: str = "Shapiro"
    sample_description: str = ""
    comment: str = ""
    nx_file_version: float = 3.0

    # Spatial parameters
    x_center: float = 0.0
    x_range: float = 5.0
    x_points: int = 50
    y_center: float = 0.0
    y_range: float = 5.0
    y_points: int = 50
    z_center: float = 0.0
    z_range: float = 0.0
    z_points: int = 1

    # Energy parameters
    energy_start: float = 700.0
    energy_stop: float = 700.0
    energy_points: int = 1
    energy_list: Optional[list[float]] = None

    # Timing
    dwell: float = 0.2

    # Motor assignments
    x_motor: str = "SampleX"
    y_motor: str = "SampleY"
    z_motor: Optional[str] = None

    # Scan behaviour flags
    scan_type: str = "Image"
    daq_list: list[str] = ["default"]
    defocus: bool = False
    double_exposure: bool = False
    spiral: bool = False
    autofocus: bool = True
    loop_scan: bool = False
    retract: bool = True

    @field_validator("x_points", "y_points", "z_points", "energy_points")
    @classmethod
    def points_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Point counts must be >= 1")
        return v

    @field_validator("x_range", "y_range", "z_range")
    @classmethod
    def range_must_be_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Range values must be >= 0")
        return v

    @field_validator("dwell")
    @classmethod
    def dwell_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Dwell time must be > 0")
        return v

    @model_validator(mode="after")
    def energy_range_check(self) -> ScanModel:
        if self.energy_list is None and self.energy_stop < self.energy_start:
            raise ValueError(
                f"energy_stop ({self.energy_stop}) must be >= energy_start ({self.energy_start})"
            )
        return self


def validate_scan(scan_dict: dict) -> tuple[bool, str]:
    """Validate a scan parameter dictionary against ScanModel.

    Returns (True, "") on success, or (False, error_message) on failure.
    """
    try:
        ScanModel(**scan_dict)
        return True, ""
    except Exception as e:
        return False, str(e)

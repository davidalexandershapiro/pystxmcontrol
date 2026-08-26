from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator


class EnergyRegionModel(BaseModel):
    """One energy region of a scan: a linspace from ``start`` to ``stop`` measured
    at ``dwell`` ms per point.

    Scans may carry several of these (that is what a saved energy definition holds),
    and each keeps its OWN dwell — the server builds a per-energy dwell array from
    them and the scan drivers index it, so a fine near-edge region can be measured
    longer than the coarse pre-edge one.
    """

    start: float
    stop: float
    n_energies: int = 1
    dwell: float = 1.0
    step: Optional[float] = None

    @field_validator("n_energies")
    @classmethod
    def n_energies_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("n_energies must be >= 1")
        return v

    @field_validator("dwell")
    @classmethod
    def dwell_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Dwell time must be > 0")
        return v

    @model_validator(mode="after")
    def region_range_check(self) -> EnergyRegionModel:
        if self.stop < self.start:
            raise ValueError(
                f"Energy region stop ({self.stop}) must be >= start ({self.start})"
            )
        if self.step is None:
            self.step = ((self.stop - self.start) / (self.n_energies - 1)
                         if self.n_energies > 1 else 0.0)
        return self


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
    # Multi-region energy definition (a saved energy preset, or a multi-region scan
    # read back from the server).  When set it OVERRIDES energy_start/stop/points —
    # those are kept in sync with the overall span so anything reading the flat
    # fields still sees sensible values.  Each region keeps its own dwell.
    energy_regions: Optional[list[EnergyRegionModel]] = None

    # Timing
    dwell: float = 0.2

    # Motor assignments
    x_motor: str = "SampleX"
    y_motor: str = "SampleY"
    z_motor: Optional[str] = None

    # Scan behavior flags
    scan_type: str = "Image"
    daq_list: list[str] = ["default"]
    defocus: bool = False
    double_exposure: bool = False
    spiral: bool = False
    autofocus: bool = True
    loop_scan: bool = False
    retract: bool = True
    # Large-scan handling (range exceeds the fine/piezo travel). Mutually exclusive:
    #   tiled       - split into sub-regions that each fit the fine range (server stitches)
    #   coarse_only - position with the coarse stage instead of the fine piezo
    tiled: bool = False
    coarse_only: bool = False

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
        # An explicit energy_list or energy_regions defines the energies outright,
        # so the flat start/stop pair is descriptive only and need not be ordered.
        if (self.energy_list is None and self.energy_regions is None
                and self.energy_stop < self.energy_start):
            raise ValueError(
                f"energy_stop ({self.energy_stop}) must be >= energy_start ({self.energy_start})"
            )
        return self

    @model_validator(mode="after")
    def sync_flat_energy_fields(self) -> ScanModel:
        """Mirror a multi-region definition into the flat energy fields.

        ``energy_start``/``energy_stop`` become the overall span, ``energy_points``
        the total count and ``dwell`` the first region's — so callers that only know
        the flat model (limit checks, summaries, the GUI's last-scan display) read
        something truthful instead of a stale single-region leftover.
        """
        if self.energy_regions:
            self.energy_start = min(r.start for r in self.energy_regions)
            self.energy_stop = max(r.stop for r in self.energy_regions)
            self.energy_points = sum(r.n_energies for r in self.energy_regions)
            self.dwell = self.energy_regions[0].dwell
        return self

    def total_energies(self) -> int:
        """Number of energy points this scan will measure."""
        if self.energy_regions:
            return sum(r.n_energies for r in self.energy_regions)
        if self.energy_list:
            return len(self.energy_list)
        return int(self.energy_points or 1)


def validate_scan(scan_dict: dict) -> tuple[bool, str]:
    """Validate a scan parameter dictionary against ScanModel.

    Returns (True, "") on success, or (False, error_message) on failure.
    """
    try:
        ScanModel(**scan_dict)
        return True, ""
    except Exception as e:
        return False, str(e)

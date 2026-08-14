"""
Auto Exposure configuration.

Plain pydantic BaseModel (not BaseSettings): wiring these values to environment
variables / the application Settings is done by the integration layer, keeping
this module free of deployment concerns. Defaults are the PRD starting values.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AutoExposureConfig(BaseModel):
    """Tunable parameters for the Auto Exposure + RAW QA subsystem.

    All fields use the conservative starting defaults from the PRD; they are
    meant to be calibrated against real rig data before production (PRD §41).
    """

    # Feature gate: OFF by default so existing manual capture is unchanged.
    enabled: bool = False
    mode: str = "fixed_sequence"
    adjust: str = "shutter_only"

    # Fixed camera settings for the production sequence.
    iso: int = 100
    aperture: float = 8.0

    # Analysis region.
    roi_mode: str = "full_frame"  # full_frame | center_crop | configured_roi

    # Target exposure.
    target_percentile: float = 99.9
    target_normalized: float = 0.75
    acceptable_low: float = 0.60
    acceptable_high: float = 0.85

    # Clipping thresholds.
    near_clip_threshold: float = 0.95
    hard_clip_threshold: float = 0.995
    max_near_clip_fraction: float = 0.001
    max_hard_clip_fraction: float = 0.00001
    max_ev_error: float = 0.10

    # Preflight control loop.
    initial_shutter_seconds: Optional[float] = None  # None -> use camera current
    convergence_tolerance_ev: float = 0.10
    max_adjustment_per_iteration_ev: float = 2.0
    max_preflight_iterations: int = 5

    # Per-frame QA.
    retake_limit: int = 2

    # Underexposure / signal quality.
    minimum_p95_normalized: float = 0.05
    minimum_median_above_black: float = 0.01

    # Preflight strategy + lighting.
    preflight_strategy: str = "all_lights_safe_exposure"
    light_settle_ms: int = 250

    # Debug artifacts.
    save_preflight_raws: bool = False
    save_metrics_json: bool = True

    @classmethod
    def defaults(cls) -> "AutoExposureConfig":
        """Return a config with all default values."""
        return cls()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (machine-readable metadata)."""
        return self.model_dump()

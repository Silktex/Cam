"""
Pydantic API models for the Auto Exposure subsystem.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ExposureConfigResponse(BaseModel):
    """Auto exposure configuration as exposed by the API."""

    enabled: bool
    mode: str
    iso: int
    aperture: float
    target_percentile: float
    target_normalized: float
    acceptable_low: float
    acceptable_high: float
    near_clip_threshold: float
    hard_clip_threshold: float
    max_hard_clip_fraction: float
    max_near_clip_fraction: float
    retake_limit: int
    minimum_p95_normalized: float


class ExposureStatusResponse(BaseModel):
    """Current camera exposure state."""

    connected: bool
    iso: Optional[int] = None
    aperture: Optional[float] = None
    shutter_seconds: Optional[float] = None
    shutter_label: Optional[str] = None
    camera_mode: Optional[str] = None


class PreflightLightResult(BaseModel):
    """Per-light summary from preflight."""

    name: str
    status: str
    limiting_channel: Optional[str] = None
    measured_normalized: Optional[float] = None
    clipped_fraction: Optional[float] = None


class PreflightResponse(BaseModel):
    """Result of an exposure preflight run."""

    status: str
    selected_shutter_seconds: Optional[float] = None
    selected_shutter_label: Optional[str] = None
    iso: Optional[int] = None
    aperture: Optional[float] = None
    limiting_light: Optional[str] = None
    limiting_channel: Optional[str] = None
    predicted_peak: Optional[float] = None
    headroom_ev: Optional[float] = None
    iterations: int = 0
    lights: List[PreflightLightResult] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class FrameQaResponse(BaseModel):
    """Per-frame QA result."""

    status: str
    reason: str = ""
    p99_9: Dict[str, float] = Field(default_factory=dict)
    limiting_channel: Optional[str] = None
    measured_normalized: Optional[float] = None
    hard_clip_fraction: Optional[float] = None
    near_clip_fraction: Optional[float] = None
    headroom_ev: Optional[float] = None

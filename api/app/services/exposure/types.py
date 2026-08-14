"""
Exposure domain types for the Auto Exposure subsystem.

Pure stdlib (enum, dataclasses, typing) — no numpy import here so downstream
modules can import these types without transitively pulling numpy.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class QaStatus(str, Enum):
    """Per-capture exposure QA outcome."""

    PASS = "PASS"
    WARNING = "WARNING"
    RETAKE = "RETAKE"
    FAIL = "FAIL"


class RoiType(str, Enum):
    """How the analysis region of interest is selected."""

    FULL_FRAME = "full_frame"
    CENTER_CROP = "center_crop"
    CONFIGURED_ROI = "configured_roi"
    CAPTURE_AREA_MASK = "capture_area_mask"


@dataclass(frozen=True)
class Roi:
    """Rectangular analysis region (pixel coordinates in the RAW mosaic)."""

    type: RoiType = RoiType.FULL_FRAME
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class ExposureSettings:
    """Camera exposure state at capture time."""

    iso: Optional[int] = None
    aperture: Optional[float] = None
    shutter_seconds: Optional[float] = None
    shutter_label: Optional[str] = None
    camera_mode: Optional[str] = None  # e.g. "Manual"
    raw_format: Optional[str] = None  # e.g. "ARW"


@dataclass(frozen=True)
class ShutterOption:
    """A shutter speed the camera reports as supported."""

    label: str  # e.g. "1/40"
    seconds: Optional[float]  # None for bulb / unparseable values


@dataclass(frozen=True)
class ChannelMetrics:
    """Per-CFA-channel statistics of a RAW mosaic."""

    min_norm: float = 0.0
    p50: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    p999: float = 0.0
    p9999: Optional[float] = None  # None when < 1e4 pixels in channel
    max_norm: float = 0.0
    clipped_count: int = 0
    clipped_fraction: float = 0.0
    near_clipped_fraction: float = 0.0


@dataclass
class ExposureAnalysisResult:
    """Full exposure analysis of a RAW mosaic.

    ``status`` is ``"OK"`` on success or an error code string on failure.
    """

    status: str = "OK"
    raw_width: int = 0
    raw_height: int = 0
    roi: Optional[Roi] = None
    black_levels: List[float] = field(default_factory=list)
    white_levels: List[float] = field(default_factory=list)
    channel_metrics: Dict[str, ChannelMetrics] = field(
        default_factory=dict
    )  # {"R","G1","G2","B"}
    limiting_channel: Optional[str] = None
    control_percentile: float = 99.9
    measured_normalized: float = 0.0  # limiting channel value at control percentile
    target_normalized: float = 0.75
    recommended_ev: float = 0.0
    headroom_ev: float = 0.0
    clipped_count: int = 0
    clipped_fraction: float = 0.0
    near_clipped_count: int = 0
    near_clipped_fraction: float = 0.0
    underexposed_fraction: float = 0.0
    metadata_exposure: Optional[ExposureSettings] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def ev_correction(current: float, target: float) -> float:
    """EV correction needed to move ``current`` normalized signal to ``target``.

    Returns ``log2(target / current)``. Example: current=0.375, target=0.75 -> +1.0.

    Raises ValueError if ``current`` is not positive (the logarithm is undefined).
    """
    if current <= 0.0:
        raise ValueError("current must be > 0 for an EV correction")
    return float(math.log2(target / current))


def headroom_ev(p: float) -> float:
    """Headroom to saturation in EV: ``log2(1 / p)``.

    Example: p=0.5 -> 1.0, p=0.75 -> ~0.415.

    Raises ValueError if ``p`` is not positive.
    """
    if p <= 0.0:
        raise ValueError("p must be > 0 for headroom")
    return float(math.log2(1.0 / p))

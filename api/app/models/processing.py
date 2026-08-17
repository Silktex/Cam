"""
Processing-related Pydantic models.

Request models for the processing router: crop, calibration, PBR and
material tool endpoints. Extracted verbatim from app/routers/processing.py.
"""
from typing import Optional, List

from pydantic import BaseModel


# ─── Crop Models ───

class ManualCropRequest(BaseModel):
    batch_name: str
    bbox: List[int]  # [x1, y1, x2, y2]
    apply_to_all: bool = True
    specific_images: Optional[List[str]] = None


class AutoCropRequest(BaseModel):
    batch_name: str
    prompt: str = "fabric sample"
    crop_size: int = 3200


class CropPoint(BaseModel):
    x: float
    y: float


class CropApplyRequest(BaseModel):
    batch_name: str
    bbox: Optional[List[int]] = None  # [x1, y1, x2, y2] - legacy simple crop
    crop_type: str = "manual"  # "manual" or "auto"
    points: Optional[List[CropPoint]] = None  # 4-point perspective crop
    rotation: float = 0  # Rotation angle in degrees


class PreviewCropRequest(BaseModel):
    batch_name: str
    bbox: List[int]  # [x1, y1, x2, y2]


class ReconvertTiffRequest(BaseModel):
    path: str  # Relative path under captures dir (e.g. "colorchecker/captures")
    checker_raw_path: Optional[str] = None  # Use this RAW's WB for all conversions


# ─── Calibration Models ───

class CalibrateRequest(BaseModel):
    batch_name: str
    profile_name: Optional[str] = None  # Use saved profile
    colorchecker_image: Optional[str] = None  # Detect from image
    checker_raw_path: Optional[str] = None  # RAW path for fixed WB calibration


class DetectColorCheckerRequest(BaseModel):
    image_path: str
    save_profile: bool = False
    profile_name: Optional[str] = None


# ─── PBR Models ───

class PBRRequest(BaseModel):
    batch_name: str
    mode: str = "grayscale"  # grayscale, colored, both
    selected_images: Optional[List[str]] = None  # None = all images


# ─── Material Tools Models ───

class EqualizePreviewRequest(BaseModel):
    batch_name: str
    method: str = "clahe"  # clahe, histogram_match, exposure_match
    reference_image: Optional[str] = None
    clip_limit: float = 2.0


class EqualizeApplyRequest(BaseModel):
    batch_name: str
    method: str = "clahe"
    reference_image: Optional[str] = None
    clip_limit: float = 2.0
    apply_to_all: bool = True


class DelightPreviewRequest(BaseModel):
    batch_name: str
    blur_radius: int = 200
    strength: float = 1.0
    method: str = "gaussian"  # gaussian, frequency_separation


class DelightApplyRequest(BaseModel):
    batch_name: str
    blur_radius: int = 200
    strength: float = 1.0
    method: str = "gaussian"
    apply_to_all: bool = True


class FlattenPreviewRequest(BaseModel):
    batch_name: str
    strength: float = 1.0
    smoothing_radius: int = 0
    pbr_mode: str = "grayscale"  # grayscale or color


class FlattenApplyRequest(BaseModel):
    batch_name: str
    strength: float = 1.0
    smoothing_radius: int = 0
    pbr_mode: str = "grayscale"
    apply_to_all: bool = True


class PerspectivePoint(BaseModel):
    x: float
    y: float


class PerspectiveDetectRequest(BaseModel):
    batch_name: str


class PerspectivePreviewRequest(BaseModel):
    batch_name: str
    source_points: List[PerspectivePoint]
    dest_points: Optional[List[PerspectivePoint]] = None


class PerspectiveApplyRequest(BaseModel):
    batch_name: str
    source_points: List[PerspectivePoint]
    dest_points: Optional[List[PerspectivePoint]] = None
    apply_to_all: bool = True


class SeamlessAnalyzeRequest(BaseModel):
    batch_name: str
    blend_width: Optional[int] = None


class SeamlessPreviewRequest(BaseModel):
    batch_name: str
    method: str = "overlay"  # overlay, mirror, poisson
    blend_width: int = 64
    spots_removal: bool = False
    color_equalizer: int = 0
    tile_count: int = 2


class SeamlessApplyRequest(BaseModel):
    batch_name: str
    method: str = "overlay"  # overlay, mirror, poisson
    blend_width: int = 64
    spots_removal: bool = False
    color_equalizer: int = 0


class TilePreviewRequest(BaseModel):
    batch_name: str
    tile_x: int = 2
    tile_y: int = 2
    offset_x: float = 0.0
    offset_y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    overlap: float = 0.0
    half_drop: bool = False


class TileApplyRequest(BaseModel):
    batch_name: str
    tile_x: int = 2
    tile_y: int = 2
    offset_x: float = 0.0
    offset_y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    overlap: float = 0.0
    half_drop: bool = False
    output_resolution: Optional[List[int]] = None


class ValidateCheckRequest(BaseModel):
    batch_name: str
    mode: str = "grayscale"
    albedo_dark_threshold: float = 30.0
    metal_range: Optional[List[float]] = None


class CloneInpaintRequest(BaseModel):
    batch_name: str
    mask_data: str  # base64 mask
    method: str = "telea"
    radius: int = 5


class CloneStampRequest(BaseModel):
    batch_name: str
    source_pos: PerspectivePoint
    target_pos: PerspectivePoint
    radius: int = 50
    fade: float = 1.0
    blur_mask: float = 0.0
    mirror: bool = False


class CloneApplyRequest(BaseModel):
    batch_name: str
    operations: List[dict]


class StraightenAnalyzeRequest(BaseModel):
    batch_name: str
    grid_divisions: int = 20
    direction: str = 'both'  # both, warp, weft


class StraightenPreviewRequest(BaseModel):
    batch_name: str
    mode: str = 'auto'  # auto, skew, bow
    strength: float = 1.0
    direction: str = 'both'
    grid_divisions: int = 20
    manual_skew_angle: Optional[float] = None


class StraightenApplyRequest(BaseModel):
    batch_name: str
    mode: str = 'auto'
    strength: float = 1.0
    direction: str = 'both'
    grid_divisions: int = 20
    manual_skew_angle: Optional[float] = None

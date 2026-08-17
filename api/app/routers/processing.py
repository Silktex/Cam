"""
Processing Router - Image processing pipeline endpoints (crop, color
calibration, PBR map generation, material tools).

Thin HTTP layer: parse/validate, delegate orchestration to the
app.services.processing_* modules, map errors to HTTP. Behavior is
identical to the pre-extraction router.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, BackgroundTasks

from app.config import settings
from app.models.processing import (
    AutoCropRequest, CalibrateRequest, CloneApplyRequest, CloneInpaintRequest,
    CloneStampRequest, CropApplyRequest, DetectColorCheckerRequest,
    DelightApplyRequest, DelightPreviewRequest, EqualizeApplyRequest,
    EqualizePreviewRequest, FlattenApplyRequest, FlattenPreviewRequest,
    ManualCropRequest, PBRRequest, PerspectiveApplyRequest,
    PerspectiveDetectRequest, PerspectivePreviewRequest, PreviewCropRequest,
    ReconvertTiffRequest, SeamlessAnalyzeRequest, SeamlessApplyRequest,
    SeamlessPreviewRequest, StraightenAnalyzeRequest, StraightenApplyRequest,
    StraightenPreviewRequest, TileApplyRequest, TilePreviewRequest, ValidateCheckRequest,
)
from app.services.database import get_batch, update_batch_status, sync_batch
from app.services import (
    processing_calibration_service as calibration,
    processing_crop_service as crop,
    processing_pbr_service as pbr,
    processing_tools_service as tools,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_batch_path(batch_name: str) -> Path:
    """Get full path to batch folder"""
    return settings.CAPTURES_DIR / batch_name


def validate_batch(batch_name: str) -> dict:
    """Validate batch exists"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    batch_path = get_batch_path(batch_name)
    if not batch_path.exists():
        raise HTTPException(status_code=404, detail=f"Batch folder not found: {batch_path}")

    return batch


def _run(label: str, fn, *args):
    """Delegate to a tool service call, mapping failures to 500 exactly as
    the previous inline endpoint bodies did (HTTPException passes through)."""
    try:
        return fn(*args)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"{label} failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _run_synced(label: str, fn, request, batch_path, background_tasks):
    """_run plus the background batch sync the inline apply bodies did."""
    result = _run(label, fn, request, batch_path)
    background_tasks.add_task(sync_batch, request.batch_name)
    return result

# ─── Crop Endpoints (Interactive Workflow) ───

@router.get("/crop/top-image/{batch_name}")
async def get_top_image_for_crop(batch_name: str):
    """Step 1: Get top image for crop interface (dimensions + thumbnail URL)."""
    validate_batch(batch_name)
    return crop.get_top_image(get_batch_path(batch_name))


@router.post("/crop/auto-detect")
async def auto_detect_crop(request: AutoCropRequest):
    """Step 2a: Auto-detect crop boundary on TOP image only (nothing saved)."""
    validate_batch(request.batch_name)
    return crop.auto_detect_endpoint(get_batch_path(request.batch_name), request.crop_size)


@router.post("/crop/preview-manual")
async def preview_manual_crop(request: PreviewCropRequest):
    """Step 2b: Preview manual crop on TOP image without saving."""
    validate_batch(request.batch_name)
    return crop.preview_manual(get_batch_path(request.batch_name), request.bbox)


@router.post("/crop/apply")
async def apply_crop(request: CropApplyRequest, background_tasks: BackgroundTasks):
    """Step 3: Apply confirmed crop to ALL images (bbox or 4-point + rotation)."""
    validate_batch(request.batch_name)
    return crop.apply_crop_flow(request, get_batch_path(request.batch_name),
                                background_tasks, update_batch_status, sync_batch)


@router.post("/crop/manual")
async def manual_crop(request: ManualCropRequest, background_tasks: BackgroundTasks):
    """Legacy: Direct manual crop. Use /crop/apply instead."""
    apply_request = CropApplyRequest(
        batch_name=request.batch_name,
        bbox=request.bbox,
        crop_type="manual"
    )
    return await apply_crop(apply_request, background_tasks)


@router.post("/crop/auto")
async def auto_crop(request: AutoCropRequest, background_tasks: BackgroundTasks):
    """Legacy: Direct auto crop. Use /crop/auto-detect then /crop/apply."""
    validate_batch(request.batch_name)
    return crop.auto_crop_flow(request, get_batch_path(request.batch_name),
                               background_tasks, update_batch_status, sync_batch)


@router.get("/crop/preview/{batch_name}")
async def get_crop_preview(batch_name: str):
    """Legacy: Get preview. Use /crop/top-image/{batch_name} instead."""
    return await get_top_image_for_crop(batch_name)


@router.post("/reconvert-tiff")
async def reconvert_tiff(request: ReconvertTiffRequest):
    """Re-convert all RAW files under path/raw to TIFF (optional fixed WB)."""
    return crop.reconvert_tiff_flow(request)


# ─── Color Calibration Endpoints ───
@router.post("/colorchecker/detect")
async def detect_colorchecker(request: DetectColorCheckerRequest):
    """Detect ColorChecker in an image and optionally save as profile."""
    image_path = Path(request.image_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {request.image_path}")

    return calibration.detect_colorchecker(image_path, request.save_profile, request.profile_name)


@router.get("/colorchecker/profiles")
async def list_colorchecker_profiles():
    """List all saved ColorChecker profiles"""
    return calibration.list_profiles()


@router.post("/calibrate")
async def calibrate_batch(request: CalibrateRequest, background_tasks: BackgroundTasks):
    """Apply color calibration to batch images (saved profile or detect image)."""
    validate_batch(request.batch_name)
    return calibration.calibrate_flow(request, get_batch_path(request.batch_name),
                                      background_tasks, update_batch_status, sync_batch)


@router.get("/calibrate/preview/{batch_name}")
async def get_calibration_preview(batch_name: str):
    """Get before/after comparison for calibration preview"""
    validate_batch(batch_name)
    return calibration.get_preview(get_batch_path(batch_name))


# ─── PBR Generation Endpoints ───
@router.post("/pbr")
async def generate_pbr(request: PBRRequest, background_tasks: BackgroundTasks):
    """Generate PBR maps (albedo, normals, roughness, height). Modes:
    grayscale (faster), colored (preserves color), both."""
    validate_batch(request.batch_name)
    return pbr.generate_flow(request, get_batch_path(request.batch_name),
                             background_tasks, update_batch_status, sync_batch)


@router.get("/pbr/preview/{batch_name}")
async def get_pbr_preview(batch_name: str):
    """Get preview of generated PBR maps"""
    validate_batch(batch_name)
    return pbr.preview_maps(get_batch_path(batch_name), batch_name)


# ─── Pipeline Status ───
@router.get("/status/{batch_name}")
async def get_processing_status(batch_name: str):
    """Get full processing pipeline status for a batch"""
    batch = validate_batch(batch_name)
    return {
        "batch_name": batch_name,
        "crop_status": batch.get("crop_status", "pending"),
        "crop_type": batch.get("crop_type"),
        "calibration_status": batch.get("calibration_status", "pending"),
        "pbr_status": batch.get("pbr_status", "pending"),
        "pbr_mode": batch.get("pbr_mode"),
        "folders": tools.pipeline_folders(get_batch_path(batch_name)),
    }


@router.get("/tools/status/{batch_name}")
async def get_tools_status(batch_name: str):
    """Check which pipeline output folders exist for a batch."""
    validate_batch(batch_name)
    return tools.tools_status(get_batch_path(batch_name), batch_name)


@router.get("/{tool}/image/{batch_name}")
async def get_tool_image(tool: str, batch_name: str):
    """Get the top/source image for any processing tool (info + thumbnail URLs)."""
    validate_batch(batch_name)
    return tools.get_tool_image(get_batch_path(batch_name), batch_name, tool)


# ─── Equalize Endpoints ───
@router.post("/equalize/preview")
async def equalize_preview(request: EqualizePreviewRequest):
    """Preview equalization on the top image."""
    validate_batch(request.batch_name)
    return _run("Equalize preview", tools.equalize_preview, request, get_batch_path(request.batch_name))


@router.post("/equalize/apply")
async def equalize_apply(request: EqualizeApplyRequest, background_tasks: BackgroundTasks):
    """Apply equalization to all images in batch."""
    validate_batch(request.batch_name)
    return _run_synced("Equalize apply", tools.equalize_apply, request,
                       get_batch_path(request.batch_name), background_tasks)


# ─── Delight Endpoints ───
@router.post("/delight/preview")
async def delight_preview(request: DelightPreviewRequest):
    """Preview delighting on the top image."""
    validate_batch(request.batch_name)
    return _run("Delight preview", tools.delight_preview, request, get_batch_path(request.batch_name))


@router.post("/delight/apply")
async def delight_apply(request: DelightApplyRequest, background_tasks: BackgroundTasks):
    """Apply delighting to all images in batch."""
    validate_batch(request.batch_name)
    return _run_synced("Delight apply", tools.delight_apply, request,
                       get_batch_path(request.batch_name), background_tasks)


# ─── Flatten Endpoints ───
@router.post("/flatten/preview")
async def flatten_preview(request: FlattenPreviewRequest):
    """Preview flattening on the top image using PBR normal maps."""
    validate_batch(request.batch_name)
    return _run("Flatten preview", tools.flatten_preview, request, get_batch_path(request.batch_name))


@router.post("/flatten/apply")
async def flatten_apply(request: FlattenApplyRequest, background_tasks: BackgroundTasks):
    """Apply flattening to all images in batch using PBR normal maps."""
    validate_batch(request.batch_name)
    return _run_synced("Flatten apply", tools.flatten_apply, request,
                       get_batch_path(request.batch_name), background_tasks)


# ─── Perspective Endpoints ───
@router.post("/perspective/detect-lines")
async def perspective_detect_lines(request: PerspectiveDetectRequest):
    """Detect lines in the top image for perspective correction."""
    validate_batch(request.batch_name)
    return _run("Perspective detect-lines", tools.perspective_detect_lines,
                request, get_batch_path(request.batch_name))


@router.post("/perspective/preview")
async def perspective_preview(request: PerspectivePreviewRequest):
    """Preview perspective transform on top image."""
    validate_batch(request.batch_name)
    return _run("Perspective preview", tools.perspective_preview,
                request, get_batch_path(request.batch_name))


@router.post("/perspective/apply")
async def perspective_apply(request: PerspectiveApplyRequest, background_tasks: BackgroundTasks):
    """Apply perspective correction to all images in batch."""
    validate_batch(request.batch_name)
    return _run_synced("Perspective apply", tools.perspective_apply, request,
                       get_batch_path(request.batch_name), background_tasks)


# ─── Seamless Endpoints ───
@router.post("/seamless/analyze")
async def seamless_analyze(request: SeamlessAnalyzeRequest):
    """Analyze edge continuity for seamless tiling."""
    validate_batch(request.batch_name)
    return _run("Seamless analyze", tools.seamless_analyze,
                request, get_batch_path(request.batch_name))


@router.post("/seamless/preview")
async def seamless_preview(request: SeamlessPreviewRequest):
    """Preview seamless tiling result."""
    validate_batch(request.batch_name)
    return _run("Seamless preview", tools.seamless_preview,
                request, get_batch_path(request.batch_name))


@router.post("/seamless/apply")
async def seamless_apply(request: SeamlessApplyRequest, background_tasks: BackgroundTasks):
    """Apply seamless tiling to all images."""
    validate_batch(request.batch_name)
    return _run_synced("Seamless apply", tools.seamless_apply, request,
                       get_batch_path(request.batch_name), background_tasks)


# ─── Tile Endpoints ───
@router.post("/tile/preview")
async def tile_preview(request: TilePreviewRequest):
    """Preview tiled output."""
    validate_batch(request.batch_name)
    return _run("Tile preview", tools.tile_preview, request, get_batch_path(request.batch_name))


@router.post("/tile/apply")
async def tile_apply(request: TileApplyRequest, background_tasks: BackgroundTasks):
    """Apply tiling to generate final output."""
    validate_batch(request.batch_name)
    return _run_synced("Tile apply", tools.tile_apply, request,
                       get_batch_path(request.batch_name), background_tasks)


# ─── Validate Endpoints ───
@router.post("/validate/check")
async def validate_check(request: ValidateCheckRequest):
    """Run PBR validation checks on batch maps."""
    validate_batch(request.batch_name)
    return _run("Validate check", tools.validate_check,
                request, get_batch_path(request.batch_name))


@router.get("/validate/stats/{batch_name}")
async def validate_stats(batch_name: str):
    """Get PBR map statistics for a batch."""
    validate_batch(batch_name)
    return _run("Validate stats", tools.validate_stats, batch_name, get_batch_path(batch_name))


# ─── Clone / Inpaint Endpoints ───
@router.post("/clone/inpaint")
async def clone_inpaint(request: CloneInpaintRequest):
    """Inpaint masked region using surrounding pixels."""
    validate_batch(request.batch_name)
    return _run("Clone inpaint", tools.clone_inpaint, request, get_batch_path(request.batch_name))


@router.post("/clone/stamp")
async def clone_stamp(request: CloneStampRequest):
    """Clone stamp from source to target position."""
    validate_batch(request.batch_name)
    return _run("Clone stamp", tools.clone_stamp, request, get_batch_path(request.batch_name))


@router.post("/clone/apply")
async def clone_apply(request: CloneApplyRequest, background_tasks: BackgroundTasks):
    """Apply all clone/inpaint operations permanently."""
    validate_batch(request.batch_name)
    return _run_synced("Clone apply", tools.clone_apply, request,
                       get_batch_path(request.batch_name), background_tasks)


# ─── Straighten Endpoints ───
@router.post("/straighten/analyze")
async def straighten_analyze(request: StraightenAnalyzeRequest):
    """Analyze yarn alignment — detect skew and bow."""
    validate_batch(request.batch_name)
    return _run("Straighten analyze", tools.straighten_analyze,
                request, get_batch_path(request.batch_name))


@router.post("/straighten/preview")
async def straighten_preview(request: StraightenPreviewRequest):
    """Preview straighten correction on top image."""
    validate_batch(request.batch_name)
    return _run("Straighten preview", tools.straighten_preview,
                request, get_batch_path(request.batch_name))


@router.post("/straighten/apply")
async def straighten_apply(request: StraightenApplyRequest, background_tasks: BackgroundTasks):
    """Apply straighten correction to all images in batch."""
    validate_batch(request.batch_name)
    return _run_synced("Straighten apply", tools.straighten_apply, request,
                       get_batch_path(request.batch_name), background_tasks)

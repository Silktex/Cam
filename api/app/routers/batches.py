"""
Batches Router - Batch management and processing status
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from app.services.database import (
    get_all_batches,
    get_batch,
    get_batch_images,
    get_batches_by_status,
    update_batch_status,
    update_image_pbr_selection,
    get_processing_summary,
    sync_batch,
    sync_all_batches,
    get_config,
    save_config,
    get_media_path,
    set_media_path,
)

router = APIRouter()


# ─── Pydantic Models ───

class BatchStatusUpdate(BaseModel):
    status: str  # pending, in_progress, completed
    crop_type: Optional[str] = None  # manual, auto (for crop phase)
    pbr_mode: Optional[str] = None  # grayscale, colored, both (for pbr phase)


class PBRSelectionUpdate(BaseModel):
    filename: str
    selected: bool


class MediaPathUpdate(BaseModel):
    path: str


# ─── Settings Endpoints ───

@router.get("/settings")
async def get_settings():
    """Get current settings including media path"""
    config = get_config()
    return {
        "media_path": str(get_media_path()),
        "last_sync": config.get("last_sync"),
        "auto_sync_on_startup": config.get("auto_sync_on_startup", True),
    }


@router.put("/settings/media-path")
async def update_media_path(update: MediaPathUpdate):
    """Update media path and trigger resync"""
    from pathlib import Path

    path = Path(update.path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"Path does not exist: {update.path}")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {update.path}")

    set_media_path(update.path)

    # Trigger full resync
    result = sync_all_batches()

    return {
        "success": True,
        "media_path": update.path,
        "sync_result": result,
    }


# ─── Sync Endpoints ───

@router.post("/sync")
async def sync_all():
    """Full resync: scan media folder and update database"""
    result = sync_all_batches()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@router.post("/sync/{batch_name}")
async def sync_single_batch(batch_name: str):
    """Sync a single batch"""
    result = sync_batch(batch_name)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


# ─── Batch Endpoints ───

@router.get("/")
async def list_batches():
    """List all batches with their processing status"""
    batches = get_all_batches()
    summary = get_processing_summary()
    return {
        "batches": batches,
        "summary": summary,
    }


@router.get("/summary")
async def processing_summary():
    """Get processing status summary across all phases"""
    return get_processing_summary()


@router.get("/status/{phase}/{status}")
async def list_batches_by_status(phase: str, status: str):
    """
    Get batches filtered by phase and status.
    Phase: crop, calibration, pbr
    Status: pending, in_progress, completed
    """
    if phase not in ['crop', 'calibration', 'pbr']:
        raise HTTPException(status_code=400, detail=f"Invalid phase: {phase}")
    if status not in ['pending', 'in_progress', 'completed']:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    batches = get_batches_by_status(phase, status)
    return {"phase": phase, "status": status, "batches": batches, "count": len(batches)}


@router.get("/{batch_name}")
async def get_batch_detail(batch_name: str):
    """Get detailed info for a single batch including all images"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    images = get_batch_images(batch_name)

    return {
        "batch": batch,
        "images": images,
    }


@router.get("/{batch_name}/images")
async def get_images(batch_name: str):
    """Get all images in a batch with their metadata and status"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    images = get_batch_images(batch_name)
    return {"batch_name": batch_name, "images": images, "count": len(images)}


# ─── Status Update Endpoints ───

@router.put("/{batch_name}/crop")
async def update_crop_status(batch_name: str, update: BatchStatusUpdate):
    """Update cropping phase status"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    success = update_batch_status(
        batch_name,
        'crop',
        update.status,
        crop_type=update.crop_type
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update status")

    return {"success": True, "batch": batch_name, "phase": "crop", "status": update.status}


@router.put("/{batch_name}/calibration")
async def update_calibration_status(batch_name: str, update: BatchStatusUpdate):
    """Update color calibration phase status"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    success = update_batch_status(batch_name, 'calibration', update.status)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update status")

    return {"success": True, "batch": batch_name, "phase": "calibration", "status": update.status}


@router.put("/{batch_name}/pbr")
async def update_pbr_status(batch_name: str, update: BatchStatusUpdate):
    """Update PBR generation phase status"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    success = update_batch_status(
        batch_name,
        'pbr',
        update.status,
        pbr_mode=update.pbr_mode
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update status")

    return {"success": True, "batch": batch_name, "phase": "pbr", "status": update.status}


@router.put("/{batch_name}/pbr-selection")
async def update_pbr_image_selection(batch_name: str, update: PBRSelectionUpdate):
    """Update PBR selection for a specific image (include/exclude from PBR processing)"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    success = update_image_pbr_selection(batch_name, update.filename, update.selected)

    if not success:
        raise HTTPException(status_code=404, detail=f"Image not found: {update.filename}")

    return {"success": True, "batch": batch_name, "filename": update.filename, "selected": update.selected}


@router.put("/{batch_name}/pbr-selection/bulk")
async def update_pbr_selection_bulk(batch_name: str, updates: List[PBRSelectionUpdate]):
    """Bulk update PBR selection for multiple images"""
    batch = get_batch(batch_name)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch not found: {batch_name}")

    results = []
    for update in updates:
        success = update_image_pbr_selection(batch_name, update.filename, update.selected)
        results.append({"filename": update.filename, "selected": update.selected, "success": success})

    return {"success": True, "batch": batch_name, "results": results}

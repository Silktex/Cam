"""
PBR orchestration service — thin orchestration layer between the processing
router and scripts.processing.pbr_service.

Extracted behavior-identically from app/routers/processing.py. The map-URL
Path walk for /pbr/preview moved here unchanged (png preferred over tiff).
"""
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)


def generate(batch_path: Path, mode: str, selected_images: Optional[List[str]]):
    """Generate PBR maps via photometric stereo.

    Exceptions propagate raw; the router owns status bookkeeping and the
    HTTP error mapping around this call.
    """
    from scripts.processing.pbr_service import PBRService

    pbr_service = PBRService()
    return pbr_service.generate(
        batch_path=str(batch_path),
        mode=mode,
        selected_images=selected_images,
    )


def generate_flow(request, batch_path: Path, background_tasks, update_status, sync) -> dict:
    """/pbr flow; update_status/sync injected so router-level patching stays
    authoritative (behavior-identical to the inline router body)."""
    if request.mode not in ['grayscale', 'colored', 'both']:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")

    try:
        update_status(request.batch_name, 'pbr', 'in_progress', pbr_mode=request.mode)

        result = generate(batch_path, request.mode, request.selected_images)

        if result.success:
            update_status(request.batch_name, 'pbr', 'completed', pbr_mode=request.mode)
        else:
            update_status(request.batch_name, 'pbr', 'pending', pbr_mode=request.mode)

        background_tasks.add_task(sync, request.batch_name)

        return {
            "success": result.success,
            "batch_name": request.batch_name,
            "mode": request.mode,
            "images_processed": result.images_processed,
            "outputs": result.outputs,
            "error": result.error,
        }

    except Exception as e:
        logger.error(f"PBR generation failed: {e}")
        update_status(request.batch_name, 'pbr', 'pending')
        raise HTTPException(status_code=500, detail=str(e))


def preview_maps(batch_path: Path, batch_name: str) -> dict:
    """Preview URLs for generated PBR maps; 404 when nothing is generated."""
    grayscale_folder = batch_path / "pbr_grayscale"
    colored_folder = batch_path / "pbr_colored"

    result = {
        "batch_name": batch_name,
        "grayscale": None,
        "colored": None,
    }

    def get_map_urls(folder: Path, mode: str) -> dict:
        if not folder.exists():
            return None

        maps = {}
        for map_type in ['albedo', 'normals', 'roughness', 'height_map']:
            # Check for .png first (new format), then .tiff (legacy)
            for ext in ['.png', '.tiff']:
                map_path = folder / f"{map_type}{ext}"
                if map_path.exists():
                    rel_path = map_path.relative_to(settings.CAPTURES_DIR)
                    maps[map_type] = f"/media/captures/{rel_path}"
                    break

        return maps if maps else None

    result["grayscale"] = get_map_urls(grayscale_folder, "grayscale")
    result["colored"] = get_map_urls(colored_folder, "colored")

    if not result["grayscale"] and not result["colored"]:
        raise HTTPException(status_code=404, detail="No PBR maps generated yet")

    return result

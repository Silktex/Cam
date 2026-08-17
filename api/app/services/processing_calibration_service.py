"""
Calibration orchestration service — thin orchestration layer between the
processing router and scripts.processing.calibration_service.

Extracted behavior-identically from app/routers/processing.py. The
colour-science availability flag is honored per call (lazy import), and the
historical error mapping (404s swallowed to 500 inside guarded blocks where
the original code did so) is preserved verbatim.
"""
import logging
from pathlib import Path
from typing import Optional, Tuple

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def detect_colorchecker(
    image_path: Path, save_profile: bool, profile_name: Optional[str]
) -> dict:
    """Detect ColorChecker in an image and optionally save as profile.

    Historical quirks preserved: colour-science absence raises 500 before
    the guarded block; a None detection raises 404 inside the block and
    therefore surfaces as 500 (str(exc) detail).
    """
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="colour-science library not installed. Run: pip install colour-science colour-checker-detection"
        )

    try:
        calibration_service = CalibrationService()
        checker_data = calibration_service.detect_colorchecker(str(image_path))

        if not checker_data:
            raise HTTPException(status_code=404, detail="No ColorChecker detected in image")

        result = {
            "success": True,
            "source_image": checker_data.source_image,
            "swatches_detected": len(checker_data.detected_swatches),
        }

        if save_profile and profile_name:
            profile_path = calibration_service.save_colorchecker_profile(
                checker_data,
                profile_name
            )
            result["profile_saved"] = True
            result["profile_path"] = profile_path

        return result

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"CalibrationService not available: {e}")
    except Exception as e:
        logger.error(f"ColorChecker detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def list_profiles() -> dict:
    """List saved ColorChecker profiles; never raises (errors in-band)."""
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        return {"profiles": [], "warning": "colour-science library not installed"}

    try:
        calibration_service = CalibrationService()
        profiles = calibration_service.list_profiles()
        return {"profiles": profiles}

    except Exception as e:
        logger.error(f"List profiles failed: {e}")
        return {"profiles": [], "error": str(e)}


def resolve_checker_data(
    profile_name: Optional[str], colorchecker_image: Optional[str]
) -> Tuple[object, object]:
    """Resolve checker data from a saved profile or a detection image.

    Returns (calibration_service, checker_data). Raises HTTPException for
    the router's passthrough paths (missing profile/image, bad request)
    and lets unexpected exceptions propagate to the caller's handler.
    """
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="colour-science library not installed"
        )

    calibration_service = CalibrationService()
    checker_data = None

    if profile_name:
        checker_data = calibration_service.load_colorchecker_profile(profile_name)
        if not checker_data:
            raise HTTPException(
                status_code=404,
                detail=f"Profile not found: {profile_name}"
            )
    elif colorchecker_image:
        image_path = Path(colorchecker_image)
        if not image_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"ColorChecker image not found: {colorchecker_image}"
            )
        checker_data = calibration_service.detect_colorchecker(str(image_path))
        if not checker_data:
            raise HTTPException(
                status_code=400,
                detail="No ColorChecker detected in provided image"
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either profile_name or colorchecker_image"
        )

    return calibration_service, checker_data


def calibrate_flow(request, batch_path: Path, background_tasks, update_status, sync) -> dict:
    """/calibrate flow; update_status/sync injected so router-level patching
    stays authoritative (behavior-identical to the inline router body)."""
    try:
        calibration_service, checker_data = resolve_checker_data(
            request.profile_name, request.colorchecker_image)

        update_status(request.batch_name, 'calibration', 'in_progress')

        result = calibrate(calibration_service, batch_path, checker_data,
                           request.checker_raw_path)

        update_status(request.batch_name, 'calibration',
                      'completed' if result["success"] else 'pending')

        background_tasks.add_task(sync, request.batch_name)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Calibration failed: {e}")
        update_status(request.batch_name, 'calibration', 'pending')
        raise HTTPException(status_code=500, detail=str(e))


def calibrate(
    calibration_service, batch_path: Path, checker_data, checker_raw_path: Optional[str]
) -> dict:
    """Apply calibration to all batch images; returns the /calibrate response.

    Exceptions propagate raw; the router owns status bookkeeping and the
    HTTP error mapping around this call.
    """
    results = calibration_service.calibrate_batch(
        batch_path=str(batch_path),
        checker_data=checker_data,
        checker_raw_path=checker_raw_path,
    )

    success_count = sum(1 for r in results if r.success)
    total_count = len(results)

    return {
        "success": success_count > 0,
        "batch_name": batch_path.name,
        "processed": success_count,
        "total": total_count,
        "results": [
            {
                "source": r.source_path,
                "output": r.output_path,
                "success": r.success,
                "error": r.error,
            }
            for r in results
        ],
    }


def get_preview(batch_path: Path) -> dict:
    """Before/after comparison for calibration preview.

    Historical quirk preserved: "No preview available" (404) is raised inside
    the guarded block and therefore surfaces as 500 (str(exc) detail).
    """
    from scripts.processing.calibration_service import CalibrationService, COLOUR_AVAILABLE

    if not COLOUR_AVAILABLE:
        raise HTTPException(status_code=500, detail="colour-science not available")

    try:
        calibration_service = CalibrationService()
        preview = calibration_service.get_preview_comparison(str(batch_path))

        if not preview:
            raise HTTPException(status_code=404, detail="No preview available")

        return preview

    except Exception as e:
        logger.error(f"Get calibration preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

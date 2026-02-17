"""
Celery tasks for post-processing captured RAW images.

Decodes RAW once at 8-bit sRGB and saves a single full-resolution JPG.
Thumbnails/webviews are served on-the-fly via the resize endpoint.
"""
import logging
from pathlib import Path

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=5)
def post_process_image(self, folder_path_str: str, raw_filename: str, ext: str):
    """
    Process a single RAW capture into a full-resolution JPG (saved to jpg/).

    Args:
        folder_path_str: Absolute path to the capture session folder.
        raw_filename: Filename of the RAW file inside folder/raw/.
        ext: Original file extension (e.g. '.ARW').
    """
    try:
        import rawpy
        from PIL import Image as PILImage
    except ImportError:
        logger.warning("rawpy/Pillow not installed — skipping post-processing")
        return {"status": "skipped", "reason": "missing dependencies"}

    folder_path = Path(folder_path_str)
    raw_path = folder_path / "raw" / raw_filename
    stem = Path(raw_filename).stem
    folder_name = folder_path.name

    # Create jpg/ subdirectory
    jpg_dir = folder_path / "jpg"
    jpg_dir.mkdir(exist_ok=True)

    result = {}

    try:
        with rawpy.imread(str(raw_path)) as raw:
            rgb_8 = raw.postprocess(
                use_camera_wb=True,
                output_bps=8,
                no_auto_bright=True,
                output_color=rawpy.ColorSpace.sRGB,
            )

        jpg_filename = f"{stem}.jpg"
        jpg_path = jpg_dir / jpg_filename
        img = PILImage.fromarray(rgb_8)
        img.save(str(jpg_path), format="JPEG", quality=95, optimize=True)
        result["jpg_url"] = f"/media/captures/{folder_name}/jpg/{jpg_filename}"
        logger.info(f"JPG saved: {jpg_path} ({img.size[0]}x{img.size[1]})")

    except Exception as e:
        logger.warning(f"Post-processing failed for {raw_filename}: {e}")
        raise self.retry(exc=e)

    logger.info(f"Post-processing complete for {raw_filename}")
    return result

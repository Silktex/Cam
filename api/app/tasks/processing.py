"""
Celery tasks for post-processing captured RAW images.

Extracted from CameraService._post_process_image() and optimised to decode
the RAW file only once (16-bit), then derive the 8-bit version via downscale
instead of calling rawpy.postprocess() a second time.
"""
import logging
from pathlib import Path

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=5)
def post_process_image(self, folder_path_str: str, raw_filename: str, ext: str):
    """
    Process a single RAW capture into derivative files:
      1. RAW -> 16-bit TIFF  (tiff/)
      2. RAW -> full web-view JPEG 2400px q92  (full_webview/)
      3. RAW -> thumbnail JPEG 400px q80  (thumbnail/)

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

    # Create output subdirectories
    tiff_dir = folder_path / "tiff"
    thumb_dir = folder_path / "thumbnail"
    webview_dir = folder_path / "full_webview"
    tiff_dir.mkdir(exist_ok=True)
    thumb_dir.mkdir(exist_ok=True)
    webview_dir.mkdir(exist_ok=True)

    result = {}

    try:
        with rawpy.imread(str(raw_path)) as raw:
            # Single decode at 16-bit — used for TIFF and as base for 8-bit
            rgb_16 = raw.postprocess(
                use_camera_wb=True,
                output_bps=16,
                no_auto_bright=True,
                output_color=rawpy.ColorSpace.sRGB,
                gamma=(1, 1),
            )

        # ── 1. TIFF (16-bit, full resolution) ──
        try:
            tiff_filename = f"{stem}.tiff"
            tiff_path = tiff_dir / tiff_filename

            try:
                import tifffile
                tifffile.imwrite(str(tiff_path), rgb_16, compression='lzw')
            except ImportError:
                try:
                    import imageio.v3 as iio
                    iio.imwrite(str(tiff_path), rgb_16)
                except ImportError:
                    rgb_8_tiff = (rgb_16 / 256).astype('uint8')
                    tiff_img = PILImage.fromarray(rgb_8_tiff)
                    tiff_img.save(str(tiff_path), format="TIFF", compression="tiff_lzw")
                    logger.info("Saved as 8-bit TIFF (install tifffile for 16-bit)")

            result["tiff_url"] = f"/media/captures/{folder_name}/tiff/{tiff_filename}"
            logger.info(f"TIFF saved: {tiff_path}")
        except Exception as e:
            logger.warning(f"TIFF conversion failed: {e}", exc_info=True)

        # ── 2 & 3. Derive 8-bit from 16-bit (single decode optimisation) ──
        try:
            import numpy as np
            rgb_8 = (rgb_16.astype(np.float32) / 256).astype('uint8')
            full_img = PILImage.fromarray(rgb_8)

            # Full webview — resize to max 2400px on longest side
            webview_filename = f"{stem}.jpg"
            webview_path = webview_dir / webview_filename
            webview_img = full_img.copy()
            webview_img.thumbnail((2400, 2400), PILImage.Resampling.LANCZOS)
            webview_img.save(str(webview_path), format="JPEG", quality=92, optimize=True)
            result["webview_url"] = f"/media/captures/{folder_name}/full_webview/{webview_filename}"
            logger.info(f"Webview saved: {webview_path} ({webview_img.size[0]}x{webview_img.size[1]})")

            # Thumbnail — resize to max 400px
            thumb_filename = f"{stem}.jpg"
            thumb_path = thumb_dir / thumb_filename
            thumb_img = full_img.copy()
            thumb_img.thumbnail((400, 400), PILImage.Resampling.LANCZOS)
            thumb_img.save(str(thumb_path), format="JPEG", quality=80, optimize=True)
            result["thumbnail_url"] = f"/media/captures/{folder_name}/thumbnail/{thumb_filename}"
            logger.info(f"Thumbnail saved: {thumb_path} ({thumb_img.size[0]}x{thumb_img.size[1]})")
        except Exception as e:
            logger.warning(f"Webview/thumbnail generation failed: {e}")

    except Exception as e:
        logger.warning(f"Post-processing failed for {raw_filename}: {e}")
        raise self.retry(exc=e)

    logger.info(f"Post-processing complete for {raw_filename}")
    return result

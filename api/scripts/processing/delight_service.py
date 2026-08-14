"""
Delight Service - Remove uneven lighting from material textures.
Creates flat, evenly-lit textures suitable for tiling and PBR workflows.

Methods:
- Gaussian: Divide by low-frequency luminance (simple, fast)
- Frequency Separation: High-pass detail preservation (better quality)
"""
import logging
from pathlib import Path
from typing import Optional, Dict, List

import cv2
import numpy as np

logger = logging.getLogger(__name__)

TIFF_EXTENSIONS = {'.tiff', '.tif'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'} | TIFF_EXTENSIONS


def _find_source_folder(batch_path: Path) -> Optional[Path]:
    """Find best source folder: flattened > equalized > color_calibrated > cropped > tiff"""
    for folder_name in ['flattened', 'equalized', 'color_calibrated', 'cropped', 'tiff']:
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            return folder
    return None


def _list_images(folder: Path) -> List[Path]:
    """List all supported images in a folder, sorted."""
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(folder.glob(f"*{ext}"))
        images.extend(folder.glob(f"*{ext.upper()}"))
    return sorted(images)


def _load_image(path: Path) -> Optional[np.ndarray]:
    """Load image preserving bit depth."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        logger.error(f"Failed to load: {path}")
    return img


def _save_preview(img: np.ndarray, path: Path, max_size: int = 1200):
    """Save a JPG preview, converting 16-bit to 8-bit if needed."""
    if img.dtype == np.uint16:
        img = (img / 256).astype(np.uint8)
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        s = max_size / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])


def _find_top_image(images: List[Path]) -> Optional[Path]:
    """Find the TOP image from the list."""
    for img in images:
        name_lower = img.name.lower()
        if '_top' in name_lower or name_lower.startswith('top'):
            return img
    return images[0] if images else None


def delight_gaussian(image: np.ndarray, blur_radius: int = 200, strength: float = 1.0) -> np.ndarray:
    """
    Remove lighting by dividing by low-frequency luminance.

    1. Convert to float32 [0,1] for full precision
    2. Convert to LAB, blur L channel heavily to get lighting estimate
    3. Divide original L by blurred L to remove gradients
    4. Blend result with original based on strength
    """
    is_16bit = image.dtype == np.uint16
    original_dtype = image.dtype

    # Work in float32 throughout to preserve 16-bit precision
    if is_16bit:
        img_f = (image.astype(np.float32) / 65535.0 * 255.0).clip(0, 255).astype(np.uint8)
    elif image.dtype == np.float32 or image.dtype == np.float64:
        img_f = (image * 255.0).clip(0, 255).astype(np.uint8)
    else:
        img_f = image.copy()

    lab = cv2.cvtColor(img_f, cv2.COLOR_BGR2LAB).astype(np.float32)
    l_channel = lab[:, :, 0]

    # Ensure blur radius is odd
    ksize = blur_radius if blur_radius % 2 == 1 else blur_radius + 1
    l_blurred = cv2.GaussianBlur(l_channel, (ksize, ksize), 0)

    # Avoid division by zero
    l_blurred = np.maximum(l_blurred, 1.0)

    # Divide to remove lighting gradients
    mean_l = l_blurred.mean()
    l_delighted = (l_channel / l_blurred) * mean_l

    # Blend with original based on strength
    l_result = l_channel * (1.0 - strength) + l_delighted * strength
    lab[:, :, 0] = np.clip(l_result, 0, 255)

    result_8 = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)

    # Scale back to original bit depth
    if is_16bit:
        # Map 8-bit result back to 16-bit using the original image's per-pixel ratio
        # to preserve sub-8-bit tonal detail
        orig_f = image.astype(np.float32)
        input_8 = img_f.astype(np.float32)
        result_f = result_8.astype(np.float32)
        ratio = np.where(input_8 > 0.5, result_f / input_8, 1.0)
        result_16 = np.clip(orig_f * ratio, 0, 65535).astype(np.uint16)
        return result_16

    return result_8


def delight_frequency_separation(
    image: np.ndarray, blur_radius: int = 200, strength: float = 1.0
) -> np.ndarray:
    """
    Frequency separation delighting.

    1. Separate image into low-frequency (lighting) and high-frequency (detail)
    2. Replace low-frequency with flat average
    3. Recombine with strength blending

    Works in float32 throughout to preserve 16-bit precision.
    """
    is_16bit = image.dtype == np.uint16

    # Convert to float32 [0, 1]
    if is_16bit:
        img_float = image.astype(np.float32) / 65535.0
    elif image.dtype == np.uint8:
        img_float = image.astype(np.float32) / 255.0
    else:
        img_float = image.astype(np.float32)

    # Ensure blur radius is odd
    ksize = blur_radius if blur_radius % 2 == 1 else blur_radius + 1

    # Low frequency = heavily blurred image
    low_freq = cv2.GaussianBlur(img_float, (ksize, ksize), 0)

    # High frequency = original - low frequency (centered at 0.5)
    high_freq = img_float - low_freq + 0.5

    # Create flat replacement for low frequency (uniform average color)
    flat_low = np.full_like(low_freq, low_freq.mean(axis=(0, 1)))

    # Blend the low frequency between original and flat based on strength
    blended_low = low_freq * (1.0 - strength) + flat_low * strength

    # Recombine
    result = blended_low + high_freq - 0.5
    result = np.clip(result, 0, 1)

    # Convert back to original dtype
    if is_16bit:
        return (result * 65535).astype(np.uint16)
    elif image.dtype == np.uint8:
        return (result * 255).astype(np.uint8)
    return result


def preview(
    batch_path: str,
    blur_radius: int = 200,
    strength: float = 1.0,
    method: str = 'gaussian',
) -> Dict:
    """
    Process the top image and return a preview.
    Returns paths to before/after preview images.
    """
    batch_path = Path(batch_path)
    source_folder = _find_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found"}

    images = _list_images(source_folder)
    top_image = _find_top_image(images)
    if not top_image:
        return {"success": False, "error": "No images found in batch"}

    img = _load_image(top_image)
    if img is None:
        return {"success": False, "error": f"Failed to load {top_image.name}"}

    # Apply delighting
    if method == 'frequency_separation':
        result = delight_frequency_separation(img, blur_radius=blur_radius, strength=strength)
    else:
        result = delight_gaussian(img, blur_radius=blur_radius, strength=strength)

    # Save preview images
    preview_dir = batch_path / "delighted_preview"
    preview_dir.mkdir(exist_ok=True)

    before_path = preview_dir / "before.jpg"
    after_path = preview_dir / "after.jpg"
    _save_preview(img, before_path)
    _save_preview(result, after_path)

    batch_name = batch_path.name

    return {
        "success": True,
        "before_url": f"/media/captures/{batch_name}/delighted_preview/before.jpg",
        "after_url": f"/media/captures/{batch_name}/delighted_preview/after.jpg",
        "method": method,
        "blur_radius": blur_radius,
        "strength": strength,
        "source_image": top_image.name,
        "image_count": len(images),
    }


def apply(
    batch_path: str,
    blur_radius: int = 200,
    strength: float = 1.0,
    method: str = 'gaussian',
) -> Dict:
    """
    Apply delighting to all images in the batch.
    Saves results to delighted/ subfolder.
    """
    batch_path = Path(batch_path)
    source_folder = _find_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found", "processed": 0, "total": 0}

    images = _list_images(source_folder)
    if not images:
        return {"success": False, "error": "No images found", "processed": 0, "total": 0}

    output_dir = batch_path / "delighted"
    output_dir.mkdir(exist_ok=True)

    thumb_dir = batch_path / "delighted_thumbnail"
    thumb_dir.mkdir(exist_ok=True)

    processed = 0
    errors = []

    for image_path in images:
        try:
            img = _load_image(image_path)
            if img is None:
                errors.append({"file": image_path.name, "error": "Failed to load"})
                continue

            if method == 'frequency_separation':
                result = delight_frequency_separation(img, blur_radius=blur_radius, strength=strength)
            else:
                result = delight_gaussian(img, blur_radius=blur_radius, strength=strength)

            # Save as TIFF
            out_path = output_dir / f"{image_path.stem}.tiff"
            cv2.imwrite(str(out_path), result)

            # Save thumbnail
            thumb_path = thumb_dir / f"{image_path.stem}.jpg"
            _save_preview(result, thumb_path, max_size=800)

            processed += 1
            logger.info(f"Delighted: {image_path.name} -> {out_path.name}")

        except Exception as e:
            logger.error(f"Error delighting {image_path.name}: {e}")
            errors.append({"file": image_path.name, "error": str(e)})

    return {
        "success": processed > 0,
        "processed": processed,
        "total": len(images),
        "method": method,
        "output_dir": str(output_dir),
        "errors": errors,
    }

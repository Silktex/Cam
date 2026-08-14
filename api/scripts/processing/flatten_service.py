"""
Flatten Service - Remove surface undulation from fabric textures using PBR normal maps.
Uses computed normals to derive a shading correction factor, dividing out
geometry-induced lighting variation so the texture appears flat.

Requires PBR maps to be generated first (normal map needed).
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
    """Find best source folder: equalized > color_calibrated > cropped > tiff"""
    for folder_name in ['equalized', 'color_calibrated', 'cropped', 'tiff']:
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            return folder
    return None


def _find_pbr_normals(batch_path: Path, pbr_mode: str = "grayscale") -> Optional[Path]:
    """Locate the normal map from PBR output."""
    folder_name = "pbr_colored" if pbr_mode == "color" else "pbr_grayscale"
    normals_path = batch_path / folder_name / "normals.png"
    if normals_path.exists():
        return normals_path
    # Fallback to other mode
    alt_folder = "pbr_grayscale" if pbr_mode == "color" else "pbr_colored"
    alt_path = batch_path / alt_folder / "normals.png"
    if alt_path.exists():
        return alt_path
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


def _load_normals(path: Path) -> Optional[np.ndarray]:
    """Load normal map and decode from RGB to [-1, 1] vector field."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        logger.error(f"Failed to load normals: {path}")
        return None

    # Convert BGR to RGB
    if len(img.shape) == 3 and img.shape[2] >= 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Decode based on bit depth
    if img.dtype == np.uint16:
        normals = (img.astype(np.float32) / 65535.0) * 2.0 - 1.0
    else:
        normals = (img.astype(np.float32) / 255.0) * 2.0 - 1.0

    return normals


def flatten_image(
    image: np.ndarray,
    normals: np.ndarray,
    strength: float = 1.0,
    smoothing_radius: int = 0,
) -> np.ndarray:
    """
    Remove surface undulation shading from an image using normal map data.

    1. Optionally smooth normals (controls correction scale)
    2. Compute cos(theta) = normals.z (dot product with top light [0,0,1])
    3. Divide L channel by cos(theta) to remove geometry-induced shading
    4. Blend with original based on strength

    Works in float32 throughout to preserve 16-bit precision.
    """
    is_16bit = image.dtype == np.uint16
    h, w = image.shape[:2]

    # Convert to 8-bit for LAB conversion (OpenCV LAB needs uint8)
    if is_16bit:
        img_8 = (image.astype(np.float32) / 65535.0 * 255.0).clip(0, 255).astype(np.uint8)
    elif image.dtype in (np.float32, np.float64):
        img_8 = (image * 255.0).clip(0, 255).astype(np.uint8)
    else:
        img_8 = image.copy()

    # Resize normals to match source image if needed
    nh, nw = normals.shape[:2]
    if nh != h or nw != w:
        normals = cv2.resize(normals, (w, h), interpolation=cv2.INTER_LINEAR)

    # Optional smoothing of normals
    if smoothing_radius > 0:
        ksize = smoothing_radius if smoothing_radius % 2 == 1 else smoothing_radius + 1
        for c in range(3):
            normals[:, :, c] = cv2.GaussianBlur(normals[:, :, c], (ksize, ksize), 0)
        # Re-normalize after blurring
        norms = np.linalg.norm(normals, axis=2, keepdims=True)
        normals = normals / np.maximum(norms, 1e-8)

    # Compute shading factor (cosine of angle from vertical)
    cos_theta = normals[:, :, 2]
    cos_theta = np.clip(cos_theta, 0.05, 1.0)

    # Convert to LAB and correct L channel
    lab = cv2.cvtColor(img_8, cv2.COLOR_BGR2LAB).astype(np.float32)
    l_channel = lab[:, :, 0]

    # Divide by cos_theta to remove geometry shading
    l_corrected = l_channel / cos_theta

    # Preserve mean luminance
    mean_orig = l_channel.mean()
    mean_corrected = l_corrected.mean()
    if mean_corrected > 0:
        l_corrected = l_corrected * (mean_orig / mean_corrected)

    # Blend with original based on strength
    l_result = l_channel * (1.0 - strength) + l_corrected * strength
    lab[:, :, 0] = np.clip(l_result, 0, 255)

    result_8 = cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)

    # Scale back to original bit depth preserving sub-8-bit detail
    if is_16bit:
        orig_f = image.astype(np.float32)
        input_f = img_8.astype(np.float32)
        result_f = result_8.astype(np.float32)
        ratio = np.where(input_f > 0.5, result_f / input_f, 1.0)
        return np.clip(orig_f * ratio, 0, 65535).astype(np.uint16)

    return result_8


def preview(
    batch_path: str,
    strength: float = 1.0,
    smoothing_radius: int = 0,
    pbr_mode: str = 'grayscale',
) -> Dict:
    """
    Process the top image and return a preview.
    Returns paths to before/after preview images.
    """
    batch_path = Path(batch_path)
    source_folder = _find_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found"}

    # Find normal map
    normals_path = _find_pbr_normals(batch_path, pbr_mode)
    if not normals_path:
        return {"success": False, "error": "No PBR normal maps found. Generate PBR maps first."}

    normals = _load_normals(normals_path)
    if normals is None:
        return {"success": False, "error": "Failed to load normal map"}

    images = _list_images(source_folder)
    top_image = _find_top_image(images)
    if not top_image:
        return {"success": False, "error": "No images found in batch"}

    img = _load_image(top_image)
    if img is None:
        return {"success": False, "error": f"Failed to load {top_image.name}"}

    # Apply flattening
    result = flatten_image(img, normals, strength=strength, smoothing_radius=smoothing_radius)

    # Save preview images
    preview_dir = batch_path / "flattened_preview"
    preview_dir.mkdir(exist_ok=True)

    before_path = preview_dir / "before.jpg"
    after_path = preview_dir / "after.jpg"
    _save_preview(img, before_path)
    _save_preview(result, after_path)

    batch_name = batch_path.name

    return {
        "success": True,
        "before_url": f"/media/captures/{batch_name}/flattened_preview/before.jpg",
        "after_url": f"/media/captures/{batch_name}/flattened_preview/after.jpg",
        "strength": strength,
        "smoothing_radius": smoothing_radius,
        "pbr_mode": pbr_mode,
        "source_image": top_image.name,
        "image_count": len(images),
    }


def apply(
    batch_path: str,
    strength: float = 1.0,
    smoothing_radius: int = 0,
    pbr_mode: str = 'grayscale',
) -> Dict:
    """
    Apply flattening to all images in the batch.
    Saves results to flattened/ subfolder.
    """
    batch_path = Path(batch_path)
    source_folder = _find_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found", "processed": 0, "total": 0}

    # Find normal map
    normals_path = _find_pbr_normals(batch_path, pbr_mode)
    if not normals_path:
        return {"success": False, "error": "No PBR normal maps found. Generate PBR maps first.", "processed": 0, "total": 0}

    normals = _load_normals(normals_path)
    if normals is None:
        return {"success": False, "error": "Failed to load normal map", "processed": 0, "total": 0}

    images = _list_images(source_folder)
    if not images:
        return {"success": False, "error": "No images found", "processed": 0, "total": 0}

    output_dir = batch_path / "flattened"
    output_dir.mkdir(exist_ok=True)

    thumb_dir = batch_path / "flattened_thumbnail"
    thumb_dir.mkdir(exist_ok=True)

    processed = 0
    errors = []

    for image_path in images:
        try:
            img = _load_image(image_path)
            if img is None:
                errors.append({"file": image_path.name, "error": "Failed to load"})
                continue

            result = flatten_image(img, normals, strength=strength, smoothing_radius=smoothing_radius)

            # Save as TIFF
            out_path = output_dir / f"{image_path.stem}.tiff"
            cv2.imwrite(str(out_path), result)

            # Save thumbnail
            thumb_path = thumb_dir / f"{image_path.stem}.jpg"
            _save_preview(result, thumb_path, max_size=800)

            processed += 1
            logger.info(f"Flattened: {image_path.name} -> {out_path.name}")

        except Exception as e:
            logger.error(f"Error flattening {image_path.name}: {e}")
            errors.append({"file": image_path.name, "error": str(e)})

    return {
        "success": processed > 0,
        "processed": processed,
        "total": len(images),
        "pbr_mode": pbr_mode,
        "output_dir": str(output_dir),
        "errors": errors,
    }

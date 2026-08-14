"""
Exposure Service - In-memory exposure equalization and roughness scaling.

Provides fast in-memory transforms for the image-processing pipeline preview,
plus on-disk operations for the save step.
"""
import logging
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {'.tiff', '.tif', '.png', '.jpg', '.jpeg'}


def _find_top_image(folder: Path) -> Optional[Path]:
    """Find the TOP image from a folder."""
    for ext in IMAGE_EXTENSIONS:
        for path in sorted(folder.glob(f"*{ext}")) + sorted(folder.glob(f"*{ext.upper()}")):
            if '_top' in path.name.lower() or path.name.lower().startswith('top'):
                return path
    # Fallback: first image
    for ext in IMAGE_EXTENSIONS:
        imgs = sorted(folder.glob(f"*{ext}")) + sorted(folder.glob(f"*{ext.upper()}"))
        if imgs:
            return imgs[0]
    return None


def _find_source_folder(batch_path: Path) -> Optional[Path]:
    """Find best source folder for exposure: color_calibrated > cropped > tiff."""
    for folder_name in ['color_calibrated', 'cropped', 'tiff']:
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            return folder
    return None


def _save_preview(img: np.ndarray, path: Path, max_size: int = 1200):
    """Save a JPG preview."""
    if img.dtype == np.uint16:
        img = (img >> 8).astype(np.uint8)
    elif img.dtype in (np.float32, np.float64):
        img = np.clip(img * 255, 0, 255).astype(np.uint8)
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        s = max_size / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])


# ── In-memory transforms ──


def apply_exposure_inmemory(
    image: np.ndarray,
    offset: float = 0.0,
    method: str = "exposure_match",
    reference: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Apply exposure adjustment in-memory (no disk writes).

    Args:
        image: Input image (uint8, uint16, or float32)
        offset: EV offset (-3.0 to +3.0). 0 = no change.
        method: "exposure_match" (reference-based) or "offset" (EV shift)
        reference: Reference image for exposure_match method

    Returns:
        Adjusted image in same dtype as input
    """
    original_dtype = image.dtype

    # Work in float32
    if image.dtype == np.uint16:
        img_f = image.astype(np.float32) / 65535.0
    elif image.dtype == np.uint8:
        img_f = image.astype(np.float32) / 255.0
    else:
        img_f = image.astype(np.float32)

    if method == "exposure_match" and reference is not None:
        # Match mean brightness to reference
        if reference.dtype == np.uint16:
            ref_f = reference.astype(np.float32) / 65535.0
        elif reference.dtype == np.uint8:
            ref_f = reference.astype(np.float32) / 255.0
        else:
            ref_f = reference.astype(np.float32)

        src_mean = img_f.mean()
        ref_mean = ref_f.mean()
        if src_mean > 1e-8:
            scale = ref_mean / src_mean
            img_f = img_f * scale

    # Apply EV offset
    if abs(offset) > 0.001:
        multiplier = 2.0 ** offset
        img_f = img_f * multiplier

    img_f = np.clip(img_f, 0.0, 1.0)

    # Convert back
    if original_dtype == np.uint16:
        return (img_f * 65535).astype(np.uint16)
    elif original_dtype == np.uint8:
        return (img_f * 255).astype(np.uint8)
    return img_f


def apply_roughness_scale_inmemory(
    roughness_map: np.ndarray,
    scale: float = 1.0,
) -> np.ndarray:
    """
    Scale roughness map values in-memory.

    Args:
        roughness_map: Roughness map (uint8 or uint16)
        scale: Multiplier (0.5x to 2.0x). 1.0 = no change.

    Returns:
        Scaled roughness map in same dtype
    """
    if abs(scale - 1.0) < 0.001:
        return roughness_map

    original_dtype = roughness_map.dtype

    if roughness_map.dtype == np.uint16:
        img_f = roughness_map.astype(np.float32) / 65535.0
    elif roughness_map.dtype == np.uint8:
        img_f = roughness_map.astype(np.float32) / 255.0
    else:
        img_f = roughness_map.astype(np.float32)

    img_f = np.clip(img_f * scale, 0.0, 1.0)

    if original_dtype == np.uint16:
        return (img_f * 65535).astype(np.uint16)
    elif original_dtype == np.uint8:
        return (img_f * 255).astype(np.uint8)
    return img_f


# ── Preview endpoints (disk-based, returns URLs) ──


def preview_exposure(
    batch_path: str,
    offset: float = 0.0,
    method: str = "exposure_match",
) -> Dict:
    """Generate exposure preview for the top image."""
    batch_path = Path(batch_path)
    source = _find_source_folder(batch_path)
    if not source:
        return {"success": False, "error": "No source images found"}

    top = _find_top_image(source)
    if not top:
        return {"success": False, "error": "No images found"}

    img = cv2.imread(str(top), cv2.IMREAD_UNCHANGED)
    if img is None:
        return {"success": False, "error": f"Failed to load {top.name}"}

    result = apply_exposure_inmemory(img, offset=offset, method=method)

    preview_dir = batch_path / "exposure_preview"
    preview_dir.mkdir(exist_ok=True)

    before_path = preview_dir / "before.jpg"
    after_path = preview_dir / "after.jpg"
    _save_preview(img, before_path)
    _save_preview(result, after_path)

    batch_name = batch_path.name
    return {
        "success": True,
        "before_url": f"/media/captures/{batch_name}/exposure_preview/before.jpg",
        "after_url": f"/media/captures/{batch_name}/exposure_preview/after.jpg",
        "offset": offset,
        "method": method,
    }


def preview_roughness_scale(
    batch_path: str,
    scale: float = 1.0,
    pbr_mode: str = "grayscale",
) -> Dict:
    """Generate roughness scale preview."""
    batch_path = Path(batch_path)
    folder_name = "pbr_colored" if pbr_mode == "color" else "pbr_grayscale"
    roughness_path = batch_path / folder_name / "roughness.png"

    if not roughness_path.exists():
        return {"success": False, "error": "No roughness map found. Generate PBR first."}

    img = cv2.imread(str(roughness_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return {"success": False, "error": "Failed to load roughness map"}

    result = apply_roughness_scale_inmemory(img, scale=scale)

    preview_dir = batch_path / "roughness_preview"
    preview_dir.mkdir(exist_ok=True)

    before_path = preview_dir / "before.jpg"
    after_path = preview_dir / "after.jpg"
    _save_preview(img, before_path)
    _save_preview(result, after_path)

    batch_name = batch_path.name
    return {
        "success": True,
        "before_url": f"/media/captures/{batch_name}/roughness_preview/before.jpg",
        "after_url": f"/media/captures/{batch_name}/roughness_preview/after.jpg",
        "scale": scale,
        "pbr_mode": pbr_mode,
    }

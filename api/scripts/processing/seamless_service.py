"""
Seamless Service - Make textures tile seamlessly using various blending methods.

Methods:
- overlay: Shifted-copy overlay with feathered blend at borders
- mirror: Mirror-fold edges and linear blend in overlap zone
- poisson: Gradient-domain blending at seam zones (OpenCV seamlessClone)

Workflow:
1. analyze_seams() — Measure edge continuity (L2 distance)
2. preview() — Generate seamless preview + tiled preview
3. apply() — Apply to all images, save to seamless/
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.config import settings
from .raw_utils import save_tiff, is_raw_file, load_raw

logger = logging.getLogger(__name__)

TIFF_EXTENSIONS = {'.tiff', '.tif'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
SUPPORTED_EXTENSIONS = TIFF_EXTENSIONS | IMAGE_EXTENSIONS

SOURCE_PRIORITY = ['straightened', 'perspective_corrected', 'color_calibrated', 'cropped', 'tiff']


def _get_source_folder(batch_path: Path) -> Tuple[Optional[Path], str]:
    """Find source folder by priority."""
    for folder_name in SOURCE_PRIORITY:
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            return folder, folder_name
    return None, ''


def _list_images(folder: Path) -> List[Path]:
    """List supported image files."""
    images = []
    for ext in SUPPORTED_EXTENSIONS:
        images.extend(folder.glob(f"*{ext}"))
        images.extend(folder.glob(f"*{ext.upper()}"))
    return sorted(images)


def _find_top_image(images: List[Path]) -> Optional[Path]:
    """Find the TOP image."""
    for img in images:
        name_lower = img.name.lower()
        if '_top' in name_lower or name_lower.startswith('top'):
            return img
    return images[0] if images else None


def _load_image(path: Path) -> Optional[np.ndarray]:
    """Load image."""
    if is_raw_file(path):
        rgb = load_raw(path)
        if rgb is not None:
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return None
    return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)


def _to_8bit(img: np.ndarray) -> np.ndarray:
    """Convert to 8-bit for processing if needed."""
    if img.dtype == np.uint16:
        return (img / 256).astype(np.uint8)
    return img


def _save_preview_jpg(img: np.ndarray, path: Path, max_size: int = 1600):
    """Save image as JPG preview."""
    h, w = img.shape[:2]
    out = _to_8bit(img)
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        out = cv2.resize(out, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), out, [cv2.IMWRITE_JPEG_QUALITY, 90])


def analyze_seams(image_path: Path, blend_width: int = 128) -> dict:
    """
    Measure seam quality — L2 distance between opposite edges.

    Compares top row vs bottom row, left col vs right col within
    the blend_width zone to assess how well edges will tile.

    Returns:
        dict with scores for each edge and overall_score
    """
    img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return {"success": False, "error": "Failed to load image"}

    img = _to_8bit(img).astype(np.float32)
    h, w = img.shape[:2]
    bw = min(blend_width, h // 4, w // 4)

    # Compare opposite edges
    top_strip = img[:bw, :, :]
    bottom_strip = img[-bw:, :, :]
    top_score = float(np.mean(np.sqrt(np.sum((top_strip - bottom_strip[::-1])**2, axis=-1))))

    left_strip = img[:, :bw, :]
    right_strip = img[:, -bw:, :]
    left_score = float(np.mean(np.sqrt(np.sum((left_strip - right_strip[:, ::-1])**2, axis=-1))))

    # Also compute simple edge-to-edge (row 0 vs row -1)
    top_edge = img[0, :, :].astype(np.float32)
    bottom_edge = img[-1, :, :].astype(np.float32)
    tb_score = float(np.mean(np.sqrt(np.sum((top_edge - bottom_edge)**2, axis=-1))))

    left_edge = img[:, 0, :].astype(np.float32)
    right_edge = img[:, -1, :].astype(np.float32)
    lr_score = float(np.mean(np.sqrt(np.sum((left_edge - right_edge)**2, axis=-1))))

    overall = (tb_score + lr_score) / 2

    return {
        "success": True,
        "scores": {
            "top": round(tb_score, 2),
            "bottom": round(tb_score, 2),
            "left": round(lr_score, 2),
            "right": round(lr_score, 2),
        },
        "overall_score": round(overall, 2),
        "blend_width": bw,
    }


def make_seamless_overlay(
    img: np.ndarray,
    blend_width: int = 128,
    spots_removal: bool = False,
    color_equalizer: int = 0,
) -> np.ndarray:
    """
    Overlay method: shift image by half, then feather-blend the seam borders.

    1. Create shifted copy (offset by half width and half height)
    2. Linear blend in the overlap zones at the seam boundaries
    """
    h, w = img.shape[:2]
    is_16bit = img.dtype == np.uint16
    work = img.astype(np.float64)

    bw = min(blend_width, h // 4, w // 4)

    # Shift by half
    shifted = np.roll(np.roll(work, h // 2, axis=0), w // 2, axis=1)

    # Create blend mask
    result = shifted.copy()

    # Horizontal seam blend (at y = h//2)
    seam_y = h // 2
    y_start = max(0, seam_y - bw // 2)
    y_end = min(h, seam_y + bw // 2)
    for y in range(y_start, y_end):
        alpha = (y - y_start) / max(1, y_end - y_start)
        result[y] = shifted[y] * alpha + work[y] * (1 - alpha)

    # Vertical seam blend (at x = w//2)
    seam_x = w // 2
    x_start = max(0, seam_x - bw // 2)
    x_end = min(w, seam_x + bw // 2)
    for x in range(x_start, x_end):
        alpha = (x - x_start) / max(1, x_end - x_start)
        result[:, x] = shifted[:, x] * alpha + work[:, x] * (1 - alpha)

    # Optional color equalization
    if color_equalizer > 0:
        blur_size = color_equalizer * 2 + 1
        mean_original = cv2.GaussianBlur(work, (blur_size, blur_size), 0)
        mean_result = cv2.GaussianBlur(result, (blur_size, blur_size), 0)
        # Adjust result to match original color distribution
        mask = mean_result > 1e-6
        correction = np.ones_like(result)
        correction[mask] = mean_original[mask] / mean_result[mask]
        correction = np.clip(correction, 0.5, 2.0)
        result = result * correction

    # Optional spots removal using median filter on seam zones
    if spots_removal:
        result_8 = np.clip(result, 0, 65535 if is_16bit else 255)
        result_8 = result_8.astype(np.uint8) if not is_16bit else (result_8 / 256).astype(np.uint8)
        median = cv2.medianBlur(result_8, 5)
        # Only apply at seam zones
        seam_mask = np.zeros((h, w), dtype=np.float64)
        seam_mask[y_start:y_end, :] = 1.0
        seam_mask[:, x_start:x_end] = 1.0
        seam_mask = cv2.GaussianBlur(seam_mask, (bw // 2 * 2 + 1, bw // 2 * 2 + 1), 0)
        if not is_16bit:
            median_f = median.astype(np.float64)
        else:
            median_f = median.astype(np.float64) * 256
        for c in range(result.shape[2] if len(result.shape) == 3 else 1):
            if len(result.shape) == 3:
                result[:, :, c] = result[:, :, c] * (1 - seam_mask * 0.3) + median_f[:, :, c] * seam_mask * 0.3
            else:
                result = result * (1 - seam_mask * 0.3) + median_f * seam_mask * 0.3

    max_val = 65535 if is_16bit else 255
    result = np.clip(result, 0, max_val)
    return result.astype(np.uint16 if is_16bit else np.uint8)


def make_seamless_mirror(img: np.ndarray, blend_width: int = 128) -> np.ndarray:
    """
    Mirror method: mirror-fold edges and linear blend in the overlap zone.

    Creates seamless tile by mirroring and blending each edge.
    """
    h, w = img.shape[:2]
    is_16bit = img.dtype == np.uint16
    work = img.astype(np.float64)
    result = work.copy()
    bw = min(blend_width, h // 4, w // 4)

    # Top edge: blend with vertically flipped bottom
    top_zone = work[:bw, :]
    bottom_zone = work[-bw:, :][::-1, :]
    for i in range(bw):
        alpha = i / max(1, bw)
        result[i] = top_zone[i] * alpha + bottom_zone[i] * (1 - alpha)

    # Bottom edge: blend with vertically flipped top
    top_flipped = work[:bw, :][::-1, :]
    for i in range(bw):
        alpha = i / max(1, bw)
        result[h - bw + i] = work[h - bw + i] * alpha + top_flipped[i] * (1 - alpha)

    # Left edge: blend with horizontally flipped right
    left_zone = result[:, :bw]
    right_zone = result[:, -bw:][:, ::-1]
    for i in range(bw):
        alpha = i / max(1, bw)
        result[:, i] = left_zone[:, i] * alpha + right_zone[:, i] * (1 - alpha)

    # Right edge: blend with horizontally flipped left
    left_flipped = result[:, :bw][:, ::-1]
    for i in range(bw):
        alpha = i / max(1, bw)
        result[:, w - bw + i] = result[:, w - bw + i] * alpha + left_flipped[:, i] * (1 - alpha)

    max_val = 65535 if is_16bit else 255
    result = np.clip(result, 0, max_val)
    return result.astype(np.uint16 if is_16bit else np.uint8)


def make_seamless_poisson(img: np.ndarray, blend_width: int = 128) -> np.ndarray:
    """
    Poisson method: gradient-domain blending at seam zones.

    Uses OpenCV's seamlessClone on border regions for smooth transitions.
    """
    h, w = img.shape[:2]
    is_16bit = img.dtype == np.uint16
    bw = min(blend_width, h // 4, w // 4)

    # Work in 8-bit for seamlessClone
    if is_16bit:
        work = (img / 256).astype(np.uint8)
    else:
        work = img.copy()

    # Create a tiled version (2x2) then extract the center
    tiled = np.tile(work, (2, 2, 1) if len(work.shape) == 3 else (2, 2))

    # Extract the center region which naturally has the seams
    center_patch = tiled[h // 2:h // 2 + h, w // 2:w // 2 + w]

    # Create mask for seam zones
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[:bw, :] = 255
    mask[-bw:, :] = 255
    mask[:, :bw] = 255
    mask[:, -bw:] = 255

    # Apply seamless clone
    center = (w // 2, h // 2)
    try:
        result = cv2.seamlessClone(center_patch, work, mask, center, cv2.MIXED_CLONE)
    except cv2.error:
        # Fallback to mirror method if seamlessClone fails
        logger.warning("Poisson blending failed, falling back to mirror method")
        return make_seamless_mirror(img, blend_width)

    if is_16bit:
        # Scale back up to 16-bit
        result = result.astype(np.uint16) * 256
        # Preserve non-seam areas from original
        interior_mask = mask == 0
        if len(img.shape) == 3:
            for c in range(img.shape[2]):
                result[:, :, c][interior_mask] = img[:, :, c][interior_mask]
        else:
            result[interior_mask] = img[interior_mask]

    return result


def generate_tiled_preview(seamless_image: np.ndarray, tile_count: int = 3) -> np.ndarray:
    """
    Generate NxN tiled preview to verify seamlessness.

    Args:
        seamless_image: The seamless texture
        tile_count: Number of tiles in each direction

    Returns:
        Tiled preview image
    """
    work = _to_8bit(seamless_image)
    h, w = work.shape[:2]

    # Scale down individual tiles if the result would be too large
    max_total = 3200
    tile_max = max_total // tile_count
    if max(h, w) > tile_max:
        scale = tile_max / max(h, w)
        work = cv2.resize(work, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    return np.tile(work, (tile_count, tile_count, 1) if len(work.shape) == 3 else (tile_count, tile_count))


def preview(
    batch_path: Path,
    method: str = 'overlay',
    blend_width: int = 128,
    spots_removal: bool = False,
    color_equalizer: int = 0,
    tile_count: int = 3,
) -> dict:
    """
    Generate seamless preview for top image.

    Returns:
        dict with preview_url, tiled_url, seam_scores
    """
    source_folder, source_type = _get_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found"}

    images = _list_images(source_folder)
    top_image = _find_top_image(images)
    if not top_image:
        return {"success": False, "error": "No top image found"}

    img = _load_image(top_image)
    if img is None:
        return {"success": False, "error": "Failed to load image"}

    # Apply seamless method
    if method == 'mirror':
        seamless = make_seamless_mirror(img, blend_width)
    elif method == 'poisson':
        seamless = make_seamless_poisson(img, blend_width)
    else:
        seamless = make_seamless_overlay(img, blend_width, spots_removal, color_equalizer)

    # Generate tiled preview
    tiled = generate_tiled_preview(seamless, tile_count)

    # Save previews
    batch_name = batch_path.name
    preview_dir = batch_path / "seamless_preview"
    preview_dir.mkdir(exist_ok=True)

    seamless_path = preview_dir / f"{top_image.stem}_seamless.jpg"
    _save_preview_jpg(seamless, seamless_path)

    tiled_path = preview_dir / f"{top_image.stem}_tiled.jpg"
    _save_preview_jpg(tiled, tiled_path, max_size=2400)

    original_path = preview_dir / f"{top_image.stem}_original.jpg"
    _save_preview_jpg(img, original_path)

    # Analyze seam scores on result
    seamless_8 = _to_8bit(seamless).astype(np.float32)
    sh, sw = seamless_8.shape[:2]
    top_edge = seamless_8[0, :, :]
    bottom_edge = seamless_8[-1, :, :]
    tb = float(np.mean(np.sqrt(np.sum((top_edge - bottom_edge)**2, axis=-1))))
    left_edge = seamless_8[:, 0, :]
    right_edge = seamless_8[:, -1, :]
    lr = float(np.mean(np.sqrt(np.sum((left_edge - right_edge)**2, axis=-1))))

    return {
        "success": True,
        "preview_url": f"/media/captures/{batch_name}/seamless_preview/{top_image.stem}_seamless.jpg",
        "tiled_url": f"/media/captures/{batch_name}/seamless_preview/{top_image.stem}_tiled.jpg",
        "original_url": f"/media/captures/{batch_name}/seamless_preview/{top_image.stem}_original.jpg",
        "seam_scores": {
            "top": round(tb, 2),
            "bottom": round(tb, 2),
            "left": round(lr, 2),
            "right": round(lr, 2),
        },
        "overall_score": round((tb + lr) / 2, 2),
        "width": seamless.shape[1],
        "height": seamless.shape[0],
    }


def apply(
    batch_path: Path,
    method: str = 'overlay',
    blend_width: int = 128,
    spots_removal: bool = False,
    color_equalizer: int = 0,
) -> dict:
    """
    Apply seamless transform to all images, save to seamless/.
    """
    source_folder, source_type = _get_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found"}

    images = _list_images(source_folder)
    if not images:
        return {"success": False, "error": "No images found"}

    output_folder = batch_path / "seamless"
    output_folder.mkdir(exist_ok=True)

    thumb_folder = batch_path / "seamless_thumbnail"
    thumb_folder.mkdir(exist_ok=True)

    processed = 0
    errors = []

    for image_path in images:
        try:
            img = _load_image(image_path)
            if img is None:
                errors.append(f"Failed to load {image_path.name}")
                continue

            if method == 'mirror':
                seamless = make_seamless_mirror(img, blend_width)
            elif method == 'poisson':
                seamless = make_seamless_poisson(img, blend_width)
            else:
                seamless = make_seamless_overlay(img, blend_width, spots_removal, color_equalizer)

            # Save as TIFF
            output_path = output_folder / f"{image_path.stem}.tiff"
            if seamless.dtype == np.uint16:
                img_rgb = cv2.cvtColor(seamless, cv2.COLOR_BGR2RGB)
                if not save_tiff(img_rgb, output_path, compression='zlib'):
                    cv2.imwrite(str(output_path), seamless)
            else:
                cv2.imwrite(str(output_path), seamless)

            # Save thumbnail
            thumb_path = thumb_folder / f"{image_path.stem}.jpg"
            _save_preview_jpg(seamless, thumb_path, max_size=800)

            processed += 1
            logger.info(f"Made seamless: {image_path.name}")

        except Exception as e:
            logger.error(f"Error processing {image_path.name}: {e}")
            errors.append(f"{image_path.name}: {str(e)}")

    return {
        "success": processed > 0,
        "processed": processed,
        "total": len(images),
        "errors": errors,
        "output_folder": "seamless",
    }

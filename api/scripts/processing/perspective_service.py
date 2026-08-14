"""
Perspective Service - Detect lines and apply perspective correction to images.

Workflow:
1. detect_lines() — Hough transform to suggest 4 corner points
2. preview() — Apply transform to top image, return preview
3. apply() — Apply transform to all images, save to perspective_corrected/
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.config import settings
from .raw_utils import load_raw, save_tiff, is_raw_file, RAW_EXTENSIONS

logger = logging.getLogger(__name__)

TIFF_EXTENSIONS = {'.tiff', '.tif'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
SUPPORTED_EXTENSIONS = TIFF_EXTENSIONS | IMAGE_EXTENSIONS

SOURCE_PRIORITY = ['color_calibrated', 'cropped', 'tiff']


def _get_source_folder(batch_path: Path) -> Tuple[Optional[Path], str]:
    """Find source folder by priority: color_calibrated > cropped > tiff."""
    for folder_name in SOURCE_PRIORITY:
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            return folder, folder_name
    return None, ''


def _list_images(folder: Path) -> List[Path]:
    """List supported image files in folder."""
    images = []
    for ext in SUPPORTED_EXTENSIONS:
        images.extend(folder.glob(f"*{ext}"))
        images.extend(folder.glob(f"*{ext.upper()}"))
    return sorted(images)


def _find_top_image(images: List[Path]) -> Optional[Path]:
    """Find the TOP image from a list."""
    for img in images:
        name_lower = img.name.lower()
        if '_top' in name_lower or name_lower.startswith('top'):
            return img
    return images[0] if images else None


def _load_image(path: Path) -> Optional[np.ndarray]:
    """Load image (TIFF or standard format)."""
    if is_raw_file(path):
        rgb = load_raw(path)
        if rgb is not None:
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return None
    return cv2.imread(str(path), cv2.IMREAD_UNCHANGED)


def _save_preview_jpg(img: np.ndarray, path: Path, max_size: int = 1600):
    """Save image as JPG preview, scaled down if needed."""
    h, w = img.shape[:2]
    if img.dtype == np.uint16:
        img = (img / 256).astype(np.uint8)
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])


def _compute_dest_rect(source_points: List[Dict]) -> Tuple[np.ndarray, int, int]:
    """Compute destination rectangle from source quadrilateral."""
    pts = source_points
    top_w = np.sqrt((pts[1]['x'] - pts[0]['x'])**2 + (pts[1]['y'] - pts[0]['y'])**2)
    bottom_w = np.sqrt((pts[2]['x'] - pts[3]['x'])**2 + (pts[2]['y'] - pts[3]['y'])**2)
    left_h = np.sqrt((pts[3]['x'] - pts[0]['x'])**2 + (pts[3]['y'] - pts[0]['y'])**2)
    right_h = np.sqrt((pts[2]['x'] - pts[1]['x'])**2 + (pts[2]['y'] - pts[1]['y'])**2)

    out_w = int((top_w + bottom_w) / 2)
    out_h = int((left_h + right_h) / 2)

    dst = np.float32([
        [0, 0],
        [out_w, 0],
        [out_w, out_h],
        [0, out_h],
    ])
    return dst, out_w, out_h


def detect_lines(image_path: Path) -> dict:
    """
    Detect dominant lines using Hough transform, suggest 4 corner points.

    Returns:
        dict with suggested_corners and detected_lines
    """
    img = cv2.imread(str(image_path))
    if img is None:
        return {"success": False, "error": "Failed to load image"}

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Convert 16-bit to 8-bit if needed
    if gray.dtype == np.uint16:
        gray = (gray / 256).astype(np.uint8)

    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10)

    if lines is None:
        # Fallback: return image corners with 5% inset
        margin = 0.05
        return {
            "success": True,
            "suggested_corners": [
                {"x": int(w * margin), "y": int(h * margin)},
                {"x": int(w * (1 - margin)), "y": int(h * margin)},
                {"x": int(w * (1 - margin)), "y": int(h * (1 - margin))},
                {"x": int(w * margin), "y": int(h * (1 - margin))},
            ],
            "detected_lines": [],
            "method": "fallback",
        }

    # Classify lines as horizontal or vertical by angle
    horizontal = []
    vertical = []

    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1)) % 180
        length = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
        if angle < 30 or angle > 150:
            horizontal.append((x1, y1, x2, y2, length))
        elif 60 < angle < 120:
            vertical.append((x1, y1, x2, y2, length))

    # Sort by length, take top lines
    horizontal.sort(key=lambda l: l[4], reverse=True)
    vertical.sort(key=lambda l: l[4], reverse=True)

    # Use longest lines to estimate edges
    def avg_y(lines_list):
        if not lines_list:
            return None
        return int(np.mean([(l[1] + l[3]) / 2 for l in lines_list[:3]]))

    def avg_x(lines_list):
        if not lines_list:
            return None
        return int(np.mean([(l[0] + l[2]) / 2 for l in lines_list[:3]]))

    # Split horizontal lines into top and bottom by y position
    h_sorted = sorted(horizontal, key=lambda l: (l[1] + l[3]) / 2)
    mid_y = h / 2
    top_lines = [l for l in h_sorted if (l[1] + l[3]) / 2 < mid_y]
    bottom_lines = [l for l in h_sorted if (l[1] + l[3]) / 2 >= mid_y]

    # Split vertical lines into left and right
    v_sorted = sorted(vertical, key=lambda l: (l[0] + l[2]) / 2)
    mid_x = w / 2
    left_lines = [l for l in v_sorted if (l[0] + l[2]) / 2 < mid_x]
    right_lines = [l for l in v_sorted if (l[0] + l[2]) / 2 >= mid_x]

    top_y = avg_y(top_lines) if top_lines else int(h * 0.05)
    bottom_y = avg_y(bottom_lines) if bottom_lines else int(h * 0.95)
    left_x = avg_x(left_lines) if left_lines else int(w * 0.05)
    right_x = avg_x(right_lines) if right_lines else int(w * 0.95)

    suggested = [
        {"x": left_x, "y": top_y},
        {"x": right_x, "y": top_y},
        {"x": right_x, "y": bottom_y},
        {"x": left_x, "y": bottom_y},
    ]

    # Return detected lines for visualization
    detected = []
    for line in lines[:50]:  # Cap at 50 lines
        x1, y1, x2, y2 = line[0]
        detected.append({"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)})

    return {
        "success": True,
        "suggested_corners": suggested,
        "detected_lines": detected,
        "method": "hough",
        "image_width": w,
        "image_height": h,
    }


def preview(batch_path: Path, source_points: list, dest_points: list = None) -> dict:
    """
    Apply perspective transform to top image, return preview.

    Args:
        batch_path: Path to batch folder
        source_points: 4 corner points [{x, y}, ...] in TL, TR, BR, BL order
        dest_points: Optional destination points (defaults to computed rectangle)

    Returns:
        dict with success, preview_url, width, height
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

    src = np.float32([[p['x'], p['y']] for p in source_points])

    if dest_points:
        dst = np.float32([[p['x'], p['y']] for p in dest_points])
        out_w = int(max(dst[:, 0]))
        out_h = int(max(dst[:, 1]))
    else:
        dst, out_w, out_h = _compute_dest_rect(source_points)

    if out_w < 10 or out_h < 10:
        return {"success": False, "error": "Output dimensions too small"}

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (out_w, out_h))

    # Save preview
    batch_name = batch_path.name
    preview_dir = batch_path / "perspective_preview"
    preview_dir.mkdir(exist_ok=True)
    preview_path = preview_dir / f"{top_image.stem}_preview.jpg"
    _save_preview_jpg(warped, preview_path)

    # Also save original for before/after comparison
    original_preview = preview_dir / f"{top_image.stem}_original.jpg"
    _save_preview_jpg(img, original_preview)

    return {
        "success": True,
        "preview_url": f"/media/captures/{batch_name}/perspective_preview/{top_image.stem}_preview.jpg",
        "original_url": f"/media/captures/{batch_name}/perspective_preview/{top_image.stem}_original.jpg",
        "width": out_w,
        "height": out_h,
        "original_width": img.shape[1],
        "original_height": img.shape[0],
    }


def apply(batch_path: Path, source_points: list, dest_points: list = None) -> dict:
    """
    Apply perspective transform to all images, save to perspective_corrected/.

    Args:
        batch_path: Path to batch folder
        source_points: 4 corner points [{x, y}, ...]
        dest_points: Optional destination points

    Returns:
        dict with success, processed count, total count
    """
    source_folder, source_type = _get_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found"}

    images = _list_images(source_folder)
    if not images:
        return {"success": False, "error": "No images found in source folder"}

    src = np.float32([[p['x'], p['y']] for p in source_points])

    if dest_points:
        dst = np.float32([[p['x'], p['y']] for p in dest_points])
        out_w = int(max(dst[:, 0]))
        out_h = int(max(dst[:, 1]))
    else:
        dst, out_w, out_h = _compute_dest_rect(source_points)

    M = cv2.getPerspectiveTransform(src, dst)

    output_folder = batch_path / "perspective_corrected"
    output_folder.mkdir(exist_ok=True)

    thumb_folder = batch_path / "perspective_corrected_thumbnail"
    thumb_folder.mkdir(exist_ok=True)

    processed = 0
    errors = []

    for image_path in images:
        try:
            img = _load_image(image_path)
            if img is None:
                errors.append(f"Failed to load {image_path.name}")
                continue

            warped = cv2.warpPerspective(img, M, (out_w, out_h))

            # Save as TIFF
            output_path = output_folder / f"{image_path.stem}.tiff"
            if warped.dtype == np.uint16:
                img_rgb = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
                if not save_tiff(img_rgb, output_path, compression='zlib'):
                    cv2.imwrite(str(output_path), warped)
            else:
                cv2.imwrite(str(output_path), warped)

            # Save thumbnail
            thumb_path = thumb_folder / f"{image_path.stem}.jpg"
            _save_preview_jpg(warped, thumb_path, max_size=800)

            processed += 1
            logger.info(f"Perspective corrected: {image_path.name}")

        except Exception as e:
            logger.error(f"Error processing {image_path.name}: {e}")
            errors.append(f"{image_path.name}: {str(e)}")

    batch_name = batch_path.name
    return {
        "success": processed > 0,
        "processed": processed,
        "total": len(images),
        "errors": errors,
        "output_folder": f"perspective_corrected",
    }

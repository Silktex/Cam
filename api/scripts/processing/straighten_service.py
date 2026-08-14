"""
Straighten Service - Detect and correct yarn skew and bow in fabric textures.

Workflow:
1. analyze() — FFT-based global skew + strip Hough local bow measurement
2. preview() — Apply correction to top image, return before/after preview
3. apply() — Apply correction to all images, save to straightened/
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from scipy.interpolate import interp1d

from app.config import settings
from .raw_utils import save_tiff, is_raw_file, load_raw

logger = logging.getLogger(__name__)

TIFF_EXTENSIONS = {'.tiff', '.tif'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'}
SUPPORTED_EXTENSIONS = TIFF_EXTENSIONS | IMAGE_EXTENSIONS

SOURCE_PRIORITY = ['perspective_corrected', 'color_calibrated', 'cropped', 'tiff']


def _get_source_folder(batch_path: Path) -> Tuple[Optional[Path], str]:
    """Find source folder by priority."""
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


def _to_8bit(img: np.ndarray) -> np.ndarray:
    """Convert to 8-bit if needed."""
    if img.dtype == np.uint16:
        return (img / 256).astype(np.uint8)
    return img


def _detect_skew_fft(gray: np.ndarray) -> float:
    """Detect global skew angle using FFT angular projection.

    Returns skew angle in degrees (deviation from 0/90).
    """
    h, w = gray.shape
    # Apply Hanning window to reduce edge artifacts
    win_y = np.hanning(h)
    win_x = np.hanning(w)
    window = np.outer(win_y, win_x)
    windowed = gray.astype(np.float64) * window

    # 2D FFT power spectrum
    fft = np.fft.fft2(windowed)
    fft_shift = np.fft.fftshift(fft)
    power = np.log1p(np.abs(fft_shift))

    # Angular projection: sum power along radial lines
    cy, cx = h // 2, w // 2
    max_r = min(cy, cx) // 2
    angles = np.arange(0, 180, 0.5)
    projection = np.zeros(len(angles))

    for i, angle_deg in enumerate(angles):
        angle_rad = np.radians(angle_deg)
        cos_a = np.cos(angle_rad)
        sin_a = np.sin(angle_rad)
        total = 0.0
        count = 0
        for r in range(10, max_r):
            x = int(cx + r * cos_a)
            y = int(cy + r * sin_a)
            if 0 <= x < w and 0 <= y < h:
                total += power[y, x]
                count += 1
        if count > 0:
            projection[i] = total / count

    # Find two dominant peaks (should be ~90 degrees apart)
    # Smooth the projection to reduce noise
    kernel_size = 5
    kernel = np.ones(kernel_size) / kernel_size
    smooth = np.convolve(projection, kernel, mode='same')

    # Find peaks
    peaks = []
    for i in range(1, len(smooth) - 1):
        if smooth[i] > smooth[i - 1] and smooth[i] > smooth[i + 1]:
            peaks.append((smooth[i], angles[i]))

    peaks.sort(reverse=True)

    if not peaks:
        return 0.0

    # Primary peak angle - compute skew as deviation from nearest 0/90/180
    primary_angle = peaks[0][1]
    # Find nearest cardinal direction
    cardinals = [0, 90, 180]
    deviations = [primary_angle - c for c in cardinals]
    min_idx = np.argmin([abs(d) for d in deviations])
    skew = deviations[min_idx]

    # Clamp to reasonable range
    if abs(skew) > 20:
        return 0.0

    return float(skew)


def _detect_bow_strips(gray: np.ndarray, grid_divisions: int, direction: str) -> dict:
    """Detect local bow via strip Hough analysis.

    Returns bow data with per-strip measurements.
    """
    h, w = gray.shape
    weft_data = []
    warp_data = []

    if direction in ('both', 'weft'):
        # Horizontal strips for weft bow
        strip_h = h // grid_divisions
        for i in range(grid_divisions):
            y_start = i * strip_h
            y_end = min((i + 1) * strip_h, h)
            strip = gray[y_start:y_end, :]

            edges = cv2.Canny(strip, 50, 150)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=30,
                                    minLineLength=w // 8, maxLineGap=10)

            if lines is not None:
                angles = []
                displacements = []
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                    # Filter near-horizontal lines
                    if abs(angle) < 30:
                        angles.append(angle)
                        mid_y = (y1 + y2) / 2 - strip_h / 2
                        displacements.append(mid_y)

                if angles:
                    weft_data.append({
                        'strip_index': i,
                        'y_center': float(y_start + strip_h / 2),
                        'median_angle': float(np.median(angles)),
                        'displacement': float(np.median(displacements)),
                        'line_count': len(angles),
                    })

    if direction in ('both', 'warp'):
        # Vertical strips for warp bow
        strip_w = w // grid_divisions
        for i in range(grid_divisions):
            x_start = i * strip_w
            x_end = min((i + 1) * strip_w, w)
            strip = gray[:, x_start:x_end]

            edges = cv2.Canny(strip, 50, 150)
            lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=30,
                                    minLineLength=h // 8, maxLineGap=10)

            if lines is not None:
                angles = []
                displacements = []
                for line in lines:
                    x1, y1, x2, y2 = line[0]
                    angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                    # Filter near-vertical lines
                    if abs(abs(angle) - 90) < 30:
                        angles.append(angle - 90 if angle > 0 else angle + 90)
                        mid_x = (x1 + x2) / 2 - strip_w / 2
                        displacements.append(mid_x)

                if angles:
                    warp_data.append({
                        'strip_index': i,
                        'x_center': float(x_start + strip_w / 2),
                        'median_angle': float(np.median(angles)),
                        'displacement': float(np.median(displacements)),
                        'line_count': len(angles),
                    })

    max_weft_bow = 0.0
    max_warp_bow = 0.0

    if weft_data:
        disps = [d['displacement'] for d in weft_data]
        max_weft_bow = float(max(disps) - min(disps)) if disps else 0.0

    if warp_data:
        disps = [d['displacement'] for d in warp_data]
        max_warp_bow = float(max(disps) - min(disps)) if disps else 0.0

    return {
        'weft_data': weft_data,
        'warp_data': warp_data,
        'max_weft_bow_px': round(max_weft_bow, 2),
        'max_warp_bow_px': round(max_warp_bow, 2),
    }


def _correct_skew(img: np.ndarray, angle: float, strength: float) -> np.ndarray:
    """Apply skew correction via rotation.

    Rotates by the negative of the detected skew, scaled by strength.
    Center-crops back to original size.
    """
    h, w = img.shape[:2]
    corrected_angle = -angle * strength

    if abs(corrected_angle) < 0.01:
        return img.copy()

    center = (w / 2, h / 2)
    M = cv2.getRotationMatrix2D(center, corrected_angle, 1.0)

    # Compute new bounding box to avoid clipping
    cos_a = abs(np.cos(np.radians(corrected_angle)))
    sin_a = abs(np.sin(np.radians(corrected_angle)))
    new_w = int(w * cos_a + h * sin_a)
    new_h = int(h * cos_a + w * sin_a)

    M[0, 2] += (new_w - w) / 2
    M[1, 2] += (new_h - h) / 2

    rotated = cv2.warpAffine(img, M, (new_w, new_h), borderMode=cv2.BORDER_REFLECT_101)

    # Center-crop back to original size
    start_x = (new_w - w) // 2
    start_y = (new_h - h) // 2
    cropped = rotated[start_y:start_y + h, start_x:start_x + w]

    return cropped


def _correct_bow(img: np.ndarray, bow_data: dict, strength: float, direction: str) -> np.ndarray:
    """Apply bow correction using displacement maps from strip data."""
    h, w = img.shape[:2]
    map_x = np.zeros((h, w), dtype=np.float32)
    map_y = np.zeros((h, w), dtype=np.float32)

    # Initialize identity map
    for y in range(h):
        map_x[y, :] = np.arange(w, dtype=np.float32)
        map_y[y, :] = float(y)

    if direction in ('both', 'weft') and bow_data.get('weft_data'):
        weft = bow_data['weft_data']
        if len(weft) >= 2:
            positions = [d['y_center'] for d in weft]
            displacements = [d['displacement'] * strength for d in weft]

            # Add boundary points for extrapolation
            positions = [0.0] + positions + [float(h)]
            displacements = [displacements[0]] + displacements + [displacements[-1]]

            interp_fn = interp1d(positions, displacements, kind='cubic' if len(positions) >= 4 else 'linear',
                                 fill_value='extrapolate')
            for y in range(h):
                shift = float(interp_fn(y))
                map_x[y, :] -= shift

    if direction in ('both', 'warp') and bow_data.get('warp_data'):
        warp = bow_data['warp_data']
        if len(warp) >= 2:
            positions = [d['x_center'] for d in warp]
            displacements = [d['displacement'] * strength for d in warp]

            positions = [0.0] + positions + [float(w)]
            displacements = [displacements[0]] + displacements + [displacements[-1]]

            interp_fn = interp1d(positions, displacements, kind='cubic' if len(positions) >= 4 else 'linear',
                                 fill_value='extrapolate')
            for x in range(w):
                shift = float(interp_fn(x))
                map_y[:, x] -= shift

    result = cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    return result


def analyze(image_path: Path, grid_divisions: int = 20, direction: str = 'both') -> dict:
    """
    Analyze yarn alignment — detect global skew and local bow.

    Args:
        image_path: Path to image file
        grid_divisions: Number of strips for bow analysis
        direction: 'both', 'warp', or 'weft'

    Returns:
        dict with skew_angle_deg, max_weft_bow_px, max_warp_bow_px,
        bow_data, recommendation
    """
    img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return {"success": False, "error": "Failed to load image"}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    gray = _to_8bit(gray)

    # Global skew via FFT
    skew_angle = _detect_skew_fft(gray)

    # Local bow via strip Hough
    bow_data = _detect_bow_strips(gray, grid_divisions, direction)

    # Generate recommendation
    recommendations = []
    if abs(skew_angle) > 0.5:
        recommendations.append(f"Skew correction of {skew_angle:.1f} degrees recommended")
    if bow_data['max_weft_bow_px'] > 5:
        recommendations.append(f"Weft bow correction recommended ({bow_data['max_weft_bow_px']:.0f}px)")
    if bow_data['max_warp_bow_px'] > 5:
        recommendations.append(f"Warp bow correction recommended ({bow_data['max_warp_bow_px']:.0f}px)")

    if not recommendations:
        recommendation = "Image appears well-aligned, minimal correction needed"
    else:
        recommendation = "; ".join(recommendations)

    return {
        "success": True,
        "skew_angle_deg": round(skew_angle, 2),
        "max_weft_bow_px": bow_data['max_weft_bow_px'],
        "max_warp_bow_px": bow_data['max_warp_bow_px'],
        "bow_data": {
            "weft": bow_data['weft_data'],
            "warp": bow_data['warp_data'],
        },
        "recommendation": recommendation,
        "image_width": img.shape[1],
        "image_height": img.shape[0],
    }


def preview(
    batch_path: Path,
    mode: str = 'auto',
    strength: float = 1.0,
    direction: str = 'both',
    grid_divisions: int = 20,
    manual_skew_angle: Optional[float] = None,
) -> dict:
    """
    Apply straighten correction to top image, return preview.

    Args:
        batch_path: Path to batch folder
        mode: 'auto' (skew+bow), 'skew', or 'bow'
        strength: Correction strength 0-1
        direction: 'both', 'warp', or 'weft'
        grid_divisions: Number of strips for bow analysis
        manual_skew_angle: Override detected skew angle

    Returns:
        dict with success, before_url, after_url, analysis data
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

    # Analyze
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    gray = _to_8bit(gray)

    skew_angle = manual_skew_angle if manual_skew_angle is not None else _detect_skew_fft(gray)
    bow_data = _detect_bow_strips(gray, grid_divisions, direction)

    # Apply corrections
    result = img.copy()
    if mode in ('auto', 'skew'):
        result = _correct_skew(result, skew_angle, strength)
    if mode in ('auto', 'bow'):
        result = _correct_bow(result, bow_data, strength, direction)

    # Save previews
    batch_name = batch_path.name
    preview_dir = batch_path / "straighten_preview"
    preview_dir.mkdir(exist_ok=True)

    after_path = preview_dir / f"{top_image.stem}_straightened.jpg"
    _save_preview_jpg(result, after_path)

    before_path = preview_dir / f"{top_image.stem}_original.jpg"
    _save_preview_jpg(img, before_path)

    return {
        "success": True,
        "before_url": f"/media/captures/{batch_name}/straighten_preview/{top_image.stem}_original.jpg",
        "after_url": f"/media/captures/{batch_name}/straighten_preview/{top_image.stem}_straightened.jpg",
        "skew_angle_deg": round(skew_angle, 2),
        "max_weft_bow_px": bow_data['max_weft_bow_px'],
        "max_warp_bow_px": bow_data['max_warp_bow_px'],
        "mode": mode,
        "strength": strength,
        "width": result.shape[1],
        "height": result.shape[0],
        "batch_name": batch_name,
    }


def apply(
    batch_path: Path,
    mode: str = 'auto',
    strength: float = 1.0,
    direction: str = 'both',
    grid_divisions: int = 20,
    manual_skew_angle: Optional[float] = None,
) -> dict:
    """
    Apply straighten correction to all images, save to straightened/.

    Args:
        batch_path: Path to batch folder
        mode: 'auto' (skew+bow), 'skew', or 'bow'
        strength: Correction strength 0-1
        direction: 'both', 'warp', or 'weft'
        grid_divisions: Number of strips for bow analysis
        manual_skew_angle: Override detected skew angle

    Returns:
        dict with success, processed count, total count, output_folder
    """
    source_folder, source_type = _get_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found"}

    images = _list_images(source_folder)
    if not images:
        return {"success": False, "error": "No images found in source folder"}

    # Analyze using top image to get consistent correction params
    top_image = _find_top_image(images)
    ref_img = _load_image(top_image)
    if ref_img is None:
        return {"success": False, "error": "Failed to load reference image"}

    gray = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY) if len(ref_img.shape) == 3 else ref_img
    gray = _to_8bit(gray)

    skew_angle = manual_skew_angle if manual_skew_angle is not None else _detect_skew_fft(gray)
    bow_data = _detect_bow_strips(gray, grid_divisions, direction)

    output_folder = batch_path / "straightened"
    output_folder.mkdir(exist_ok=True)

    thumb_folder = batch_path / "straightened_thumbnail"
    thumb_folder.mkdir(exist_ok=True)

    processed = 0
    errors = []

    for image_path in images:
        try:
            img = _load_image(image_path)
            if img is None:
                errors.append(f"Failed to load {image_path.name}")
                continue

            result = img.copy()
            if mode in ('auto', 'skew'):
                result = _correct_skew(result, skew_angle, strength)
            if mode in ('auto', 'bow'):
                result = _correct_bow(result, bow_data, strength, direction)

            # Save as TIFF
            output_path = output_folder / f"{image_path.stem}.tiff"
            if result.dtype == np.uint16:
                img_rgb = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
                if not save_tiff(img_rgb, output_path, compression='zlib'):
                    cv2.imwrite(str(output_path), result)
            else:
                cv2.imwrite(str(output_path), result)

            # Save thumbnail
            thumb_path = thumb_folder / f"{image_path.stem}.jpg"
            _save_preview_jpg(result, thumb_path, max_size=800)

            processed += 1
            logger.info(f"Straightened: {image_path.name}")

        except Exception as e:
            logger.error(f"Error processing {image_path.name}: {e}")
            errors.append(f"{image_path.name}: {str(e)}")

    batch_name = batch_path.name
    return {
        "success": processed > 0,
        "processed": processed,
        "total": len(images),
        "errors": errors,
        "output_folder": "straightened",
        "skew_angle_deg": round(skew_angle, 2),
        "max_weft_bow_px": bow_data['max_weft_bow_px'],
        "max_warp_bow_px": bow_data['max_warp_bow_px'],
    }

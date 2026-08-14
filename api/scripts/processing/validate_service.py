"""
Validate Service - PBR map validation and analysis.
Reads from pbr_grayscale/ or pbr_colored/ (no output - analysis only).
Checks albedo value ranges, metallic ranges, generates heatmap overlays.
"""
import logging
from pathlib import Path
from typing import Optional, Dict, List

import cv2
import numpy as np

logger = logging.getLogger(__name__)

TIFF_EXTENSIONS = {'.tiff', '.tif'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'} | TIFF_EXTENSIONS

# PBR map names to look for
PBR_MAP_NAMES = {
    'albedo': ['albedo', 'diffuse', 'base_color', 'basecolor', 'color'],
    'normal': ['normal', 'norm', 'nrm'],
    'roughness': ['roughness', 'rough', 'gloss'],
    'height': ['height', 'displacement', 'disp', 'bump'],
    'metallic': ['metallic', 'metal', 'metalness'],
    'ao': ['ao', 'ambient_occlusion', 'occlusion'],
}


def _find_pbr_folder(batch_path: Path) -> Optional[Path]:
    """Find PBR output folder: pbr_grayscale > pbr_colored"""
    for folder_name in ['pbr_grayscale', 'pbr_colored']:
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            return folder
    return None


def _find_pbr_map(folder: Path, map_type: str) -> Optional[Path]:
    """Find a specific PBR map file by type."""
    keywords = PBR_MAP_NAMES.get(map_type, [map_type])
    for f in sorted(folder.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        name_lower = f.stem.lower()
        for kw in keywords:
            if kw in name_lower:
                return f
    return None


def _load_image(path: Path) -> Optional[np.ndarray]:
    """Load image preserving bit depth."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        logger.error(f"Failed to load: {path}")
    return img


def _to_8bit(img: np.ndarray) -> np.ndarray:
    """Convert to 8-bit if needed."""
    if img.dtype == np.uint16:
        return (img / 256).astype(np.uint8)
    return img


def _save_preview(img: np.ndarray, path: Path, max_size: int = 1200):
    """Save a JPG preview."""
    img = _to_8bit(img)
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        s = max_size / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])


def _compute_histogram(img: np.ndarray) -> Dict:
    """Compute histogram for image channels."""
    img8 = _to_8bit(img)
    result = {}

    if len(img8.shape) == 3 and img8.shape[2] >= 3:
        for i, ch in enumerate(['b', 'g', 'r']):
            hist = cv2.calcHist([img8], [i], None, [256], [0, 256])
            result[ch] = hist.flatten().tolist()
        gray = cv2.cvtColor(img8, cv2.COLOR_BGR2GRAY)
    else:
        gray = img8 if len(img8.shape) == 2 else img8[:, :, 0]

    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    result['luminance'] = hist.flatten().tolist()
    return result


def validate_albedo(
    batch_path: str,
    dark_threshold: int = 30,
) -> Dict:
    """
    Validate albedo map values.
    Flags pixels below dark_threshold as too dark for PBR.
    Returns heatmap overlay and statistics.
    """
    batch_path = Path(batch_path)
    pbr_folder = _find_pbr_folder(batch_path)
    if not pbr_folder:
        return {"success": False, "error": "No PBR maps found"}

    albedo_path = _find_pbr_map(pbr_folder, 'albedo')
    if not albedo_path:
        return {"success": False, "error": "No albedo map found"}

    img = _load_image(albedo_path)
    if img is None:
        return {"success": False, "error": "Failed to load albedo map"}

    img8 = _to_8bit(img)
    if len(img8.shape) == 3:
        gray = cv2.cvtColor(img8, cv2.COLOR_BGR2GRAY)
    else:
        gray = img8

    # Analyze
    total_pixels = gray.size
    dark_pixels = int(np.sum(gray < dark_threshold))
    bright_pixels = int(np.sum(gray > 240))
    mean_val = float(gray.mean())
    min_val = int(gray.min())
    max_val = int(gray.max())

    dark_pct = (dark_pixels / total_pixels) * 100
    bright_pct = (bright_pixels / total_pixels) * 100

    # Generate heatmap overlay (green=good, red=bad)
    heatmap = np.zeros((*gray.shape, 3), dtype=np.uint8)
    heatmap[gray >= dark_threshold] = [0, 180, 0]  # Green - OK
    heatmap[gray < dark_threshold] = [0, 0, 220]    # Red - too dark
    heatmap[gray > 240] = [0, 140, 255]             # Orange - too bright

    # Blend with original
    if len(img8.shape) == 3:
        blended = cv2.addWeighted(img8, 0.6, heatmap, 0.4, 0)
    else:
        img_bgr = cv2.cvtColor(img8, cv2.COLOR_GRAY2BGR)
        blended = cv2.addWeighted(img_bgr, 0.6, heatmap, 0.4, 0)

    # Save overlay
    preview_dir = batch_path / "validate_preview"
    preview_dir.mkdir(exist_ok=True)
    overlay_path = preview_dir / "albedo_overlay.jpg"
    _save_preview(blended, overlay_path)

    batch_name = batch_path.name
    passed = dark_pct < 5 and bright_pct < 5

    return {
        "success": True,
        "map_type": "albedo",
        "passed": passed,
        "overlay_url": f"/media/captures/{batch_name}/validate_preview/albedo_overlay.jpg",
        "stats": {
            "mean": round(mean_val, 1),
            "min": min_val,
            "max": max_val,
            "dark_pixels_pct": round(dark_pct, 2),
            "bright_pixels_pct": round(bright_pct, 2),
            "dark_threshold": dark_threshold,
        },
        "histogram": _compute_histogram(img),
    }


def validate_metallic(
    batch_path: str,
    metal_range: tuple = (180, 255),
) -> Dict:
    """
    Validate metallic map values.
    Metallic maps should be mostly black (non-metal) or white (metal).
    Values in between are suspicious.
    """
    batch_path = Path(batch_path)
    pbr_folder = _find_pbr_folder(batch_path)
    if not pbr_folder:
        return {"success": False, "error": "No PBR maps found"}

    metallic_path = _find_pbr_map(pbr_folder, 'metallic')
    if not metallic_path:
        return {"success": False, "error": "No metallic map found (this is OK for non-metallic materials)", "passed": True}

    img = _load_image(metallic_path)
    if img is None:
        return {"success": False, "error": "Failed to load metallic map"}

    img8 = _to_8bit(img)
    if len(img8.shape) == 3:
        gray = cv2.cvtColor(img8, cv2.COLOR_BGR2GRAY)
    else:
        gray = img8

    total_pixels = gray.size
    non_metal = int(np.sum(gray < 30))
    metal = int(np.sum(gray >= metal_range[0]))
    ambiguous = total_pixels - non_metal - metal
    ambiguous_pct = (ambiguous / total_pixels) * 100

    # Heatmap
    heatmap = np.zeros((*gray.shape, 3), dtype=np.uint8)
    heatmap[gray < 30] = [0, 180, 0]                          # Green - clear non-metal
    heatmap[gray >= metal_range[0]] = [0, 180, 0]             # Green - clear metal
    heatmap[(gray >= 30) & (gray < metal_range[0])] = [0, 0, 220]  # Red - ambiguous

    preview_dir = batch_path / "validate_preview"
    preview_dir.mkdir(exist_ok=True)
    overlay_path = preview_dir / "metallic_overlay.jpg"
    _save_preview(heatmap, overlay_path)

    batch_name = batch_path.name
    passed = ambiguous_pct < 10

    return {
        "success": True,
        "map_type": "metallic",
        "passed": passed,
        "overlay_url": f"/media/captures/{batch_name}/validate_preview/metallic_overlay.jpg",
        "stats": {
            "mean": round(float(gray.mean()), 1),
            "min": int(gray.min()),
            "max": int(gray.max()),
            "non_metal_pct": round((non_metal / total_pixels) * 100, 2),
            "metal_pct": round((metal / total_pixels) * 100, 2),
            "ambiguous_pct": round(ambiguous_pct, 2),
            "metal_range": list(metal_range),
        },
        "histogram": _compute_histogram(img),
    }


def get_stats(batch_path: str) -> Dict:
    """Return per-channel statistics and histograms for all PBR maps."""
    batch_path = Path(batch_path)
    pbr_folder = _find_pbr_folder(batch_path)
    if not pbr_folder:
        return {"success": False, "error": "No PBR maps found"}

    maps = {}
    batch_name = batch_path.name

    for map_type in ['albedo', 'normal', 'roughness', 'height', 'metallic', 'ao']:
        map_path = _find_pbr_map(pbr_folder, map_type)
        if not map_path:
            continue

        img = _load_image(map_path)
        if img is None:
            continue

        img8 = _to_8bit(img)

        # Save thumbnail for display
        preview_dir = batch_path / "validate_preview"
        preview_dir.mkdir(exist_ok=True)
        thumb_path = preview_dir / f"{map_type}.jpg"
        _save_preview(img, thumb_path, max_size=800)

        stats = {
            "filename": map_path.name,
            "thumbnail_url": f"/media/captures/{batch_name}/validate_preview/{map_type}.jpg",
            "histogram": _compute_histogram(img),
        }

        if len(img8.shape) == 3 and img8.shape[2] >= 3:
            for i, ch in enumerate(['b', 'g', 'r']):
                channel = img8[:, :, i]
                stats[f"{ch}_min"] = int(channel.min())
                stats[f"{ch}_max"] = int(channel.max())
                stats[f"{ch}_mean"] = round(float(channel.mean()), 1)
        else:
            gray = img8 if len(img8.shape) == 2 else img8[:, :, 0]
            stats["min"] = int(gray.min())
            stats["max"] = int(gray.max())
            stats["mean"] = round(float(gray.mean()), 1)

        maps[map_type] = stats

    return {
        "success": True,
        "maps": maps,
        "pbr_folder": pbr_folder.name,
    }


def generate_overlay(
    batch_path: str,
    mode: str = "albedo",
    threshold: int = 30,
) -> Dict:
    """Generate a red-green heatmap overlay image for the specified mode."""
    if mode == "albedo":
        return validate_albedo(batch_path, dark_threshold=threshold)
    elif mode == "metallic":
        return validate_metallic(batch_path, metal_range=(threshold, 255))
    else:
        return {"success": False, "error": f"Unknown mode: {mode}"}

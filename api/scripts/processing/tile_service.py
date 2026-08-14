"""
Tile Service - Generate tiled/repeated texture previews and exports.
Reads from seamless/ or color_calibrated/ or cropped/ or tiff/ (priority order).
Output: tiled/ subfolder.
"""
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

TIFF_EXTENSIONS = {'.tiff', '.tif'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg'} | TIFF_EXTENSIONS


def _find_source_folder(batch_path: Path) -> Optional[Path]:
    """Find best source folder: seamless > color_calibrated > cropped > tiff"""
    for folder_name in ['seamless', 'straightened', 'color_calibrated', 'cropped', 'tiff']:
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


def _find_top_image(images: List[Path]) -> Optional[Path]:
    """Find the TOP image from the list."""
    for img in images:
        name_lower = img.name.lower()
        if '_top' in name_lower or name_lower.startswith('top'):
            return img
    return images[0] if images else None


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


def generate_tiled_preview(
    image: np.ndarray,
    tile_x: int = 3,
    tile_y: int = 3,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
    overlap: float = 0.0,
    half_drop: bool = False,
    output_size: Tuple[int, int] = (1200, 1200),
) -> np.ndarray:
    """
    Generate a tiled output image from a single tile.
    """
    h, w = image.shape[:2]

    # Scale the tile
    tile_w = int(w * scale)
    tile_h = int(h * scale)
    if tile_w < 1 or tile_h < 1:
        return image

    scaled = cv2.resize(image, (tile_w, tile_h), interpolation=cv2.INTER_AREA)

    # Rotate tile if needed
    if abs(rotation) > 0.01:
        center = (tile_w // 2, tile_h // 2)
        M = cv2.getRotationMatrix2D(center, rotation, 1.0)
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        new_w = int(tile_h * sin + tile_w * cos)
        new_h = int(tile_h * cos + tile_w * sin)
        M[0, 2] += (new_w - tile_w) / 2
        M[1, 2] += (new_h - tile_h) / 2
        scaled = cv2.warpAffine(scaled, M, (new_w, new_h), borderMode=cv2.BORDER_WRAP)
        tile_w, tile_h = new_w, new_h

    out_w, out_h = output_size

    # Calculate step with overlap
    step_x = int(tile_w * (1 - overlap))
    step_y = int(tile_h * (1 - overlap))
    if step_x < 1:
        step_x = 1
    if step_y < 1:
        step_y = 1

    # Pixel offsets
    px_offset_x = int(offset_x * step_x)
    px_offset_y = int(offset_y * step_y)

    # Create output canvas
    channels = image.shape[2] if len(image.shape) == 3 else 1
    dtype = image.dtype
    if channels > 1:
        canvas = np.zeros((out_h, out_w, channels), dtype=dtype)
    else:
        canvas = np.zeros((out_h, out_w), dtype=dtype)

    # Place tiles
    for row in range(-1, tile_y + 2):
        for col in range(-1, tile_x + 2):
            x = col * step_x + px_offset_x
            y = row * step_y + px_offset_y

            if half_drop and row % 2 != 0:
                x += step_x // 2

            # Compute paste region
            src_x1 = max(0, -x)
            src_y1 = max(0, -y)
            dst_x1 = max(0, x)
            dst_y1 = max(0, y)
            paste_w = min(tile_w - src_x1, out_w - dst_x1)
            paste_h = min(tile_h - src_y1, out_h - dst_y1)

            if paste_w <= 0 or paste_h <= 0:
                continue

            canvas[dst_y1:dst_y1 + paste_h, dst_x1:dst_x1 + paste_w] = \
                scaled[src_y1:src_y1 + paste_h, src_x1:src_x1 + paste_w]

    return canvas


def preview(
    batch_path: str,
    tile_x: int = 3,
    tile_y: int = 3,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
    overlap: float = 0.0,
    half_drop: bool = False,
) -> Dict:
    """Generate tiled preview from the top image."""
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

    tiled = generate_tiled_preview(
        img,
        tile_x=tile_x,
        tile_y=tile_y,
        offset_x=offset_x,
        offset_y=offset_y,
        scale=scale,
        rotation=rotation,
        overlap=overlap,
        half_drop=half_drop,
    )

    # Save preview
    preview_dir = batch_path / "tiled_preview"
    preview_dir.mkdir(exist_ok=True)
    preview_path = preview_dir / "tiled.jpg"
    _save_preview(tiled, preview_path)

    batch_name = batch_path.name
    return {
        "success": True,
        "preview_url": f"/media/captures/{batch_name}/tiled_preview/tiled.jpg",
        "source_image": top_image.name,
        "tile_x": tile_x,
        "tile_y": tile_y,
    }


def apply(
    batch_path: str,
    tile_x: int = 3,
    tile_y: int = 3,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    scale: float = 1.0,
    rotation: float = 0.0,
    overlap: float = 0.0,
    half_drop: bool = False,
    output_resolution: Tuple[int, int] = (2048, 2048),
) -> Dict:
    """Export tiled texture to tiled/ subfolder."""
    batch_path = Path(batch_path)
    source_folder = _find_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found", "processed": 0, "total": 0}

    images = _list_images(source_folder)
    top_image = _find_top_image(images)
    if not top_image:
        return {"success": False, "error": "No images found", "processed": 0, "total": 0}

    img = _load_image(top_image)
    if img is None:
        return {"success": False, "error": f"Failed to load {top_image.name}", "processed": 0, "total": 0}

    tiled = generate_tiled_preview(
        img,
        tile_x=tile_x,
        tile_y=tile_y,
        offset_x=offset_x,
        offset_y=offset_y,
        scale=scale,
        rotation=rotation,
        overlap=overlap,
        half_drop=half_drop,
        output_size=output_resolution,
    )

    output_dir = batch_path / "tiled"
    output_dir.mkdir(exist_ok=True)

    out_path = output_dir / f"{top_image.stem}_tiled.tiff"
    cv2.imwrite(str(out_path), tiled)

    # Also save a thumbnail
    thumb_dir = batch_path / "tiled_thumbnail"
    thumb_dir.mkdir(exist_ok=True)
    thumb_path = thumb_dir / f"{top_image.stem}_tiled.jpg"
    _save_preview(tiled, thumb_path, max_size=800)

    logger.info(f"Tiled export: {out_path} ({output_resolution[0]}x{output_resolution[1]})")

    return {
        "success": True,
        "processed": 1,
        "total": 1,
        "output_path": str(out_path),
        "resolution": list(output_resolution),
    }

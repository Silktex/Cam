"""
Clone Service - Inpainting and clone stamp for cleaning material textures.
Remove lint, threads, dust with OpenCV inpaint or region cloning.
Reads from seamless/ or color_calibrated/ or cropped/ or tiff/.
Output: cleaned/ subfolder.
"""
import base64
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


def _find_top_image(images: List[Path]) -> Optional[Path]:
    """Find the TOP image from the list."""
    for img in images:
        name_lower = img.name.lower()
        if '_top' in name_lower or name_lower.startswith('top'):
            return img
    return images[0] if images else None


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
    """Save a JPG preview."""
    if img.dtype == np.uint16:
        img = (img / 256).astype(np.uint8)
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        s = max_size / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])


def _decode_mask(mask_data_b64: str, target_shape: Tuple[int, int]) -> Optional[np.ndarray]:
    """Decode base64 mask data (PNG data URL) to grayscale mask."""
    try:
        # Strip data URL prefix if present
        if ',' in mask_data_b64:
            mask_data_b64 = mask_data_b64.split(',', 1)[1]

        raw = base64.b64decode(mask_data_b64)
        arr = np.frombuffer(raw, dtype=np.uint8)
        mask_img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)

        if mask_img is None:
            return None

        h, w = target_shape
        if mask_img.shape[:2] != (h, w):
            mask_img = cv2.resize(mask_img, (w, h), interpolation=cv2.INTER_NEAREST)

        return mask_img
    except Exception as e:
        logger.error(f"Failed to decode mask: {e}")
        return None


def inpaint(
    image_path: str,
    mask_data_b64: str,
    method: str = 'telea',
    radius: int = 3,
) -> Optional[np.ndarray]:
    """
    Inpaint regions specified by the mask using OpenCV.
    method: 'telea' (fast marching) or 'navier-stokes' (Navier-Stokes)
    """
    img = _load_image(Path(image_path))
    if img is None:
        return None

    h, w = img.shape[:2]
    mask = _decode_mask(mask_data_b64, (h, w))
    if mask is None:
        return None

    # Convert 16-bit to 8-bit for inpainting (OpenCV limitation)
    is_16bit = img.dtype == np.uint16
    if is_16bit:
        img_work = (img / 256).astype(np.uint8)
    else:
        img_work = img

    flag = cv2.INPAINT_TELEA if method == 'telea' else cv2.INPAINT_NS
    result = cv2.inpaint(img_work, mask, radius, flag)

    if is_16bit:
        result = (result.astype(np.uint16) * 256)

    return result


def clone_stamp(
    image_path: str,
    source_pos: Dict,
    target_pos: Dict,
    radius: int = 25,
    fade: float = 0.8,
    blur_mask: float = 0.3,
    mirror: bool = False,
) -> Optional[np.ndarray]:
    """
    Copy a circular region from source to target with blending.
    """
    img = _load_image(Path(image_path))
    if img is None:
        return None

    h, w = img.shape[:2]
    sx, sy = int(source_pos['x']), int(source_pos['y'])
    tx, ty = int(target_pos['x']), int(target_pos['y'])

    # Create circular mask
    mask = np.zeros((h, w), dtype=np.float32)
    cv2.circle(mask, (tx, ty), radius, 1.0, -1)

    # Apply blur for soft edges
    if blur_mask > 0:
        blur_size = max(3, int(radius * blur_mask * 2) | 1)
        mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)

    mask = mask * fade

    # Extract source patch
    result = img.copy()

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue

            src_x = sx + (-dx if mirror else dx)
            src_y = sy + dy
            dst_x = tx + dx
            dst_y = ty + dy

            if not (0 <= src_x < w and 0 <= src_y < h):
                continue
            if not (0 <= dst_x < w and 0 <= dst_y < h):
                continue

            alpha = mask[dst_y, dst_x]
            if alpha < 0.001:
                continue

            if img.dtype == np.uint16:
                result[dst_y, dst_x] = (
                    img[src_y, src_x].astype(np.float32) * alpha +
                    result[dst_y, dst_x].astype(np.float32) * (1 - alpha)
                ).astype(np.uint16)
            else:
                result[dst_y, dst_x] = (
                    img[src_y, src_x].astype(np.float32) * alpha +
                    result[dst_y, dst_x].astype(np.float32) * (1 - alpha)
                ).astype(np.uint8)

    return result


def preview_inpaint(
    batch_path: str,
    mask_data_b64: str,
    method: str = 'telea',
    radius: int = 3,
) -> Dict:
    """Preview inpaint on top image."""
    batch_path = Path(batch_path)
    source_folder = _find_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found"}

    images = _list_images(source_folder)
    top_image = _find_top_image(images)
    if not top_image:
        return {"success": False, "error": "No images found"}

    result = inpaint(str(top_image), mask_data_b64, method, radius)
    if result is None:
        return {"success": False, "error": "Inpaint failed"}

    preview_dir = batch_path / "clone_preview"
    preview_dir.mkdir(exist_ok=True)
    preview_path = preview_dir / "inpaint_preview.jpg"
    _save_preview(result, preview_path)

    batch_name = batch_path.name
    return {
        "success": True,
        "preview_url": f"/media/captures/{batch_name}/clone_preview/inpaint_preview.jpg",
        "method": method,
    }


def preview_stamp(
    batch_path: str,
    source_pos: Dict,
    target_pos: Dict,
    radius: int = 25,
    fade: float = 0.8,
    blur_mask: float = 0.3,
    mirror: bool = False,
) -> Dict:
    """Preview clone stamp on top image."""
    batch_path = Path(batch_path)
    source_folder = _find_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found"}

    images = _list_images(source_folder)
    top_image = _find_top_image(images)
    if not top_image:
        return {"success": False, "error": "No images found"}

    result = clone_stamp(
        str(top_image), source_pos, target_pos,
        radius=radius, fade=fade, blur_mask=blur_mask, mirror=mirror,
    )
    if result is None:
        return {"success": False, "error": "Clone stamp failed"}

    preview_dir = batch_path / "clone_preview"
    preview_dir.mkdir(exist_ok=True)
    preview_path = preview_dir / "stamp_preview.jpg"
    _save_preview(result, preview_path)

    batch_name = batch_path.name
    return {
        "success": True,
        "preview_url": f"/media/captures/{batch_name}/clone_preview/stamp_preview.jpg",
    }


def apply(
    batch_path: str,
    operations: List[Dict],
) -> Dict:
    """
    Apply a list of operations to the top image and save to cleaned/.
    Each operation is either {type: 'inpaint', mask_data, method, radius}
    or {type: 'stamp', source_pos, target_pos, radius, fade, blur_mask, mirror}.
    """
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
        return {"success": False, "error": "Failed to load image", "processed": 0, "total": 0}

    # Apply operations sequentially
    current = img.copy()
    applied = 0

    for op in operations:
        op_type = op.get('type', 'inpaint')

        if op_type == 'inpaint':
            mask_data = op.get('mask_data', '')
            method = op.get('method', 'telea')
            radius = op.get('radius', 3)

            h, w = current.shape[:2]
            mask = _decode_mask(mask_data, (h, w))
            if mask is None:
                continue

            is_16bit = current.dtype == np.uint16
            if is_16bit:
                work = (current / 256).astype(np.uint8)
            else:
                work = current

            flag = cv2.INPAINT_TELEA if method == 'telea' else cv2.INPAINT_NS
            result = cv2.inpaint(work, mask, radius, flag)

            if is_16bit:
                current = (result.astype(np.uint16) * 256)
            else:
                current = result
            applied += 1

        elif op_type == 'stamp':
            source_pos = op.get('source_pos', {})
            target_pos = op.get('target_pos', {})
            radius = op.get('radius', 25)
            fade = op.get('fade', 0.8)
            blur = op.get('blur_mask', 0.3)
            mirror = op.get('mirror', False)

            # Write current to temp, use clone_stamp
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix='.tiff', delete=False)
            cv2.imwrite(tmp.name, current)
            result = clone_stamp(tmp.name, source_pos, target_pos, radius, fade, blur, mirror)
            Path(tmp.name).unlink(missing_ok=True)

            if result is not None:
                current = result
                applied += 1

    # Save to cleaned/
    output_dir = batch_path / "cleaned"
    output_dir.mkdir(exist_ok=True)

    out_path = output_dir / f"{top_image.stem}.tiff"
    cv2.imwrite(str(out_path), current)

    thumb_dir = batch_path / "cleaned_thumbnail"
    thumb_dir.mkdir(exist_ok=True)
    thumb_path = thumb_dir / f"{top_image.stem}.jpg"
    _save_preview(current, thumb_path, max_size=800)

    logger.info(f"Cleaned: {out_path} ({applied} operations applied)")

    return {
        "success": True,
        "processed": 1,
        "total": 1,
        "operations_applied": applied,
        "output_path": str(out_path),
    }

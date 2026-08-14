"""
Equalize Service - Histogram equalization and exposure matching for material textures.
Ensures consistent brightness/contrast across all images in a batch.

Methods:
- CLAHE: Adaptive local histogram equalization in LAB color space
- Histogram Match: Match histogram to a reference image
- Exposure Match: Normalize mean brightness to a reference
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
    """Find best source folder: color_calibrated > cropped > tiff"""
    for folder_name in ['color_calibrated', 'cropped', 'tiff']:
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


def _compute_histogram(img: np.ndarray) -> Dict:
    """Compute RGB histogram with 256 bins."""
    result = {}
    if img.dtype == np.uint16:
        img8 = (img / 256).astype(np.uint8)
    else:
        img8 = img

    for i, ch in enumerate(['b', 'g', 'r']):
        hist = cv2.calcHist([img8], [i], None, [256], [0, 256])
        result[ch] = hist.flatten().tolist()

    # Luminance
    gray = cv2.cvtColor(img8, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    result['luminance'] = hist.flatten().tolist()
    return result


def equalize_clahe(image: np.ndarray, clip_limit: float = 2.0) -> np.ndarray:
    """
    CLAHE equalization in LAB color space.
    Only equalizes the L channel, preserving color information.
    """
    is_16bit = image.dtype == np.uint16

    if is_16bit:
        img8 = (image / 256).astype(np.uint8)
    else:
        img8 = image.copy()

    lab = cv2.cvtColor(img8, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    l_eq = clahe.apply(l)

    lab_eq = cv2.merge([l_eq, a, b])
    result = cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)

    if is_16bit:
        result = (result.astype(np.uint16) * 256)

    return result


def equalize_histogram_match(image: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """
    Match the histogram of image to reference image, channel by channel.
    """
    is_16bit = image.dtype == np.uint16

    if is_16bit:
        src = (image / 256).astype(np.uint8)
        ref = (reference / 256).astype(np.uint8) if reference.dtype == np.uint16 else reference
    else:
        src = image.copy()
        ref = reference.copy()

    result = np.zeros_like(src)

    for i in range(3):
        src_hist, _ = np.histogram(src[:, :, i].flatten(), 256, [0, 256])
        ref_hist, _ = np.histogram(ref[:, :, i].flatten(), 256, [0, 256])

        src_cdf = src_hist.cumsum()
        ref_cdf = ref_hist.cumsum()

        src_cdf = (src_cdf - src_cdf.min()) * 255 / (src_cdf.max() - src_cdf.min() + 1e-6)
        ref_cdf = (ref_cdf - ref_cdf.min()) * 255 / (ref_cdf.max() - ref_cdf.min() + 1e-6)

        # Build lookup table
        lut = np.zeros(256, dtype=np.uint8)
        for s_val in range(256):
            diff = np.abs(ref_cdf - src_cdf[s_val])
            lut[s_val] = np.argmin(diff)

        result[:, :, i] = lut[src[:, :, i]]

    if is_16bit:
        result = (result.astype(np.uint16) * 256)

    return result


def equalize_exposure_match(image: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """
    Normalize mean brightness of image to match the reference.
    Works in LAB space on the L channel only.
    """
    is_16bit = image.dtype == np.uint16

    if is_16bit:
        src = (image / 256).astype(np.uint8)
        ref = (reference / 256).astype(np.uint8) if reference.dtype == np.uint16 else reference
    else:
        src = image.copy()
        ref = reference.copy()

    src_lab = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref_lab = cv2.cvtColor(ref, cv2.COLOR_BGR2LAB).astype(np.float32)

    src_mean = src_lab[:, :, 0].mean()
    ref_mean = ref_lab[:, :, 0].mean()

    if src_mean > 0:
        scale = ref_mean / src_mean
        src_lab[:, :, 0] = np.clip(src_lab[:, :, 0] * scale, 0, 255)

    result = cv2.cvtColor(src_lab.astype(np.uint8), cv2.COLOR_LAB2BGR)

    if is_16bit:
        result = (result.astype(np.uint16) * 256)

    return result


def _find_top_image(images: List[Path]) -> Optional[Path]:
    """Find the TOP image from the list."""
    for img in images:
        name_lower = img.name.lower()
        if '_top' in name_lower or name_lower.startswith('top'):
            return img
    return images[0] if images else None


def preview(
    batch_path: str,
    method: str = 'clahe',
    reference_image: Optional[str] = None,
    clip_limit: float = 2.0,
) -> Dict:
    """
    Process the top image and return a preview.
    Returns paths to before/after preview images and histogram data.
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

    # Apply equalization
    reference = None
    if method in ('histogram_match', 'exposure_match') and reference_image:
        ref_path = source_folder / reference_image
        if not ref_path.exists():
            return {"success": False, "error": f"Reference image not found: {reference_image}"}
        reference = _load_image(ref_path)
        if reference is None:
            return {"success": False, "error": f"Failed to load reference: {reference_image}"}

    if method == 'clahe':
        result = equalize_clahe(img, clip_limit=clip_limit)
    elif method == 'histogram_match':
        if reference is None:
            return {"success": False, "error": "Reference image required for histogram match"}
        result = equalize_histogram_match(img, reference)
    elif method == 'exposure_match':
        if reference is None:
            return {"success": False, "error": "Reference image required for exposure match"}
        result = equalize_exposure_match(img, reference)
    else:
        return {"success": False, "error": f"Unknown method: {method}"}

    # Save preview images
    preview_dir = batch_path / "equalized_preview"
    preview_dir.mkdir(exist_ok=True)

    before_path = preview_dir / "before.jpg"
    after_path = preview_dir / "after.jpg"
    _save_preview(img, before_path)
    _save_preview(result, after_path)

    # Compute histograms
    before_hist = _compute_histogram(img)
    after_hist = _compute_histogram(result)

    batch_name = batch_path.name

    return {
        "success": True,
        "before_url": f"/media/captures/{batch_name}/equalized_preview/before.jpg",
        "after_url": f"/media/captures/{batch_name}/equalized_preview/after.jpg",
        "before_histogram": before_hist,
        "after_histogram": after_hist,
        "method": method,
        "source_image": top_image.name,
        "image_count": len(images),
        "images": [img.name for img in images],
    }


def apply(
    batch_path: str,
    method: str = 'clahe',
    reference_image: Optional[str] = None,
    clip_limit: float = 2.0,
) -> Dict:
    """
    Apply equalization to all images in the batch.
    Saves results to equalized/ subfolder.
    """
    batch_path = Path(batch_path)
    source_folder = _find_source_folder(batch_path)
    if not source_folder:
        return {"success": False, "error": "No source images found", "processed": 0, "total": 0}

    images = _list_images(source_folder)
    if not images:
        return {"success": False, "error": "No images found", "processed": 0, "total": 0}

    # Load reference if needed
    reference = None
    if method in ('histogram_match', 'exposure_match') and reference_image:
        ref_path = source_folder / reference_image
        if ref_path.exists():
            reference = _load_image(ref_path)

    output_dir = batch_path / "equalized"
    output_dir.mkdir(exist_ok=True)

    thumb_dir = batch_path / "equalized_thumbnail"
    thumb_dir.mkdir(exist_ok=True)

    processed = 0
    errors = []

    for image_path in images:
        try:
            img = _load_image(image_path)
            if img is None:
                errors.append({"file": image_path.name, "error": "Failed to load"})
                continue

            if method == 'clahe':
                result = equalize_clahe(img, clip_limit=clip_limit)
            elif method == 'histogram_match' and reference is not None:
                result = equalize_histogram_match(img, reference)
            elif method == 'exposure_match' and reference is not None:
                result = equalize_exposure_match(img, reference)
            else:
                # Fallback to CLAHE if reference missing
                result = equalize_clahe(img, clip_limit=clip_limit)

            # Save as TIFF
            out_path = output_dir / f"{image_path.stem}.tiff"
            cv2.imwrite(str(out_path), result)

            # Save thumbnail
            thumb_path = thumb_dir / f"{image_path.stem}.jpg"
            _save_preview(result, thumb_path, max_size=800)

            processed += 1
            logger.info(f"Equalized: {image_path.name} -> {out_path.name}")

        except Exception as e:
            logger.error(f"Error equalizing {image_path.name}: {e}")
            errors.append({"file": image_path.name, "error": str(e)})

    return {
        "success": processed > 0,
        "processed": processed,
        "total": len(images),
        "method": method,
        "output_dir": str(output_dir),
        "errors": errors,
    }

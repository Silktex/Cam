"""
Pipeline Renderer - In-memory pipeline chaining for previews and full save.

Orchestrates existing services (crop, calibration, exposure, PBR, etc.)
to render previews in-memory (top image only) and save full pipeline output
(all images) to disk.

Non-destructive: no intermediate files persisted. Only final output saved on /save.
"""
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {'.tiff', '.tif', '.png', '.jpg', '.jpeg'}
RAW_EXTENSIONS = {'.arw', '.cr2', '.nef', '.dng', '.raf', '.orf', '.rw2', '.pef', '.srw'}


def _list_images(folder: Path) -> List[Path]:
    """List all images in a folder, sorted."""
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(folder.glob(f"*{ext}"))
        images.extend(folder.glob(f"*{ext.upper()}"))
    return sorted(images)


def _list_raw_files(folder: Path) -> List[Path]:
    """List all RAW files in a folder, sorted."""
    images = []
    for ext in RAW_EXTENSIONS:
        images.extend(folder.glob(f"*{ext}"))
        images.extend(folder.glob(f"*{ext.upper()}"))
    return sorted(images)


def _find_top_image(images: List[Path]) -> Optional[Path]:
    """Find the TOP image."""
    for img in images:
        name = img.name.lower()
        if '_top' in name or name.startswith('top'):
            return img
    return images[0] if images else None


def _find_source_folder(batch_path: Path) -> Optional[Path]:
    """Find the best available source folder for a batch. Prefer raw/ for highest quality."""
    for name in ['raw', 'tiff']:
        folder = batch_path / name
        if folder.exists() and any(folder.iterdir()):
            return folder
    return None


def _load_image(path: Path, fixed_wb: Optional[list] = None, half_size: bool = False) -> Optional[np.ndarray]:
    """Load image preserving bit depth. Always returns BGR (consistent with cv2.imread).
    Handles RAW via raw_utils with optional fixed WB.
    half_size=True uses half-resolution demosaic for faster previews."""
    if path.suffix.lower() in RAW_EXTENSIONS:
        if fixed_wb:
            from scripts.processing.raw_utils import load_raw_with_fixed_wb
            rgb = load_raw_with_fixed_wb(path, fixed_wb, half_size=half_size)
        else:
            from scripts.processing.raw_utils import load_raw
            rgb = load_raw(path, half_size=half_size)
        if rgb is not None:
            # raw_utils returns RGB; convert to BGR to match cv2.imread convention
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return None

    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        logger.error(f"Failed to load: {path}")
    return img


# ── Preview image cache ──
# Caches loaded+downscaled images to skip RAW decode on repeated preview requests
# (e.g. exposure slider adjustments). Max 4 entries (~36MB at 2400px uint16).
_preview_cache: dict = {}
_CACHE_MAX = 4


def _load_image_cached(path: Path, fixed_wb: Optional[list] = None, half_size: bool = False, max_size: int = 2400) -> Optional[np.ndarray]:
    """Load image with caching — returns a copy of the cached downscaled image."""
    key = (str(path), str(fixed_wb), half_size, max_size)
    if key in _preview_cache:
        return _preview_cache[key].copy()
    img = _load_image(path, fixed_wb=fixed_wb, half_size=half_size)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        s = max_size / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    if len(_preview_cache) >= _CACHE_MAX:
        del _preview_cache[next(iter(_preview_cache))]
    _preview_cache[key] = img.copy()
    return img


def _linear_to_srgb(img: np.ndarray) -> np.ndarray:
    """Convert linear RGB float32 to sRGB float32 (matching calibrate_and_crop.py)."""
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055,
    ).clip(0, 1)


def _sharpen_16(bgr_16: np.ndarray) -> np.ndarray:
    """Two-pass unsharp mask on 16-bit BGR (matching calibrate_and_crop.py)."""
    img = bgr_16.astype(np.float32)
    blur1 = cv2.GaussianBlur(img, (0, 0), sigmaX=0.8)
    img = img + 0.7 * (img - blur1)
    blur2 = cv2.GaussianBlur(img, (0, 0), sigmaX=2.0)
    img = img + 0.3 * (img - blur2)
    return np.clip(img, 0, 65535).astype(np.uint16)


def _save_preview_jpg(img: np.ndarray, path: Path, max_size: int = 2400):
    """Save a JPEG preview, converting to 8-bit if needed."""
    if img.dtype == np.uint16:
        img = (img >> 8).astype(np.uint8)
    elif img.dtype in (np.float32, np.float64):
        img = np.clip(img * 255, 0, 255).astype(np.uint8)
    h, w = img.shape[:2]
    if max(h, w) > max_size:
        s = max_size / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])


# ── Phase processors (in-memory) ──

def _apply_crop_inmemory(img: np.ndarray, params: dict) -> np.ndarray:
    """Apply crop/rotate/perspective in-memory."""
    crop_type = params.get("crop_type")
    if crop_type is None:
        return img

    rotation = params.get("rotation", 0)
    points = params.get("points")

    # When 4-point perspective crop is used, the frontend inverse-rotates
    # the points before saving — rotation is baked into the point positions.
    # Only apply image rotation for non-perspective (bbox) crops.
    if abs(rotation) > 0.01 and not (points and len(points) == 4):
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), -rotation, 1.0)
        cos_a = abs(M[0, 0])
        sin_a = abs(M[0, 1])
        new_w = int(h * sin_a + w * cos_a)
        new_h = int(h * cos_a + w * sin_a)
        M[0, 2] += (new_w - w) / 2
        M[1, 2] += (new_h - h) / 2
        img = cv2.warpAffine(img, M, (new_w, new_h), borderMode=cv2.BORDER_REFLECT)

    # Apply perspective / bbox crop
    if points and len(points) == 4:
        src_pts = np.array(
            [[p["x"], p["y"]] for p in points], dtype=np.float32
        )
        # Compute output size from points
        w = int(max(
            np.linalg.norm(src_pts[1] - src_pts[0]),
            np.linalg.norm(src_pts[2] - src_pts[3]),
        ))
        h = int(max(
            np.linalg.norm(src_pts[3] - src_pts[0]),
            np.linalg.norm(src_pts[2] - src_pts[1]),
        ))
        dst_pts = np.array(
            [[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32
        )
        M = cv2.getPerspectiveTransform(src_pts, dst_pts)
        img = cv2.warpPerspective(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)

    return img


def _apply_calibration_inmemory(img: np.ndarray, params: dict, skip_sharpen: bool = False) -> np.ndarray:
    """
    Apply color calibration in-memory.

    Matches the quality pipeline from calibrate_and_crop.py:
    1. If input is from RAW loaded with fixed_wb → already linear RGB uint16
    2. Apply 3x3 color correction matrix in linear space
    3. Apply linear→sRGB gamma transfer
    4. Two-pass unsharp mask (skipped when skip_sharpen=True, e.g. for previews)
    """
    matrix = params.get("matrix_3x3")
    if matrix is None:
        return img

    matrix = np.array(matrix, dtype=np.float64)

    # Convert to linear float32 RGB for matrix math
    # _load_image always returns BGR (cv2.imread convention)
    is_bgr = True
    if img.dtype == np.uint16:
        img_f = img.astype(np.float32) / 65535.0
    elif img.dtype == np.uint8:
        img_f = img.astype(np.float32) / 255.0
    else:
        img_f = img.astype(np.float32)

    # Convert BGR→RGB for matrix (matrix operates in RGB space)
    if is_bgr and len(img_f.shape) == 3 and img_f.shape[2] == 3:
        img_rgb = img_f[:, :, ::-1]
    else:
        img_rgb = img_f

    # Apply 3x3 color correction in linear space
    h, w = img_rgb.shape[:2]
    flat = img_rgb.reshape(-1, 3)
    corrected = (matrix @ flat.T).T.reshape(h, w, 3)
    corrected = np.clip(corrected, 0, 1)

    # Linear → sRGB gamma
    srgb = _linear_to_srgb(corrected)

    # Convert to 16-bit BGR for output
    srgb_16 = (srgb * 65535).astype(np.uint16)
    bgr_16 = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)

    # Two-pass unsharp mask (imperceptible at preview resolution, saves ~50ms)
    if not skip_sharpen:
        bgr_16 = _sharpen_16(bgr_16)

    return bgr_16


def _apply_exposure_inmemory(img: np.ndarray, params: dict) -> np.ndarray:
    """Apply exposure offset in-memory."""
    from scripts.processing.exposure_service import apply_exposure_inmemory

    offset = params.get("exposure_offset", 0.0)

    # Only apply if there's a meaningful offset
    if abs(offset) < 0.001:
        return img

    return apply_exposure_inmemory(img, offset=offset, method="offset")


# ── Preview helpers ──


def _scale_crop_params(params: dict, scale: float) -> dict:
    """Scale crop parameters to match a resized preview image."""
    if scale == 1.0:
        return params
    scaled = dict(params)
    points = params.get("points")
    if points and len(points) == 4:
        scaled["points"] = [{"x": p["x"] * scale, "y": p["y"] * scale} for p in points]
    return scaled


# ── Main render functions ──


def render_preview(
    batch_path: Path,
    phase: str,
    track: dict,
    preview_max_size: int = 2400,
) -> Dict:
    """
    Chain RAW -> crop -> calibrate -> exposure -> ... -> requested phase
    for the top image only. Returns JPEG preview URL.

    No intermediate files created (except the preview JPEG itself).
    """
    from scripts.processing.process_track_service import PHASES, get_phase_index

    batch_path = Path(batch_path)
    phase_idx = get_phase_index(phase)
    phases = track["phases"]

    # Find source folder (prefer raw/ for highest quality)
    source = _find_source_folder(batch_path)
    if not source:
        return {"success": False, "error": "No source images found (need tiff/ or raw/ folder)"}

    # List images — handle both RAW and processed formats
    is_raw_source = source.name == 'raw'
    if is_raw_source:
        images = _list_raw_files(source)
    else:
        images = _list_images(source)
    top_path = _find_top_image(images)
    if not top_path:
        return {"success": False, "error": "No images found in batch"}

    # Extract checker_wb from color params for RAW re-demosaic
    color_params = phases["color"]["params"]
    checker_wb = color_params.get("checker_wb") if is_raw_source else None

    # Load top image with half_size demosaic for speed
    img = _load_image(top_path, fixed_wb=checker_wb, half_size=True)
    if img is None:
        return {"success": False, "error": f"Failed to load {top_path.name}"}

    # Downscale to preview resolution BEFORE any processing
    h, w = img.shape[:2]
    scale_factor = 1.0
    if max(h, w) > preview_max_size:
        scale_factor = preview_max_size / max(h, w)
        img = cv2.resize(img, (int(w * scale_factor), int(h * scale_factor)),
                         interpolation=cv2.INTER_AREA)

    # Crop points are in full-resolution coordinates — adjust for half_size + downscale.
    # half_size gives ~0.5x per axis; combined with the downscale above gives total scale.
    # Get full-res dimensions to compute accurate total scale.
    if is_raw_source and top_path.suffix.lower() in RAW_EXTENSIONS:
        try:
            import rawpy as _rp
            with _rp.imread(str(top_path)) as _raw:
                orig_h, orig_w = _raw.sizes.height, _raw.sizes.width
            ph, pw = img.shape[:2]
            scale_factor = pw / orig_w  # use width ratio as uniform scale
        except Exception:
            pass  # fall back to scale_factor already computed from half_size dims

    # Track whether image is still in linear light (RAW sources are linear)
    is_linear = is_raw_source

    # Chain phases in order up to the requested phase
    # Phase 0: crop_align — scale crop points to match preview resolution
    if phase_idx >= 0:
        crop_params = _scale_crop_params(phases["crop_align"]["params"], scale_factor)
        img = _apply_crop_inmemory(img, crop_params)

    # Phase 1: color (calibration + exposure) — skip sharpening for preview
    if phase_idx >= 1:
        img = _apply_calibration_inmemory(img, color_params, skip_sharpen=True)
        if color_params.get("matrix_3x3") is not None:
            is_linear = False  # calibration applied sRGB gamma
        img = _apply_exposure_inmemory(img, color_params)

    # If image is still linear (RAW without calibration), apply sRGB gamma for display
    if is_linear and img.dtype == np.uint16:
        img_f = img.astype(np.float32) / 65535.0
        img_rgb = img_f[:, :, ::-1]  # BGR→RGB
        srgb = _linear_to_srgb(img_rgb)
        srgb_16 = (srgb * 65535).astype(np.uint16)
        img = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)

    # Phases 2+ operate on PBR maps (albedo). Load PBR output if available.
    if phase_idx >= 2:
        pbr_mode = phases["pbr"]["params"].get("mode", "grayscale")
        folder_name = "pbr_colored" if pbr_mode == "color" else "pbr_grayscale"
        albedo_path = batch_path / folder_name / "albedo.png"
        if albedo_path.exists():
            pbr_img = cv2.imread(str(albedo_path), cv2.IMREAD_UNCHANGED)
            if pbr_img is not None:
                img = pbr_img

    # Phase 3: Map Refinement — apply flatten & delight in-memory on albedo
    if phase_idx >= 3:
        refine_params = phases["map_refine"]["params"]
        pbr_mode = phases["pbr"]["params"].get("mode", "grayscale")

        # Flatten (requires normals)
        if refine_params.get("flatten", {}).get("enabled", False):
            from scripts.processing.flatten_service import flatten_image, _load_normals, _find_pbr_normals
            normals_path = _find_pbr_normals(batch_path, pbr_mode)
            if normals_path:
                normals = _load_normals(normals_path)
                if normals is not None:
                    flat_params = refine_params["flatten"]
                    img = flatten_image(
                        img, normals,
                        strength=flat_params.get("strength", 1.0),
                        smoothing_radius=flat_params.get("smoothing", 0),
                    )

        # Delight (operates on flattened result)
        if refine_params.get("delight", {}).get("enabled", False):
            dl_params = refine_params["delight"]
            method = dl_params.get("method", "gaussian")
            if method == "frequency_separation":
                from scripts.processing.delight_service import delight_frequency_separation
                img = delight_frequency_separation(
                    img,
                    blur_radius=dl_params.get("blur_radius", 200),
                    strength=dl_params.get("strength", 1.0),
                )
            else:
                from scripts.processing.delight_service import delight_gaussian
                img = delight_gaussian(
                    img,
                    blur_radius=dl_params.get("blur_radius", 200),
                    strength=dl_params.get("strength", 1.0),
                )

    # Phase 4: Seamless — apply seamless in-memory on albedo
    if phase_idx >= 4:
        s_params = phases["seamless_tiling"]["params"].get("seamless", {})
        method = s_params.get("method", "overlay")
        blend_width = s_params.get("blend_width", 64)
        from scripts.processing import seamless_service
        if method == "mirror":
            img = seamless_service.make_seamless_mirror(img, blend_width)
        elif method == "poisson":
            img = seamless_service.make_seamless_poisson(img, blend_width)
        else:
            img = seamless_service.make_seamless_overlay(
                img, blend_width,
                spots_removal=s_params.get("spots_removal", False),
                color_equalizer=s_params.get("color_equalizer", 0),
            )

    # Save preview JPEG
    preview_dir = batch_path / "pipeline_preview"
    preview_dir.mkdir(exist_ok=True)
    preview_path = preview_dir / f"{phase}.jpg"
    _save_preview_jpg(img, preview_path)

    batch_name = batch_path.name
    return {
        "success": True,
        "preview_url": f"/media/captures/{batch_name}/pipeline_preview/{phase}.jpg",
        "phase": phase,
        "source_image": top_path.name,
    }


def render_and_save(
    batch_path: Path,
    track: dict,
    save_through_phase: str = "validate_export",
) -> Dict:
    """
    Run full pipeline from source for ALL images through the specified phase.
    Saves final output to disk (TIFF/PNG). Returns saved file paths.
    """
    from scripts.processing.process_track_service import PHASES, get_phase_index

    batch_path = Path(batch_path)
    phase_idx = get_phase_index(save_through_phase)
    phases = track["phases"]

    source = _find_source_folder(batch_path)
    if not source:
        return {"success": False, "error": "No source images found"}

    is_raw_source = source.name == 'raw'
    if is_raw_source:
        all_images = _list_raw_files(source)
    else:
        all_images = _list_images(source)
    if not all_images:
        return {"success": False, "error": "No images found in batch"}

    # Extract checker_wb for RAW re-demosaic
    color_params = phases["color"]["params"]
    checker_wb = color_params.get("checker_wb") if is_raw_source else None

    saved_files = []
    errors = []

    # Phase 0: Crop & Align - save cropped images
    if phase_idx >= 0 and phases["crop_align"]["status"] in ("completed", "in_progress"):
        crop_params = phases["crop_align"]["params"]
        output_dir = batch_path / "cropped"
        output_dir.mkdir(exist_ok=True)

        for img_path in all_images:
            try:
                img = _load_image(img_path, fixed_wb=checker_wb)
                if img is None:
                    errors.append({"file": img_path.name, "error": "Failed to load"})
                    continue

                result = _apply_crop_inmemory(img, crop_params)
                out_path = output_dir / f"{img_path.stem}.tiff"
                cv2.imwrite(str(out_path), result)
                saved_files.append(str(out_path))
            except Exception as e:
                errors.append({"file": img_path.name, "error": str(e)})

    # Phase 1: Color - save calibrated images
    if phase_idx >= 1 and phases["color"]["status"] in ("completed", "in_progress"):
        # Use cropped images if available, otherwise re-load from source with checker_wb
        crop_dir = batch_path / "cropped"
        if crop_dir.exists() and any(crop_dir.iterdir()):
            src = crop_dir
            src_images = _list_images(src)
            load_wb = None  # Cropped images already have WB baked in
        else:
            src = source
            src_images = all_images
            load_wb = checker_wb

        output_dir = batch_path / "color_calibrated"
        output_dir.mkdir(exist_ok=True)

        for img_path in src_images:
            try:
                img = _load_image(img_path, fixed_wb=load_wb)
                if img is None:
                    continue
                result = _apply_calibration_inmemory(img, color_params)
                result = _apply_exposure_inmemory(result, color_params)
                out_path = output_dir / f"{img_path.stem}.tiff"
                cv2.imwrite(str(out_path), result)
                saved_files.append(str(out_path))
            except Exception as e:
                errors.append({"file": img_path.name, "error": str(e)})

    # Phase 2: PBR - invoke pbr_service
    if phase_idx >= 2 and phases["pbr"]["status"] in ("completed", "in_progress"):
        try:
            from scripts.processing.pbr_service import PBRService, PBRMode
            pbr = PBRService()
            mode_str = phases["pbr"]["params"].get("mode", "grayscale")
            mode = PBRMode(mode_str) if mode_str != "both" else PBRMode.BOTH
            # Use color_calibrated if we just saved it, otherwise let PBR auto-detect
            pbr_source = None
            cal_dir = batch_path / "color_calibrated"
            if cal_dir.exists() and any(cal_dir.iterdir()):
                pbr_source = str(cal_dir)
            results = pbr.generate(str(batch_path), mode=mode, source_folder=pbr_source)
            for r in results:
                if r.success:
                    for attr in ('albedo_path', 'normals_path', 'roughness_path', 'height_map_path'):
                        p = getattr(r, attr)
                        if p:
                            saved_files.append(p)
                else:
                    errors.append({"phase": "pbr", "error": r.error})
        except Exception as e:
            errors.append({"phase": "pbr", "error": str(e)})

    # Phase 3: Map Refinement
    if phase_idx >= 3 and phases["map_refine"]["status"] in ("completed", "in_progress"):
        refine_params = phases["map_refine"]["params"]

        # Flatten
        if refine_params.get("flatten", {}).get("enabled", False):
            try:
                from scripts.processing import flatten_service
                flatten_params = refine_params["flatten"]
                pbr_mode = phases["pbr"]["params"].get("mode", "grayscale")
                result = flatten_service.apply(
                    str(batch_path),
                    strength=flatten_params.get("strength", 1.0),
                    smoothing_radius=flatten_params.get("smoothing", 0),
                    pbr_mode=pbr_mode,
                )
                if result.get("success"):
                    saved_files.append(result.get("output_dir", ""))
            except Exception as e:
                errors.append({"phase": "map_refine/flatten", "error": str(e)})

        # Delight
        if refine_params.get("delight", {}).get("enabled", False):
            try:
                from scripts.processing import delight_service
                delight_params = refine_params["delight"]
                result = delight_service.apply(
                    str(batch_path),
                    blur_radius=delight_params.get("blur_radius", 200),
                    strength=delight_params.get("strength", 1.0),
                    method=delight_params.get("method", "gaussian"),
                )
                if result.get("success"):
                    saved_files.append(result.get("output_dir", ""))
            except Exception as e:
                errors.append({"phase": "map_refine/delight", "error": str(e)})

        # Roughness scale — write to map_refine/ to preserve original PBR output
        roughness_scale = refine_params.get("roughness", {}).get("scale_factor", 1.0)
        if abs(roughness_scale - 1.0) > 0.01:
            try:
                from scripts.processing.exposure_service import apply_roughness_scale_inmemory
                pbr_mode = phases["pbr"]["params"].get("mode", "grayscale")
                folder_name = "pbr_colored" if pbr_mode == "color" else "pbr_grayscale"
                roughness_path = batch_path / folder_name / "roughness.png"
                if roughness_path.exists():
                    r_img = cv2.imread(str(roughness_path), cv2.IMREAD_UNCHANGED)
                    if r_img is not None:
                        scaled = apply_roughness_scale_inmemory(r_img, roughness_scale)
                        refine_dir = batch_path / "map_refine"
                        refine_dir.mkdir(exist_ok=True)
                        out_path = refine_dir / "roughness_scaled.png"
                        cv2.imwrite(str(out_path), scaled)
                        saved_files.append(str(out_path))
            except Exception as e:
                errors.append({"phase": "map_refine/roughness", "error": str(e)})

    # Phase 4: Seamless & Tiling
    if phase_idx >= 4 and phases["seamless_tiling"]["status"] in ("completed", "in_progress"):
        seamless_params = phases["seamless_tiling"]["params"]
        s_params = seamless_params.get("seamless", {})

        # Apply seamless to all PBR maps with same params
        pbr_mode = phases["pbr"]["params"].get("mode", "grayscale")
        folder_name = "pbr_colored" if pbr_mode == "color" else "pbr_grayscale"
        pbr_folder = batch_path / folder_name

        if pbr_folder.exists():
            try:
                from scripts.processing import seamless_service
                method = s_params.get("method", "overlay")
                blend_width = s_params.get("blend_width", 64)

                output_dir = batch_path / "seamless"
                output_dir.mkdir(exist_ok=True)

                for map_name in ["albedo", "normals", "roughness", "height_map"]:
                    map_path = pbr_folder / f"{map_name}.png"
                    if not map_path.exists():
                        continue
                    img = cv2.imread(str(map_path), cv2.IMREAD_UNCHANGED)
                    if img is None:
                        continue

                    if method == "mirror":
                        result = seamless_service.make_seamless_mirror(img, blend_width)
                    elif method == "poisson":
                        result = seamless_service.make_seamless_poisson(img, blend_width)
                    else:
                        result = seamless_service.make_seamless_overlay(
                            img, blend_width,
                            spots_removal=s_params.get("spots_removal", False),
                            color_equalizer=s_params.get("color_equalizer", 0),
                        )
                    out_path = output_dir / f"{map_name}.png"
                    cv2.imwrite(str(out_path), result)
                    saved_files.append(str(out_path))
            except Exception as e:
                errors.append({"phase": "seamless_tiling", "error": str(e)})

    # Phase 5: Validate & Export
    if phase_idx >= 5 and phases["validate_export"]["status"] in ("completed", "in_progress"):
        try:
            from scripts.processing import validate_service
            val_params = phases["validate_export"]["params"]
            validate_service.validate_albedo(
                str(batch_path),
                dark_threshold=val_params.get("albedo_dark_threshold", 30),
            )
        except Exception as e:
            errors.append({"phase": "validate_export", "error": str(e)})

    # Clean up cache
    cache_dir = batch_path / "_cache"
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)

    return {
        "success": len(errors) == 0,
        "saved_files": saved_files,
        "errors": errors,
        "save_through": save_through_phase,
    }


def render_pbr_preview(batch_path: Path, track: dict, preview_max_size: int = 2400) -> Dict:
    """
    For PBR phase: materializes all 9 processed images to _cache/,
    runs photometric stereo, returns preview URLs.
    Uses half_size + downscale and parallel loading for speed.
    """
    batch_path = Path(batch_path)
    phases = track["phases"]

    # Materialize processed images to _cache
    cache_dir = batch_path / "_cache"
    cache_dir.mkdir(exist_ok=True)

    source = _find_source_folder(batch_path)
    if not source:
        return {"success": False, "error": "No source images found"}

    is_raw_source = source.name == 'raw'
    if is_raw_source:
        all_images = _list_raw_files(source)
    else:
        all_images = _list_images(source)
    crop_params = phases["crop_align"]["params"]
    color_params = phases["color"]["params"]
    checker_wb = color_params.get("checker_wb") if is_raw_source else None

    has_calibration = color_params.get("matrix_3x3") is not None

    # Precompute crop scale: load first image to get dimensions, compute scale factor
    _first = all_images[0] if all_images else None
    _pbr_crop_params = crop_params
    if _first and is_raw_source and _first.suffix.lower() in RAW_EXTENSIONS:
        try:
            import rawpy as _rp
            with _rp.imread(str(_first)) as _raw:
                _orig_w = _raw.sizes.width
            # half_size gives ~half, then downscale to preview_max_size
            _half_w = _orig_w // 2
            _scale = min(preview_max_size / _half_w, 1.0) * (_half_w / _orig_w)
            _pbr_crop_params = _scale_crop_params(crop_params, _scale)
        except Exception:
            pass
    elif _first and not is_raw_source:
        # Non-RAW: loaded at full res, downscale factor is just preview_max_size / max_dim
        _probe = cv2.imread(str(_first), cv2.IMREAD_UNCHANGED)
        if _probe is not None:
            _h, _w = _probe.shape[:2]
            _scale = preview_max_size / max(_h, _w) if max(_h, _w) > preview_max_size else 1.0
            _pbr_crop_params = _scale_crop_params(crop_params, _scale)
            del _probe

    def _process_one_pbr_image(img_path: Path) -> Optional[str]:
        """Load, process, downscale, and write one image to cache. Returns stem or None."""
        try:
            img = _load_image(img_path, fixed_wb=checker_wb, half_size=True)
            if img is None:
                return None

            # Downscale to preview resolution before processing
            h, w = img.shape[:2]
            if max(h, w) > preview_max_size:
                s = preview_max_size / max(h, w)
                img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

            img = _apply_crop_inmemory(img, _pbr_crop_params)
            img = _apply_calibration_inmemory(img, color_params, skip_sharpen=True)
            img = _apply_exposure_inmemory(img, color_params)

            # If source is RAW and no calibration matrix, apply sRGB gamma
            # so PBR operates on perceptually correct images
            if is_raw_source and not has_calibration and img.dtype == np.uint16:
                img_f = img.astype(np.float32) / 65535.0
                img_rgb = img_f[:, :, ::-1]
                srgb = _linear_to_srgb(img_rgb)
                srgb_16 = (srgb * 65535).astype(np.uint16)
                img = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)

            out_path = cache_dir / f"{img_path.stem}.tiff"
            cv2.imwrite(str(out_path), img)
            return img_path.stem
        except Exception as e:
            logger.error(f"Cache write failed for {img_path.name}: {e}")
            return None

    # Process all images in parallel (4 workers balances CPU vs memory)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_process_one_pbr_image, all_images))

    # Run PBR on cached images
    try:
        from scripts.processing.pbr_service import PBRService, PBRMode
        pbr = PBRService()
        mode_str = phases["pbr"]["params"].get("mode", "grayscale")

        # Pass cache folder directly so PBR uses our processed images
        mode = PBRMode(mode_str) if mode_str != "both" else PBRMode.BOTH
        results = pbr.generate(str(batch_path), mode=mode, source_folder=str(cache_dir))

        # Clean up cache
        shutil.rmtree(cache_dir, ignore_errors=True)

        batch_name = batch_path.name
        pbr_mode = "grayscale" if mode_str != "color" else "color"
        folder = f"pbr_{pbr_mode}"

        return {
            "success": True,
            "albedo_url": f"/media/captures/{batch_name}/{folder}/albedo.png",
            "normals_url": f"/media/captures/{batch_name}/{folder}/normals.png",
            "roughness_url": f"/media/captures/{batch_name}/{folder}/roughness.png",
            "height_map_url": f"/media/captures/{batch_name}/{folder}/height_map.png",
        }
    except Exception as e:
        shutil.rmtree(cache_dir, ignore_errors=True)
        return {"success": False, "error": str(e)}

"""
Material tools orchestration service — delegation layer between the
processing router and the scripts.processing.* material tool modules
(equalize, delight, flatten, perspective, seamless, tile, validate, clone,
straighten) plus the shared Path walks (tool source-folder priority, tool
image resolution, tools status, pipeline folder existence).

Extracted behavior-identically from app/routers/processing.py: kwargs are
forwarded verbatim and scripts.processing imports stay lazy (per-call)
exactly as the router performed them. Functions take the parsed request
model plus the resolved batch Path; the router keeps parse/validate duties.
"""
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

IMAGE_EXTS = {'.tiff', '.tif', '.png', '.jpg', '.jpeg', '.arw', '.cr2', '.nef', '.dng'}

# Source folder priority per tool for GET /{tool}/image/{batch_name}
TOOL_SOURCE_PRIORITY = {
    'equalize': ['color_calibrated', 'cropped', 'tiff'],
    'flatten': ['equalized', 'color_calibrated', 'cropped', 'tiff'],
    'delight': ['flattened', 'equalized', 'color_calibrated', 'cropped', 'tiff'],
    'perspective': ['cropped', 'tiff'],
    'straighten': ['perspective_corrected', 'color_calibrated', 'cropped', 'tiff', 'raw'],
    'seamless': ['straightened', 'delighted', 'flattened', 'equalized', 'color_calibrated', 'cropped', 'tiff'],
    'tile': ['seamless', 'straightened', 'delighted', 'flattened', 'equalized', 'cropped', 'tiff'],
    'validate': ['pbr_grayscale', 'pbr_colored'],
    'clone': ['seamless', 'straightened', 'delighted', 'flattened', 'equalized', 'cropped', 'tiff'],
}

# Source folder priority for analyze tools resolving their own top image
ANALYZE_SOURCE_PRIORITY = {
    'perspective': ['cropped', 'tiff'],
    'flatten': ['equalized', 'color_calibrated', 'cropped', 'tiff'],
    'straighten': ['perspective_corrected', 'color_calibrated', 'cropped', 'tiff', 'raw'],
    'seamless': ['delighted', 'flattened', 'equalized', 'color_calibrated', 'cropped', 'tiff'],
}


def find_top_image_for_tool(batch_path: Path, tool: str) -> Path:
    """Resolve the top image path for a given tool using source folder priority."""
    image_exts = IMAGE_EXTS
    for folder_name in ANALYZE_SOURCE_PRIORITY.get(tool, ['cropped', 'tiff']):
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            images = sorted(f for f in folder.iterdir() if f.suffix.lower() in image_exts)
            if images:
                for img in images:
                    if '_top' in img.name.lower() or img.name.lower().startswith('top'):
                        return img
                return images[0]
    raise HTTPException(status_code=404, detail="No source images found for this tool")


def get_tool_image(batch_path: Path, batch_name: str, tool: str) -> dict:
    """Top/source image info for any processing tool (folder priority walk)."""
    folders_to_check = TOOL_SOURCE_PRIORITY.get(tool, ['cropped', 'tiff'])
    source_folder = None
    for folder_name in folders_to_check:
        folder = batch_path / folder_name
        if folder.exists() and any(folder.iterdir()):
            source_folder = folder
            break

    if not source_folder:
        raise HTTPException(status_code=404, detail="No source images found for this tool")

    # List images
    images = sorted([
        f for f in source_folder.iterdir()
        if f.suffix.lower() in IMAGE_EXTS
    ])

    if not images:
        raise HTTPException(status_code=404, detail="No images in source folder")

    # Find top image
    top = None
    for img in images:
        if '_top' in img.name.lower() or img.name.lower().startswith('top'):
            top = img
            break
    if not top:
        top = images[0]

    # Check for thumbnails
    thumb_folder = source_folder.name + "_thumbnail"
    thumb_path = batch_path / thumb_folder / f"{top.stem}.jpg"
    webview_path = batch_path / "full_webview" / f"{top.stem}.jpg"
    generic_thumb = batch_path / "thumbnail" / f"{top.stem}.jpg"

    if thumb_path.exists():
        preview_url = f"/media/captures/{batch_name}/{thumb_folder}/{top.stem}.jpg"
    elif webview_path.exists():
        preview_url = f"/media/captures/{batch_name}/full_webview/{top.stem}.jpg"
    elif generic_thumb.exists():
        preview_url = f"/media/captures/{batch_name}/thumbnail/{top.stem}.jpg"
    else:
        preview_url = f"/media/captures/{batch_name}/{source_folder.name}/{top.name}"

    return {
        "batch_name": batch_name,
        "source_folder": source_folder.name,
        "filename": top.name,
        "preview_url": preview_url,
        "image_count": len(images),
        "images": [img.name for img in images],
    }


def tools_status(batch_path: Path, batch_name: str) -> dict:
    """Which pipeline output folders exist (non-empty) for a batch."""

    def _exists(name: str) -> bool:
        for candidate in [batch_path / name, batch_path / "output" / name]:
            if candidate.exists() and any(candidate.iterdir()):
                return True
        return False

    return {
        "batch_name": batch_name,
        "perspective_corrected": _exists("perspective_corrected"),
        "equalized": _exists("equalized"),
        "flattened": _exists("flattened"),
        "delighted": _exists("delighted"),
        "seamless": _exists("seamless"),
        "tiled": _exists("tiled"),
    }


def pipeline_folders(batch_path: Path) -> dict:
    """Existence flags for the main processing pipeline folders."""
    return {
        "tiff": (batch_path / "tiff").exists(),
        "raw": (batch_path / "raw").exists(),
        "cropped": (batch_path / "cropped").exists(),
        "color_calibrated": (batch_path / "color_calibrated").exists(),
        "pbr_grayscale": (batch_path / "pbr_grayscale").exists(),
        "pbr_colored": (batch_path / "pbr_colored").exists(),
    }


# ─── Equalize ───

def equalize_preview(request, batch_path: Path):
    from scripts.processing.equalize_service import preview

    return preview(
        batch_path=str(batch_path),
        method=request.method,
        reference_image=request.reference_image,
        clip_limit=request.clip_limit,
    )


def equalize_apply(request, batch_path: Path):
    from scripts.processing.equalize_service import apply

    return apply(
        batch_path=str(batch_path),
        method=request.method,
        reference_image=request.reference_image,
        clip_limit=request.clip_limit,
    )


# ─── Delight ───

def delight_preview(request, batch_path: Path):
    from scripts.processing.delight_service import preview

    return preview(
        batch_path=str(batch_path),
        blur_radius=request.blur_radius,
        strength=request.strength,
        method=request.method,
    )


def delight_apply(request, batch_path: Path):
    from scripts.processing.delight_service import apply

    return apply(
        batch_path=str(batch_path),
        blur_radius=request.blur_radius,
        strength=request.strength,
        method=request.method,
    )


# ─── Flatten ───

def flatten_preview(request, batch_path: Path):
    from scripts.processing.flatten_service import preview

    return preview(
        batch_path=str(batch_path),
        strength=request.strength,
        smoothing_radius=request.smoothing_radius,
        pbr_mode=request.pbr_mode,
    )


def flatten_apply(request, batch_path: Path):
    from scripts.processing.flatten_service import apply

    return apply(
        batch_path=str(batch_path),
        strength=request.strength,
        smoothing_radius=request.smoothing_radius,
        pbr_mode=request.pbr_mode,
    )


# ─── Perspective ───

def perspective_detect_lines(request, batch_path: Path) -> dict:
    from scripts.processing.perspective_service import detect_lines

    result = detect_lines(image_path=find_top_image_for_tool(batch_path, 'perspective'))
    result["batch_name"] = request.batch_name
    return result


def perspective_preview(request, batch_path: Path):
    from scripts.processing.perspective_service import preview

    source_pts = [{"x": p.x, "y": p.y} for p in request.source_points]
    dest_pts = [{"x": p.x, "y": p.y} for p in request.dest_points] if request.dest_points else None
    return preview(
        batch_path=batch_path,
        source_points=source_pts,
        dest_points=dest_pts,
    )


def perspective_apply(request, batch_path: Path):
    from scripts.processing.perspective_service import apply

    source_pts = [{"x": p.x, "y": p.y} for p in request.source_points]
    dest_pts = [{"x": p.x, "y": p.y} for p in request.dest_points] if request.dest_points else None
    return apply(
        batch_path=batch_path,
        source_points=source_pts,
        dest_points=dest_pts,
    )


# ─── Seamless ───

def seamless_analyze(request, batch_path: Path) -> dict:
    from scripts.processing.seamless_service import analyze_seams

    result = analyze_seams(
        image_path=find_top_image_for_tool(batch_path, 'seamless'),
        blend_width=request.blend_width or 128,
    )
    result["batch_name"] = request.batch_name
    return result


def seamless_preview(request, batch_path: Path):
    from scripts.processing.seamless_service import preview

    return preview(
        batch_path=batch_path,
        method=request.method,
        blend_width=request.blend_width,
        spots_removal=request.spots_removal,
        color_equalizer=request.color_equalizer,
        tile_count=request.tile_count,
    )


def seamless_apply(request, batch_path: Path):
    from scripts.processing.seamless_service import apply

    return apply(
        batch_path=batch_path,
        method=request.method,
        blend_width=request.blend_width,
        spots_removal=request.spots_removal,
        color_equalizer=request.color_equalizer,
    )


# ─── Tile ───

def tile_preview(request, batch_path: Path):
    from scripts.processing.tile_service import preview

    return preview(
        batch_path=str(batch_path),
        tile_x=request.tile_x,
        tile_y=request.tile_y,
        offset_x=request.offset_x,
        offset_y=request.offset_y,
        scale=request.scale,
        rotation=request.rotation,
        overlap=request.overlap,
        half_drop=request.half_drop,
    )


def tile_apply(request, batch_path: Path):
    from scripts.processing.tile_service import apply

    return apply(
        batch_path=str(batch_path),
        tile_x=request.tile_x,
        tile_y=request.tile_y,
        offset_x=request.offset_x,
        offset_y=request.offset_y,
        scale=request.scale,
        rotation=request.rotation,
        overlap=request.overlap,
        half_drop=request.half_drop,
        output_resolution=tuple(request.output_resolution) if request.output_resolution else (2048, 2048),
    )


# ─── Validate ───

def validate_check(request, batch_path: Path) -> dict:
    from scripts.processing.validate_service import validate_albedo, validate_metallic

    checks = []
    albedo_result = validate_albedo(
        batch_path=str(batch_path),
        dark_threshold=int(request.albedo_dark_threshold),
    )
    checks.append({"map": "albedo", **albedo_result})

    metal_range = tuple(request.metal_range) if request.metal_range else (180, 255)
    metallic_result = validate_metallic(
        batch_path=str(batch_path),
        metal_range=metal_range,
    )
    checks.append({"map": "metallic", **metallic_result})

    all_passed = all(c.get("passed", False) for c in checks if c.get("success", True))
    return {
        "success": True,
        "batch_name": request.batch_name,
        "checks": checks,
        "all_passed": all_passed,
    }


def validate_stats(batch_name: str, batch_path: Path) -> dict:
    from scripts.processing.validate_service import get_stats

    result = get_stats(batch_path=str(batch_path))
    result["batch_name"] = batch_name
    return result


# ─── Clone / Inpaint ───

def clone_inpaint(request, batch_path: Path):
    from scripts.processing.clone_service import preview_inpaint

    return preview_inpaint(
        batch_path=str(batch_path),
        mask_data_b64=request.mask_data,
        method=request.method,
        radius=request.radius,
    )


def clone_stamp(request, batch_path: Path):
    from scripts.processing.clone_service import preview_stamp

    return preview_stamp(
        batch_path=str(batch_path),
        source_pos={"x": request.source_pos.x, "y": request.source_pos.y},
        target_pos={"x": request.target_pos.x, "y": request.target_pos.y},
        radius=request.radius,
        fade=request.fade,
        blur_mask=request.blur_mask,
        mirror=request.mirror,
    )


def clone_apply(request, batch_path: Path):
    from scripts.processing.clone_service import apply

    return apply(
        batch_path=str(batch_path),
        operations=request.operations,
    )


# ─── Straighten ───

def straighten_analyze(request, batch_path: Path) -> dict:
    from scripts.processing.straighten_service import analyze

    result = analyze(
        image_path=find_top_image_for_tool(batch_path, 'straighten'),
        grid_divisions=request.grid_divisions,
        direction=request.direction,
    )
    result["batch_name"] = request.batch_name
    return result


def straighten_preview(request, batch_path: Path):
    from scripts.processing.straighten_service import preview

    return preview(
        batch_path=batch_path,
        mode=request.mode,
        strength=request.strength,
        direction=request.direction,
        grid_divisions=request.grid_divisions,
        manual_skew_angle=request.manual_skew_angle,
    )


def straighten_apply(request, batch_path: Path):
    from scripts.processing.straighten_service import apply

    return apply(
        batch_path=batch_path,
        mode=request.mode,
        strength=request.strength,
        direction=request.direction,
        grid_divisions=request.grid_divisions,
        manual_skew_angle=request.manual_skew_angle,
    )

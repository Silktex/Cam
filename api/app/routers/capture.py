"""
Capture Router - Image capture with folder support
"""
import io
import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services.camera_service import camera_service
from app.models.capture import (
    CaptureRequest,
    CaptureResponse,
    CaptureResult,
    FolderInfo,
    GalleryResponse,
)

router = APIRouter()


@router.post("/", response_model=CaptureResponse)
async def capture_images(request: CaptureRequest):
    """
    Capture one or more images and save to specified folder.
    Folder is created inside media/captures/.
    """
    results: List[CaptureResult] = []
    success_count = 0
    
    for i in range(request.count):
        result = camera_service.capture_image(request.folder, request.prefix)
        
        if result["success"]:
            success_count += 1
            results.append(CaptureResult(
                success=True,
                filename=result["filename"],
                filepath=result["filepath"],
                file_url=result["file_url"],
                file_size=result["file_size"],
                captured_at=result.get("captured_at"),
            ))
        else:
            results.append(CaptureResult(
                success=False,
                error=result.get("error"),
            ))
    
    return CaptureResponse(
        success=success_count > 0,
        captured_count=success_count,
        total_requested=request.count,
        folder=request.folder,
        files=results,
        message=f"Captured {success_count}/{request.count} images",
    )


SIZE_PRESETS = {
    "thumb": 400,
    "webview": 2400,
    "full": None,  # no resize
}


@router.get("/image/{session}/{filename}")
async def serve_image(
    session: str,
    filename: str,
    size: str = Query("full", regex="^(thumb|webview|full)$"),
):
    """
    Serve a JPG from the jpg/ folder, optionally resized on-the-fly.
    ?size=thumb  → max 400px longest side
    ?size=webview → max 2400px longest side
    ?size=full   → original resolution
    """
    jpg_path = settings.CAPTURES_DIR / session / "jpg" / filename

    # Prevent path traversal
    try:
        jpg_path.resolve().relative_to(settings.CAPTURES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not jpg_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    from PIL import Image as PILImage

    max_px = SIZE_PRESETS[size]
    img = PILImage.open(jpg_path)

    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px), PILImage.Resampling.LANCZOS)

    buf = io.BytesIO()
    quality = 80 if size == "thumb" else 92
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/folders", response_model=GalleryResponse)
async def list_folders():
    """List all capture folders with their stats (supports nested subfolders)"""
    folders: List[FolderInfo] = []
    total_captures = 0

    captures_dir = settings.CAPTURES_DIR

    if not captures_dir.exists():
        return GalleryResponse(folders=[], total_captures=0)

    for folder_path in sorted(captures_dir.iterdir()):
        if folder_path.is_dir():
            # Recursively find all files (handles both flat and nested structures)
            all_files = list(folder_path.rglob("*"))
            file_count = len([f for f in all_files if f.is_file()])
            total_size = sum(f.stat().st_size for f in all_files if f.is_file())
            total_captures += file_count

            folders.append(FolderInfo(
                name=folder_path.name,
                path=str(folder_path),
                file_count=file_count,
                total_size=total_size,
            ))

    return GalleryResponse(folders=folders, total_captures=total_captures)


@router.get("/browse/{path:path}")
async def browse_path(path: str = ""):
    """Browse captures directory - supports nested navigation with breadcrumbs"""
    # Handle empty path as root
    if not path or path == "/":
        browse_path_obj = settings.CAPTURES_DIR
        path = ""
    else:
        browse_path_obj = settings.CAPTURES_DIR / path

    if not browse_path_obj.exists():
        raise HTTPException(status_code=404, detail=f"Path '{path}' not found")

    if not browse_path_obj.is_dir():
        raise HTTPException(status_code=400, detail=f"Path '{path}' is not a directory")

    # Build breadcrumbs
    breadcrumbs = [{"name": "Captures", "path": ""}]
    if path:
        parts = path.split("/")
        for i, part in enumerate(parts):
            breadcrumbs.append({
                "name": part,
                "path": "/".join(parts[:i+1])
            })

    # List contents
    items = []
    for item in sorted(browse_path_obj.iterdir()):
        rel_path = f"{path}/{item.name}" if path else item.name

        if item.is_dir():
            # Count files in subdirectory
            file_count = len([f for f in item.rglob("*") if f.is_file()])
            items.append({
                "name": item.name,
                "type": "folder",
                "path": rel_path,
                "file_count": file_count,
                "size": None,
                "modified": item.stat().st_mtime,
            })
        else:
            # Check if it's an image
            ext = item.suffix.lower()
            is_image = ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif", ".arw", ".cr2", ".nef", ".dng"]

            # Find thumbnail and display/download URLs
            # Use the dynamic resize endpoint when a jpg/ derivative exists
            thumbnail_url = None
            display_url = f"/media/captures/{rel_path}"
            download_url = f"/media/captures/{rel_path}"

            DERIVED_FOLDERS = {"raw", "jpg", "tiff", "thumbnail", "cropped_thumbnail", "full_webview"}
            if is_image and path:
                parent_parts = path.split("/")
                session_folder = parent_parts[0] if len(parent_parts) >= 1 else None
                current_subfolder = parent_parts[1] if len(parent_parts) >= 2 else None

                if session_folder:
                    jpg_file = settings.CAPTURES_DIR / session_folder / "jpg" / f"{item.stem}.jpg"
                    has_jpg = jpg_file.is_file()

                    if current_subfolder == "cropped":
                        # Browsing cropped folder — use cropped_thumbnail for cards
                        cropped_thumb_path = settings.CAPTURES_DIR / session_folder / "cropped_thumbnail" / f"{item.stem}.jpg"
                        if cropped_thumb_path.exists():
                            thumbnail_url = f"/media/captures/{session_folder}/cropped_thumbnail/{item.stem}.jpg"
                            display_url = f"/media/captures/{session_folder}/cropped_thumbnail/{item.stem}.jpg"
                        download_url = f"/media/captures/{rel_path}"
                    elif current_subfolder in DERIVED_FOLDERS:
                        # Browsing a specific derived folder — use dynamic resize from jpg/
                        if has_jpg:
                            thumbnail_url = f"/api/capture/image/{session_folder}/{item.stem}.jpg?size=thumb"
                            display_url = f"/api/capture/image/{session_folder}/{item.stem}.jpg?size=webview"
                    else:
                        # Session root or unknown subfolder
                        cropped_thumb_path = settings.CAPTURES_DIR / session_folder / "cropped_thumbnail" / f"{item.stem}.jpg"
                        if cropped_thumb_path.exists():
                            thumbnail_url = f"/media/captures/{session_folder}/cropped_thumbnail/{item.stem}.jpg"
                            display_url = f"/media/captures/{session_folder}/cropped_thumbnail/{item.stem}.jpg"
                        elif has_jpg:
                            thumbnail_url = f"/api/capture/image/{session_folder}/{item.stem}.jpg?size=thumb"
                            display_url = f"/api/capture/image/{session_folder}/{item.stem}.jpg?size=webview"

                        # Download URL: prefer cropped > original
                        cropped_dir = settings.CAPTURES_DIR / session_folder / "cropped"
                        for crop_ext in ['.tiff', '.jpg', '.jpeg', '.png']:
                            cropped_path = cropped_dir / f"{item.stem}{crop_ext}"
                            if cropped_path.exists():
                                download_url = f"/media/captures/{session_folder}/cropped/{item.stem}{crop_ext}"
                                break

            items.append({
                "name": item.name,
                "type": "file",
                "path": rel_path,
                "url": display_url,
                "download_url": download_url,
                "thumbnail_url": thumbnail_url,
                "size": item.stat().st_size,
                "modified": item.stat().st_mtime,
                "is_image": is_image,
            })

    return {
        "path": path,
        "breadcrumbs": breadcrumbs,
        "items": items,
        "folder_count": len([i for i in items if i["type"] == "folder"]),
        "file_count": len([i for i in items if i["type"] == "file"]),
    }


@router.get("/folders/{folder_name}")
async def list_folder_contents(folder_name: str):
    """List files in a capture folder (supports nested subfolders like raw/, thumbnail/, etc.)"""
    folder_path = settings.CAPTURES_DIR / folder_name

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail=f"Folder '{folder_name}' not found")

    files = []
    subfolders = {}

    for item in sorted(folder_path.iterdir()):
        if item.is_file():
            # Direct file in folder (legacy flat structure)
            files.append({
                "name": item.name,
                "url": f"/media/captures/{folder_name}/{item.name}",
                "size": item.stat().st_size,
                "modified": item.stat().st_mtime,
                "subfolder": None,
            })
        elif item.is_dir():
            # Subfolder (raw, thumbnail, full_webview, tiff)
            subfolder_name = item.name
            subfolder_files = []
            for file_path in sorted(item.rglob("*")):
                if file_path.is_file():
                    rel_path = file_path.relative_to(folder_path)
                    subfolder_files.append({
                        "name": file_path.name,
                        "url": f"/media/captures/{folder_name}/{rel_path}",
                        "size": file_path.stat().st_size,
                        "modified": file_path.stat().st_mtime,
                        "subfolder": subfolder_name,
                    })
            subfolders[subfolder_name] = subfolder_files
            files.extend(subfolder_files)

    return {
        "folder": folder_name,
        "files": files,
        "subfolders": subfolders,
        "count": len(files),
    }


@router.delete("/folders/{folder_path:path}")
async def delete_folder(folder_path: str):
    """Delete a capture folder and all its contents"""
    full_path = settings.CAPTURES_DIR / folder_path

    # Prevent path traversal
    try:
        full_path.resolve().relative_to(settings.CAPTURES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"Folder not found")

    if not full_path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a folder")

    import shutil
    shutil.rmtree(full_path)

    # Cascade: deleting paired folders (e.g. cropped -> also delete cropped_thumbnail)
    FOLDER_PAIRS = {
        "cropped": "cropped_thumbnail",
        "cropped_thumbnail": "cropped",
    }
    folder_name = full_path.name
    if folder_name in FOLDER_PAIRS:
        paired = full_path.parent / FOLDER_PAIRS[folder_name]
        if paired.exists() and paired.is_dir():
            shutil.rmtree(paired)

    return {"success": True, "message": f"Deleted folder '{full_path.name}'"}


@router.delete("/files/{file_path:path}")
async def delete_file(file_path: str):
    """Delete a single file from captures"""
    full_path = settings.CAPTURES_DIR / file_path

    # Prevent path traversal
    try:
        full_path.resolve().relative_to(settings.CAPTURES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found")

    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    full_path.unlink()

    # Also delete associated derived files
    parts = file_path.split("/")
    if len(parts) >= 2:
        session_folder = parts[0]
        source_dir = parts[1] if len(parts) >= 3 else None
        stem = full_path.stem

        # Map: when deleting from source_dir, also clean up these sibling dirs
        SIBLING_MAP = {
            "cropped": ["cropped_thumbnail"],
            "cropped_thumbnail": ["cropped"],
        }
        # Default: clean all derived dirs
        dirs_to_clean = SIBLING_MAP.get(source_dir, ["jpg", "thumbnail", "cropped_thumbnail", "full_webview", "cropped"])

        for derived_dir in dirs_to_clean:
            derived_parent = settings.CAPTURES_DIR / session_folder / derived_dir
            if derived_parent.exists():
                for f in derived_parent.iterdir():
                    if f.stem == stem:
                        f.unlink()

    return {"success": True, "message": f"Deleted '{full_path.name}'"}

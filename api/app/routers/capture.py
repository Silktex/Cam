"""
Capture Router - Image capture with folder support
"""
import os
from pathlib import Path
from typing import List
from fastapi import APIRouter, HTTPException

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
        prefix = f"{request.prefix}_{i+1}" if request.count > 1 else request.prefix
        result = camera_service.capture_image(request.folder, prefix)
        
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

            # Find thumbnail if available
            thumbnail_url = None
            if is_image and path:
                # Try to find corresponding thumbnail
                parent_parts = path.split("/")
                if len(parent_parts) >= 1:
                    session_folder = parent_parts[0]
                    thumb_path = settings.CAPTURES_DIR / session_folder / "thumbnail" / f"{item.stem}.jpg"
                    if thumb_path.exists():
                        thumbnail_url = f"/media/captures/{session_folder}/thumbnail/{item.stem}.jpg"

            items.append({
                "name": item.name,
                "type": "file",
                "path": rel_path,
                "url": f"/media/captures/{rel_path}",
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


@router.delete("/folders/{folder_name}")
async def delete_folder(folder_name: str):
    """Delete a capture folder and all its contents"""
    folder_path = settings.CAPTURES_DIR / folder_name
    
    if not folder_path.exists():
        raise HTTPException(status_code=404, detail=f"Folder '{folder_name}' not found")
    
    import shutil
    shutil.rmtree(folder_path)
    
    return {"success": True, "message": f"Deleted folder '{folder_name}'"}

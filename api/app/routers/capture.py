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
    """List all capture folders with their stats"""
    folders: List[FolderInfo] = []
    total_captures = 0
    
    captures_dir = settings.CAPTURES_DIR
    
    if not captures_dir.exists():
        return GalleryResponse(folders=[], total_captures=0)
    
    for folder_path in sorted(captures_dir.iterdir()):
        if folder_path.is_dir():
            files = list(folder_path.glob("*"))
            file_count = len([f for f in files if f.is_file()])
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            total_captures += file_count
            
            folders.append(FolderInfo(
                name=folder_path.name,
                path=str(folder_path),
                file_count=file_count,
                total_size=total_size,
            ))
    
    return GalleryResponse(folders=folders, total_captures=total_captures)


@router.get("/folders/{folder_name}")
async def list_folder_contents(folder_name: str):
    """List files in a specific capture folder"""
    folder_path = settings.CAPTURES_DIR / folder_name
    
    if not folder_path.exists():
        raise HTTPException(status_code=404, detail=f"Folder '{folder_name}' not found")
    
    files = []
    for file_path in sorted(folder_path.iterdir()):
        if file_path.is_file():
            files.append({
                "name": file_path.name,
                "url": f"/media/captures/{folder_name}/{file_path.name}",
                "size": file_path.stat().st_size,
                "modified": file_path.stat().st_mtime,
            })
    
    return {
        "folder": folder_name,
        "files": files,
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

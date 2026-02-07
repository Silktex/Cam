"""
Capture-related Pydantic models
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field


class CaptureRequest(BaseModel):
    """Request to capture image(s)"""
    folder: str = Field(..., description="Folder name to save captures (inside media/captures/)")
    prefix: str = Field(default="capture", description="Filename prefix")
    count: int = Field(default=1, ge=1, le=100, description="Number of images to capture")


class CaptureResult(BaseModel):
    """Single capture result"""
    success: bool
    filename: Optional[str] = None
    filepath: Optional[str] = None
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    error: Optional[str] = None
    captured_at: Optional[datetime] = None


class CaptureResponse(BaseModel):
    """Response from capture request"""
    success: bool
    captured_count: int
    total_requested: int
    folder: str
    files: List[CaptureResult]
    message: str


class FolderInfo(BaseModel):
    """Information about a capture folder"""
    name: str
    path: str
    file_count: int
    total_size: int
    created_at: Optional[datetime] = None


class GalleryResponse(BaseModel):
    """Response listing capture folders"""
    folders: List[FolderInfo]
    total_captures: int

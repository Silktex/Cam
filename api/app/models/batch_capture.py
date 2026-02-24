"""
Pydantic models for Batch Capture
"""
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class BatchCaptureRequest(BaseModel):
    """Request to start a batch capture session"""
    folder: str = Field(..., description="Folder name to save captures")
    prefix: str = Field(default="batch", description="Filename prefix")
    light_stabilize_delay: float = Field(default=2.0, ge=0.5, le=10.0, description="Seconds to wait after light change")


class BatchCaptureProgress(BaseModel):
    """Progress update for batch capture"""
    current_step: int = Field(..., description="Current step number (1-8)")
    total_steps: int = Field(default=8, description="Total steps")
    current_light: str = Field(..., description="Current side light name")
    status: str = Field(..., description="Status: waiting_light, capturing, processing, complete, error")
    message: str = Field(..., description="Human-readable status message")
    phase: str = Field(default="capturing", description="Phase: capturing or downloading")
    captures: List[str] = Field(default_factory=list, description="List of captured filenames so far")


class BatchCaptureResult(BaseModel):
    """Result of a batch capture session"""
    success: bool
    folder: str
    total_captures: int
    captures: List[dict] = Field(default_factory=list, description="List of capture details")
    started_at: str
    completed_at: str
    duration_seconds: float
    errors: List[str] = Field(default_factory=list)

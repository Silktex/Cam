"""
Application configuration with environment variable support
"""
import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment"""
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
    ]
    
    # Media storage
    MEDIA_DIR: Path = Path(__file__).parent.parent / "media"
    CAPTURES_DIR: Path = MEDIA_DIR / "captures"
    
    # Camera settings
    CAMERA_TIMEOUT: int = 10  # seconds
    PREVIEW_FPS: int = 15
    
    # macOS PTP daemons to kill
    PTP_PROCESSES: List[str] = [
        "PTPCamera",
        "ptpcamerad", 
        "mscamerad-xpc",
        "cameracaptured",
    ]
    
    class Config:
        env_file = ".env"
        extra = "ignore"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()

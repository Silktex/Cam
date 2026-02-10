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
    
    # ESP32 Light Controller (HTTP API)
    ESP32_HOST: str = "192.168.0.44"
    LIGHT_NAMES: str = "Top Light,Side 1 Light,Side 2 Light,Side 3 Light,Side 4 Light,Side 5 Light,Side 6 Light,Side 7 Light,Side 8 Light"
    LIGHT_PINS: str = "26,25,5,19,21,4,13,12,27"
    
    # macOS PTP daemons to kill
    PTP_PROCESSES: List[str] = [
        "PTPCamera",
        "ptpcamerad", 
        "mscamerad-xpc",
        "cameracaptured",
    ]
    
    @property
    def light_names_list(self) -> List[str]:
        return [n.strip() for n in self.LIGHT_NAMES.split(",")]
    
    @property
    def light_pins_list(self) -> List[int]:
        return [int(p.strip()) for p in self.LIGHT_PINS.split(",")]
    
    class Config:
        env_file = ".env"
        extra = "ignore"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()

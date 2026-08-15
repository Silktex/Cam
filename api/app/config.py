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
    LOG_LEVEL: str = "INFO"
    
    # CORS — allow all origins
    CORS_ORIGINS: List[str] = ["*"]
    
    # Media storage
    MEDIA_DIR: Path = Path(__file__).parent.parent / "media"
    CAPTURES_DIR: Path = MEDIA_DIR / "captures"
    COLORCHECKER_DIR: Path = MEDIA_DIR / "colorchecker"
    MODELS_DIR: Path = Path(__file__).parent.parent / "models"

    # Processing settings
    USE_GPU: bool = False  # Mac M4 uses MPS, set True for CUDA
    SAM_MODEL: str = "mobile_sam.pt"
    DOWNSAMPLE_SCALE: float = 1.0  # 1.0 = full resolution

    # Camera settings
    CAMERA_TIMEOUT: int = 10  # seconds
    PREVIEW_FPS: int = 15
    
    # ESP32 Light Controller (HTTP API)
    ESP32_HOST: str = "192.168.0.44"
    LIGHT_NAMES: str = "Top Light,Side 1 Light,Side 2 Light,Side 3 Light,Side 4 Light,Side 5 Light,Side 6 Light,Side 7 Light,Side 8 Light"
    LIGHT_PINS: str = "26,25,5,19,21,4,13,12,27"

    # Auto Exposure / RAW QA (feature-gated off by default)
    AUTO_EXPOSURE_ENABLED: bool = False
    AUTO_EXPOSURE_ISO: int = 100
    AUTO_EXPOSURE_APERTURE: float = 8.0
    AUTO_EXPOSURE_TARGET_NORMALIZED: float = 0.75
    AUTO_EXPOSURE_ACCEPTABLE_LOW: float = 0.60
    AUTO_EXPOSURE_ACCEPTABLE_HIGH: float = 0.85
    AUTO_EXPOSURE_NEAR_CLIP_THRESHOLD: float = 0.95
    AUTO_EXPOSURE_HARD_CLIP_THRESHOLD: float = 0.995
    AUTO_EXPOSURE_MAX_HARD_CLIP_FRACTION: float = 0.00001
    AUTO_EXPOSURE_MAX_NEAR_CLIP_FRACTION: float = 0.001
    AUTO_EXPOSURE_RETAKE_LIMIT: int = 2
    AUTO_EXPOSURE_MINIMUM_P95_NORMALIZED: float = 0.05
    
    # macOS PTP daemons that grab the camera USB
    PTP_PROCESSES: List[str] = [
        "PTPCamera",
        "ptpcamerad",
        "mscamerad-xpc",
        "cameracaptured",
    ]

    # Linux (Debian/Docker) processes that grab the camera USB
    LINUX_USB_PROCESSES: List[str] = [
        "gvfs-gphoto2-volume-monitor",
        "gvfsd-gphoto2",
    ]
    
    @property
    def light_names_list(self) -> List[str]:
        return [n.strip() for n in self.LIGHT_NAMES.split(",")]
    
    @property
    def light_pins_list(self) -> List[int]:
        return [int(p.strip()) for p in self.LIGHT_PINS.split(",")]

    def auto_exposure_config(self):
        """Build the exposure domain config from environment-backed settings."""
        from app.services.exposure.config import AutoExposureConfig

        return AutoExposureConfig(
            enabled=self.AUTO_EXPOSURE_ENABLED,
            iso=self.AUTO_EXPOSURE_ISO,
            aperture=self.AUTO_EXPOSURE_APERTURE,
            target_normalized=self.AUTO_EXPOSURE_TARGET_NORMALIZED,
            acceptable_low=self.AUTO_EXPOSURE_ACCEPTABLE_LOW,
            acceptable_high=self.AUTO_EXPOSURE_ACCEPTABLE_HIGH,
            near_clip_threshold=self.AUTO_EXPOSURE_NEAR_CLIP_THRESHOLD,
            hard_clip_threshold=self.AUTO_EXPOSURE_HARD_CLIP_THRESHOLD,
            max_hard_clip_fraction=self.AUTO_EXPOSURE_MAX_HARD_CLIP_FRACTION,
            max_near_clip_fraction=self.AUTO_EXPOSURE_MAX_NEAR_CLIP_FRACTION,
            retake_limit=self.AUTO_EXPOSURE_RETAKE_LIMIT,
            minimum_p95_normalized=self.AUTO_EXPOSURE_MINIMUM_P95_NORMALIZED,
        )

    class Config:
        env_file = ".env"
        extra = "ignore"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure directories exist
        self.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
        self.COLORCHECKER_DIR.mkdir(parents=True, exist_ok=True)
        self.MODELS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()

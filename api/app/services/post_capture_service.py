"""
Post-Capture Processing Service

Lazy calibrate+crop: processes ONLY the top image eagerly, stores calibration
parameters as JSON, and renders the other 8 images on demand via render_image().
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)

PROFILE_DIR = settings.MEDIA_DIR / "colorchecker" / "profiles"


@dataclass
class ProcessingJob:
    batch: str
    profile: str
    crop_size: int
    status: str = "pending"  # pending | processing | completed | failed
    error: Optional[str] = None
    queued_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    current_step: str = ""
    calibrated_count: int = 0
    cropped_count: int = 0


class PostCaptureService:
    """Manages background calibrate+crop jobs."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="postcap")
        self._jobs: Dict[str, ProcessingJob] = {}
        self._lock = threading.Lock()

    def queue(
        self,
        batch: str,
        profile: str = "CHECKER-17FEB.npz",
        crop_size: int = 2048,
    ) -> ProcessingJob:
        """Queue a calibrate+crop job for a batch folder."""
        profile_path = PROFILE_DIR / profile
        if not profile_path.exists():
            raise FileNotFoundError(f"Profile not found: {profile_path}")

        raw_dir = settings.CAPTURES_DIR / batch / "raw"
        if not raw_dir.exists():
            raise FileNotFoundError(f"RAW folder not found: {raw_dir}")

        with self._lock:
            # If already running/pending for this batch, don't duplicate
            existing = self._jobs.get(batch)
            if existing and existing.status in ("pending", "processing"):
                logger.info(f"Job already {existing.status} for {batch}")
                return existing

            job = ProcessingJob(
                batch=batch,
                profile=profile,
                crop_size=crop_size,
                status="pending",
                queued_at=datetime.now().isoformat(),
            )
            self._jobs[batch] = job

        self._executor.submit(self._run_job, batch)
        logger.info(f"Queued post-capture processing for {batch}")
        return job

    def get_status(self, batch: str) -> Optional[ProcessingJob]:
        """Get processing status for a batch."""
        return self._jobs.get(batch)

    def list_jobs(self) -> Dict[str, dict]:
        """List all jobs and their statuses."""
        return {
            batch: {
                "status": job.status,
                "current_step": job.current_step,
                "calibrated_count": job.calibrated_count,
                "cropped_count": job.cropped_count,
                "error": job.error,
                "queued_at": job.queued_at,
                "started_at": job.started_at,
                "completed_at": job.completed_at,
            }
            for batch, job in self._jobs.items()
        }

    def _run_job(self, batch: str):
        """Calibrate + crop the top image only, save params for on-demand rendering."""
        job = self._jobs[batch]
        job.status = "processing"
        job.started_at = datetime.now().isoformat()

        profile_path = PROFILE_DIR / job.profile
        raw_dir = settings.CAPTURES_DIR / batch / "raw"
        output_dir = settings.CAPTURES_DIR / batch / "output"

        try:
            import cv2
            import numpy as np
            import rawpy

            # ── Load profile ──
            job.current_step = "loading_profile"
            profile = np.load(str(profile_path), allow_pickle=True)
            detected = profile["detected_swatches"].astype(np.float64)
            reference = profile["reference_swatches"].astype(np.float64)
            checker_raw_path = Path(str(profile["checker_raw_path"]))

            logger.info(f"[{batch}] Profile: {job.profile}")

            # Extract checker WB
            checker_wb_raw = None
            if checker_raw_path.exists():
                with rawpy.imread(str(checker_raw_path)) as raw:
                    checker_wb_raw = list(raw.camera_whitebalance)
                logger.info(f"[{batch}] Checker WB: {checker_wb_raw}")
            else:
                logger.warning(f"[{batch}] Checker RAW not found, using per-image WB")

            # ── Compute 3x3 matrix ──
            job.current_step = "computing_matrix"
            matrix, wp_scale = _compute_3x3_matrix(detected, reference)

            # ── Find RAWs ──
            fabric_arws = sorted(
                f for f in raw_dir.iterdir()
                if f.suffix.lower() in {".arw", ".cr2", ".nef", ".dng"}
            )
            logger.info(f"[{batch}] Found {len(fabric_arws)} RAW files")

            # ── Find top RAW ──
            top_arw = next((f for f in fabric_arws if "_top" in f.name.lower()), None)
            if top_arw is None:
                raise ValueError("No top image found among RAW files")

            # ── Calibrate top image in memory (no file saved) ──
            job.current_step = "calibrating_top"

            img, _ = _load_raw_linear(top_arw, fixed_wb=checker_wb_raw)
            h, w, _ = img.shape
            flat = img.reshape(-1, 3)
            corrected = (matrix @ flat.T).T.reshape(h, w, 3)
            corrected = np.clip(corrected, 0, 1)

            srgb = _linear_to_srgb(corrected)
            srgb_16 = (srgb * 65535).astype(np.uint16)
            bgr_16 = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)
            bgr_16 = _sharpen_16(bgr_16)
            job.calibrated_count = 1
            logger.info(f"[{batch}] Calibrated top in memory: {top_arw.name}")

            # ── Detect boundary on calibrated top → compute crop box ──
            job.current_step = "detecting_boundary"
            bbox = _detect_fabric_boundary(bgr_16)

            h, w = bgr_16.shape[:2]
            if bbox is None:
                cx, cy = w // 2, h // 2
            else:
                x1, y1, x2, y2 = bbox
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

            half = job.crop_size // 2
            crop_x1 = max(0, cx - half)
            crop_y1 = max(0, cy - half)
            crop_x2 = min(w, crop_x1 + job.crop_size)
            crop_y2 = min(h, crop_y1 + job.crop_size)
            if crop_x2 - crop_x1 < job.crop_size:
                crop_x1 = max(0, crop_x2 - job.crop_size)
            if crop_y2 - crop_y1 < job.crop_size:
                crop_y1 = max(0, crop_y2 - job.crop_size)

            # ── Save calibration.json for on-demand rendering ──
            job.current_step = "saving_calibration"
            cal_data = {
                "profile_name": job.profile,
                "checker_wb": checker_wb_raw,
                "matrix_3x3": matrix.tolist(),
                "crop_box": {
                    "x1": int(crop_x1),
                    "y1": int(crop_y1),
                    "x2": int(crop_x2),
                    "y2": int(crop_y2),
                },
                "crop_size": job.crop_size,
                "raw_files": [f.name for f in fabric_arws],
                "top_image": top_arw.name,
                "created_at": datetime.now().isoformat(),
            }
            cal_json_path = output_dir / "calibration.json"
            output_dir.mkdir(parents=True, exist_ok=True)
            cal_json_path.write_text(json.dumps(cal_data, indent=2))
            logger.info(f"[{batch}] Saved calibration.json")

            job.status = "completed"
            job.completed_at = datetime.now().isoformat()
            job.current_step = "done"
            logger.info(f"[{batch}] Processing complete: calibration.json saved, {len(fabric_arws)} images available on-demand")

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now().isoformat()
            logger.exception(f"[{batch}] Processing failed: {e}")


# ── Helper functions (same math as calibrate_and_crop.py) ────────────────

NEUTRAL_INDICES = list(range(18, 24))
NEUTRAL_WEIGHT = 10.0
RIDGE_LAMBDA = 0.30
HUBER_DELTA = 0.03
HUBER_ITERATIONS = 3


def _load_raw_linear(raw_path, fixed_wb=None):
    import numpy as np
    import rawpy

    with rawpy.imread(str(raw_path)) as raw:
        camera_wb = list(raw.camera_whitebalance)
        if fixed_wb is not None:
            wb_params = dict(user_wb=fixed_wb, use_camera_wb=False)
        else:
            wb_params = dict(use_camera_wb=True)
        rgb = raw.postprocess(
            **wb_params,
            demosaic_algorithm=rawpy.DemosaicAlgorithm.DHT,
            output_bps=16,
            output_color=rawpy.ColorSpace.sRGB,
            no_auto_bright=True,
            gamma=(1, 1),
            half_size=False,
            fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
        )
    return rgb.astype(np.float32) / 65535.0, camera_wb


def _linear_to_srgb(img):
    import numpy as np

    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055,
    ).clip(0, 1)


def _sharpen_16(bgr_16):
    """Capture sharpening on 16-bit BGR — matches camera-embedded JPEG sharpness.

    Two-pass unsharp mask:
      1. Detail pass  (sigma=0.8, amount=0.7) — recovers fine texture/threads
      2. Structure pass (sigma=2.0, amount=0.3) — restores micro-contrast
    """
    import cv2
    import numpy as np

    img = bgr_16.astype(np.float32)

    # Pass 1: detail (tight radius)
    blur1 = cv2.GaussianBlur(img, (0, 0), sigmaX=0.8)
    img = img + 0.7 * (img - blur1)

    # Pass 2: structure (wider radius)
    blur2 = cv2.GaussianBlur(img, (0, 0), sigmaX=2.0)
    img = img + 0.3 * (img - blur2)

    return np.clip(img, 0, 65535).astype(np.uint16)


def _compute_3x3_matrix(detected, reference):
    import numpy as np

    det_white = detected[18]
    ref_white = reference[18]
    safe_ref = np.where(ref_white > 1e-6, ref_white, 1e-6)
    wp_scale = det_white / safe_ref
    adapted_ref = reference * wp_scale

    D = detected
    I3 = np.eye(3)
    base_weights = np.ones(24)
    base_weights[NEUTRAL_INDICES] = NEUTRAL_WEIGHT
    weights = base_weights.copy()
    M = None

    for iteration in range(max(1, HUBER_ITERATIONS)):
        W = np.diag(weights)
        DtWD = D.T @ W @ D + RIDGE_LAMBDA * I3
        M = np.zeros((3, 3))
        for c in range(3):
            r_c = adapted_ref[:, c]
            e_c = I3[:, c]
            M[c, :] = np.linalg.solve(DtWD, D.T @ W @ r_c + RIDGE_LAMBDA * e_c)
        corrected = (M @ D.T).T
        if iteration < HUBER_ITERATIONS - 1:
            for i in range(24):
                r = np.sqrt(np.sum((corrected[i] - adapted_ref[i]) ** 2))
                huber_w = 1.0 if r <= HUBER_DELTA else HUBER_DELTA / r
                weights[i] = base_weights[i] * huber_w

    for c in range(3):
        rs = M[c, :].sum()
        if abs(rs) > 1e-6:
            M[c, :] /= rs

    return M, wp_scale


def _detect_fabric_boundary(img):
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
    if gray.dtype == np.uint16:
        gray = (gray / 256).astype(np.uint8)

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        edges = cv2.Canny(blurred, 50, 150)
        edges = cv2.dilate(edges, kernel, iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    image_area = h * w
    valid = [c for c in contours if image_area * 0.05 < cv2.contourArea(c) < image_area * 0.95]
    if not valid:
        valid = contours

    largest = max(valid, key=cv2.contourArea)
    x, y, bw, bh = cv2.boundingRect(largest)
    pad = int(min(bw, bh) * 0.03)

    return (max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad))


def load_calibration(batch: str) -> dict:
    """Load calibration.json for a batch folder."""
    cal_path = settings.CAPTURES_DIR / batch / "output" / "calibration.json"
    if not cal_path.exists():
        raise FileNotFoundError(f"calibration.json not found for batch: {batch}")
    return json.loads(cal_path.read_text())


def render_image(batch: str, filename: str, fmt: str = "jpg", crop: bool = True) -> bytes:
    """
    Render a single RAW image using stored calibration parameters.
    Returns encoded image bytes (JPEG or TIFF).
    """
    import cv2
    import numpy as np

    cal = load_calibration(batch)
    raw_dir = settings.CAPTURES_DIR / batch / "raw"
    raw_path = raw_dir / filename
    if not raw_path.exists():
        raise FileNotFoundError(f"RAW file not found: {filename}")

    # Check if this is the top image and a pre-rendered file exists
    stem = raw_path.stem
    if crop:
        cached = settings.CAPTURES_DIR / batch / "output" / "cropped" / f"{stem}.tiff"
    else:
        cached = settings.CAPTURES_DIR / batch / "output" / "calibrated" / f"{stem}.tiff"
    if cached.exists():
        img = cv2.imread(str(cached), cv2.IMREAD_UNCHANGED)
        if fmt == "tiff":
            _, buf = cv2.imencode(".tiff", img)
            return bytes(buf)
        else:
            img_8 = (img / 256).astype(np.uint8) if img.dtype == np.uint16 else img
            _, buf = cv2.imencode(".jpg", img_8, [cv2.IMWRITE_JPEG_QUALITY, 92])
            return bytes(buf)

    # Decode RAW with stored WB
    checker_wb = cal.get("checker_wb")
    matrix = np.array(cal["matrix_3x3"], dtype=np.float64)

    img, _ = _load_raw_linear(raw_path, fixed_wb=checker_wb)
    h, w, _ = img.shape
    flat = img.reshape(-1, 3)
    corrected = (matrix @ flat.T).T.reshape(h, w, 3)
    corrected = np.clip(corrected, 0, 1)

    srgb = _linear_to_srgb(corrected)
    srgb_16 = (srgb * 65535).astype(np.uint16)
    bgr_16 = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)
    bgr_16 = _sharpen_16(bgr_16)

    # Apply crop if requested
    if crop:
        cb = cal["crop_box"]
        bgr_16 = bgr_16[cb["y1"]:cb["y2"], cb["x1"]:cb["x2"]]

    if fmt == "tiff":
        _, buf = cv2.imencode(".tiff", bgr_16)
        return bytes(buf)
    else:
        img_8 = (bgr_16 / 256).astype(np.uint8)
        _, buf = cv2.imencode(".jpg", img_8, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return bytes(buf)


# Singleton
post_capture_service = PostCaptureService()

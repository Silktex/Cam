#!/usr/bin/env python3
"""
Calibration + Crop

Standalone script that takes a batch capture folder with RAW images and
calibration.json, then outputs calibrated + cropped TIFFs to output/cropped.

Input folder structure:
    batch_folder/
        raw/              ← RAW files (*.ARW)
        output/
            calibration.json

Output:
    batch_folder/output/
        cropped/
            *.tiff  (calibrated + cropped)

Usage:
    python calibrate_and_crop.py --batch ~/captures/MALVERN-GREEN
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import cv2
import numpy as np
import rawpy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════
#  RAW PROCESSING HELPERS
# ═════════════════════════════════════════════════════════════════════════

def load_raw_linear(raw_path, fixed_wb=None):
    """Load RAW -> linear float32 RGB (0-1). Returns (image, camera_wb)."""
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


def linear_to_srgb(img):
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055,
    ).clip(0, 1)


def sharpen_16(bgr_16):
    """Two-pass unsharp mask on 16-bit BGR."""
    img = bgr_16.astype(np.float32)
    blur1 = cv2.GaussianBlur(img, (0, 0), sigmaX=0.8)
    img = img + 0.7 * (img - blur1)
    blur2 = cv2.GaussianBlur(img, (0, 0), sigmaX=2.0)
    img = img + 0.3 * (img - blur2)
    return np.clip(img, 0, 65535).astype(np.uint16)


def render_side_image(raw_path, calibration, crop=True):
    """Render a single RAW side image using stored calibration params.
    Returns cropped+calibrated BGR uint16 image."""
    checker_wb = calibration.get("checker_wb")
    matrix = np.array(calibration["matrix_3x3"], dtype=np.float64)

    img, _ = load_raw_linear(raw_path, fixed_wb=checker_wb)
    h, w, _ = img.shape
    flat = img.reshape(-1, 3)
    corrected = (matrix @ flat.T).T.reshape(h, w, 3)
    corrected = np.clip(corrected, 0, 1)

    srgb = linear_to_srgb(corrected)
    srgb_16 = (srgb * 65535).astype(np.uint16)
    bgr_16 = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)
    bgr_16 = sharpen_16(bgr_16)

    if crop:
        cb = calibration["crop_box"]
        bgr_16 = bgr_16[cb["y1"]:cb["y2"], cb["x1"]:cb["x2"]]

    return bgr_16


def save_cropped(image, output_path):
    output_path = Path(output_path).with_suffix(".tiff")
    cv2.imwrite(str(output_path), image)
    return output_path


def calibrate_and_crop_batch(batch_dir):
    """Render all RAW files listed in calibration.json and save cropped TIFFs."""
    batch_dir = Path(batch_dir)
    output_dir = batch_dir / "output"
    raw_dir = batch_dir / "raw"
    cal_path = output_dir / "calibration.json"
    cropped_dir = output_dir / "cropped"

    if not cal_path.exists():
        raise FileNotFoundError(f"calibration.json not found at {cal_path}")
    if not raw_dir.exists():
        raise FileNotFoundError(f"RAW directory not found at {raw_dir}")

    calibration = json.loads(cal_path.read_text())
    log.info(f"  Loaded calibration.json (profile: {calibration.get('profile_name', '?')})")
    log.info(f"  Crop box: {calibration['crop_box']}")
    log.info(f"  RAW files: {calibration['raw_files']}")

    cropped_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for raw_name in calibration["raw_files"]:
        raw_path = raw_dir / raw_name
        if not raw_path.exists():
            log.warning(f"  RAW not found, skipping: {raw_name}")
            continue

        log.info(f"  Rendering + cropping: {raw_name}")
        image = render_side_image(raw_path, calibration, crop=True)
        out_path = cropped_dir / f"{Path(raw_name).stem}.tiff"
        save_cropped(image, out_path)
        saved.append(out_path)

    log.info(f"  Saved {len(saved)} cropped TIFFs -> {cropped_dir}")
    return saved


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate + crop RAWs from a batch capture folder",
    )
    parser.add_argument("--batch", required=True,
                        help="Path to batch folder (contains raw/ and output/)")
    args = parser.parse_args()

    batch_dir = Path(args.batch).expanduser().resolve()
    output_dir = batch_dir / "output"

    log.info("=" * 70)
    log.info("CALIBRATE + CROP")
    log.info(f"  Batch: {batch_dir}")
    log.info("=" * 70)

    log.info("\n" + "=" * 70)
    log.info("CALIBRATION + CROP")
    log.info("=" * 70)
    calibrate_and_crop_batch(batch_dir)

    log.info("\n" + "=" * 70)
    log.info("COMPLETE")
    log.info("=" * 70)
    log.info(f"  Cropped outputs: {output_dir / 'cropped'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
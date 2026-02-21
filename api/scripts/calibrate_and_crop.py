#!/usr/bin/env python3
"""
Calibrate & Crop: Apply a saved checker profile to a batch of RAW images.

Loads detected/reference swatches from an .npz profile, computes the 3x3
color correction matrix, applies it to every RAW in the batch using the
checker's WB, then auto-crops all calibrated images to a square centered
on the detected fabric boundary.

Usage:
    cd api && source .venv/bin/activate
    python scripts/calibrate_and_crop.py \
      --profile media/colorchecker/profiles/CHECKER-17FEB.npz \
      --batch MALVERN-SEAGREEN \
      --crop-size 3000
"""

import argparse
import json
import logging
import sys
from datetime import datetime
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

# ── Constants (same as full_pipeline.py) ─────────────────────────────────

NEUTRAL_INDICES = list(range(18, 24))
LUMA_COEFF = np.array([0.2126, 0.7152, 0.0722])

NEUTRAL_WEIGHT    = 10.0
RIDGE_LAMBDA      = 0.30
HUBER_DELTA       = 0.03
HUBER_ITERATIONS  = 3

MEDIA_DIR = Path(__file__).resolve().parent.parent / "media"
CAPTURES_DIR = MEDIA_DIR / "captures"


# ── RAW loading ──────────────────────────────────────────────────────────

def load_raw_linear(raw_path, fixed_wb=None):
    """Load RAW -> linear float32 RGB (0-1).  Returns (image, camera_wb_raw)."""
    with rawpy.imread(str(raw_path)) as raw:
        camera_wb = list(raw.camera_whitebalance)
        if fixed_wb is not None:
            wb_params = dict(user_wb=fixed_wb, use_camera_wb=False)
        else:
            wb_params = dict(use_camera_wb=True)
        rgb = raw.postprocess(
            **wb_params,
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            output_bps=16,
            output_color=rawpy.ColorSpace.sRGB,
            no_auto_bright=True,
            gamma=(1, 1),
            half_size=False,
            fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
        )
    img = rgb.astype(np.float32) / 65535.0
    return img, camera_wb


def linear_to_srgb(img):
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055,
    ).clip(0, 1)


# ── Calibration math ────────────────────────────────────────────────────

def compute_3x3_matrix(detected, reference):
    """Fit a 3x3 color correction matrix from detected vs reference swatches."""
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

    # Row-sum normalization
    for c in range(3):
        rs = M[c, :].sum()
        if abs(rs) > 1e-6:
            M[c, :] /= rs

    diag = np.diag(M)
    off_diag = np.abs(M - np.diag(diag)).sum()
    log.info(f"  3x3 diagonal: [{diag[0]:.4f}, {diag[1]:.4f}, {diag[2]:.4f}]")
    log.info(f"  Off-diagonal energy: {off_diag:.6f}")
    return M, wp_scale


# ── Auto-crop ────────────────────────────────────────────────────────────

def detect_fabric_boundary(img):
    """Detect fabric boundary using Otsu + morphology + contour."""
    h, w = img.shape[:2]

    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

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

    valid_contours = []
    image_area = h * w
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > image_area * 0.05 and area < image_area * 0.95:
            valid_contours.append(cnt)

    if not valid_contours:
        valid_contours = contours

    largest = max(valid_contours, key=cv2.contourArea)
    x, y, bw, bh = cv2.boundingRect(largest)

    pad = int(min(bw, bh) * 0.03)
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(w, x + bw + pad)
    y2 = min(h, y + bh + pad)

    return (x1, y1, x2, y2)


# ── Steps ────────────────────────────────────────────────────────────────

def step1_calibrate(profile_path, raw_dir, output_dir):
    """Calibrate all RAWs using saved checker profile."""
    log.info("=" * 70)
    log.info("STEP 1: COLOR CALIBRATION (from profile)")
    log.info("=" * 70)

    # Load profile
    profile = np.load(str(profile_path), allow_pickle=True)
    detected = profile['detected_swatches'].astype(np.float64)
    reference = profile['reference_swatches'].astype(np.float64)
    checker_raw_path = Path(str(profile['checker_raw_path']))

    log.info(f"  Profile: {profile_path.name}")
    log.info(f"  Checker RAW: {checker_raw_path.name}")
    log.info(f"  Detected swatches: {detected.shape}")

    # Extract checker WB for consistent processing
    if not checker_raw_path.exists():
        log.error(f"  Checker RAW not found: {checker_raw_path}")
        log.info("  Falling back to camera WB per image")
        checker_wb_raw = None
    else:
        with rawpy.imread(str(checker_raw_path)) as raw:
            checker_wb_raw = list(raw.camera_whitebalance)
        log.info(f"  Checker WB: {checker_wb_raw}")

    # Compute 3x3 matrix
    log.info("\n--- Fitting 3x3 matrix ---")
    matrix, wp_scale = compute_3x3_matrix(detected, reference)

    # Find fabric ARWs
    fabric_arws = sorted(raw_dir.glob("*.ARW"))
    if not fabric_arws:
        fabric_arws = sorted(f for f in raw_dir.iterdir() if f.suffix.lower() in {'.arw', '.cr2', '.nef', '.dng'})
    log.info(f"\n  Fabric RAWs: {len(fabric_arws)}")
    for f in fabric_arws:
        log.info(f"    {f.name}")

    # Calibrate each image
    cal_dir = output_dir / "calibrated"
    cal_dir.mkdir(parents=True, exist_ok=True)

    calibrated_paths = []
    for arw_path in fabric_arws:
        log.info(f"\n--- Calibrating: {arw_path.name} ---")
        img, _ = load_raw_linear(arw_path, fixed_wb=checker_wb_raw)
        log.info(f"  Shape: {img.shape}  (using checker WB)")

        # Apply 3x3 matrix
        h, w, _ = img.shape
        flat = img.reshape(-1, 3)
        corrected = (matrix @ flat.T).T.reshape(h, w, 3)
        corrected = np.clip(corrected, 0, 1)

        # Save 16-bit sRGB TIFF
        srgb = linear_to_srgb(corrected)
        srgb_16 = (srgb * 65535).astype(np.uint16)
        bgr_16 = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)
        tiff_name = arw_path.stem + ".tiff"
        tiff_path = cal_dir / tiff_name
        cv2.imwrite(str(tiff_path), bgr_16)
        calibrated_paths.append(tiff_path)
        log.info(f"  Saved: {tiff_path}")

    log.info(f"\n  Calibration complete: {len(calibrated_paths)} images -> {cal_dir}")
    return matrix, calibrated_paths, checker_wb_raw, [f.name for f in fabric_arws]


def step2_crop(calibrated_paths, output_dir, crop_size):
    """Auto-crop all calibrated images centered on fabric boundary."""
    log.info("\n" + "=" * 70)
    log.info("STEP 2: AUTO-CROP")
    log.info("=" * 70)

    crop_dir = output_dir / "cropped"
    crop_dir.mkdir(parents=True, exist_ok=True)

    # Find the top image
    top_path = None
    for p in calibrated_paths:
        if "_top" in p.name.lower():
            top_path = p
            break

    if top_path is None:
        log.error("  No top image found among calibrated images!")
        return []

    # Load top and detect boundary
    log.info(f"  Detecting fabric boundary on: {top_path.name}")
    top_img = cv2.imread(str(top_path), cv2.IMREAD_UNCHANGED)
    bbox = detect_fabric_boundary(top_img)

    h, w = top_img.shape[:2]
    if bbox is None:
        log.warning("  No boundary detected, using image center")
        cx, cy = w // 2, h // 2
    else:
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        log.info(f"  Detected boundary: ({x1},{y1})->({x2},{y2}), center=({cx},{cy})")
        # Clamp crop_size to detected boundary (anomaly: fabric smaller than requested crop)
        detected_w = x2 - x1
        detected_h = y2 - y1
        detected_size = max(detected_w, detected_h)
        if detected_size < crop_size:
            log.info(f"  Detected region ({detected_size}px) smaller than crop_size ({crop_size}px), shrinking crop")
            crop_size = detected_size

    # Clamp to image dims
    crop_size = min(crop_size, w, h)

    # Compute crop box
    half = crop_size // 2
    crop_x1 = max(0, cx - half)
    crop_y1 = max(0, cy - half)
    crop_x2 = crop_x1 + crop_size
    crop_y2 = crop_y1 + crop_size

    if crop_x2 > w:
        crop_x2 = w
        crop_x1 = max(0, w - crop_size)
    if crop_y2 > h:
        crop_y2 = h
        crop_y1 = max(0, h - crop_size)

    log.info(f"  Crop box: ({crop_x1},{crop_y1})->({crop_x2},{crop_y2})  "
             f"size={crop_x2 - crop_x1}x{crop_y2 - crop_y1}")

    # Apply same crop to all images
    cropped_paths = []
    for cal_path in calibrated_paths:
        img = cv2.imread(str(cal_path), cv2.IMREAD_UNCHANGED)
        cropped = img[crop_y1:crop_y2, crop_x1:crop_x2]
        out_path = crop_dir / cal_path.name
        cv2.imwrite(str(out_path), cropped)
        cropped_paths.append(out_path)
        log.info(f"  Cropped: {cal_path.name} -> {cropped.shape[1]}x{cropped.shape[0]}")

    log.info(f"\n  Crop complete: {len(cropped_paths)} images -> {crop_dir}")

    # Find top image name for calibration.json
    top_name = top_path.stem.split("/")[-1]
    for p in calibrated_paths:
        if "_top" in p.name.lower():
            # Use the original RAW name (replace .tiff with .ARW)
            top_name = p.stem + ".ARW"
            break

    crop_info = {
        "crop_box": {"x1": int(crop_x1), "y1": int(crop_y1), "x2": int(crop_x2), "y2": int(crop_y2)},
        "crop_size": int(crop_x2 - crop_x1),
        "top_image": top_name,
    }
    return cropped_paths, crop_info


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Calibrate & Crop: Apply checker profile to a batch of RAWs",
    )
    parser.add_argument("--profile", required=True,
                        help="Path to .npz checker profile")
    parser.add_argument("--batch", required=True,
                        help="Batch folder name under media/captures/ (e.g. MALVERN-SEAGREEN)")
    parser.add_argument("--output",
                        help="Output directory (default: media/captures/<batch>/output)")
    parser.add_argument("--crop-size", type=int, default=3000,
                        help="Crop size in pixels (default: 3000)")
    args = parser.parse_args()

    profile_path = Path(args.profile).expanduser().resolve()
    raw_dir = CAPTURES_DIR / args.batch / "raw"
    output_dir = Path(args.output).expanduser().resolve() if args.output else CAPTURES_DIR / args.batch / "output"

    if not profile_path.exists():
        log.error(f"Profile not found: {profile_path}")
        return 1
    if not raw_dir.exists():
        log.error(f"RAW folder not found: {raw_dir}")
        return 1

    log.info("=" * 70)
    log.info("CALIBRATE & CROP")
    log.info(f"  Profile:   {profile_path}")
    log.info(f"  Batch:     {args.batch}")
    log.info(f"  RAW dir:   {raw_dir}")
    log.info(f"  Output:    {output_dir}")
    log.info(f"  Crop size: {args.crop_size}")
    log.info("=" * 70)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Calibrate
    matrix, calibrated_paths, checker_wb_raw, raw_files = step1_calibrate(profile_path, raw_dir, output_dir)
    if not calibrated_paths:
        log.error("Calibration failed — no images produced")
        return 1

    # Step 2: Crop
    result = step2_crop(calibrated_paths, output_dir, args.crop_size)
    if not result or not result[0]:
        log.error("Crop failed — no images produced")
        return 1
    cropped_paths, crop_info = result

    # Save calibration.json (matches backend post_capture_service format)
    cal_data = {
        "profile_name": profile_path.name,
        "checker_wb": checker_wb_raw,
        "matrix_3x3": matrix.tolist(),
        "crop_box": crop_info["crop_box"],
        "crop_size": crop_info["crop_size"],
        "raw_files": raw_files,
        "top_image": crop_info["top_image"],
        "created_at": datetime.now().isoformat(),
    }
    cal_json_path = output_dir / "calibration.json"
    cal_json_path.write_text(json.dumps(cal_data, indent=2))
    log.info(f"  Saved calibration.json -> {cal_json_path}")

    # Summary
    log.info("\n" + "=" * 70)
    log.info("COMPLETE")
    log.info("=" * 70)
    log.info(f"  Calibrated: {output_dir / 'calibrated'}  ({len(calibrated_paths)} images)")
    log.info(f"  Cropped:    {output_dir / 'cropped'}  ({len(cropped_paths)} images)")
    return 0


if __name__ == '__main__':
    sys.exit(main())

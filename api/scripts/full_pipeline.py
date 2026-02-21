#!/usr/bin/env python3
"""
Full Pipeline: Calibration -> Crop -> PBR -> Blender

Standalone end-to-end script that processes raw camera images through:
  1. Color calibration (checker-based 3x3 matrix)
  2. Auto-crop (fabric boundary detection)
  3. PBR map generation (photometric stereo)
  4. Blender scene assembly (.blend + renders)

Usage:
    cd api && source .venv/bin/activate
    python scripts/full_pipeline.py \
      --input ~/Downloads/new \
      --checker SINGLE_V2_20260216_160056.ARW \
      --glb ~/Downloads/sofa_web.glb \
      --output ~/Downloads/new/output \
      --crop-size 3200
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import rawpy
from scipy.linalg import lstsq
from scipy.ndimage import convolve as scipy_convolve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

SWATCH_LABELS = [
    'DarkSkin', 'LightSkin', 'BlueSky', 'Foliage', 'BlueFlower', 'BluishGreen',
    'Orange', 'PurplishBlue', 'ModerateRed', 'Purple', 'YellowGreen', 'OrangeYellow',
    'Blue', 'Green', 'Red', 'Yellow', 'Magenta', 'Cyan',
    'White', 'Neutral8', 'Neutral6.5', 'Neutral5', 'Neutral3.5', 'Black',
]
NEUTRAL_INDICES = list(range(18, 24))
LUMA_COEFF = np.array([0.2126, 0.7152, 0.0722])

# Calibration tuning
NEUTRAL_WEIGHT    = 10.0
RIDGE_LAMBDA      = 0.30
HUBER_DELTA       = 0.03
HUBER_ITERATIONS  = 3
WHITE_CLIP_THRESH = 0.95
WB_DRIFT_THRESH   = 0.15

# PBR tuning
SHADOW_THRESHOLD = 0.10
ROUGHNESS_WINDOW = 17          # Window for normal-variance roughness component
DENOISE_KERNEL   = None        # No pre-denoise — preserve fine texture detail
SKIP_SIDES       = {'side_8'}

# Light directions: top = directly above, sides = 45 deg elevation
LIGHT_DIRECTIONS = {
    'top':    [0,  0,  1],
    'side_1': [0,  1,  1],       # front
    'side_2': [-1, 1,  1],       # front-left
    'side_3': [-1, 0,  1],       # left
    'side_4': [-1, -1, 1],       # rear-left
    'side_5': [0,  -1, 1],       # rear
    'side_6': [1,  -1, 1],       # rear-right
    'side_7': [1,  0,  1],       # right
}

# D65 chromatic adaptation (Bradford)
SCENE_WHITE_SRGB = np.array([0.451322, 0.586777, 0.665998])
_SRGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_XYZ_TO_SRGB = np.linalg.inv(_SRGB_TO_XYZ)
_BRADFORD = np.array([
    [ 0.8951000,  0.2664000, -0.1614000],
    [-0.7502000,  1.7135000,  0.0367000],
    [ 0.0389000, -0.0685000,  1.0296000],
])
_BRADFORD_INV = np.linalg.inv(_BRADFORD)
_D65_XYZ = np.array([0.95047, 1.00000, 1.08883])

BLENDER_PATH = "/Applications/Blender.app/Contents/MacOS/Blender"


# =========================================================================
#  STEP 1: COLOR CALIBRATION  (from test_calibration_seagreen.py)
# =========================================================================

def luma(rgb):
    if rgb.ndim == 1:
        return rgb @ LUMA_COEFF
    return rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


def linear_to_srgb(img):
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055,
    ).clip(0, 1)


def load_raw_linear(raw_path, fixed_wb=None):
    """Load RAW -> linear float32 RGB (0-1).  Returns (image, camera_wb_raw).
    If fixed_wb is given (raw [R,G,B,G2] multipliers), use that instead of
    per-image camera WB.  This keeps all images in the same color space."""
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


def detect_swatches(checker_img):
    import colour
    from colour_checker_detection import detect_colour_checkers_segmentation

    results = list(detect_colour_checkers_segmentation(checker_img, additional_data=True))
    if not results:
        return None, None

    detected = results[0].values[0].copy()
    if detected.shape[0] != 24:
        log.error(f"  Expected 24 swatches, got {detected.shape[0]}")
        return None, None

    cc = colour.CCS_COLOURCHECKERS['ColorChecker24 - After November 2014']
    reference = colour.XYZ_to_RGB(
        colour.xyY_to_XYZ(list(cc.data.values())),
        'sRGB', cc.illuminant, apply_cctf_encoding=False,
    )
    return detected, reference


def auto_fix_serpentine(detected, reference):
    detected = detected.copy()
    for row in range(4):
        s, e = row * 6, row * 6 + 6
        det_row = detected[s:e]
        ref_row = reference[s:e]
        de_fwd = np.mean(np.sqrt(np.sum((det_row - ref_row) ** 2, axis=1)))
        de_rev = np.mean(np.sqrt(np.sum((det_row[::-1] - ref_row) ** 2, axis=1)))
        if de_rev < de_fwd * 0.7:
            detected[s:e] = det_row[::-1]
            log.info(f"  Row {row} auto-reversed (dE fwd={de_fwd:.4f} rev={de_rev:.4f})")
    return detected


def quality_gates(detected):
    warnings, reshoot = [], []
    white = detected[18]
    for c, ch in enumerate(['R', 'G', 'B']):
        if white[c] > WHITE_CLIP_THRESH:
            reshoot.append(f"White patch {ch}={white[c]:.4f} > {WHITE_CLIP_THRESH}")
    neutral_luma = [luma(detected[i]) for i in NEUTRAL_INDICES]
    is_monotonic = all(neutral_luma[i] >= neutral_luma[i + 1] for i in range(5))
    if not is_monotonic:
        reshoot.append(f"Neutral row NOT monotonic: {[f'{v:.4f}' for v in neutral_luma]}")
    return len(reshoot) == 0, warnings, reshoot


def compute_3x3_matrix(detected, reference):
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
    residuals = np.zeros(24)

    for iteration in range(max(1, HUBER_ITERATIONS)):
        W = np.diag(weights)
        DtWD = D.T @ W @ D + RIDGE_LAMBDA * I3
        M = np.zeros((3, 3))
        for c in range(3):
            r_c = adapted_ref[:, c]
            e_c = I3[:, c]
            M[c, :] = np.linalg.solve(DtWD, D.T @ W @ r_c + RIDGE_LAMBDA * e_c)
        corrected = (M @ D.T).T
        for i in range(24):
            residuals[i] = np.sqrt(np.sum((corrected[i] - adapted_ref[i]) ** 2))
        if iteration < HUBER_ITERATIONS - 1:
            for i in range(24):
                r = residuals[i]
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
    return M, wp_scale, adapted_ref, {'residuals': residuals}


def step1_calibrate(input_dir, checker_name, output_dir):
    """Color-calibrate all fabric ARWs using the checker image."""
    log.info("=" * 70)
    log.info("STEP 1: COLOR CALIBRATION")
    log.info("=" * 70)

    cal_dir = output_dir / "calibrated"
    cal_dir.mkdir(parents=True, exist_ok=True)

    checker_path = input_dir / checker_name
    if not checker_path.exists():
        log.error(f"Checker not found: {checker_path}")
        return None, [], None, []

    # Find fabric ARWs (everything except the checker)
    all_arws = sorted(input_dir.glob("*.ARW"))
    fabric_arws = [f for f in all_arws if f.name != checker_name]
    log.info(f"  Checker: {checker_name}")
    log.info(f"  Fabric ARWs: {len(fabric_arws)}")
    for f in fabric_arws:
        log.info(f"    {f.name}")

    # Load checker with its own camera WB — extract raw WB for reuse
    log.info("\n--- Loading checker ---")
    checker_img, checker_wb_raw = load_raw_linear(checker_path)
    log.info(f"  Shape: {checker_img.shape}")
    log.info(f"  Camera WB raw: {checker_wb_raw}")

    # Detect swatches
    log.info("\n--- Detecting swatches ---")
    detected, reference = detect_swatches(checker_img)
    if detected is None:
        log.error("  No checker detected!")
        return None, [], None, []

    detected = auto_fix_serpentine(detected, reference)
    gates_ok, gate_warnings, reshoot_reasons = quality_gates(detected)
    for r in reshoot_reasons:
        log.error(f"  RESHOOT: {r}")
    if not gates_ok:
        log.warning("  Quality gates FAILED -- continuing anyway")

    # Fit matrix
    log.info("\n--- Fitting 3x3 matrix ---")
    matrix, wp_scale, adapted_ref, diagnostics = compute_3x3_matrix(detected, reference)

    # Calibrate each fabric image — use CHECKER's WB so all images share
    # the same color space.  Per-image camera WB would neutralize fabric color.
    calibrated_paths = []
    for arw_path in fabric_arws:
        log.info(f"\n--- Calibrating: {arw_path.name} ---")
        img, fab_wb_raw = load_raw_linear(arw_path, fixed_wb=checker_wb_raw)
        log.info(f"  Shape: {img.shape}  (using checker WB)")

        # Apply 3x3 matrix (no WB shift needed — same WB as checker)
        h, w, _ = img.shape
        flat = img.reshape(-1, 3)
        corrected = (matrix @ flat.T).T.reshape(h, w, 3)
        corrected = np.clip(corrected, 0, 1)

        # Save 16-bit sRGB TIFF
        srgb = linear_to_srgb(corrected)
        srgb_16 = (srgb * 65535).astype(np.uint16)
        lin_bgr = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)
        tiff_name = arw_path.stem + ".tiff"
        tiff_path = cal_dir / tiff_name
        cv2.imwrite(str(tiff_path), lin_bgr)
        calibrated_paths.append(tiff_path)
        log.info(f"  Saved: {tiff_path}")

    log.info(f"\n  Calibration complete: {len(calibrated_paths)} images -> {cal_dir}")
    return matrix, calibrated_paths, checker_wb_raw, [f.name for f in fabric_arws]


# =========================================================================
#  STEP 2: AUTO-CROP  (from crop_service.py _detect_fabric_boundary)
# =========================================================================

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


def step2_crop(calibrated_paths, output_dir, crop_size):
    """Auto-crop all calibrated images to crop_size x crop_size centered on fabric."""
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

    # Compute crop box centered on detected region
    half = crop_size // 2
    crop_x1 = max(0, cx - half)
    crop_y1 = max(0, cy - half)
    crop_x2 = crop_x1 + crop_size
    crop_y2 = crop_y1 + crop_size

    # Clamp to image bounds
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
            top_name = p.stem + ".ARW"
            break

    crop_info = {
        "crop_box": {"x1": int(crop_x1), "y1": int(crop_y1), "x2": int(crop_x2), "y2": int(crop_y2)},
        "crop_size": int(crop_x2 - crop_x1),
        "top_image": top_name,
    }
    return cropped_paths, crop_info


# =========================================================================
#  STEP 2b: EDGE DETECTION CHECK  (tiling seam visibility)
# =========================================================================

def step2b_edge_check(cropped_paths, output_dir):
    """Run edge detection on cropped images to check for tiling seam visibility.

    Produces per-image:
      - Canny edge map
      - 2x2 tiled preview (shows where seams will appear)
      - Border vs interior edge energy comparison

    A high border/interior ratio means visible seams when the texture tiles.
    """
    log.info("\n" + "=" * 70)
    log.info("STEP 2b: EDGE DETECTION CHECK (tiling seams)")
    log.info("=" * 70)

    edge_dir = output_dir / "edge_check"
    edge_dir.mkdir(parents=True, exist_ok=True)

    # Find the top image (primary albedo — most important for seam visibility)
    top_path = None
    for p in cropped_paths:
        if "_top" in p.name.lower():
            top_path = p
            break
    if top_path is None:
        top_path = cropped_paths[0]

    results = []
    for fpath in cropped_paths:
        img = cv2.imread(str(fpath), cv2.IMREAD_UNCHANGED)
        if img is None:
            continue

        h, w = img.shape[:2]
        is_top = (fpath == top_path)
        label = "TOP" if is_top else fpath.stem.split("_")[-1]

        # Convert to 8-bit grayscale for edge detection
        if img.dtype == np.uint16:
            img8 = (img / 256).astype(np.uint8)
        else:
            img8 = img
        if len(img8.shape) == 3:
            gray = cv2.cvtColor(img8, cv2.COLOR_BGR2GRAY)
        else:
            gray = img8

        # Canny edge detection
        edges = cv2.Canny(gray, 50, 150)

        # Save edge map
        edge_path = edge_dir / f"{fpath.stem}_edges.png"
        cv2.imwrite(str(edge_path), edges)

        # ── Border vs interior edge energy ──
        border_w = max(16, w // 64)  # ~32px border strip
        # Four border strips
        top_strip = edges[:border_w, :]
        bot_strip = edges[-border_w:, :]
        left_strip = edges[:, :border_w]
        right_strip = edges[:, -border_w:]
        # Interior (excluding borders)
        interior = edges[border_w:-border_w, border_w:-border_w]

        border_energy = np.mean(np.concatenate([
            top_strip.ravel(), bot_strip.ravel(),
            left_strip.ravel(), right_strip.ravel(),
        ]))
        interior_energy = np.mean(interior)
        ratio = border_energy / max(interior_energy, 1e-6)

        # ── Cross-border discontinuity (how different are opposite edges) ──
        # Top row vs bottom row
        tb_diff = np.mean(np.abs(gray[0, :].astype(float) - gray[-1, :].astype(float)))
        # Left col vs right col
        lr_diff = np.mean(np.abs(gray[:, 0].astype(float) - gray[:, -1].astype(float)))
        seam_score = (tb_diff + lr_diff) / 2.0

        results.append({
            'name': fpath.stem,
            'label': label,
            'border_energy': border_energy,
            'interior_energy': interior_energy,
            'ratio': ratio,
            'tb_diff': tb_diff,
            'lr_diff': lr_diff,
            'seam_score': seam_score,
            'is_top': is_top,
        })

        log.info(f"  {label:>8s}: border={border_energy:.1f} interior={interior_energy:.1f} "
                 f"ratio={ratio:.2f}  seam_score={seam_score:.1f} "
                 f"(TB={tb_diff:.1f} LR={lr_diff:.1f})")

        # ── 2x2 tiled preview (only for top image) ──
        if is_top:
            # Downscale for preview
            preview_size = min(512, w)
            small = cv2.resize(img8, (preview_size, preview_size))
            tiled = np.vstack([
                np.hstack([small, small]),
                np.hstack([small, small]),
            ])
            # Draw red lines at seam positions
            ph, pw = tiled.shape[:2]
            if len(tiled.shape) == 2:
                tiled = cv2.cvtColor(tiled, cv2.COLOR_GRAY2BGR)
            cv2.line(tiled, (pw // 2, 0), (pw // 2, ph), (0, 0, 255), 2)
            cv2.line(tiled, (0, ph // 2), (pw, ph // 2), (0, 0, 255), 2)
            cv2.putText(tiled, f"seam={seam_score:.1f}", (10, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            tiled_path = edge_dir / "tiled_2x2_preview.jpg"
            cv2.imwrite(str(tiled_path), tiled, [cv2.IMWRITE_JPEG_QUALITY, 95])
            log.info(f"    Saved tiled preview: {tiled_path.name}")

            # Also save edges tiled
            edges_small = cv2.resize(edges, (preview_size, preview_size))
            edges_tiled = np.vstack([
                np.hstack([edges_small, edges_small]),
                np.hstack([edges_small, edges_small]),
            ])
            edges_tiled_bgr = cv2.cvtColor(edges_tiled, cv2.COLOR_GRAY2BGR)
            cv2.line(edges_tiled_bgr, (pw // 2, 0), (pw // 2, ph), (0, 0, 255), 2)
            cv2.line(edges_tiled_bgr, (0, ph // 2), (pw, ph // 2), (0, 0, 255), 2)
            edges_tiled_path = edge_dir / "tiled_2x2_edges.jpg"
            cv2.imwrite(str(edges_tiled_path), edges_tiled_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
            log.info(f"    Saved tiled edges: {edges_tiled_path.name}")

    # Summary
    if results:
        top_result = next((r for r in results if r['is_top']), results[0])
        log.info(f"\n  SEAM SUMMARY (top image):")
        log.info(f"    Seam score:     {top_result['seam_score']:.1f}  "
                 f"(0=perfect tile, >20=visible seam)")
        log.info(f"    TB discontinuity: {top_result['tb_diff']:.1f}")
        log.info(f"    LR discontinuity: {top_result['lr_diff']:.1f}")
        log.info(f"    Border/interior:  {top_result['ratio']:.2f}")
        if top_result['seam_score'] > 20:
            log.warning("    WARNING: High seam score — tiling will show visible edges")
        else:
            log.info("    OK: Low seam score — tiling should be relatively smooth")

    log.info(f"\n  Edge check outputs -> {edge_dir}")
    return results


# =========================================================================
#  STEP 2c: MAKE TILEABLE  (offset-and-crossfade)
# =========================================================================

def make_tileable(img, blend_px=256):
    """Make an image seamlessly tileable using offset-and-crossfade.

    1. Shift image by half in both axes (brings edges to center).
    2. Blend the resulting center seams with a smooth cosine mask.

    Works on uint8, uint16, or float images, any number of channels.
    """
    h, w = img.shape[:2]
    is_color = img.ndim == 3

    # Work in float64 for blending precision
    orig_dtype = img.dtype
    if orig_dtype == np.uint8:
        max_val = 255.0
    elif orig_dtype == np.uint16:
        max_val = 65535.0
    else:
        max_val = 1.0

    img_f = img.astype(np.float64) / max_val

    # Shift by half (wrapping) — seams now at center
    shifted = np.roll(np.roll(img_f, h // 2, axis=0), w // 2, axis=1)

    # Build cosine blend mask: 1 at center seams, 0 at edges
    # Horizontal ramp: cosine that peaks at w//2
    x = np.arange(w, dtype=np.float64)
    cx = w / 2.0
    # Cosine window centered at cx, width = 2*blend_px
    # cos goes from 1 (at cx) to 0 (at cx ± blend_px)
    hx = np.clip((1.0 + np.cos(np.pi * (x - cx) / blend_px)) / 2.0, 0, 1)
    # Clamp to zero outside the blend region
    hx[np.abs(x - cx) > blend_px] = 0.0

    # Vertical ramp
    y = np.arange(h, dtype=np.float64)
    cy = h / 2.0
    hy = np.clip((1.0 + np.cos(np.pi * (y - cy) / blend_px)) / 2.0, 0, 1)
    hy[np.abs(y - cy) > blend_px] = 0.0

    # 2D mask: max of horizontal and vertical blend (covers both cross seams)
    mask_h = hx[np.newaxis, :]                  # (1, W)
    mask_v = hy[:, np.newaxis]                  # (H, 1)
    # Combine: blend where EITHER seam is present
    # Use: alpha = 1 - (1-mask_h)*(1-mask_v)  (union of blend zones)
    mask = 1.0 - (1.0 - mask_h) * (1.0 - mask_v)

    if is_color:
        mask = mask[:, :, np.newaxis]

    # Blend: shifted image in seam zone, original elsewhere
    blended = shifted * (1.0 - mask) + img_f * mask

    # Convert back
    result = np.clip(blended * max_val, 0, max_val).astype(orig_dtype)
    return result


def step2c_make_tileable(cropped_paths, output_dir, blend_px=256):
    """Apply tileable blending to all cropped images.

    Overwrites the cropped files so downstream PBR uses tileable textures.
    Also saves originals to cropped_originals/ for reference.
    """
    log.info("\n" + "=" * 70)
    log.info("STEP 2c: MAKE TILEABLE (offset-and-crossfade)")
    log.info("=" * 70)

    backup_dir = output_dir / "cropped_originals"
    backup_dir.mkdir(parents=True, exist_ok=True)

    tileable_paths = []
    for fpath in cropped_paths:
        img = cv2.imread(str(fpath), cv2.IMREAD_UNCHANGED)
        if img is None:
            log.error(f"  Failed to load: {fpath}")
            continue

        # Backup original
        backup_path = backup_dir / fpath.name
        cv2.imwrite(str(backup_path), img)

        # Make tileable
        tileable = make_tileable(img, blend_px=blend_px)

        # Overwrite cropped file
        cv2.imwrite(str(fpath), tileable)
        tileable_paths.append(fpath)
        log.info(f"  Tileable: {fpath.name}  (blend={blend_px}px)")

    log.info(f"\n  Tileable complete: {len(tileable_paths)} images")
    log.info(f"  Originals backed up -> {backup_dir}")
    return tileable_paths


# =========================================================================
#  STEP 3: PBR GENERATION  (from test_pbr_standalone.py)
# =========================================================================

def denoise(img):
    if DENOISE_KERNEL is None:
        return img
    return cv2.GaussianBlur(img, DENOISE_KERNEL, 0)


def detect_shadows(images, threshold=SHADOW_THRESHOLD):
    grays = []
    for img in images:
        if img.ndim == 3:
            grays.append(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32))
        else:
            grays.append(img.astype(np.float32))
    mean_intensity = np.mean(grays, axis=0)
    max_val = np.max(mean_intensity)
    if max_val < 1e-8:
        return np.ones(mean_intensity.shape, dtype=bool)
    return mean_intensity > (threshold * max_val)


def photometric_stereo_grayscale(images, light_dirs):
    """Photometric stereo on grayscale images.

    Returns (normals, albedo, lambert_residual):
      normals:  (H, W, 3) unit normals
      albedo:   (H, W) scalar albedo
      residual: (H, W) RMS Lambert fit residual per pixel —
                physically measures how much reality deviates from Lambert.
    """
    n = len(images)
    h, w = images[0].shape

    shadow_mask = detect_shadows(images)

    I = np.stack(images, axis=0).astype(np.float32)
    L = light_dirs.astype(np.float32)
    I_flat = I.reshape(n, -1)  # (N, H*W)

    G, _, _, _ = lstsq(L, I_flat)  # (3, H*W)

    rho = np.linalg.norm(G, axis=0)
    rho_safe = np.where(rho == 0, 1e-8, rho)

    normals = (G / rho_safe.reshape(1, -1)).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)

    norm_lengths = np.linalg.norm(normals, axis=2, keepdims=True)
    norm_lengths[norm_lengths == 0] = 1e-8
    normals = normals / norm_lengths

    # Lambert prediction: Î = rho * max(0, N·L)
    N_flat = normals.reshape(-1, 3)            # (H*W, 3)
    NdotL = np.clip(N_flat @ L.T, 0, None)    # (H*W, N)
    I_predicted = rho_safe.reshape(-1, 1) * NdotL  # (H*W, N)
    residual = np.sqrt(np.mean((I_flat.T - I_predicted) ** 2, axis=1))  # (H*W,)
    # Normalize by albedo to get relative residual
    residual = residual / rho_safe
    residual = np.nan_to_num(residual, nan=0.0, posinf=0.0, neginf=0.0)

    normals[~shadow_mask] = [0, 0, 1]
    residual_map = residual.reshape(h, w)
    residual_map[~shadow_mask] = 0.0
    rho = rho.reshape(h, w)
    return normals, rho, residual_map


def photometric_stereo_color(images, light_dirs):
    """Photometric stereo on color images.

    Returns (normals, albedo, lambert_residual).
    """
    n = len(images)
    h, w, channels = images[0].shape

    shadow_mask = detect_shadows(images)

    I = np.array(
        [img.astype(np.float32).reshape(-1, channels) for img in images]
    ).transpose(1, 0, 2)  # (H*W, N, C)
    L = light_dirs.astype(np.float32)

    I_intensity = np.mean(I, axis=2)  # (H*W, N)
    G_intensity, _, _, _ = lstsq(L, I_intensity.T)  # (3, H*W)

    albedo_intensity = np.linalg.norm(G_intensity, axis=0)
    albedo_safe = np.where(albedo_intensity == 0, 1e-8, albedo_intensity)

    normals = (G_intensity / albedo_safe).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)

    norm_lengths = np.linalg.norm(normals, axis=2, keepdims=True)
    norm_lengths[norm_lengths == 0] = 1e-8
    normals = normals / norm_lengths

    # Lambert residual (on intensity channel)
    N_flat = normals.reshape(-1, 3)
    NdotL = np.clip(N_flat @ L.T, 0, None)        # (H*W, N)
    I_predicted = albedo_safe.reshape(-1, 1) * NdotL
    residual = np.sqrt(np.mean((I_intensity - I_predicted) ** 2, axis=1))
    residual = residual / albedo_safe
    residual = np.nan_to_num(residual, nan=0.0, posinf=0.0, neginf=0.0)

    normals[~shadow_mask] = [0, 0, 1]
    residual_map = residual.reshape(h, w)
    residual_map[~shadow_mask] = 0.0
    rho = albedo_intensity.reshape(h, w)
    return normals, rho, residual_map


def compute_roughness(normals, lambert_residual, window_size=ROUGHNESS_WINDOW):
    """Compute physically-based roughness from two complementary signals:

    1. Lambert residual (per-pixel): How much reality deviates from perfect
       Lambertian reflectance.  Directly measures non-Lambert scattering
       (specular micro-facets, subsurface, fiber fuzz).  This is the
       PHYSICAL roughness — high residual = rough surface.

    2. Normal variance (local window): How much surface normals vary in a
       neighborhood.  Captures STRUCTURAL roughness — fabric weave pattern,
       wrinkles, macro-texture.

    The two are combined: roughness = sqrt(residual * normal_var) (geometric
    mean preserves both signals).  Result is normalized to 0-1 using robust
    percentiles (no hardcoded floor or gamma).
    """
    h, w = normals.shape[:2]

    # ── Component 1: Lambert residual (physical micro-roughness) ──
    # Already per-pixel, relative to albedo.  Smooth to reduce noise.
    residual = scipy_convolve(
        lambert_residual.astype(np.float32),
        np.ones((5, 5)) / 25.0, mode='reflect'
    )

    # ── Component 2: Normal variance (structural macro-roughness) ──
    normal_var = np.zeros((h, w), dtype=np.float32)
    kernel = np.ones((window_size, window_size)) / (window_size * window_size)
    for c in range(3):
        mean = scipy_convolve(normals[:, :, c], kernel, mode='reflect')
        sq_diff = (normals[:, :, c] - mean) ** 2
        normal_var += scipy_convolve(sq_diff, kernel, mode='reflect')

    # ── Normalize each component to 0-1 using robust percentiles ──
    def robust_normalize(arr):
        p2 = np.percentile(arr, 2)
        p98 = np.percentile(arr, 98)
        if p98 - p2 < 1e-8:
            return np.ones_like(arr) * 0.5
        normed = (arr - p2) / (p98 - p2)
        return np.clip(normed, 0, 1)

    r_norm = robust_normalize(residual)
    v_norm = robust_normalize(normal_var)

    # ── Combine: geometric mean ──
    # sqrt(A * B) gives equal weight to physical and structural components.
    # Both must be high for roughness to be high.
    roughness = np.sqrt(r_norm * v_norm)

    # Final normalize to use full 0-1 range
    roughness = robust_normalize(roughness)

    log.info(f"  Roughness (physical):")
    log.info(f"    Lambert residual:  p50={np.median(residual):.4f}  p95={np.percentile(residual, 95):.4f}")
    log.info(f"    Normal variance:   p50={np.median(normal_var):.6f}  p95={np.percentile(normal_var, 95):.6f}")
    log.info(f"    Combined:  range=[{roughness.min():.3f}, {roughness.max():.3f}]  "
             f"mean={roughness.mean():.3f}  p50={np.median(roughness):.3f}")

    return (roughness * 255).clip(0, 255).astype(np.uint8)


def compute_height_map(normals):
    nz = normals[:, :, 2]
    nz_safe = np.where(np.abs(nz) < 1e-8, 1e-8, nz)
    p = normals[:, :, 0] / nz_safe  # dz/dx
    q = normals[:, :, 1] / nz_safe  # dz/dy

    h, w = p.shape

    u = np.fft.fftfreq(w).reshape(1, w).astype(np.float64)
    v = np.fft.fftfreq(h).reshape(h, 1).astype(np.float64)

    Px = np.fft.fft2(p.astype(np.float64))
    Qx = np.fft.fft2(q.astype(np.float64))

    denom = u ** 2 + v ** 2
    denom[0, 0] = 1.0

    Z = (-1j * u * Px - 1j * v * Qx) / denom
    Z[0, 0] = 0

    height_map = np.real(np.fft.ifft2(Z))
    height_map = np.nan_to_num(height_map, nan=0.0, posinf=0.0, neginf=0.0)

    return cv2.normalize(
        height_map.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX
    ).astype(np.uint8)


def compute_ao(height_map, normals, num_scales=4):
    """Compute ambient occlusion from height map and normals.

    Two components combined:
      1. Multi-scale height occlusion — at each scale, pixels lower than their
         neighborhood average are more occluded.
      2. Cavity map — Laplacian of the height map.  Concave = occluded.
      3. Normal-based occlusion — steep normals = occluded.

    Result: 0 = fully occluded (black), 1 = fully exposed (white).
    Returned as uint8 (0-255).
    """
    hf = height_map.astype(np.float32) / 255.0

    # Multi-scale height occlusion
    occlusion_scales = []
    for i in range(num_scales):
        radius = 3 + i * 4
        ksize = radius * 2 + 1
        local_mean = cv2.GaussianBlur(hf, (ksize, ksize), 0)
        diff = np.clip(local_mean - hf, 0, None)
        occlusion_scales.append(diff)

    weights = [1.0, 0.7, 0.5, 0.3][:num_scales]
    total_weight = sum(weights)
    height_occ = sum(w * s for w, s in zip(weights, occlusion_scales)) / total_weight

    # Cavity from Laplacian
    laplacian = cv2.Laplacian(hf, cv2.CV_32F, ksize=5)
    laplacian = cv2.GaussianBlur(laplacian, (5, 5), 0)
    cavity = np.clip(-laplacian, 0, None)

    # Normal-based occlusion
    nz = normals[:, :, 2]
    normal_occ = np.clip(1.0 - nz, 0, 1) ** 2

    def robust_norm(arr):
        p1, p99 = np.percentile(arr, 1), np.percentile(arr, 99)
        if p99 - p1 < 1e-8:
            return np.zeros_like(arr)
        return np.clip((arr - p1) / (p99 - p1), 0, 1)

    height_occ = robust_norm(height_occ)
    cavity = robust_norm(cavity)
    normal_occ = robust_norm(normal_occ)

    combined_occ = 0.5 * height_occ + 0.3 * cavity + 0.2 * normal_occ
    combined_occ = robust_norm(combined_occ)

    ao = np.power(1.0 - combined_occ, 0.7)

    log.info(f"  AO: min={ao.min():.3f} max={ao.max():.3f} mean={ao.mean():.3f}")

    return (np.clip(ao, 0, 1) * 255).astype(np.uint8)


def normalize_albedo(img, target_percentile=99.5, target_value=0.85):
    """Normalize albedo brightness, preserving original dtype precision."""
    if img.dtype == np.uint16:
        max_val = 65535.0
    elif img.dtype == np.uint8:
        max_val = 255.0
    else:
        max_val = 1.0

    img_f = img.astype(np.float32) / max_val
    p = np.percentile(img_f, target_percentile)
    if p < 1e-8:
        return img
    scale = target_value / p
    normalized = np.clip(img_f * scale, 0, 1)
    log.info(f"  Albedo normalized: p{target_percentile}={p:.4f} -> "
             f"{target_value}, scale={scale:.2f}x")

    # Return in original dtype
    return np.clip(normalized * max_val, 0, max_val).astype(img.dtype)


def visualize_normals(normals):
    return ((normals + 1.0) / 2.0 * 255.0).clip(0, 255).astype(np.uint8)


def save_16bit(img, path):
    path = Path(path).with_suffix('.tiff')
    if img.dtype == np.uint8:
        img16 = img.astype(np.uint16) * 257  # 0-255 -> 0-65535
    elif img.dtype == np.uint16:
        img16 = img
    elif img.dtype in (np.float32, np.float64):
        img16 = np.clip(img * 65535, 0, 65535).astype(np.uint16)
    else:
        img16 = img.astype(np.uint16)
    cv2.imwrite(str(path), img16)
    return path


def compute_d65_adaptation(scene_white_srgb):
    source_xyz = _SRGB_TO_XYZ @ scene_white_srgb
    source_xyz = source_xyz / source_xyz[1]

    cone_src = _BRADFORD @ source_xyz
    cone_dst = _BRADFORD @ _D65_XYZ

    scale = cone_dst / cone_src
    adapt_xyz = _BRADFORD_INV @ np.diag(scale) @ _BRADFORD

    combined = _XYZ_TO_SRGB @ adapt_xyz @ _SRGB_TO_XYZ
    log.info("  D65 adaptation matrix:")
    for r, ch in enumerate(['R', 'G', 'B']):
        log.info(f"    {ch}: [{combined[r, 0]:+.4f}  {combined[r, 1]:+.4f}  {combined[r, 2]:+.4f}]")
    return combined


def apply_d65_adaptation(img):
    """Apply D65 Bradford adaptation to a BGR uint8/uint16 image."""
    M = compute_d65_adaptation(SCENE_WHITE_SRGB)

    orig_dtype = img.dtype
    if orig_dtype == np.uint16:
        max_val = 65535.0
    elif orig_dtype == np.uint8:
        max_val = 255.0
    else:
        max_val = 1.0

    img_f = img.astype(np.float64) / max_val
    rgb = img_f[:, :, ::-1]  # BGR -> RGB

    h, w, _ = rgb.shape
    pixels = rgb.reshape(-1, 3)

    adapted = (M @ pixels.T).T
    adapted = np.clip(adapted, 0, 1)

    log.info(f"  D65 applied ({w}x{h}): "
             f"R {pixels[:, 0].mean():.4f}->{adapted[:, 0].mean():.4f}  "
             f"G {pixels[:, 1].mean():.4f}->{adapted[:, 1].mean():.4f}  "
             f"B {pixels[:, 2].mean():.4f}->{adapted[:, 2].mean():.4f}")

    adapted_bgr = adapted.reshape(h, w, 3)[:, :, ::-1]  # RGB -> BGR
    return np.clip(adapted_bgr * max_val, 0, max_val).astype(orig_dtype)


def step3_pbr(cropped_paths, output_dir):
    """Generate PBR maps from cropped images."""
    log.info("\n" + "=" * 70)
    log.info("STEP 3: PBR GENERATION")
    log.info("=" * 70)

    gray_dir = output_dir / "pbr" / "grayscale"
    color_dir = output_dir / "pbr" / "colored"
    gray_dir.mkdir(parents=True, exist_ok=True)
    color_dir.mkdir(parents=True, exist_ok=True)

    # Classify images by position
    top_color = None
    top_gray = None
    side_colors = []
    side_grays = []
    side_light_dirs = []
    side_names = []

    for fpath in sorted(cropped_paths):
        fname = fpath.name.lower()

        matched_pos = None
        matched_dir = None
        for pos, direction in LIGHT_DIRECTIONS.items():
            if pos in fname or pos.replace('_', '') in fname:
                matched_pos = pos
                matched_dir = direction
                break

        if matched_pos is None:
            is_skipped = any(s in fname or s.replace('_', '') in fname for s in SKIP_SIDES)
            if is_skipped:
                log.info(f"    SKIP (excluded): {fpath.name}")
            else:
                log.info(f"    SKIP (no match): {fpath.name}")
            continue

        img = cv2.imread(str(fpath), cv2.IMREAD_UNCHANGED)
        if img is None:
            log.error(f"    FAIL to load: {fpath.name}")
            continue

        if img.ndim == 3 and img.shape[2] == 4:
            img = img[:, :, :3]

        img = denoise(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

        if matched_pos == 'top':
            top_color = img
            top_gray = gray
            log.info(f"    TOP (albedo):  {fpath.name}  shape={img.shape} dtype={img.dtype}")
        else:
            side_colors.append(img)
            side_grays.append(gray)
            side_light_dirs.append(matched_dir)
            side_names.append(matched_pos)
            log.info(f"    SIDE {matched_pos:>6s}:  {fpath.name}  shape={img.shape}")

    if top_color is None or top_gray is None:
        log.error("  No top image found!")
        return None
    if len(side_grays) < 3:
        log.error(f"  Need >=3 side images, found {len(side_grays)}")
        return None

    # Normalize light directions
    L = np.array(side_light_dirs, dtype=np.float32)
    norms = np.linalg.norm(L, axis=1, keepdims=True)
    norms[norms == 0] = 1e-8
    L /= norms

    log.info(f"  Loaded: top=YES, sides={len(side_grays)}")

    # ── Grayscale PBR ──
    log.info("\n" + "-" * 60)
    log.info("GENERATING GRAYSCALE PBR")
    log.info("-" * 60)

    gray_albedo = normalize_albedo(top_gray)
    gray_normals, gray_rho, gray_residual = photometric_stereo_grayscale(side_grays, L)
    gray_roughness = compute_roughness(gray_normals, gray_residual)
    gray_height = compute_height_map(gray_normals)
    gray_ao = compute_ao(gray_height, gray_normals)
    gray_normals_rgb = visualize_normals(gray_normals)

    save_16bit(gray_albedo, gray_dir / "albedo.tiff")
    normals_bgr = cv2.cvtColor(gray_normals_rgb, cv2.COLOR_RGB2BGR)
    save_16bit(normals_bgr, gray_dir / "normals.tiff")
    save_16bit(gray_roughness, gray_dir / "roughness.tiff")
    save_16bit(gray_height, gray_dir / "height_map.tiff")
    save_16bit(gray_ao, gray_dir / "ao.tiff")
    log.info(f"  Saved grayscale PBR -> {gray_dir}")

    # ── Colored PBR ──
    log.info("\n" + "-" * 60)
    log.info("GENERATING COLORED PBR")
    log.info("-" * 60)

    color_albedo = normalize_albedo(top_color)
    color_normals, color_rho, color_residual = photometric_stereo_color(side_colors, L)
    color_roughness = compute_roughness(color_normals, color_residual)
    color_height = compute_height_map(color_normals)
    color_ao = compute_ao(color_height, color_normals)
    color_normals_rgb = visualize_normals(color_normals)

    # Calibrated albedo is already color-corrected by the 3x3 checker matrix.
    # No additional D65 adaptation needed (would double-correct).
    save_16bit(color_albedo, color_dir / "albedo.tiff")

    color_normals_bgr = cv2.cvtColor(color_normals_rgb, cv2.COLOR_RGB2BGR)
    save_16bit(color_normals_bgr, color_dir / "normals.tiff")
    save_16bit(color_roughness, color_dir / "roughness.tiff")
    save_16bit(color_height, color_dir / "height_map.tiff")
    save_16bit(color_ao, color_dir / "ao.tiff")
    log.info(f"  Saved colored PBR -> {color_dir}")

    return color_dir


# =========================================================================
#  STEP 4: BLENDER  (invoke blender_apply_pbr.py as subprocess)
# =========================================================================

def step4_blender(glb_path, pbr_dir, output_dir, batch_name):
    """Invoke Blender in background to create .blend + renders."""
    log.info("\n" + "=" * 70)
    log.info("STEP 4: BLENDER")
    log.info("=" * 70)

    blender_dir = output_dir / "blender"
    blender_dir.mkdir(parents=True, exist_ok=True)

    # Find the blender_apply_pbr.py script (same directory as this script)
    script_dir = Path(__file__).resolve().parent
    blender_script = script_dir / "blender_apply_pbr.py"

    if not blender_script.exists():
        log.error(f"  Blender script not found: {blender_script}")
        return False

    blender_exe = Path(BLENDER_PATH)
    if not blender_exe.exists():
        log.warning(f"  Blender not found at {BLENDER_PATH} -- skipping Step 4")
        log.warning(f"  To run manually:")
        log.warning(f"    {BLENDER_PATH} --background --python {blender_script} -- \\")
        log.warning(f"      --glb {glb_path} --pbr {pbr_dir} "
                    f"--output {blender_dir} --batch {batch_name}")
        return False

    cmd = [
        str(blender_exe),
        "-b",
        "-P", str(blender_script),
        "--",
        "--glb", str(glb_path),
        "--pbr", str(pbr_dir),
        "--output", str(blender_dir),
        "--batch", batch_name,
        "--no-render",
    ]

    log.info(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    if result.returncode != 0:
        log.error(f"  Blender failed (exit code {result.returncode})")
        if result.stderr:
            for line in result.stderr.strip().split('\n')[-20:]:
                log.error(f"    {line}")
        return False

    log.info(f"  Blender complete -> {blender_dir}")
    return True


# =========================================================================
#  MAIN
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Full Pipeline: Calibration -> Crop -> PBR -> Blender",
    )
    parser.add_argument("--input", required=True,
                        help="Input directory with ARW files")
    parser.add_argument("--checker", required=True,
                        help="Checker ARW filename (relative to --input)")
    parser.add_argument("--glb",
                        help="GLB model path for Blender step")
    parser.add_argument("--output", required=True,
                        help="Output directory")
    parser.add_argument("--crop-size", type=int, default=3200,
                        help="Crop size in pixels (default: 3200)")
    parser.add_argument("--batch",
                        help="Batch name for Blender (default: derived from filenames)")
    parser.add_argument("--blend-px", type=int, default=256,
                        help="Tileable blend width in pixels (default: 256)")
    parser.add_argument("--skip-tileable", action="store_true",
                        help="Skip tileable blending step")
    parser.add_argument("--skip-blender", action="store_true",
                        help="Skip Blender step")
    args = parser.parse_args()

    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()

    log.info("=" * 70)
    log.info("FULL PIPELINE: Calibration -> Crop -> PBR -> Blender")
    log.info(f"  Input:     {input_dir}")
    log.info(f"  Checker:   {args.checker}")
    log.info(f"  Output:    {output_dir}")
    log.info(f"  Crop size: {args.crop_size}")
    if args.glb:
        log.info(f"  GLB:       {args.glb}")
    log.info("=" * 70)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Calibration
    matrix, calibrated_paths, checker_wb_raw, raw_files = step1_calibrate(input_dir, args.checker, output_dir)
    if not calibrated_paths:
        log.error("Step 1 failed -- no calibrated images produced")
        return 1

    # Step 2: Crop
    result = step2_crop(calibrated_paths, output_dir, args.crop_size)
    if not result or not result[0]:
        log.error("Step 2 failed -- no cropped images produced")
        return 1
    cropped_paths, crop_info = result

    # Save calibration.json (matches backend post_capture_service format)
    cal_data = {
        "profile_name": args.checker,
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

    # Step 2b: Edge detection check (before tileable)
    step2b_edge_check(cropped_paths, output_dir)

    # Step 2c: Make tileable
    if not args.skip_tileable:
        cropped_paths = step2c_make_tileable(cropped_paths, output_dir, blend_px=args.blend_px)
    else:
        log.info("\n  Skipping tileable step (--skip-tileable)")

    # Step 3: PBR
    pbr_colored_dir = step3_pbr(cropped_paths, output_dir)
    if pbr_colored_dir is None:
        log.error("Step 3 failed -- no PBR maps generated")
        return 1

    # Step 4: Blender
    if not args.skip_blender and args.glb:
        glb_path = Path(args.glb).expanduser().resolve()
        # Derive batch name from filenames
        batch_name = args.batch
        if not batch_name:
            for p in calibrated_paths:
                m = re.match(r'^(test_\d+)', p.stem)
                if m:
                    batch_name = m.group(1)
                    break
            if not batch_name:
                batch_name = "batch"
        step4_blender(glb_path, pbr_colored_dir, output_dir, batch_name)
    elif not args.glb:
        log.info("\n  Skipping Blender step (no --glb specified)")
    else:
        log.info("\n  Skipping Blender step (--skip-blender)")

    # Summary
    log.info("\n" + "=" * 70)
    log.info("PIPELINE COMPLETE")
    log.info("=" * 70)
    log.info(f"  Calibrated: {output_dir / 'calibrated'}  ({len(calibrated_paths)} images)")
    log.info(f"  Cropped:    {output_dir / 'cropped'}  ({len(cropped_paths)} images)")
    log.info(f"  Edge check: {output_dir / 'edge_check'}")
    log.info(f"  PBR gray:   {output_dir / 'pbr' / 'grayscale'}")
    log.info(f"  PBR color:  {output_dir / 'pbr' / 'colored'}")
    if not args.skip_blender and args.glb:
        log.info(f"  Blender:    {output_dir / 'blender'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

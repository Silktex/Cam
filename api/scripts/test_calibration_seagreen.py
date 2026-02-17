"""
Color Calibration Test — MALVERN-SEAGREEN (new-images)

Uses both checker profiles (MALVERN-SEAGREEN and SINGLE-CHECKER) to calibrate
the top image from the MALVERN-SEAGREEN batch.  Source: RAW only (no pre-made
TIFFs), so we convert RAW→linear float inline.

Based on test_calibration_v12_grimsby.py — same pipeline, different paths.

Usage:
    python test_calibration_seagreen.py
"""
import csv
import sys
import logging
from pathlib import Path

import cv2
import numpy as np
import rawpy

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────
BASE = Path("/Users/abhinavsrivastava/Downloads/new-images/camera-images/captures")
CHECKER_DIR = BASE / "colorchecker"
BATCH_DIR = BASE / "MALVERN-SEAGREEN"

CHECKER_RAWS = {
    "MALVERN-SEAGREEN": CHECKER_DIR / "raw" / "MALVERN-SEAGREEN_20260216_115408.ARW",
    "SINGLE-CHECKER":   CHECKER_DIR / "raw" / "SINGLE-CHECKER_20260216_115723.ARW",
}

TOP_RAW = BATCH_DIR / "raw" / "MALVERN-SEAGREEN_20260216_115943_top.ARW"
OUTPUT_DIR = BATCH_DIR / "calibrated_test"

SWATCH_LABELS = [
    'DarkSkin', 'LightSkin', 'BlueSky', 'Foliage', 'BlueFlower', 'BluishGreen',
    'Orange', 'PurplishBlue', 'ModerateRed', 'Purple', 'YellowGreen', 'OrangeYellow',
    'Blue', 'Green', 'Red', 'Yellow', 'Magenta', 'Cyan',
    'White', 'Neutral8', 'Neutral6.5', 'Neutral5', 'Neutral3.5', 'Black',
]
NEUTRAL_INDICES = list(range(18, 24))
LUMA_COEFF = np.array([0.2126, 0.7152, 0.0722])

# ── Tunable parameters (same as v12) ─────────────────────────────────
NEUTRAL_WEIGHT    = 10.0
RIDGE_LAMBDA      = 0.30
HUBER_DELTA       = 0.03
HUBER_ITERATIONS  = 3
WHITE_CLIP_THRESH = 0.95
WB_DRIFT_THRESH   = 0.15
FLOOR_GATE_THRESH = 0.005
FLOOR_MAX_IMPACT  = 0.03
TOP_BRIGHTNESS_TOL = 0.05


# ── sRGB gamma ──────────────────────────────────────────────────────────

def linear_to_srgb(img):
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055
    ).clip(0, 1)


def luma(rgb):
    return rgb @ LUMA_COEFF if rgb.ndim == 1 else rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


# ── RAW loading ─────────────────────────────────────────────────────────

def load_raw_linear(raw_path):
    """Load RAW → linear float32 RGB (0-1), returns (image, wb_normalized_to_G1)."""
    with rawpy.imread(str(raw_path)) as raw:
        camera_wb = list(raw.camera_whitebalance)
        rgb = raw.postprocess(
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            output_bps=16,
            output_color=rawpy.ColorSpace.sRGB,
            use_camera_wb=True,
            no_auto_bright=True,
            gamma=(1, 1),
            half_size=False,
            fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
        )
    img = rgb.astype(np.float32) / 65535.0
    wb_norm = np.array(camera_wb[:3]) / camera_wb[1]
    return img, wb_norm


def extract_wb_multipliers(raw_path):
    with rawpy.imread(str(raw_path)) as raw:
        wb = np.array(raw.camera_whitebalance[:3], dtype=np.float64)
    return wb / wb[1]


# ── Swatch detection ────────────────────────────────────────────────────

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


# ── Quality gates ────────────────────────────────────────────────────────

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


# ── Regularized 3x3 matrix ──────────────────────────────────────────────

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
        cond = np.linalg.cond(DtWD)
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
    log.info(f"  Condition number: {cond:.2f}")
    log.info(f"  Diagonal: [{diag[0]:.4f}, {diag[1]:.4f}, {diag[2]:.4f}]")
    log.info(f"  Off-diagonal energy: {off_diag:.6f}")

    return M, wp_scale, adapted_ref, {'condition_number': cond, 'residuals': residuals}


# ── Printing ────────────────────────────────────────────────────────────

def print_swatch_table(detected, reference, label=""):
    if label:
        log.info(f"\n  {label}:")
    log.info(f"  {'#':>3s} {'Label':>14s}  {'Detected':>24s}  {'Reference':>24s}  {'dE':>6s}")
    log.info(f"  {'-'*78}")
    errors = []
    for i in range(24):
        d, r = detected[i], reference[i]
        de = np.sqrt(np.sum((d - r) ** 2))
        errors.append(de)
        log.info(f"  {i:3d} {SWATCH_LABELS[i]:>14s}  "
                 f"({d[0]:.4f},{d[1]:.4f},{d[2]:.4f})  "
                 f"({r[0]:.4f},{r[1]:.4f},{r[2]:.4f})  {de:.4f}")
    log.info(f"\n  Mean dE: {np.mean(errors):.4f}  Max dE: {np.max(errors):.4f}")


def print_matrix(M, label=""):
    if label:
        log.info(f"\n  {label}:")
    for r in range(3):
        ch = ['R', 'G', 'B'][r]
        log.info(f"    {ch}: [{M[r, 0]:+.6f}  {M[r, 1]:+.6f}  {M[r, 2]:+.6f}]")


# ── Main ────────────────────────────────────────────────────────────────

def calibrate_with_checker(checker_name, checker_raw_path, top_raw_path, output_dir):
    """Run full calibration pipeline with one checker, output to output_dir/checker_name/."""
    log.info(f"\n{'='*70}")
    log.info(f"CHECKER: {checker_name}")
    log.info(f"  RAW: {checker_raw_path.name}")
    log.info(f"{'='*70}")

    out_dir = output_dir / checker_name
    out_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = out_dir / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Load checker RAW ──
    log.info("\n--- Step 1: Load Checker RAW ---")
    checker_img, checker_wb = load_raw_linear(checker_raw_path)
    log.info(f"  Shape: {checker_img.shape}")
    log.info(f"  WB (G=1): R={checker_wb[0]:.4f} G={checker_wb[1]:.4f} B={checker_wb[2]:.4f}")
    log.info(f"  Stats: min={checker_img.min():.4f} max={checker_img.max():.4f} mean={checker_img.mean():.4f}")

    # ── 2. Detect swatches ──
    log.info("\n--- Step 2: Detect Swatches ---")
    detected, reference = detect_swatches(checker_img)
    if detected is None:
        log.error("  No checker detected!")
        return False

    log.info(f"  Detected {len(detected)} swatches")
    detected = auto_fix_serpentine(detected, reference)

    gates_ok, gate_warnings, reshoot_reasons = quality_gates(detected)
    for w in gate_warnings:
        log.info(f"  GATE: {w}")
    for r in reshoot_reasons:
        log.error(f"  RESHOOT: {r}")
    if not gates_ok:
        log.error("  Quality gates FAILED")
        return False

    print_swatch_table(detected, reference, "Detected vs Reference")

    # ── 3. Fit 3x3 matrix ──
    log.info("\n--- Step 3: Fit 3x3 Matrix ---")
    matrix, wp_scale, adapted_ref, diagnostics = compute_3x3_matrix(detected, reference)
    log.info(f"  WP scale: R={wp_scale[0]:.4f} G={wp_scale[1]:.4f} B={wp_scale[2]:.4f}")
    print_matrix(matrix, "3x3 Matrix")

    corrected_swatches = np.clip((matrix @ detected.T).T, 0, None)
    print_swatch_table(corrected_swatches, adapted_ref, "Post-correction accuracy")

    # ── 4. Load top RAW ──
    log.info("\n--- Step 4: Load & Calibrate Top Image ---")
    top_img, top_wb = load_raw_linear(top_raw_path)
    log.info(f"  Top shape: {top_img.shape}")
    log.info(f"  Top WB (G=1): R={top_wb[0]:.4f} G={top_wb[1]:.4f} B={top_wb[2]:.4f}")
    log.info(f"  Top stats: min={top_img.min():.4f} max={top_img.max():.4f} mean={top_img.mean():.4f}")

    orig_mean = top_img.mean()

    # WB shift: bring top image into checker WB space
    wb_shift = checker_wb / top_wb
    drift = np.max(np.abs(wb_shift - 1.0))
    log.info(f"  WB shift: R={wb_shift[0]:.4f} G={wb_shift[1]:.4f} B={wb_shift[2]:.4f}  drift={drift:.4f}")

    calibrated = top_img.copy()
    if drift > WB_DRIFT_THRESH:
        log.info(f"  Applying WB shift (drift {drift:.4f} > {WB_DRIFT_THRESH})")
        calibrated = calibrated * wb_shift.reshape(1, 1, 3)
    else:
        log.info(f"  Skipping WB shift (drift {drift:.4f} <= {WB_DRIFT_THRESH})")

    # Apply 3x3 matrix
    h, w, _ = calibrated.shape
    flat = calibrated.reshape(-1, 3)
    corrected = (matrix @ flat.T).T.reshape(h, w, 3)
    corrected = np.clip(corrected, 0, 1)

    calib_mean = corrected.mean()
    log.info(f"  Calibrated: orig_mean={orig_mean:.4f} -> calib_mean={calib_mean:.4f}  delta={calib_mean - orig_mean:+.4f}")

    # ── 5. Save outputs ──
    log.info("\n--- Step 5: Save Outputs ---")

    # Linear TIFF (16-bit)
    linear_16 = (corrected * 65535).astype(np.uint16)
    lin_bgr = cv2.cvtColor(linear_16, cv2.COLOR_RGB2BGR)
    tiff_path = out_dir / f"top_calibrated_linear.tiff"
    cv2.imwrite(str(tiff_path), lin_bgr)
    log.info(f"  Saved: {tiff_path.name} (linear TIFF)")

    # sRGB PNG (16-bit)
    srgb_16 = (linear_to_srgb(corrected) * 65535).astype(np.uint16)
    srgb_bgr = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)
    png_path = out_dir / f"top_calibrated_srgb.png"
    cv2.imwrite(str(png_path), srgb_bgr)
    log.info(f"  Saved: {png_path.name} (sRGB PNG)")

    # sRGB JPEG (for quick preview)
    srgb_8 = (linear_to_srgb(corrected) * 255).astype(np.uint8)
    srgb_bgr_8 = cv2.cvtColor(srgb_8, cv2.COLOR_RGB2BGR)
    jpg_path = out_dir / f"top_calibrated_srgb.jpg"
    cv2.imwrite(str(jpg_path), srgb_bgr_8, [cv2.IMWRITE_JPEG_QUALITY, 95])
    log.info(f"  Saved: {jpg_path.name} (sRGB JPEG preview)")

    # Before/after comparison
    orig_srgb_8 = (linear_to_srgb(top_img) * 255).astype(np.uint8)
    h, w = orig_srgb_8.shape[:2]
    sc = min(1200 / w, 1200 / h)
    sz = (int(w * sc), int(h * sc))
    before_sm = cv2.resize(cv2.cvtColor(orig_srgb_8, cv2.COLOR_RGB2BGR), sz)
    after_sm = cv2.resize(srgb_bgr_8, sz)
    comp = np.hstack([before_sm, after_sm])
    cv2.putText(comp, "BEFORE", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.putText(comp, f"AFTER ({checker_name})", (sz[0] + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    cv2.imwrite(str(debug_dir / "before_after.png"), comp)
    log.info(f"  Saved: _debug/before_after.png")

    # Also save uncalibrated sRGB for reference
    orig_jpg = out_dir / "top_original_srgb.jpg"
    cv2.imwrite(str(orig_jpg), cv2.cvtColor(orig_srgb_8, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
    log.info(f"  Saved: {orig_jpg.name} (original sRGB JPEG)")

    log.info(f"\n  Done: {checker_name}")
    return True


def main():
    log.info("=" * 70)
    log.info("Color Calibration Test — MALVERN-SEAGREEN")
    log.info(f"  Using both checker profiles")
    log.info(f"  Top image: {TOP_RAW.name}")
    log.info("=" * 70)

    # Verify files exist
    if not TOP_RAW.exists():
        log.error(f"Top RAW not found: {TOP_RAW}")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for name, raw_path in CHECKER_RAWS.items():
        if not raw_path.exists():
            log.error(f"Checker RAW not found: {raw_path}")
            continue
        calibrate_with_checker(name, raw_path, TOP_RAW, OUTPUT_DIR)

    log.info(f"\n{'='*70}")
    log.info(f"ALL DONE — outputs in {OUTPUT_DIR}")
    log.info(f"{'='*70}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

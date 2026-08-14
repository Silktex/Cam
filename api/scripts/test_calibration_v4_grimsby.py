"""
Color Calibration Test Script for GRIMSBY-EARTH (v4)

Based on v3 with stronger tuning per Gemini recommendations:
  1. Weighted least-squares: 10x weight on neutral patches (was 5x)
  2. Black point compensation: 0.7 scale (was 0.5) — deeper blacks
  3. Midtone crush: 1.2 power (was 1.1) — more contrast/pop

Pipeline per image:
  1. Load cropped TIFF (linear, 16-bit, fabric WB baked in)
  2. Apply WB shift (fabric WB -> checker WB)
  3. Apply weighted diagonal color gains
  4. Subtract black point offset (anchor shadows)
  5. Apply midtone crush (power factor)
  6. Clip to [0,1]
  7. Apply sRGB gamma
  8. Save as 16-bit PNG

Input:  GRIMSBY-EARTH/cropped/*.tiff
Output: GRIMSBY-EARTH/color_calibrated_v4/ (16-bit PNGs, sRGB gamma)
"""
import sys
import logging
from pathlib import Path

import cv2
import numpy as np
import rawpy

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent / "media"
BATCH_PATH = BASE / "captures" / "GRIMSBY-EARTH"
CHECKER_RAW = BASE / "captures" / "colorchecker" / "captures" / "raw" / "colorchecker_ok.ARW"

CROPPED_DIR = BATCH_PATH / "cropped"
OUTPUT_DIR = BATCH_PATH / "color_calibrated_v4"
DEBUG_DIR = OUTPUT_DIR / "_debug"
OLD_CALIB_DIR = BATCH_PATH / "color_calibrated"
V2_CALIB_DIR = BATCH_PATH / "color_calibrated_v2"
V3_CALIB_DIR = BATCH_PATH / "color_calibrated_v3"

SWATCH_LABELS = [
    'DarkSkin', 'LightSkin', 'BlueSky', 'Foliage', 'BlueFlower', 'BluishGreen',
    'Orange', 'PurplishBlue', 'ModerateRed', 'Purple', 'YellowGreen', 'OrangeYellow',
    'Blue', 'Green', 'Red', 'Yellow', 'Magenta', 'Cyan',
    'White', 'Neutral8', 'Neutral6.5', 'Neutral5', 'Neutral3.5', 'Black',
]

# ── Tunable parameters ──────────────────────────────────────────────────
NEUTRAL_WEIGHT = 10.0      # Weight multiplier for neutral patches in least-squares (was 5.0)
BLACK_OFFSET_SCALE = 0.7   # How much of the black patch to subtract (was 0.5) — deeper blacks
MIDTONE_CRUSH = 1.2        # Power factor before sRGB (was 1.1) — more contrast/pop


def linear_to_srgb(img):
    """Apply sRGB gamma curve (linear float 0-1 -> sRGB float 0-1)."""
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055
    ).clip(0, 1)


def load_checker_raw(raw_path):
    """Load checker RAW with camera WB, return (image_float, camera_wb)."""
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
    return img, camera_wb


def detect_swatches(checker_img):
    """Detect 24 ColorChecker swatches, return (detected, reference)."""
    import colour
    from colour_checker_detection import detect_colour_checkers_segmentation

    results = list(detect_colour_checkers_segmentation(checker_img, additional_data=True))
    if not results:
        return None, None

    detected = results[0].values[0].copy()  # (24, 3)

    # Reference swatches (linear sRGB, D65)
    cc = colour.CCS_COLOURCHECKERS['ColorChecker24 - After November 2014']
    reference = colour.XYZ_to_RGB(
        colour.xyY_to_XYZ(list(cc.data.values())),
        'sRGB', cc.illuminant, apply_cctf_encoding=False,
    )

    return detected, reference


def auto_fix_serpentine(detected, reference):
    """Fix serpentine row ordering — reverse rows where it improves match."""
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


def compute_weighted_diagonal_gains(detected, reference):
    """
    Weighted least-squares diagonal gains.
    Neutral patches (18-23) get NEUTRAL_WEIGHT x more influence.
    This keeps greys neutral without over-correcting saturated colors.

    Returns (gains, wp_scale, adapted_reference).
    """
    # White-point adaptation: scale reference so white patch matches detected
    det_white = detected[18]
    ref_white = reference[18]
    safe_ref = np.where(ref_white > 1e-6, ref_white, 1e-6)
    wp_scale = det_white / safe_ref
    adapted_ref = reference * wp_scale

    # Weights: 1.0 for color patches, NEUTRAL_WEIGHT for neutrals
    weights = np.ones(24)
    weights[18:24] = NEUTRAL_WEIGHT

    # Weighted diagonal gains: least-squares per channel
    gains = np.ones(3)
    for c in range(3):
        det_c = detected[:, c]
        ref_c = adapted_ref[:, c]
        numerator = np.sum(weights * det_c * ref_c)
        denominator = np.sum(weights * (det_c ** 2))
        if denominator > 1e-10:
            gains[c] = numerator / denominator

    return gains, wp_scale, adapted_ref


def compute_wb_shift(checker_wb, fabric_raw_path):
    """
    Compute WB shift ratio: checker_wb / fabric_wb (normalized to G=1).
    This shifts fabric images to match checker illuminant before applying gains.
    """
    with rawpy.imread(str(fabric_raw_path)) as raw:
        fabric_wb = list(raw.camera_whitebalance)

    ck = np.array(checker_wb[:3]) / checker_wb[1]
    fb = np.array(fabric_wb[:3]) / fabric_wb[1]
    wb_shift = ck / fb
    return wb_shift, fabric_wb


def print_swatch_table(detected, reference, label=""):
    """Print detected vs reference swatch comparison."""
    if label:
        log.info(f"\n  {label}:")
    log.info(f"  {'#':>3s} {'Label':>14s}  {'Detected':>24s}  {'Reference':>24s}  {'dE':>6s}")
    log.info(f"  {'-'*78}")
    errors = []
    for i in range(24):
        d = detected[i]
        r = reference[i]
        de = np.sqrt(np.sum((d - r) ** 2))
        errors.append(de)
        log.info(f"  {i:3d} {SWATCH_LABELS[i]:>14s}  "
                 f"({d[0]:.4f},{d[1]:.4f},{d[2]:.4f})  "
                 f"({r[0]:.4f},{r[1]:.4f},{r[2]:.4f})  {de:.4f}")
    log.info(f"\n  Mean dE: {np.mean(errors):.4f}  Max dE: {np.max(errors):.4f}")
    return errors


def print_neutral_check(swatches, label=""):
    """Check neutral patches are actually neutral (R ~= G ~= B)."""
    if label:
        log.info(f"\n  {label}:")
    for i, name in zip(range(18, 24), ['White', 'N8', 'N6.5', 'N5', 'N3.5', 'Black']):
        c = swatches[i]
        spread = max(c) - min(c)
        status = "OK" if spread < 0.02 else "WARN" if spread < 0.05 else "BAD"
        log.info(f"    {name:>6s}: R={c[0]:.4f} G={c[1]:.4f} B={c[2]:.4f}  "
                 f"spread={spread:.4f}  {status}")


# ── Main ────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 70)
    log.info("Color Calibration v4: GRIMSBY-EARTH")
    log.info("Stronger: weighted gains (10x) + black point (0.7) + crush (1.2)")
    log.info(f"  NEUTRAL_WEIGHT={NEUTRAL_WEIGHT}  BLACK_OFFSET={BLACK_OFFSET_SCALE}  CRUSH={MIDTONE_CRUSH}")
    log.info("=" * 70)

    # Check paths
    for name, path in [("Batch", BATCH_PATH), ("Cropped", CROPPED_DIR), ("Checker", CHECKER_RAW)]:
        ok = path.exists()
        log.info(f"  {name:>10s}: {'OK' if ok else 'MISSING'}")
        if not ok:
            return 1

    # ── Step 1: Load checker and detect swatches ──
    log.info("\n--- Step 1: Detect ColorChecker ---")
    checker_img, checker_wb = load_checker_raw(CHECKER_RAW)
    log.info(f"  Checker image: {checker_img.shape}")
    log.info(f"  Camera WB: {checker_wb[:3]}")

    detected, reference = detect_swatches(checker_img)
    if detected is None:
        log.error("  No checker detected!")
        return 1
    log.info(f"  Detected {len(detected)} swatches")

    # Fix serpentine ordering
    detected = auto_fix_serpentine(detected, reference)

    # Show white patch stats
    w = detected[18]
    log.info(f"\n  White patch: R={w[0]:.4f} G={w[1]:.4f} B={w[2]:.4f}")
    log.info(f"    R/G={w[0]/w[1]:.4f}  B/G={w[2]/w[1]:.4f}")

    # Show black patch stats
    b = detected[23]
    log.info(f"  Black patch: R={b[0]:.4f} G={b[1]:.4f} B={b[2]:.4f}")

    # ── Step 2: Compute weighted diagonal gains ──
    log.info("\n--- Step 2: Compute Weighted Diagonal Gains ---")
    gains, wp_scale, adapted_ref = compute_weighted_diagonal_gains(detected, reference)
    log.info(f"  White-point scale: R={wp_scale[0]:.4f} G={wp_scale[1]:.4f} B={wp_scale[2]:.4f}")
    log.info(f"  Weighted gains:   R={gains[0]:.4f} G={gains[1]:.4f} B={gains[2]:.4f}")

    # Compare with unweighted (v2) gains for reference
    gains_v2 = np.ones(3)
    for c in range(3):
        det_c = detected[:, c]
        ref_c = adapted_ref[:, c]
        denom = np.sum(det_c ** 2)
        if denom > 1e-10:
            gains_v2[c] = np.sum(det_c * ref_c) / denom
    log.info(f"  (v2 unweighted:   R={gains_v2[0]:.4f} G={gains_v2[1]:.4f} B={gains_v2[2]:.4f})")

    # Show corrected swatches vs adapted reference
    corrected_swatches = detected * gains
    print_swatch_table(corrected_swatches, adapted_ref, "Post-correction accuracy")
    print_neutral_check(corrected_swatches, "Neutral check (corrected)")

    # ── Step 3: Compute black point offset ──
    log.info("\n--- Step 3: Black Point Offset ---")
    black_patch = detected[23]
    black_offset = black_patch * gains * BLACK_OFFSET_SCALE
    log.info(f"  Black patch (detected): R={black_patch[0]:.4f} G={black_patch[1]:.4f} B={black_patch[2]:.4f}")
    log.info(f"  Black after gains:      R={black_patch[0]*gains[0]:.4f} G={black_patch[1]*gains[1]:.4f} B={black_patch[2]*gains[2]:.4f}")
    log.info(f"  Offset (x{BLACK_OFFSET_SCALE}):       R={black_offset[0]:.4f} G={black_offset[1]:.4f} B={black_offset[2]:.4f}")

    # ── Step 4: Compute WB shift ──
    log.info("\n--- Step 4: Fabric WB Shift ---")
    fabric_raw = BATCH_PATH / "raw" / "GRIMSBY-EARTH_20260213_180038_top.ARW"
    wb_shift, fabric_wb = compute_wb_shift(checker_wb, fabric_raw)
    log.info(f"  Checker WB (G=1): {checker_wb[0]/checker_wb[1]:.4f}, 1.0000, {checker_wb[2]/checker_wb[1]:.4f}")
    log.info(f"  Fabric  WB (G=1): {fabric_wb[0]/fabric_wb[1]:.4f}, 1.0000, {fabric_wb[2]/fabric_wb[1]:.4f}")
    log.info(f"  WB shift (ck/fb): R={wb_shift[0]:.4f} G={wb_shift[1]:.4f} B={wb_shift[2]:.4f}")

    # ── Step 5: Calibrate batch ──
    log.info("\n--- Step 5: Calibrate Batch ---")
    combined = wb_shift * gains
    log.info(f"  WB shift:     R={wb_shift[0]:.4f} G={wb_shift[1]:.4f} B={wb_shift[2]:.4f}")
    log.info(f"  Gains:        R={gains[0]:.4f} G={gains[1]:.4f} B={gains[2]:.4f}")
    log.info(f"  Combined:     R={combined[0]:.4f} G={combined[1]:.4f} B={combined[2]:.4f}")
    log.info(f"  Black offset: R={black_offset[0]:.4f} G={black_offset[1]:.4f} B={black_offset[2]:.4f}")
    log.info(f"  Midtone crush: {MIDTONE_CRUSH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    count = 0
    for tiff_path in sorted(CROPPED_DIR.iterdir()):
        if tiff_path.suffix.lower() not in {'.tiff', '.tif'}:
            continue

        count += 1
        log.info(f"\n  [{count}] {tiff_path.name}")

        # Load cropped TIFF
        img_cv = cv2.imread(str(tiff_path), cv2.IMREAD_UNCHANGED)
        if img_cv is None:
            log.error(f"    FAILED to read")
            continue

        img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
        if img_cv.dtype == np.uint16:
            img_f = img_rgb.astype(np.float32) / 65535.0
        else:
            img_f = img_rgb.astype(np.float32) / 255.0

        log.info(f"    Input: shape={img_f.shape} range=[{img_f.min():.4f}, {img_f.max():.4f}]")

        # 1. Apply WB shift + gains
        calibrated = img_f * combined.reshape(1, 1, 3)

        # 2. Black point compensation — subtract offset to anchor shadows
        calibrated = calibrated - black_offset.reshape(1, 1, 3)
        calibrated = np.clip(calibrated, 0, 1)

        # 3. Midtone crush — power factor to darken midtones/shadows
        calibrated = np.power(calibrated, MIDTONE_CRUSH)

        # 4. sRGB gamma
        calibrated_srgb = linear_to_srgb(calibrated)

        # Save as 16-bit PNG
        out_16 = (calibrated_srgb * 65535).astype(np.uint16)
        out_bgr = cv2.cvtColor(out_16, cv2.COLOR_RGB2BGR)
        out_path = OUTPUT_DIR / f"{tiff_path.stem}_calibrated.png"
        cv2.imwrite(str(out_path), out_bgr)
        log.info(f"    Saved: {out_path.name}  range=[{calibrated.min():.4f}, {calibrated.max():.4f}]")

        # Debug images for first image
        if count <= 1:
            # Original (just sRGB gamma, no correction)
            orig_srgb = linear_to_srgb(img_f)
            cv2.imwrite(str(DEBUG_DIR / f"{tiff_path.stem}_00_original.png"),
                       cv2.cvtColor((orig_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            # After WB shift only
            wb_only = np.clip(img_f * wb_shift.reshape(1, 1, 3), 0, 1)
            wb_srgb = linear_to_srgb(wb_only)
            cv2.imwrite(str(DEBUG_DIR / f"{tiff_path.stem}_01_wb_shift.png"),
                       cv2.cvtColor((wb_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            # v2 style (gains only, no black offset, no crush) for comparison
            v2_cal = np.clip(img_f * combined.reshape(1, 1, 3), 0, 1)
            v2_srgb = linear_to_srgb(v2_cal)
            cv2.imwrite(str(DEBUG_DIR / f"{tiff_path.stem}_02_v2_gains_only.png"),
                       cv2.cvtColor((v2_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            # Final v4 calibrated
            cv2.imwrite(str(DEBUG_DIR / f"{tiff_path.stem}_03_v4_calibrated.png"), out_bgr)

    log.info(f"\n  Calibrated {count} images")

    # ── Step 6: Compare old vs v2 vs v3 ──
    log.info("\n--- Step 6: Compare ---")

    # Find top images from each version
    old_top = None
    v2_top = None
    v3_top = None
    v4_top = None

    if OLD_CALIB_DIR.exists():
        old_top = next((f for f in OLD_CALIB_DIR.glob("*top*calibrated*")), None)
    if V2_CALIB_DIR.exists():
        v2_top = next((f for f in V2_CALIB_DIR.glob("*top*calibrated*")), None)
    if V3_CALIB_DIR.exists():
        v3_top = next((f for f in V3_CALIB_DIR.glob("*top*calibrated*")), None)
    v4_top = next((f for f in OUTPUT_DIR.glob("*top*calibrated*")), None)

    if v4_top:
        new = cv2.imread(str(v4_top), cv2.IMREAD_UNCHANGED)
        for c, ch in enumerate(['B', 'G', 'R']):
            nm = new[:, :, c].astype(float).mean()
            log.info(f"  v4 {ch}: mean={nm:.0f}")

    # Build comparison across all versions
    images_for_comp = []
    labels = []

    if old_top:
        img = cv2.imread(str(old_top), cv2.IMREAD_UNCHANGED)
        if img is not None:
            images_for_comp.append(img)
            labels.append("OLD (service)")

    if v2_top:
        img = cv2.imread(str(v2_top), cv2.IMREAD_UNCHANGED)
        if img is not None:
            images_for_comp.append(img)
            labels.append("v2 (WP+gains)")

    if v3_top:
        img = cv2.imread(str(v3_top), cv2.IMREAD_UNCHANGED)
        if img is not None:
            images_for_comp.append(img)
            labels.append("v3 (w5/bp0.5/c1.1)")

    if v4_top:
        images_for_comp.append(new)
        labels.append("v4 (w10/bp0.7/c1.2)")

    if len(images_for_comp) >= 2:
        # Resize all to same dimensions
        target_shape = images_for_comp[0].shape[:2]
        sc = min(800 / target_shape[1], 800 / target_shape[0])
        sz = (int(target_shape[1] * sc), int(target_shape[0] * sc))

        panels = []
        for img in images_for_comp:
            if img.shape[:2] != target_shape:
                img = cv2.resize(img, (target_shape[1], target_shape[0]))
            resized = cv2.resize(img, sz)
            if resized.dtype == np.uint16:
                resized = (resized / 257).astype(np.uint8)
            panels.append(resized)

        comp = np.hstack(panels)
        x = 10
        for label in labels:
            cv2.putText(comp, label, (x, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            x += sz[0]

        cv2.imwrite(str(DEBUG_DIR / "comparison_all_versions.png"), comp)
        log.info(f"  Saved: comparison_all_versions.png ({len(labels)} panels)")
    else:
        log.info("  Not enough versions for comparison")

    log.info(f"\n{'='*70}")
    log.info(f"DONE — Output: {OUTPUT_DIR}")
    log.info(f"Debug: {DEBUG_DIR}")
    log.info(f"  _00_original.png       — TIFF + sRGB (no correction)")
    log.info(f"  _01_wb_shift.png       — after WB shift only")
    log.info(f"  _02_v2_gains_only.png  — v2 style (gains, no BP/crush)")
    log.info(f"  _03_v4_calibrated.png  — v4 final (w10/bp0.7/crush1.2)")
    log.info(f"  comparison_all_versions.png")
    log.info(f"{'='*70}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""
Color Calibration Test Script v7 (any GRIMSBY batch)

Based on v4 (Power Law pipeline) with "v4.1 Slight Polish" tweaks:
  1. Weighted least-squares: 10x weight on neutral patches (same as v4)
  2. Black point compensation: 0.62 scale (was 0.7) — reveals deep weave texture
  3. Midtone crush: 1.14 power (was 1.2) — slightly brighter midtones

Pipeline per image:
  1. Load cropped TIFF (linear, 16-bit, fabric WB baked in)
  2. Apply WB shift (fabric WB -> checker WB)
  3. Apply weighted diagonal color gains
  4. Subtract black point offset (anchor shadows)
  5. Apply midtone crush (power factor)
  6. Clip to [0,1]
  7. Apply sRGB gamma
  8. Save as 16-bit PNG

Usage: python test_calibration_v7_grimsby.py [BATCH_NAME]
  Default: GRIMSBY-EARTH
  Example: python test_calibration_v7_grimsby.py GRIMSBY-MUSHROOM
"""
import sys
import logging
from pathlib import Path

import cv2
import numpy as np
import rawpy

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger(__name__)

# ── Paths (set up in main() based on batch name) ───────────────────────
BASE = Path(__file__).resolve().parent.parent / "media"
CHECKER_RAW = BASE / "captures" / "colorchecker" / "captures" / "raw" / "colorchecker_ok.ARW"

SWATCH_LABELS = [
    'DarkSkin', 'LightSkin', 'BlueSky', 'Foliage', 'BlueFlower', 'BluishGreen',
    'Orange', 'PurplishBlue', 'ModerateRed', 'Purple', 'YellowGreen', 'OrangeYellow',
    'Blue', 'Green', 'Red', 'Yellow', 'Magenta', 'Cyan',
    'White', 'Neutral8', 'Neutral6.5', 'Neutral5', 'Neutral3.5', 'Black',
]

# ── Tunable parameters v7 ("Perfect Color" Polish) ───────────────────
NEUTRAL_WEIGHT = 10.0       # Same as v4
BLACK_OFFSET_SCALE = 0.62   # Dropped from 0.7 (reveals deep weave texture / "grit")
MIDTONE_CRUSH = 1.14        # Dropped from 1.2 (slightly brighter midtones)


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
    batch_name = sys.argv[1] if len(sys.argv) > 1 else "GRIMSBY-EARTH"

    # Derive all paths from batch name
    batch_path = BASE / "captures" / batch_name
    cropped_dir = batch_path / "cropped"
    output_dir = batch_path / "color_calibrated_v7"
    debug_dir = output_dir / "_debug"

    log.info("=" * 70)
    log.info(f"Color Calibration v7: {batch_name}")
    log.info("v4.1 Polish: same color, more grit + slight brightness lift")
    log.info(f"  NEUTRAL_WEIGHT={NEUTRAL_WEIGHT}  BLACK_OFFSET={BLACK_OFFSET_SCALE}  CRUSH={MIDTONE_CRUSH}")
    log.info("=" * 70)

    # Check paths
    for name, path in [("Batch", batch_path), ("Cropped", cropped_dir), ("Checker", CHECKER_RAW)]:
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
    # Find the top RAW file for this batch
    raw_dir = batch_path / "raw"
    fabric_raw = next((f for f in sorted(raw_dir.glob("*top*.ARW"))), None)
    if fabric_raw is None:
        log.error("  No top RAW file found!")
        return 1
    log.info(f"  Fabric RAW: {fabric_raw.name}")
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

    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for tiff_path in sorted(cropped_dir.iterdir()):
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
        out_path = output_dir / f"{tiff_path.stem}_calibrated.png"
        cv2.imwrite(str(out_path), out_bgr)
        log.info(f"    Saved: {out_path.name}  range=[{calibrated.min():.4f}, {calibrated.max():.4f}]")

        # Debug images for first image
        if count <= 1:
            # Original (just sRGB gamma, no correction)
            orig_srgb = linear_to_srgb(img_f)
            cv2.imwrite(str(debug_dir / "_00_original.png"),
                       cv2.cvtColor((orig_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            # After WB shift only
            wb_only = np.clip(img_f * wb_shift.reshape(1, 1, 3), 0, 1)
            wb_srgb = linear_to_srgb(wb_only)
            cv2.imwrite(str(debug_dir / "_01_wb_shift.png"),
                       cv2.cvtColor((wb_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            # v4 style (same gains, v4 params) for comparison
            v4_cal = img_f * combined.reshape(1, 1, 3)
            v4_bp = black_patch * gains * 0.7  # v4 offset scale
            v4_cal = np.clip(v4_cal - v4_bp.reshape(1, 1, 3), 0, 1)
            v4_cal = np.power(v4_cal, 1.2)  # v4 crush
            v4_srgb = linear_to_srgb(v4_cal)
            cv2.imwrite(str(debug_dir / "_02_v4_reference.png"),
                       cv2.cvtColor((v4_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            # Final v7 calibrated
            cv2.imwrite(str(debug_dir / "_03_v7_calibrated.png"), out_bgr)

    log.info(f"\n  Calibrated {count} images")

    # ── Step 6: Compare ──
    log.info("\n--- Step 6: Compare ---")

    v7_top = next((f for f in output_dir.glob("*top*calibrated*")), None)

    if v7_top:
        new = cv2.imread(str(v7_top), cv2.IMREAD_UNCHANGED)
        for c, ch in enumerate(['B', 'G', 'R']):
            nm = new[:, :, c].astype(float).mean()
            log.info(f"  v7 {ch}: mean={nm:.0f}")

    # Build comparison: original vs v7
    images_for_comp = []
    labels = []

    # Try to load original (uncalibrated) top for reference
    orig_top = next((f for f in sorted(cropped_dir.glob("*top*.tiff"))), None)
    if orig_top:
        img_cv = cv2.imread(str(orig_top), cv2.IMREAD_UNCHANGED)
        if img_cv is not None:
            img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
            if img_cv.dtype == np.uint16:
                img_f = img_rgb.astype(np.float32) / 65535.0
            else:
                img_f = img_rgb.astype(np.float32) / 255.0
            orig_srgb = linear_to_srgb(img_f)
            orig_16 = (orig_srgb * 65535).astype(np.uint16)
            orig_bgr = cv2.cvtColor(orig_16, cv2.COLOR_RGB2BGR)
            images_for_comp.append(orig_bgr)
            labels.append("Original")

    if v7_top:
        images_for_comp.append(new)
        labels.append("v7 (bp0.62/c1.14)")

    if len(images_for_comp) >= 2:
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

        cv2.imwrite(str(debug_dir / "comparison_orig_v7.png"), comp)
        log.info(f"  Saved: comparison_orig_v7.png ({len(labels)} panels)")
    else:
        log.info("  Not enough versions for comparison")

    log.info(f"\n{'='*70}")
    log.info(f"DONE — Output: {output_dir}")
    log.info(f"Debug: {debug_dir}")
    log.info(f"  _00_original.png       — TIFF + sRGB (no correction)")
    log.info(f"  _01_wb_shift.png       — after WB shift only")
    log.info(f"  _02_v4_reference.png   — v4 params for comparison")
    log.info(f"  _03_v7_calibrated.png  — v7 final (bp0.62/crush1.14)")
    log.info(f"  comparison_orig_v7.png")
    log.info(f"{'='*70}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

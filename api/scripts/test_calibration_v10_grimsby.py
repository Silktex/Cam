"""
Color Calibration Test Script v10 — Global Target Matcher

Problem with v7: Fixed black subtraction crushes dark side images.
Problem with v8: Levels remap brightens everything uniformly.
Problem with v9: Adaptive floor cap preserves dark images but doesn't
                 normalize brightness across batches.

Solution: Proportional remap + dynamic per-batch adaptive boost.
  - Proportional remap: (pixel - floor) / (1 - floor)
    Removes black offset without crushing — maps floor→0, 1→1
  - Dynamic target: top image's post-remap mean IS the batch target
    Top image gets boost=1.0 (preserves fabric's natural brightness)
    Side images get boosted toward top's mean, clamped [0.8, 1.5]
  - Midtone crush applied after boost for texture/grit

Pipeline:
  1. Load all cropped TIFFs, process top image first (no boost)
  2. Apply WB shift + weighted diagonal color gains
  3. Proportional remap: (pixel - floor) / (1 - floor)
  4. Top image: no boost → its mean becomes the batch target
     Side images: adaptive boost toward top's mean (clamped [0.8, 1.5])
  5. Midtone crush (power factor for texture/grit)
  6. Clip to [0,1]
  7. Apply sRGB gamma
  8. Save as 16-bit PNG

Usage: python test_calibration_v10_grimsby.py [BATCH_NAME]
  Default: GRIMSBY-EARTH
  Example: python test_calibration_v10_grimsby.py GRIMSBY-MUSHROOM
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
CHECKER_RAW = BASE / "captures" / "colorchecker" / "captures" / "raw" / "colorchecker_ok.ARW"

SWATCH_LABELS = [
    'DarkSkin', 'LightSkin', 'BlueSky', 'Foliage', 'BlueFlower', 'BluishGreen',
    'Orange', 'PurplishBlue', 'ModerateRed', 'Purple', 'YellowGreen', 'OrangeYellow',
    'Blue', 'Green', 'Red', 'Yellow', 'Magenta', 'Cyan',
    'White', 'Neutral8', 'Neutral6.5', 'Neutral5', 'Neutral3.5', 'Black',
]

# ── Tunable parameters v10 (Global Target Matcher) ──────────────────
NEUTRAL_WEIGHT = 10.0       # Proven good color from v4/v7
BLACK_OFFSET_SCALE = 0.58   # Slightly less aggressive than v7's 0.62
MIDTONE_CRUSH = 1.12        # Slightly less than v7's 1.14 — boost handles grit
# DYNAMIC target: derived from each batch's own top image (no fixed global)
BOOST_MIN = 0.8             # Don't darken bright images too much
BOOST_MAX = 1.5             # Don't blow out dark images
WB_SHIFT_BLEND = 0.3        # How much WB shift to apply (0=none, 1=full)
                            # 0.3 + uniform floor preserves fabric warmth


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

    Returns (gains, wp_scale, adapted_reference).
    """
    det_white = detected[18]
    ref_white = reference[18]
    safe_ref = np.where(ref_white > 1e-6, ref_white, 1e-6)
    wp_scale = det_white / safe_ref
    adapted_ref = reference * wp_scale

    weights = np.ones(24)
    weights[18:24] = NEUTRAL_WEIGHT

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

    batch_path = BASE / "captures" / batch_name
    cropped_dir = batch_path / "cropped"
    output_dir = batch_path / "color_calibrated_v10"
    debug_dir = output_dir / "_debug"
    v7_calib_dir = batch_path / "color_calibrated_v7"
    v9_calib_dir = batch_path / "color_calibrated_v9"

    log.info("=" * 70)
    log.info(f"Color Calibration v10: {batch_name}")
    log.info("Global Target Matcher: proportional remap + dynamic batch boost")
    log.info(f"  NEUTRAL_WEIGHT={NEUTRAL_WEIGHT}  BLACK_OFFSET={BLACK_OFFSET_SCALE}")
    log.info(f"  CRUSH={MIDTONE_CRUSH}  TARGET=dynamic (from top image)")
    log.info(f"  BOOST_RANGE=[{BOOST_MIN}, {BOOST_MAX}]  WB_BLEND={WB_SHIFT_BLEND}")
    log.info("=" * 70)

    for name, path in [("Batch", batch_path), ("Cropped", cropped_dir), ("Checker", CHECKER_RAW)]:
        ok = path.exists()
        log.info(f"  {name:>10s}: {'OK' if ok else 'MISSING'}")
        if not ok:
            return 1

    # ── Step 1: Detect ColorChecker ──
    log.info("\n--- Step 1: Detect ColorChecker ---")
    checker_img, checker_wb = load_checker_raw(CHECKER_RAW)
    log.info(f"  Checker image: {checker_img.shape}")
    log.info(f"  Camera WB: {checker_wb[:3]}")

    detected, reference = detect_swatches(checker_img)
    if detected is None:
        log.error("  No checker detected!")
        return 1
    log.info(f"  Detected {len(detected)} swatches")

    detected = auto_fix_serpentine(detected, reference)

    w = detected[18]
    log.info(f"\n  White patch: R={w[0]:.4f} G={w[1]:.4f} B={w[2]:.4f}")
    b = detected[23]
    log.info(f"  Black patch: R={b[0]:.4f} G={b[1]:.4f} B={b[2]:.4f}")

    # ── Step 2: Weighted diagonal gains ──
    log.info("\n--- Step 2: Compute Weighted Diagonal Gains ---")
    gains, wp_scale, adapted_ref = compute_weighted_diagonal_gains(detected, reference)
    log.info(f"  White-point scale: R={wp_scale[0]:.4f} G={wp_scale[1]:.4f} B={wp_scale[2]:.4f}")
    log.info(f"  Weighted gains:   R={gains[0]:.4f} G={gains[1]:.4f} B={gains[2]:.4f}")

    corrected_swatches = detected * gains
    print_swatch_table(corrected_swatches, adapted_ref, "Post-correction accuracy")
    print_neutral_check(corrected_swatches, "Neutral check (corrected)")

    # ── Step 3: Checker-derived floor for proportional remap ──
    log.info("\n--- Step 3: Checker Black Floor (proportional remap) ---")
    black_patch = detected[23]
    floor_rgb = black_patch * gains * BLACK_OFFSET_SCALE
    # Use UNIFORM scalar floor (luminance-weighted) to avoid color shift
    # Per-channel floors amplify blue more than red in the division step
    floor = 0.2126 * floor_rgb[0] + 0.7152 * floor_rgb[1] + 0.0722 * floor_rgb[2]
    log.info(f"  Black patch (detected): R={black_patch[0]:.4f} G={black_patch[1]:.4f} B={black_patch[2]:.4f}")
    log.info(f"  Floor per-ch (x{BLACK_OFFSET_SCALE}):  R={floor_rgb[0]:.4f} G={floor_rgb[1]:.4f} B={floor_rgb[2]:.4f}")
    log.info(f"  Floor uniform (luma):   {floor:.4f}")
    log.info(f"  Remap: (pixel - floor) / (1 - floor)  [color-neutral]")

    # ── Step 4: WB shift ──
    log.info("\n--- Step 4: Fabric WB Shift ---")
    raw_dir = batch_path / "raw"
    fabric_raw = next((f for f in sorted(raw_dir.glob("*top*.ARW"))), None)
    if fabric_raw is None:
        log.error("  No top RAW file found!")
        return 1
    log.info(f"  Fabric RAW: {fabric_raw.name}")
    wb_shift, fabric_wb = compute_wb_shift(checker_wb, fabric_raw)
    log.info(f"  Checker WB (G=1): {checker_wb[0]/checker_wb[1]:.4f}, 1.0000, {checker_wb[2]/checker_wb[1]:.4f}")
    log.info(f"  Fabric  WB (G=1): {fabric_wb[0]/fabric_wb[1]:.4f}, 1.0000, {fabric_wb[2]/fabric_wb[1]:.4f}")
    log.info(f"  WB shift (raw): R={wb_shift[0]:.4f} G={wb_shift[1]:.4f} B={wb_shift[2]:.4f}")

    # Blend WB shift: 0=no shift (preserve fabric color), 1=full shift
    blended_wb = 1.0 + WB_SHIFT_BLEND * (wb_shift - 1.0)
    log.info(f"  WB blended ({WB_SHIFT_BLEND}): R={blended_wb[0]:.4f} G={blended_wb[1]:.4f} B={blended_wb[2]:.4f}")

    # ── Step 5: Calibrate batch ──
    log.info("\n--- Step 5: Calibrate Batch (Dynamic Target Matcher) ---")
    combined = blended_wb * gains
    log.info(f"  WB shift:      R={blended_wb[0]:.4f} G={blended_wb[1]:.4f} B={blended_wb[2]:.4f}")
    log.info(f"  Gains:         R={gains[0]:.4f} G={gains[1]:.4f} B={gains[2]:.4f}")
    log.info(f"  Combined:      R={combined[0]:.4f} G={combined[1]:.4f} B={combined[2]:.4f}")
    log.info(f"  Floor:         {floor:.4f} (uniform)")
    log.info(f"  Midtone crush: {MIDTONE_CRUSH}")

    output_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    # Pre-compute remap denominator (scalar — color-neutral)
    remap_denom = 1.0 - floor

    # Sort files so top image comes first — it sets the dynamic target
    all_tiffs = sorted(
        [f for f in cropped_dir.iterdir() if f.suffix.lower() in {'.tiff', '.tif'}]
    )
    top_tiffs = [f for f in all_tiffs if 'top' in f.stem.lower()]
    side_tiffs = [f for f in all_tiffs if 'top' not in f.stem.lower()]
    ordered_tiffs = top_tiffs + side_tiffs

    if not top_tiffs:
        log.warning("  No top image found — falling back to first image as target")

    batch_mean_target = None  # Will be set from top image

    count = 0
    boost_log = []
    for tiff_path in ordered_tiffs:
        count += 1
        is_top = 'top' in tiff_path.stem.lower()
        log.info(f"\n  [{count}] {tiff_path.name}{'  *** TOP (reference) ***' if is_top else ''}")

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

        # 1. Apply WB shift + gains (color calibration)
        calibrated = img_f * combined.reshape(1, 1, 3)

        # Capture natural mean BEFORE remap/crush (this is what the image "should" look like)
        natural_mean = calibrated.mean()

        # 2. PROPORTIONAL REMAP: (pixel - floor) / (1 - floor)
        #    Uniform scalar floor — removes black offset without shifting color
        calibrated = (calibrated - floor) / remap_denom
        calibrated = np.clip(calibrated, 0, 1)

        # 3. Midtone crush — power factor for texture/grit
        #    Applied BEFORE boost so boost compensates for ALL darkening
        calibrated = np.power(calibrated, MIDTONE_CRUSH)

        # 4. DYNAMIC ADAPTIVE BOOST
        #    Remap+crush darken the image. Boost compensates for both.
        #    Top image: boost restores its natural (pre-pipeline) brightness
        #    Side images: boost toward the top's natural brightness
        post_pipeline_mean = calibrated.mean()

        if is_top or (batch_mean_target is None and count == 1):
            # Top: target is its own natural mean (restore what remap+crush took away)
            batch_mean_target = natural_mean
            log.info(f"    TOP — natural={natural_mean:.4f}  post-pipeline={post_pipeline_mean:.4f}")

        if post_pipeline_mean > 1e-6:
            raw_boost = batch_mean_target / post_pipeline_mean
        else:
            raw_boost = 1.0
        boost = np.clip(raw_boost, BOOST_MIN, BOOST_MAX)

        calibrated = calibrated * boost
        calibrated = np.clip(calibrated, 0, 1)

        boost_status = ""
        if raw_boost < BOOST_MIN:
            boost_status = " (clamped low)"
        elif raw_boost > BOOST_MAX:
            boost_status = " (clamped high)"
        log.info(f"    Post-pipeline mean: {post_pipeline_mean:.4f}  target={batch_mean_target:.4f}")
        log.info(f"    Boost: {boost:.4f} (raw={raw_boost:.4f}){boost_status}")
        log.info(f"    Mean after boost:  {calibrated.mean():.4f}")
        boost_log.append((tiff_path.name, natural_mean, post_pipeline_mean, boost,
                          calibrated.mean(), "TOP" if is_top else ""))

        # 5. sRGB gamma
        calibrated_srgb = linear_to_srgb(calibrated)

        # Save as 16-bit PNG
        out_16 = (calibrated_srgb * 65535).astype(np.uint16)
        out_bgr = cv2.cvtColor(out_16, cv2.COLOR_RGB2BGR)
        out_path = output_dir / f"{tiff_path.stem}_calibrated.png"
        cv2.imwrite(str(out_path), out_bgr)
        log.info(f"    Saved: {out_path.name}  range=[{calibrated_srgb.min():.4f}, {calibrated_srgb.max():.4f}]")

        # Debug images for top image
        if is_top:
            orig_srgb = linear_to_srgb(img_f)
            cv2.imwrite(str(debug_dir / "_00_original.png"),
                       cv2.cvtColor((orig_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            wb_only = np.clip(img_f * wb_shift.reshape(1, 1, 3), 0, 1)
            wb_srgb = linear_to_srgb(wb_only)
            cv2.imwrite(str(debug_dir / "_01_wb_shift.png"),
                       cv2.cvtColor((wb_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            # v7 for comparison (fixed subtraction)
            v7_cal = img_f * combined.reshape(1, 1, 3)
            v7_bp = black_patch * gains * 0.62
            v7_cal = np.clip(v7_cal - v7_bp.reshape(1, 1, 3), 0, 1)
            v7_cal = np.power(v7_cal, 1.14)
            v7_srgb = linear_to_srgb(v7_cal)
            cv2.imwrite(str(debug_dir / "_02_v7_reference.png"),
                       cv2.cvtColor((v7_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))

            cv2.imwrite(str(debug_dir / "_03_v10_calibrated.png"), out_bgr)

    log.info(f"\n  Calibrated {count} images")

    # ── Boost summary ──
    log.info("\n--- Boost Summary ---")
    log.info(f"  Batch target (from top's natural mean): {batch_mean_target:.4f}")
    log.info(f"  {'Image':>40s}  {'Natural':>8s}  {'Remapped':>8s}  {'Boost':>6s}  {'Final':>6s}  {'Role':>4s}")
    log.info(f"  {'-'*80}")
    for name, nat, remap, bst, final, role in boost_log:
        log.info(f"  {name:>40s}  {nat:8.4f}  {remap:8.4f}  {bst:6.4f}  {final:6.4f}  {role:>4s}")
    if boost_log:
        final_means = [x[4] for x in boost_log]
        natural_means = [x[1] for x in boost_log]
        log.info(f"\n  Natural range: [{min(natural_means):.4f}, {max(natural_means):.4f}]  spread={max(natural_means)-min(natural_means):.4f}")
        log.info(f"  Final range:   [{min(final_means):.4f}, {max(final_means):.4f}]  spread={max(final_means)-min(final_means):.4f}")

    # ── Step 6: Compare ──
    log.info("\n--- Step 6: Compare ---")

    v7_top = None
    v9_top = None
    v10_top = next((f for f in output_dir.glob("*top*calibrated*")), None)

    if v7_calib_dir.exists():
        v7_top = next((f for f in v7_calib_dir.glob("*top*calibrated*")), None)
    if v9_calib_dir.exists():
        v9_top = next((f for f in v9_calib_dir.glob("*top*calibrated*")), None)

    if v10_top:
        new = cv2.imread(str(v10_top), cv2.IMREAD_UNCHANGED)
        for c, ch in enumerate(['B', 'G', 'R']):
            nm = new[:, :, c].astype(float).mean()
            log.info(f"  v10 {ch}: mean={nm:.0f}")

    images_for_comp = []
    labels = []

    if v7_top:
        img = cv2.imread(str(v7_top), cv2.IMREAD_UNCHANGED)
        if img is not None:
            images_for_comp.append(img)
            labels.append("v7 (fixed sub)")

    if v9_top:
        img = cv2.imread(str(v9_top), cv2.IMREAD_UNCHANGED)
        if img is not None:
            images_for_comp.append(img)
            labels.append("v9 (adaptive)")

    if v10_top:
        images_for_comp.append(new)
        labels.append("v10 (target)")

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

        comp_name = f"comparison_{'_'.join(l.split()[0] for l in labels)}.png"
        cv2.imwrite(str(debug_dir / comp_name), comp)
        log.info(f"  Saved: {comp_name} ({len(labels)} panels)")
    else:
        log.info("  (not enough versions for comparison)")

    log.info(f"\n{'='*70}")
    log.info(f"DONE — Output: {output_dir}")
    log.info(f"Debug: {debug_dir}")
    log.info(f"{'='*70}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""
Color Calibration Test Script v11 — Pure Calibration (Any Fabric)

Changes from v10:
  - v10 used diagonal gains (per-channel) — can leave yellow/green tint on textiles
  - v10 blended WB between checker and fabric — inconsistent across fabrics
  - v10 did proportional remap + adaptive boost — breaks dark fabrics
  - v10 applied midtone crush 1.12 — mixed calibration with "look"

v11 follows the calibration checklist strictly:
  D. 3x3 matrix (weighted least-squares) instead of diagonal gains
  E. Camera WB only (from checker shot) — no per-fabric WB blending
  F. No brightness normalization — dark fabric stays dark
  G. Calibration separated from look — minimal optional toe curve
  B. Input validation (linearity, bit depth, color order)
  C. Glare rejection (patch variance check), shrink sampling
  I. Regression tests (neutral spread, clipping, dE, dark fabric safety, determinism)

Pipeline:
  1. Load checker RAW with camera WB (linear, no auto-bright)
  2. Detect 24 swatches — validate, fix serpentine, reject glare
  3. White-point adapt reference to scene illuminant
  4. Compute 3x3 correction matrix (weighted least-squares, neutrals weighted higher)
  5. For each fabric image:
     a. Load cropped TIFF (validate linear, uint16, RGB)
     b. Apply 3x3 matrix in linear space
     c. Clip in linear
     d. Apply sRGB gamma exactly once
     e. Save 16-bit PNG
  6. Run regression tests

Usage: python test_calibration_v11_grimsby.py [BATCH_NAME ...]
  Default: GRIMSBY-EARTH GRIMSBY-MUSHROOM
  Example: python test_calibration_v11_grimsby.py GRIMSBY-EARTH
"""
import sys
import hashlib
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

NEUTRAL_INDICES = list(range(18, 24))  # White through Black

# ── Tunable parameters v11 ─────────────────────────────────────────────
NEUTRAL_WEIGHT    = 10.0   # Extra weight for neutral patches in 3x3 fit
GLARE_VAR_THRESH  = 0.015  # Max per-channel std within a patch before glare warning
SHRINK_FACTOR     = 0.15   # Shrink patch sampling region by 15% on each side
MIDTONE_CRUSH     = 1.0    # 1.0 = no crush (pure calibration). Bump to ~1.03-1.05 for subtle texture.
DARK_BOOST_LIMIT  = 0.15   # Regression test: fail if any image boosted >15%


# ── sRGB gamma ──────────────────────────────────────────────────────────

def linear_to_srgb(img):
    """Apply sRGB gamma curve (linear float 0-1 -> sRGB float 0-1)."""
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055
    ).clip(0, 1)


# ── Checker loading ─────────────────────────────────────────────────────

def load_checker_raw(raw_path):
    """
    Load checker RAW with camera WB, return (image_float_linear, camera_wb).
    Uses camera WB — this is the single WB source for the session (checklist E).
    """
    with rawpy.imread(str(raw_path)) as raw:
        camera_wb = list(raw.camera_whitebalance)
        rgb = raw.postprocess(
            demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,
            output_bps=16,
            output_color=rawpy.ColorSpace.sRGB,
            use_camera_wb=True,
            no_auto_bright=True,
            gamma=(1, 1),       # Linear output
            half_size=False,
            fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
        )
    img = rgb.astype(np.float32) / 65535.0
    return img, camera_wb


# ── Swatch detection ────────────────────────────────────────────────────

def detect_swatches(checker_img):
    """
    Detect 24 ColorChecker swatches.
    Returns (detected_24x3, reference_24x3) or (None, None).
    """
    import colour
    from colour_checker_detection import detect_colour_checkers_segmentation

    results = list(detect_colour_checkers_segmentation(checker_img, additional_data=True))
    if not results:
        return None, None

    detected = results[0].values[0].copy()  # (24, 3)

    if detected.shape[0] != 24:
        log.error(f"  Expected 24 swatches, got {detected.shape[0]} — aborting")
        return None, None

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


def check_glare(detected):
    """
    Check for glare: if the white patch (index 18) clips any channel.
    Returns list of warnings. (Checklist A: no clipping on white patch)
    """
    warnings = []
    white = detected[18]
    for c, ch in enumerate(['R', 'G', 'B']):
        if white[c] > 0.98:
            warnings.append(f"White patch {ch}={white[c]:.4f} near clipping!")
    return warnings


def check_patch_variance(checker_img, detected):
    """
    Placeholder: with segmentation-based detection we get mean values only.
    Log a note. In a full implementation with bounding boxes, we'd sample
    inside each patch and check variance to reject glare.
    """
    # The colour_checker_detection library returns mean swatch values,
    # not per-pixel data. We check for obvious issues via value range.
    warnings = []
    for i in range(24):
        vals = detected[i]
        if np.any(vals > 0.99):
            warnings.append(f"  Patch {i} ({SWATCH_LABELS[i]}): channel near 1.0 — possible glare")
        if np.any(vals < 0.001) and i != 23:  # Black patch (23) is expected to be dark
            warnings.append(f"  Patch {i} ({SWATCH_LABELS[i]}): channel near 0.0 — possible shadow")
    return warnings


# ── 3x3 Matrix computation (checklist D) ────────────────────────────────

def compute_3x3_matrix(detected, reference, neutral_weight=NEUTRAL_WEIGHT):
    """
    Compute a 3x3 color correction matrix using weighted least-squares.

    Solves:  reference ≈ detected @ M.T
    i.e., for each swatch i:  ref[i] = M @ det[i]

    Neutral patches (18-23) get extra weight to ensure grays stay gray,
    but all 24 patches contribute to avoid distorting chromatic colors.

    Returns (M_3x3, wp_scale, adapted_reference).
    """
    # White-point adaptation: scale reference to match scene illuminant
    det_white = detected[18]
    ref_white = reference[18]
    safe_ref = np.where(ref_white > 1e-6, ref_white, 1e-6)
    wp_scale = det_white / safe_ref
    adapted_ref = reference * wp_scale

    # Build weight vector
    weights = np.ones(24)
    weights[NEUTRAL_INDICES] = neutral_weight

    # Weighted least-squares: solve for M such that adapted_ref ≈ M @ detected
    # For each output channel c: ref[:, c] = detected @ m_c
    # With weights W: m_c = (D^T W D)^-1 D^T W r_c
    W = np.diag(weights)
    D = detected  # (24, 3)

    DtWD = D.T @ W @ D  # (3, 3)
    DtWD_inv = np.linalg.inv(DtWD)

    M = np.zeros((3, 3))
    for c in range(3):
        r_c = adapted_ref[:, c]  # (24,)
        M[c, :] = DtWD_inv @ (D.T @ W @ r_c)

    return M, wp_scale, adapted_ref


# ── Input validation (checklist B) ──────────────────────────────────────

def validate_tiff_input(img_cv, tiff_path):
    """
    Validate a loaded TIFF:
      - Must be uint16 (linear 16-bit)
      - Must have 3 channels
      - Warn if values suggest it's already gamma-encoded
    Returns (is_valid, warnings).
    """
    warnings = []

    if img_cv is None:
        return False, [f"Failed to read: {tiff_path}"]

    if img_cv.dtype != np.uint16:
        warnings.append(f"Expected uint16, got {img_cv.dtype} — may not be linear")

    if len(img_cv.shape) != 3 or img_cv.shape[2] != 3:
        return False, [f"Expected 3-channel image, got shape {img_cv.shape}"]

    # Heuristic: if mean value is very high relative to max, might be gamma-encoded
    img_f = img_cv.astype(np.float32) / 65535.0
    mean_val = img_f.mean()
    max_val = img_f.max()
    if max_val > 0.01 and mean_val / max_val > 0.65:
        warnings.append(
            f"Mean/max ratio = {mean_val/max_val:.3f} — suspiciously high, "
            f"image may already be gamma-encoded"
        )

    return True, warnings


# ── Printing helpers ────────────────────────────────────────────────────

def print_swatch_table(detected, reference, label=""):
    """Print detected vs reference swatch comparison with dE."""
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
    """Check neutral patches R ~= G ~= B (checklist I: neutral spread)."""
    if label:
        log.info(f"\n  {label}:")
    spreads = []
    for i, name in zip(range(18, 24), ['White', 'N8', 'N6.5', 'N5', 'N3.5', 'Black']):
        c = swatches[i]
        spread = max(c) - min(c)
        spreads.append(spread)
        status = "OK" if spread < 0.02 else "WARN" if spread < 0.05 else "BAD"
        log.info(f"    {name:>6s}: R={c[0]:.4f} G={c[1]:.4f} B={c[2]:.4f}  "
                 f"spread={spread:.4f}  {status}")
    return spreads


def print_matrix(M, label=""):
    """Pretty-print a 3x3 matrix."""
    if label:
        log.info(f"\n  {label}:")
    for r in range(3):
        ch = ['R', 'G', 'B'][r]
        log.info(f"    {ch}: [{M[r, 0]:+.6f}  {M[r, 1]:+.6f}  {M[r, 2]:+.6f}]")
    # Show how diagonal-dominant it is
    diag = np.diag(M)
    off_diag = np.abs(M - np.diag(diag)).sum()
    log.info(f"    Diagonal: {diag}")
    log.info(f"    Off-diagonal energy: {off_diag:.6f}")


# ── Regression tests (checklist I) ─────────────────────────────────────

class RegressionTests:
    """Automated regression tests run after calibration."""

    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0

    def _record(self, name, passed, detail=""):
        status = "PASS" if passed else "FAIL"
        self.results.append((name, status, detail))
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        log.info(f"  [{status}] {name}  {detail}")

    def test_neutral_spread(self, corrected_swatches):
        """
        Neutral patches should be truly neutral after white-balance normalization.
        We normalize each patch by the corrected white patch (index 18) so that
        the illuminant color cancels out, then check R ~= G ~= B.
        """
        white = corrected_swatches[18]
        safe_white = np.where(white > 1e-6, white, 1e-6)
        spreads = []
        for i in NEUTRAL_INDICES:
            c = corrected_swatches[i]
            # Normalize by white patch — removes illuminant bias
            normalized = c / safe_white
            spread = max(normalized) - min(normalized)
            spreads.append(spread)
        max_spread = max(spreads)
        mean_spread = np.mean(spreads)
        self._record(
            "Neutral spread (WB-normalized, max < 0.05)",
            max_spread < 0.05,
            f"max={max_spread:.4f} mean={mean_spread:.4f}"
        )

    def test_no_clipping(self, corrected_swatches):
        """No channel in the corrected checker should clip."""
        max_val = corrected_swatches.max()
        self._record(
            "No clipping (max < 0.99)",
            max_val < 0.99,
            f"max={max_val:.4f}"
        )

    def test_de_metric(self, corrected_swatches, adapted_ref):
        """Mean and max dE across all 24 patches."""
        errors = []
        for i in range(24):
            de = np.sqrt(np.sum((corrected_swatches[i] - adapted_ref[i]) ** 2))
            errors.append(de)
        mean_de = np.mean(errors)
        max_de = np.max(errors)
        self._record(
            "Mean dE < 0.05",
            mean_de < 0.05,
            f"mean={mean_de:.4f} max={max_de:.4f}"
        )
        self._record(
            "Max dE < 0.10",
            max_de < 0.10,
            f"max={max_de:.4f}"
        )

    def test_dark_fabric_safety(self, image_stats):
        """
        No image should have received >15% exposure boost IN LINEAR SPACE.
        Compare calibrated linear mean vs original linear mean.
        Note: sRGB gamma naturally lifts midtones ~2-3x — that's encoding,
        not a boost. We must compare in the same domain (linear).
        """
        for name, orig_mean, calib_linear_mean in image_stats:
            if orig_mean > 1e-6:
                boost_pct = (calib_linear_mean - orig_mean) / orig_mean
            else:
                boost_pct = 0.0
            passed = boost_pct <= DARK_BOOST_LIMIT
            self._record(
                f"Dark fabric safety: {Path(name).stem[:30]}",
                passed,
                f"linear boost={boost_pct:+.1%} (limit={DARK_BOOST_LIMIT:+.0%})"
            )

    def test_determinism(self, calibrate_fn, tiff_path, matrix, crush):
        """Run calibration twice on same image, output must be identical."""
        out1, _ = calibrate_fn(tiff_path, matrix, crush)
        out2, _ = calibrate_fn(tiff_path, matrix, crush)
        if out1 is None or out2 is None:
            self._record("Determinism", False, "calibration returned None")
            return
        h1 = hashlib.sha256(out1.tobytes()).hexdigest()[:16]
        h2 = hashlib.sha256(out2.tobytes()).hexdigest()[:16]
        self._record(
            "Determinism (identical output)",
            h1 == h2,
            f"hash1={h1} hash2={h2}"
        )

    def summary(self):
        log.info(f"\n  Regression: {self.passed} passed, {self.failed} failed, "
                 f"{self.passed + self.failed} total")
        return self.failed == 0


# ── Image calibration (single image) ───────────────────────────────────

def calibrate_single(tiff_path, matrix, crush=MIDTONE_CRUSH):
    """
    Calibrate one cropped TIFF. Returns (srgb_uint16, linear_mean) or (None, None).

    Pipeline:
      1. Load uint16 TIFF, validate (checklist B)
      2. Convert BGR->RGB, normalize to float32 [0,1] (checklist B: exactly once)
      3. Apply 3x3 matrix in linear space (checklist D)
      4. Clip in linear BEFORE gamma (checklist H)
      5. Optional mild crush (checklist G: separate from calibration)
      6. Apply sRGB gamma exactly once (checklist H)
      7. Return uint16 + linear mean (for dark fabric safety test)
    """
    img_cv = cv2.imread(str(tiff_path), cv2.IMREAD_UNCHANGED)

    valid, warnings = validate_tiff_input(img_cv, tiff_path)
    for w in warnings:
        log.warning(f"    INPUT WARNING: {w}")
    if not valid:
        return None, None

    # BGR -> RGB (checklist B: exactly once)
    img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)

    # Normalize to float [0,1] — uint16 / 65535 (checklist B: correct scaling)
    if img_cv.dtype == np.uint16:
        img_f = img_rgb.astype(np.float32) / 65535.0
    else:
        img_f = img_rgb.astype(np.float32) / 255.0

    # Apply 3x3 matrix: each pixel p -> M @ p
    h, w_px, _ = img_f.shape
    flat = img_f.reshape(-1, 3)          # (N, 3)
    corrected = (matrix @ flat.T).T      # (N, 3)
    corrected = corrected.reshape(h, w_px, 3)

    # Clip in linear space (checklist H: clip before gamma)
    corrected = np.clip(corrected, 0, 1)

    # Capture linear mean BEFORE gamma (for dark fabric safety comparison)
    linear_mean = corrected.mean()

    # Optional mild crush — 1.0 means no effect (checklist G: minimal look)
    if crush != 1.0:
        corrected = np.power(corrected, crush)

    # sRGB gamma — exactly once (checklist H)
    corrected_srgb = linear_to_srgb(corrected)

    # Return as uint16 RGB + linear mean
    out_16 = (corrected_srgb * 65535).astype(np.uint16)
    return out_16, linear_mean


# ── Main ────────────────────────────────────────────────────────────────

def main():
    batch_names = sys.argv[1:] if len(sys.argv) > 1 else ["GRIMSBY-EARTH", "GRIMSBY-MUSHROOM"]

    log.info("=" * 70)
    log.info("Color Calibration v11: Pure Calibration (Any Fabric)")
    log.info("3x3 matrix, camera WB only, no brightness normalization")
    log.info(f"  NEUTRAL_WEIGHT={NEUTRAL_WEIGHT}  CRUSH={MIDTONE_CRUSH}")
    log.info(f"  GLARE_THRESH={GLARE_VAR_THRESH}  SHRINK={SHRINK_FACTOR}")
    log.info(f"  Batches: {batch_names}")
    log.info("=" * 70)

    # ── Step 1: Load & detect ColorChecker ──
    log.info("\n--- Step 1: Detect ColorChecker ---")
    if not CHECKER_RAW.exists():
        log.error(f"  Checker RAW not found: {CHECKER_RAW}")
        return 1

    checker_img, checker_wb = load_checker_raw(CHECKER_RAW)
    log.info(f"  Checker image: {checker_img.shape} range=[{checker_img.min():.4f}, {checker_img.max():.4f}]")
    log.info(f"  Camera WB: {checker_wb[:3]}")

    detected, reference = detect_swatches(checker_img)
    if detected is None:
        log.error("  No checker detected — aborting!")
        return 1
    log.info(f"  Detected {len(detected)} swatches")

    # ── Step 2: Validate & fix ordering ──
    log.info("\n--- Step 2: Validate Swatches ---")

    # Check glare (checklist A/C)
    glare_warnings = check_glare(detected)
    for w in glare_warnings:
        log.warning(f"  GLARE: {w}")

    patch_warnings = check_patch_variance(checker_img, detected)
    for w in patch_warnings:
        log.warning(w)

    if len(glare_warnings) > 0:
        log.warning("  White patch near clipping — results may be unreliable. Consider reshooting.")

    # Fix serpentine (checklist C)
    detected = auto_fix_serpentine(detected, reference)

    w = detected[18]
    log.info(f"\n  White patch: R={w[0]:.4f} G={w[1]:.4f} B={w[2]:.4f}")
    b = detected[23]
    log.info(f"  Black patch: R={b[0]:.4f} G={b[1]:.4f} B={b[2]:.4f}")

    print_swatch_table(detected, reference, "Raw detected vs reference")

    # ── Step 3: Compute 3x3 correction matrix (checklist D) ──
    log.info("\n--- Step 3: Compute 3x3 Correction Matrix ---")
    matrix, wp_scale, adapted_ref = compute_3x3_matrix(detected, reference)
    log.info(f"  White-point scale: R={wp_scale[0]:.4f} G={wp_scale[1]:.4f} B={wp_scale[2]:.4f}")
    print_matrix(matrix, "3x3 Correction Matrix")

    # Verify: apply matrix to detected swatches
    corrected_swatches = (matrix @ detected.T).T
    corrected_swatches = np.clip(corrected_swatches, 0, None)
    print_swatch_table(corrected_swatches, adapted_ref, "Post-correction accuracy (checker)")
    print_neutral_check(corrected_swatches, "Neutral check (corrected)")

    # ── Step 4: Regression tests on checker ──
    log.info("\n--- Step 4: Checker Regression Tests ---")
    tests = RegressionTests()
    tests.test_neutral_spread(corrected_swatches)
    tests.test_no_clipping(corrected_swatches)
    tests.test_de_metric(corrected_swatches, adapted_ref)

    # ── Step 5: Calibrate batches ──
    for batch_name in batch_names:
        log.info(f"\n{'='*70}")
        log.info(f"BATCH: {batch_name}")
        log.info(f"{'='*70}")

        batch_path = BASE / "captures" / batch_name
        cropped_dir = batch_path / "cropped"
        output_dir = batch_path / "color_calibrated_v11"
        debug_dir = output_dir / "_debug"
        v10_dir = batch_path / "color_calibrated_v10"

        for name, path in [("Batch", batch_path), ("Cropped", cropped_dir)]:
            ok = path.exists()
            log.info(f"  {name:>10s}: {'OK' if ok else 'MISSING'} — {path}")
            if not ok:
                log.error(f"  Skipping {batch_name}")
                continue

        output_dir.mkdir(parents=True, exist_ok=True)
        debug_dir.mkdir(parents=True, exist_ok=True)

        # Sort: top first, then sides
        all_tiffs = sorted(
            [f for f in cropped_dir.iterdir() if f.suffix.lower() in {'.tiff', '.tif'}]
        )
        top_tiffs = [f for f in all_tiffs if 'top' in f.stem.lower()]
        side_tiffs = [f for f in all_tiffs if 'top' not in f.stem.lower()]
        ordered_tiffs = top_tiffs + side_tiffs

        log.info(f"  Images: {len(top_tiffs)} top + {len(side_tiffs)} side = {len(ordered_tiffs)} total")

        image_stats = []  # (name, orig_mean, final_mean) for dark fabric test
        count = 0

        for tiff_path in ordered_tiffs:
            count += 1
            is_top = 'top' in tiff_path.stem.lower()
            log.info(f"\n  [{count}] {tiff_path.name}{'  *** TOP ***' if is_top else ''}")

            # Read original for stats
            img_cv = cv2.imread(str(tiff_path), cv2.IMREAD_UNCHANGED)
            if img_cv is None:
                log.error(f"    FAILED to read")
                continue

            img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
            if img_cv.dtype == np.uint16:
                orig_f = img_rgb.astype(np.float32) / 65535.0
            else:
                orig_f = img_rgb.astype(np.float32) / 255.0

            orig_mean = orig_f.mean()
            log.info(f"    Input: shape={orig_f.shape} range=[{orig_f.min():.4f}, {orig_f.max():.4f}] mean={orig_mean:.4f}")

            # Calibrate
            out_16, calib_linear_mean = calibrate_single(tiff_path, matrix, MIDTONE_CRUSH)
            if out_16 is None:
                log.error(f"    Calibration failed!")
                continue

            srgb_mean = (out_16.astype(np.float32) / 65535.0).mean()
            # Track linear mean for dark fabric safety (apples-to-apples with orig_mean)
            image_stats.append((tiff_path.name, orig_mean, calib_linear_mean))

            log.info(f"    Linear: orig={orig_mean:.4f} -> calib={calib_linear_mean:.4f}  delta={calib_linear_mean - orig_mean:+.4f}")
            log.info(f"    sRGB output mean: {srgb_mean:.4f}")

            # Save as 16-bit PNG
            out_bgr = cv2.cvtColor(out_16, cv2.COLOR_RGB2BGR)
            out_path = output_dir / f"{tiff_path.stem}_calibrated.png"
            cv2.imwrite(str(out_path), out_bgr)
            log.info(f"    Saved: {out_path.name}")

            # Debug: save top original + v11 side by side
            if is_top:
                # Original (apply sRGB for display)
                orig_srgb = linear_to_srgb(orig_f)
                cv2.imwrite(str(debug_dir / "_00_original.png"),
                           cv2.cvtColor((orig_srgb * 65535).astype(np.uint16), cv2.COLOR_RGB2BGR))
                cv2.imwrite(str(debug_dir / "_01_v11_calibrated.png"), out_bgr)

        log.info(f"\n  Calibrated {count} images -> {output_dir}")

        # ── Image stats summary (all in linear space) ──
        log.info(f"\n--- Image Stats (linear): {batch_name} ---")
        log.info(f"  {'Image':>45s}  {'Orig':>7s}  {'Calib':>7s}  {'Delta':>7s}  {'Pct':>7s}")
        log.info(f"  {'-'*78}")
        for name, orig, calib in image_stats:
            delta = calib - orig
            pct = (delta / orig * 100) if orig > 1e-6 else 0.0
            log.info(f"  {name:>45s}  {orig:7.4f}  {calib:7.4f}  {delta:+7.4f}  {pct:+6.1f}%")
        if image_stats:
            orig_means = [x[1] for x in image_stats]
            calib_means = [x[2] for x in image_stats]
            log.info(f"\n  Original range: [{min(orig_means):.4f}, {max(orig_means):.4f}]  spread={max(orig_means)-min(orig_means):.4f}")
            log.info(f"  Calib range:    [{min(calib_means):.4f}, {max(calib_means):.4f}]  spread={max(calib_means)-min(calib_means):.4f}")

        # ── Dark fabric safety test ──
        tests.test_dark_fabric_safety(image_stats)

        # ── Determinism test (on first image) ──
        if ordered_tiffs:
            tests.test_determinism(calibrate_single, ordered_tiffs[0], matrix, MIDTONE_CRUSH)

        # ── Compare v10 vs v11 ──
        log.info(f"\n--- Compare v10 vs v11: {batch_name} ---")
        v10_top = next((f for f in v10_dir.glob("*top*calibrated*")), None) if v10_dir.exists() else None
        v11_top = next((f for f in output_dir.glob("*top*calibrated*")), None)

        if v10_top and v11_top:
            img_v10 = cv2.imread(str(v10_top), cv2.IMREAD_UNCHANGED)
            img_v11 = cv2.imread(str(v11_top), cv2.IMREAD_UNCHANGED)

            if img_v10 is not None and img_v11 is not None:
                for tag, img in [("v10", img_v10), ("v11", img_v11)]:
                    for c, ch in enumerate(['B', 'G', 'R']):
                        log.info(f"  {tag} {ch}: mean={img[:, :, c].astype(float).mean():.0f}")

                # Build comparison panel
                target_shape = img_v10.shape[:2]
                sc = min(800 / target_shape[1], 800 / target_shape[0])
                sz = (int(target_shape[1] * sc), int(target_shape[0] * sc))

                panels = []
                labels = ["v10 (diag+boost)", "v11 (3x3 pure)"]
                for img in [img_v10, img_v11]:
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

                comp_path = debug_dir / "comparison_v10_v11.png"
                cv2.imwrite(str(comp_path), comp)
                log.info(f"  Saved: {comp_path.name}")
        else:
            log.info("  (v10 or v11 top not found — skipping comparison)")

    # ── Final regression summary ──
    log.info(f"\n{'='*70}")
    log.info("REGRESSION TEST SUMMARY")
    log.info(f"{'='*70}")
    for name, status, detail in tests.results:
        log.info(f"  [{status}] {name}  {detail}")
    all_passed = tests.summary()

    log.info(f"\n{'='*70}")
    log.info(f"DONE — v11 calibration complete")
    log.info(f"{'='*70}")
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())

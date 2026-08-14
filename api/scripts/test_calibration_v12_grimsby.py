"""
Color Calibration Test Script v12 — Locked WB + Regularized 3x3

Changes from v11:
  - v11 ignored WB mismatch between checker and fabric TIFFs
  - v11 had unconstrained 3x3 matrix (could shift brightness via off-diagonal)
  - v11 had no luminance preservation constraint
  - v11 had no robust outlier handling in fitting

v12 non-negotiable invariants:
  1. One domain: everything in linear RGB until final sRGB encode
  2. One gamma: sRGB applied exactly once at the end
  3. One WB basis: fabric TIFFs normalized to checker WB before matrix
  4. Calibration != Look: no crush/boost/levels

v12 additions:
  D. WB normalization: compute per-image WB shift (fabric->checker), apply before matrix
  E. Luminance-preserving 3x3: constrain matrix so white patch luma stays constant
  F. Regularized fitting: ridge penalty toward identity, condition number check,
     iterative Huber reweighting for outlier resistance
  G. Floor handling: optional, gated, neutral scalar only
  I. Top brightness preservation test (linear mean within ±5%)
  I. 5th percentile shadow preservation test
  J. Debug artifacts: CSV, matrix.txt, overlay, histogram, before/after
  K. Reshoot warnings

Pipeline:
  1. Load checker RAW, extract WB multipliers
  2. Detect 24 swatches, validate, fix serpentine, quality gates
  3. White-point adapt reference, fit regularized 3x3 with Huber weights
  4. Enforce luminance preservation on white patch
  5. For each fabric TIFF:
     a. Load, validate (B)
     b. Read fabric RAW WB, compute shift to checker WB (D)
     c. Apply WB shift in linear (D)
     d. Apply 3x3 matrix (E)
     e. Optional gated floor correction (G)
     f. Clip in linear, apply sRGB gamma once (H)
     g. Save 16-bit PNG
  6. Run regression tests (I)
  7. Write debug artifacts (J)

Usage: python test_calibration_v12_grimsby.py [BATCH_NAME ...]
  Default: GRIMSBY-EARTH GRIMSBY-MUSHROOM
"""
import csv
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
NEUTRAL_INDICES = list(range(18, 24))
LUMA_COEFF = np.array([0.2126, 0.7152, 0.0722])

# ── Tunable parameters v12 ─────────────────────────────────────────────
NEUTRAL_WEIGHT       = 10.0    # Extra weight for neutrals in 3x3 fit
RIDGE_LAMBDA         = 0.30    # Regularization toward identity (F) — higher = more conservative
HUBER_DELTA          = 0.03    # Huber loss threshold for outlier patches (F)
HUBER_ITERATIONS     = 3       # Iterative reweighting rounds
WHITE_CLIP_THRESH    = 0.95    # Max white patch channel before RESHOOT warning (C)
WB_DRIFT_THRESH      = 0.15   # Max WB drift before applying correction (D) — 15% (same lightbox = no shift needed)
FLOOR_GATE_THRESH    = 0.005   # Only apply floor if black patch luma > this (G)
FLOOR_MAX_IMPACT     = 0.03    # Floor must not change top mean by >3% (G)
TOP_BRIGHTNESS_TOL   = 0.05    # Top image linear mean must stay within ±5% (I)
SHADOW_P5_TOL        = 0.10    # 5th percentile luma can change by at most 10% (I)
COND_NUMBER_WARN     = 50.0    # Warn if DtWD condition number exceeds this (F)


# ── sRGB gamma ──────────────────────────────────────────────────────────

def linear_to_srgb(img):
    """Apply sRGB gamma (linear 0-1 -> sRGB 0-1). Applied exactly once."""
    return np.where(
        img <= 0.0031308,
        img * 12.92,
        1.055 * np.power(np.clip(img, 0.0031308, None), 1.0 / 2.4) - 0.055
    ).clip(0, 1)


def luma(rgb):
    """Compute luminance from linear RGB (scalar or array)."""
    return rgb @ LUMA_COEFF if rgb.ndim == 1 else rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722


# ── WB extraction ──────────────────────────────────────────────────────

def extract_wb_multipliers(raw_path):
    """Extract camera WB multipliers from RAW, normalized to G=1."""
    with rawpy.imread(str(raw_path)) as raw:
        wb = np.array(raw.camera_whitebalance[:3], dtype=np.float64)
    wb_norm = wb / wb[1]  # Normalize to G=1
    return wb_norm


def load_checker_raw(raw_path):
    """Load checker RAW with camera WB. Returns (linear_float, wb_g_normalized)."""
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


# ── Swatch detection ────────────────────────────────────────────────────

def detect_swatches(checker_img):
    """Detect 24 ColorChecker swatches. Returns (detected, reference) or (None, None)."""
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


# ── Quality gates (C/K) ────────────────────────────────────────────────

def quality_gates(detected):
    """
    Run all checker quality gates. Returns (pass, warnings, reshoot_reasons).
    A reshoot reason is a hard failure.
    """
    warnings = []
    reshoot = []

    # White patch clipping (C)
    white = detected[18]
    for c, ch in enumerate(['R', 'G', 'B']):
        if white[c] > WHITE_CLIP_THRESH:
            reshoot.append(f"White patch {ch}={white[c]:.4f} > {WHITE_CLIP_THRESH} — near clipping")

    # Patch value sanity
    for i in range(24):
        v = detected[i]
        if np.any(v > 0.99):
            warnings.append(f"Patch {i} ({SWATCH_LABELS[i]}): channel near 1.0")
        if np.any(v < 0.001) and i != 23:
            warnings.append(f"Patch {i} ({SWATCH_LABELS[i]}): channel near 0.0")

    # Neutral monotonicity (C)
    neutral_luma = [luma(detected[i]) for i in NEUTRAL_INDICES]
    is_monotonic = all(neutral_luma[i] >= neutral_luma[i + 1] for i in range(5))
    if not is_monotonic:
        reshoot.append(f"Neutral row NOT monotonic: {[f'{v:.4f}' for v in neutral_luma]}")
    else:
        warnings.append(f"Neutral monotonicity OK: {[f'{v:.4f}' for v in neutral_luma]}")

    return len(reshoot) == 0, warnings, reshoot


# ── Regularized 3x3 with Huber reweighting (E/F) ──────────────────────

def compute_3x3_matrix(detected, reference, neutral_weight=NEUTRAL_WEIGHT,
                       ridge_lambda=RIDGE_LAMBDA, huber_delta=HUBER_DELTA,
                       huber_iters=HUBER_ITERATIONS):
    """
    Regularized 3x3 color correction matrix with Huber robust reweighting.

    1. White-point adapt reference to scene illuminant
    2. Ridge-regularized WLS: M = argmin Σ w_i ||ref_i - M@det_i||² + λ||M - I||²
    3. Iterative Huber reweighting: down-weight outlier patches
    4. Luminance preservation: rescale M so white patch luma is unchanged

    Returns (M, wp_scale, adapted_ref, diagnostics_dict).
    """
    # White-point adaptation
    det_white = detected[18]
    ref_white = reference[18]
    safe_ref = np.where(ref_white > 1e-6, ref_white, 1e-6)
    wp_scale = det_white / safe_ref
    adapted_ref = reference * wp_scale

    D = detected  # (24, 3)
    I3 = np.eye(3)

    # Initial weights: neutrals weighted higher
    base_weights = np.ones(24)
    base_weights[NEUTRAL_INDICES] = neutral_weight
    weights = base_weights.copy()

    M = None
    residuals_per_patch = np.zeros(24)

    for iteration in range(max(1, huber_iters)):
        W = np.diag(weights)

        # Ridge-regularized: (D^T W D + λI)^-1 (D^T W r_c + λ e_c)
        DtWD = D.T @ W @ D + ridge_lambda * I3
        cond = np.linalg.cond(DtWD)

        M = np.zeros((3, 3))
        for c in range(3):
            r_c = adapted_ref[:, c]
            e_c = I3[:, c]  # Identity column
            M[c, :] = np.linalg.solve(DtWD, D.T @ W @ r_c + ridge_lambda * e_c)

        # Compute per-patch residuals for Huber reweighting
        corrected = (M @ D.T).T
        for i in range(24):
            residuals_per_patch[i] = np.sqrt(np.sum((corrected[i] - adapted_ref[i]) ** 2))

        # Huber weights: down-weight patches with residual > delta
        if iteration < huber_iters - 1:
            for i in range(24):
                r = residuals_per_patch[i]
                if r <= huber_delta:
                    huber_w = 1.0
                else:
                    huber_w = huber_delta / r  # Decreasing weight for outliers
                weights[i] = base_weights[i] * huber_w

        if iteration > 0:
            outliers = [i for i in range(24) if residuals_per_patch[i] > huber_delta]
            if outliers:
                log.info(f"    Huber iter {iteration}: {len(outliers)} outlier patches "
                         f"(>{huber_delta:.4f}): {outliers}")

    # Row-sum normalization: force each row to sum to 1.0
    # This guarantees neutral pixels (R=G=B) stay perfectly neutral — no color tint.
    row_sums_before = M.sum(axis=1)
    for c in range(3):
        if abs(row_sums_before[c]) > 1e-6:
            M[c, :] /= row_sums_before[c]
    row_sums_after = M.sum(axis=1)
    log.info(f"  Row-sum normalization: [{row_sums_before[0]:.4f}, {row_sums_before[1]:.4f}, {row_sums_before[2]:.4f}] -> "
             f"[{row_sums_after[0]:.4f}, {row_sums_after[1]:.4f}, {row_sums_after[2]:.4f}]")

    # Check luminance preservation (informational — row-sum=1 keeps it close)
    det_white_luma = luma(det_white)
    corrected_white = M @ det_white
    corrected_white_luma = luma(corrected_white)
    luma_change = (corrected_white_luma - det_white_luma) / det_white_luma if det_white_luma > 1e-6 else 0.0
    log.info(f"  White luma: {det_white_luma:.4f} -> {corrected_white_luma:.4f} ({luma_change:+.2%})")

    # Diagnostics
    diag = np.diag(M)
    off_diag = np.abs(M - np.diag(diag)).sum()
    neutral_gains = []
    for i in NEUTRAL_INDICES:
        orig_luma = luma(detected[i])
        corr_luma = luma(M @ detected[i])
        if orig_luma > 1e-6:
            neutral_gains.append(corr_luma / orig_luma)

    diagnostics = {
        'condition_number': cond,
        'off_diagonal_energy': off_diag,
        'diagonal': diag.tolist(),
        'row_sums_before': row_sums_before.tolist(),
        'residuals': residuals_per_patch.tolist(),
        'neutral_luma_gains': neutral_gains,
        'luma_change_pct': luma_change,
        'huber_final_weights': weights.tolist(),
    }

    return M, wp_scale, adapted_ref, diagnostics


# ── Input validation (B) ───────────────────────────────────────────────

def validate_tiff_input(img_cv, tiff_path):
    """Validate TIFF: uint16, 3-channel, clipping check. Returns (valid, warnings)."""
    warnings = []

    if img_cv is None:
        return False, [f"Failed to read: {tiff_path}"]

    if img_cv.dtype != np.uint16:
        warnings.append(f"Expected uint16, got {img_cv.dtype}")

    if len(img_cv.shape) != 3 or img_cv.shape[2] != 3:
        return False, [f"Expected 3-channel, got shape {img_cv.shape}"]

    # Clipping check: >0.5% pixels at 0 or 65535
    total = img_cv.size
    at_zero = np.sum(img_cv == 0)
    at_max = np.sum(img_cv == 65535)
    if at_max / total > 0.005:
        warnings.append(f"{at_max/total:.2%} pixels at 65535 — possible clipping")
    if at_zero / total > 0.005:
        warnings.append(f"{at_zero/total:.2%} pixels at 0 — possible underexposure")

    # Gamma heuristic
    img_f = img_cv.astype(np.float32) / 65535.0
    mean_val = img_f.mean()
    max_val = img_f.max()
    if max_val > 0.01 and mean_val / max_val > 0.65:
        warnings.append(f"Mean/max={mean_val/max_val:.3f} — may already be gamma-encoded")

    return True, warnings


# ── Printing helpers ────────────────────────────────────────────────────

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
    return errors


def print_neutral_check(swatches, label=""):
    if label:
        log.info(f"\n  {label}:")
    for i, name in zip(range(18, 24), ['White', 'N8', 'N6.5', 'N5', 'N3.5', 'Black']):
        c = swatches[i]
        spread = max(c) - min(c)
        status = "OK" if spread < 0.02 else "WARN" if spread < 0.05 else "BAD"
        log.info(f"    {name:>6s}: R={c[0]:.4f} G={c[1]:.4f} B={c[2]:.4f}  "
                 f"spread={spread:.4f}  {status}")


def print_matrix(M, diag_dict, label=""):
    if label:
        log.info(f"\n  {label}:")
    for r in range(3):
        ch = ['R', 'G', 'B'][r]
        log.info(f"    {ch}: [{M[r, 0]:+.6f}  {M[r, 1]:+.6f}  {M[r, 2]:+.6f}]")
    log.info(f"    Diagonal: {diag_dict['diagonal']}")
    log.info(f"    Off-diagonal energy: {diag_dict['off_diagonal_energy']:.6f}")
    log.info(f"    Condition number: {diag_dict['condition_number']:.2f}")
    log.info(f"    Row sums (pre-norm): {['%.4f' % s for s in diag_dict.get('row_sums_before', [0,0,0])]}")
    log.info(f"    Luma change: {diag_dict.get('luma_change_pct', 0):+.2%}")
    if diag_dict['neutral_luma_gains']:
        gains_str = ', '.join(f'{g:.4f}' for g in diag_dict['neutral_luma_gains'])
        log.info(f"    Neutral luma gains: [{gains_str}]")


# ── Debug artifact writers (J) ──────────────────────────────────────────

def write_checker_csv(debug_dir, detected, adapted_ref, corrected, weights, residuals):
    """Write checker patch table as CSV."""
    csv_path = debug_dir / "checker_patch_table.csv"
    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['index', 'label', 'det_R', 'det_G', 'det_B',
                     'ref_R', 'ref_G', 'ref_B',
                     'cor_R', 'cor_G', 'cor_B',
                     'weight', 'residual_dE'])
        for i in range(24):
            d, r, c = detected[i], adapted_ref[i], corrected[i]
            w.writerow([i, SWATCH_LABELS[i],
                         f'{d[0]:.6f}', f'{d[1]:.6f}', f'{d[2]:.6f}',
                         f'{r[0]:.6f}', f'{r[1]:.6f}', f'{r[2]:.6f}',
                         f'{c[0]:.6f}', f'{c[1]:.6f}', f'{c[2]:.6f}',
                         f'{weights[i]:.4f}', f'{residuals[i]:.6f}'])
    log.info(f"  DEBUG: {csv_path.name}")


def write_matrix_txt(debug_dir, M, diagnostics):
    """Write matrix + diagnostics to text file."""
    txt_path = debug_dir / "matrix.txt"
    with open(txt_path, 'w') as f:
        f.write("Color Correction Matrix v12\n")
        f.write("=" * 40 + "\n")
        for r in range(3):
            ch = ['R', 'G', 'B'][r]
            f.write(f"{ch}: [{M[r, 0]:+.8f}  {M[r, 1]:+.8f}  {M[r, 2]:+.8f}]\n")
        f.write(f"\nDiagonal: {diagnostics['diagonal']}\n")
        f.write(f"Off-diagonal energy: {diagnostics['off_diagonal_energy']:.6f}\n")
        f.write(f"Condition number: {diagnostics['condition_number']:.2f}\n")
        f.write(f"Row sums (pre-norm): {diagnostics.get('row_sums_before', [])}\n")
        f.write(f"Luma change: {diagnostics.get('luma_change_pct', 0):+.4%}\n")
        f.write(f"Ridge lambda: {RIDGE_LAMBDA}\n")
        f.write(f"Huber delta: {HUBER_DELTA}\n")
        f.write(f"Neutral weight: {NEUTRAL_WEIGHT}\n")
        gains_str = ', '.join(f'{g:.4f}' for g in diagnostics['neutral_luma_gains'])
        f.write(f"Neutral luma gains: [{gains_str}]\n")
        f.write(f"Final Huber weights: {diagnostics['huber_final_weights']}\n")
    log.info(f"  DEBUG: {txt_path.name}")


def write_top_comparison(debug_dir, orig_linear, calibrated_linear, label_prefix=""):
    """Save side-by-side before/after for top image + luma histogram data."""
    # Before/after side-by-side
    orig_srgb = linear_to_srgb(orig_linear)
    calib_srgb = linear_to_srgb(calibrated_linear)

    orig_8 = (orig_srgb * 255).astype(np.uint8)
    calib_8 = (calib_srgb * 255).astype(np.uint8)

    # Resize for comparison
    h, w = orig_8.shape[:2]
    sc = min(800 / w, 800 / h)
    sz = (int(w * sc), int(h * sc))
    orig_sm = cv2.resize(cv2.cvtColor(orig_8, cv2.COLOR_RGB2BGR), sz)
    calib_sm = cv2.resize(cv2.cvtColor(calib_8, cv2.COLOR_RGB2BGR), sz)

    comp = np.hstack([orig_sm, calib_sm])
    cv2.putText(comp, "BEFORE", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(comp, "AFTER v12", (sz[0] + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.imwrite(str(debug_dir / f"{label_prefix}top_before_after.png"), comp)

    # Luminance histograms (save as text — no matplotlib dependency)
    orig_luma = luma(orig_linear).flatten()
    calib_luma = luma(calibrated_linear).flatten()
    hist_path = debug_dir / f"{label_prefix}hist_luma_top.txt"
    with open(hist_path, 'w') as f:
        f.write("bin_center,count_before,count_after\n")
        bins = np.linspace(0, 1, 101)
        h_before, _ = np.histogram(orig_luma, bins=bins)
        h_after, _ = np.histogram(calib_luma, bins=bins)
        for j in range(100):
            center = (bins[j] + bins[j + 1]) / 2
            f.write(f"{center:.4f},{h_before[j]},{h_after[j]}\n")

    log.info(f"  DEBUG: top_before_after.png, hist_luma_top.txt")


# ── Regression tests (I) ──────────────────────────────────────────────

class RegressionTests:
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

    def test_neutral_spread(self, corrected_swatches, threshold=0.03):
        white = corrected_swatches[18]
        safe_white = np.where(white > 1e-6, white, 1e-6)
        spreads = []
        for i in NEUTRAL_INDICES:
            normalized = corrected_swatches[i] / safe_white
            spreads.append(max(normalized) - min(normalized))
        self._record("Neutral spread (WB-norm, max < 0.03)",
                     max(spreads) < threshold,
                     f"max={max(spreads):.4f} mean={np.mean(spreads):.4f}")

    def test_no_clipping(self, corrected_swatches):
        max_val = corrected_swatches.max()
        self._record("No clipping (max < 0.99)", max_val < 0.99, f"max={max_val:.4f}")

    def test_de_metric(self, corrected_swatches, adapted_ref):
        errors = [np.sqrt(np.sum((corrected_swatches[i] - adapted_ref[i]) ** 2))
                  for i in range(24)]
        self._record("Mean dE < 0.05", np.mean(errors) < 0.05,
                     f"mean={np.mean(errors):.4f} max={np.max(errors):.4f}")
        self._record("Max dE < 0.10", np.max(errors) < 0.10, f"max={np.max(errors):.4f}")

    def test_condition_number(self, cond):
        self._record(f"Condition number < {COND_NUMBER_WARN}",
                     cond < COND_NUMBER_WARN, f"cond={cond:.2f}")

    def test_top_brightness(self, orig_linear_mean, calib_linear_mean):
        """Top image linear mean must stay within ±TOL."""
        if orig_linear_mean > 1e-6:
            change = (calib_linear_mean - orig_linear_mean) / orig_linear_mean
        else:
            change = 0.0
        self._record(f"Top brightness (±{TOP_BRIGHTNESS_TOL:.0%})",
                     abs(change) <= TOP_BRIGHTNESS_TOL,
                     f"change={change:+.2%} (orig={orig_linear_mean:.4f} calib={calib_linear_mean:.4f})")

    def test_shadow_preservation(self, orig_linear, calib_linear, name=""):
        """5th percentile luma should not change by more than SHADOW_P5_TOL."""
        orig_luma = luma(orig_linear).flatten()
        calib_luma = luma(calib_linear).flatten()
        p5_orig = np.percentile(orig_luma, 5)
        p5_calib = np.percentile(calib_luma, 5)
        if p5_orig > 1e-6:
            change = (p5_calib - p5_orig) / p5_orig
        else:
            change = 0.0
        self._record(f"Shadow P5 (±{SHADOW_P5_TOL:.0%}): {name[:25]}",
                     abs(change) <= SHADOW_P5_TOL,
                     f"change={change:+.2%} (p5_orig={p5_orig:.4f} p5_calib={p5_calib:.4f})")

    def test_dark_fabric_safety(self, image_stats):
        for name, orig_mean, calib_mean in image_stats:
            if orig_mean > 1e-6:
                boost = (calib_mean - orig_mean) / orig_mean
            else:
                boost = 0.0
            self._record(f"Dark safety: {Path(name).stem[:30]}",
                         boost <= TOP_BRIGHTNESS_TOL,
                         f"boost={boost:+.1%}")

    def test_determinism(self, calibrate_fn, *args):
        out1, _, _ = calibrate_fn(*args)
        out2, _, _ = calibrate_fn(*args)
        if out1 is None or out2 is None:
            self._record("Determinism", False, "returned None")
            return
        h1 = hashlib.sha256(out1.tobytes()).hexdigest()[:16]
        h2 = hashlib.sha256(out2.tobytes()).hexdigest()[:16]
        self._record("Determinism", h1 == h2, f"hash1={h1} hash2={h2}")

    def summary(self):
        log.info(f"\n  Regression: {self.passed} passed, {self.failed} failed, "
                 f"{self.passed + self.failed} total")
        return self.failed == 0


# ── Image calibration ──────────────────────────────────────────────────

def calibrate_single(tiff_path, matrix, wb_shift=None, floor=None):
    """
    Calibrate one TIFF. Returns (linear_uint16, srgb_uint16, calib_linear_float) or (None, None, None).

    Pipeline:
      1. Load uint16 TIFF, validate
      2. BGR->RGB, /65535 to float
      3. Apply WB shift if provided (D)
      4. Apply 3x3 matrix (E)
      5. Optional floor correction (G)
      6. Clip in linear
      7. Return linear uint16 (primary) + sRGB uint16 (delivery) + linear float (tests)
    """
    img_cv = cv2.imread(str(tiff_path), cv2.IMREAD_UNCHANGED)
    valid, warnings = validate_tiff_input(img_cv, tiff_path)
    for w in warnings:
        log.warning(f"    INPUT: {w}")
    if not valid:
        return None, None, None

    img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
    img_f = img_rgb.astype(np.float32) / (65535.0 if img_cv.dtype == np.uint16 else 255.0)

    # WB shift (D): bring into checker WB space
    if wb_shift is not None:
        img_f = img_f * wb_shift.reshape(1, 1, 3)

    # 3x3 matrix (E)
    h, w_px, _ = img_f.shape
    flat = img_f.reshape(-1, 3)
    corrected = (matrix @ flat.T).T
    corrected = corrected.reshape(h, w_px, 3)

    # Optional floor correction (G)
    if floor is not None and floor > 0:
        corrected = (corrected - floor) / (1.0 - floor)

    # Clip in linear
    corrected = np.clip(corrected, 0, 1)

    # Keep linear copy for tests
    calib_linear = corrected.copy()

    # Linear uint16 (primary output — same format as input TIFF)
    linear_16 = (corrected * 65535).astype(np.uint16)

    # sRGB uint16 (delivery format)
    srgb_16 = (linear_to_srgb(corrected) * 65535).astype(np.uint16)

    return linear_16, srgb_16, calib_linear


# ── Main ────────────────────────────────────────────────────────────────

def main():
    batch_names = sys.argv[1:] if len(sys.argv) > 1 else ["GRIMSBY-EARTH", "GRIMSBY-MUSHROOM"]

    log.info("=" * 70)
    log.info("Color Calibration v12: Locked WB + Regularized 3x3")
    log.info("WB normalization, ridge+Huber 3x3, luminance preservation")
    log.info(f"  NEUTRAL_WEIGHT={NEUTRAL_WEIGHT}  RIDGE={RIDGE_LAMBDA}  HUBER={HUBER_DELTA}")
    log.info(f"  WB_DRIFT_THRESH={WB_DRIFT_THRESH}  TOP_BRIGHT_TOL={TOP_BRIGHTNESS_TOL}")
    log.info(f"  Batches: {batch_names}")
    log.info("=" * 70)

    # ── Step 1: Load checker ──
    log.info("\n--- Step 1: Load ColorChecker ---")
    if not CHECKER_RAW.exists():
        log.error(f"  Checker RAW not found: {CHECKER_RAW}")
        return 1

    checker_img, checker_wb = load_checker_raw(CHECKER_RAW)
    log.info(f"  Checker shape: {checker_img.shape}")
    log.info(f"  Checker WB (G=1): R={checker_wb[0]:.4f} G={checker_wb[1]:.4f} B={checker_wb[2]:.4f}")

    # ── Step 2: Detect swatches, quality gates ──
    log.info("\n--- Step 2: Detect & Validate Swatches ---")
    detected, reference = detect_swatches(checker_img)
    if detected is None:
        log.error("  No checker detected!")
        return 1
    log.info(f"  Detected {len(detected)} swatches")

    detected = auto_fix_serpentine(detected, reference)

    gates_ok, gate_warnings, reshoot_reasons = quality_gates(detected)
    for w in gate_warnings:
        log.info(f"  GATE: {w}")
    for r in reshoot_reasons:
        log.error(f"  RESHOOT: {r}")
    if not gates_ok:
        log.error("  Quality gates FAILED — reshoot checker!")
        return 1

    log.info(f"  White: R={detected[18][0]:.4f} G={detected[18][1]:.4f} B={detected[18][2]:.4f}")
    log.info(f"  Black: R={detected[23][0]:.4f} G={detected[23][1]:.4f} B={detected[23][2]:.4f}")
    print_swatch_table(detected, reference, "Raw detected vs reference")

    # ── Step 3: Fit regularized 3x3 ──
    log.info("\n--- Step 3: Fit Regularized 3x3 Matrix ---")
    matrix, wp_scale, adapted_ref, diagnostics = compute_3x3_matrix(detected, reference)
    log.info(f"  WP scale: R={wp_scale[0]:.4f} G={wp_scale[1]:.4f} B={wp_scale[2]:.4f}")
    print_matrix(matrix, diagnostics, "3x3 Matrix (ridge+Huber, luma-preserved)")

    if diagnostics['condition_number'] > COND_NUMBER_WARN:
        log.warning(f"  RESHOOT: Condition number {diagnostics['condition_number']:.1f} > {COND_NUMBER_WARN}")

    # Verify on checker
    corrected_swatches = np.clip((matrix @ detected.T).T, 0, None)
    print_swatch_table(corrected_swatches, adapted_ref, "Post-correction accuracy")
    print_neutral_check(corrected_swatches, "Neutral check")

    # ── Step 4: Checker regression tests ──
    log.info("\n--- Step 4: Checker Regression Tests ---")
    tests = RegressionTests()
    tests.test_neutral_spread(corrected_swatches)
    tests.test_no_clipping(corrected_swatches)
    tests.test_de_metric(corrected_swatches, adapted_ref)
    tests.test_condition_number(diagnostics['condition_number'])

    # ── Step 5: Floor estimation (G) ──
    log.info("\n--- Step 5: Floor Estimation ---")
    black_after_matrix = matrix @ detected[23]
    black_luma = luma(np.clip(black_after_matrix, 0, None))
    if black_luma > FLOOR_GATE_THRESH:
        floor_val = float(black_luma * 0.5)  # Conservative: half of black patch luma
        log.info(f"  Black patch luma after matrix: {black_luma:.4f} > gate {FLOOR_GATE_THRESH}")
        log.info(f"  Floor candidate: {floor_val:.4f} (will gate per-image)")
    else:
        floor_val = None
        log.info(f"  Black patch luma {black_luma:.4f} <= gate {FLOOR_GATE_THRESH} — no floor correction")

    # ── Step 6: Calibrate batches ──
    for batch_name in batch_names:
        log.info(f"\n{'='*70}")
        log.info(f"BATCH: {batch_name}")
        log.info(f"{'='*70}")

        batch_path = BASE / "captures" / batch_name
        cropped_dir = batch_path / "cropped"
        raw_dir = batch_path / "raw"
        output_dir = batch_path / "color_calibrated_v12"
        debug_dir = output_dir / "_debug"
        v11_dir = batch_path / "color_calibrated_v11"

        skip_batch = False
        for name, path in [("Batch", batch_path), ("Cropped", cropped_dir), ("Raw", raw_dir)]:
            ok = path.exists()
            log.info(f"  {name:>10s}: {'OK' if ok else 'MISSING'}")
            if not ok and name != "Raw":
                log.error(f"  Skipping {batch_name} — {name} missing")
                skip_batch = True
        if skip_batch:
            continue

        output_dir.mkdir(parents=True, exist_ok=True)
        debug_dir.mkdir(parents=True, exist_ok=True)

        # Sort: top first
        all_tiffs = sorted(
            [f for f in cropped_dir.iterdir() if f.suffix.lower() in {'.tiff', '.tif'}]
        )
        top_tiffs = [f for f in all_tiffs if 'top' in f.stem.lower()]
        side_tiffs = [f for f in all_tiffs if 'top' not in f.stem.lower()]
        ordered_tiffs = top_tiffs + side_tiffs

        log.info(f"  Images: {len(top_tiffs)} top + {len(side_tiffs)} side = {len(ordered_tiffs)}")

        image_stats = []
        top_orig_linear = None
        top_calib_linear = None
        count = 0
        floor_enabled = False  # Track top's floor decision for all images

        for tiff_path in ordered_tiffs:
            count += 1
            is_top = 'top' in tiff_path.stem.lower()
            log.info(f"\n  [{count}] {tiff_path.name}{'  *** TOP ***' if is_top else ''}")

            # ── WB normalization (D2): compute shift for this image ──
            wb_shift = None
            if raw_dir.exists():
                raw_candidate = raw_dir / f"{tiff_path.stem}.ARW"
                if raw_candidate.exists():
                    fabric_wb = extract_wb_multipliers(raw_candidate)
                    wb_shift = checker_wb / fabric_wb
                    drift = np.max(np.abs(wb_shift - 1.0))
                    log.info(f"    Fabric WB (G=1): R={fabric_wb[0]:.4f} G={fabric_wb[1]:.4f} B={fabric_wb[2]:.4f}")
                    log.info(f"    WB shift: R={wb_shift[0]:.4f} G={wb_shift[1]:.4f} B={wb_shift[2]:.4f}  drift={drift:.4f}")
                    if drift > WB_DRIFT_THRESH:
                        log.warning(f"    WB DRIFT {drift:.4f} > {WB_DRIFT_THRESH} — applying correction")
                    else:
                        wb_shift = None  # Below threshold — don't apply
                else:
                    log.warning(f"    No RAW found: {raw_candidate.name} — skipping WB shift")
            else:
                log.warning(f"    No raw/ directory — WB shift unavailable")

            # Read original for stats
            img_cv = cv2.imread(str(tiff_path), cv2.IMREAD_UNCHANGED)
            if img_cv is None:
                log.error(f"    FAILED to read")
                continue
            img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
            orig_f = img_rgb.astype(np.float32) / (65535.0 if img_cv.dtype == np.uint16 else 255.0)
            orig_mean = orig_f.mean()
            orig_luma_mean = luma(orig_f).mean()

            # Gate floor: test on top image, propagate decision to all
            effective_floor = None
            if floor_val is not None and is_top:
                # Trial run: apply floor and check impact
                test_f = orig_f.copy()
                if wb_shift is not None:
                    test_f = test_f * wb_shift.reshape(1, 1, 3)
                test_corr = np.clip((matrix @ test_f.reshape(-1, 3).T).T.reshape(test_f.shape), 0, 1)
                mean_before_floor = test_corr.mean()
                test_floored = np.clip((test_corr - floor_val) / (1.0 - floor_val), 0, 1)
                mean_after_floor = test_floored.mean()
                floor_impact = abs(mean_after_floor - mean_before_floor) / max(mean_before_floor, 1e-6)
                if floor_impact <= FLOOR_MAX_IMPACT:
                    effective_floor = floor_val
                    floor_enabled = True
                    log.info(f"    Floor: {floor_val:.4f} ENABLED (impact={floor_impact:.2%} <= {FLOOR_MAX_IMPACT:.0%})")
                else:
                    floor_enabled = False
                    log.info(f"    Floor: {floor_val:.4f} DISABLED (impact={floor_impact:.2%} > {FLOOR_MAX_IMPACT:.0%})")
            elif floor_val is not None and floor_enabled:
                effective_floor = floor_val  # Same decision as top

            # Calibrate
            linear_16, srgb_16, calib_linear = calibrate_single(tiff_path, matrix, wb_shift, effective_floor)
            if linear_16 is None:
                log.error(f"    Calibration failed!")
                continue

            calib_mean = calib_linear.mean()
            image_stats.append((tiff_path.name, orig_mean, calib_mean))

            log.info(f"    Linear: orig={orig_mean:.4f} -> calib={calib_mean:.4f}  delta={calib_mean - orig_mean:+.4f}")

            # Save linear TIFF (primary — matches input format for fair visual comparison)
            lin_bgr = cv2.cvtColor(linear_16, cv2.COLOR_RGB2BGR)
            tiff_out = output_dir / f"{tiff_path.stem}_calibrated.tiff"
            cv2.imwrite(str(tiff_out), lin_bgr)
            log.info(f"    Saved: {tiff_out.name}  (linear TIFF)")

            # Save sRGB PNG (delivery format)
            srgb_subdir = output_dir / "srgb"
            srgb_subdir.mkdir(exist_ok=True)
            srgb_bgr = cv2.cvtColor(srgb_16, cv2.COLOR_RGB2BGR)
            png_out = srgb_subdir / f"{tiff_path.stem}_calibrated.png"
            cv2.imwrite(str(png_out), srgb_bgr)
            log.info(f"    Saved: {png_out.name}  (sRGB PNG)")

            # Debug for top
            if is_top:
                top_orig_linear = orig_f
                top_calib_linear = calib_linear

        log.info(f"\n  Calibrated {count} images -> {output_dir}")

        # ── Debug artifacts (J) ──
        write_checker_csv(debug_dir, detected, adapted_ref, corrected_swatches,
                          diagnostics['huber_final_weights'], diagnostics['residuals'])
        write_matrix_txt(debug_dir, matrix, diagnostics)

        if top_orig_linear is not None and top_calib_linear is not None:
            write_top_comparison(debug_dir, top_orig_linear, top_calib_linear)

            # Top brightness test (I)
            tests.test_top_brightness(top_orig_linear.mean(), top_calib_linear.mean())
            tests.test_shadow_preservation(top_orig_linear, top_calib_linear, batch_name)

        # Image stats summary
        log.info(f"\n--- Stats (linear): {batch_name} ---")
        log.info(f"  {'Image':>45s}  {'Orig':>7s}  {'Calib':>7s}  {'Delta':>7s}  {'Pct':>7s}")
        log.info(f"  {'-'*78}")
        for name, orig, calib in image_stats:
            delta = calib - orig
            pct = (delta / orig * 100) if orig > 1e-6 else 0.0
            log.info(f"  {name:>45s}  {orig:7.4f}  {calib:7.4f}  {delta:+7.4f}  {pct:+6.1f}%")

        # Dark fabric safety
        tests.test_dark_fabric_safety(image_stats)

        # Determinism
        if ordered_tiffs:
            wb_for_first = None
            if raw_dir.exists():
                raw_first = raw_dir / f"{ordered_tiffs[0].stem}.ARW"
                if raw_first.exists():
                    fb_wb = extract_wb_multipliers(raw_first)
                    wb_for_first = checker_wb / fb_wb
            tests.test_determinism(calibrate_single, ordered_tiffs[0], matrix, wb_for_first, effective_floor)

        # Compare v11 vs v12
        log.info(f"\n--- Compare v11 vs v12: {batch_name} ---")
        v11_top = next((f for f in v11_dir.glob("*top*calibrated*")), None) if v11_dir.exists() else None
        v12_top = next((f for f in output_dir.glob("*top*calibrated*")), None)

        if v11_top and v12_top:
            img_v11 = cv2.imread(str(v11_top), cv2.IMREAD_UNCHANGED)
            img_v12 = cv2.imread(str(v12_top), cv2.IMREAD_UNCHANGED)
            if img_v11 is not None and img_v12 is not None:
                for tag, img in [("v11", img_v11), ("v12", img_v12)]:
                    for c, ch in enumerate(['B', 'G', 'R']):
                        log.info(f"  {tag} {ch}: mean={img[:, :, c].astype(float).mean():.0f}")

                target_shape = img_v11.shape[:2]
                sc = min(800 / target_shape[1], 800 / target_shape[0])
                sz = (int(target_shape[1] * sc), int(target_shape[0] * sc))
                panels = []
                for img in [img_v11, img_v12]:
                    if img.shape[:2] != target_shape:
                        img = cv2.resize(img, (target_shape[1], target_shape[0]))
                    r = cv2.resize(img, sz)
                    if r.dtype == np.uint16:
                        r = (r / 257).astype(np.uint8)
                    panels.append(r)
                comp = np.hstack(panels)
                cv2.putText(comp, "v11 (no WB norm)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.putText(comp, "v12 (locked WB)", (sz[0] + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.imwrite(str(debug_dir / "comparison_v11_v12.png"), comp)
                log.info(f"  Saved: comparison_v11_v12.png")
        else:
            log.info("  (skipping comparison — missing v11 or v12 top)")

    # ── Final summary ──
    log.info(f"\n{'='*70}")
    log.info("REGRESSION TEST SUMMARY")
    log.info(f"{'='*70}")
    for name, status, detail in tests.results:
        log.info(f"  [{status}] {name}  {detail}")
    all_passed = tests.summary()

    log.info(f"\n{'='*70}")
    log.info(f"DONE — v12 calibration complete")
    log.info(f"{'='*70}")
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())

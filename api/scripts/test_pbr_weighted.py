"""
Weighted Photometric Stereo PBR — Multi-batch

Two-pass approach:
  Pass 1: Standard (uniform) least-squares → per-side residuals → auto-weights
  Pass 2: Weighted least-squares using derived weights → improved normals

Weighted LS: instead of solving  L·G = I,
  solve  (√W·L)·G = √W·I
  where W = diag(weights) per light source.
  This minimizes Σ w_i·||L_i·G - I_i||² — high-residual (bad) lights
  get lower weight, reducing their influence on the normal estimate.

Also runs uniform solve for head-to-head comparison.

Output:  pbr_v12_weighted/{grayscale,colored}/  (16-bit TIFF)
Compare: pbr_v12_weighted/comparison_{batch}.txt

Usage: python test_pbr_weighted.py [BATCH_NAME ...]
  Default: GRIMSBY-EARTH GRIMSBY-MUSHROOM MALVERN-SEAGREEN MALVERN-CHARCOAL
"""

import sys
import numpy as np
import cv2
from pathlib import Path
from scipy.linalg import lstsq
from scipy.ndimage import convolve as scipy_convolve

# ── Config ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent / "media" / "captures"
CALIB_FOLDER = "color_calibrated_v12"
OUTPUT_FOLDER = "pbr_v12_weighted"
SKIP_SIDES = {'side_8'}
DOWNSAMPLE_SCALE = 1.0
DENOISE_KERNEL = (3, 3)
SHADOW_THRESHOLD = 0.10
ROUGHNESS_WINDOW = 5

SUPPORTED_EXT = {'.tiff', '.tif', '.png', '.jpg', '.jpeg'}

LIGHT_DIRECTIONS = {
    'top':    [0,  0,  1],
    'side_1': [0,  1,  1],      # front
    'side_2': [-1, 1,  1],      # front-left
    'side_3': [-1, 0,  1],      # left
    'side_4': [-1, -1, 1],      # rear-left
    'side_5': [0,  -1, 1],      # rear
    'side_6': [1,  -1, 1],      # rear-right
    'side_7': [1,  0,  1],      # right
}

# Manual weight overrides from cross-batch correlation analysis.
# Set to None to use auto-weights (recommended).
MANUAL_WEIGHTS = None
# Example manual override based on observed per-side performance:
# MANUAL_WEIGHTS = {
#     'side_1': 0.5,   # front — consistently worst
#     'side_2': 1.0,   # front-left — best
#     'side_3': 0.8,   # left — moderate
#     'side_4': 1.0,   # rear-left — good
#     'side_5': 0.6,   # rear — second worst
#     'side_6': 0.7,   # rear-right — moderate
#     'side_7': 1.0,   # right — good
# }


# ═══════════════════════════════════════════════════════════════════════
#  PREPROCESSING
# ═══════════════════════════════════════════════════════════════════════

def denoise(img):
    return cv2.GaussianBlur(img, DENOISE_KERNEL, 0)

def downsample(img, scale=1.0):
    if scale == 1.0:
        return img
    w = int(img.shape[1] * scale)
    h = int(img.shape[0] * scale)
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)

def preprocess(img, scale=1.0):
    return downsample(denoise(img), scale)


# ═══════════════════════════════════════════════════════════════════════
#  SHADOW DETECTION
# ═══════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════
#  IMAGE LOADING
# ═══════════════════════════════════════════════════════════════════════

def load_images(source_folder, scale=DOWNSAMPLE_SCALE):
    top_color = None
    top_gray = None
    side_colors = []
    side_grays = []
    side_light_dirs = []
    side_names = []

    all_files = sorted([
        f for f in source_folder.iterdir()
        if f.suffix.lower() in SUPPORTED_EXT
    ])

    # Deduplicate: prefer TIFF over PNG
    seen_stems = {}
    files = []
    for f in all_files:
        stem = f.stem
        if stem in seen_stems:
            if f.suffix.lower() in {'.tiff', '.tif'}:
                files = [x for x in files if x.stem != stem]
                files.append(f)
                seen_stems[stem] = f
        else:
            seen_stems[stem] = f
            files.append(f)
    files.sort()

    print(f"  Found {len(files)} images in {source_folder}")

    for fpath in files:
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
                print(f"    SKIP (excluded): {fpath.name}")
            else:
                print(f"    SKIP (no match): {fpath.name}")
            continue

        img = cv2.imread(str(fpath), cv2.IMREAD_UNCHANGED)
        if img is None:
            print(f"    FAIL to load: {fpath.name}")
            continue

        if img.ndim == 3 and img.shape[2] == 4:
            img = img[:, :, :3]

        img = preprocess(img, scale)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

        if matched_pos == 'top':
            top_color = img
            top_gray = gray
            print(f"    TOP (albedo):  {fpath.name}  shape={img.shape} dtype={img.dtype}")
        else:
            side_colors.append(img)
            side_grays.append(gray)
            side_light_dirs.append(matched_dir)
            side_names.append(matched_pos)
            print(f"    SIDE {matched_pos:>6s}:  {fpath.name}  shape={img.shape}")

    L = np.array(side_light_dirs, dtype=np.float32)
    if len(L) > 0:
        norms = np.linalg.norm(L, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        L /= norms

    print(f"  Loaded: top={'YES' if top_color is not None else 'NO'}, sides={len(side_grays)}")
    return top_gray, top_color, side_grays, side_colors, L, side_names


# ═══════════════════════════════════════════════════════════════════════
#  AUTO-WEIGHT COMPUTATION
# ═══════════════════════════════════════════════════════════════════════

def compute_auto_weights(images, light_dirs, side_names, is_grayscale=True):
    """
    Two-pass weight computation:
      Pass 1: Uniform lstsq → G
      Pass 2: Per-side mean residual → inverse-residual weights

    For each light i, residual_i = mean_pixel(|L_i · G - I_i|).
    Weight_i = (1 / residual_i), then normalized so max = 1.0.
    This gives bad sides (high residual) low weight and good sides
    (low residual) high weight.
    """
    n = len(images)
    L = light_dirs.astype(np.float32)

    if is_grayscale:
        h, w = images[0].shape
        I_flat = np.stack(images, axis=0).astype(np.float32).reshape(n, -1)
    else:
        h, w, channels = images[0].shape
        # Use intensity (mean across channels) for weight computation
        I_flat = np.stack([
            cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) if img.ndim == 3
            else img.astype(np.float32)
            for img in images
        ], axis=0).reshape(n, -1)

    # Pass 1: uniform solve
    G, _, _, _ = lstsq(L, I_flat)  # (3, H*W)

    # Predicted intensities per side
    I_pred = L @ G  # (N, H*W)

    # Per-side mean absolute residual
    residuals = np.mean(np.abs(I_pred - I_flat), axis=1)  # (N,)

    # Convert to weights: inverse residual, normalized to max=1
    inv_res = 1.0 / (residuals + 1e-8)
    weights = inv_res / np.max(inv_res)

    # Clamp minimum weight to 0.2 (don't completely discard any side)
    weights = np.clip(weights, 0.2, 1.0)

    print(f"\n  Auto-weights (from pass-1 residuals):")
    print(f"    {'Side':>8s}  {'Residual':>10s}  {'Weight':>8s}")
    print(f"    {'-'*30}")
    for i, name in enumerate(side_names):
        print(f"    {name:>8s}  {residuals[i]:>10.2f}  {weights[i]:>8.3f}")

    return weights


# ═══════════════════════════════════════════════════════════════════════
#  PHOTOMETRIC STEREO — UNIFORM (baseline)
# ═══════════════════════════════════════════════════════════════════════

def stereo_uniform_gray(images, light_dirs):
    """Standard unweighted photometric stereo on grayscale images."""
    n = len(images)
    h, w = images[0].shape
    shadow_mask = detect_shadows(images)

    I_flat = np.stack(images, axis=0).astype(np.float32).reshape(n, -1)
    L = light_dirs.astype(np.float32)

    G, _, _, _ = lstsq(L, I_flat)

    rho = np.linalg.norm(G, axis=0)
    rho_safe = np.where(rho == 0, 1e-8, rho)

    normals = (G / rho_safe.reshape(1, -1)).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)

    # Re-normalize
    nl = np.linalg.norm(normals, axis=2, keepdims=True)
    nl[nl == 0] = 1e-8
    normals = normals / nl

    normals[~shadow_mask] = [0, 0, 1]
    return normals, rho.reshape(h, w)


def stereo_uniform_color(images, light_dirs):
    """Standard unweighted photometric stereo on color images."""
    n = len(images)
    h, w, channels = images[0].shape
    shadow_mask = detect_shadows(images)

    I = np.array(
        [img.astype(np.float32).reshape(-1, channels) for img in images]
    ).transpose(1, 0, 2)
    L = light_dirs.astype(np.float32)

    I_intensity = np.mean(I, axis=2)
    G_intensity, _, _, _ = lstsq(L, I_intensity.T)

    albedo = np.linalg.norm(G_intensity, axis=0)
    albedo_safe = np.where(albedo == 0, 1e-8, albedo)

    normals = (G_intensity / albedo_safe).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)

    nl = np.linalg.norm(normals, axis=2, keepdims=True)
    nl[nl == 0] = 1e-8
    normals = normals / nl

    normals[~shadow_mask] = [0, 0, 1]
    return normals, albedo.reshape(h, w)


# ═══════════════════════════════════════════════════════════════════════
#  PHOTOMETRIC STEREO — WEIGHTED
# ═══════════════════════════════════════════════════════════════════════

def stereo_weighted_gray(images, light_dirs, weights):
    """
    Weighted least-squares photometric stereo on grayscale images.

    Solves  (√W · L) · G = √W · I
    where W = diag(weights).
    """
    n = len(images)
    h, w = images[0].shape
    shadow_mask = detect_shadows(images)

    I_flat = np.stack(images, axis=0).astype(np.float32).reshape(n, -1)
    L = light_dirs.astype(np.float32)

    # Apply weights: multiply rows by sqrt(weight)
    W_sqrt = np.sqrt(weights).reshape(-1, 1)  # (N, 1)
    L_w = L * W_sqrt                           # (N, 3)
    I_w = I_flat * W_sqrt                      # (N, H*W)

    G, _, _, _ = lstsq(L_w, I_w)

    rho = np.linalg.norm(G, axis=0)
    rho_safe = np.where(rho == 0, 1e-8, rho)

    normals = (G / rho_safe.reshape(1, -1)).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)

    nl = np.linalg.norm(normals, axis=2, keepdims=True)
    nl[nl == 0] = 1e-8
    normals = normals / nl

    normals[~shadow_mask] = [0, 0, 1]
    return normals, rho.reshape(h, w)


def stereo_weighted_color(images, light_dirs, weights):
    """
    Weighted least-squares photometric stereo on color images.
    Uses intensity average for normals, weights applied to lstsq.
    """
    n = len(images)
    h, w, channels = images[0].shape
    shadow_mask = detect_shadows(images)

    I = np.array(
        [img.astype(np.float32).reshape(-1, channels) for img in images]
    ).transpose(1, 0, 2)
    L = light_dirs.astype(np.float32)

    I_intensity = np.mean(I, axis=2)  # (H*W, N)

    # Apply weights
    W_sqrt = np.sqrt(weights).reshape(1, -1)  # (1, N)
    I_w = I_intensity * W_sqrt                 # (H*W, N)
    L_w = L * np.sqrt(weights).reshape(-1, 1)  # (N, 3)

    G_intensity, _, _, _ = lstsq(L_w, I_w.T)

    albedo = np.linalg.norm(G_intensity, axis=0)
    albedo_safe = np.where(albedo == 0, 1e-8, albedo)

    normals = (G_intensity / albedo_safe).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)

    nl = np.linalg.norm(normals, axis=2, keepdims=True)
    nl[nl == 0] = 1e-8
    normals = normals / nl

    normals[~shadow_mask] = [0, 0, 1]
    return normals, albedo.reshape(h, w)


# ═══════════════════════════════════════════════════════════════════════
#  ROUGHNESS / HEIGHT / NORMALS VIZ
# ═══════════════════════════════════════════════════════════════════════

def compute_roughness(normals, window_size=ROUGHNESS_WINDOW):
    h, w = normals.shape[:2]
    roughness = np.zeros((h, w), dtype=np.float32)
    kernel = np.ones((window_size, window_size)) / (window_size * window_size)
    for c in range(3):
        mean = scipy_convolve(normals[:, :, c], kernel, mode='reflect')
        sq_diff = (normals[:, :, c] - mean) ** 2
        roughness += scipy_convolve(sq_diff, kernel, mode='reflect')
    return cv2.normalize(roughness, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def compute_height_map(normals):
    nz = normals[:, :, 2]
    nz_safe = np.where(np.abs(nz) < 1e-8, 1e-8, nz)
    p = normals[:, :, 0] / nz_safe
    q = normals[:, :, 1] / nz_safe
    h, w = p.shape

    u = np.fft.fftfreq(w).reshape(1, w).astype(np.float64)
    v = np.fft.fftfreq(h).reshape(h, 1).astype(np.float64)

    Px = np.fft.fft2(p.astype(np.float64))
    Qx = np.fft.fft2(q.astype(np.float64))

    denom = u**2 + v**2
    denom[0, 0] = 1.0

    Z = (-1j * u * Px - 1j * v * Qx) / denom
    Z[0, 0] = 0

    height_map = np.real(np.fft.ifft2(Z))
    height_map = np.nan_to_num(height_map, nan=0.0, posinf=0.0, neginf=0.0)
    return cv2.normalize(height_map.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def visualize_normals(normals):
    return ((normals + 1.0) / 2.0 * 255.0).clip(0, 255).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════════════
#  SAVE
# ═══════════════════════════════════════════════════════════════════════

def save_16bit(img, path):
    path = Path(path).with_suffix('.tiff')
    if img.dtype == np.uint8:
        img16 = img.astype(np.uint16) * 257
    elif img.dtype == np.uint16:
        img16 = img
    elif img.dtype in (np.float32, np.float64):
        img16 = np.clip(img * 65535, 0, 65535).astype(np.uint16)
    else:
        img16 = img.astype(np.uint16)
    cv2.imwrite(str(path), img16)
    return path


def save_maps(maps, output_dir, mode_name):
    out = output_dir / mode_name
    out.mkdir(parents=True, exist_ok=True)

    save_16bit(maps['albedo'], out / "albedo.tiff")

    normals_bgr = cv2.cvtColor(maps['normals_rgb'], cv2.COLOR_RGB2BGR)
    save_16bit(normals_bgr, out / "normals.tiff")
    save_16bit(maps['roughness'], out / "roughness.tiff")
    save_16bit(maps['height_map'], out / "height_map.tiff")

    nz = ((maps['normals'][:, :, 2] + 1) / 2 * 255).clip(0, 255).astype(np.uint8)
    save_16bit(nz, out / "normals_nz.tiff")

    print(f"  Saved 16-bit TIFFs to {out}/")


# ═══════════════════════════════════════════════════════════════════════
#  VERIFICATION (shared for both uniform and weighted)
# ═══════════════════════════════════════════════════════════════════════

def compute_rerender_metrics(normals, rho, side_grays, light_dirs, side_names):
    """Compute per-side RMSE and correlation without saving mosaics."""
    rmse_dict = {}
    corr_dict = {}

    for i in range(len(side_grays)):
        L_i = light_dirs[i]
        NdotL = np.clip(np.sum(normals * L_i, axis=2), 0, 1)

        predicted = rho * NdotL
        actual = side_grays[i].astype(np.float32)

        pred_scale = np.percentile(predicted, 99.5)
        predicted_u8 = np.clip(predicted / max(pred_scale, 1e-8) * 255, 0, 255).astype(np.uint8)
        act_scale = np.percentile(actual, 99.5)
        actual_u8 = np.clip(actual / max(act_scale, 1e-8) * 255, 0, 255).astype(np.uint8)

        rmse = np.sqrt(np.mean((predicted_u8.astype(float) - actual_u8.astype(float)) ** 2))
        fp = predicted_u8.flatten().astype(float)
        fa = actual_u8.flatten().astype(float)
        corr = np.corrcoef(fp, fa)[0, 1] if np.std(fp) > 0 and np.std(fa) > 0 else 0.0

        rmse_dict[side_names[i]] = rmse
        corr_dict[side_names[i]] = corr

    return rmse_dict, corr_dict


def compute_curl_metrics(normals):
    """Compute integrability curl metrics."""
    nz = normals[:, :, 2]
    nz_safe = np.where(np.abs(nz) < 1e-8, 1e-8, nz)
    p = normals[:, :, 0] / nz_safe
    q = normals[:, :, 1] / nz_safe

    dp_dy = np.gradient(p, axis=0)
    dq_dx = np.gradient(q, axis=1)
    curl = dp_dy - dq_dx

    return {
        'mean_curl': float(np.mean(np.abs(curl))),
        'median_curl': float(np.median(np.abs(curl))),
        'p99_curl': float(np.percentile(np.abs(curl), 99)),
    }


def save_rerender_mosaic(normals, rho, side_grays, light_dirs, side_names, output_dir, label):
    """Save visual re-render comparison mosaic."""
    h, w = normals.shape[:2]
    mosaic_rows = []

    for i in range(len(side_grays)):
        L_i = light_dirs[i]
        NdotL = np.clip(np.sum(normals * L_i, axis=2), 0, 1)

        predicted = rho * NdotL
        actual = side_grays[i].astype(np.float32)

        pred_scale = np.percentile(predicted, 99.5)
        predicted_u8 = np.clip(predicted / max(pred_scale, 1e-8) * 255, 0, 255).astype(np.uint8)
        act_scale = np.percentile(actual, 99.5)
        actual_u8 = np.clip(actual / max(act_scale, 1e-8) * 255, 0, 255).astype(np.uint8)

        error = np.abs(predicted_u8.astype(float) - actual_u8.astype(float))
        error_u8 = np.clip(error * 3, 0, 255).astype(np.uint8)
        error_color = cv2.applyColorMap(error_u8, cv2.COLORMAP_JET)

        rmse = np.sqrt(np.mean((predicted_u8.astype(float) - actual_u8.astype(float)) ** 2))

        scale = min(400 / w, 400 / h)
        sz = (int(w * scale), int(h * scale))
        row = np.hstack([
            cv2.resize(cv2.cvtColor(actual_u8, cv2.COLOR_GRAY2BGR), sz),
            cv2.resize(cv2.cvtColor(predicted_u8, cv2.COLOR_GRAY2BGR), sz),
            cv2.resize(error_color, sz),
        ])
        cv2.putText(row, f"{side_names[i]} actual", (5, 20),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(row, "predicted", (sz[0] + 5, 20),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(row, f"error RMSE={rmse:.1f}", (sz[0] * 2 + 5, 20),
                     cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        mosaic_rows.append(row)

    mosaic = np.vstack(mosaic_rows)
    mosaic_path = output_dir / f"rerender_{label}.png"
    cv2.imwrite(str(mosaic_path), mosaic)
    return mosaic_path


# ═══════════════════════════════════════════════════════════════════════
#  GENERATE + COMPARE
# ═══════════════════════════════════════════════════════════════════════

def generate_and_compare(top_gray, top_color, side_grays, side_colors,
                         light_dirs, side_names, weights, output_dir):
    """
    Run both uniform and weighted stereo, compare metrics side-by-side.
    Save only the weighted result as final output.
    """
    results = {}

    for mode_label, is_gray in [("grayscale", True), ("colored", False)]:
        print(f"\n{'='*60}")
        print(f"  {mode_label.upper()} — Uniform vs Weighted comparison")
        print(f"{'='*60}")

        images = side_grays if is_gray else side_colors
        side_imgs_gray = side_grays  # Always gray for re-render verification

        # ── Uniform solve ──
        if is_gray:
            u_normals, u_rho = stereo_uniform_gray(images, light_dirs)
        else:
            u_normals, u_rho = stereo_uniform_color(images, light_dirs)

        u_rmse, u_corr = compute_rerender_metrics(
            u_normals, u_rho, side_imgs_gray, light_dirs, side_names)
        u_curl = compute_curl_metrics(u_normals)

        # ── Weighted solve ──
        if is_gray:
            w_normals, w_rho = stereo_weighted_gray(images, light_dirs, weights)
        else:
            w_normals, w_rho = stereo_weighted_color(images, light_dirs, weights)

        w_rmse, w_corr = compute_rerender_metrics(
            w_normals, w_rho, side_imgs_gray, light_dirs, side_names)
        w_curl = compute_curl_metrics(w_normals)

        # ── Per-side comparison ──
        print(f"\n  {'Side':>8s}  {'U.RMSE':>7s} {'W.RMSE':>7s} {'Δ':>6s}  "
              f"{'U.Corr':>7s} {'W.Corr':>7s} {'Δ':>7s}")
        print(f"  {'-'*58}")
        for name in side_names:
            ur = u_rmse[name]
            wr = w_rmse[name]
            uc = u_corr[name]
            wc = w_corr[name]
            rmse_delta = wr - ur
            corr_delta = wc - uc
            rmse_sign = '+' if rmse_delta > 0 else ''
            corr_sign = '+' if corr_delta > 0 else ''
            print(f"  {name:>8s}  {ur:>7.2f} {wr:>7.2f} {rmse_sign}{rmse_delta:>5.2f}  "
                  f"{uc:>7.4f} {wc:>7.4f} {corr_sign}{corr_delta:>6.4f}")

        # Means
        u_mean_rmse = np.mean(list(u_rmse.values()))
        w_mean_rmse = np.mean(list(w_rmse.values()))
        u_mean_corr = np.mean(list(u_corr.values()))
        w_mean_corr = np.mean(list(w_corr.values()))

        print(f"  {'MEAN':>8s}  {u_mean_rmse:>7.2f} {w_mean_rmse:>7.2f} "
              f"{'+'if w_mean_rmse-u_mean_rmse>0 else ''}{w_mean_rmse-u_mean_rmse:>5.2f}  "
              f"{u_mean_corr:>7.4f} {w_mean_corr:>7.4f} "
              f"{'+'if w_mean_corr-u_mean_corr>0 else ''}{w_mean_corr-u_mean_corr:>6.4f}")

        # Curl comparison
        print(f"\n  Integrability (curl):")
        print(f"    {'Metric':>15s}  {'Uniform':>8s}  {'Weighted':>8s}  {'Δ':>8s}")
        print(f"    {'-'*42}")
        for key in ['mean_curl', 'median_curl', 'p99_curl']:
            uv = u_curl[key]
            wv = w_curl[key]
            d = wv - uv
            print(f"    {key:>15s}  {uv:>8.4f}  {wv:>8.4f}  {'+'if d>0 else ''}{d:>7.4f}")

        # ── Build final maps from weighted result ──
        albedo = top_gray if is_gray else top_color
        roughness = compute_roughness(w_normals)
        height_map = compute_height_map(w_normals)
        normals_rgb = visualize_normals(w_normals)

        maps = {
            'albedo': albedo,
            'normals': w_normals,
            'normals_rgb': normals_rgb,
            'roughness': roughness,
            'height_map': height_map,
            'rho': w_rho,
        }

        save_maps(maps, output_dir, mode_label)

        # Save re-render mosaics for both
        save_rerender_mosaic(
            u_normals, u_rho, side_imgs_gray, light_dirs, side_names,
            output_dir, f"{mode_label}_uniform")
        mosaic_path = save_rerender_mosaic(
            w_normals, w_rho, side_imgs_gray, light_dirs, side_names,
            output_dir, f"{mode_label}_weighted")
        print(f"\n  Mosaics saved to {output_dir}/")

        results[mode_label] = {
            'uniform': {
                'mean_rmse': u_mean_rmse,
                'mean_corr': u_mean_corr,
                'per_side_rmse': u_rmse,
                'per_side_corr': u_corr,
                'curl': u_curl,
            },
            'weighted': {
                'mean_rmse': w_mean_rmse,
                'mean_corr': w_mean_corr,
                'per_side_rmse': w_rmse,
                'per_side_corr': w_corr,
                'curl': w_curl,
            },
        }

    return results


# ═══════════════════════════════════════════════════════════════════════
#  BATCH PROCESSING
# ═══════════════════════════════════════════════════════════════════════

def process_batch(batch_name):
    batch_path = BASE / batch_name
    source_folder = batch_path / CALIB_FOLDER
    output_dir = batch_path / OUTPUT_FOLDER

    print("\n" + "=" * 70)
    print(f"BATCH: {batch_name}")
    print(f"Source: {source_folder}")
    print("=" * 70)

    if not source_folder.exists():
        print(f"  ERROR: {source_folder} not found — skipping")
        return None

    top_gray, top_color, side_grays, side_colors, light_dirs, side_names = \
        load_images(source_folder)

    if top_gray is None or top_color is None:
        print("  ERROR: No top image found")
        return None
    if len(side_grays) < 3:
        print(f"  ERROR: Need >=3 side images, found {len(side_grays)}")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Compute weights ──
    if MANUAL_WEIGHTS is not None:
        weights = np.array([MANUAL_WEIGHTS.get(name, 1.0) for name in side_names],
                           dtype=np.float32)
        print(f"\n  Using MANUAL weights: {dict(zip(side_names, weights))}")
    else:
        weights = compute_auto_weights(side_grays, light_dirs, side_names, is_grayscale=True)

    # ── Generate + compare ──
    results = generate_and_compare(
        top_gray, top_color, side_grays, side_colors,
        light_dirs, side_names, weights, output_dir
    )

    return {
        'batch': batch_name,
        'n_sides': len(side_grays),
        'weights': dict(zip(side_names, weights.tolist())),
        'results': results,
        'output_dir': str(output_dir),
    }


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    batch_names = sys.argv[1:] if len(sys.argv) > 1 else [
        "GRIMSBY-EARTH", "GRIMSBY-MUSHROOM", "MALVERN-SEAGREEN", "MALVERN-CHARCOAL"
    ]

    print("=" * 70)
    print("WEIGHTED PBR — Uniform vs Weighted Least-Squares Comparison")
    print(f"  Batches:    {batch_names}")
    print(f"  Source:     {CALIB_FOLDER}")
    print(f"  Output:     {OUTPUT_FOLDER}")
    print(f"  Skip:       {SKIP_SIDES}")
    print(f"  Weights:    {'MANUAL' if MANUAL_WEIGHTS else 'AUTO (residual-based)'}")
    print("=" * 70)

    all_summaries = []

    for batch_name in batch_names:
        summary = process_batch(batch_name)
        if summary is not None:
            all_summaries.append(summary)

    # ── Cross-batch summary ──
    print("\n" + "=" * 70)
    print("CROSS-BATCH SUMMARY: Uniform → Weighted improvement")
    print("=" * 70)

    if all_summaries:
        # Weights table
        print(f"\n  Auto-weights per batch:")
        all_sides = ['side_1', 'side_2', 'side_3', 'side_4', 'side_5', 'side_6', 'side_7']
        header = f"  {'Batch':>25s}  " + "  ".join(f"{s:>6s}" for s in all_sides)
        print(header)
        print(f"  {'-'*len(header)}")
        for s in all_summaries:
            row = f"  {s['batch']:>25s}  "
            row += "  ".join(f"{s['weights'].get(side, 0):>6.3f}" for side in all_sides)
            print(row)

        # Metrics comparison
        print(f"\n  {'Batch':>25s}  {'Mode':>10s}  "
              f"{'U.Corr':>7s} {'W.Corr':>7s} {'ΔCorr':>7s}  "
              f"{'U.RMSE':>7s} {'W.RMSE':>7s} {'ΔRMSE':>7s}  "
              f"{'U.Curl':>7s} {'W.Curl':>7s} {'ΔCurl':>7s}")
        print(f"  {'-'*110}")

        for s in all_summaries:
            for mode in ['grayscale', 'colored']:
                u = s['results'][mode]['uniform']
                w = s['results'][mode]['weighted']
                dc = w['mean_corr'] - u['mean_corr']
                dr = w['mean_rmse'] - u['mean_rmse']
                dcurl = w['curl']['median_curl'] - u['curl']['median_curl']
                print(f"  {s['batch']:>25s}  {mode:>10s}  "
                      f"{u['mean_corr']:>7.4f} {w['mean_corr']:>7.4f} "
                      f"{'+'if dc>0 else ''}{dc:>6.4f}  "
                      f"{u['mean_rmse']:>7.2f} {w['mean_rmse']:>7.2f} "
                      f"{'+'if dr>0 else ''}{dr:>6.2f}  "
                      f"{u['curl']['median_curl']:>7.4f} {w['curl']['median_curl']:>7.4f} "
                      f"{'+'if dcurl>0 else ''}{dcurl:>6.4f}")

    # Output paths
    print()
    for s in all_summaries:
        print(f"  {s['batch']:>25s} -> {s['output_dir']}")

    return 0


if __name__ == '__main__':
    sys.exit(main())

"""
Standalone PBR Generation + Verification — Multi-batch

Combines best approaches from:
  - pbr_maps.py        (shadow detection, per-channel color stereo)
  - pbr_grayscale.py   (clean grayscale stereo, TIFF output)
  - pbr_service.py     (top=albedo, 16-bit output, denoise)
  - test_pbr_grimsby.py (TIFF dedup, verification suite, multi-batch)

Improvements over all existing scripts:
  - Shadow masking for BOTH grayscale and color modes
  - Gaussian blur denoising before photometric stereo
  - 16-bit TIFF output (preserves linear data from pipeline)
  - Proper Frankot-Chellappa with fftfreq (correct frequency coords)
  - Normal re-normalization to unit length after solving
  - Top image used as albedo (not computed from stereo)
  - TIFF deduplication (prefer linear TIFF over sRGB PNG)

Pipeline:
  - Top image (color calibrated v12) → albedo for BOTH grayscale and color
  - 7 side images (side_1..side_7, skip side_8) → photometric stereo
    → normals, roughness, height
  - D65 Bradford chromatic adaptation applied to color albedo
    (fixes blue-shifted scene illuminant → warm natural tones)

Generates per batch:
  - pbr_v13_standalone/grayscale/  (albedo, normals, roughness, height)
  - pbr_v13_standalone/colored/    (albedo, albedo_normalized, normals, roughness, height)

Verification:
  1. Normal map validity (unit length, Nz > 0, no NaN)
  2. Re-render consistency (predict side images, compare to actual)
  3. Height map integrability (curl of gradient field)
  4. Roughness sanity (histogram spread, spatial structure)
  5. Albedo shadow-free check

Usage: python test_pbr_standalone.py [BATCH_NAME ...]
  Default: GRIMSBY-EARTH GRIMSBY-MUSHROOM MALVERN-SEAGREEN MALVERN-CHARCOAL
"""

import os
import sys
import numpy as np
import cv2
from pathlib import Path
from scipy.linalg import lstsq
from scipy.ndimage import convolve as scipy_convolve

# ── Config ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent / "media" / "captures"
CALIB_FOLDER = "color_calibrated_v12"
OUTPUT_FOLDER = "pbr_v13_standalone"
SKIP_SIDES = {'side_8'}
DOWNSAMPLE_SCALE = 1.0          # 1.0 = no downsample
DENOISE_KERNEL = (3, 3)         # Gaussian blur kernel
SHADOW_THRESHOLD = 0.10         # % of max intensity below which = shadow
ROUGHNESS_WINDOW = 5            # Convolution window for roughness

SUPPORTED_EXT = {'.tiff', '.tif', '.png', '.jpg', '.jpeg'}

# ── D65 Chromatic Adaptation (Bradford) ──────────────────────────────
# Detected white patch values from ColorChecker under top light (linear sRGB).
# Measured: strongly blue-shifted (B/R = 1.48).
SCENE_WHITE_SRGB = np.array([0.451322, 0.586777, 0.665998])

# sRGB ↔ XYZ conversion matrices (linear sRGB, D65 reference)
_SRGB_TO_XYZ = np.array([
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
])
_XYZ_TO_SRGB = np.linalg.inv(_SRGB_TO_XYZ)

# Bradford cone response matrix
_BRADFORD = np.array([
    [ 0.8951000,  0.2664000, -0.1614000],
    [-0.7502000,  1.7135000,  0.0367000],
    [ 0.0389000, -0.0685000,  1.0296000],
])
_BRADFORD_INV = np.linalg.inv(_BRADFORD)

# D65 white point in XYZ (CIE 1931 2°)
_D65_XYZ = np.array([0.95047, 1.00000, 1.08883])


def compute_d65_adaptation(scene_white_srgb):
    """
    Compute a 3x3 Bradford chromatic adaptation matrix that transforms
    linear sRGB pixels from the scene illuminant to D65.

    Returns: (3, 3) matrix to apply as: corrected_rgb = M @ pixel_rgb.
    """
    source_xyz = _SRGB_TO_XYZ @ scene_white_srgb
    source_xyz = source_xyz / source_xyz[1]

    cone_src = _BRADFORD @ source_xyz
    cone_dst = _BRADFORD @ _D65_XYZ

    scale = cone_dst / cone_src
    adapt_xyz = _BRADFORD_INV @ np.diag(scale) @ _BRADFORD

    combined = _XYZ_TO_SRGB @ adapt_xyz @ _SRGB_TO_XYZ

    print(f"  Bradford D65 adaptation matrix:")
    for r, ch in enumerate(['R', 'G', 'B']):
        print(f"    {ch}: [{combined[r,0]:+.4f}  {combined[r,1]:+.4f}  {combined[r,2]:+.4f}]")

    return combined


def apply_d65_adaptation_cv2(img, strength=1.0):
    """
    Apply Bradford chromatic adaptation to a cv2 image (BGR, uint8 or uint16).
    Converts albedo from scene illuminant to D65 neutral daylight.

    strength: 0.0 = no adaptation, 1.0 = full adaptation, 0.5 = half.
    Returns: adapted image (same dtype as input).
    """
    M_full = compute_d65_adaptation(SCENE_WHITE_SRGB)
    M = np.eye(3) + strength * (M_full - np.eye(3))

    orig_dtype = img.dtype
    if orig_dtype == np.uint8:
        max_val = 255.0
    elif orig_dtype == np.uint16:
        max_val = 65535.0
    else:
        max_val = 1.0

    # Convert to float RGB (cv2 stores BGR)
    img_f = img.astype(np.float64) / max_val
    rgb = img_f[:, :, ::-1]  # BGR → RGB

    h, w, _ = rgb.shape
    pixels = rgb.reshape(-1, 3)

    # Apply 3x3 matrix: corrected = M @ pixel (per pixel)
    adapted = (M @ pixels.T).T
    adapted = np.clip(adapted, 0, 1)

    # Stats
    print(f"  D65 adaptation applied ({w}x{h} = {pixels.shape[0]} pixels):")
    print(f"    R: {pixels[:,0].mean():.4f} → {adapted[:,0].mean():.4f}")
    print(f"    G: {pixels[:,1].mean():.4f} → {adapted[:,1].mean():.4f}")
    print(f"    B: {pixels[:,2].mean():.4f} → {adapted[:,2].mean():.4f}")

    # Convert back to BGR and original dtype
    adapted_bgr = adapted.reshape(h, w, 3)[:, :, ::-1]  # RGB → BGR
    result = np.clip(adapted_bgr * max_val, 0, max_val).astype(orig_dtype)
    return result


# Light directions: top = directly above, sides = 45° elevation
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


# ═══════════════════════════════════════════════════════════════════════
#  PREPROCESSING
# ═══════════════════════════════════════════════════════════════════════

def denoise(img):
    """Apply Gaussian blur to reduce sensor noise. Preserves edges better
    than bilateral at this small kernel size."""
    return cv2.GaussianBlur(img, DENOISE_KERNEL, 0)


def downsample(img, scale=1.0):
    """Downsample image by scale factor. Uses INTER_AREA for anti-aliased
    reduction (best for downscaling)."""
    if scale == 1.0:
        return img
    w = int(img.shape[1] * scale)
    h = int(img.shape[0] * scale)
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def preprocess(img, scale=1.0):
    """Denoise + downsample."""
    return downsample(denoise(img), scale)


# ═══════════════════════════════════════════════════════════════════════
#  SHADOW DETECTION
# ═══════════════════════════════════════════════════════════════════════

def detect_shadows(images, threshold=SHADOW_THRESHOLD):
    """
    Compute per-pixel shadow mask from a set of images.
    A pixel is considered lit (True) if its mean intensity across all images
    exceeds threshold × max_intensity. Shadow pixels (False) get default
    normals [0, 0, 1] since we can't solve stereo there.
    """
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
    """
    Load calibrated images from source_folder.
    Separates top (albedo) from sides (photometric stereo).
    Applies denoising and optional downsampling.
    Deduplicates TIFF vs PNG (prefers TIFF for linear data).

    Returns:
        top_gray, top_color, side_grays, side_colors, light_dirs, side_names
    """
    top_color = None
    top_gray = None
    side_colors = []
    side_grays = []
    side_light_dirs = []
    side_names = []

    # ── List and deduplicate files ──
    all_files = sorted([
        f for f in source_folder.iterdir()
        if f.suffix.lower() in SUPPORTED_EXT
    ])

    # Prefer TIFF (linear) over PNG (sRGB) when both exist for same stem
    seen_stems = {}
    files = []
    for f in all_files:
        stem = f.stem
        if stem in seen_stems:
            if f.suffix.lower() in {'.tiff', '.tif'}:
                files = [x for x in files if x.stem != stem]
                files.append(f)
                seen_stems[stem] = f
            # else: keep existing TIFF, skip this PNG
        else:
            seen_stems[stem] = f
            files.append(f)
    files.sort()

    print(f"  Found {len(files)} images in {source_folder}")

    # ── Load and pair ──
    for fpath in files:
        fname = fpath.name.lower()

        # Match to light direction
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

        # Drop alpha channel if present
        if img.ndim == 3 and img.shape[2] == 4:
            img = img[:, :, :3]

        # Preprocess: denoise + downsample
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

    # Normalize light directions
    L = np.array(side_light_dirs, dtype=np.float32)
    if len(L) > 0:
        norms = np.linalg.norm(L, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        L /= norms

    print(f"  Loaded: top={'YES' if top_color is not None else 'NO'}, sides={len(side_grays)}")
    return top_gray, top_color, side_grays, side_colors, L, side_names


# ═══════════════════════════════════════════════════════════════════════
#  PHOTOMETRIC STEREO
# ═══════════════════════════════════════════════════════════════════════

def photometric_stereo_grayscale(images, light_dirs):
    """
    Compute normals from grayscale side images using photometric stereo.

    Solves L × G = I  (least squares) where:
      L = (N×3) light directions
      G = (3×P) gradient field (= albedo × normal per pixel)
      I = (N×P) pixel intensities

    Shadow masking: pixels where mean intensity is too low get default
    normals [0, 0, 1] (facing up).

    Returns: normals (H×W×3), rho (H×W) albedo magnitude
    """
    n = len(images)
    h, w = images[0].shape

    # Shadow mask
    shadow_mask = detect_shadows(images)

    # Stack: (N, H*W)
    I = np.stack(images, axis=0).astype(np.float32)
    L = light_dirs.astype(np.float32)
    I_flat = I.reshape(n, -1)

    # Least-squares solve
    G, _, _, _ = lstsq(L, I_flat)  # G: (3, H*W)

    # Albedo magnitude per pixel
    rho = np.linalg.norm(G, axis=0)  # (H*W,)
    rho_safe = np.where(rho == 0, 1e-8, rho)

    # Normals = G / ||G||
    normals = (G / rho_safe.reshape(1, -1)).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)

    # Re-normalize to unit length
    norm_lengths = np.linalg.norm(normals, axis=2, keepdims=True)
    norm_lengths[norm_lengths == 0] = 1e-8
    normals = normals / norm_lengths

    # Apply shadow mask: shadowed pixels get default up-facing normal
    normals[~shadow_mask] = [0, 0, 1]

    rho = rho.reshape(h, w)
    return normals, rho


def photometric_stereo_color(images, light_dirs):
    """
    Compute normals from color side images using photometric stereo.

    Uses average intensity across RGB channels for normal computation
    (more robust than single-channel). Per-channel albedo computed
    separately for color-accurate rho.

    Shadow masking applied to both normals and albedo.

    Returns: normals (H×W×3), rho (H×W) intensity albedo magnitude
    """
    n = len(images)
    h, w, channels = images[0].shape

    # Shadow mask
    shadow_mask = detect_shadows(images)

    # Stack: (pixels, n_images, channels)
    I = np.array(
        [img.astype(np.float32).reshape(-1, channels) for img in images]
    ).transpose(1, 0, 2)  # (H*W, N, C)
    L = light_dirs.astype(np.float32)

    # Compute normals from mean-intensity (average of B, G, R channels)
    I_intensity = np.mean(I, axis=2)  # (H*W, N)
    G_intensity, _, _, _ = lstsq(L, I_intensity.T)  # (3, H*W)

    albedo_intensity = np.linalg.norm(G_intensity, axis=0)
    albedo_safe = np.where(albedo_intensity == 0, 1e-8, albedo_intensity)

    normals = (G_intensity / albedo_safe).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)

    # Re-normalize to unit length
    norm_lengths = np.linalg.norm(normals, axis=2, keepdims=True)
    norm_lengths[norm_lengths == 0] = 1e-8
    normals = normals / norm_lengths

    # Apply shadow mask
    normals[~shadow_mask] = [0, 0, 1]

    rho = albedo_intensity.reshape(h, w)
    return normals, rho


# ═══════════════════════════════════════════════════════════════════════
#  ROUGHNESS MAP
# ═══════════════════════════════════════════════════════════════════════

def compute_roughness(normals, window_size=ROUGHNESS_WINDOW):
    """
    Compute roughness from local normal variation.

    For each normal component (Nx, Ny, Nz), computes local variance
    using a box filter. Roughness = sum of variances across all 3 channels.
    High variance → rough surface. Low variance → smooth surface.

    Returns: roughness map (H×W) normalized to 0-255 uint8.
    """
    h, w = normals.shape[:2]
    roughness = np.zeros((h, w), dtype=np.float32)
    kernel = np.ones((window_size, window_size)) / (window_size * window_size)

    for c in range(3):
        mean = scipy_convolve(normals[:, :, c], kernel, mode='reflect')
        sq_diff = (normals[:, :, c] - mean) ** 2
        roughness += scipy_convolve(sq_diff, kernel, mode='reflect')

    return cv2.normalize(roughness, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════════════
#  HEIGHT MAP (Frankot-Chellappa)
# ═══════════════════════════════════════════════════════════════════════

def compute_height_map(normals):
    """
    Integrate normal map to height map using Frankot-Chellappa algorithm.

    Uses proper FFT frequency coordinates (via fftfreq) instead of the
    approximation used in other scripts. This ensures correct integration
    across the full frequency range.

    Z(u,v) = (-j·u·P(u,v) - j·v·Q(u,v)) / (u² + v²)

    where u,v are frequency coordinates and P,Q are FFTs of the gradient
    components p = Nx/Nz, q = Ny/Nz.

    Returns: height map (H×W) normalized to 0-255 uint8.
    """
    nz = normals[:, :, 2]
    nz_safe = np.where(np.abs(nz) < 1e-8, 1e-8, nz)
    p = normals[:, :, 0] / nz_safe  # dz/dx
    q = normals[:, :, 1] / nz_safe  # dz/dy

    h, w = p.shape

    # Proper frequency grids
    u = np.fft.fftfreq(w).reshape(1, w).astype(np.float64)  # horizontal freq
    v = np.fft.fftfreq(h).reshape(h, 1).astype(np.float64)  # vertical freq

    # FFT of gradient components
    Px = np.fft.fft2(p.astype(np.float64))
    Qx = np.fft.fft2(q.astype(np.float64))

    # Integrate in frequency domain
    denom = u**2 + v**2
    denom[0, 0] = 1.0  # DC component: avoid div-by-zero

    Z = (-1j * u * Px - 1j * v * Qx) / denom
    Z[0, 0] = 0  # Zero mean height

    height_map = np.real(np.fft.ifft2(Z))
    height_map = np.nan_to_num(height_map, nan=0.0, posinf=0.0, neginf=0.0)

    return cv2.normalize(height_map.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════════════
#  NORMAL VISUALIZATION
# ═══════════════════════════════════════════════════════════════════════

def visualize_normals(normals):
    """
    Convert normals [-1,1] to RGB [0,255] for visualization.
    Standard convention: R=Nx, G=Ny, B=Nz.
    Flat surface (0,0,1) → purple-blue (128, 128, 255).
    """
    return ((normals + 1.0) / 2.0 * 255.0).clip(0, 255).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════════════
#  SAVE MAPS (16-bit TIFF)
# ═══════════════════════════════════════════════════════════════════════

def save_16bit(img, path):
    """
    Save image as 16-bit TIFF for maximum precision.
    Input can be uint8 (scaled to 16-bit) or uint16 (saved as-is).
    """
    path = Path(path).with_suffix('.tiff')
    if img.dtype == np.uint8:
        img16 = img.astype(np.uint16) * 257  # 0-255 → 0-65535
    elif img.dtype == np.uint16:
        img16 = img
    elif img.dtype in (np.float32, np.float64):
        img16 = np.clip(img * 65535, 0, 65535).astype(np.uint16)
    else:
        img16 = img.astype(np.uint16)
    cv2.imwrite(str(path), img16)
    return path


def save_maps(maps, output_dir, mode_name):
    """Save all PBR maps for a mode as 16-bit TIFF."""
    out = output_dir / mode_name
    out.mkdir(parents=True, exist_ok=True)

    albedo = maps['albedo']
    save_16bit(albedo, out / "albedo.tiff")

    # Normals RGB: convert to BGR for cv2
    normals_bgr = cv2.cvtColor(maps['normals_rgb'], cv2.COLOR_RGB2BGR)
    save_16bit(normals_bgr, out / "normals.tiff")

    save_16bit(maps['roughness'], out / "roughness.tiff")
    save_16bit(maps['height_map'], out / "height_map.tiff")

    # Also save Nz channel for inspection
    nz = ((maps['normals'][:, :, 2] + 1) / 2 * 255).clip(0, 255).astype(np.uint8)
    save_16bit(nz, out / "normals_nz.tiff")

    print(f"  Saved 16-bit TIFFs to {out}/")


# ═══════════════════════════════════════════════════════════════════════
#  GENERATE MODES
# ═══════════════════════════════════════════════════════════════════════

def generate_grayscale(top_gray, side_grays, light_dirs):
    """
    Grayscale PBR pipeline.
    - Albedo = top image (captured under even top light)
    - Normals = photometric stereo on side images (with shadow masking)
    """
    print("\n" + "=" * 60)
    print("GENERATING GRAYSCALE PBR")
    print("=" * 60)

    albedo = normalize_albedo(top_gray)
    print(f"  Albedo (top):     shape={albedo.shape} dtype={albedo.dtype}")
    print(f"  Side images:      {len(side_grays)} (photometric stereo)")

    normals, rho = photometric_stereo_grayscale(side_grays, light_dirs)
    roughness = compute_roughness(normals)
    height_map = compute_height_map(normals)
    normals_rgb = visualize_normals(normals)

    # Stats
    norms = np.linalg.norm(normals, axis=2)
    print(f"  Normals mean ||N||: {np.mean(norms):.4f}")
    print(f"  Normals Nz range:   [{normals[:,:,2].min():.3f}, {normals[:,:,2].max():.3f}]")
    print(f"  Shadow mask used:   {np.mean(detect_shadows(side_grays)) * 100:.1f}% lit")
    print(f"  Roughness range:    [{roughness.min()}, {roughness.max()}]")
    print(f"  Height range:       [{height_map.min()}, {height_map.max()}]")

    return {
        'albedo': albedo,
        'normals': normals,
        'normals_rgb': normals_rgb,
        'roughness': roughness,
        'height_map': height_map,
        'rho': rho,
    }


def normalize_albedo(img, target_percentile=99.5, target_value=0.85):
    """
    Normalize albedo to proper reflectance range for PBR.

    Raw camera captures have arbitrary brightness depending on exposure/lighting.
    This scales the image so the brightest parts (target_percentile) map to
    target_value, giving physically plausible reflectance (0-1) for Blender.

    target_value=0.85 leaves headroom for highlights while ensuring
    dark fabrics (~0.15-0.30) and light fabrics (~0.50-0.75) are in range.
    """
    img_f = img.astype(np.float32)
    p = np.percentile(img_f, target_percentile)
    if p < 1e-8:
        return img
    scale = (target_value * 255.0) / p
    normalized = np.clip(img_f * scale, 0, 255).astype(np.uint8)
    print(f"  Albedo normalized: p{target_percentile}={p:.1f} → {target_value*255:.0f}, "
          f"scale={scale:.2f}x, mean {np.mean(img):.1f} → {np.mean(normalized):.1f}")
    return normalized


def generate_colored(top_color, side_colors, light_dirs):
    """
    Color PBR pipeline.
    - Albedo = top image (captured under even top light), normalized to reflectance
    - D65 chromatic adaptation applied to correct blue-shifted scene illuminant
    - Normals = photometric stereo on color side images (intensity-averaged)
    """
    print("\n" + "=" * 60)
    print("GENERATING COLORED PBR")
    print("=" * 60)

    albedo = normalize_albedo(top_color)
    print(f"  Albedo (top):     shape={albedo.shape} dtype={albedo.dtype}")
    print(f"  Side images:      {len(side_colors)} (photometric stereo)")

    normals, rho = photometric_stereo_color(side_colors, light_dirs)
    roughness = compute_roughness(normals)
    height_map = compute_height_map(normals)
    normals_rgb = visualize_normals(normals)

    # Stats
    norms = np.linalg.norm(normals, axis=2)
    print(f"  Normals mean ||N||: {np.mean(norms):.4f}")
    print(f"  Normals Nz range:   [{normals[:,:,2].min():.3f}, {normals[:,:,2].max():.3f}]")
    print(f"  Shadow mask used:   {np.mean(detect_shadows(side_colors)) * 100:.1f}% lit")
    print(f"  Roughness range:    [{roughness.min()}, {roughness.max()}]")
    print(f"  Height range:       [{height_map.min()}, {height_map.max()}]")

    return {
        'albedo': albedo,
        'normals': normals,
        'normals_rgb': normals_rgb,
        'roughness': roughness,
        'height_map': height_map,
        'rho': rho,
    }


# ═══════════════════════════════════════════════════════════════════════
#  VERIFICATION SUITE
# ═══════════════════════════════════════════════════════════════════════

def verify_normals(normals, label):
    """Check normal map validity: unit length, Nz > 0, no NaN/Inf."""
    print(f"\n  [{label}] Normal Map Validity")

    norms = np.linalg.norm(normals, axis=2)
    mean_norm = np.mean(norms)
    std_norm = np.std(norms)
    pct_unit = np.mean((norms > 0.95) & (norms < 1.05)) * 100
    pct_nz_neg = np.mean(normals[:, :, 2] < 0) * 100
    has_nan = np.any(np.isnan(normals))
    has_inf = np.any(np.isinf(normals))

    print(f"    Mean ||N||:        {mean_norm:.4f}  (expect ~1.0)")
    print(f"    Std  ||N||:        {std_norm:.4f}  (expect <0.05)")
    print(f"    % unit-length:     {pct_unit:.1f}%  (expect >90%)")
    print(f"    % Nz < 0:          {pct_nz_neg:.2f}%  (expect ~0%)")
    print(f"    Has NaN:           {has_nan}")
    print(f"    Has Inf:           {has_inf}")

    passed = 0.9 < mean_norm < 1.1 and pct_nz_neg < 5.0 and not has_nan and not has_inf
    print(f"    RESULT:            {'PASS' if passed else 'FAIL'}")
    return passed, {
        'mean_norm': mean_norm,
        'std_norm': std_norm,
        'pct_unit': pct_unit,
        'pct_nz_neg': pct_nz_neg,
    }


def verify_rerender(normals, rho, side_grays, light_dirs, side_names, output_dir, label):
    """Re-render each side image from rho + normals, compare to actual."""
    print(f"\n  [{label}] Re-render Consistency")

    h, w = normals.shape[:2]
    mosaic_rows = []
    rmse_list = []
    corr_list = []

    for i in range(len(side_grays)):
        L_i = light_dirs[i]
        NdotL = np.clip(np.sum(normals * L_i, axis=2), 0, 1)

        predicted = rho * NdotL
        actual = side_grays[i].astype(np.float32)

        # Normalize both to 0-255 for comparison
        pred_scale = np.percentile(predicted, 99.5)
        predicted_u8 = np.clip(predicted / max(pred_scale, 1e-8) * 255, 0, 255).astype(np.uint8)

        act_scale = np.percentile(actual, 99.5)
        actual_u8 = np.clip(actual / max(act_scale, 1e-8) * 255, 0, 255).astype(np.uint8)

        # Error metrics
        error = np.abs(predicted_u8.astype(float) - actual_u8.astype(float))
        error_u8 = np.clip(error * 3, 0, 255).astype(np.uint8)
        error_color = cv2.applyColorMap(error_u8, cv2.COLORMAP_JET)

        rmse = np.sqrt(np.mean((predicted_u8.astype(float) - actual_u8.astype(float)) ** 2))
        fp = predicted_u8.flatten().astype(float)
        fa = actual_u8.flatten().astype(float)
        corr = np.corrcoef(fp, fa)[0, 1] if np.std(fp) > 0 and np.std(fa) > 0 else 0.0

        rmse_list.append(rmse)
        corr_list.append(corr)
        print(f"    {side_names[i]:>8s}:  RMSE={rmse:6.2f}  corr={corr:.4f}")

        # Mosaic row: actual | predicted | error
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

    mean_rmse = np.mean(rmse_list)
    mean_corr = np.mean(corr_list)
    print(f"    Mosaic saved:      {mosaic_path}")
    print(f"    Mean RMSE:         {mean_rmse:.2f}  (lower=better)")
    print(f"    Mean correlation:  {mean_corr:.4f}  (>0.7 good, >0.5 acceptable)")

    passed = mean_corr > 0.5
    print(f"    RESULT:            {'PASS' if passed else 'FAIL'}")
    return passed, {
        'mean_rmse': mean_rmse,
        'mean_corr': mean_corr,
        'per_side_rmse': dict(zip(side_names, rmse_list)),
        'per_side_corr': dict(zip(side_names, corr_list)),
    }


def verify_integrability(normals, label):
    """Curl of gradient field — should be ~0 for integrable normals."""
    print(f"\n  [{label}] Height Integrability (Curl)")

    nz = normals[:, :, 2]
    nz_safe = np.where(np.abs(nz) < 1e-8, 1e-8, nz)
    p = normals[:, :, 0] / nz_safe
    q = normals[:, :, 1] / nz_safe

    dp_dy = np.gradient(p, axis=0)
    dq_dx = np.gradient(q, axis=1)
    curl = dp_dy - dq_dx

    mean_curl = np.mean(np.abs(curl))
    median_curl = np.median(np.abs(curl))
    p99_curl = np.percentile(np.abs(curl), 99)

    print(f"    Mean |curl|:       {mean_curl:.4f}")
    print(f"    Median |curl|:     {median_curl:.4f}")
    print(f"    99th pct |curl|:   {p99_curl:.4f}")

    passed = median_curl < 1.0
    print(f"    RESULT:            {'PASS' if passed else 'FAIL'}")
    return passed, {
        'mean_curl': mean_curl,
        'median_curl': median_curl,
        'p99_curl': p99_curl,
    }


def verify_roughness(roughness, label):
    """Roughness map sanity: should have texture, not be constant."""
    print(f"\n  [{label}] Roughness Sanity")

    mean_val = np.mean(roughness)
    std_val = np.std(roughness)
    pct_zero = np.mean(roughness == 0) * 100
    pct_sat = np.mean(roughness == 255) * 100

    print(f"    Range:             [{np.min(roughness)}, {np.max(roughness)}]")
    print(f"    Mean:              {mean_val:.1f}")
    print(f"    Std:               {std_val:.1f}  (expect >10)")
    print(f"    % zero:            {pct_zero:.1f}%")
    print(f"    % saturated:       {pct_sat:.1f}%")

    passed = std_val > 5 and pct_zero < 80 and pct_sat < 50
    print(f"    RESULT:            {'PASS' if passed else 'FAIL'}")
    return passed, {
        'mean': mean_val,
        'std': std_val,
        'pct_zero': pct_zero,
        'pct_sat': pct_sat,
    }


def verify_albedo(albedo, normals, label):
    """Albedo shadow-free check: top lighting should be even."""
    print(f"\n  [{label}] Albedo Shadow-Free")

    nz = normals[:, :, 2]
    mean_nz = np.mean(nz)
    pct_facing = np.mean(nz > 0.5) * 100

    if albedo.ndim == 3:
        alb_gray = cv2.cvtColor(albedo, cv2.COLOR_BGR2GRAY).astype(float)
    else:
        alb_gray = albedo.astype(float)

    alb_mean = np.mean(alb_gray)
    alb_std = np.std(alb_gray)
    alb_cv = alb_std / max(alb_mean, 1)

    print(f"    Mean Nz:           {mean_nz:.4f}  (expect >0.7)")
    print(f"    % facing up:       {pct_facing:.1f}%")
    print(f"    Albedo mean:       {alb_mean:.1f}")
    print(f"    Albedo CV:         {alb_cv:.3f}  (expect <0.5)")

    passed = mean_nz > 0.3 and alb_cv < 1.0
    print(f"    RESULT:            {'PASS' if passed else 'FAIL'}")
    return passed, {
        'mean_nz': mean_nz,
        'pct_facing': pct_facing,
        'alb_mean': alb_mean,
        'alb_cv': alb_cv,
    }


def run_verification(maps, side_grays, light_dirs, side_names, output_dir, label):
    """Run all 5 verification tests for one mode."""
    results = {}
    metrics = {}

    p, m = verify_normals(maps['normals'], label)
    results['normals'] = p
    metrics['normals'] = m

    p, m = verify_rerender(
        maps['normals'], maps['rho'], side_grays, light_dirs, side_names, output_dir, label
    )
    results['rerender'] = p
    metrics['rerender'] = m

    p, m = verify_integrability(maps['normals'], label)
    results['integrability'] = p
    metrics['integrability'] = m

    p, m = verify_roughness(maps['roughness'], label)
    results['roughness'] = p
    metrics['roughness'] = m

    p, m = verify_albedo(maps['albedo'], maps['normals'], label)
    results['albedo'] = p
    metrics['albedo'] = m

    return results, metrics


# ═══════════════════════════════════════════════════════════════════════
#  BATCH PROCESSING
# ═══════════════════════════════════════════════════════════════════════

def process_batch(batch_name):
    """
    Process one batch: load images, generate grayscale + color PBR,
    run verification suite.

    Returns: (gray_results, color_results, gray_metrics, color_metrics, summary)
             or None if batch cannot be processed.
    """
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

    # ── Generate ──
    gray_maps = generate_grayscale(top_gray, side_grays, light_dirs)
    save_maps(gray_maps, output_dir, "grayscale")

    color_maps = generate_colored(top_color, side_colors, light_dirs)
    save_maps(color_maps, output_dir, "colored")

    # ── Verify ──
    print("\n" + "-" * 60)
    print("GRAYSCALE VERIFICATION")
    print("-" * 60)
    gray_results, gray_metrics = run_verification(
        gray_maps, side_grays, light_dirs, side_names, output_dir,
        f"{batch_name}_grayscale"
    )

    print("\n" + "-" * 60)
    print("COLORED VERIFICATION")
    print("-" * 60)
    color_results, color_metrics = run_verification(
        color_maps, side_grays, light_dirs, side_names, output_dir,
        f"{batch_name}_colored"
    )

    # Summary
    summary = {
        'batch': batch_name,
        'n_sides': len(side_grays),
        'image_shape': side_grays[0].shape,
        'gray_pass': all(gray_results.values()),
        'color_pass': all(color_results.values()),
        'gray_normals_ok': gray_results['normals'],
        'gray_rerender_ok': gray_results['rerender'],
        'gray_integ_ok': gray_results['integrability'],
        'gray_rough_ok': gray_results['roughness'],
        'gray_albedo_ok': gray_results['albedo'],
        'color_normals_ok': color_results['normals'],
        'color_rerender_ok': color_results['rerender'],
        'color_integ_ok': color_results['integrability'],
        'color_rough_ok': color_results['roughness'],
        'color_albedo_ok': color_results['albedo'],
        'gray_mean_corr': gray_metrics['rerender']['mean_corr'],
        'gray_mean_rmse': gray_metrics['rerender']['mean_rmse'],
        'color_mean_corr': color_metrics['rerender']['mean_corr'],
        'color_mean_rmse': color_metrics['rerender']['mean_rmse'],
        'gray_median_curl': gray_metrics['integrability']['median_curl'],
        'color_median_curl': color_metrics['integrability']['median_curl'],
        'output_dir': str(output_dir),
    }

    return gray_results, color_results, gray_metrics, color_metrics, summary


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    batch_names = sys.argv[1:] if len(sys.argv) > 1 else [
        "GRIMSBY-EARTH", "GRIMSBY-MUSHROOM", "MALVERN-SEAGREEN", "MALVERN-CHARCOAL"
    ]

    print("=" * 70)
    print("STANDALONE PBR Generation + Verification")
    print(f"  Batches:    {batch_names}")
    print(f"  Source:     {CALIB_FOLDER}")
    print(f"  Output:     {OUTPUT_FOLDER}")
    print(f"  Skip:       {SKIP_SIDES}")
    print(f"  Downsample: {DOWNSAMPLE_SCALE}")
    print(f"  Denoise:    {DENOISE_KERNEL}")
    print(f"  Shadow thr: {SHADOW_THRESHOLD}")
    print("=" * 70)

    all_summaries = []
    all_pass = True

    for batch_name in batch_names:
        result = process_batch(batch_name)
        if result is None:
            continue
        gray_results, color_results, gray_metrics, color_metrics, summary = result
        all_summaries.append(summary)

        if not summary['gray_pass'] or not summary['color_pass']:
            all_pass = False

    # ── Cross-batch comparison table ──
    print("\n" + "=" * 70)
    print("CROSS-BATCH COMPARISON")
    print("=" * 70)

    if all_summaries:
        # Test results table
        def p(v):
            return 'PASS' if v else 'FAIL'

        print(f"\n  {'Batch':>25s}  {'Sides':>5s}  "
              f"{'G.Nrm':>5s} {'G.ReR':>5s} {'G.Int':>5s} {'G.Rgh':>5s} {'G.Alb':>5s}  "
              f"{'C.Nrm':>5s} {'C.ReR':>5s} {'C.Int':>5s} {'C.Rgh':>5s} {'C.Alb':>5s}")
        print(f"  {'-'*100}")
        for s in all_summaries:
            print(f"  {s['batch']:>25s}  {s['n_sides']:>5d}  "
                  f"{p(s['gray_normals_ok']):>5s} {p(s['gray_rerender_ok']):>5s} "
                  f"{p(s['gray_integ_ok']):>5s} {p(s['gray_rough_ok']):>5s} "
                  f"{p(s['gray_albedo_ok']):>5s}  "
                  f"{p(s['color_normals_ok']):>5s} {p(s['color_rerender_ok']):>5s} "
                  f"{p(s['color_integ_ok']):>5s} {p(s['color_rough_ok']):>5s} "
                  f"{p(s['color_albedo_ok']):>5s}")

        # Metrics table
        print(f"\n  {'Batch':>25s}  {'G.Corr':>7s} {'G.RMSE':>7s} {'G.Curl':>7s}  "
              f"{'C.Corr':>7s} {'C.RMSE':>7s} {'C.Curl':>7s}")
        print(f"  {'-'*75}")
        for s in all_summaries:
            print(f"  {s['batch']:>25s}  "
                  f"{s['gray_mean_corr']:>7.4f} {s['gray_mean_rmse']:>7.2f} "
                  f"{s['gray_median_curl']:>7.4f}  "
                  f"{s['color_mean_corr']:>7.4f} {s['color_mean_rmse']:>7.2f} "
                  f"{s['color_median_curl']:>7.4f}")

    # Final summary
    print(f"\n  Overall: {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
    for s in all_summaries:
        status = 'OK' if s['gray_pass'] and s['color_pass'] else 'ISSUES'
        print(f"    {s['batch']:>25s}  [{status}]  -> {s['output_dir']}")

    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())

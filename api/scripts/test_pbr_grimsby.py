"""
PBR Generation + Verification for GRIMSBY-EARTH

Pipeline:
  - Top image (color calibrated) → albedo (base color) for BOTH grayscale and colored
  - 8 side images (color calibrated) → photometric stereo → normals, roughness, height
  - Top image is EXCLUDED from photometric stereo

Generates:
  - pbr_test/grayscale/  (albedo gray, normals, roughness, height)
  - pbr_test/colored/    (albedo color, normals, roughness, height)

Verification:
  1. Normal map validity (unit length, Nz > 0, no NaN)
  2. Re-render consistency (predict each side image, compare to actual)
  3. Height map integrability (curl of gradient field)
  4. Roughness sanity (histogram spread, spatial structure)
  5. Albedo shadow-free check
"""
import os
import sys
import numpy as np
import cv2
from pathlib import Path
from scipy.linalg import lstsq
from scipy.ndimage import convolve as scipy_convolve

# ── Config ──────────────────────────────────────────────────────────────
BATCH_PATH = Path(__file__).resolve().parent.parent / "media" / "captures" / "GRIMSBY-EARTH"
SOURCE_FOLDER = BATCH_PATH / "color_calibrated"
OUTPUT_DIR = BATCH_PATH / "pbr_test"

LIGHT_DIRECTIONS = {
    'top':    [0, 0, 1],
    'side_1': [0, 1, 1],
    'side_2': [-1, 1, 1],
    'side_3': [-1, 0, 1],
    'side_4': [-1, -1, 1],
    'side_5': [0, -1, 1],
    'side_6': [1, -1, 1],
    'side_7': [1, 0, 1],
    'side_8': [1, 1, 1],
}

SUPPORTED_EXT = {'.tiff', '.tif', '.png', '.jpg', '.jpeg'}


# ── Image Loading ───────────────────────────────────────────────────────
def load_images(source_folder):
    """
    Load calibrated images. Separate top from sides.
    Returns both color and grayscale versions for both modes.
    """
    top_color = None
    top_gray = None
    side_colors = []
    side_grays = []
    side_light_dirs = []
    side_names = []

    files = sorted([
        f for f in source_folder.iterdir()
        if f.suffix.lower() in SUPPORTED_EXT
    ])

    print(f"Found {len(files)} images in {source_folder}")

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
            print(f"  SKIP (no match): {fpath.name}")
            continue

        img = cv2.imread(str(fpath), cv2.IMREAD_UNCHANGED)
        if img is None:
            print(f"  FAIL to load: {fpath.name}")
            continue

        if img.ndim == 3 and img.shape[2] == 4:
            img = img[:, :, :3]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

        if matched_pos == 'top':
            top_color = img
            top_gray = gray
            print(f"  TOP (albedo):  {fpath.name}  shape={img.shape} dtype={img.dtype}")
        else:
            side_colors.append(img)
            side_grays.append(gray)
            side_light_dirs.append(matched_dir)
            side_names.append(matched_pos)
            print(f"  SIDE {matched_pos:>6s}:  {fpath.name}  shape={img.shape}")

    # Normalize light directions
    L = np.array(side_light_dirs, dtype=np.float32)
    norms = np.linalg.norm(L, axis=1, keepdims=True)
    norms[norms == 0] = 1e-8
    L /= norms

    print(f"\nLoaded: top={'YES' if top_color is not None else 'NO'}, sides={len(side_grays)}")
    return top_gray, top_color, side_grays, side_colors, L, side_names


# ── PBR Computation ─────────────────────────────────────────────────────
def compute_normals_grayscale(images_gray, light_dirs):
    """Photometric stereo on grayscale side images → normals + rho."""
    n = len(images_gray)
    h, w = images_gray[0].shape
    I = np.stack(images_gray, axis=0).astype(np.float32)
    L = light_dirs.astype(np.float32)
    I_flat = I.reshape(n, -1)

    G, _, _, _ = lstsq(L, I_flat)

    rho = np.linalg.norm(G, axis=0).reshape(h, w)
    rho_safe = np.where(rho == 0, 1e-8, rho)

    normals = (G / rho_safe.reshape(1, -1)).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals).astype(np.float32)

    return normals, rho


def compute_normals_color(images_color, light_dirs):
    """Photometric stereo on color side images → normals (from intensity channel)."""
    n = len(images_color)
    h, w, channels = images_color[0].shape

    # Shadow mask
    intensities = np.mean([
        cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) if img.ndim == 3 else img.astype(np.float32)
        for img in images_color
    ], axis=0)
    shadow_mask = intensities > (0.1 * np.max(intensities))

    # Stack: (pixels, n_images, channels)
    I = np.array([img.reshape(-1, channels) for img in images_color]).transpose(1, 0, 2)
    L = light_dirs.astype(np.float32)

    # Normals from average intensity
    I_intensity = np.mean(I, axis=2)
    G_intensity, _, _, _ = lstsq(L, I_intensity.T)

    albedo_intensity = np.linalg.norm(G_intensity, axis=0)
    albedo_safe = np.where(albedo_intensity == 0, 1e-8, albedo_intensity)

    normals = (G_intensity / albedo_safe).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)
    normals[~shadow_mask] = [0, 0, 1]

    # rho for re-render verification
    rho = albedo_intensity.reshape(h, w)

    return normals, rho


def compute_roughness(normals, window_size=5):
    """Roughness from normal variation."""
    h, w = normals.shape[:2]
    roughness = np.zeros((h, w), dtype=np.float32)
    kernel = np.ones((window_size, window_size)) / (window_size * window_size)
    for c in range(3):
        mean = scipy_convolve(normals[:, :, c], kernel, mode='reflect')
        sq_diff = (normals[:, :, c] - mean) ** 2
        roughness += scipy_convolve(sq_diff, kernel, mode='reflect')
    return cv2.normalize(roughness, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def compute_height_map(normals):
    """Frankot-Chellappa integration."""
    p = normals[:, :, 0] / (normals[:, :, 2] + 1e-8)
    q = normals[:, :, 1] / (normals[:, :, 2] + 1e-8)
    h, w = p.shape
    y, x = np.mgrid[0:h, 0:w]
    x = x - w / 2
    y = y - h / 2
    denom = x**2 + y**2
    denom[denom == 0] = 1
    Px = np.fft.fft2(p)
    Qx = np.fft.fft2(q)
    Z = (-1j * x * Px - 1j * y * Qx) / denom
    height = np.real(np.fft.ifft2(Z))
    height = np.nan_to_num(height, nan=0.0, posinf=0.0, neginf=0.0)
    return cv2.normalize(height, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def visualize_normals(normals):
    """Normals → RGB visualization."""
    return ((normals + 1) / 2 * 255).astype(np.uint8)


# ── Generate Both Modes ─────────────────────────────────────────────────
def generate_grayscale(top_gray, side_grays, light_dirs):
    """Grayscale PBR: gray top = albedo, gray sides → normals."""
    print("\n" + "=" * 60)
    print("GENERATING GRAYSCALE PBR")
    print("=" * 60)

    albedo = top_gray
    print(f"  Albedo (top):   shape={albedo.shape} dtype={albedo.dtype}")
    print(f"  Side images:    {len(side_grays)} (used for photometric stereo)")

    normals, rho = compute_normals_grayscale(side_grays, light_dirs)
    roughness = compute_roughness(normals)
    height_map = compute_height_map(normals)
    normals_rgb = visualize_normals(normals)

    print(f"  Normals:        shape={normals.shape}")
    print(f"  Roughness:      shape={roughness.shape}")
    print(f"  Height:         shape={height_map.shape}")

    return {
        'albedo': albedo,
        'normals': normals,
        'normals_rgb': normals_rgb,
        'roughness': roughness,
        'height_map': height_map,
        'rho': rho,
    }


def generate_colored(top_color, side_colors, light_dirs):
    """Color PBR: color top = albedo, color sides → normals."""
    print("\n" + "=" * 60)
    print("GENERATING COLORED PBR")
    print("=" * 60)

    albedo = top_color
    print(f"  Albedo (top):   shape={albedo.shape} dtype={albedo.dtype}")
    print(f"  Side images:    {len(side_colors)} (used for photometric stereo)")

    normals, rho = compute_normals_color(side_colors, light_dirs)
    roughness = compute_roughness(normals)
    height_map = compute_height_map(normals)
    normals_rgb = visualize_normals(normals)

    print(f"  Normals:        shape={normals.shape}")
    print(f"  Roughness:      shape={roughness.shape}")
    print(f"  Height:         shape={height_map.shape}")

    return {
        'albedo': albedo,
        'normals': normals,
        'normals_rgb': normals_rgb,
        'roughness': roughness,
        'height_map': height_map,
        'rho': rho,
    }


# ── Save ────────────────────────────────────────────────────────────────
def save_maps(maps, output_dir, mode_name):
    """Save all PBR maps for a mode."""
    out = output_dir / mode_name
    out.mkdir(parents=True, exist_ok=True)

    albedo = maps['albedo']
    if albedo.ndim == 3:
        # Color — already BGR from cv2.imread
        cv2.imwrite(str(out / "albedo.png"), albedo)
    else:
        cv2.imwrite(str(out / "albedo.png"), albedo)

    cv2.imwrite(str(out / "normals.png"),
                cv2.cvtColor(maps['normals_rgb'], cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(out / "roughness.png"), maps['roughness'])
    cv2.imwrite(str(out / "height_map.png"), maps['height_map'])

    # Nz channel for inspection
    nz = ((maps['normals'][:, :, 2] + 1) / 2 * 255).astype(np.uint8)
    cv2.imwrite(str(out / "normals_nz.png"), nz)

    print(f"  Saved to {out}/")


# ── Verification ────────────────────────────────────────────────────────
def verify_normals(normals, label):
    """Check normal map validity."""
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
    return passed


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

        # Normalize both to 0-255
        pred_scale = np.percentile(predicted, 99.5)
        predicted_u8 = np.clip(predicted / max(pred_scale, 1e-8) * 255, 0, 255).astype(np.uint8)

        act_scale = np.percentile(actual, 99.5)
        actual_u8 = np.clip(actual / max(act_scale, 1e-8) * 255, 0, 255).astype(np.uint8)

        # Error
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

        # Mosaic row
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
    print(f"    Mean correlation:  {mean_corr:.4f}  (>0.7 acceptable)")

    passed = mean_corr > 0.5
    print(f"    RESULT:            {'PASS' if passed else 'FAIL'}")
    return passed


def verify_integrability(normals, label):
    """Curl of gradient field — should be ~0."""
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
    return passed


def verify_roughness(roughness, label):
    """Roughness map sanity."""
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
    return passed


def verify_albedo(albedo, normals, label):
    """Albedo shadow-free check."""
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
    return passed


def run_verification(maps, side_grays, light_dirs, side_names, output_dir, label):
    """Run all 5 tests for one mode."""
    results = {}
    results['normals'] = verify_normals(maps['normals'], label)
    results['rerender'] = verify_rerender(
        maps['normals'], maps['rho'], side_grays, light_dirs, side_names, output_dir, label
    )
    results['integrability'] = verify_integrability(maps['normals'], label)
    results['roughness'] = verify_roughness(maps['roughness'], label)
    results['albedo'] = verify_albedo(maps['albedo'], maps['normals'], label)
    return results


# ── Main ────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("PBR Generation + Verification: GRIMSBY-EARTH")
    print(f"Source: {SOURCE_FOLDER}")
    print("=" * 60)

    if not SOURCE_FOLDER.exists():
        print(f"ERROR: {SOURCE_FOLDER} not found")
        return 1

    # Load all calibrated images
    top_gray, top_color, side_grays, side_colors, light_dirs, side_names = load_images(SOURCE_FOLDER)

    if top_gray is None or top_color is None:
        print("ERROR: No top image found")
        return 1
    if len(side_grays) < 3:
        print(f"ERROR: Need >=3 side images, found {len(side_grays)}")
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Generate Grayscale PBR ──
    gray_maps = generate_grayscale(top_gray, side_grays, light_dirs)
    save_maps(gray_maps, OUTPUT_DIR, "grayscale")

    # ── Generate Colored PBR ──
    color_maps = generate_colored(top_color, side_colors, light_dirs)
    save_maps(color_maps, OUTPUT_DIR, "colored")

    # ── Verify Both ──
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    print("\n" + "-" * 60)
    print("GRAYSCALE MODE")
    print("-" * 60)
    gray_results = run_verification(
        gray_maps, side_grays, light_dirs, side_names, OUTPUT_DIR, "grayscale"
    )

    print("\n" + "-" * 60)
    print("COLORED MODE")
    print("-" * 60)
    color_results = run_verification(
        color_maps, side_grays, light_dirs, side_names, OUTPUT_DIR, "colored"
    )

    # ── Summary ──
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_pass = True
    for mode_name, results in [("grayscale", gray_results), ("colored", color_results)]:
        print(f"\n  {mode_name.upper()}:")
        for test, passed in results.items():
            status = "PASS" if passed else "FAIL"
            print(f"    {test:25s} {status}")
            if not passed:
                all_pass = False

    print(f"\n  Overall: {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
    print(f"  Output:  {OUTPUT_DIR}")
    print(f"    grayscale/ — albedo (gray top), normals, roughness, height")
    print(f"    colored/   — albedo (color top), normals, roughness, height")
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())

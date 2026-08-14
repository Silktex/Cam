"""
PBR grayscale map generation.
Adapted from backend/helpers/pbr_grayscale.py - minimal changes, TIFF output enforced.
"""
import os
import numpy as np
from scipy.linalg import lstsq
from scipy.ndimage import convolve
import cv2


def denoise_image(img):
    """Apply Gaussian blur to denoise the image."""
    return cv2.GaussianBlur(img, (3, 3), 0)


def downsample_image(img, scale_factor=1.0):
    """Downsample the image by a given scale factor."""
    if scale_factor == 1.0:
        return img
    width = int(img.shape[1] * scale_factor)
    height = int(img.shape[0] * scale_factor)
    return cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)


def preprocess_image(img, downsample_scale=1.0):
    """Preprocess the image: denoise and downsample."""
    denoised = denoise_image(img)
    return downsample_image(denoised, scale_factor=downsample_scale)


def load_and_pair_images(image_dir, downsample_scale=1.0):
    """Load images and pair them with light directions."""
    light_directions = {
        'segment_0': [0, 0, 1],
        'segment_1': [0, 1, 1],
        'segment_2': [-1, 1, 1],
        'segment_3': [-1, 0, 1],
        'segment_4': [-1, -1, 1],
        'segment_5': [0, -1, 1],
        'segment_6': [1, -1, 1],
        'segment_7': [1, 0, 1],
        'segment_8': [1, 1, 1],
    }

    # Alternative naming: top/side_N maps to segment_N
    alt_names = {
        '_top': 'segment_0',
        'side_1': 'segment_1',
        'side_2': 'segment_2',
        'side_3': 'segment_3',
        'side_4': 'segment_4',
        'side_5': 'segment_5',
        'side_6': 'segment_6',
        'side_7': 'segment_7',
        'side_8': 'segment_8',
    }

    image_paths = [
        os.path.join(image_dir, f)
        for f in os.listdir(image_dir)
        if f.lower().endswith(('.png', '.tiff', '.tif', '.jpg', '.jpeg'))
    ]
    paired_images = []
    paired_light_directions = []
    sorted_keys = sorted(light_directions.keys(), key=len, reverse=True)
    sorted_alt_keys = sorted(alt_names.keys(), key=len, reverse=True)

    for path in image_paths:
        filename = os.path.basename(path).lower()
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

        matched = False
        for key in sorted_keys:
            if key in filename:
                preprocessed = preprocess_image(img, downsample_scale=downsample_scale)
                paired_images.append(preprocessed)
                paired_light_directions.append(light_directions[key])
                matched = True
                break
        if not matched:
            for alt_key in sorted_alt_keys:
                if alt_key in filename:
                    seg_key = alt_names[alt_key]
                    preprocessed = preprocess_image(img, downsample_scale=downsample_scale)
                    paired_images.append(preprocessed)
                    paired_light_directions.append(light_directions[seg_key])
                    break

    if not paired_images:
        raise ValueError("No images were successfully loaded and paired.")

    light_dirs = np.array(paired_light_directions, dtype=np.float32)
    norms = np.linalg.norm(light_dirs, axis=1, keepdims=True)
    norms[norms == 0] = 1e-8
    light_dirs /= norms

    if len(paired_images) < 3:
        raise ValueError(f"Photometric stereo requires at least 3 images. Found {len(paired_images)}.")

    return paired_images, light_dirs


def photometric_stereo(images, light_dirs):
    """Compute albedo and normals using photometric stereo (grayscale version)."""
    num_images = len(images)
    h, w = images[0].shape

    I = np.stack(images, axis=0).astype(np.float32)
    L = light_dirs.astype(np.float32)
    I_flat = I.reshape(num_images, -1)

    G, _, _, _ = lstsq(L, I_flat)
    albedo = np.linalg.norm(G, axis=0).reshape(h, w)
    albedo_safe = np.where(albedo == 0, 1e-8, albedo)

    normals = (G / albedo_safe.reshape(1, -1)).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals).astype(np.float32)

    scale = max(np.percentile(albedo, 99.5), 1e-8)
    albedo_gray = (np.clip(albedo / scale, 0, 1) * 255).astype(np.uint8)

    return albedo_gray, normals


def compute_roughness(normals, window_size=5):
    """Compute roughness map from normals."""
    h, w = normals.shape[:2]
    roughness = np.zeros((h, w), dtype=np.float32)
    kernel = np.ones((window_size, window_size)) / (window_size * window_size)

    for c in range(3):
        mean = convolve(normals[:, :, c], kernel, mode='reflect')
        sq_diff = (normals[:, :, c] - mean) ** 2
        variance = convolve(sq_diff, kernel, mode='reflect')
        roughness += variance

    roughness = cv2.normalize(roughness, None, 0, 1, cv2.NORM_MINMAX)
    return (roughness * 255).astype(np.uint8)


def integrate_normals(normals):
    """Integrate normals to compute height map using Frankot-Chellappa."""
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
    Z = np.real(np.fft.ifft2(Z))
    Z = np.nan_to_num(Z, nan=0.0, posinf=0.0, neginf=0.0)
    return cv2.normalize(Z, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)


def visualize_normals(normals):
    """Convert normals to RGB for visualization."""
    normals_rgb = ((normals + 1) / 2 * 255).astype(np.uint8)
    return normals_rgb


def save_map(image, save_path):
    """Save an image as TIFF using cv2 (not matplotlib)."""
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    if image.ndim == 2:
        cv2.imwrite(save_path, image)
    else:
        image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        cv2.imwrite(save_path, image_bgr)

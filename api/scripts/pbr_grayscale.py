import os
import numpy as np
import matplotlib.pyplot as plt
from scipy.linalg import lstsq
from scipy.ndimage import convolve
import cv2
import uuid

# Utility functions
def denoise_image(img):
    """Apply Gaussian blur to denoise the image."""
    return cv2.GaussianBlur(img, (3, 3), 0)  # Reduced kernel size to preserve details

def downsample_image(img, scale_factor=1.0):
    """Downsample the image by a given scale factor."""
    if scale_factor == 1.0:
        return img
    width = int(img.shape[1] * scale_factor)
    height = int(img.shape[0] * scale_factor)
    resized = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
    # print(f"Downsampled image from {img.shape} to {resized.shape}")
    return resized

def preprocess_image(img, downsample_scale=1.0):
    """Preprocess the image: denoise and downsample."""
    # Removed cv2.normalize to preserve intensity relationships
    denoised = denoise_image(img)
    # Save intermediate image for debugging
    # visualize_and_save(denoised, f"denoised_{uuid.uuid4().hex}.tiff")
    return downsample_image(denoised, scale_factor=downsample_scale)

# Image loading and pairing
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
        'segment_8': [1, 1, 1]
    }

    # light_directions = {
    #     'top': [0, 0, 1],
    #     'front': [0, 1, 1],
    #     'front_left': [-1, 1, 1],
    #     'left': [-1, 0, 1],
    #     # 'rear_left': [-1, -1, 1],
    #     'rear': [0, -1, 1],
    #     'rear_right': [1, -1, 1],
    #     'right': [1, 0, 1],
    #     'front_right': [1, 1, 1]
    # }

    image_paths = [os.path.join(image_dir, f) for f in os.listdir(image_dir) 
               if f.lower().endswith(('.png', '.tiff', '.tif', '.jpg', '.jpeg'))]
    paired_images = []
    paired_light_directions = []
    sorted_keys = sorted(light_directions.keys(), key=len, reverse=True)

    for path in image_paths:
        filename = os.path.basename(path).lower()
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        if img is None:
            print(f"Failed to load image: {path}")
            continue
        # print(f"Loaded image {path}: {img.shape}")
        matched = False
        for key in sorted_keys:
            key_normalized = key
            if key_normalized in filename:
                print(f"Matching {filename} with light direction key: {key}")
                preprocessed = preprocess_image(img, downsample_scale=downsample_scale)
                # print(f"Preprocessed image {filename}: {preprocessed.shape}")
                paired_images.append(preprocessed)
                paired_light_directions.append(light_directions[key])
                # print(f"Matched: {filename} -> {key}")
                matched = True
                break
        if not matched:
            print(f"No match found for: {filename}")

    if not paired_images:
        raise ValueError("No images were successfully loaded and paired.")
    light_dirs = np.array(paired_light_directions, dtype=np.float32)
    light_dirs /= np.linalg.norm(light_dirs, axis=1, keepdims=True)
    num_images = len(paired_images)
    if num_images < 3:
        raise ValueError(f"Photometric stereo requires at least 3 images. Found {num_images} matches.")
    # print(f"Processing {num_images} matched images...")
    # print(f"Light directions:\n{light_dirs}")
    return paired_images, light_dirs

def detect_shadows(images, threshold=0.1):
    """Detect shadow regions based on intensity threshold."""
    intensities = np.mean([images], axis=0)
    max_intensity = np.max(intensities)
    shadow_mask = intensities > (threshold * max_intensity)
    return shadow_mask

def photometric_stereo(images, light_dirs):
    """Compute albedo and normals using photometric stereo (grayscale version)."""
    num_images = len(images)
    h, w = images[0].shape

    if light_dirs.shape[0] != num_images:
        raise ValueError(
            f"Number of images ({num_images}) does not match "
            f"number of light directions ({light_dirs.shape[0]})."
        )
    
    # Stack images into shape (N, H, W)
    I = np.stack(images, axis=0).astype(np.float32)  
    L = light_dirs.astype(np.float32)

    # Reshape intensities into (N, H*W)
    I_flat = I.reshape(num_images, -1)

    # Solve Least Squares:  L * G = I
    # G has shape (3, H*W): each column is (Nx, Ny, Nz)*albedo
    G, _, _, _ = lstsq(L, I_flat)

    # Compute albedo = ||G|| for each pixel
    albedo = np.linalg.norm(G, axis=0)       # shape (H*W,)
    albedo = albedo.reshape(h, w)

    # Prevent division by zero
    albedo_safe = np.where(albedo == 0, 1e-8, albedo)

    # Compute normalized normals
    normals = (G / albedo_safe.reshape(1, -1)).T.reshape(h, w, 3)
    normals = np.nan_to_num(normals).astype(np.float32)

    # Normalized grayscale albedo for display (0–255)
    scale = np.percentile(albedo, 99.5)
    scale = max(scale, 1e-8)
    albedo_norm = np.clip(albedo / scale, 0, 1)
    albedo_gray = (albedo_norm * 255).astype(np.uint8)

    return albedo_gray, normals


def compute_roughness(normals, window_size=5):
    """Compute roughness map from normals."""
    h, w = normals.shape[:2]
    roughness = np.zeros((h, w), dtype=np.float32)
    kernel = np.ones((window_size, window_size, 1)) / (window_size * window_size)
    for c in range(3): 
        mean = convolve(normals[:, :, c], kernel[:, :, 0], mode='reflect')
        sq_diff = (normals[:, :, c] - mean) ** 2
        variance = convolve(sq_diff, kernel[:, :, 0], mode='reflect')
        roughness += variance
    roughness = cv2.normalize(roughness, None, 0, 1, cv2.NORM_MINMAX)
    roughness = (roughness * 255).astype(np.uint8)
    # print(f"Roughness shape: {roughness.shape}")
    return roughness

def frankot_chellappa(normals):
    """Integrate normals to compute height map using Frankot-Chellappa."""
    p = normals[:, :, 0] / (normals[:, :, 2] + 1e-8)
    q = normals[:, :, 1] / (normals[:, :, 2] + 1e-8)
    h, w = p.shape
    y, x = np.mgrid[0:h, 0:w]
    x = x - w / 2
    y = y - h / 2
    denom = (x**2 + y**2)
    denom[denom == 0] = 1
    Px = np.fft.fft2(p)
    Qx = np.fft.fft2(q)
    Z = (-1j * x * Px - 1j * y * Qx) / denom
    Z = np.real(np.fft.ifft2(Z))
    Z = np.nan_to_num(Z, nan=0.0, posinf=0.0, neginf=0.0)
    height_map = cv2.normalize(Z, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    # print(f"Height map shape: {height_map.shape}")
    return height_map

def integrate_normals(normals):
    """Integrate normals to compute height map."""
    return frankot_chellappa(normals)

def visualize_normals(normals):
    """Convert normals to RGB for visualization."""
    normals_rgb = (normals + 1) / 2
    normals_rgb = (normals_rgb * 255).astype(np.uint8)
    # print(f"Visualized normals shape: {normals_rgb.shape}")
    return normals_rgb

def save_map(image, save_path):
    """Save an image with high quality. Grayscale images saved as single-channel TIFF."""
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # For grayscale images (2D arrays), save as single-channel TIFF using cv2
    if len(image.shape) == 2:
        cv2.imwrite(save_path, image)
        print(f"Saved grayscale TIFF: {save_path} (shape: {image.shape})")
    else:
        # For RGB images, convert from RGB to BGR for cv2
        image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        cv2.imwrite(save_path, image_bgr)
        print(f"Saved RGB TIFF: {save_path} (shape: {image.shape})")

def main(image_dir, downsample_scale=1.0):
    """Main function to process images and generate PBR maps."""
    output_dir = os.path.join(image_dir, "pbr_maps")
    os.makedirs(output_dir, exist_ok=True)
    # Load and pair images
    images, light_dirs = load_and_pair_images(image_dir, downsample_scale=downsample_scale)
    
    # Compute albedo and normals
    albedo_rgb, normals = photometric_stereo(images, light_dirs)
    
    # Compute roughness and height map
    roughness = compute_roughness(normals)
    height_map = integrate_normals(normals)
    normals_rgb = visualize_normals(normals)

    # import matplotlib.pyplot as plt
    # fig, axes = plt.subplots(1, 4, figsize=(20, 5))

    # axes[0].imshow(albedo_rgb)
    # axes[0].set_title('albedo')
    # axes[0].axis('off')

    # axes[1].imshow(normals_rgb)
    # axes[1].set_title('normals')
    # axes[1].axis('off')

    # axes[2].imshow(height_map, cmap='gray')
    # axes[2].set_title('height')
    # axes[2].axis('off')

    # axes[3].imshow(roughness, cmap='gray')
    # axes[3].set_title('roughness')
    # axes[3].axis('off')


    # # Adjust layout to prevent overlap
    # plt.tight_layout()

    # # Show the plot
    # plt.show()

    # Save maps - grayscale maps saved as true single-channel TIFFs
    save_map(albedo_rgb, os.path.join(output_dir, "albedo.tiff"))
    save_map(normals_rgb, os.path.join(output_dir, "normals.tiff"))
    save_map(roughness, os.path.join(output_dir, "roughness.tiff"))  # Grayscale
    save_map(height_map, os.path.join(output_dir, "height_map.tiff"))  # Grayscale
    print(f"\nAll PBR maps saved to {output_dir}")

image_dir = '/srv/ashish/backend/media/MAJESTIC/cropped/'  # Replace with your image directory
downsample_scale = 1.0  # Adjust as needed
main(image_dir, downsample_scale)
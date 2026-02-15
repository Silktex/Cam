import os
try:
    import cupy as cp
    import cupyx.scipy.ndimage as cp_ndimage
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False
import numpy as np
import cv2
from scipy.linalg import lstsq
from scipy.ndimage import convolve as scipy_convolve
import matplotlib.pyplot as plt

class ImageProcessor:
    """Handles image loading, preprocessing, and pairing with light directions."""
    @staticmethod
    def downsample_image(image: np.ndarray, scale_factor: float = 1.0) -> np.ndarray:
        """Downsample an image by a given scale factor."""
        if scale_factor == 1.0:
            return image
        width = int(image.shape[1] * scale_factor)
        height = int(image.shape[0] * scale_factor)
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

    @staticmethod
    def preprocess_image(image: np.ndarray, downsample_scale: float = 1.0) -> np.ndarray:
        """Apply Gaussian blur and downsample the image."""
        denoised = cv2.GaussianBlur(image, (3, 3), 0)
        return ImageProcessor.downsample_image(denoised, downsample_scale)

    @staticmethod
    def load_and_pair_images(image_dir: str, downsample_scale: float = 1.0) -> tuple[list[np.ndarray], np.ndarray]:
        """Load images from a directory and pair them with light directions."""

        light_directions = {
            'top': [0, 0, 1],
            'front': [0, 1, 1],
            'front_left': [-1, 1, 1],
            'left': [-1, 0, 1],
            'rear_left': [-1, -1, 1],
            'rear': [0, -1, 1],
            'rear_right': [1, -1, 1],
            'right': [1, 0, 1],
            'front_right': [1, 1, 1]
        }

        image_paths = [
            os.path.join(image_dir, f) for f in sorted(os.listdir(image_dir))
            if f.lower().endswith(('.tiff', '.tif'))
        ]
        paired_images = []
        paired_light_dirs = []
        sorted_keys = sorted(light_directions.keys(), key=len, reverse=True)

        for path in image_paths:
            filename = os.path.basename(path).lower()
            image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if image is None:
                print(f"Failed to load image: {path}")
                continue
            elif image.shape[2] == 4:  # RGBA
                image = image[:, :, :3]  # Drop alpha

            matched = False
            for key in sorted_keys:
                key_variants = [key, key.replace('-', '_')]
                if any(kv in filename for kv in key_variants):
                    preprocessed = ImageProcessor.preprocess_image(image, downsample_scale)
                    paired_images.append(preprocessed)
                    paired_light_dirs.append(light_directions[key])
                    matched = True
                    break
            if not matched:
                print(f"No light direction match for: {filename}")

        if not paired_images:
            raise ValueError(f"No images were successfully loaded and paired from {image_dir}.")

        light_dirs = np.array(paired_light_dirs, dtype=np.float32)
        norms = np.linalg.norm(light_dirs, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        light_dirs /= norms

        if len(paired_images) < 4:
            raise ValueError(f"Photometric stereo requires at least 4 images. Found {len(paired_images)}.")

        print(f"Loaded {len(paired_images)} images")
        return paired_images, light_dirs

    @staticmethod
    def detect_shadows(images: list[np.ndarray], threshold: float = 0.1) -> np.ndarray:
        """Detect shadow regions based on intensity threshold."""
        intensities = np.mean([cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img for img in images], axis=0)
        max_intensity = np.max(intensities)
        return intensities > (threshold * max_intensity)

    @staticmethod
    def save_map(image: np.ndarray, save_path: str):
        """Save an image with high quality."""
        cmap = 'gray' if image.ndim == 2 else None
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.figure(figsize=(10, 10))
        plt.imshow(image, cmap=cmap)
        plt.axis('off')
        plt.savefig(save_path, bbox_inches='tight', pad_inches=0, dpi=300)
        plt.close()

class PBRMaps:
    """Generates PBR maps (albedo, normals, roughness, height) from images."""

    def __init__(self, image_dir: str, downsample_scale: float = 1.0, use_gpu: bool = False):
        """Initialize with image directory, downsample scale, and GPU option."""
        self.image_dir = image_dir
        self.downsample_scale = downsample_scale
        self.use_gpu = use_gpu and CUPY_AVAILABLE
        self.xp = cp if self.use_gpu else np
        if self.use_gpu and not CUPY_AVAILABLE:
            print("CuPy not available, falling back to NumPy (CPU).")
            self.use_gpu = False
            self.xp = np
        self.images, self.light_directions = ImageProcessor.load_and_pair_images(image_dir, downsample_scale)
        self.light_directions = self.xp.array(self.light_directions, dtype=self.xp.float32)

    def compute_photometric_stereo(self) -> tuple[np.ndarray, np.ndarray]:
        """Compute albedo and normal maps using photometric stereo."""
        height, width, channels = self.images[0].shape
        num_images = len(self.images)

        if num_images != self.light_directions.shape[0]:
            raise ValueError(f"Image count ({num_images}) does not match light directions ({self.light_directions.shape[0]}).")

        shadow_mask = ImageProcessor.detect_shadows(self.images)
        images_xp = [self.xp.array(img, dtype=self.xp.float32) for img in self.images]
        L = self.xp.array(self.light_directions, dtype=self.xp.float32)

        albedo_rgb = self.xp.zeros((height, width, 3), dtype=self.xp.uint8)
        normals = self.xp.zeros((height, width, 3), dtype=self.xp.float32)

        # Compute G for all RGB channels in one array
        I = self.xp.array([img.reshape(-1, channels) for img in images_xp]).transpose(1, 0, 2)  # Shape: (h * w, num_images, 3)
        G = self.xp.zeros((height * width, 3, 3), dtype=self.xp.float32)
        for c in range(3 if channels == 3 else 1):
            I_channel = I[:, :, c].T  # Shape: (num_images, h * w)
            if self.use_gpu:
                G_channel = lstsq(L.get(), I_channel.get())[0].T
                G[:, :, c] = self.xp.array(G_channel)
            else:
                G_channel, _, _, _ = lstsq(L, I_channel)
                G[:, :, c] = G_channel.T

        # Compute albedo from G
        albedo_rgb = self.xp.linalg.norm(G, axis=1).reshape(height, width, 3)
        albedo_max = self.xp.percentile(albedo_rgb, 99.5, axis=(0, 1))  # Per-channel max
        albedo_rgb = self.xp.clip(albedo_rgb / (albedo_max + 1e-8), 0, 1)
        albedo_rgb = albedo_rgb * 255 * 0.8  # Brightness reduction
        albedo_rgb = albedo_rgb.astype(self.xp.uint8)

        # Compute normals using averaged RGB intensity (or single channel for grayscale)
        I_intensity = self.xp.mean(I, axis=2) if channels == 3 else I[:, :, 0]
        if self.use_gpu:
            G_intensity = lstsq(L.get(), I_intensity.get().T)[0]
            G_intensity = self.xp.array(G_intensity)
        else:
            G_intensity, _, _, _ = lstsq(L, I_intensity.T)
        albedo_intensity = self.xp.linalg.norm(G_intensity, axis=0)
        albedo_intensity_safe = albedo_intensity.copy()
        albedo_intensity_safe[albedo_intensity_safe == 0] = 1e-8
        normals = (G_intensity / albedo_intensity_safe).T.reshape(height, width, 3)
        normals = self.xp.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)
        print("Normals min/max before shadow mask:", normals.min().get() if self.use_gpu else normals.min(), normals.max().get() if self.use_gpu else normals.max())
        normals[~shadow_mask] = [0, 0, 1]
        print("Normals min/max after shadow mask:", normals.min().get() if self.use_gpu else normals.min(), normals.max().get() if self.use_gpu else normals.max())
        print("Shadow mask proportion:", np.mean(shadow_mask))

        # If grayscale input, replicate albedo to RGB
        if channels == 1:
            albedo_rgb = self.xp.stack([albedo_rgb[:, :, 0], albedo_rgb[:, :, 0], albedo_rgb[:, :, 0]], axis=-1)

        albedo_rgb[~shadow_mask] = 0
        albedo_rgb = albedo_rgb.get() if self.use_gpu else albedo_rgb
        albedo_rgb = cv2.cvtColor(albedo_rgb, cv2.COLOR_RGB2BGR)  # Convert to BGR for saving
        normals = normals.get() if self.use_gpu else normals
        
        return albedo_rgb, normals

    def compute_roughness(self, normals: np.ndarray, window_size: int = 5) -> np.ndarray:
        """Compute roughness map from normal variations."""
        height, width = normals.shape[:2]
        normals_xp = self.xp.array(normals, dtype=self.xp.float32)
        roughness = self.xp.zeros((height, width), dtype=self.xp.float32)
        kernel = self.xp.ones((window_size, window_size)) / (window_size * window_size)

        for c in range(3):
            if self.use_gpu:
                mean = cp_ndimage.convolve(normals_xp[:, :, c], kernel, mode='reflect')
                sq_diff = (normals_xp[:, :, c] - mean) ** 2
                roughness += cp_ndimage.convolve(sq_diff, kernel, mode='reflect')
            else:
                mean = scipy_convolve(normals_xp[:, :, c], kernel, mode='reflect')
                sq_diff = (normals_xp[:, :, c] - mean) ** 2
                roughness += scipy_convolve(sq_diff, kernel, mode='reflect')

        roughness = cv2.normalize(roughness.get() if self.use_gpu else roughness, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        return roughness

    def compute_height_map(self, normals: np.ndarray) -> np.ndarray:
        """Compute height map using Frankot-Chellappa algorithm."""
        normals_xp = self.xp.array(normals, dtype=self.xp.float32)
        p = normals_xp[:, :, 0] / (normals_xp[:, :, 2] + 1e-8)
        q = normals_xp[:, :, 1] / (normals_xp[:, :, 2] + 1e-8)
        height, width = p.shape
        y, x = self.xp.mgrid[0:height, 0:width]
        x = x - width / 2
        y = y - height / 2
        denom = (x**2 + y**2)
        denom[denom == 0] = 1

        Px = self.xp.fft.fft2(p)
        Qx = self.xp.fft.fft2(q)
        Z = (-1j * x * Px - 1j * y * Qx) / denom
        height_map = self.xp.real(self.xp.fft.ifft2(Z))
        height_map = self.xp.nan_to_num(height_map, nan=0.0, posinf=0.0, neginf=0.0)
        height_map = cv2.normalize(height_map.get() if self.use_gpu else height_map, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        return height_map
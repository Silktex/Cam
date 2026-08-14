"""
PBR color map generation with optional GPU acceleration.
Adapted from backend/helpers/pbr_maps.py - save_map uses cv2 instead of matplotlib.
"""
import os

import numpy as np
import cv2
from scipy.linalg import lstsq
from scipy.ndimage import convolve as scipy_convolve

try:
    import cupy as cp
    import cupyx.scipy.ndimage as cp_ndimage
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False


class ImageProcessor:
    """Handles image loading, preprocessing, and pairing with light directions."""

    @staticmethod
    def downsample_image(image: np.ndarray, scale_factor: float = 1.0) -> np.ndarray:
        if scale_factor == 1.0:
            return image
        width = int(image.shape[1] * scale_factor)
        height = int(image.shape[0] * scale_factor)
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

    @staticmethod
    def preprocess_image(image: np.ndarray, downsample_scale: float = 1.0) -> np.ndarray:
        denoised = cv2.GaussianBlur(image, (3, 3), 0)
        return ImageProcessor.downsample_image(denoised, downsample_scale)

    @staticmethod
    def load_and_pair_images(image_dir: str, downsample_scale: float = 1.0):
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
            for f in sorted(os.listdir(image_dir))
            if f.lower().endswith(('.tiff', '.tif', '.png', '.jpg', '.jpeg'))
        ]
        paired_images = []
        paired_light_dirs = []
        sorted_keys = sorted(light_directions.keys(), key=len, reverse=True)
        sorted_alt_keys = sorted(alt_names.keys(), key=len, reverse=True)

        for path in image_paths:
            filename = os.path.basename(path).lower()
            image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if image is None:
                continue
            if image.ndim == 2:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            elif image.ndim == 3 and image.shape[2] == 4:
                image = image[:, :, :3]

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
                for alt_key in sorted_alt_keys:
                    if alt_key in filename:
                        seg_key = alt_names[alt_key]
                        preprocessed = ImageProcessor.preprocess_image(image, downsample_scale)
                        paired_images.append(preprocessed)
                        paired_light_dirs.append(light_directions[seg_key])
                        break

        if not paired_images:
            raise ValueError(f"No images loaded from {image_dir}.")

        light_dirs = np.array(paired_light_dirs, dtype=np.float32)
        norms = np.linalg.norm(light_dirs, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        light_dirs /= norms

        if len(paired_images) < 4:
            raise ValueError(f"Need at least 4 images, found {len(paired_images)}.")

        return paired_images, light_dirs

    @staticmethod
    def detect_shadows(images, threshold=0.1):
        intensities = np.mean(
            [cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img for img in images],
            axis=0,
        )
        return intensities > (threshold * np.max(intensities))

    @staticmethod
    def save_map(image: np.ndarray, save_path: str):
        """Save an image as TIFF using cv2 (not matplotlib)."""
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        if image.ndim == 2:
            cv2.imwrite(save_path, image)
        else:
            image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR) if image.shape[2] == 3 else image
            cv2.imwrite(save_path, image_bgr)


class PBRMaps:
    """Generates PBR maps (albedo, normals, roughness, height) from images."""

    def __init__(self, image_dir: str, downsample_scale: float = 1.0, use_gpu: bool = False):
        self.use_gpu = use_gpu and CUPY_AVAILABLE
        self.xp = cp if self.use_gpu else np
        if use_gpu and not CUPY_AVAILABLE:
            self.use_gpu = False
            self.xp = np
        self.images, self.light_directions = ImageProcessor.load_and_pair_images(image_dir, downsample_scale)
        self.light_directions = self.xp.array(self.light_directions, dtype=self.xp.float32)

    def compute_photometric_stereo(self):
        height, width, channels = self.images[0].shape
        num_images = len(self.images)

        shadow_mask = ImageProcessor.detect_shadows(self.images)
        images_xp = [self.xp.array(img, dtype=self.xp.float32) for img in self.images]
        L = self.xp.array(self.light_directions, dtype=self.xp.float32)

        I = self.xp.array([img.reshape(-1, channels) for img in images_xp]).transpose(1, 0, 2)
        G = self.xp.zeros((height * width, 3, 3), dtype=self.xp.float32)

        for c in range(3 if channels == 3 else 1):
            I_channel = I[:, :, c].T
            if self.use_gpu:
                G_channel = lstsq(L.get(), I_channel.get())[0].T
                G[:, :, c] = self.xp.array(G_channel)
            else:
                G_channel, _, _, _ = lstsq(L, I_channel)
                G[:, :, c] = G_channel.T

        albedo_rgb = self.xp.linalg.norm(G, axis=1).reshape(height, width, 3)
        albedo_max = self.xp.percentile(albedo_rgb, 99.5, axis=(0, 1))
        albedo_rgb = self.xp.clip(albedo_rgb / (albedo_max + 1e-8), 0, 1)
        albedo_rgb = (albedo_rgb * 255).astype(self.xp.uint8)

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
        normals[~shadow_mask] = [0, 0, 1]

        if channels == 1:
            albedo_rgb = self.xp.stack([albedo_rgb[:, :, 0]] * 3, axis=-1)

        albedo_rgb[~shadow_mask] = 0
        albedo_rgb = albedo_rgb.get() if self.use_gpu else albedo_rgb
        albedo_rgb = cv2.cvtColor(albedo_rgb, cv2.COLOR_RGB2BGR)
        normals = normals.get() if self.use_gpu else normals

        return albedo_rgb, normals

    def compute_roughness(self, normals, window_size=5):
        normals_xp = self.xp.array(normals, dtype=self.xp.float32)
        height, width = normals.shape[:2]
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

        roughness_np = roughness.get() if self.use_gpu else roughness
        return cv2.normalize(roughness_np, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    def compute_height_map(self, normals):
        normals_xp = self.xp.array(normals, dtype=self.xp.float32)
        p = normals_xp[:, :, 0] / (normals_xp[:, :, 2] + 1e-8)
        q = normals_xp[:, :, 1] / (normals_xp[:, :, 2] + 1e-8)
        height, width = p.shape
        y, x = self.xp.mgrid[0:height, 0:width]
        x = x - width / 2
        y = y - height / 2
        denom = x**2 + y**2
        denom[denom == 0] = 1

        Px = self.xp.fft.fft2(p)
        Qx = self.xp.fft.fft2(q)
        Z = (-1j * x * Px - 1j * y * Qx) / denom
        height_map = self.xp.real(self.xp.fft.ifft2(Z))
        height_map = self.xp.nan_to_num(height_map, nan=0.0, posinf=0.0, neginf=0.0)
        height_map_np = height_map.get() if self.use_gpu else height_map
        return cv2.normalize(height_map_np, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

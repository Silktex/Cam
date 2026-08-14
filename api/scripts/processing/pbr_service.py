"""
PBR Service - Generates PBR maps (albedo, normals, roughness, height) using photometric stereo.
Supports both grayscale and color processing.
Adapted from Django services for FastAPI.
"""
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np
from scipy.linalg import lstsq
from scipy.ndimage import convolve as scipy_convolve

from app.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {'.tiff', '.tif', '.png', '.jpg', '.jpeg'}


def save_pbr_map(img: np.ndarray, path: Path, is_rgb: bool = False):
    """
    Save PBR map as 16-bit PNG for optimal quality and compression.
    PNG gives ~50-70% smaller files than uncompressed TIFF.
    """
    # Ensure 16-bit
    if img.dtype == np.float32 or img.dtype == np.float64:
        img = np.clip(img * 65535, 0, 65535).astype(np.uint16)
    elif img.dtype == np.uint8:
        img = (img.astype(np.uint16) * 257)  # Scale 0-255 to 0-65535

    # Save as 16-bit PNG
    path = path.with_suffix('.png')
    if is_rgb and len(img.shape) == 3:
        # cv2 expects BGR
        cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    else:
        cv2.imwrite(str(path), img)
    return path


class PBRMode(str, Enum):
    GRAYSCALE = "grayscale"
    COLOR = "color"
    BOTH = "both"


@dataclass
class PBRResult:
    success: bool
    mode: str
    output_folder: Optional[str] = None
    albedo_path: Optional[str] = None
    normals_path: Optional[str] = None
    roughness_path: Optional[str] = None
    height_map_path: Optional[str] = None
    error: Optional[str] = None


# Light directions mapped to position names (top, side_1-8)
LIGHT_DIRECTIONS = {
    'top': [0, 0, 1],
    'side_1': [0, 1, 1],      # front
    'side_2': [-1, 1, 1],     # front_left
    'side_3': [-1, 0, 1],     # left
    'side_4': [-1, -1, 1],    # rear_left
    'side_5': [0, -1, 1],     # rear
    'side_6': [1, -1, 1],     # rear_right
    'side_7': [1, 0, 1],      # right
    'side_8': [1, 1, 1],      # front_right
}


class PBRService:
    """Generates PBR maps using photometric stereo."""

    def __init__(self, use_gpu: bool = None, downsample_scale: float = None):
        self.use_gpu = use_gpu if use_gpu is not None else settings.USE_GPU
        self.downsample_scale = downsample_scale if downsample_scale is not None else settings.DOWNSAMPLE_SCALE

        # GPU acceleration via CuPy (NVIDIA) - fallback to NumPy
        self.xp = np
        if self.use_gpu:
            try:
                import cupy as cp
                import cupyx.scipy.ndimage as cp_ndimage
                self.xp = cp
                self.cp_ndimage = cp_ndimage
                logger.info("Using CuPy for GPU acceleration")
            except ImportError:
                logger.warning("CuPy not available, using NumPy (CPU)")
                self.use_gpu = False

    def generate(
        self,
        batch_path: str,
        mode: PBRMode = PBRMode.BOTH,
        selected_images: List[str] = None,
        use_calibrated: bool = True,
        source_folder: str = None,
    ) -> List[PBRResult]:
        """
        Generate PBR maps for a batch.

        Args:
            batch_path: Path to batch folder
            mode: grayscale, color, or both
            selected_images: List of specific images to use (None = all)
            use_calibrated: If True, use color_calibrated/ folder
            source_folder: Override source folder (e.g. pipeline cache)

        Returns:
            List of PBRResult objects
        """
        batch_path = Path(batch_path)
        results = []

        # Determine source folder
        if source_folder is not None:
            source_folder = Path(source_folder)
        else:
            source_folder = self._get_source_folder(batch_path, use_calibrated)
        if not source_folder:
            return [PBRResult(
                success=False,
                mode=mode.value,
                error="No source images found"
            )]

        if mode in [PBRMode.GRAYSCALE, PBRMode.BOTH]:
            result = self._generate_grayscale(batch_path, source_folder, selected_images)
            results.append(result)

        if mode in [PBRMode.COLOR, PBRMode.BOTH]:
            result = self._generate_color(batch_path, source_folder, selected_images)
            results.append(result)

        return results

    def _generate_grayscale(
        self,
        batch_path: Path,
        source_folder: Path,
        selected_images: List[str] = None
    ) -> PBRResult:
        """Generate grayscale PBR maps."""
        try:
            output_folder = batch_path / "pbr_grayscale"
            output_folder.mkdir(exist_ok=True)

            # Load images: top image = albedo, side images = photometric stereo
            top_image, side_images, light_dirs = self._load_and_pair_images(
                source_folder, selected_images, grayscale=True
            )

            if len(side_images) < 3:
                return PBRResult(
                    success=False,
                    mode="grayscale",
                    error=f"Need at least 3 side-lit images, found {len(side_images)}"
                )

            # Top image is the albedo (direct capture under even top light)
            if top_image is not None:
                albedo = top_image
            else:
                logger.warning("No top image found, computing albedo from photometric stereo")
                albedo, _ = self._photometric_stereo_grayscale(side_images, light_dirs)

            # Compute normals from side-lit images only
            normals = self._compute_normals_grayscale(side_images, light_dirs)
            roughness = self._compute_roughness(normals)
            height_map = self._compute_height_map(normals)
            normals_rgb = self._visualize_normals(normals)

            # Save maps as 16-bit PNG (optimal quality + compression)
            albedo_path = save_pbr_map(albedo, output_folder / "albedo")
            normals_path = save_pbr_map(normals_rgb, output_folder / "normals", is_rgb=True)
            roughness_path = save_pbr_map(roughness, output_folder / "roughness")
            height_path = save_pbr_map(height_map, output_folder / "height_map")

            logger.info(f"Generated grayscale PBR maps in {output_folder}")

            return PBRResult(
                success=True,
                mode="grayscale",
                output_folder=str(output_folder),
                albedo_path=str(albedo_path),
                normals_path=str(normals_path),
                roughness_path=str(roughness_path),
                height_map_path=str(height_path)
            )

        except Exception as e:
            logger.error(f"Grayscale PBR generation failed: {e}")
            return PBRResult(
                success=False,
                mode="grayscale",
                error=str(e)
            )

    def _generate_color(
        self,
        batch_path: Path,
        source_folder: Path,
        selected_images: List[str] = None
    ) -> PBRResult:
        """Generate color PBR maps."""
        try:
            output_folder = batch_path / "pbr_colored"
            output_folder.mkdir(exist_ok=True)

            # Load images: top image = albedo, side images = photometric stereo
            top_image, side_images, light_dirs = self._load_and_pair_images(
                source_folder, selected_images, grayscale=False
            )

            if len(side_images) < 3:
                return PBRResult(
                    success=False,
                    mode="color",
                    error=f"Need at least 3 side-lit images, found {len(side_images)}"
                )

            # Top image is the albedo (direct capture under even top light)
            if top_image is not None:
                albedo = top_image
            else:
                logger.warning("No top image found, computing albedo from photometric stereo")
                albedo, _ = self._photometric_stereo_color(side_images, light_dirs)

            # Compute normals from side-lit images only
            normals = self._compute_normals_color(side_images, light_dirs)
            roughness = self._compute_roughness(normals)
            height_map = self._compute_height_map(normals)
            normals_rgb = self._visualize_normals(normals)

            # Save maps as 16-bit PNG (optimal quality + compression)
            albedo_path = save_pbr_map(albedo, output_folder / "albedo")
            normals_path = save_pbr_map(normals_rgb, output_folder / "normals", is_rgb=True)
            roughness_path = save_pbr_map(roughness, output_folder / "roughness")
            height_path = save_pbr_map(height_map, output_folder / "height_map")

            logger.info(f"Generated color PBR maps in {output_folder}")

            return PBRResult(
                success=True,
                mode="color",
                output_folder=str(output_folder),
                albedo_path=str(albedo_path),
                normals_path=str(normals_path),
                roughness_path=str(roughness_path),
                height_map_path=str(height_path)
            )

        except Exception as e:
            logger.error(f"Color PBR generation failed: {e}")
            return PBRResult(
                success=False,
                mode="color",
                error=str(e)
            )

    def _load_and_pair_images(
        self,
        source_folder: Path,
        selected_images: List[str] = None,
        grayscale: bool = False
    ) -> Tuple[Optional[np.ndarray], List[np.ndarray], np.ndarray]:
        """
        Load images and separate top (albedo) from side-lit (photometric stereo).

        Returns:
            (top_image, side_images, side_light_dirs)
            - top_image: calibrated top-light image used as albedo (None if not found)
            - side_images: list of side-lit images for photometric stereo
            - side_light_dirs: normalized light direction vectors for side images
        """
        top_image = None
        side_images = []
        side_light_dirs = []

        image_files = self._list_images(source_folder)

        for image_path in image_files:
            filename = image_path.name.lower()

            # Skip if not in selected images
            if selected_images and image_path.name not in selected_images:
                continue

            # Match to light direction
            matched_position = None
            matched_dir = None
            for position, direction in LIGHT_DIRECTIONS.items():
                if position in filename or position.replace('_', '') in filename:
                    matched_position = position
                    matched_dir = direction
                    break

            if matched_position is None:
                logger.warning(f"No light direction match for: {filename}")
                continue

            # Load image
            img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
            if img is None:
                continue

            # Convert to grayscale if needed
            if grayscale:
                if len(img.shape) == 3:
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            else:
                if len(img.shape) == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                elif img.shape[2] == 4:
                    img = img[:, :, :3]

            # Preprocess (denoise + downsample)
            img = self._preprocess_image(img)

            # Top image → albedo; side images → photometric stereo
            if matched_position == 'top':
                top_image = img
                logger.info(f"Using top image as albedo: {image_path.name}")
            else:
                side_images.append(img)
                side_light_dirs.append(matched_dir)
                logger.debug(f"Loaded side image {filename} -> {matched_position}")

        if not side_images:
            raise ValueError(f"No side-lit images loaded from {source_folder}")

        # Normalize light directions
        side_light_dirs = np.array(side_light_dirs, dtype=np.float32)
        norms = np.linalg.norm(side_light_dirs, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        side_light_dirs /= norms

        logger.info(f"Loaded {len(side_images)} side images + {'top' if top_image is not None else 'no top'}")
        return top_image, side_images, side_light_dirs

    def _preprocess_image(self, img: np.ndarray) -> np.ndarray:
        """Denoise and downsample image."""
        # Gaussian blur for denoising
        denoised = cv2.GaussianBlur(img, (3, 3), 0)

        # Downsample if needed
        if self.downsample_scale != 1.0:
            width = int(img.shape[1] * self.downsample_scale)
            height = int(img.shape[0] * self.downsample_scale)
            denoised = cv2.resize(denoised, (width, height), interpolation=cv2.INTER_AREA)

        return denoised

    def _photometric_stereo_grayscale(
        self,
        images: List[np.ndarray],
        light_dirs: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute albedo and normals using photometric stereo (grayscale)."""
        num_images = len(images)
        h, w = images[0].shape

        # Stack images into shape (N, H, W)
        I = np.stack(images, axis=0).astype(np.float32)
        L = light_dirs.astype(np.float32)

        # Reshape intensities into (N, H*W)
        I_flat = I.reshape(num_images, -1)

        # Solve Least Squares: L * G = I
        G, _, _, _ = lstsq(L, I_flat)

        # Compute albedo = ||G|| for each pixel
        albedo = np.linalg.norm(G, axis=0).reshape(h, w)

        # Prevent division by zero
        albedo_safe = np.where(albedo == 0, 1e-8, albedo)

        # Compute normalized normals
        normals = (G / albedo_safe.reshape(1, -1)).T.reshape(h, w, 3)
        normals = np.nan_to_num(normals).astype(np.float32)

        # Normalize albedo for display (0-255)
        scale = np.percentile(albedo, 99.5)
        scale = max(scale, 1e-8)
        albedo_norm = np.clip(albedo / scale, 0, 1)
        albedo_gray = (albedo_norm * 255).astype(np.uint8)

        return albedo_gray, normals

    def _photometric_stereo_color(
        self,
        images: List[np.ndarray],
        light_dirs: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Compute albedo and normals using photometric stereo (color)."""
        num_images = len(images)
        h, w, channels = images[0].shape

        # Detect shadows
        shadow_mask = self._detect_shadows(images)

        # Stack and reshape
        I = np.array([img.reshape(-1, channels) for img in images]).transpose(1, 0, 2)
        L = light_dirs.astype(np.float32)

        # Compute G for all RGB channels
        G = np.zeros((h * w, 3, 3), dtype=np.float32)
        for c in range(channels):
            I_channel = I[:, :, c].T
            G_channel, _, _, _ = lstsq(L, I_channel)
            G[:, :, c] = G_channel.T

        # Compute color albedo
        albedo_rgb = np.linalg.norm(G, axis=1).reshape(h, w, 3)
        albedo_max = np.percentile(albedo_rgb, 99.5, axis=(0, 1))
        albedo_rgb = np.clip(albedo_rgb / (albedo_max + 1e-8), 0, 1)
        albedo_rgb = (albedo_rgb * 255).astype(np.uint8)

        # Compute normals from intensity
        I_intensity = np.mean(I, axis=2)
        G_intensity, _, _, _ = lstsq(L, I_intensity.T)

        albedo_intensity = np.linalg.norm(G_intensity, axis=0)
        albedo_intensity_safe = np.where(albedo_intensity == 0, 1e-8, albedo_intensity)

        normals = (G_intensity / albedo_intensity_safe).T.reshape(h, w, 3)
        normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)
        normals[~shadow_mask] = [0, 0, 1]

        # Apply shadow mask to albedo
        albedo_rgb[~shadow_mask] = 0
        albedo_rgb = cv2.cvtColor(albedo_rgb, cv2.COLOR_RGB2BGR)

        return albedo_rgb, normals

    def _compute_normals_grayscale(
        self,
        images: List[np.ndarray],
        light_dirs: np.ndarray
    ) -> np.ndarray:
        """Compute normals from side-lit grayscale images using photometric stereo."""
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

        return normals

    def _compute_normals_color(
        self,
        images: List[np.ndarray],
        light_dirs: np.ndarray
    ) -> np.ndarray:
        """Compute normals from side-lit color images using photometric stereo."""
        num_images = len(images)
        h, w, channels = images[0].shape

        shadow_mask = self._detect_shadows(images)

        I = np.array([img.reshape(-1, channels) for img in images]).transpose(1, 0, 2)
        L = light_dirs.astype(np.float32)

        # Compute normals from intensity (average across channels)
        I_intensity = np.mean(I, axis=2)
        G_intensity, _, _, _ = lstsq(L, I_intensity.T)

        albedo_intensity = np.linalg.norm(G_intensity, axis=0)
        albedo_intensity_safe = np.where(albedo_intensity == 0, 1e-8, albedo_intensity)

        normals = (G_intensity / albedo_intensity_safe).T.reshape(h, w, 3)
        normals = np.nan_to_num(normals, nan=0.0, posinf=0.0, neginf=0.0)
        normals[~shadow_mask] = [0, 0, 1]

        return normals

    def _detect_shadows(self, images: List[np.ndarray], threshold: float = 0.1) -> np.ndarray:
        """Detect shadow regions based on intensity threshold."""
        intensities = np.mean([
            cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
            for img in images
        ], axis=0)
        return intensities > (threshold * np.max(intensities))

    def _compute_roughness(
        self,
        normals: np.ndarray,
        lambert_residual: np.ndarray = None,
        window_size: int = 17,
    ) -> np.ndarray:
        """Compute physically-based roughness from two complementary signals:

        1. Lambert residual (per-pixel): How much reality deviates from perfect
           Lambertian reflectance. Measures non-Lambert scattering (specular
           micro-facets, subsurface, fiber fuzz). PHYSICAL roughness.

        2. Normal variance (local window): How much surface normals vary in a
           neighborhood. Captures STRUCTURAL roughness (weave pattern, wrinkles).

        Combined via geometric mean: roughness = sqrt(residual * normal_var).
        Falls back to normal-variance-only when no residual is available.
        """
        h, w = normals.shape[:2]

        # ── Component 2: Normal variance (structural macro-roughness) ──
        normal_var = np.zeros((h, w), dtype=np.float32)
        kernel = np.ones((window_size, window_size)) / (window_size * window_size)
        for c in range(3):
            mean = scipy_convolve(normals[:, :, c], kernel, mode='reflect')
            sq_diff = (normals[:, :, c] - mean) ** 2
            normal_var += scipy_convolve(sq_diff, kernel, mode='reflect')

        def robust_normalize(arr):
            p2 = np.percentile(arr, 2)
            p98 = np.percentile(arr, 98)
            if p98 - p2 < 1e-8:
                return np.ones_like(arr) * 0.5
            normed = (arr - p2) / (p98 - p2)
            return np.clip(normed, 0, 1)

        v_norm = robust_normalize(normal_var)

        if lambert_residual is not None:
            # ── Component 1: Lambert residual (physical micro-roughness) ──
            residual = scipy_convolve(
                lambert_residual.astype(np.float32),
                np.ones((5, 5)) / 25.0, mode='reflect'
            )
            r_norm = robust_normalize(residual)

            # Geometric mean: both must be high for roughness to be high
            roughness = np.sqrt(r_norm * v_norm)
            roughness = robust_normalize(roughness)
        else:
            roughness = v_norm

        return (roughness * 255).clip(0, 255).astype(np.uint8)

    def _compute_height_map(self, normals: np.ndarray) -> np.ndarray:
        """Compute height map using Frankot-Chellappa algorithm."""
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
        height_map = np.real(np.fft.ifft2(Z))
        height_map = np.nan_to_num(height_map, nan=0.0, posinf=0.0, neginf=0.0)

        return cv2.normalize(height_map, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    def _visualize_normals(self, normals: np.ndarray) -> np.ndarray:
        """Convert normals to RGB for visualization."""
        normals_rgb = (normals + 1) / 2
        normals_rgb = (normals_rgb * 255).astype(np.uint8)
        return normals_rgb

    def _get_source_folder(self, batch_path: Path, use_calibrated: bool) -> Optional[Path]:
        """Get source folder for PBR generation.
        Priority chain includes material tool output folders:
        seamless > delighted > equalized > perspective_corrected > color_calibrated > cropped > tiff
        """
        # Check material tool output folders first (most processed → least)
        tool_folders = ['seamless', 'delighted', 'equalized', 'perspective_corrected']
        for folder_name in tool_folders:
            folder = batch_path / folder_name
            if folder.exists() and list(folder.glob("*")):
                return folder

        if use_calibrated:
            calibrated = batch_path / "color_calibrated"
            if calibrated.exists() and list(calibrated.glob("*")):
                return calibrated

        cropped = batch_path / "cropped"
        if cropped.exists() and list(cropped.glob("*")):
            return cropped

        tiff = batch_path / "tiff"
        if tiff.exists() and list(tiff.glob("*")):
            return tiff

        return None

    def _list_images(self, folder: Path) -> List[Path]:
        """List all images in folder."""
        images = []
        for ext in SUPPORTED_EXTENSIONS:
            images.extend(folder.glob(f"*{ext}"))
            images.extend(folder.glob(f"*{ext.upper()}"))
        return sorted(images)

    def get_preview(self, batch_path: str, mode: str = "grayscale") -> Optional[Dict]:
        """
        Get preview of generated PBR maps.

        Returns:
            Dict with URLs for albedo, normals, roughness, height_map
        """
        batch_path = Path(batch_path)
        folder_name = "pbr_grayscale" if mode == "grayscale" else "pbr_colored"
        pbr_folder = batch_path / folder_name

        if not pbr_folder.exists():
            return None

        batch_name = batch_path.name
        base_url = f"/media/captures/{batch_name}/{folder_name}"

        return {
            "mode": mode,
            "albedo_url": f"{base_url}/albedo.tiff" if (pbr_folder / "albedo.tiff").exists() else None,
            "normals_url": f"{base_url}/normals.tiff" if (pbr_folder / "normals.tiff").exists() else None,
            "roughness_url": f"{base_url}/roughness.tiff" if (pbr_folder / "roughness.tiff").exists() else None,
            "height_map_url": f"{base_url}/height_map.tiff" if (pbr_folder / "height_map.tiff").exists() else None,
        }

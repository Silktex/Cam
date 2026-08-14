"""
Shared test fixtures for material processing tool tests.

Provides synthetic images, mock batch directories, and test utilities
that mirror real batch structures without requiring camera hardware.
"""
import base64
import io
import logging
from pathlib import Path

import cv2
import numpy as np
import pytest

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Synthetic Image Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def synthetic_image_8bit():
    """512×512 BGR uint8 with gradient + noise pattern.

    Not flat — has enough variation for histogram/equalization tests.
    Seeded RNG for reproducibility.
    """
    rng = np.random.RandomState(42)
    # Linear gradient left-to-right (50→200 in blue channel)
    gradient = np.linspace(50, 200, 512, dtype=np.float32)
    base = np.zeros((512, 512, 3), dtype=np.float32)
    base[:, :, 0] = gradient[np.newaxis, :]       # B channel gradient
    base[:, :, 1] = gradient[np.newaxis, :] * 0.8  # G slightly dimmer
    base[:, :, 2] = gradient[np.newaxis, :] * 0.6  # R dimmer still
    # Add noise
    noise = rng.normal(0, 10, (512, 512, 3)).astype(np.float32)
    img = np.clip(base + noise, 0, 255).astype(np.uint8)
    return img


@pytest.fixture
def synthetic_image_16bit():
    """512×512 BGR uint16 (0–65535) with gradient + noise.

    Tests 16-bit code paths in every service.
    """
    rng = np.random.RandomState(42)
    gradient = np.linspace(5000, 50000, 512, dtype=np.float64)
    base = np.zeros((512, 512, 3), dtype=np.float64)
    base[:, :, 0] = gradient[np.newaxis, :]
    base[:, :, 1] = gradient[np.newaxis, :] * 0.8
    base[:, :, 2] = gradient[np.newaxis, :] * 0.6
    noise = rng.normal(0, 500, (512, 512, 3))
    img = np.clip(base + noise, 0, 65535).astype(np.uint16)
    return img


@pytest.fixture
def synthetic_image_with_lines():
    """800×600 image with drawn rectangles and lines for Hough detection.

    Has clear edges for perspective detect_lines() testing.
    """
    img = np.full((600, 800, 3), 180, dtype=np.uint8)  # light gray background
    # Draw a strong rectangle (fabric-like boundary)
    cv2.rectangle(img, (100, 80), (700, 520), (40, 40, 40), 3)
    # Draw inner lines for extra detection
    cv2.line(img, (100, 80), (700, 80), (40, 40, 40), 2)    # top
    cv2.line(img, (100, 520), (700, 520), (40, 40, 40), 2)   # bottom
    cv2.line(img, (100, 80), (100, 520), (40, 40, 40), 2)    # left
    cv2.line(img, (700, 80), (700, 520), (40, 40, 40), 2)    # right
    return img


@pytest.fixture
def synthetic_gradient_image():
    """512×512 with strong left-to-right luminance gradient.

    Useful for delight service tests (removing lighting gradients).
    """
    img = np.zeros((512, 512, 3), dtype=np.uint8)
    gradient = np.linspace(50, 200, 512, dtype=np.uint8)
    for c in range(3):
        img[:, :, c] = gradient[np.newaxis, :]
    return img


@pytest.fixture
def bright_reference_image():
    """512×512 bright image (mean ~200) for histogram match tests."""
    rng = np.random.RandomState(99)
    base = np.full((512, 512, 3), 200, dtype=np.float32)
    noise = rng.normal(0, 15, (512, 512, 3)).astype(np.float32)
    return np.clip(base + noise, 0, 255).astype(np.uint8)


@pytest.fixture
def dark_source_image():
    """512×512 dark image (mean ~50) for equalization tests."""
    rng = np.random.RandomState(77)
    base = np.full((512, 512, 3), 50, dtype=np.float32)
    noise = rng.normal(0, 10, (512, 512, 3)).astype(np.float32)
    return np.clip(base + noise, 0, 255).astype(np.uint8)


# ──────────────────────────────────────────────
# Mock Batch Directory Fixtures
# ──────────────────────────────────────────────

def _save_synthetic_tiff(path: Path, img: np.ndarray):
    """Save image as TIFF via cv2 (works for both 8 and 16-bit)."""
    cv2.imwrite(str(path), img)


@pytest.fixture
def mock_batch_dir(tmp_path, synthetic_image_8bit):
    """Creates a mock batch directory with source priority folders.

    Structure:
        tmp_path/test_batch/
            tiff/
                material_top.tiff
                material_side1.tiff
            cropped/
                material_top.tiff
                material_side1.tiff
            color_calibrated/
                material_top.tiff
                material_side1.tiff
    """
    batch = tmp_path / "test_batch"
    batch.mkdir()

    img = synthetic_image_8bit
    # Create a slightly different second image
    img2 = np.roll(img, 50, axis=1)

    for folder_name in ["tiff", "cropped", "color_calibrated"]:
        folder = batch / folder_name
        folder.mkdir()
        _save_synthetic_tiff(folder / "material_top.tiff", img)
        _save_synthetic_tiff(folder / "material_side1.tiff", img2)

    return batch


@pytest.fixture
def mock_batch_dir_16bit(tmp_path, synthetic_image_16bit):
    """Mock batch with 16-bit TIFF images."""
    batch = tmp_path / "test_batch_16bit"
    batch.mkdir()

    img = synthetic_image_16bit
    for folder_name in ["tiff", "cropped", "color_calibrated"]:
        folder = batch / folder_name
        folder.mkdir()
        _save_synthetic_tiff(folder / "material_top.tiff", img)

    return batch


@pytest.fixture
def mock_batch_with_seamless(mock_batch_dir, synthetic_image_8bit):
    """Adds seamless/ folder to existing mock batch."""
    seamless = mock_batch_dir / "seamless"
    seamless.mkdir()
    _save_synthetic_tiff(seamless / "material_top.tiff", synthetic_image_8bit)
    _save_synthetic_tiff(seamless / "material_side1.tiff", np.roll(synthetic_image_8bit, 50, axis=1))
    return mock_batch_dir


@pytest.fixture
def mock_batch_with_perspective(mock_batch_dir, synthetic_image_8bit):
    """Adds perspective_corrected/ folder to existing mock batch."""
    persp = mock_batch_dir / "perspective_corrected"
    persp.mkdir()
    _save_synthetic_tiff(persp / "material_top.tiff", synthetic_image_8bit)
    return mock_batch_dir


@pytest.fixture
def mock_batch_with_equalized(mock_batch_dir, synthetic_image_8bit):
    """Adds equalized/ folder for delight service source priority."""
    eq = mock_batch_dir / "equalized"
    eq.mkdir()
    _save_synthetic_tiff(eq / "material_top.tiff", synthetic_image_8bit)
    _save_synthetic_tiff(eq / "material_side1.tiff", np.roll(synthetic_image_8bit, 50, axis=1))
    return mock_batch_dir


@pytest.fixture
def mock_batch_with_pbr(tmp_path):
    """Creates batch with pbr_grayscale/ containing PBR maps.

    Maps: albedo, normal, roughness, height, metallic.
    """
    batch = tmp_path / "test_batch_pbr"
    batch.mkdir()

    pbr = batch / "pbr_grayscale"
    pbr.mkdir()

    # Albedo: mid-range (mean ~128)
    rng = np.random.RandomState(42)
    albedo = np.clip(rng.normal(128, 30, (256, 256, 3)), 0, 255).astype(np.uint8)
    cv2.imwrite(str(pbr / "material_albedo.png"), albedo)

    # Normal map: typical normal map with blue-dominant
    normal = np.full((256, 256, 3), 128, dtype=np.uint8)
    normal[:, :, 0] = 255  # Blue channel high (Z direction)
    cv2.imwrite(str(pbr / "material_normal.png"), normal)

    # Roughness: mid-range single channel
    roughness = np.clip(rng.normal(128, 40, (256, 256)), 0, 255).astype(np.uint8)
    roughness_bgr = cv2.cvtColor(roughness, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(str(pbr / "material_roughness.png"), roughness_bgr)

    # Height: gradient
    height = np.linspace(80, 180, 256, dtype=np.uint8)
    height_img = np.tile(height, (256, 1))
    height_bgr = cv2.cvtColor(height_img, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(str(pbr / "material_height.png"), height_bgr)

    # Metallic: binary (half black, half white)
    metallic = np.zeros((256, 256), dtype=np.uint8)
    metallic[:, 128:] = 255
    metallic_bgr = cv2.cvtColor(metallic, cv2.COLOR_GRAY2BGR)
    cv2.imwrite(str(pbr / "material_metallic.png"), metallic_bgr)

    return batch


@pytest.fixture
def mock_batch_dark_albedo(tmp_path):
    """Batch with very dark albedo map (mean ~10) for validation failure test."""
    batch = tmp_path / "test_batch_dark"
    batch.mkdir()

    pbr = batch / "pbr_grayscale"
    pbr.mkdir()

    dark = np.full((256, 256, 3), 10, dtype=np.uint8)
    cv2.imwrite(str(pbr / "material_albedo.png"), dark)

    return batch


@pytest.fixture
def mock_batch_gray_metallic(tmp_path):
    """Batch with ambiguous gray metallic map for validation failure test."""
    batch = tmp_path / "test_batch_gray_metal"
    batch.mkdir()

    pbr = batch / "pbr_grayscale"
    pbr.mkdir()

    gray = np.full((256, 256, 3), 128, dtype=np.uint8)
    cv2.imwrite(str(pbr / "material_metallic.png"), gray)

    return batch


@pytest.fixture
def mock_batch_with_straightened(mock_batch_dir, synthetic_image_8bit):
    """Adds straightened/ folder to existing mock batch."""
    straightened = mock_batch_dir / "straightened"
    straightened.mkdir()
    _save_synthetic_tiff(straightened / "material_top.tiff", synthetic_image_8bit)
    _save_synthetic_tiff(straightened / "material_side1.tiff", np.roll(synthetic_image_8bit, 50, axis=1))
    return mock_batch_dir


@pytest.fixture
def synthetic_weave_image():
    """512x512 synthetic woven fabric pattern with alternating H/V stripes at 8px intervals.

    Useful for straighten service yarn detection tests.
    """
    img = np.full((512, 512, 3), 200, dtype=np.uint8)  # light background
    # Horizontal stripes (weft yarns)
    for y in range(0, 512, 16):
        img[y:y+8, :] = [80, 80, 80]
    # Vertical stripes (warp yarns)
    for x in range(0, 512, 16):
        img[:, x:x+8] = np.minimum(img[:, x:x+8], [120, 120, 120])
    return img


@pytest.fixture
def empty_batch_dir(tmp_path):
    """Empty batch directory with no source folders."""
    batch = tmp_path / "empty_batch"
    batch.mkdir()
    return batch


# ──────────────────────────────────────────────
# Clone/Inpaint Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def base64_mask_data():
    """Valid base64-encoded PNG mask (white circle on black).

    512×512 mask with white circle of radius 50 at center.
    """
    mask = np.zeros((512, 512), dtype=np.uint8)
    cv2.circle(mask, (256, 256), 50, 255, -1)

    _, png_buffer = cv2.imencode('.png', mask)
    b64 = base64.b64encode(png_buffer.tobytes()).decode('utf-8')
    return b64


@pytest.fixture
def base64_mask_data_with_prefix(base64_mask_data):
    """Base64 mask with data URL prefix for _decode_mask strip test."""
    return f"data:image/png;base64,{base64_mask_data}"


@pytest.fixture
def image_with_red_square(synthetic_image_8bit):
    """Image with a red square for inpaint testing.

    Red square at (200, 200) to (300, 300).
    """
    img = synthetic_image_8bit.copy()
    img[200:300, 200:300] = [0, 0, 255]  # BGR red
    return img


@pytest.fixture
def mask_for_red_square():
    """Mask covering the red square region for inpaint test."""
    mask = np.zeros((512, 512), dtype=np.uint8)
    mask[200:300, 200:300] = 255
    _, png_buffer = cv2.imencode('.png', mask)
    return base64.b64encode(png_buffer.tobytes()).decode('utf-8')


# ──────────────────────────────────────────────
# Utility Helpers
# ──────────────────────────────────────────────

@pytest.fixture
def save_temp_image(tmp_path):
    """Returns a helper function to save an image to a temp path."""
    def _save(img: np.ndarray, name: str = "test_image.tiff") -> Path:
        path = tmp_path / name
        cv2.imwrite(str(path), img)
        return path
    return _save

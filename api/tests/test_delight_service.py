"""
Tests for Delight Service — lighting removal from material textures.

Covers Gaussian and frequency separation delighting core functions,
plus preview/apply integration with source folder priority.
"""
import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# Direct module import to avoid __init__.py dependency chain
_mod_path = Path(__file__).resolve().parents[1] / "scripts" / "processing" / "delight_service.py"
_spec = importlib.util.spec_from_file_location("delight_service", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

delight_gaussian = _mod.delight_gaussian
delight_frequency_separation = _mod.delight_frequency_separation
preview = _mod.preview
apply = _mod.apply
_find_source_folder = _mod._find_source_folder


# ──────────────────────────────────────────────
# DL-01 through DL-05: Gaussian Delighting
# ──────────────────────────────────────────────

class TestDelightGaussian:

    def test_dl01_gaussian_flattens_luminance_gradient(self, synthetic_gradient_image):
        """DL-01: Gaussian delight flattens luminance (output L stddev < input L stddev)."""
        result = delight_gaussian(synthetic_gradient_image)

        # Compute L-channel standard deviation before and after
        input_lab = cv2.cvtColor(synthetic_gradient_image, cv2.COLOR_BGR2LAB)
        result_lab = cv2.cvtColor(result, cv2.COLOR_BGR2LAB)

        input_l_std = input_lab[:, :, 0].astype(np.float64).std()
        result_l_std = result_lab[:, :, 0].astype(np.float64).std()

        assert result_l_std < input_l_std, (
            f"Delighted L stddev ({result_l_std:.2f}) should be less than "
            f"input L stddev ({input_l_std:.2f})"
        )

    def test_dl02_preserves_uint8_shape_and_dtype(self, synthetic_image_8bit):
        """DL-02: Gaussian delight preserves uint8 shape and dtype."""
        result = delight_gaussian(synthetic_image_8bit)
        assert result.dtype == np.uint8
        assert result.shape == synthetic_image_8bit.shape

    def test_dl03_preserves_uint16_shape_and_dtype(self, synthetic_image_16bit):
        """DL-03: Gaussian delight preserves uint16 shape and dtype."""
        result = delight_gaussian(synthetic_image_16bit)
        assert result.dtype == np.uint16
        assert result.shape == synthetic_image_16bit.shape

    def test_dl04_strength_zero_returns_near_original(self, synthetic_image_8bit):
        """DL-04: strength=0 returns near-original.

        Note: BGR->LAB->BGR roundtrip introduces up to ~7 levels of
        quantization error, so we verify >99% of pixels are within atol=2
        and no pixel differs by more than 8 (LAB roundtrip ceiling).
        """
        result = delight_gaussian(synthetic_image_8bit, strength=0.0)
        diff = np.abs(result.astype(np.int16) - synthetic_image_8bit.astype(np.int16))
        pct_within_2 = (diff <= 2).mean()
        assert pct_within_2 > 0.99, (
            f"Expected >99% of pixels within atol=2, got {pct_within_2*100:.2f}%"
        )
        assert diff.max() <= 8, (
            f"Max diff should be <=8 (LAB roundtrip), got {diff.max()}"
        )

    @pytest.mark.parametrize("blur_radius", [199, 200, 201])
    def test_dl05_even_and_odd_blur_radius(self, synthetic_image_8bit, blur_radius):
        """DL-05: Both even and odd blur_radius values work without crash."""
        result = delight_gaussian(synthetic_image_8bit, blur_radius=blur_radius)
        assert result.shape == synthetic_image_8bit.shape
        assert result.dtype == np.uint8


# ──────────────────────────────────────────────
# DL-06 through DL-07: Frequency Separation
# ──────────────────────────────────────────────

class TestDelightFrequencySeparation:

    def test_dl06_frequency_separation_produces_valid_output(self, synthetic_image_8bit):
        """DL-06: Frequency separation produces valid output (no NaN/Inf, correct shape)."""
        result = delight_frequency_separation(synthetic_image_8bit)
        assert result.shape == synthetic_image_8bit.shape
        assert result.dtype == synthetic_image_8bit.dtype
        # Check for NaN/Inf (convert to float to test)
        result_f = result.astype(np.float64)
        assert not np.any(np.isnan(result_f)), "Output contains NaN values"
        assert not np.any(np.isinf(result_f)), "Output contains Inf values"

    def test_dl07_frequency_separation_strength_zero(self, synthetic_image_8bit):
        """DL-07: frequency_separation strength=0 returns near-original."""
        result = delight_frequency_separation(synthetic_image_8bit, strength=0.0)
        assert np.allclose(result, synthetic_image_8bit, atol=2), (
            "strength=0 should produce output nearly identical to input"
        )


# ──────────────────────────────────────────────
# DL-08 through DL-09: Preview Integration
# ──────────────────────────────────────────────

class TestDelightPreview:

    def test_dl08_preview_returns_success(self, mock_batch_dir):
        """DL-08: preview() returns success, before_url, after_url."""
        result = preview(str(mock_batch_dir))
        assert result["success"] is True
        assert "before_url" in result
        assert "after_url" in result

    @pytest.mark.parametrize("method", ["gaussian", "frequency_separation"])
    def test_dl09_preview_parametrized_methods(self, mock_batch_dir, method):
        """DL-09: preview() works for both gaussian and frequency_separation methods."""
        result = preview(str(mock_batch_dir), method=method)
        assert result["success"] is True
        assert result["method"] == method
        assert "before_url" in result
        assert "after_url" in result


# ──────────────────────────────────────────────
# DL-10 through DL-11: Apply Integration
# ──────────────────────────────────────────────

class TestDelightApply:

    def test_dl10_apply_creates_output_dirs_with_correct_counts(self, mock_batch_dir):
        """DL-10: apply() creates delighted/ and delighted_thumbnail/ with correct file counts."""
        result = apply(str(mock_batch_dir))
        assert result["success"] is True
        assert result["processed"] == 2  # material_top + material_side1
        assert result["total"] == 2

        delighted_dir = mock_batch_dir / "delighted"
        thumb_dir = mock_batch_dir / "delighted_thumbnail"
        assert delighted_dir.exists(), "delighted/ dir should be created"
        assert thumb_dir.exists(), "delighted_thumbnail/ dir should be created"

        delighted_files = list(delighted_dir.glob("*.tiff"))
        thumb_files = list(thumb_dir.glob("*.jpg"))
        assert len(delighted_files) == 2
        assert len(thumb_files) == 2

    def test_dl11_source_priority_equalized_chosen(self, mock_batch_with_equalized):
        """DL-11: Source priority -- equalized/ folder is chosen over color_calibrated/."""
        result = apply(str(mock_batch_with_equalized))
        assert result["success"] is True
        # The output_dir in the result confirms apply ran; verify it used equalized/
        # by checking that the source folder resolved to equalized
        source = _find_source_folder(Path(str(mock_batch_with_equalized)))
        assert source is not None
        assert source.name == "equalized", (
            f"Expected source folder 'equalized', got '{source.name}'"
        )

"""
Tests for straighten_service -- yarn skew/bow detection and correction.

Covers analyze (FFT skew + Hough bow), skew correction, bow correction,
and preview/apply integration with source folder priority.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts.processing.straighten_service import (
    analyze,
    preview,
    apply,
    _correct_skew,
    _correct_bow,
)


# ──────────────────────────────────────────────
# ST-01 through ST-06: Analyze
# ──────────────────────────────────────────────

class TestAnalyze:

    def test_st01_analyze_returns_expected_keys(self, synthetic_weave_image, save_temp_image):
        """ST-01: analyze returns dict with all required keys."""
        path = save_temp_image(synthetic_weave_image, "weave.tiff")
        result = analyze(image_path=path)
        assert result['success'] is True
        assert 'skew_angle_deg' in result
        assert 'max_weft_bow_px' in result
        assert 'max_warp_bow_px' in result
        assert 'bow_data' in result
        assert 'recommendation' in result

    def test_st02_analyze_missing_file(self):
        """ST-02: analyze returns failure on nonexistent file."""
        result = analyze(image_path=Path("/nonexistent/image.tiff"))
        assert result['success'] is False

    def test_st03_analyze_detects_known_rotation(self, synthetic_weave_image, save_temp_image):
        """ST-03: analyze detects skew on a 3-degree rotated weave image."""
        h, w = synthetic_weave_image.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 3.0, 1.0)
        rotated = cv2.warpAffine(synthetic_weave_image, M, (w, h), borderMode=cv2.BORDER_REFLECT_101)
        path = save_temp_image(rotated, "rotated_weave.tiff")
        result = analyze(image_path=path)
        # Should detect nonzero skew
        assert abs(result['skew_angle_deg']) > 0.5

    def test_st04_analyze_straight_image_low_skew(self, synthetic_weave_image, save_temp_image):
        """ST-04: straight weave image has near-zero skew."""
        path = save_temp_image(synthetic_weave_image, "straight_weave.tiff")
        result = analyze(image_path=path)
        assert abs(result['skew_angle_deg']) < 2.0

    def test_st05_analyze_direction_warp_only(self, synthetic_weave_image, save_temp_image):
        """ST-05: analyze with direction='warp' returns valid result."""
        path = save_temp_image(synthetic_weave_image, "weave.tiff")
        result = analyze(image_path=path, direction='warp')
        assert 'skew_angle_deg' in result

    def test_st06_analyze_direction_weft_only(self, synthetic_weave_image, save_temp_image):
        """ST-06: analyze with direction='weft' returns valid result."""
        path = save_temp_image(synthetic_weave_image, "weave.tiff")
        result = analyze(image_path=path, direction='weft')
        assert 'skew_angle_deg' in result


# ──────────────────────────────────────────────
# ST-07 through ST-10: Skew Correction
# ──────────────────────────────────────────────

class TestSkewCorrection:

    def test_st07_skew_correction_preserves_dtype_8bit(self, synthetic_image_8bit):
        """ST-07: _correct_skew preserves uint8 shape and dtype."""
        result = _correct_skew(synthetic_image_8bit, 2.0, strength=1.0)
        assert result.dtype == np.uint8
        assert result.shape == synthetic_image_8bit.shape

    def test_st08_skew_correction_preserves_dtype_16bit(self, synthetic_image_16bit):
        """ST-08: _correct_skew preserves uint16 shape and dtype."""
        result = _correct_skew(synthetic_image_16bit, 2.0, strength=1.0)
        assert result.dtype == np.uint16
        assert result.shape == synthetic_image_16bit.shape

    def test_st09_skew_zero_strength_unchanged(self, synthetic_image_8bit):
        """ST-09: strength=0 returns input unchanged."""
        result = _correct_skew(synthetic_image_8bit, 5.0, strength=0.0)
        np.testing.assert_array_equal(result, synthetic_image_8bit)

    def test_st10_skew_zero_angle_unchanged(self, synthetic_image_8bit):
        """ST-10: angle=0 returns input unchanged."""
        result = _correct_skew(synthetic_image_8bit, 0.0, strength=1.0)
        np.testing.assert_array_equal(result, synthetic_image_8bit)


# ──────────────────────────────────────────────
# ST-11 through ST-12: Bow Correction
# ──────────────────────────────────────────────

class TestBowCorrection:

    def test_st11_bow_correction_preserves_shape(self, synthetic_image_8bit):
        """ST-11: _correct_bow with zero displacement preserves shape."""
        bow_data = {
            'weft_data': [{'y_center': float(25 + i * 24), 'displacement': 0.0, 'median_angle': 0.0, 'line_count': 5} for i in range(20)],
            'warp_data': [{'x_center': float(25 + i * 24), 'displacement': 0.0, 'median_angle': 0.0, 'line_count': 5} for i in range(20)],
        }
        result = _correct_bow(synthetic_image_8bit, bow_data, strength=1.0, direction='both')
        assert result.shape == synthetic_image_8bit.shape

    def test_st12_bow_zero_displacement_unchanged(self, synthetic_image_8bit):
        """ST-12: zero displacement produces output close to original."""
        bow_data = {
            'weft_data': [{'y_center': float(25 + i * 24), 'displacement': 0.0, 'median_angle': 0.0, 'line_count': 5} for i in range(20)],
            'warp_data': [{'x_center': float(25 + i * 24), 'displacement': 0.0, 'median_angle': 0.0, 'line_count': 5} for i in range(20)],
        }
        result = _correct_bow(synthetic_image_8bit, bow_data, strength=1.0, direction='both')
        # Remap interpolation may cause tiny diffs
        assert np.allclose(result.astype(float), synthetic_image_8bit.astype(float), atol=2)


# ──────────────────────────────────────────────
# ST-13 through ST-16: Preview / Apply Integration
# ──────────────────────────────────────────────

class TestPreviewApply:

    def test_st13_preview_creates_output(self, mock_batch_dir):
        """ST-13: preview() returns success with before/after URLs."""
        result = preview(batch_path=mock_batch_dir)
        assert result['success'] is True
        assert 'before_url' in result
        assert 'after_url' in result
        preview_dir = mock_batch_dir / 'straighten_preview'
        assert preview_dir.exists()

    def test_st14_apply_creates_output_folder(self, mock_batch_dir):
        """ST-14: apply() creates straightened/ with processed images."""
        result = apply(batch_path=mock_batch_dir)
        assert result['success'] is True
        assert result['processed'] > 0
        straightened_dir = mock_batch_dir / 'straightened'
        assert straightened_dir.exists()
        assert any(straightened_dir.iterdir())

    def test_st15_apply_16bit(self, mock_batch_dir_16bit):
        """ST-15: apply() works with 16-bit input images."""
        result = apply(batch_path=mock_batch_dir_16bit)
        assert result['success'] is True

    def test_st16_preview_with_manual_angle(self, mock_batch_dir):
        """ST-16: preview() accepts manual_skew_angle override."""
        result = preview(batch_path=mock_batch_dir, manual_skew_angle=2.5)
        assert result['success'] is True

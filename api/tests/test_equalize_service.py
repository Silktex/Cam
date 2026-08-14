"""
Tests for Equalize Service — histogram equalization and exposure matching.

Covers CLAHE, histogram match, exposure match core functions,
plus preview/apply integration tests with mock batch directories.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

# Direct module import to avoid __init__.py dependency chain
_mod_path = Path(__file__).resolve().parents[1] / "scripts" / "processing" / "equalize_service.py"
_spec = importlib.util.spec_from_file_location("equalize_service", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

equalize_clahe = _mod.equalize_clahe
equalize_exposure_match = _mod.equalize_exposure_match
equalize_histogram_match = _mod.equalize_histogram_match
preview = _mod.preview
apply = _mod.apply
_compute_histogram = _mod._compute_histogram


# ──────────────────────────────────────────────
# EQ-01 through EQ-04: CLAHE Core Function
# ──────────────────────────────────────────────

class TestEqualizeCLAHE:

    def test_eq01_clahe_changes_pixels(self, synthetic_image_8bit):
        """EQ-01: CLAHE output differs from input (equalization applied)."""
        result = equalize_clahe(synthetic_image_8bit)
        assert not np.array_equal(result, synthetic_image_8bit), (
            "CLAHE should modify pixel values"
        )

    def test_eq02_clahe_preserves_uint8_dtype(self, synthetic_image_8bit):
        """EQ-02: CLAHE preserves uint8 dtype."""
        result = equalize_clahe(synthetic_image_8bit)
        assert result.dtype == np.uint8
        assert result.shape == synthetic_image_8bit.shape

    def test_eq03_clahe_preserves_uint16_dtype(self, synthetic_image_16bit):
        """EQ-03: CLAHE preserves uint16 dtype."""
        result = equalize_clahe(synthetic_image_16bit)
        assert result.dtype == np.uint16
        assert result.shape == synthetic_image_16bit.shape

    def test_eq04_clip_limit_affects_output(self, synthetic_image_8bit):
        """EQ-04: Different clip_limit values produce different outputs."""
        low = equalize_clahe(synthetic_image_8bit, clip_limit=0.5)
        high = equalize_clahe(synthetic_image_8bit, clip_limit=10.0)
        assert not np.array_equal(low, high), (
            "clip_limit=0.5 vs 10.0 should produce different results"
        )


# ──────────────────────────────────────────────
# EQ-05 through EQ-06: Histogram Match
# ──────────────────────────────────────────────

class TestEqualizeHistogramMatch:

    def test_eq05_histogram_match_shifts_mean_toward_reference(
        self, dark_source_image, bright_reference_image
    ):
        """EQ-05: histogram_match shifts source mean toward reference."""
        result = equalize_histogram_match(dark_source_image, bright_reference_image)
        src_mean = dark_source_image.mean()
        result_mean = result.mean()
        ref_mean = bright_reference_image.mean()
        # Result should be closer to reference than source was
        assert abs(result_mean - ref_mean) < abs(src_mean - ref_mean), (
            f"Result mean ({result_mean:.1f}) should be closer to reference "
            f"({ref_mean:.1f}) than source ({src_mean:.1f})"
        )

    @pytest.mark.parametrize("dtype,fixture_name", [
        (np.uint8, "synthetic_image_8bit"),
        (np.uint16, "synthetic_image_16bit"),
    ])
    def test_eq06_histogram_match_preserves_dtype(
        self, dtype, fixture_name, request
    ):
        """EQ-06: histogram_match preserves dtype for both 8-bit and 16-bit."""
        image = request.getfixturevalue(fixture_name)
        # Use a copy of the image as the reference
        reference = image.copy()
        result = equalize_histogram_match(image, reference)
        assert result.dtype == dtype


# ──────────────────────────────────────────────
# EQ-07 through EQ-08: Exposure Match
# ──────────────────────────────────────────────

class TestEqualizeExposureMatch:

    def test_eq07_exposure_match_normalizes_l_channel(
        self, dark_source_image, bright_reference_image
    ):
        """EQ-07: exposure_match normalizes L-channel mean within 10% of reference."""
        import cv2

        result = equalize_exposure_match(dark_source_image, bright_reference_image)

        # Convert to LAB and check L-channel mean
        ref_lab = cv2.cvtColor(bright_reference_image, cv2.COLOR_BGR2LAB)
        result_lab = cv2.cvtColor(result, cv2.COLOR_BGR2LAB)

        ref_l_mean = ref_lab[:, :, 0].mean()
        result_l_mean = result_lab[:, :, 0].mean()

        tolerance = ref_l_mean * 0.10
        assert abs(result_l_mean - ref_l_mean) <= tolerance, (
            f"Result L mean ({result_l_mean:.1f}) not within 10% of "
            f"reference L mean ({ref_l_mean:.1f})"
        )

    def test_eq08_exposure_match_handles_zero_mean(self, bright_reference_image):
        """EQ-08: exposure_match handles all-black source (zero L-mean) gracefully."""
        black_image = np.zeros((512, 512, 3), dtype=np.uint8)
        # Should not crash -- the function guards against zero-mean
        result = equalize_exposure_match(black_image, bright_reference_image)
        assert result.shape == black_image.shape
        assert result.dtype == np.uint8


# ──────────────────────────────────────────────
# EQ-09 through EQ-11: Preview Integration
# ──────────────────────────────────────────────

class TestEqualizePreview:

    def test_eq09_preview_returns_success(self, mock_batch_dir):
        """EQ-09: preview() returns success, URLs, and histograms with 256 bins."""
        result = preview(str(mock_batch_dir))
        assert result["success"] is True
        assert "before_url" in result
        assert "after_url" in result
        assert "before_histogram" in result
        assert "after_histogram" in result

        # Verify histogram structure: 256 bins for b, g, r, luminance
        for hist_key in ["before_histogram", "after_histogram"]:
            hist = result[hist_key]
            for channel in ["b", "g", "r", "luminance"]:
                assert channel in hist, f"Missing channel: {channel}"
                assert len(hist[channel]) == 256, (
                    f"{hist_key}[{channel}] should have 256 bins, got {len(hist[channel])}"
                )

    def test_eq10_preview_invalid_method(self, mock_batch_dir):
        """EQ-10: preview() with invalid method returns success=False."""
        result = preview(str(mock_batch_dir), method="nonexistent_method")
        assert result["success"] is False
        assert "error" in result

    def test_eq11_preview_histogram_match_without_reference(self, mock_batch_dir):
        """EQ-11: preview() histogram_match without reference returns error."""
        result = preview(str(mock_batch_dir), method="histogram_match")
        assert result["success"] is False
        assert "reference" in result["error"].lower() or "Reference" in result["error"]


# ──────────────────────────────────────────────
# EQ-12 through EQ-13: Apply Integration
# ──────────────────────────────────────────────

class TestEqualizeApply:

    def test_eq12_apply_processes_all_images(self, mock_batch_dir):
        """EQ-12: apply() processes all images and creates output dirs."""
        result = apply(str(mock_batch_dir))
        assert result["success"] is True
        assert result["processed"] == 2  # material_top + material_side1
        assert result["total"] == 2

        equalized_dir = mock_batch_dir / "equalized"
        thumb_dir = mock_batch_dir / "equalized_thumbnail"
        assert equalized_dir.exists(), "equalized/ dir should be created"
        assert thumb_dir.exists(), "equalized_thumbnail/ dir should be created"

        equalized_files = list(equalized_dir.glob("*.tiff"))
        thumb_files = list(thumb_dir.glob("*.jpg"))
        assert len(equalized_files) == 2
        assert len(thumb_files) == 2

    def test_eq13_apply_fallback_to_clahe_when_reference_missing(self, mock_batch_dir):
        """EQ-13: apply() falls back to CLAHE when reference is missing for match methods."""
        # Request histogram_match but do not provide reference_image
        result = apply(
            str(mock_batch_dir),
            method="histogram_match",
            reference_image=None,
        )
        # Should still succeed via CLAHE fallback
        assert result["success"] is True
        assert result["processed"] > 0


# ──────────────────────────────────────────────
# EQ-14: _compute_histogram
# ──────────────────────────────────────────────

class TestComputeHistogram:

    def test_eq14_compute_histogram_bins(self, synthetic_image_8bit):
        """EQ-14: _compute_histogram returns 256-bin arrays per channel."""
        hist = _compute_histogram(synthetic_image_8bit)
        for channel in ["b", "g", "r", "luminance"]:
            assert channel in hist
            assert len(hist[channel]) == 256, (
                f"Channel {channel} should have 256 bins"
            )
            # Values should be non-negative counts
            assert all(v >= 0 for v in hist[channel])

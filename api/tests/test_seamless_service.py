"""
Tests for seamless_service — make textures tile seamlessly.

SS-01 through SS-16: analyze_seams, make_seamless_*, preview, apply, helpers.
"""
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from scripts.processing.seamless_service import (
    analyze_seams,
    make_seamless_overlay,
    make_seamless_mirror,
    make_seamless_poisson,
    generate_tiled_preview,
    preview,
    apply,
    _get_source_folder,
)


# ──────────────────────────────────────────────
# analyze_seams() tests
# ──────────────────────────────────────────────


class TestAnalyzeSeams:
    """SS-01 through SS-03: seam analysis and edge scoring."""

    def test_ss01_analyze_seams_returns_scores(
        self, synthetic_image_8bit, save_temp_image
    ):
        """SS-01: analyze_seams returns success=True with 4 edge scores and overall."""
        path = save_temp_image(synthetic_image_8bit, "seam_test.tiff")
        result = analyze_seams(path)

        assert result["success"] is True
        scores = result["scores"]
        assert isinstance(scores["top"], float)
        assert isinstance(scores["bottom"], float)
        assert isinstance(scores["left"], float)
        assert isinstance(scores["right"], float)
        assert all(v >= 0 for v in scores.values())
        assert "overall_score" in result
        assert isinstance(result["overall_score"], float)

    def test_ss02_analyze_seams_clamps_blend_width(self, save_temp_image):
        """SS-02: analyze_seams clamps blend_width to h//4 for small image."""
        small = np.full((256, 256, 3), 128, dtype=np.uint8)
        path = save_temp_image(small, "small_seam.tiff")
        result = analyze_seams(path, blend_width=200)

        assert result["success"] is True
        # 256 // 4 = 64, which is less than 200, so clamped
        assert result["blend_width"] == 64

    def test_ss03_analyze_seams_nonexistent_file(self, tmp_path):
        """SS-03: analyze_seams returns failure for nonexistent path."""
        fake_path = tmp_path / "no_such_file.tiff"
        result = analyze_seams(fake_path)

        assert result["success"] is False
        assert "error" in result


# ──────────────────────────────────────────────
# make_seamless_overlay() tests
# ──────────────────────────────────────────────


class TestMakeSeamlessOverlay:
    """SS-04 through SS-07: overlay blending method."""

    def test_ss04_overlay_preserves_uint8(self, synthetic_image_8bit):
        """SS-04: make_seamless_overlay preserves uint8 dtype and shape."""
        result = make_seamless_overlay(synthetic_image_8bit)

        assert result.dtype == np.uint8
        assert result.shape == synthetic_image_8bit.shape

    def test_ss05_overlay_preserves_uint16(self, synthetic_image_16bit):
        """SS-05: make_seamless_overlay preserves uint16 dtype and shape."""
        result = make_seamless_overlay(synthetic_image_16bit)

        assert result.dtype == np.uint16
        assert result.shape == synthetic_image_16bit.shape

    def test_ss06_overlay_spots_removal(self, synthetic_image_8bit):
        """SS-06: make_seamless_overlay with spots_removal=True runs without crash."""
        result = make_seamless_overlay(
            synthetic_image_8bit, spots_removal=True
        )

        assert result.dtype == np.uint8
        assert result.shape == synthetic_image_8bit.shape

    def test_ss07_overlay_color_equalizer(self, synthetic_image_8bit):
        """SS-07: make_seamless_overlay with color_equalizer=5 runs without crash."""
        result = make_seamless_overlay(
            synthetic_image_8bit, color_equalizer=5
        )

        assert result.dtype == np.uint8
        assert result.shape == synthetic_image_8bit.shape


# ──────────────────────────────────────────────
# make_seamless_mirror() tests
# ──────────────────────────────────────────────


class TestMakeSeamlessMirror:
    """SS-08 through SS-09: mirror blending method."""

    @pytest.mark.parametrize("fixture_name", ["8bit", "16bit"])
    def test_ss08_mirror_preserves_shape(
        self, fixture_name, synthetic_image_8bit, synthetic_image_16bit
    ):
        """SS-08: make_seamless_mirror preserves shape for both bit depths."""
        img = synthetic_image_8bit if fixture_name == "8bit" else synthetic_image_16bit
        result = make_seamless_mirror(img)

        assert result.shape == img.shape
        assert result.dtype == img.dtype

    def test_ss09_mirror_seam_quality(
        self, synthetic_image_8bit, save_temp_image
    ):
        """SS-09: mirror method does not dramatically worsen seam score."""
        path = save_temp_image(synthetic_image_8bit, "mirror_input.tiff")
        original_result = analyze_seams(path)

        mirror_out = make_seamless_mirror(synthetic_image_8bit)
        mirror_path = save_temp_image(mirror_out, "mirror_output.tiff")
        mirror_result = analyze_seams(mirror_path)

        # The mirror output should not be dramatically worse
        # Allow 3x tolerance — the method may not always improve, but
        # should not catastrophically degrade either
        assert mirror_result["overall_score"] < original_result["overall_score"] * 3


# ──────────────────────────────────────────────
# make_seamless_poisson() tests
# ──────────────────────────────────────────────


class TestMakeSeamlessPoisson:
    """SS-10 through SS-11: Poisson blending method."""

    def test_ss10_poisson_returns_valid_output(self, synthetic_image_8bit):
        """SS-10: make_seamless_poisson returns valid output (shape, dtype)."""
        result = make_seamless_poisson(synthetic_image_8bit)

        assert result.shape == synthetic_image_8bit.shape
        assert result.dtype == synthetic_image_8bit.dtype

    def test_ss11_poisson_fallback_to_mirror_on_cv2_error(
        self, synthetic_image_8bit
    ):
        """SS-11: Poisson falls back to mirror method when cv2.seamlessClone raises."""
        with patch("scripts.processing.seamless_service.cv2.seamlessClone") as mock_clone:
            mock_clone.side_effect = cv2.error("Mock seamlessClone failure")

            result = make_seamless_poisson(synthetic_image_8bit)

            # Should still produce valid output via mirror fallback
            assert result.shape == synthetic_image_8bit.shape
            assert result.dtype == synthetic_image_8bit.dtype
            mock_clone.assert_called_once()


# ──────────────────────────────────────────────
# preview() tests
# ──────────────────────────────────────────────


class TestPreview:
    """SS-12 through SS-13: seamless preview generation."""

    def test_ss12_preview_generates_files(self, mock_batch_dir):
        """SS-12: preview generates 3 preview files and returns expected keys."""
        result = preview(mock_batch_dir, method='overlay')

        assert result["success"] is True
        assert "preview_url" in result
        assert "tiled_url" in result
        assert "original_url" in result
        assert "seam_scores" in result

        # Verify 3 files written
        preview_dir = mock_batch_dir / "seamless_preview"
        assert preview_dir.exists()
        jpg_files = list(preview_dir.glob("*.jpg"))
        assert len(jpg_files) == 3

    @pytest.mark.parametrize("method", ["overlay", "mirror", "poisson"])
    def test_ss13_preview_all_methods(self, mock_batch_dir, method):
        """SS-13: preview works for all 3 methods."""
        result = preview(mock_batch_dir, method=method)

        assert result["success"] is True
        assert "preview_url" in result
        assert result["width"] > 0
        assert result["height"] > 0


# ──────────────────────────────────────────────
# apply() tests
# ──────────────────────────────────────────────


class TestApply:
    """SS-14: batch seamless application."""

    def test_ss14_apply_creates_output_dirs_and_files(self, mock_batch_dir):
        """SS-14: apply creates seamless/ + seamless_thumbnail/ with correct file counts."""
        result = apply(mock_batch_dir, method='overlay')

        assert result["success"] is True
        assert result["processed"] == result["total"]

        seamless_dir = mock_batch_dir / "seamless"
        thumb_dir = mock_batch_dir / "seamless_thumbnail"

        assert seamless_dir.exists()
        assert thumb_dir.exists()

        tiff_files = list(seamless_dir.glob("*.tiff"))
        jpg_files = list(thumb_dir.glob("*.jpg"))

        assert len(tiff_files) == result["processed"]
        assert len(jpg_files) == result["processed"]


# ──────────────────────────────────────────────
# generate_tiled_preview() tests
# ──────────────────────────────────────────────


class TestGenerateTiledPreview:
    """SS-15: tiled preview scaling."""

    def test_ss15_tiled_preview_scales_down(self):
        """SS-15: generate_tiled_preview scales down when result > 3200px total."""
        # 1200x1200 with tile_count=3 would be 3600px without scaling
        large = np.full((1200, 1200, 3), 128, dtype=np.uint8)
        tiled = generate_tiled_preview(large, tile_count=3)

        # Max total is 3200, so each tile should be scaled to ~1066
        # Result should be <= 3200 in each dimension
        assert tiled.shape[0] <= 3200
        assert tiled.shape[1] <= 3200

        # Should still be tiled (larger than one tile after scaling)
        assert tiled.shape[0] > 1200  # must be multi-tiled
        assert tiled.shape[1] > 1200


# ──────────────────────────────────────────────
# Source priority tests
# ──────────────────────────────────────────────


class TestSourcePriority:
    """SS-16: source folder priority for seamless service."""

    def test_ss16_perspective_corrected_chosen(self, mock_batch_with_perspective):
        """SS-16: when perspective_corrected/ exists, it is chosen as source."""
        folder, name = _get_source_folder(mock_batch_with_perspective)

        assert name == "perspective_corrected"
        assert folder == mock_batch_with_perspective / "perspective_corrected"

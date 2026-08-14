"""
Tests for perspective_service — detect lines and apply perspective correction.

PS-01 through PS-14: detect_lines, preview, apply, internal helpers.
"""
import numpy as np
import pytest

from pathlib import Path

from scripts.processing.perspective_service import (
    detect_lines,
    preview,
    apply,
    _get_source_folder,
    _find_top_image,
    _compute_dest_rect,
)


# ──────────────────────────────────────────────
# detect_lines() tests
# ──────────────────────────────────────────────


class TestDetectLines:
    """PS-01 through PS-04: Hough line detection and fallback behaviour."""

    def test_ps01_detect_lines_returns_suggested_corners(
        self, synthetic_image_with_lines, save_temp_image
    ):
        """PS-01: detect_lines returns suggested_corners for image with clear lines."""
        path = save_temp_image(synthetic_image_with_lines, "lines_image.tiff")
        result = detect_lines(path)

        assert result["success"] is True
        assert result["method"] == "hough"
        assert len(result["suggested_corners"]) == 4

        h, w = synthetic_image_with_lines.shape[:2]
        for corner in result["suggested_corners"]:
            assert 0 <= corner["x"] <= w
            assert 0 <= corner["y"] <= h

    def test_ps02_detect_lines_fallback_for_flat_image(self, save_temp_image):
        """PS-02: detect_lines falls back to 5% inset for featureless gray image."""
        flat = np.full((600, 800, 3), 128, dtype=np.uint8)
        path = save_temp_image(flat, "flat_gray.tiff")
        result = detect_lines(path)

        assert result["success"] is True
        assert result["method"] == "fallback"
        assert len(result["suggested_corners"]) == 4
        assert result["detected_lines"] == []

        # Verify 5% inset corners
        h, w = 600, 800
        margin = 0.05
        expected_tl = {"x": int(w * margin), "y": int(h * margin)}
        assert result["suggested_corners"][0] == expected_tl

    def test_ps03_detect_lines_nonexistent_path(self, tmp_path):
        """PS-03: detect_lines returns success=False for nonexistent file."""
        fake_path = tmp_path / "nonexistent.tiff"
        result = detect_lines(fake_path)

        assert result["success"] is False
        assert "error" in result

    def test_ps04_detect_lines_handles_16bit(
        self, synthetic_image_16bit, save_temp_image
    ):
        """PS-04: detect_lines handles 16-bit image without crashing."""
        path = save_temp_image(synthetic_image_16bit, "image_16bit.tiff")
        result = detect_lines(path)

        # Should not crash — either hough or fallback
        assert result["success"] is True
        assert len(result["suggested_corners"]) == 4


# ──────────────────────────────────────────────
# preview() tests
# ──────────────────────────────────────────────


class TestPreview:
    """PS-05 through PS-08: perspective preview generation."""

    @pytest.fixture
    def valid_source_points(self):
        """Source points covering most of the 512x512 test image."""
        return [
            {"x": 50, "y": 50},    # TL
            {"x": 460, "y": 50},   # TR
            {"x": 460, "y": 460},  # BR
            {"x": 50, "y": 460},   # BL
        ]

    def test_ps05_preview_valid_source_points(
        self, mock_batch_dir, valid_source_points
    ):
        """PS-05: preview with valid source_points returns success, preview_url, dimensions."""
        result = preview(mock_batch_dir, valid_source_points)

        assert result["success"] is True
        assert "preview_url" in result
        assert result["width"] > 0
        assert result["height"] > 0

    def test_ps06_preview_tiny_output_fails(self, mock_batch_dir):
        """PS-06: preview with tiny quadrilateral (<10px output) returns success=False."""
        tiny_points = [
            {"x": 100, "y": 100},
            {"x": 105, "y": 100},
            {"x": 105, "y": 105},
            {"x": 100, "y": 105},
        ]
        result = preview(mock_batch_dir, tiny_points)

        assert result["success"] is False
        assert "too small" in result["error"].lower()

    def test_ps07_preview_empty_batch_fails(self, empty_batch_dir):
        """PS-07: preview with no source folder returns success=False."""
        points = [
            {"x": 50, "y": 50},
            {"x": 400, "y": 50},
            {"x": 400, "y": 400},
            {"x": 50, "y": 400},
        ]
        result = preview(empty_batch_dir, points)

        assert result["success"] is False
        assert "error" in result

    def test_ps08_preview_custom_dest_points(
        self, mock_batch_dir, valid_source_points
    ):
        """PS-08: preview with custom dest_points uses those points."""
        dest_points = [
            {"x": 0, "y": 0},
            {"x": 300, "y": 0},
            {"x": 300, "y": 300},
            {"x": 0, "y": 300},
        ]
        result = preview(mock_batch_dir, valid_source_points, dest_points=dest_points)

        assert result["success"] is True
        assert result["width"] == 300
        assert result["height"] == 300


# ──────────────────────────────────────────────
# apply() tests
# ──────────────────────────────────────────────


class TestApply:
    """PS-09 through PS-10: batch perspective correction."""

    @pytest.fixture
    def source_points(self):
        return [
            {"x": 50, "y": 50},
            {"x": 460, "y": 50},
            {"x": 460, "y": 460},
            {"x": 50, "y": 460},
        ]

    def test_ps09_apply_writes_tiff_and_thumbnails(
        self, mock_batch_dir, source_points
    ):
        """PS-09: apply writes TIFF + JPG thumbnail, creates output directories."""
        result = apply(mock_batch_dir, source_points)

        assert result["success"] is True
        assert result["processed"] == result["total"]

        output_dir = mock_batch_dir / "perspective_corrected"
        thumb_dir = mock_batch_dir / "perspective_corrected_thumbnail"

        assert output_dir.exists()
        assert thumb_dir.exists()

        tiff_files = list(output_dir.glob("*.tiff"))
        jpg_files = list(thumb_dir.glob("*.jpg"))

        assert len(tiff_files) == result["processed"]
        assert len(jpg_files) == result["processed"]

    def test_ps10_apply_corrupt_file_partial_processing(
        self, mock_batch_dir, source_points
    ):
        """PS-10: apply with corrupt 0-byte file reports error, processes others."""
        # Find source folder and add a corrupt file
        source_folder, _ = _get_source_folder(mock_batch_dir)
        corrupt = source_folder / "corrupt_image.tiff"
        corrupt.write_bytes(b"")  # 0-byte corrupt file

        result = apply(mock_batch_dir, source_points)

        assert result["success"] is True
        assert result["processed"] < result["total"]
        assert len(result["errors"]) > 0


# ──────────────────────────────────────────────
# Internal helper tests
# ──────────────────────────────────────────────


class TestHelpers:
    """PS-11 through PS-14: internal utility functions."""

    def test_ps11_get_source_folder_priority(self, mock_batch_dir):
        """PS-11: _get_source_folder respects priority: color_calibrated > cropped > tiff."""
        folder, name = _get_source_folder(mock_batch_dir)
        assert name == "color_calibrated"

        # Remove color_calibrated, should fall back to cropped
        import shutil
        shutil.rmtree(mock_batch_dir / "color_calibrated")

        folder, name = _get_source_folder(mock_batch_dir)
        assert name == "cropped"

        # Remove cropped, should fall back to tiff
        shutil.rmtree(mock_batch_dir / "cropped")

        folder, name = _get_source_folder(mock_batch_dir)
        assert name == "tiff"

    def test_ps12_find_top_image_by_name(self, tmp_path):
        """PS-12: _find_top_image finds filename containing '_top'."""
        files = [
            tmp_path / "material_side1.tiff",
            tmp_path / "material_top.tiff",
            tmp_path / "material_side2.tiff",
        ]
        for f in files:
            f.touch()

        result = _find_top_image(files)
        assert result is not None
        assert "_top" in result.name.lower()

    def test_ps13_find_top_image_fallback_to_first(self, tmp_path):
        """PS-13: _find_top_image falls back to first image when no '_top' match."""
        files = [
            tmp_path / "material_side1.tiff",
            tmp_path / "material_side2.tiff",
        ]
        for f in files:
            f.touch()

        result = _find_top_image(files)
        assert result == files[0]

    def test_ps14_compute_dest_rect(self):
        """PS-14: _compute_dest_rect produces correct rectangle for known quadrilateral."""
        source_points = [
            {"x": 0, "y": 0},      # TL
            {"x": 200, "y": 0},    # TR
            {"x": 200, "y": 100},  # BR
            {"x": 0, "y": 100},    # BL
        ]
        dst, out_w, out_h = _compute_dest_rect(source_points)

        assert out_w == 200
        assert out_h == 100
        assert dst.shape == (4, 2)

        # Verify corner ordering: TL, TR, BR, BL
        np.testing.assert_array_almost_equal(dst[0], [0, 0])
        np.testing.assert_array_almost_equal(dst[1], [200, 0])
        np.testing.assert_array_almost_equal(dst[2], [200, 100])
        np.testing.assert_array_almost_equal(dst[3], [0, 100])

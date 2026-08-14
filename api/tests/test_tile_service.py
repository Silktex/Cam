"""
Tests for Tile Service — tiled texture preview generation and export.

Covers generate_tiled_preview core function with various parameters,
plus preview/apply integration with source folder priority.
"""
import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# Direct module import to avoid __init__.py dependency chain
_mod_path = Path(__file__).resolve().parents[1] / "scripts" / "processing" / "tile_service.py"
_spec = importlib.util.spec_from_file_location("tile_service", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

generate_tiled_preview = _mod.generate_tiled_preview
preview = _mod.preview
apply = _mod.apply
_find_source_folder = _mod._find_source_folder


# ──────────────────────────────────────────────
# TS-01 through TS-07: generate_tiled_preview Core
# ──────────────────────────────────────────────

class TestGenerateTiledPreview:

    def test_ts01_default_output_size(self, synthetic_image_8bit):
        """TS-01: Default output size matches output_size param (1200x1200)."""
        result = generate_tiled_preview(synthetic_image_8bit, output_size=(1200, 1200))
        assert result.shape[0] == 1200, f"Height should be 1200, got {result.shape[0]}"
        assert result.shape[1] == 1200, f"Width should be 1200, got {result.shape[1]}"

    def test_ts02_scale_half_still_full_canvas(self, synthetic_image_8bit):
        """TS-02: scale=0.5 still produces full output_size canvas."""
        result = generate_tiled_preview(
            synthetic_image_8bit, scale=0.5, output_size=(1200, 1200)
        )
        assert result.shape[0] == 1200
        assert result.shape[1] == 1200

    def test_ts03_tiny_scale_returns_input(self, synthetic_image_8bit):
        """TS-03: scale=0.001 produces tile <1px, returns input image (early return)."""
        result = generate_tiled_preview(synthetic_image_8bit, scale=0.001)
        # When tile dimensions round to <1, function returns original image
        assert np.array_equal(result, synthetic_image_8bit)

    def test_ts04_rotation_applies_without_crash(self, synthetic_image_8bit):
        """TS-04: rotation=45 applies without crash and output has correct dims."""
        result = generate_tiled_preview(
            synthetic_image_8bit, rotation=45.0, output_size=(1200, 1200)
        )
        assert result.shape[0] == 1200
        assert result.shape[1] == 1200
        assert result.dtype == synthetic_image_8bit.dtype

    def test_ts05_overlap_compresses_step(self, synthetic_image_8bit):
        """TS-05: overlap=0.25 compresses step (more tiles visible)."""
        # With overlap, tiles are placed closer together, resulting in more
        # non-zero pixels covered.  Compare with no overlap.
        no_overlap = generate_tiled_preview(
            synthetic_image_8bit, overlap=0.0, output_size=(1200, 1200)
        )
        with_overlap = generate_tiled_preview(
            synthetic_image_8bit, overlap=0.25, output_size=(1200, 1200)
        )
        # Both should be 1200x1200 -- the overlap affects tile placement density
        assert no_overlap.shape == with_overlap.shape
        # The outputs should differ because tile placement differs
        assert not np.array_equal(no_overlap, with_overlap), (
            "overlap=0.25 should produce different tiling than overlap=0.0"
        )

    def test_ts06_half_drop_offsets_odd_rows(self, synthetic_image_8bit):
        """TS-06: half_drop=True offsets odd rows (pixel content differs)."""
        normal = generate_tiled_preview(
            synthetic_image_8bit, half_drop=False, output_size=(1200, 1200)
        )
        half_drop = generate_tiled_preview(
            synthetic_image_8bit, half_drop=True, output_size=(1200, 1200)
        )
        assert not np.array_equal(normal, half_drop), (
            "half_drop=True should shift odd rows, producing different output"
        )

    def test_ts07_offset_x_shifts_tile_positions(self, synthetic_image_8bit):
        """TS-07: offset_x=0.5 shifts tile positions vs offset_x=0."""
        no_offset = generate_tiled_preview(
            synthetic_image_8bit, offset_x=0.0, output_size=(1200, 1200)
        )
        with_offset = generate_tiled_preview(
            synthetic_image_8bit, offset_x=0.5, output_size=(1200, 1200)
        )
        assert not np.array_equal(no_offset, with_offset), (
            "offset_x=0.5 should shift tile positions"
        )


# ──────────────────────────────────────────────
# TS-08 through TS-09: Preview Integration
# ──────────────────────────────────────────────

class TestTilePreview:

    def test_ts08_preview_valid_batch(self, mock_batch_dir):
        """TS-08: preview() with valid batch returns success and creates tiled_preview/ dir."""
        result = preview(str(mock_batch_dir))
        assert result["success"] is True
        assert "preview_url" in result
        assert "source_image" in result

        preview_dir = mock_batch_dir / "tiled_preview"
        assert preview_dir.exists(), "tiled_preview/ dir should be created"
        preview_files = list(preview_dir.glob("*.jpg"))
        assert len(preview_files) >= 1, "Should have at least one preview image"

    def test_ts09_preview_empty_batch(self, empty_batch_dir):
        """TS-09: preview() with empty batch returns success=False."""
        result = preview(str(empty_batch_dir))
        assert result["success"] is False
        assert "error" in result


# ──────────────────────────────────────────────
# TS-10 through TS-12: Apply Integration
# ──────────────────────────────────────────────

class TestTileApply:

    def test_ts10_apply_exports_tiff_and_thumbnail(self, mock_batch_dir):
        """TS-10: apply() exports TIFF + JPG thumbnail in tiled/ and tiled_thumbnail/."""
        result = apply(str(mock_batch_dir))
        assert result["success"] is True
        assert result["processed"] == 1

        tiled_dir = mock_batch_dir / "tiled"
        thumb_dir = mock_batch_dir / "tiled_thumbnail"
        assert tiled_dir.exists(), "tiled/ dir should be created"
        assert thumb_dir.exists(), "tiled_thumbnail/ dir should be created"

        tiff_files = list(tiled_dir.glob("*.tiff"))
        jpg_files = list(thumb_dir.glob("*.jpg"))
        assert len(tiff_files) == 1, "Should have 1 TIFF export"
        assert len(jpg_files) == 1, "Should have 1 JPG thumbnail"

    def test_ts11_apply_output_resolution(self, mock_batch_dir):
        """TS-11: apply() with output_resolution=(4096,4096) produces correctly sized output."""
        result = apply(str(mock_batch_dir), output_resolution=(4096, 4096))
        assert result["success"] is True
        assert result["resolution"] == [4096, 4096]

        # Verify the actual TIFF file dimensions
        tiled_dir = mock_batch_dir / "tiled"
        tiff_files = list(tiled_dir.glob("*.tiff"))
        assert len(tiff_files) == 1

        exported = cv2.imread(str(tiff_files[0]), cv2.IMREAD_UNCHANGED)
        assert exported is not None
        assert exported.shape[0] == 4096, f"Height should be 4096, got {exported.shape[0]}"
        assert exported.shape[1] == 4096, f"Width should be 4096, got {exported.shape[1]}"

    def test_ts12_source_priority_seamless_chosen(self, mock_batch_with_seamless):
        """TS-12: Source priority -- seamless/ folder is chosen over color_calibrated/."""
        result = apply(str(mock_batch_with_seamless))
        assert result["success"] is True

        source = _find_source_folder(Path(str(mock_batch_with_seamless)))
        assert source is not None
        assert source.name == "seamless", (
            f"Expected source folder 'seamless', got '{source.name}'"
        )

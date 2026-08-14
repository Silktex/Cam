"""
Tests for Clone Service -- inpainting and clone stamp for cleaning material textures.

Covers inpaint (telea/navier-stokes), 16-bit preservation, mask decoding,
clone stamp operations, preview/apply integration, and source priority.
"""
import base64

import cv2
import numpy as np
import pytest

from scripts.processing.clone_service import (
    inpaint,
    clone_stamp,
    preview_inpaint,
    preview_stamp,
    apply,
    _decode_mask,
)


# ──────────────────────────────────────────────
# CL-01 through CL-05: Inpaint Core
# ──────────────────────────────────────────────

class TestInpaint:

    def test_cl01_telea_modifies_masked_region(
        self, image_with_red_square, mask_for_red_square, save_temp_image
    ):
        """CL-01: inpaint() with telea modifies masked region (pixels changed)."""
        img_path = save_temp_image(image_with_red_square, "red_square.tiff")
        result = inpaint(str(img_path), mask_for_red_square, method="telea")
        assert result is not None
        # The red square region (200:300, 200:300) should be different after inpainting
        original_region = image_with_red_square[200:300, 200:300]
        result_region = result[200:300, 200:300]
        assert not np.array_equal(original_region, result_region), (
            "Inpainted region should differ from original red square"
        )

    def test_cl02_navier_stokes_modifies_masked_region(
        self, image_with_red_square, mask_for_red_square, save_temp_image
    ):
        """CL-02: inpaint() with navier-stokes modifies masked region."""
        img_path = save_temp_image(image_with_red_square, "red_square_ns.tiff")
        result = inpaint(str(img_path), mask_for_red_square, method="navier-stokes")
        assert result is not None
        original_region = image_with_red_square[200:300, 200:300]
        result_region = result[200:300, 200:300]
        assert not np.array_equal(original_region, result_region), (
            "Navier-Stokes inpaint should modify the masked region"
        )

    def test_cl03_preserves_16bit_output(
        self, synthetic_image_16bit, base64_mask_data, save_temp_image
    ):
        """CL-03: inpaint() preserves 16-bit output (uint16 in -> uint16 out)."""
        img_path = save_temp_image(synthetic_image_16bit, "img16.tiff")
        result = inpaint(str(img_path), base64_mask_data)
        assert result is not None
        assert result.dtype == np.uint16, (
            f"Expected uint16 output, got {result.dtype}"
        )

    def test_cl04_invalid_image_path_returns_none(self, base64_mask_data):
        """CL-04: inpaint() returns None for invalid image path."""
        result = inpaint("/nonexistent/path/image.tiff", base64_mask_data)
        assert result is None

    def test_cl05_invalid_base64_mask_returns_none(
        self, synthetic_image_8bit, save_temp_image
    ):
        """CL-05: inpaint() returns None for invalid base64 mask."""
        img_path = save_temp_image(synthetic_image_8bit, "img.tiff")
        result = inpaint(str(img_path), "not_valid_base64!!!")
        assert result is None


# ──────────────────────────────────────────────
# CL-06 through CL-07: _decode_mask
# ──────────────────────────────────────────────

class TestDecodeMask:

    def test_cl06_strips_data_url_prefix(
        self, base64_mask_data, base64_mask_data_with_prefix
    ):
        """CL-06: _decode_mask() strips data:image/png;base64, prefix correctly."""
        target_shape = (512, 512)

        mask_no_prefix = _decode_mask(base64_mask_data, target_shape)
        mask_with_prefix = _decode_mask(base64_mask_data_with_prefix, target_shape)

        assert mask_no_prefix is not None
        assert mask_with_prefix is not None
        assert np.array_equal(mask_no_prefix, mask_with_prefix), (
            "Mask decoded with prefix should equal mask decoded without prefix"
        )

    def test_cl07_resizes_mask_to_target_shape(self):
        """CL-07: _decode_mask() resizes mask to target shape (100x100 mask -> 512x512)."""
        # Create a small 100x100 mask
        small_mask = np.zeros((100, 100), dtype=np.uint8)
        cv2.circle(small_mask, (50, 50), 20, 255, -1)
        _, png_buf = cv2.imencode('.png', small_mask)
        b64 = base64.b64encode(png_buf.tobytes()).decode('utf-8')

        # Decode targeting 512x512
        result = _decode_mask(b64, (512, 512))
        assert result is not None
        assert result.shape == (512, 512), (
            f"Expected (512, 512), got {result.shape}"
        )


# ──────────────────────────────────────────────
# CL-08 through CL-11: clone_stamp Core
# ──────────────────────────────────────────────

class TestCloneStamp:

    def test_cl08_copies_source_to_target(
        self, synthetic_image_8bit, save_temp_image
    ):
        """CL-08: clone_stamp() copies source to target position (target region changes)."""
        img_path = save_temp_image(synthetic_image_8bit, "stamp_src.tiff")
        source_pos = {"x": 100, "y": 100}
        target_pos = {"x": 300, "y": 300}

        result = clone_stamp(str(img_path), source_pos, target_pos, radius=25)
        assert result is not None

        # Target region should have changed
        original_target = synthetic_image_8bit[275:326, 275:326]
        result_target = result[275:326, 275:326]
        assert not np.array_equal(original_target, result_target), (
            "Target region should change after clone stamp"
        )

    def test_cl09_mirror_differs_from_no_mirror(
        self, synthetic_image_8bit, save_temp_image
    ):
        """CL-09: clone_stamp() mirror=True differs from mirror=False output."""
        img_path = save_temp_image(synthetic_image_8bit, "stamp_mirror.tiff")
        source_pos = {"x": 100, "y": 256}
        target_pos = {"x": 400, "y": 256}

        no_mirror = clone_stamp(
            str(img_path), source_pos, target_pos, radius=25, mirror=False
        )
        mirror = clone_stamp(
            str(img_path), source_pos, target_pos, radius=25, mirror=True
        )
        assert no_mirror is not None
        assert mirror is not None
        assert not np.array_equal(no_mirror, mirror), (
            "Mirror=True should produce different output than mirror=False"
        )

    def test_cl10_fade_blends_with_background(
        self, synthetic_image_8bit, save_temp_image
    ):
        """CL-10: clone_stamp() fade=0.5 blends with background (not pure copy)."""
        img_path = save_temp_image(synthetic_image_8bit, "stamp_fade.tiff")
        source_pos = {"x": 100, "y": 100}
        target_pos = {"x": 300, "y": 300}

        full_fade = clone_stamp(
            str(img_path), source_pos, target_pos, radius=25, fade=1.0
        )
        half_fade = clone_stamp(
            str(img_path), source_pos, target_pos, radius=25, fade=0.5
        )
        assert full_fade is not None
        assert half_fade is not None
        assert not np.array_equal(full_fade, half_fade), (
            "fade=0.5 should produce blended (different) output vs fade=1.0"
        )

    def test_cl11_clamps_to_image_boundaries(
        self, synthetic_image_8bit, save_temp_image
    ):
        """CL-11: clone_stamp() clamps to image boundaries (source near edge, no crash)."""
        img_path = save_temp_image(synthetic_image_8bit, "stamp_edge.tiff")
        # Place source at very edge of 512x512 image
        source_pos = {"x": 5, "y": 5}
        target_pos = {"x": 256, "y": 256}

        result = clone_stamp(str(img_path), source_pos, target_pos, radius=25)
        assert result is not None, "Should not crash when source is near edge"
        assert result.shape == synthetic_image_8bit.shape


# ──────────────────────────────────────────────
# CL-12 through CL-13: Preview Integration
# ──────────────────────────────────────────────

class TestPreview:

    def test_cl12_preview_inpaint_returns_success(
        self, mock_batch_dir, base64_mask_data
    ):
        """CL-12: preview_inpaint() returns success=True + preview_url."""
        result = preview_inpaint(str(mock_batch_dir), base64_mask_data)
        assert result["success"] is True
        assert "preview_url" in result
        assert "inpaint_preview.jpg" in result["preview_url"]

    def test_cl13_preview_stamp_returns_success(self, mock_batch_dir):
        """CL-13: preview_stamp() returns success=True + preview_url."""
        result = preview_stamp(
            str(mock_batch_dir),
            source_pos={"x": 100, "y": 100},
            target_pos={"x": 300, "y": 300},
            radius=25,
        )
        assert result["success"] is True
        assert "preview_url" in result
        assert "stamp_preview.jpg" in result["preview_url"]


# ──────────────────────────────────────────────
# CL-14 through CL-16: Apply Integration
# ──────────────────────────────────────────────

class TestApply:

    def test_cl14_chains_inpaint_and_stamp(
        self, mock_batch_dir, base64_mask_data
    ):
        """CL-14: apply() chains inpaint + stamp operations (operations_applied >= 2)."""
        operations = [
            {
                "type": "inpaint",
                "mask_data": base64_mask_data,
                "method": "telea",
                "radius": 3,
            },
            {
                "type": "stamp",
                "source_pos": {"x": 100, "y": 100},
                "target_pos": {"x": 300, "y": 300},
                "radius": 25,
                "fade": 0.8,
                "blur_mask": 0.3,
                "mirror": False,
            },
        ]
        result = apply(str(mock_batch_dir), operations)
        assert result["success"] is True
        assert result["operations_applied"] >= 2, (
            f"Expected at least 2 operations applied, got {result['operations_applied']}"
        )

    def test_cl15_empty_operations_list(self, mock_batch_dir):
        """CL-15: apply() handles empty operations list (operations_applied=0)."""
        result = apply(str(mock_batch_dir), [])
        assert result["success"] is True
        assert result["operations_applied"] == 0

    def test_cl16_skips_invalid_operation_type(self, mock_batch_dir):
        """CL-16: apply() skips invalid operation type (operations_applied=0 for unknown type)."""
        operations = [
            {"type": "nonexistent_operation"},
        ]
        result = apply(str(mock_batch_dir), operations)
        assert result["success"] is True
        assert result["operations_applied"] == 0, (
            "Unknown operation type should be skipped"
        )


# ──────────────────────────────────────────────
# CL-17: Source Priority
# ──────────────────────────────────────────────

class TestSourcePriority:

    def test_cl17_seamless_folder_chosen_first(self, mock_batch_with_seamless):
        """CL-17: Source priority -- seamless/ is chosen over color_calibrated/cropped/tiff."""
        from scripts.processing.clone_service import _find_source_folder
        from pathlib import Path

        source = _find_source_folder(Path(str(mock_batch_with_seamless)))
        assert source is not None
        assert source.name == "seamless", (
            f"Expected seamless/ to be chosen, got {source.name}"
        )

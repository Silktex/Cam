"""
Tests for Validate Service -- PBR map validation and analysis.

Covers albedo validation (pass/fail/heatmap), metallic validation,
get_stats(), generate_overlay(), and _find_pbr_map() internal helper.
"""
import numpy as np
import pytest

from scripts.processing.validate_service import (
    validate_albedo,
    validate_metallic,
    get_stats,
    generate_overlay,
    _find_pbr_map,
)


# ──────────────────────────────────────────────
# VL-01 through VL-05: Albedo Validation
# ──────────────────────────────────────────────

class TestValidateAlbedo:

    def test_vl01_mid_range_albedo_passes(self, mock_batch_with_pbr):
        """VL-01: validate_albedo() passes for mid-range albedo map (mean ~128)."""
        result = validate_albedo(str(mock_batch_with_pbr))
        assert result["success"] is True
        assert result["passed"] is True
        assert result["stats"]["dark_pixels_pct"] < 5, (
            f"Expected dark_pct < 5, got {result['stats']['dark_pixels_pct']}"
        )
        # Mean should be somewhere around 128
        assert 90 < result["stats"]["mean"] < 170, (
            f"Expected mean near 128, got {result['stats']['mean']}"
        )

    def test_vl02_dark_albedo_fails(self, mock_batch_dark_albedo):
        """VL-02: validate_albedo() fails for very dark map (mean ~10)."""
        result = validate_albedo(str(mock_batch_dark_albedo))
        assert result["success"] is True
        assert result["passed"] is False, (
            "Very dark albedo map should fail validation"
        )

    def test_vl03_albedo_generates_overlay(self, mock_batch_with_pbr):
        """VL-03: validate_albedo() generates heatmap overlay file."""
        result = validate_albedo(str(mock_batch_with_pbr))
        assert result["success"] is True
        assert "overlay_url" in result
        assert "albedo_overlay.jpg" in result["overlay_url"]
        # Verify the overlay file was actually created
        overlay_path = mock_batch_with_pbr / "validate_preview" / "albedo_overlay.jpg"
        assert overlay_path.exists(), "Overlay JPEG should be written to disk"

    def test_vl04_custom_dark_threshold(self, mock_batch_with_pbr):
        """VL-04: validate_albedo() with custom dark_threshold=100 changes stats."""
        default = validate_albedo(str(mock_batch_with_pbr), dark_threshold=30)
        custom = validate_albedo(str(mock_batch_with_pbr), dark_threshold=100)
        assert custom["stats"]["dark_threshold"] == 100
        assert default["stats"]["dark_threshold"] == 30
        # Higher threshold flags more dark pixels
        assert custom["stats"]["dark_pixels_pct"] >= default["stats"]["dark_pixels_pct"], (
            "Higher dark_threshold should flag at least as many dark pixels"
        )

    def test_vl05_histogram_has_luminance_256_bins(self, mock_batch_with_pbr):
        """VL-05: validate_albedo() histogram has luminance key with 256 bins."""
        result = validate_albedo(str(mock_batch_with_pbr))
        assert result["success"] is True
        hist = result["histogram"]
        assert "luminance" in hist, "Histogram must contain 'luminance' key"
        assert len(hist["luminance"]) == 256, (
            f"Expected 256 luminance bins, got {len(hist['luminance'])}"
        )


# ──────────────────────────────────────────────
# VL-06 through VL-08: Metallic Validation
# ──────────────────────────────────────────────

class TestValidateMetallic:

    def test_vl06_binary_metallic_passes(self, mock_batch_with_pbr):
        """VL-06: validate_metallic() passes for binary metallic map (half 0, half 255)."""
        result = validate_metallic(str(mock_batch_with_pbr))
        assert result["success"] is True
        assert result["passed"] is True
        assert result["stats"]["ambiguous_pct"] < 10, (
            f"Binary map should have low ambiguous_pct, got {result['stats']['ambiguous_pct']}"
        )

    def test_vl07_gray_metallic_fails(self, mock_batch_gray_metallic):
        """VL-07: validate_metallic() fails for uniform gray map (128, high ambiguous_pct)."""
        result = validate_metallic(str(mock_batch_gray_metallic))
        assert result["success"] is True
        assert result["passed"] is False, (
            "Uniform gray metallic map should fail (high ambiguous_pct)"
        )
        assert result["stats"]["ambiguous_pct"] > 50, (
            f"Expected high ambiguous_pct for gray map, got {result['stats']['ambiguous_pct']}"
        )

    def test_vl08_missing_metallic_returns_passed(self, mock_batch_dark_albedo):
        """VL-08: validate_metallic() returns passed=True when no metallic map exists."""
        # mock_batch_dark_albedo has only an albedo map, no metallic
        result = validate_metallic(str(mock_batch_dark_albedo))
        assert result["passed"] is True, (
            "Missing metallic map should be OK for non-metallic materials"
        )


# ──────────────────────────────────────────────
# VL-09 through VL-10: get_stats()
# ──────────────────────────────────────────────

class TestGetStats:

    def test_vl09_returns_per_map_stats_with_albedo(self, mock_batch_with_pbr):
        """VL-09: get_stats() returns per-map statistics with at least albedo key."""
        result = get_stats(str(mock_batch_with_pbr))
        assert result["success"] is True
        assert "maps" in result
        assert "albedo" in result["maps"], "stats must include albedo map"
        albedo_stats = result["maps"]["albedo"]
        assert "filename" in albedo_stats
        assert "histogram" in albedo_stats

    def test_vl10_handles_grayscale_maps(self, mock_batch_with_pbr):
        """VL-10: get_stats() handles grayscale (single-channel) maps gracefully.

        The roughness/height maps in our fixture are saved as BGR but
        get_stats() should still produce valid per-channel stats.
        """
        result = get_stats(str(mock_batch_with_pbr))
        assert result["success"] is True
        # Verify we got stats for at least some maps
        assert len(result["maps"]) >= 2, (
            f"Expected at least 2 maps, got {len(result['maps'])}"
        )
        # Each map entry should have histogram with luminance
        for map_type, stats in result["maps"].items():
            assert "histogram" in stats, f"Missing histogram for {map_type}"
            assert "luminance" in stats["histogram"], (
                f"Missing luminance histogram for {map_type}"
            )


# ──────────────────────────────────────────────
# VL-11: generate_overlay()
# ──────────────────────────────────────────────

class TestGenerateOverlay:

    def test_vl11_routes_albedo_and_metallic(self, mock_batch_with_pbr):
        """VL-11: generate_overlay() routes correctly for both albedo and metallic modes."""
        albedo_result = generate_overlay(str(mock_batch_with_pbr), mode="albedo")
        assert albedo_result["success"] is True
        assert albedo_result["map_type"] == "albedo"

        metallic_result = generate_overlay(str(mock_batch_with_pbr), mode="metallic")
        assert metallic_result["success"] is True
        assert metallic_result["map_type"] == "metallic"

        # Unknown mode returns error
        unknown_result = generate_overlay(str(mock_batch_with_pbr), mode="unknown")
        assert unknown_result["success"] is False


# ──────────────────────────────────────────────
# VL-12: _find_pbr_map()
# ──────────────────────────────────────────────

class TestFindPbrMap:

    def test_vl12_matches_keyword_variants(self, mock_batch_with_pbr):
        """VL-12: _find_pbr_map() matches keyword variants (albedo, diffuse, etc.)."""
        from pathlib import Path

        pbr_folder = mock_batch_with_pbr / "pbr_grayscale"

        # The fixture has 'material_albedo.png' -- the keyword 'albedo' should match
        found = _find_pbr_map(pbr_folder, "albedo")
        assert found is not None, "Should find albedo map"
        assert "albedo" in found.name.lower()

        # 'metallic' keyword should find 'material_metallic.png'
        found_metal = _find_pbr_map(pbr_folder, "metallic")
        assert found_metal is not None, "Should find metallic map"
        assert "metallic" in found_metal.name.lower()

        # 'normal' keyword should find 'material_normal.png'
        found_normal = _find_pbr_map(pbr_folder, "normal")
        assert found_normal is not None, "Should find normal map"

        # Non-existent map type returns None
        found_none = _find_pbr_map(pbr_folder, "emissive")
        assert found_none is None, "Non-existent map type should return None"


# ──────────────────────────────────────────────
# VL-13: No PBR folder error
# ──────────────────────────────────────────────

class TestNoPbrFolder:

    def test_vl13_no_pbr_folder_returns_error(self, empty_batch_dir):
        """VL-13: No PBR folder returns error for validate functions."""
        albedo_result = validate_albedo(str(empty_batch_dir))
        assert albedo_result["success"] is False
        assert "error" in albedo_result

        metallic_result = validate_metallic(str(empty_batch_dir))
        assert metallic_result["success"] is False

        stats_result = get_stats(str(empty_batch_dir))
        assert stats_result["success"] is False

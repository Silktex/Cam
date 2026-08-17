"""
Unit tests for the processing service modules extracted from the router
(app/services/processing_{crop,calibration,pbr,tools}_service.py).

Complements test_processing_characterization.py (which pins HTTP behavior
through TestClient) by exercising the service functions directly at their
own boundary.
"""
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from fastapi import HTTPException

sys.modules.setdefault("gphoto2", MagicMock())
sys.modules.setdefault("aiohttp", MagicMock())

from app.services import (
    processing_calibration_service as calibration,
    processing_crop_service as crop,
    processing_pbr_service as pbr,
    processing_tools_service as tools,
)


def _crop_result(success=True, error=None):
    return SimpleNamespace(
        success=success, source_path="/s.ARW",
        output_path="/o.tiff" if success else None,
        error=error, bbox=[1, 1, 2, 2] if success else None,
    )


class TestCropServiceSummaries:

    def test_apply_crop_counts_and_strips_per_result_bbox(self, tmp_path):
        with patch("scripts.processing.crop_service.CropService") as cls_:
            cls_.return_value.apply_crop_to_all.return_value = [
                _crop_result(), _crop_result(False, "dark")]
            out = crop.apply_crop("B", tmp_path, [0, 0, 9, 9], "manual", None, 0)
        assert out["success"] is True
        assert out["processed"] == 1 and out["total"] == 2
        assert all("bbox" not in r for r in out["results"])
        assert out["results"][1]["error"] == "dark"

    def test_apply_crop_auto_keeps_bbox_per_result(self, tmp_path):
        detect = {"success": True, "bbox": [5, 5, 500, 500]}
        with patch("scripts.processing.crop_service.CropService") as cls_:
            cls_.return_value.apply_crop_to_all.return_value = [
                _crop_result(), _crop_result(False)]
            out = crop.apply_auto_crop("B", tmp_path, detect)
        assert out["bbox"] == [5, 5, 500, 500]
        assert out["results"][0]["bbox"] == [1, 1, 2, 2]
        assert out["results"][1]["bbox"] is None
        assert out["success"] is True

    def test_apply_crop_converts_four_points_to_dicts(self, tmp_path):
        pts = [SimpleNamespace(x=float(i), y=float(i)) for i in range(4)]
        with patch("scripts.processing.crop_service.CropService") as cls_:
            cls_.return_value.apply_crop_to_all.return_value = []
            crop.apply_crop("B", tmp_path, None, "manual", pts, 15)
        assert cls_.return_value.apply_crop_to_all.call_args.kwargs == {
            "batch_path": str(tmp_path), "bbox": None, "crop_type": "manual",
            "points": [{"x": float(i), "y": float(i)} for i in range(4)],
            "rotation": 15,
        }

    def test_get_top_image_none_becomes_500(self, tmp_path):
        with patch("scripts.processing.crop_service.CropService") as cls_:
            cls_.return_value.get_top_image_for_crop.return_value = None
            with pytest.raises(HTTPException) as ei:
                crop.get_top_image(tmp_path)
        assert ei.value.status_code == 500
        assert "No images found in batch" in str(ei.value.detail)

    def test_auto_detect_uses_gpu_setting(self, tmp_path):
        with patch("scripts.processing.crop_service.CropService") as cls_:
            cls_.return_value.auto_detect_crop.return_value = {"success": True}
            out = crop.auto_detect(tmp_path, 2048)
        assert out == {"success": True}
        cls_.assert_called_once_with(use_gpu=False)


class TestCropServiceReconvert:

    def _raw(self, tmp_path, names=("a.ARW",)):
        raw = tmp_path / "raw"
        raw.mkdir(parents=True)
        for n in names:
            (raw / n).write_bytes(b"")
        return raw

    def test_happy_counts_and_creates_tiff_dir(self, tmp_path):
        self._raw(tmp_path, ("a.ARW", "b.ARW"))
        with patch("scripts.processing.raw_utils.load_raw", return_value="R"), \
             patch("scripts.processing.raw_utils.save_tiff", return_value=True):
            out = crop.reconvert_tiff(tmp_path, None)
        assert out == {"fixed_wb": None, "success": 2, "failed": 0, "total": 2,
                       "files": [{"name": "a.ARW", "status": "ok"},
                                 {"name": "b.ARW", "status": "ok"}]}
        assert (tmp_path / "tiff").is_dir()

    def test_checker_missing_raises_404(self, tmp_path):
        self._raw(tmp_path)
        with pytest.raises(HTTPException) as ei:
            crop.reconvert_tiff(tmp_path, "/gone.ARW")
        assert ei.value.status_code == 404


class TestCalibrationService:

    def test_resolve_requires_profile_or_image(self):
        with patch("scripts.processing.calibration_service.CalibrationService"), \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            with pytest.raises(HTTPException) as ei:
                calibration.resolve_checker_data(None, None)
        assert ei.value.status_code == 400

    def test_resolve_missing_profile_404(self):
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.load_colorchecker_profile.return_value = None
            with pytest.raises(HTTPException) as ei:
                calibration.resolve_checker_data("GONE", None)
        assert ei.value.status_code == 404
        assert ei.value.detail == "Profile not found: GONE"

    def test_calibrate_summary(self, tmp_path):
        svc = MagicMock()
        svc.calibrate_batch.return_value = [
            SimpleNamespace(success=True, source_path="/s", output_path="/o", error=None),
            SimpleNamespace(success=False, source_path="/s2", output_path=None, error="x"),
        ]
        out = calibration.calibrate(svc, tmp_path, object(), None)
        assert out["success"] is True
        assert out["processed"] == 1 and out["total"] == 2
        assert out["batch_name"] == tmp_path.name

    def test_list_profiles_error_goes_in_band(self):
        with patch("scripts.processing.calibration_service.CalibrationService") as cls_, \
             patch("scripts.processing.calibration_service.COLOUR_AVAILABLE", True):
            cls_.return_value.list_profiles.side_effect = RuntimeError("fs")
            out = calibration.list_profiles()
        assert out == {"profiles": [], "error": "fs"}


class TestPbrService:

    def test_generate_flow_status_sequence_and_shape(self, tmp_path):
        request = SimpleNamespace(batch_name="B", mode="grayscale",
                                  selected_images=None)
        updates = []

        def update(*a, **kw):
            updates.append((a, kw))

        bg = MagicMock()
        with patch("scripts.processing.pbr_service.PBRService") as cls_:
            cls_.return_value.generate.return_value = SimpleNamespace(
                success=True, images_processed=9, outputs=["a.png"], error=None)
            out = pbr.generate_flow(request, tmp_path, bg, update, lambda n: None)
        assert out == {"success": True, "batch_name": "B", "mode": "grayscale",
                       "images_processed": 9, "outputs": ["a.png"], "error": None}
        assert updates == [
            (("B", "pbr", "in_progress"), {"pbr_mode": "grayscale"}),
            (("B", "pbr", "completed"), {"pbr_mode": "grayscale"}),
        ]
        bg.add_task.assert_called_once()

    def test_generate_flow_invalid_mode_400_before_status(self, tmp_path):
        request = SimpleNamespace(batch_name="B", mode="turbo", selected_images=None)
        with pytest.raises(HTTPException) as ei:
            pbr.generate_flow(request, tmp_path, MagicMock(),
                              lambda *a, **k: pytest.fail("status touched"), None)
        assert ei.value.status_code == 400

    def test_preview_maps_png_preferred(self, tmp_path, monkeypatch):
        from app.config import settings as app_settings
        monkeypatch.setattr(app_settings, "CAPTURES_DIR", tmp_path)
        gs = tmp_path / "B" / "pbr_grayscale"
        gs.mkdir(parents=True)
        (gs / "albedo.png").write_bytes(b"")
        (gs / "albedo.tiff").write_bytes(b"")
        out = pbr.preview_maps(tmp_path / "B", "B")
        assert out["grayscale"] == {"albedo": "/media/captures/B/pbr_grayscale/albedo.png"}
        assert out["colored"] is None

    def test_preview_maps_nothing_404(self, tmp_path):
        with pytest.raises(HTTPException) as ei:
            pbr.preview_maps(tmp_path, "B")
        assert ei.value.status_code == 404


class TestToolsService:

    def test_find_top_image_prefers_top_named(self, tmp_path):
        tiff = tmp_path / "tiff"
        tiff.mkdir()
        (tiff / "a_side.tiff").write_bytes(b"")
        (tiff / "b_top.tiff").write_bytes(b"")
        assert tools.find_top_image_for_tool(tmp_path, "perspective") == tiff / "b_top.tiff"

    def test_find_top_image_missing_404(self, tmp_path):
        with pytest.raises(HTTPException) as ei:
            tools.find_top_image_for_tool(tmp_path, "perspective")
        assert ei.value.status_code == 404
        assert ei.value.detail == "No source images found for this tool"

    def test_tools_status_output_subfolder_counts(self, tmp_path):
        out = tmp_path / "output" / "tiled"
        out.mkdir(parents=True)
        (out / "a.png").write_bytes(b"")
        status = tools.tools_status(tmp_path, "B")
        assert status["tiled"] is True
        assert status["seamless"] is False

    def test_pipeline_folders_flags(self, tmp_path):
        (tmp_path / "raw").mkdir()
        folders = tools.pipeline_folders(tmp_path)
        assert folders == {"tiff": False, "raw": True, "cropped": False,
                           "color_calibrated": False, "pbr_grayscale": False,
                           "pbr_colored": False}

    def test_get_tool_image_priority_walk(self, tmp_path):
        cropped = tmp_path / "cropped"
        cropped.mkdir()
        (cropped / "mat_top.tiff").write_bytes(b"")
        info = tools.get_tool_image(tmp_path, "B", "equalize")
        assert info["source_folder"] == "cropped"
        assert info["filename"] == "mat_top.tiff"
        assert info["preview_url"] == "/media/captures/B/cropped/mat_top.tiff"

    def test_seamless_analyze_blend_width_zero_quirk(self, tmp_path):
        tiff = tmp_path / "tiff"
        tiff.mkdir()
        (tiff / "mat_top.tiff").write_bytes(b"")
        request = SimpleNamespace(batch_name="B", blend_width=0)
        with patch("scripts.processing.seamless_service.analyze_seams",
                   return_value={"diff": 1}) as ans:
            out = tools.seamless_analyze(request, tmp_path)
        ans.assert_called_once_with(image_path=tiff / "mat_top.tiff", blend_width=128)
        assert out == {"diff": 1, "batch_name": "B"}

    def test_tile_apply_default_resolution(self, tmp_path):
        request = SimpleNamespace(
            batch_name="B", tile_x=2, tile_y=2, offset_x=0.0, offset_y=0.0,
            scale=1.0, rotation=0.0, overlap=0.0, half_drop=False,
            output_resolution=None)
        with patch("scripts.processing.tile_service.apply", return_value={}) as ap:
            tools.tile_apply(request, tmp_path)
        assert ap.call_args.kwargs["output_resolution"] == (2048, 2048)

    def test_validate_check_failed_subcheck_excluded(self, tmp_path):
        request = SimpleNamespace(batch_name="B", albedo_dark_threshold=30.0,
                                  metal_range=None)
        with patch("scripts.processing.validate_service.validate_albedo",
                   return_value={"success": False, "passed": False}), \
             patch("scripts.processing.validate_service.validate_metallic",
                   return_value={"success": True, "passed": True}):
            out = tools.validate_check(request, tmp_path)
        assert out["all_passed"] is True
        assert out["checks"][0] == {"map": "albedo", "success": False, "passed": False}

    def test_straighten_analyze_injects_batch_name(self, tmp_path):
        tiff = tmp_path / "tiff"
        tiff.mkdir()
        (tiff / "mat_top.tiff").write_bytes(b"")
        request = SimpleNamespace(batch_name="B", grid_divisions=20, direction="both")
        with patch("scripts.processing.straighten_service.analyze",
                   return_value={"skew": 0.5}) as an:
            out = tools.straighten_analyze(request, tmp_path)
        assert out == {"skew": 0.5, "batch_name": "B"}
        an.assert_called_once_with(image_path=tiff / "mat_top.tiff",
                                   grid_divisions=20, direction="both")
